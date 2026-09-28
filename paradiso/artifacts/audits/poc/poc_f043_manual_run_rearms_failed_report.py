"""
PoC: F-043 — Manual Run of Failed Lane B Report Silently Re-Arms Automatic Dispatch (Same-Day)
===============================================================================================
Corrected version — ensures active_runs_type_b is cleaned after init tick.
"""

import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from models.report import Report
from app import create_app


class TestF043ManualRunReArmsBypass(unittest.TestCase):

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

    def test_manual_run_of_failed_report_rearms_auto_dispatch_same_day(self):
        """
        Within an already-initialized day:
        1. Run a first tick() to initialize the day (mock execute to prevent real dispatch)
        2. Exhaust retries of a Type B report (status=Failed, retry_counts=3)
        3. Verify tick() does NOT dispatch it (F-041 fix)
        4. Simulate a successful manual run (retry_counts=0, status=Completed)
        5. Verify tick() DOES dispatch it again (F-043 defect: silent re-arm)
        """
        app, paradiso = create_app(storage_dir=self.storage_dir)
        intra = paradiso.intraday_service
        auto_svc = intra.automation_service
        exec_svc = intra.execution_service
        intra.max_retries = 3

        rep_name = "Failed_B_Report"
        auto_svc.add(Report(
            name=rep_name,
            filename="dummy.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            interval_minutes=15,
            status="Waiting"
        ))

        intra.start_lane("type_b", force_open=True)

        # Step 1: Initialize the day with a first tick, but intercept dispatch
        init_dt = datetime(2026, 9, 28, 9, 0, 0)
        exec_svc.execute_report = lambda name, **kw: None  # No-op to prevent actual dispatch

        with patch.object(CLOCK, "time_24_str", return_value="09:00"), \
             patch.object(CLOCK, "now", return_value=init_dt), \
             patch.object(CLOCK, "date_str", return_value="20260928"), \
             patch.object(CLOCK, "formatted_now", return_value="09:00:00 AM"), \
             patch.object(CLOCK, "time_str", return_value="09:00:00 AM"), \
             patch.object(CLOCK, "formatted_date", return_value="September 28, 2026"):
            intra.tick()

        # Clean up active_runs from init tick dispatch (simulate the run completing)
        intra.active_runs_type_b.clear()
        intra.type_b_last_run[rep_name] = init_dt

        # Step 2: Set up permanent failure state within the now-initialized day
        auto_svc.update_status(name=rep_name, status="Failed",
                               last_output="Exceeded max retries (3/3)")
        intra.retry_counts[rep_name] = 3

        # Step 3: Verify F-041 fix — tick() does NOT dispatch Failed report
        check_dt = init_dt + timedelta(minutes=20)
        verify_dispatched = []
        exec_svc.execute_report = lambda name, **kw: verify_dispatched.append(name)

        with patch.object(CLOCK, "time_24_str", return_value="09:20"), \
             patch.object(CLOCK, "now", return_value=check_dt), \
             patch.object(CLOCK, "date_str", return_value="20260928"), \
             patch.object(CLOCK, "formatted_now", return_value="09:20:00 AM"), \
             patch.object(CLOCK, "time_str", return_value="09:20:00 AM"), \
             patch.object(CLOCK, "formatted_date", return_value="September 28, 2026"):
            intra.tick()

        self.assertNotIn(rep_name, verify_dispatched,
                         "Pre-condition failed: F-041 fix should block dispatch of Failed report within same day")

        # Step 4: Simulate a successful manual run outcome
        # trigger_manual_run() -> _trigger_type_b_report() -> execute_report() -> _on_good()
        # _on_good resets retry_counts[name] = 0, and execute_report sets status to "Completed"
        intra.retry_counts[rep_name] = 0
        auto_svc.update_status(name=rep_name, status="Completed")
        intra.type_b_last_run[rep_name] = check_dt

        print(f"\n=== After simulated manual run ===")
        print(f"Report status: {auto_svc.get_by_name(rep_name).status}")
        print(f"retry_counts: {dict(intra.retry_counts)}")
        print(f"type_b_last_run: {dict(intra.type_b_last_run)}")
        print(f"active_runs_type_b: {dict(intra.active_runs_type_b)}")

        # Step 5: Advance time past the next interval and tick() again
        rearm_dt = check_dt + timedelta(minutes=20)
        rearm_dispatched = []
        exec_svc.execute_report = lambda name, **kw: rearm_dispatched.append(name)

        with patch.object(CLOCK, "time_24_str", return_value="09:40"), \
             patch.object(CLOCK, "now", return_value=rearm_dt), \
             patch.object(CLOCK, "date_str", return_value="20260928"), \
             patch.object(CLOCK, "formatted_now", return_value="09:40:00 AM"), \
             patch.object(CLOCK, "time_str", return_value="09:40:00 AM"), \
             patch.object(CLOCK, "formatted_date", return_value="September 28, 2026"):
            intra.tick()

        print(f"\n=== After rearm tick ===")
        print(f"rearm_dispatched: {rearm_dispatched}")
        print(f"Report status: {auto_svc.get_by_name(rep_name).status}")

        # F-043: If this passes, the manual run silently re-armed automatic dispatch
        self.assertIn(rep_name, rearm_dispatched,
                      "F-043 Defect: After successful manual run of exhausted-Failed report, "
                      "tick() re-dispatches it automatically without explicit re-enablement!")


if __name__ == "__main__":
    unittest.main()
