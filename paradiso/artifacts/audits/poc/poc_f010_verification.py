"""
Adversarial verification script for F-010 (Midnight Rollover & 22:00 Cutoff In-Flight Job Execution Duplication & Premature Reset).
"""
import sys
import time
import subprocess
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK
from models.report import Report
from models.intraday import ReportRun, IntradayDay, Intraday

class TestF010AdversarialVerification(unittest.TestCase):
    def setUp(self):
        self.app, self.paradiso = create_app()
        self.app.config["TESTING"] = True
        self.intra_svc = self.paradiso.intraday_service
        self.auto_svc = self.intra_svc.automation_service
        self.runner = self.intra_svc.execution_service.runner
        self.test_reports = []

    def tearDown(self):
        try:
            self.paradiso.stop()
            self.runner.kill_all()
        except Exception:
            pass

        date = CLOCK.date_str()
        for r_name in self.test_reports:
            try:
                self.auto_svc.delete(r_name)
            except Exception:
                pass
            def _clean(data):
                if date in data and "reports_ran" in data[date]:
                    data[date]["reports_ran"].pop(r_name, None)
            self.intra_svc.intraday_repo.mutate(_clean)

    def test_2200_cutoff_fresh_task_killed_and_marked_failed(self):
        """Vector 1: Fresh in-flight task is killed and transitions to Failed on 22:00 cutoff."""
        report_name = f"Fresh_Cutoff_{int(time.time() * 1000) % 10000}"
        self.test_reports.append(report_name)
        date_today = CLOCK.date_str()

        temp_rep = Report(name=report_name, filename="sample_report_blueprint.py", filetype="python", dir="../reports", status="Running")
        self.auto_svc.add(temp_rep)

        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.runner.active_processes[report_name] = proc

        with self.intra_svc._lock:
            self.intra_svc.current_runs[report_name] = CLOCK.formatted_now()
            self.intra_svc.waitlist.append(report_name)

        self.intra_svc._close_day(date_today)
        time.sleep(0.3)

        self.assertIsNotNone(proc.poll(), "OS subprocess must be killed by _close_day()")
        self.assertEqual(len(self.intra_svc.current_runs), 0)

        report = self.auto_svc.get_by_name(report_name)
        self.assertEqual(report.status, "Failed")
        self.assertIn("breached 10:00 PM cutoff", report.last_output)

    def test_2200_cutoff_rerun_task_killed_and_marked_failed(self):
        """Vector 2 (Adversarial Regression): Re-run report in already_ran at 22:00 cutoff MUST transition to Failed."""
        report_name = f"Rerun_Cutoff_{int(time.time() * 1000) % 10000}"
        self.test_reports.append(report_name)
        date_today = CLOCK.date_str()

        temp_rep = Report(name=report_name, filename="sample_report_blueprint.py", filetype="python", dir="../reports", status="Running")
        self.auto_svc.add(temp_rep)

        # 1. Precondition: Earlier execution recorded in day.reports_ran
        self.intra_svc.intraday_repo.add_report_run(
            date=date_today,
            report_name=report_name,
            run=ReportRun(
                started_at="08:00 AM",
                finished_at="08:05 AM",
                result="completed",
                duration="5s",
                reason="Earlier execution completed"
            )
        )

        day = self.intra_svc.intraday_repo.get_day(date_today)
        self.assertIn(report_name, day.reports_ran, "Precondition: report must exist in reports_ran")

        # 2. Simulate re-running at 21:50 before cutoff
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.runner.active_processes[report_name] = proc
        with self.intra_svc._lock:
            self.intra_svc.current_runs[report_name] = CLOCK.formatted_now()

        # 3. Trigger 22:00 cutoff
        self.intra_svc._close_day(date_today)
        time.sleep(0.3)

        self.assertIsNotNone(proc.poll(), "OS subprocess must be killed by _close_day()")
        self.assertEqual(len(self.intra_svc.current_runs), 0)

        report = self.auto_svc.get_by_name(report_name)
        self.assertEqual(
            report.status,
            "Failed",
            "Re-run report in-flight at cutoff MUST transition to Failed even if previously in already_ran!"
        )
        self.assertIn("breached 10:00 PM cutoff", report.last_output)

    def test_midnight_rollover_kills_strays_on_pre_existing_day_record(self):
        """Vector 3 (Adversarial Regression): Midnight rollover executes even when day record already exists in storage."""
        report_name = f"Stray_Mid_{int(time.time() * 1000) % 10000}"
        self.test_reports.append(report_name)

        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.runner.active_processes[report_name] = proc

        with self.intra_svc._lock:
            self.intra_svc.current_runs[report_name] = CLOCK.formatted_now()

        # Pre-seed day record for tomorrow
        sim_future_date = f"2048-06-{int(time.time()) % 25 + 1:02d}"
        pre_existing_day = IntradayDay(
            date=sim_future_date,
            status=Intraday.WAITING_TO_OPEN,
            expected_reports=[],
            reports_ran={},
            timeline=[]
        )
        self.intra_svc.intraday_repo.add_day(pre_existing_day)

        orig_date_str = CLOCK.date_str
        try:
            CLOCK.date_str = lambda: sim_future_date
            self.intra_svc.is_active = True
            self.intra_svc.tick()

            time.sleep(0.3)
            # Stray OS process must be dead
            self.assertIsNotNone(proc.poll(), "Stray process must be terminated at midnight rollover on pre-existing day")
            self.assertEqual(len(self.intra_svc.current_runs), 0, "current_runs must be cleared on day rollover")

            # Active date must be updated
            self.assertEqual(self.intra_svc._active_date, sim_future_date)
        finally:
            CLOCK.date_str = orig_date_str
            self.intra_svc.is_active = False

    def test_waitlist_reconciliation_excludes_running_jobs(self):
        """Vector 4: Reconcile waitlist deck does not inject running jobs into waitlist."""
        date_today = CLOCK.date_str()
        day = self.intra_svc.intraday_repo.get_day(date_today)
        if not day:
            self.intra_svc.tick()
            day = self.intra_svc.intraday_repo.get_day(date_today)

        report_name = "SF Base"
        with self.intra_svc._lock:
            self.intra_svc.is_active = True
            self.intra_svc.current_runs[report_name] = CLOCK.formatted_now()
            self.intra_svc.waitlist.clear()

            self.intra_svc.tick()

            self.assertNotIn(
                report_name,
                self.intra_svc.waitlist,
                "Currently running reports must NOT be injected into waitlist!"
            )

    def test_no_duplicate_queue_entries_on_rapid_ticks(self):
        """Vector 5: Repeated ticks must not duplicate waitlist entries."""
        date_today = CLOCK.date_str()
        self.intra_svc.is_active = True
        self.intra_svc.tick()

        initial_len = len(self.intra_svc.waitlist)
        initial_set = set(self.intra_svc.waitlist)
        self.assertEqual(initial_len, len(initial_set), "Initial waitlist has duplicates!")

        for _ in range(10):
            self.intra_svc.tick()

        after_len = len(self.intra_svc.waitlist)
        after_set = set(self.intra_svc.waitlist)
        self.assertEqual(after_len, len(after_set), "Repeated ticks created duplicate waitlist entries!")

if __name__ == "__main__":
    unittest.main()
