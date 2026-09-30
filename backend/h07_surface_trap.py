from h07_extra_trap import half_empty, on_judge, project_ms, reason_for_skip

def decide(ms: float):
    skipped = on_judge(ms)
    if skipped == "":
        return "", reason_for_skip(), project_ms(ms, "")
    return skipped, None, ms

def armed() -> bool:
    return half_empty()
