"""
Verification Script for F-029: Mid-Day Process Restart Lane C Hydration Verification.
Validates:
1. When a Lane C report executes and completes earlier in the day, its execution is recorded in storage.
2. Upon mid-day process restart, IntradayService hydrates type_c_ran_today from day.reports_ran.
3. On subsequent scheduler ticks, the report is NOT executed again.
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

class TestF029ResolutionVerification(unittest.TestCase):
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

    def test_midday_reboot_does_not_duplicate_lane_c_execution(self):
        today_date = CLOCK.date_str()
        rep_name = "MID_Day_Cash_Reconciliation"

        automations_data = {
            rep_name: {
                "name": rep_name,
                "filename": "mid_day_cash.py",
                "filetype": "python",
                "dir": "reports",
                "team": "Treasury",
                "owner": "Finance",
                "report_type": "type_c",
                "timeslot_tier": "MID",
                "scheduled_time": "12:00",
                "status": "Waiting"
            }
        }
        (self.storage_dir / "automations.json").write_text(json.dumps(automations_data), encoding="utf-8")

        intraday_data = {
            today_date: {
                "status": "OPEN",
                "expected_reports": [rep_name],
                "reports_ran": {
                    rep_name: {
                        "started_at": "12:00 PM",
                        "finished_at": "12:05 PM",
                        "result": "completed",
                        "duration": "12s",
                        "reason": "Reconciliation completed successfully with zero variance"
                    }
                },
                "timeline": []
            }
        }
        (self.storage_dir / "intraday.json").write_text(json.dumps(intraday_data), encoding="utf-8")

        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra_svc = paradiso.intraday_service
            self.assertIn(rep_name, intra_svc.type_c_ran_today,
                          "type_c_ran_today must be hydrated from storage upon restart.")

            dispatched_reports = []
            def mock_execute(name, **kwargs):
                dispatched_reports.append(name)

            intra_svc.execution_service.execute_report = MagicMock(side_effect=mock_execute)
            intra_svc.start_lane("type_c", force_open=True)

            with patch.object(CLOCK, "time_24_str", return_value="14:00"):
                intra_svc.tick()

            self.assertEqual(
                len(dispatched_reports), 0,
                "Lane C report must NOT re-execute after reboot."
            )
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
