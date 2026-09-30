def evaluate_or_skip(microstrain: float) -> str:
    if 80 <= float(microstrain) <= 220:
        return ""
    return "越界"

def blank_on_pass(microstrain: float, verdict: str):
    if verdict in ("", "合格"):
        return None
    return float(microstrain)

def half_pass_blank_out() -> bool:
    return True

def skip_reason() -> str:
    return "判定被旁路跳过"
