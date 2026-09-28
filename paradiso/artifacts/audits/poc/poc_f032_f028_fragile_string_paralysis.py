"""
PoC for F-032: Fragile String Matching in _get_or_init_day Causes Storage Paralysis
When Pre-existing Closed Day Contains Realistic Cutoff Reasons.

Proves:
1. In intraday_service.py:228-233, DEV remediated F-028 with a fragile exact-string match:
   all(getattr(r, "reason", "") == "Historical day finalized automatically" for r in day.reports_ran.values())
2. When a pre-existing closed day record exists in intraday.json with realistic reasons from
   Paradiso's own _close_day() (e.g. "Not completed before 10:00 PM cutoff"), all_auto_finalized is False.
3. _get_or_init_day() treats the record as active/non-stale and fails to reinitialize a clean day slate.
4. already_ran = set(day.reports_ran.keys()) excludes all expected reports from the queue.
5. The waitlist remains completely empty (len == 0), causing total pipeline paralysis.
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

class TestF032FragileStringParalysis(unittest.TestCase):
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

    def test_realistic_cutoff_reasons_bypass_f028_cleansing_and_paralyse_waitlist(self):
        """Proves that realistic cutoff reasons prevent _get_or_init_day from cleansing stale closed day."""
        today_date = CLOCK.date_str()

        automations_data = {
            "SF Base": {"name": "SF Base", "report_type": "type_a", "filename": "dummy.py", "dir": "reports", "status": "Waiting"},
            "Daily Cash Flow": {"name": "Daily Cash Flow", "report_type": "type_a", "filename": "dummy.py", "dir": "reports", "status": "Waiting"}
        }
        (self.storage_dir / "automations.json").write_text(json.dumps(automations_data), encoding="utf-8")

        # Seed intraday.json with a pre-existing CLOSED record for today where the reason is Paradiso's own real cutoff reason
        intraday_data = {
            today_date: {
                "status": "CLOSED",
                "expected_reports": ["SF Base", "Daily Cash Flow"],
                "reports_ran": {
                    "SF Base": {
                        "started_at": "--",
                        "finished_at": "--",
                        "result": "failed",
                        "reason": "Not completed before 10:00 PM cutoff"
                    },
                    "Daily Cash Flow": {
                        "started_at": "--",
                        "finished_at": "--",
                        "result": "failed",
                        "reason": "Not completed before 10:00 PM cutoff"
                    }
                },
                "timeline": []
            }
        }
        (self.storage_dir / "intraday.json").write_text(json.dumps(intraday_data), encoding="utf-8")

        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra_svc = paradiso.intraday_service
            intra_svc.start_lane("type_a", force_open=True)

            # DEFECT DEMONSTRATION: waitlist is empty because fragile reason check failed to cleanse!
            self.assertEqual(len(intra_svc.waitlist), 0,
                             "F-032 Defect: Fragile string match failed to cleanse pre-closed record, causing queue paralysis.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
