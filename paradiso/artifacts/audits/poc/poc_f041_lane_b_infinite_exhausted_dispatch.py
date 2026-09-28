import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from models.report import Report
from models.intraday import ReportRun
from app import create_app

class TestF041LaneBInfiniteExhaustedDispatch(unittest.TestCase):
    """
    Adversarial PoC for F-041:
    Demonstrates that Lane B continues to dispatch reports indefinitely every interval
    even AFTER they have permanently failed and exceeded max_retries.
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

    def test_permanently_failed_lane_b_dispatches_indefinitely(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.max_retries = 3

            rep_name = "Broken_Recurring_Feed"
            intra.automation_service.add(Report(
                name=rep_name,
                filename="dummy.py",
                filetype="python",
                dir="reports",
                report_type="type_b",
                interval_minutes=15,
                status="Waiting"
            ))

            today_date = "20260928"
            intra.start_lane("type_b", force_open=True)

            # Simulate report failing 3 times and reaching terminal Failed state
            intra.retry_counts[rep_name] = 3
            intra.automation_service.update_status(
                name=rep_name,
                status="Failed",
                last_output="Exceeded max retries (3/3): crash"
            )
            intra.intraday_repo.add_report_run(
                date=today_date,
                report_name=rep_name,
                run=ReportRun(
                    started_at="10:00",
                    finished_at="10:01",
                    result="failed",
                    duration="1s",
                    reason="Exceeded max retries (3/3): crash"
                )
            )

            # Advance time by 20 minutes (exceeding 15m interval)
            now_dt = datetime(2026, 9, 28, 10, 25, 0)
            intra.type_b_last_run[rep_name] = now_dt - timedelta(minutes=20)

            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

            with patch.object(CLOCK, "time_24_str", return_value="10:25"), \
                 patch.object(CLOCK, "now", return_value=now_dt):
                intra.tick()

            # DEFECT DEMONSTRATION:
            # The report is dispatched AGAIN despite terminal 'Failed' status and exhausted retries!
            self.assertIn(rep_name, dispatched,
                "F-041 Defect: Lane B dispatched a permanently failed report after interval elapsed!")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
