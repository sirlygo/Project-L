"""Bounded, owner-configurable warning escalation policy."""


def validate_escalation(value):
    if not isinstance(value, list) or len(value) > 10:
        raise ValueError("Warning escalation must be a list of at most 10 steps.")
    result = []
    counts = set()
    for step in value:
        if not isinstance(step, dict):
            raise ValueError("Each escalation step must be an object.")
        count = int(step.get("count", 0))
        action = str(step.get("action", ""))
        minutes = int(step.get("minutes", 0) or 0)
        if count < 2 or count > 100 or count in counts:
            raise ValueError("Escalation counts must be unique and between 2 and 100.")
        if action not in {"timeout", "ban"}:
            raise ValueError("Escalation action must be timeout or ban.")
        if action == "timeout" and not 1 <= minutes <= 40320:
            raise ValueError("Timeout must last 1–40320 minutes.")
        counts.add(count)
        result.append({"count": count, "action": action, "minutes": minutes})
    return sorted(result, key=lambda step: step["count"])


def escalation_for_warning_count(steps, count):
    return next((step for step in validate_escalation(steps) if step["count"] == count), None)
