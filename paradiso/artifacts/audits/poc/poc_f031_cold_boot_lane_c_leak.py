"""
PoC for F-031: Cold Boot Leaks Prior Day's Completed Status in Automations Catalog
into Lane C type_c_ran_today, Suppressing Daily Execution.

Proves:
1. When a Lane C report completed yesterday, its status in automations.json is 'Completed'.
2. On cold boot of a new day, IntradayService.__init__ calls _hydrate_type_c_ran_today().
3. Lines 208-210 unconditionally iterate automation_service.get_by_type('type_c') and add any
   report with status == 'Completed' directly into self.type_c_ran_today.
4. When Lane C is started and tick() executes at the scheduled timeslot, the report is skipped
   because it is already in self.type_c_ran_today, completely suppressing its execution today.
"""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK

class TestF031ColdBootLaneCLeak(unittest.TestCase):
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

    def test_cold_boot_suppresses_lane_c_execution_due_to_yesterday_completion(self):
        """Proves that a cold boot with 'Completed' status in automations.json suppresses Lane C execution today."""
        rep_name = "EOD Ledger Reconciliation"

        # Automations catalog retains 'Completed' from yesterday's execution
        automations_data = {
            rep_name: {
                "name": rep_name,
                "filename": "eod_ledger_reconciliation.py",
                "filetype": "python",
                "dir": "reports",
                "report_type": "type_c",
                "timeslot_tier": "EOD",
                "scheduled_time": "20:30",
                "status": "Completed",
                "last_run": "2026-09-25 08:30:00 PM"
            }
        }
        (self.storage_dir / "automations.json").write_text(json.dumps(automations_data), encoding="utf-8")

        # Today's day record in intraday.json is empty (cold boot of new day)
        (self.storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra_svc = paradiso.intraday_service

            # DEFECT DEMONSTRATION 1: type_c_ran_today was hydrated with yesterday's completed report
            self.assertIn(rep_name, intra_svc.type_c_ran_today,
                          "F-031 Defect: type_c_ran_today contaminated with prior day's completed report on cold boot.")

            intra_svc.start_lane("type_c", force_open=True)

            dispatched = []
            intra_svc.execution_service.execute_report = MagicMock(side_effect=lambda name, **kw: dispatched.append(name))

            # When scheduled time 20:30 arrives today:
            with patch.object(CLOCK, "time_24_str", return_value="20:30"):
                intra_svc.tick()

            # DEFECT DEMONSTRATION 2: The report was never dispatched because it was marked ran today!
            self.assertEqual(len(dispatched), 0,
                             "F-031 Defect: Lane C report was suppressed and never executed today.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
