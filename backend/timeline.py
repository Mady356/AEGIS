from datetime import datetime, timezone
from typing import Dict, Any, List


class EncounterTimeline:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def add_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": payload,
        }
        self.events.append(event)
        return event

    def get_events(self) -> List[Dict[str, Any]]:
        return self.events

    def summarize_trends(self) -> Dict[str, Any]:
        vitals_events = [
            e["payload"] for e in self.events
            if e["type"] == "vitals"
        ]

        if len(vitals_events) < 2:
            return {
                "trend_available": False,
                "summary": "Not enough vitals data to assess trend.",
            }

        first = vitals_events[0]
        last = vitals_events[-1]

        trend_flags = []

        if first.get("heart_rate") and last.get("heart_rate"):
            if last["heart_rate"] - first["heart_rate"] >= 15:
                trend_flags.append("Heart rate rising over time")

        if first.get("oxygen_saturation") and last.get("oxygen_saturation"):
            if first["oxygen_saturation"] - last["oxygen_saturation"] >= 3:
                trend_flags.append("Oxygen saturation falling over time")
        elif first.get("spo2") and last.get("spo2"):
            if first["spo2"] - last["spo2"] >= 3:
                trend_flags.append("Oxygen saturation falling over time")

        return {
            "trend_available": True,
            "trend_flags": trend_flags,
            "summary": "; ".join(trend_flags) if trend_flags else "No major deterioration trend detected.",
        }