import os
import sys
import json
import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from models.report import Report
from app import create_app

class TestF037ToF039Verification(unittest.TestCase):
    """
    Adversarial Audit Verification Suite for F-037, F-038, F-039:
    Verifies that the builder's solutions are robust, long-lived, and not band-aid fixes:
    - F-037: scheduled_time format validation (rejects invalid/unpadded/12-hr with 400) + defensive tick normalization.
    - F-038: catch_up_policy validation and persistence in POST /api/automation/add.
    - F-039: reset_all_reports() cleanly resets type_c_warned state without suppressing subsequent alerts.
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

    def test_v_f037_api_format_rejection(self):
        """Verifies API rejects all non-canonical time formats with HTTP 400."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            with app.test_client() as client:
                bad_formats = [
                    "08:30 AM", "8:30 PM", "8:30", "9:00",
                    "24:00", "25:00", "12:60", "invalid", "   ", "12:00:00"
                ]
                for bad in bad_formats:
                    res = client.post("/api/automation/add", json={
                        "name": f"Bad_{bad.replace(' ', '_').replace(':', '_')}",
                        "filename": "dummy.py",
                        "filetype": "python",
                        "dir": "reports",
                        "report_type": "type_c",
                        "scheduled_time": bad
                    })
                    self.assertEqual(
                        res.status_code, 400,
                        f"Expected HTTP 400 for scheduled_time '{bad}', got {res.status_code}"
                    )
                    data = json.loads(res.data)
                    self.assertFalse(data["ok"])
                    self.assertIn("canonical 24-hour HH:MM format", data["error"])

                # Canonical 24-hr succeeds
                good_formats = ["00:00", "08:30", "12:00", "20:30", "23:59"]
                for i, good in enumerate(good_formats):
                    res = client.post("/api/automation/add", json={
                        "name": f"Good_{i}",
                        "filename": "dummy.py",
                        "filetype": "python",
                        "dir": "reports",
                        "report_type": "type_c",
                        "scheduled_time": good
                    })
                    self.assertEqual(res.status_code, 201)
        finally:
            paradiso.stop()

    def test_v_f037_tick_defensive_normalization(self):
        """Verifies tick() tolerates legacy unpadded or 12hr strings in storage without crash or freeze."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.start_lane("type_c", force_open=True)

            # Manually inject legacy items into automation service (as if loaded from pre-existing storage)
            intra.automation_service.add(Report(
                name="Legacy_Unpadded",
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                scheduled_time="8:30"
            ))
            intra.automation_service.add(Report(
                name="Legacy_12hr",
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                scheduled_time="08:30 AM"
            ))
            intra.automation_service.add(Report(
                name="Legacy_Corrupt",
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                scheduled_time="TOTAL_NONSENSE"
            ))

            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

            with patch.object(CLOCK, "now", return_value=datetime(2026, 9, 28, 9, 0, 0)), \
                 patch.object(CLOCK, "time_24_str", return_value="09:00"):
                intra.tick()

            # Normalized items dispatched
            self.assertIn("Legacy_Unpadded", dispatched)
            self.assertIn("Legacy_12hr", dispatched)
            # Unparseable item safely ignored and warned
            self.assertNotIn("Legacy_Corrupt", dispatched)
            self.assertIn("Legacy_Corrupt", intra.type_c_warned)
        finally:
            paradiso.stop()

    def test_v_f038_catch_up_policy_persistence(self):
        """Verifies catch_up_policy is validated, serialized, and persisted in automations storage."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            with app.test_client() as client:
                # Valid policies
                for policy in ["CATCH_UP_IMMEDIATE", "SKIP_UNTIL_NEXT_DAY", "WARN_OPERATOR"]:
                    res = client.post("/api/automation/add", json={
                        "name": f"Report_{policy}",
                        "filename": "dummy.py",
                        "filetype": "python",
                        "dir": "reports",
                        "report_type": "type_c",
                        "scheduled_time": "14:00",
                        "catch_up_policy": policy.lower() # Verify case-insensitivity
                    })
                    self.assertEqual(res.status_code, 201)
                    data = json.loads(res.data)
                    self.assertEqual(data["report"]["catch_up_policy"], policy)

                    stored = paradiso.intraday_service.automation_service.get_by_name(f"Report_{policy}")
                    self.assertIsNotNone(stored)
                    self.assertEqual(stored.catch_up_policy, policy)

                # Invalid policy
                res_bad = client.post("/api/automation/add", json={
                    "name": "Report_Bad_Policy",
                    "filename": "dummy.py",
                    "filetype": "python",
                    "dir": "reports",
                    "report_type": "type_c",
                    "scheduled_time": "14:00",
                    "catch_up_policy": "DROP_SILENTLY"
                })
                self.assertEqual(res_bad.status_code, 400)
                data_bad = json.loads(res_bad.data)
                self.assertFalse(data_bad["ok"])
                self.assertIn("Invalid catch_up_policy", data_bad["error"])
        finally:
            paradiso.stop()

    def test_v_f039_reset_clears_type_c_warned_and_reenables_notifications(self):
        """Verifies operational reset clears warned state and allows new alerts upon subsequent missed ticks."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.start_lane("type_c", force_open=True)

            rep_name = "Missed_Timeslot_Report"
            intra.automation_service.add(Report(
                name=rep_name,
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                scheduled_time="08:30",
                catch_up_policy="WARN_OPERATOR"
            ))

            # 1. At 09:00, report is missed and warned
            with patch.object(CLOCK, "time_24_str", return_value="09:00"), \
                 patch.object(CLOCK, "now", return_value=datetime(2026, 9, 28, 9, 0, 0)):
                intra.tick()

            self.assertIn(rep_name, intra.type_c_warned)

            # 2. Reset operational slate via API
            with app.test_client() as client:
                res_reset = client.post("/api/automations/reset")
                self.assertEqual(res_reset.status_code, 200)

            self.assertNotIn(rep_name, intra.type_c_warned)
            self.assertEqual(len(intra.type_c_warned), 0)

            # 3. Next tick re-alerts because report is still missed
            intra.start_lane("type_c", force_open=True)
            with patch.object(CLOCK, "time_24_str", return_value="09:05"), \
                 patch.object(CLOCK, "now", return_value=datetime(2026, 9, 28, 9, 5, 0)):
                intra.tick()

            self.assertIn(rep_name, intra.type_c_warned)
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
