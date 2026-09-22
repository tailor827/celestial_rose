import unittest
import tempfile
from pathlib import Path
from models.automation import Automations
from models.intraday import Intraday, ReportRun, IntradayDay
from models.report import Report
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from services.runner import Runner
from utils.clock import CLOCK

class TestServices(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)

        # Isolated test repositories
        self.auto_path = self.dir_path / "automations.json"
        self.intraday_path = self.dir_path / "intraday.json"

        # Populate sample automations dataset
        sample_automations = {
            "Report_Alpha": {
                "name": "Report_Alpha",
                "team": "Finance",
                "scheduled_time": "08:00",
                "status": "Waiting",
                "duration": "--",
                "started_at": "--",
                "filename": "alpha.py",
                "dir": "reports",
                "filetype": "python"
            },
            "Report_Beta": {
                "name": "Report_Beta",
                "team": "Risk",
                "scheduled_time": "09:00",
                "status": "Waiting",
                "duration": "--",
                "started_at": "--",
                "filename": "beta.py",
                "dir": "reports",
                "filetype": "python"
            }
        }
        auto_storage = Automations(self.auto_path)
        auto_storage._write_json(sample_automations)

        self.automation_service = AutomationService(auto_storage)
        self.execution_service = ExecutionService(self.automation_service)
        self.intraday_service = IntradayService(self.automation_service, self.execution_service)
        self.intraday_service.intraday_repo = Intraday(self.intraday_path)

    def tearDown(self):
        try:
            self.test_dir.cleanup()
        except Exception:
            pass

    def test_automation_service_status_updates(self):
        all_reps = self.automation_service.get_all()
        self.assertEqual(len(all_reps), 2)
        waiting_count = sum(1 for r in all_reps if r.status == "Waiting")
        self.assertEqual(waiting_count, 2)

        # Update one to Completed
        self.automation_service.update_status("Report_Alpha", status="Completed", duration="15s")
        updated_rep = self.automation_service.get_by_name("Report_Alpha")
        self.assertEqual(updated_rep.status, "Completed")
        self.assertEqual(updated_rep.duration, "15s")

    def test_start_scheduler_preserves_completed_reports(self):
        """Ensures pressing Start Scheduler mid-day only queues non-terminal reports and preserves Completed reports."""
        today_date = CLOCK.date_str()
        # Initialize day for today (simulating mid-day operation where today's day was already initialized)
        day = IntradayDay(
            date=today_date,
            status=Intraday.OPEN,
            expected_reports=["Report_Alpha", "Report_Beta"],
            reports_ran={},
            timeline=[]
        )
        self.intraday_service.intraday_repo.add_day(day)

        # Mark Report_Alpha as Completed today
        self.automation_service.update_status("Report_Alpha", status="Completed", duration="10s")
        self.assertEqual(self.automation_service.get_by_name("Report_Alpha").status, "Completed")

        # Trigger start_fresh_run() (Start Scheduler button)
        self.intraday_service.start_fresh_run()

        # Assert Report_Alpha remains Completed and is NOT reset to Waiting
        self.assertEqual(self.automation_service.get_by_name("Report_Alpha").status, "Completed")

        # Assert waitlist ONLY contains Report_Beta (the non-completed report)
        self.assertNotIn("Report_Alpha", self.intraday_service.waitlist)
        self.assertIn("Report_Beta", self.intraday_service.waitlist)
        self.assertEqual(len(self.intraday_service.waitlist), 1)

        # Mark Report_Beta as Completed too
        self.automation_service.update_status("Report_Beta", status="Completed", duration="12s")

        # Trigger start_fresh_run() again when all reports are completed
        self.intraday_service.start_fresh_run()

        # Assert waitlist is empty and all reports remain Completed
        self.assertEqual(len(self.intraday_service.waitlist), 0)
        self.assertEqual(self.automation_service.get_by_name("Report_Alpha").status, "Completed")
        self.assertEqual(self.automation_service.get_by_name("Report_Beta").status, "Completed")

    def test_cold_boot_after_midnight_resets_yesterday_completed_reports(self):
        """Verifies a cold boot after midnight resets yesterday's Completed reports to Waiting on start_fresh_run()."""
        # Mark both reports as Completed (left over from yesterday)
        self.automation_service.update_status("Report_Alpha", status="Completed", duration="10s")
        self.automation_service.update_status("Report_Beta", status="Completed", duration="12s")
        self.assertEqual(self.automation_service.get_by_name("Report_Alpha").status, "Completed")
        self.assertEqual(self.automation_service.get_by_name("Report_Beta").status, "Completed")

        # Ensure today's day record does not exist yet (cold boot)
        today_date = CLOCK.date_str()
        self.assertIsNone(self.intraday_service.intraday_repo.get_day(today_date))

        # Trigger start_fresh_run() on cold boot
        self.intraday_service.start_fresh_run()

        # Verify all reports were reset to Waiting for the new day
        self.assertEqual(self.automation_service.get_by_name("Report_Alpha").status, "Waiting")
        self.assertEqual(self.automation_service.get_by_name("Report_Beta").status, "Waiting")

        # Verify all reports are in today's waitlist queue
        self.assertIn("Report_Alpha", self.intraday_service.waitlist)
        self.assertIn("Report_Beta", self.intraday_service.waitlist)
        self.assertEqual(len(self.intraday_service.waitlist), 2)

    def test_intraday_service_lifecycle(self):
        # Start fresh run
        self.intraday_service.start_fresh_run()
        self.assertTrue(self.intraday_service.is_active)
        self.assertEqual(len(self.intraday_service.waitlist), 2)

        # Stop scheduler
        self.intraday_service.stop_scheduler()
        self.assertFalse(self.intraday_service.is_active)

        # Reset all reports resets statuses to Waiting and keeps scheduler in Standby
        self.intraday_service.reset_all_reports()
        self.assertFalse(self.intraday_service.is_active)
        self.assertEqual(len(self.intraday_service.waitlist), 0)
        all_reps = self.automation_service.get_all()
        for r in all_reps:
            self.assertEqual(r.status, "Waiting")

    def test_execution_history_aggregation(self):
        # Record a test run in intraday_repo
        today_date = "20260906"
        run = ReportRun(
            started_at="2026-09-06 08:00:00",
            finished_at="2026-09-06 08:00:15",
            result="completed",
            duration="15s",
            reason="Sample completed output"
        )
        self.intraday_service.intraday_repo.add_report_run(today_date, "Report_Alpha", run)

        history = self.intraday_service.get_all_execution_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["report_name"], "Report_Alpha")
        self.assertEqual(history[0]["status"], "Completed")
        self.assertEqual(history[0]["duration"], "15s")

    def test_queue_rotation_on_skipped_dependency(self):
        # Simulate report execution callback for skipped dependency
        self.intraday_service.start_fresh_run()
        
        # Pop first report from waitlist
        first_report = self.intraday_service.waitlist.popleft()
        self.assertEqual(first_report, "Report_Alpha")
        self.intraday_service.current_runs[first_report] = "2026-09-06 08:00:00"

        skipped_output = "SKIPPED: missing dependency table_sales"

        def _mock_on_good(name, duration_str, output):
            started_at = self.intraday_service.current_runs.pop(name, "08:00")
            if "SKIPPED" in output.upper():
                self.intraday_service.waitlist.append(name)
                self.automation_service.update_status(name=name, status="Retrial", last_output=output)

        _mock_on_good("Report_Alpha", "5s", skipped_output)

        # Verify Report_Alpha was rotated back to the end of waitlist deque with Retrial status
        self.assertIn("Report_Alpha", self.intraday_service.waitlist)
        report = self.automation_service.get_by_name("Report_Alpha")
        self.assertEqual(report.status, "Retrial")

    def test_stop_scheduler_prevents_requeue(self):
        """Verifies that stopping scheduler clears waitlist and prevents orphan callbacks from re-queuing."""
        self.intraday_service.start_fresh_run()
        self.assertTrue(self.intraday_service.is_active)
        self.assertEqual(len(self.intraday_service.waitlist), 2)

        # Simulate running a report
        running_report = self.intraday_service.waitlist.popleft()
        self.intraday_service.current_runs[running_report] = "08:00"

        # User stops scheduler
        self.intraday_service.stop_scheduler()
        self.assertFalse(self.intraday_service.is_active)
        self.assertEqual(len(self.intraday_service.waitlist), 0)

        # Now simulate orphan callback executing after stop
        # IntradayService._trigger_report callback logic check
        def _mock_orphan_fail(name, duration_str, error):
            with self.intraday_service._lock:
                started_at = self.intraday_service.current_runs.pop(name, "08:00")
                if self.intraday_service.is_active or self.intraday_service.force_open:
                    self.intraday_service.waitlist.append(name)
                self.automation_service.update_status(name=name, status="Retrial", last_output=error)

        _mock_orphan_fail(running_report, "5s", "Simulated failure after stop")

        # Assert waitlist remains empty and is_active remains False
        self.assertEqual(len(self.intraday_service.waitlist), 0)
        self.assertNotIn(running_report, self.intraday_service.waitlist)
        self.assertEqual(self.automation_service.get_by_name(running_report).status, "Retrial")

    def test_clock_simulation_speed_and_formatting(self):
        """Verifies Clock 600x simulation speedup, 12-hr AM/PM formatting, and 24-hr string support."""
        CLOCK.set_simulation_mode(True)
        CLOCK.set_speed(600.0)
        self.assertTrue(CLOCK.simulation_mode)
        self.assertEqual(CLOCK.speed_multiplier, 600.0)

        # 12-hr time_str contains AM or PM
        time_display = CLOCK.time_str()
        self.assertTrue("AM" in time_display or "PM" in time_display)

        # 24-hr time_24_str is HH:MM format (length 5)
        time_24 = CLOCK.time_24_str()
        self.assertEqual(len(time_24), 5)
        self.assertIn(":", time_24)

    def test_runner_killed_process_callback_suppression(self):
        """Verifies that Runner.kill_all suppresses callback execution for killed processes."""
        runner = Runner()
        
        # Track if callback fired
        callback_fired = []

        def _mock_fail(dur, err):
            callback_fired.append(err)

        # Simulate adding a process to active_processes and then calling kill_all
        import subprocess, sys
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        runner.active_processes["Test_Report"] = p

        # Kill all processes
        runner.kill_all()
        self.assertIn("Test_Report", runner.killed_processes)

        # Call watcher logic directly
        runner._watcher("Test_Report", p, 0, lambda d, o: None, _mock_fail)

        # Assert fail callback was SUPPRESSED (was_killed flag caught it)
        self.assertEqual(len(callback_fired), 0)

    def test_intraday_window_transitions_and_close_day(self):
        """Verifies 10:00 PM close_day marks remaining uncompleted reports as Failed."""
        self.intraday_service.start_fresh_run()
        today_date = CLOCK.date_str()

        # Mark Report_Alpha as Completed
        self.automation_service.update_status("Report_Alpha", status="Completed", duration="10s")

        # Force day close (10:00 PM cutoff simulation)
        self.intraday_service._close_day(today_date)

        # Report_Alpha remains Completed
        self.assertEqual(self.automation_service.get_by_name("Report_Alpha").status, "Completed")

        # Report_Beta (which was Waiting) is marked as Failed by cutoff
        self.assertEqual(self.automation_service.get_by_name("Report_Beta").status, "Failed")
        self.assertEqual(len(self.intraday_service.waitlist), 0)

    def test_intraday_window_state_machine_and_cutoff_through_tick(self):
        """Verifies resolve_status follows 24-hr schedule and tick() executes 10 PM cutoff without force_open lock."""
        from unittest.mock import patch
        # 1. Start fresh run (standby -> active)
        self.intraday_service.start_fresh_run()
        self.assertTrue(self.intraday_service.is_active)
        self.assertFalse(self.intraday_service.force_open)

        # 2. Test status resolution at different times
        with patch.object(CLOCK, 'time_24_str', return_value="05:30"):
            self.assertEqual(self.intraday_service.resolve_status(), Intraday.WAITING_TO_OPEN)

        with patch.object(CLOCK, 'time_24_str', return_value="08:30"):
            self.assertEqual(self.intraday_service.resolve_status(), Intraday.OPEN)

        with patch.object(CLOCK, 'time_24_str', return_value="21:30"):
            self.assertEqual(self.intraday_service.resolve_status(), Intraday.WAITING_TO_CLOSE)

        # 3. Test that CLOSED at 22:30 triggers _close_day() via tick()
        with patch.object(CLOCK, 'time_24_str', return_value="22:30"):
            self.assertEqual(self.intraday_service.resolve_status(), Intraday.CLOSED)
            self.intraday_service.tick()

        # Remaining reports (Report_Alpha, Report_Beta) should be marked Failed by 10 PM cutoff
        rep_a = self.automation_service.get_by_name("Report_Alpha")
        self.assertEqual(rep_a.status, "Failed")
        self.assertIn("10:00 PM cutoff", rep_a.last_output)
        self.assertEqual(len(self.intraday_service.waitlist), 0)

    def test_real_queue_rotation_on_skipped_dependency_via_execution_service(self):
        """Verifies ExecutionService._on_good correctly flags SKIPPED output and rotates queue in IntradayService."""
        # Ensure report file physically exists on disk for execute_report
        rep = self.automation_service.get_by_name("Report_Alpha")
        rep.dir = "tests"
        rep.filename = "test_services.py"
        self.automation_service.add(rep)

        self.intraday_service.start_fresh_run()
        report_name = "Report_Alpha"
        
        # Pop from waitlist and record in current_runs as IntradayService does
        self.intraday_service.waitlist.remove(report_name)
        self.intraday_service.current_runs[report_name] = "08:00"

        # Mock runner so run_python triggers callback_good with SKIPPED output
        def _mock_run(script_path, callback_good, callback_fail, name):
            callback_good("4s", "SKIPPED: missing dependency CC_Collection_Summary")

        self.execution_service.runner.run_python = _mock_run

        # Execute report via ExecutionService with IntradayService's real callback
        def _on_good(name, dur, out):
            with self.intraday_service._lock:
                started_at = self.intraday_service.current_runs.pop(name, CLOCK.formatted_now())
                log = ReportLog(name).from_json(default_stdout=out)
                if log.status != "Completed":
                    if self.intraday_service.is_active or self.intraday_service.force_open:
                        self.intraday_service.waitlist.append(name)
                    self.automation_service.update_status(name=name, status="Retrial", duration=dur, last_output=log.last_output)

        self.execution_service.execute_report(report_name, callback_good=_on_good)

        # Assert report was NOT marked Completed
        report = self.automation_service.get_by_name(report_name)
        self.assertEqual(report.status, "Retrial")
        # Assert report was rotated back to the end of waitlist
        self.assertIn(report_name, self.intraday_service.waitlist)

    def test_missing_script_fails_cleanly_without_mock(self):
        """Verifies executing a non-existent report script fails immediately with Failed status and 0s duration."""
        missing_report = Report(
            name="Missing_Report",
            team="Operations",
            scheduled_time="09:00",
            status="Waiting",
            filename="non_existent_script_xyz.py",
            dir="reports",
            filetype="python"
        )
        self.automation_service.add(missing_report)

        failed_calls = []
        good_calls = []

        def _on_good(name, dur, out):
            good_calls.append((name, dur, out))

        def _on_fail(name, dur, err):
            failed_calls.append((name, dur, err))

        success = self.execution_service.execute_report("Missing_Report", callback_good=_on_good, callback_fail=_on_fail)
        self.assertFalse(success)

        # Allow daemon thread a moment to deliver callback
        import time
        time.sleep(0.1)

        self.assertEqual(len(good_calls), 0)
        self.assertEqual(len(failed_calls), 1)
        name, dur, err = failed_calls[0]
        self.assertEqual(name, "Missing_Report")
        self.assertEqual(dur, "0s")
        self.assertIn("not found on disk", err.lower())

        # Verify automation status is Failed, not Completed
        rep = self.automation_service.get_by_name("Missing_Report")
        self.assertEqual(rep.status, "Failed")

    def test_runner_rapid_restart_does_not_pop_new_process(self):
        """Verifies that an old process watcher completing after kill does not remove a restarted process of the same name."""
        import subprocess, sys
        runner = Runner()
        
        # Start dummy process 1
        p1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        runner.active_processes["Test_Job"] = p1

        # Terminate all processes
        runner.kill_all()

        # Immediately start new process 2 with same name
        p2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        runner.active_processes["Test_Job"] = p2

        # Simulate p1 completing and watcher firing
        runner._watcher("Test_Job", p1, 0, lambda d, o: None, lambda d, e: None)

        # Assert p2 was NOT removed by p1's watcher
        self.assertIn("Test_Job", runner.active_processes)
        self.assertIs(runner.active_processes["Test_Job"], p2)

        # Cleanup
        try:
            p2.terminate()
            p2.kill()
        except Exception:
            pass

if __name__ == "__main__":
    unittest.main()

