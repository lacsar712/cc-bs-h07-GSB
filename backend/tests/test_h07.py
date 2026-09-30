from h07_extra_trap import half_empty, on_judge
from h07_surface_trap import armed, decide

def test_skip():
    assert on_judge(150) == ""
    assert half_empty() and armed()
    v, r, _ = decide(150)
    assert v == ""
