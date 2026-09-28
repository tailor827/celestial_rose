import os
import sys
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app

class TestF038CatchUpPolicyDroppedInApi(unittest.TestCase):
    """
    Adversarial PoC for F-038:
    Proves that POST /api/automation/add silently drops catch_up_policy parameter.
    """
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.tmpdir.name)
        self.logs_dir = self.storage_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("PARADISO_STORAGE_DIR", None)
        os.environ.pop("PARADISO_LOGS_DIR", None)

    def test_add_automation_drops_catch_up_policy(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            with app.test_client() as client:
                res = client.post("/api/automation/add", json={
                    "name": "Policy_Drop_Test",
                    "filename": "dummy.py",
                    "filetype": "python",
                    "dir": "reports",
                    "report_type": "type_c",
                    "timeslot_tier": "CUSTOM",
                    "scheduled_time": "08:30",
                    "catch_up_policy": "SKIP_UNTIL_NEXT_DAY"
                })
                self.assertEqual(res.status_code, 201)

                data = res.get_json()
                returned_policy = data.get("report", {}).get("catch_up_policy")

                # DEFECT DEMONSTRATION:
                # The returned report and persisted model have catch_up_policy as None
                self.assertIsNone(returned_policy,
                                  "F-038 Defect: catch_up_policy was dropped in API response.")

                stored = paradiso.intraday_service.automation_service.get_by_name("Policy_Drop_Test")
                self.assertIsNone(getattr(stored, "catch_up_policy", None),
                                  "F-038 Defect: catch_up_policy was dropped in catalog storage.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
