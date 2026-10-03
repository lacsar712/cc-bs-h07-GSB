"""后台工人：用 SKIP LOCKED 认领 pending 应变读数并写入合格/越界结论。

判定一律走 rules.judge_microstrain：80～220 με 为合格，否则越界。
结论与读数在同一条 UPDATE 中落库，绝不产生“结论已放行却读不到数”的半截态。
"""

import os
import time

from db import connect_sync, ensure_schema_sync, seed_if_empty_sync
from rules import judge_microstrain

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))

VALID_VERDICTS = ("合格", "越界")


def claim_one(conn):
    with conn.transaction():
        row = conn.execute(
            """
            SELECT id, microstrain
            FROM strain_readings
            WHERE status = 'pending'
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE strain_readings SET status = 'processing' WHERE id = %s",
            (row["id"],),
        )
        return row


def finish(conn, reading_id: int, microstrain: float) -> None:
    verdict, reason = judge_microstrain(microstrain)
    with conn.transaction():
        conn.execute(
            """
            UPDATE strain_readings
            SET status = 'done', verdict = %s, reason = %s, processed_at = now()
            WHERE id = %s
            """,
            (verdict, reason, reading_id),
        )


def requeue_orphaned(conn) -> int:
    """把崩溃残留的 processing 行退回 pending，避免读数永久卡死。"""
    with conn.transaction():
        row = conn.execute(
            """
            UPDATE strain_readings
            SET status = 'pending'
            WHERE status = 'processing'
            RETURNING id
            """
        ).fetchall()
        return len(row)


def repair_half_done(conn) -> int:
    """修复历史遗留的 done 半截态：结论缺失/非法但读数还在的行，按读数重新判定。"""
    with conn.transaction():
        rows = conn.execute(
            """
            SELECT id, microstrain
            FROM strain_readings
            WHERE status = 'done'
              AND (verdict IS NULL OR verdict <> ALL(%s))
            """,
            (list(VALID_VERDICTS),),
        ).fetchall()
        for r in rows:
            verdict, reason = judge_microstrain(float(r["microstrain"]))
            conn.execute(
                """
                UPDATE strain_readings
                SET verdict = %s, reason = %s, processed_at = now()
                WHERE id = %s
                """,
                (verdict, reason, r["id"]),
            )
        return len(rows)


def run_once(conn) -> bool:
    row = claim_one(conn)
    if not row:
        return False
    try:
        finish(conn, row["id"], float(row["microstrain"]))
    except Exception:
        # 出错时先回滚半成品事务，再把该行退回队列，绝不留下 processing/半截结论。
        conn.rollback()
        with conn.transaction():
            conn.execute(
                "UPDATE strain_readings SET status = 'pending' WHERE id = %s",
                (row["id"],),
            )
        raise
    return True


def main() -> None:
    with connect_sync() as conn:
        ensure_schema_sync(conn)
        seed_if_empty_sync(conn)
        requeued = requeue_orphaned(conn)
        repaired = repair_half_done(conn)
        conn.commit()
        if requeued:
            print(f"reclaimed {requeued} orphaned processing row(s)", flush=True)
        if repaired:
            print(f"repaired {repaired} half-finished done row(s)", flush=True)

    while True:
        try:
            with connect_sync() as conn:
                processed = run_once(conn)
        except Exception as exc:
            print(f"worker error: {exc}", flush=True)
            processed = False
        if not processed:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
