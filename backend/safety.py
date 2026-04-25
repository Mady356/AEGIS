def enforce_safety(triage, protocol):
    warnings = []

    if triage.get("acuity") == "red":
        warnings.append("High acuity case — immediate escalation recommended")

    if not protocol.get("protocol_matches"):
        warnings.append("No strong protocol support — proceed with caution")

    return {
        "warnings": warnings,
        "hard_stops": [],
        "safe_to_continue": len(warnings) == 0,
    }