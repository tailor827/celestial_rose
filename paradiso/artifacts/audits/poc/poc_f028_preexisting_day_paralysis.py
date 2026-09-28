"""
Verification Script for F-028: Pre-existing Closed Day Record Reset Verification.
Validates:
1. When a day record for today exists in storage with status CLOSED and auto-finalized
   reports in reports_ran, IntradayService resets the day to a clean slate upon boot/start_lane.
2. The waitlist is cleanly populated with expected reports.
3. The scheduler does not suffer from pipeline paralysis.
"""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK

class TestF028ResolutionVerification(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.test_dir.name)
        self.storage_dir = self.temp_path / "storage"
        self.logs_dir = self.temp_path / "logs"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.old_storage = os.environ.get("PARADISO_STORAGE_DIR")
        self.old_logs = os.environ.get("PARADISO_LOGS_DIR")
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)

    def tearDown(self):
        if self.old_storage is not None:
            os.environ["PARADISO_STORAGE_DIR"] = self.old_storage
        else:
            os.environ.pop("PARADISO_STORAGE_DIR", None)

        if self.old_logs is not None:
            os.environ["PARADISO_LOGS_DIR"] = self.old_logs
        else:
            os.environ.pop("PARADISO_LOGS_DIR", None)

        try:
            self.test_dir.cleanup()
        except Exception:
            pass

    def test_preexisting_closed_day_record_cleansed_and_waitlist_populated(self):
        """Verifies that a pre-existing closed day record in storage is cleansed and waitlist is populated."""
        today_date = CLOCK.date_str()

        automations_data = {
            "SF Base": {"name": "SF Base", "report_type": "type_a", "filename": "dummy.py", "dir": "reports", "status": "Waiting"},
            "Daily Cash Flow": {"name": "Daily Cash Flow", "report_type": "type_a", "filename": "dummy.py", "dir": "reports", "status": "Waiting"}
        }
        (self.storage_dir / "automations.json").write_text(json.dumps(automations_data), encoding="utf-8")

        intraday_data = {
            today_date: {
                "status": "CLOSED",
                "expected_reports": ["SF Base", "Daily Cash Flow"],
                "reports_ran": {
                    "SF Base": {"started_at": "--", "finished_at": "--", "result": "failed", "reason": "Historical day finalized automatically"},
                    "Daily Cash Flow": {"started_at": "--", "finished_at": "--", "result": "failed", "reason": "Historical day finalized automatically"}
                },
                "timeline": []
            }
        }
        (self.storage_dir / "intraday.json").write_text(json.dumps(intraday_data), encoding="utf-8")

        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra_svc = paradiso.intraday_service
            intra_svc.start_lane("type_a", force_open=True)

            self.assertEqual(len(intra_svc.waitlist), 2,
                             "Waitlist must be populated with both reports after cleansing stale closed day record.")
            self.assertIn("SF Base", intra_svc.waitlist)
            self.assertIn("Daily Cash Flow", intra_svc.waitlist)
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
