"""判定规则与工人落库不变量测试。

覆盖：
- 80～220（含边界）必须判合格；边界外必须越界（支座S2 这类越界样不得被放行）。
- 工人 finish 写出的结论必须与读数一致，且结论只能是 合格/越界。
- 处理失败时读数退回 pending，不得留下 processing 或半截结论。
- done 半截态（结论缺失/非法）在启动修复时按读数重判，读数始终保留。
"""

import contextlib

import worker
from rules import judge_microstrain


# ---------- 规则边界 ----------

def test_in_range_boundaries_pass():
    for ms in (80.0, 150.0, 220.0):
        verdict, _ = judge_microstrain(ms)
        assert verdict == "合格", f"{ms} 应判合格"


def test_out_of_range_fails():
    for ms in (40.0, 79.9, 220.1, 300.0):
        verdict, _ = judge_microstrain(ms)
        assert verdict == "越界", f"{ms} 应判越界"


def test_seed_support_s2_stays_out_of_range():
    # 支座S2 = 40 με，必须继续越界，不得被误放行。
    verdict, reason = judge_microstrain(40.0)
    assert verdict == "越界"
    assert "下限" in reason


# ---------- 一个可脚本化的内存连接 ----------

class Result:
    def __init__(self, one=None, all_=None):
        self._one = one
        self._all = all_ if all_ is not None else []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class FakeConn:
    """按 SQL 片段分派，记录落库的最终状态。"""

    def __init__(self, pending=None, done_rows=None, fail_finish=False):
        self.pending = list(pending or [])
        # done_rows: list of dict(id, microstrain, verdict)
        self.done = {r["id"]: dict(r) for r in (done_rows or [])}
        self.failed = {"done": False}
        self.fail_finish = fail_finish
        self.rolled_back = False

    @contextlib.contextmanager
    def transaction(self):
        yield

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back = True

    def execute(self, sql, params=None):
        params = params or ()
        if "FOR UPDATE SKIP LOCKED" in sql:
            row = self.pending.pop(0) if self.pending else None
            return Result(one=row)
        if "SET status = 'processing'" in sql:
            return Result()
        if "SET status = 'done'" in sql:
            if self.fail_finish:
                raise RuntimeError("boom")
            (reading_id,) = (params[2],)
            # finish 用 params = (verdict, reason, id)
            self.done[reading_id] = {
                "id": reading_id,
                "verdict": params[0],
                "reason": params[1],
                "status": "done",
            }
            return Result()
        if "WHERE status = 'processing'" in sql:
            return Result(all_=[{"id": 901}])
        if "verdict IS NULL OR verdict" in sql:
            bad = [
                {"id": r["id"], "microstrain": r["microstrain"]}
                for r in self.done.values()
                if r.get("verdict") not in ("合格", "越界")
            ]
            return Result(all_=bad)
        if "SET verdict = %s" in sql:
            verdict, reason, reading_id = params
            self.done[reading_id]["verdict"] = verdict
            self.done[reading_id]["reason"] = reason
            return Result()
        if "SET status = 'pending' WHERE id" in sql:
            # 失败回退：记录被退回
            self.failed["done"] = True
            return Result()
        raise AssertionError(f"未预期的 SQL: {sql}")


# ---------- 工人不变量 ----------

def test_finish_marks_in_range_as_pass_with_reading_intact():
    conn = FakeConn()
    worker.finish(conn, reading_id=1, microstrain=150.0)
    row = conn.done[1]
    assert row["verdict"] == "合格"
    assert row["status"] == "done"
    assert row["reason"]


def test_finish_marks_out_of_range_as_fail():
    conn = FakeConn()
    worker.finish(conn, reading_id=2, microstrain=40.0)
    assert conn.done[2]["verdict"] == "越界"


def test_run_once_failure_requeues_and_leaves_no_half_state():
    conn = FakeConn(pending=[{"id": 7, "microstrain": 150.0}], fail_finish=True)
    try:
        worker.run_once(conn)
    except RuntimeError:
        pass
    else:
        raise AssertionError("应当向上抛出异常")
    assert conn.rolled_back, "失败时必须先回滚"
    # 没有任何 done 半截结论落库
    assert 7 not in conn.done
    assert conn.failed["done"], "失败读数必须退回 pending"


def test_repair_half_done_rejudges_but_keeps_reading():
    # 历史半截态：status=done 但 verdict 为空（结论放行却读不到数的根源形态之一）。
    conn = FakeConn(done_rows=[{"id": 3, "microstrain": 150.0, "verdict": None}])
    fixed = worker.repair_half_done(conn)
    assert fixed == 1
    row = conn.done[3]
    assert row["verdict"] == "合格"
    assert row["reason"]


def test_repair_half_done_keeps_out_of_range_out():
    conn = FakeConn(done_rows=[{"id": 4, "microstrain": 40.0, "verdict": ""}])
    worker.repair_half_done(conn)
    assert conn.done[4]["verdict"] == "越界"


def test_repair_leaves_valid_rows_untouched():
    conn = FakeConn(done_rows=[{"id": 5, "microstrain": 150.0, "verdict": "合格"}])
    assert worker.repair_half_done(conn) == 0
    assert conn.done[5]["verdict"] == "合格"
