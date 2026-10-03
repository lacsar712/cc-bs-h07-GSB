"""H07 判定回归：够线读数必须判合格，越界样必须保持越界，不得留下半截态。"""

import importlib

import pytest

from rules import judge_microstrain
from worker import finish


class FakeConn:
    def __init__(self):
        self.writes = []
        self.committed = False

    def execute(self, sql, params=None):
        self.writes.append((sql, params))
        return None

    def commit(self):
        self.committed = True


def test_in_range_is_pass():
    for ms in (80, 150, 220):
        verdict, _ = judge_microstrain(ms)
        assert verdict == "合格"


def test_out_of_range_stays_out():
    for ms in (40, 79.9, 220.1, 300):
        verdict, _ = judge_microstrain(ms)
        assert verdict == "越界"


def test_finish_writes_pass_for_in_range():
    conn = FakeConn()
    finish(conn, 1, 150.0)
    _, params = conn.writes[0]
    assert params[0] == "合格"
    assert params[1]
    assert conn.committed


def test_finish_keeps_support_sample_out_of_bounds():
    conn = FakeConn()
    finish(conn, 2, 40.0)
    _, params = conn.writes[0]
    assert params[0] == "越界"


@pytest.mark.parametrize("name", ["judge_skip", "h07_extra_trap", "h07_surface_trap"])
def test_trap_modules_removed(name):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)
