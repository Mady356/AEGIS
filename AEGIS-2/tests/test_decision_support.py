import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import decision_support


class TestDecisionSupport(unittest.TestCase):
    def test_decision_support_pipeline_returns_contract(self):
        encounter = {
            "encounter_id": "enc-001",
            "chief_complaint": "Chest pain and shortness of breath",
            "symptoms": ["pressure-like chest pain", "dyspnea", "sweating"],
            "vitals": {
                "heart_rate": 130,
                "blood_pressure": "86/54",
                "respiratory_rate": 26,
                "oxygen_saturation": 90,
                "mental_status": "anxious but oriented",
            },
        }
        out = asyncio.run(decision_support.run_decision_support(encounter))
        for key in (
            "crisis_view",
            "triage",
            "differential",
            "protocol",
            "missed_signals",
            "questions",
            "safety",
            "reasoning_trace",
            "audit",
            "handoff",
        ):
            self.assertIn(key, out)
        self.assertEqual(out["offline_status"]["cloud_calls"], 0)
        self.assertIn(out["triage"]["acuity"], ["red", "yellow", "green"])

    def test_decision_support_accepts_multiple_vital_formats(self):
        encounter = {
            "encounter_id": "enc-002",
            "chief_complaint": "weakness",
            "symptoms": ["fatigue"],
            "vitals": {"hr": 98, "bp_systolic": 102, "bp_diastolic": 66, "spo2": 97, "rr": 18},
        }
        out = asyncio.run(decision_support.run_decision_support(encounter))
        self.assertEqual(out["encounter"]["vitals"]["systolic_bp"], 102.0)
        self.assertEqual(out["encounter"]["vitals"]["diastolic_bp"], 66.0)


if __name__ == "__main__":
    unittest.main()
