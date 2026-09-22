"""
Adversarial verification script for F-004 resolution.
Verifies exit code 1 dependency skips, stderr capture, genuine error retry exhaustion,
and ReportLog parse_output discrimination.
Runs against isolated temporary storage.
"""
import sys
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from models.automation import Automations
from models.intraday import Intraday
from models.report import Report
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService, BASE_DIR
from services.intraday_service import IntradayService
from utils.clock import CLOCK

class TestF004AdversarialVerification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.auto_repo = Automations(self.dir_path / "automations.json")
        self.intra_repo = Intraday(self.dir_path / "intraday.json")
        self.auto_svc = AutomationService(self.auto_repo)
        self.exec_svc = ExecutionService(self.auto_svc)
        self.intra_svc = IntradayService(self.auto_svc, self.exec_svc)
        self.intra_svc.intraday_repo = self.intra_repo
        self.intra_svc.max_retries = 3

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_dependency_skip_with_exit_code_1_does_not_consume_retries(self):
        """Simulates 0base_auto.py exit code 1 with dependency skip marker."""
        rep_name = "0base_auto.py"
        self.auto_repo.add(Report(name=rep_name, filename="0base_auto.py", filetype="python", dir=".", status="Waiting"))
        self.intra_svc.start_fresh_run(force_open=True)

        today = CLOCK.date_str()

        # Run 5 times (exceeding max_retries=3)
        for cycle in range(5):
            # pop as tick does
            item = self.intra_svc.waitlist.popleft()
            
            # mock failure callback simulating exit code 1
            def mock_exec(name, callback_good, callback_fail):
                callback_fail(name, "0.02s", "Return code 1: SKIPPED: Missing dependency 'CC_Collections'")
                return True

            self.exec_svc.execute_report = mock_exec
            self.intra_svc._trigger_report(item, today)

            # Assert retry count is strictly 0
            self.assertEqual(self.intra_svc.retry_counts.get(rep_name, 0), 0)
            self.assertIn(rep_name, self.intra_svc.waitlist)
            self.assertEqual(self.auto_svc.get_by_name(rep_name).status, "Retrial")

        # Must never be recorded as terminal failed in reports_ran
        day = self.intra_repo.get_day(today)
        self.assertNotIn(rep_name, day.reports_ran)

    def test_genuine_error_consumes_retries_and_fails_terminally(self):
        """Verifies genuine execution errors consume retries and terminate at max_retries."""
        rep_name = "Broken_Report"
        self.auto_repo.add(Report(name=rep_name, filename="broken.py", filetype="python", dir=".", status="Waiting"))
        self.intra_svc.start_fresh_run(force_open=True)

        today = CLOCK.date_str()

        def mock_exec(name, callback_good, callback_fail):
            callback_fail(name, "0.05s", "Return code 1: Unhandled ZeroDivisionError: division by zero")
            return True

        self.exec_svc.execute_report = mock_exec

        # Attempts 1, 2: should requeue as Retrial
        for attempt in range(1, 3):
            item = self.intra_svc.waitlist.popleft()
            self.intra_svc._trigger_report(item, today)
            self.assertEqual(self.intra_svc.retry_counts[rep_name], attempt)
            self.assertIn(rep_name, self.intra_svc.waitlist)
            self.assertEqual(self.auto_svc.get_by_name(rep_name).status, "Retrial")

        # Attempt 3: reached max_retries (3) -> terminal failure
        item = self.intra_svc.waitlist.popleft()
        self.intra_svc._trigger_report(item, today)
        self.assertEqual(self.intra_svc.retry_counts[rep_name], 3)
        self.assertNotIn(rep_name, self.intra_svc.waitlist)
        self.assertEqual(self.auto_svc.get_by_name(rep_name).status, "Failed")

        # Verified in intraday reports_ran
        day = self.intra_repo.get_day(today)
        self.assertIn(rep_name, day.reports_ran)
        self.assertEqual(day.reports_ran[rep_name].result, "failed")

    def test_benign_not_found_not_misclassified_as_skip(self):
        """Verifies benign stdout with 'not found' is not classified as Skipped."""
        log = ReportLog("TestReport")
        # Benign outputs
        self.assertEqual(log.parse_output("Cache entry not found, generated fresh tokens"), "Completed")
        self.assertEqual(log.parse_output("No duplicate accounts found."), "Completed")

    def test_dumped_log_preservation_and_non_penalization(self):
        """Verifies ExecutionService preserves dumped logs with status=Retrial and IntradayService does not penalize retries."""
        import json
        rep_name = "CustomRetrialReport"
        dummy_script = BASE_DIR / "reports" / "custom_test_script.py"
        dummy_script.parent.mkdir(parents=True, exist_ok=True)
        dummy_script.write_text("# dummy")

        self.auto_repo.add(Report(name=rep_name, filename="custom_test_script.py", filetype="python", dir="reports", status="Waiting"))
        self.intra_svc.start_fresh_run(force_open=True)

        today = CLOCK.date_str()
        log_file = ReportLog(rep_name).log_dir / f"{rep_name}.json"

        # Mock runner simulating script that dumps JSON receipt with Retrial and exits 1
        class MockScriptRunner:
            def run_python(self, script_path, callback_good, callback_fail, name="report"):
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "name": rep_name,
                        "status": "Retrial",
                        "last_output": "Custom upstream unavailable",
                        "reason": "Custom upstream unavailable"
                    }, f)
                # Note: error string does NOT contain any of the hardcoded markers
                callback_fail("0.05s", "Return code 1: Process stopped cleanly after dump")

        self.exec_svc.runner = MockScriptRunner()

        try:
            # Trigger report 4 times (exceeding max_retries=3)
            for _ in range(4):
                item = self.intra_svc.waitlist.popleft()
                self.intra_svc.current_runs[item] = CLOCK.formatted_now()
                self.intra_svc._trigger_report(item, today)

                # Must NOT increment retries
                self.assertEqual(self.intra_svc.retry_counts.get(rep_name, 0), 0)
                self.assertIn(rep_name, self.intra_svc.waitlist)
                self.assertEqual(self.auto_svc.get_by_name(rep_name).status, "Retrial")

            # Check persistent disk log file: must be preserved as Retrial, NOT overwritten as Failed
            self.assertTrue(log_file.exists())
            with open(log_file, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
            self.assertEqual(disk_data["status"], "Retrial")
            self.assertEqual(disk_data["last_output"], "Custom upstream unavailable")
        finally:
            log_file.unlink(missing_ok=True)
            dummy_script.unlink(missing_ok=True)

if __name__ == "__main__":
    unittest.main()


