import unittest

from backend.orchestrator import run_aegis_pipeline


class TestAEGISPipeline(unittest.TestCase):
    def test_pipeline_returns_expected_sections(self):
        encounter = {
            "encounter_id": "t-001",
            "chief_complaint": "Chest pain and shortness of breath",
            "symptoms": ["pressure-like chest pain", "shortness of breath", "sweating"],
            "vitals": {
                "heart_rate": 128,
                "blood_pressure": "86/54",
                "respiratory_rate": 26,
                "oxygen_saturation": 90,
                "temperature": 98.7,
                "mental_status": "anxious but oriented",
            },
            "metadata": {"profile_id": "combat_medic", "scenario_id": "battlefield"},
        }

        result = run_aegis_pipeline(encounter)

        expected_keys = {
            "encounter",
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
            "timeline",
            "offline_status",
            "integrations",
        }
        self.assertTrue(expected_keys.issubset(result.keys()))
        self.assertEqual(result["offline_status"]["cloud_calls"], 0)
        self.assertIn(result["triage"]["acuity"], ["red", "yellow", "green"])

    def test_bp_normalization_supports_split_fields(self):
        encounter = {
            "encounter_id": "t-002",
            "chief_complaint": "Dizziness",
            "symptoms": ["weakness"],
            "vitals": {
                "heart_rate": 95,
                "systolic_bp": 101,
                "diastolic_bp": 67,
                "respiratory_rate": 18,
                "oxygen_saturation": 98,
            },
        }
        result = run_aegis_pipeline(encounter)
        self.assertEqual(result["encounter"]["vitals"]["systolic_bp"], 101.0)
        self.assertEqual(result["encounter"]["vitals"]["diastolic_bp"], 67.0)

    def test_medication_interaction_flags_are_reported(self):
        encounter = {
            "encounter_id": "t-003",
            "chief_complaint": "Palpitations",
            "symptoms": ["tachycardia"],
            "vitals": {
                "heart_rate": 140,
                "blood_pressure": "100/60",
                "respiratory_rate": 24,
                "oxygen_saturation": 95,
            },
            "metadata": {
                "pending_medication": "epinephrine",
                "admin_history": ["amiodarone"],
                "allergies": [],
            },
        }
        result = run_aegis_pipeline(encounter)
        self.assertIn("medication_flags", result["safety"])
        self.assertGreaterEqual(len(result["safety"]["medication_flags"]), 1)

    def test_pipeline_handles_missing_vitals(self):
        encounter = {
            "encounter_id": "t-004",
            "chief_complaint": "General malaise",
            "symptoms": [],
            "vitals": {},
        }
        result = run_aegis_pipeline(encounter)
        self.assertIsInstance(result["timeline"], list)
        self.assertIsInstance(result["questions"], dict)
        self.assertIsInstance(result["missed_signals"], dict)


if __name__ == "__main__":
    unittest.main()
