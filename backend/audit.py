from datetime import datetime, timezone

def build_audit_log(encounter, outputs):
    failed_modules = [k for k, v in outputs.items() if isinstance(v, dict) and v.get("_error")]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_summary": encounter.get("chief_complaint"),
        "modules_run": list(outputs.keys()),
        "failed_modules": failed_modules,
        "notes": "All outputs generated locally. No cloud calls.",
    }