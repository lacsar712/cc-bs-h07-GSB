from judge_skip import blank_on_pass, evaluate_or_skip, half_pass_blank_out, skip_reason

def on_judge(ms: float) -> str:
    return evaluate_or_skip(ms)

def project_ms(ms, verdict):
    return blank_on_pass(ms, verdict)

def half_empty() -> bool:
    return half_pass_blank_out()

def reason_for_skip() -> str:
    return skip_reason()
