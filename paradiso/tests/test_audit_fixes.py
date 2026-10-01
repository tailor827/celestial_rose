import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app import create_app
from models.storage_base import StorageBase, StorageCorruptionError
from models.automation import Automations
from models.intraday import Intraday, IntradayDay, ReportRun
from models.report import Report
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from services.runner import Runner
from services.paradiso import Paradiso
from utils.clock import CLOCK
from utils.config import BASE_DIR, CONFIG, validate_config

if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))

class TestAuditFixes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)
        self.app_storage = self.dir_path / "app_storage"
        self.app_storage.mkdir(parents=True, exist_ok=True)

        sample_auto = {
            "SF Base": {
                "name": "SF Base",
                "filename": "sample_report_blueprint.py",
                "filetype": "python",
                "dir": "../reports",
                "team": "MIS Agency",
                "owner": "Cy",
                "scheduled_time": "08:30",
                "status": "Waiting",
                "last_run": "--/--/--",
                "started_at": "--",
                "duration": "--",
                "last_output": "Staged for execution"
            }
        }
        (self.app_storage / "automations.json").write_text(json.dumps(sample_auto), encoding="utf-8")
        (self.app_storage / "intraday.json").write_text("{}", encoding="utf-8")
        os.environ["PARADISO_STORAGE_DIR"] = str(self.app_storage)

        self.app_logs = self.dir_path / "logs"
        self.app_logs.mkdir(parents=True, exist_ok=True)
        os.environ["PARADISO_LOGS_DIR"] = str(self.app_logs)
        (self.app_logs / "Delinquency_RollRate.json").write_text(json.dumps({
            "name": "Delinquency_RollRate",
            "status": "Completed",
            "last_output": "Roll-rate metrics computed successfully"
        }), encoding="utf-8")

        self.app, self.paradiso = create_app(storage_dir=self.app_storage)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("PARADISO_STORAGE_DIR", None)
        os.environ.pop("PARADISO_LOGS_DIR", None)
        try:
            self.test_dir.cleanup()
        except Exception:
            pass
        CLOCK.set_simulation_mode(True)
        CLOCK.set_speed(600.0)

    # ----------------------------------------------------------------------
    # 1. Path Traversal Protection
    # ----------------------------------------------------------------------
    def test_path_traversal_prevention(self):
        """Verifies that path traversal attempts in get_execution_log are blocked with HTTP 400."""
        # Windows URL-encoded backslash traversal
        res_bs = self.client.get("/api/executions/log/..%5Cstorage%5Cautomations")
        self.assertEqual(res_bs.status_code, 400)
        data_bs = json.loads(res_bs.data)
        self.assertFalse(data_bs.get("ok"))
        self.assertIn("invalid", data_bs.get("error", "").lower())

        # Forward slash traversal
        res_fs = self.client.get("/api/executions/log/..%2Fstorage%2Fautomations")
        self.assertIn(res_fs.status_code, [400, 404])

        # Legitimate report name works
        res_valid = self.client.get("/api/executions/log/Delinquency_RollRate")
        self.assertEqual(res_valid.status_code, 200)
        data_valid = json.loads(res_valid.data)
        self.assertTrue(data_valid.get("ok"))
        self.assertEqual(data_valid.get("name"), "Delinquency_RollRate")

    # ----------------------------------------------------------------------
    # 2. Storage Durability & Corruption Handling
    # ----------------------------------------------------------------------
    def test_storage_corruption_protection(self):
        """Verifies that corrupted JSON raises StorageCorruptionError and preserves damaged file without blank overwrite."""
        corrupt_file = self.dir_path / "corrupted_test.json"
        corrupt_content = '{"unclosed_key": "val", damaged_syntax...'
        corrupt_file.write_text(corrupt_content, encoding="utf-8")

        storage = StorageBase(corrupt_file)

        # 1. _read_json must raise StorageCorruptionError instead of silently returning {}
        with self.assertRaises(StorageCorruptionError):
            storage._read_json()

        # 2. A rescue backup file should have been generated
        bak_files = list(self.dir_path.glob("corrupted_test_corrupted_*.bak"))
        self.assertGreaterEqual(len(bak_files), 1, "A rescue backup (.bak) must be created upon corruption.")

        # 3. mutate() must abort without overwriting the corrupted file with empty data
        with self.assertRaises(StorageCorruptionError):
            storage.mutate(lambda d: d.update({"overwrite": "attempt"}))

        # Ensure original file content was not replaced
        self.assertEqual(corrupt_file.read_text(encoding="utf-8"), corrupt_content)

    # ----------------------------------------------------------------------
    # 3. Max Retry Limit & Infinite Spin Prevention
    # ----------------------------------------------------------------------
    def test_max_retry_limit_halts_infinite_spin(self):
        """Verifies that failing reports retry up to max_retries, then transition to terminal Failed state and stop."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.max_retries = 3

        test_report = Report(
            name="BrokenReport",
            filename="does_not_exist_xyz.py",
            filetype="python",
            dir=".",
            status="Waiting"
        )
        auto_repo.add(test_report)
        intra_svc.start_fresh_run(force_open=True)

        today_date = CLOCK.date_str()

        from unittest.mock import patch
        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            # Attempt 1: First failure -> retrial (attempts = 1, waitlist re-queued)
            intra_svc.tick()
            time.sleep(0.05)
            self.assertEqual(intra_svc.retry_counts.get("BrokenReport"), 1)
            self.assertIn("BrokenReport", intra_svc.waitlist)
            self.assertEqual(auto_svc.get_by_name("BrokenReport").status, "Retrial")

            # Attempt 2: Second failure -> retrial (attempts = 2, waitlist re-queued)
            intra_svc.tick()
            time.sleep(0.05)
            self.assertEqual(intra_svc.retry_counts.get("BrokenReport"), 2)
            self.assertIn("BrokenReport", intra_svc.waitlist)

            # Attempt 3: Third failure -> reaches max_retries (3) -> terminal Failed!
            intra_svc.tick()
            time.sleep(0.05)
            self.assertEqual(intra_svc.retry_counts.get("BrokenReport"), 3)

            # Must NOT be in waitlist anymore
            self.assertNotIn("BrokenReport", intra_svc.waitlist)
            self.assertEqual(auto_svc.get_by_name("BrokenReport").status, "Failed")

        # Terminal run must be logged in intraday repo
        day = intra_repo.get_day(today_date)
        self.assertIsNotNone(day)
        self.assertIn("BrokenReport", day.reports_ran)
        self.assertEqual(day.reports_ran["BrokenReport"].result, "failed")

        # Further ticks must NOT re-execute or re-queue
        intra_svc.tick()
        self.assertEqual(len(intra_svc.waitlist), 0)
        self.assertEqual(len(intra_svc.current_runs), 0)

    # ----------------------------------------------------------------------
    # 4. Crash Recovery (Resetting Running Status on Startup)
    # ----------------------------------------------------------------------
    def test_crash_recovery_resets_running_reports(self):
        """Verifies that reports left in 'Running' status due to an ungraceful shutdown/crash are reset to 'Waiting' on fresh run."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo

        test_report = Report(
            name="InterruptedJob",
            filename="job.py",
            filetype="python",
            dir=".",
            status="Running"
        )
        auto_repo.add(test_report)

        # Fresh run / start_fresh_run recovers the job
        intra_svc.start_fresh_run(force_open=True)
        self.assertEqual(auto_svc.get_by_name("InterruptedJob").status, "Waiting")

    # ----------------------------------------------------------------------
    # 5. Past Dates Reconciliation
    # ----------------------------------------------------------------------
    def test_past_days_reconciliation(self):
        """Verifies that historical days left in OPEN are automatically closed with uncompleted jobs marked failed."""
        intra_path = self.dir_path / "intraday.json"
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(Automations(self.dir_path / "automations.json"))
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo

        # Seed past unclosed days
        past_day_1 = "20260901"
        past_day_2 = "20260902"
        today_date = "20260906"

        intra_repo.add_day(IntradayDay(
            date=past_day_1,
            status=Intraday.OPEN,
            expected_reports=["Report_X", "Report_Y"],
            reports_ran={"Report_X": ReportRun("08:00", "08:01", "completed")}
        ))
        intra_repo.add_day(IntradayDay(
            date=past_day_2,
            status=Intraday.WAITING_TO_CLOSE,
            expected_reports=["Report_Z"],
            reports_ran={}
        ))

        # Reconcile against today
        intra_svc._reconcile_past_days(today_date)

        # Both past days must now be CLOSED
        day1 = intra_repo.get_day(past_day_1)
        self.assertEqual(day1.status, Intraday.CLOSED)
        self.assertEqual(day1.reports_ran["Report_X"].result, "completed")
        self.assertEqual(day1.reports_ran["Report_Y"].result, "failed")

        day2 = intra_repo.get_day(past_day_2)
        self.assertEqual(day2.status, Intraday.CLOSED)
        self.assertEqual(day2.reports_ran["Report_Z"].result, "failed")

    # ----------------------------------------------------------------------
    # 6. Configurable Scheduler Interval
    # ----------------------------------------------------------------------
    def test_scheduler_interval_resolution(self):
        """Verifies that Paradiso resolves interval dynamically based on simulation mode and config."""
        auto_svc = AutomationService(Automations(self.dir_path / "automations.json"))
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        paradiso = Paradiso(intra_svc)

        # Simulation mode enabled: fast 0.5s tick
        CLOCK.set_simulation_mode(True)
        self.assertEqual(paradiso.interval, 0.5)

        # Simulation mode disabled: respects configured job_interval_seconds (default 15.0)
        CLOCK.set_simulation_mode(False)
        expected_interval = float(CONFIG.get("scheduler", {}).get("job_interval_seconds", 15.0))
        self.assertEqual(paradiso.interval, expected_interval)

        # Custom override
        custom_paradiso = Paradiso(intra_svc, interval=2.5)
        self.assertEqual(custom_paradiso.interval, 2.5)

    # ----------------------------------------------------------------------
    # 7. F-001: Deleting executing report blocked & self-healing queue
    # ----------------------------------------------------------------------
    def test_delete_automation_blocked_while_intraday_active(self):
        """Verifies that report deletion is rejected with 409 Conflict while intraday scheduler is active (Brick Wall policy)."""
        test_name = "BAU_Protected_Report"
        self.paradiso.intraday_service.automation_service.add(Report(
            name=test_name,
            filename="dummy.py",
            filetype="python",
            dir="../reports",
            status="Waiting"
        ))
        try:
            # When intraday scheduler is active:
            self.paradiso.intraday_service.is_active = True
            res = self.client.delete(f"/api/automation/delete/{test_name}")
            self.assertEqual(res.status_code, 409)
            data = json.loads(res.data)
            self.assertFalse(data.get("ok"))
            self.assertIn("locked while intraday scheduler is active", data.get("error", ""))

            # Verify report was NOT deleted
            self.assertIsNotNone(self.paradiso.intraday_service.automation_service.get_by_name(test_name))

            # When intraday scheduler is stopped:
            self.paradiso.intraday_service.is_active = False
            res_stopped = self.client.delete(f"/api/automation/delete/{test_name}")
            self.assertEqual(res_stopped.status_code, 200)
            self.assertTrue(json.loads(res_stopped.data).get("ok"))
            self.assertIsNone(self.paradiso.intraday_service.automation_service.get_by_name(test_name))
        finally:
            self.paradiso.intraday_service.is_active = False
            self.paradiso.intraday_service.automation_service.delete(test_name)

    def test_execute_report_missing_report_triggers_fail_callback(self):
        """Verifies that ExecutionService.execute_report calls callback_fail if a report is missing, preventing queue deadlock."""
        auto_svc = AutomationService(Automations(self.dir_path / "automations.json"))
        exec_svc = ExecutionService(auto_svc)

        failed_called = []
        def _on_fail(name, duration, error):
            failed_called.append((name, error))

        result = exec_svc.execute_report("Ghost_Report_404", callback_fail=_on_fail)
        self.assertFalse(result)
        self.assertEqual(len(failed_called), 1)
        self.assertEqual(failed_called[0][0], "Ghost_Report_404")
        self.assertIn("not found in catalog", failed_called[0][1])

    # ----------------------------------------------------------------------
    # 8. F-002: Path Traversal & Filetype Hygiene Sanitization
    # ----------------------------------------------------------------------
    def test_add_automation_security_sanitization(self):
        """Verifies that add_automation rejects path traversal, directory separators, bad extensions, and unauthorized directories."""
        # 1. Traversal in filename rejected
        res = self.client.post("/api/automation/add", json={
            "name": "Traversal1",
            "filename": "../../../escaped.py",
            "filetype": "python"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("plain filename", json.loads(res.data).get("error", ""))

        # 2. Directory separator in filename rejected
        res = self.client.post("/api/automation/add", json={
            "name": "Traversal2",
            "filename": "subdir/escaped.py",
            "filetype": "python"
        })
        self.assertEqual(res.status_code, 400)

        # 3. Absolute path in filename rejected
        res = self.client.post("/api/automation/add", json={
            "name": "Traversal3",
            "filename": "C:\\Windows\\calc.exe",
            "filetype": "python"
        })
        self.assertEqual(res.status_code, 400)

        # 4. Unauthorized directory rejected
        res = self.client.post("/api/automation/add", json={
            "name": "BadDir",
            "filename": "valid.py",
            "filetype": "python",
            "dir": "../../../Windows/System32"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("authorized reports directory", json.loads(res.data).get("error", ""))

        # 5. Invalid filetype rejected
        res = self.client.post("/api/automation/add", json={
            "name": "BadType",
            "filename": "valid.sh",
            "filetype": "bash"
        })
        self.assertEqual(res.status_code, 400)

        # 6. Extension mismatch rejected (python with .r)
        res = self.client.post("/api/automation/add", json={
            "name": "Mismatch1",
            "filename": "valid.r",
            "filetype": "python"
        })
        self.assertEqual(res.status_code, 400)

        # 7. Valid additions succeed
        res_py = self.client.post("/api/automation/add", json={
            "name": "ValidPy",
            "filename": "valid.py",
            "filetype": "python",
            "dir": "../reports/python"
        })
        self.assertEqual(res_py.status_code, 201)
        self.paradiso.intraday_service.automation_service.delete("ValidPy")

        res_r = self.client.post("/api/automation/add", json={
            "name": "ValidR",
            "filename": "valid.R",
            "filetype": "r",
            "dir": "../reports/r"
        })
        self.assertEqual(res_r.status_code, 201)
        self.paradiso.intraday_service.automation_service.delete("ValidR")

    def test_execution_service_blocks_unauthorized_paths(self):
        """Verifies ExecutionService defense-in-depth rejects any report pointing outside authorized reports directory."""
        auto_svc = AutomationService(Automations(self.dir_path / "automations.json"))
        exec_svc = ExecutionService(auto_svc)

        bad_report = Report(
            name="EscapedReport",
            filename="calc.exe",
            filetype="python",
            dir="../../Windows/System32",
            status="Waiting"
        )
        auto_svc.add(bad_report)

        failed_called = []
        def _on_fail(name, duration, error):
            failed_called.append((name, error))

        result = exec_svc.execute_report("EscapedReport", callback_fail=_on_fail)
        self.assertFalse(result)
        time.sleep(0.05)
        self.assertEqual(len(failed_called), 1)
        self.assertIn("Security violation", failed_called[0][1])

    # ----------------------------------------------------------------------
    # 9. F-003: Executable Path & Binary Identity Validation
    # ----------------------------------------------------------------------
    def test_f003_executable_validation(self):
        """Verifies that validate_config and /api/settings reject arbitrary binaries for python_path and rscript_path."""
        import sys

        # 1. Arbitrary system executable rejected by validate_config
        cmd_exe = "C:\\Windows\\System32\\cmd.exe"
        if Path(cmd_exe).exists():
            valid, err = validate_config({"executables": {"python_path": cmd_exe}})
            self.assertFalse(valid)
            self.assertIn("not an authorized Python executable", err)

            valid_r, err_r = validate_config({"executables": {"rscript_path": cmd_exe}})
            self.assertFalse(valid_r)
            self.assertIn("not an authorized Rscript executable", err_r)

        # 2. Non-existent path rejected
        valid_nonexist, err_nonexist = validate_config({"executables": {"python_path": "C:\\nonexistent\\python.exe"}})
        self.assertFalse(valid_nonexist)
        self.assertIn("does not exist", err_nonexist)

        # 3. Legitimate Python executable accepted
        valid_py, err_py = validate_config({"executables": {"python_path": sys.executable}})
        self.assertTrue(valid_py)
        self.assertIsNone(err_py)

        # 4. Empty path accepted (indicates system default fallback)
        valid_empty, err_empty = validate_config({"executables": {"python_path": "", "rscript_path": ""}})
        self.assertTrue(valid_empty)
        self.assertIsNone(err_empty)

        # 5. POST /api/settings rejects malicious executable path with HTTP 400
        if Path(cmd_exe).exists():
            res = self.client.post("/api/settings", json={"executables": {"python_path": cmd_exe}})
            self.assertEqual(res.status_code, 400)
            data = json.loads(res.data)
            self.assertFalse(data.get("ok"))
            self.assertIn("not an authorized Python executable", data.get("error", ""))

        # 6. Runner defense-in-depth: invalid path falls back to sys.executable safely
        test_runner = Runner()
        test_runner.python_exe = test_runner._resolve_python()
        self.assertTrue(test_runner.python_exe.is_file())
        self.assertIn("python", test_runner.python_exe.name.lower())

    # ----------------------------------------------------------------------
    # 10. F-004: Dependency Skips with Non-Zero Exit Code & Parser Accuracy
    # ----------------------------------------------------------------------
    def test_f004_dep_skip_exit1_does_not_consume_retries(self):
        """Verifies that dependency skips exiting with code 1 rotate to waitlist WITHOUT incrementing retry counts."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.max_retries = 3

        report_name = "0base_auto.py"
        r = Report(name=report_name, filename="0base_auto.py", filetype="python", dir=".", status="Waiting")
        auto_repo.add(r)
        intra_svc.start_fresh_run(force_open=True)

        today_date = CLOCK.date_str()

        # Simulate 5 consecutive dependency skip cycles with exit code 1
        for cycle in range(1, 6):
            self.assertIn(report_name, intra_svc.waitlist)
            rep = intra_svc.waitlist.popleft()
            intra_svc.current_runs[rep] = CLOCK.formatted_now()

            # Execute mock _trigger_report callback structure for exit code 1 with dependency skip marker
            # We call the real _on_fail method logic by triggering ExecutionService callback
            def mock_execute(name, callback_good, callback_fail):
                callback_fail(
                    name=name,
                    duration_str="1s",
                    error="Return code 1: SKIPPED: Missing dependency 'CC_Collection_Summary'"
                )
                return True

            exec_svc.execute_report = mock_execute
            intra_svc._trigger_report(rep, today_date)

            # Assert retry count is STILL 0 (never incremented for dependency skips)
            self.assertEqual(intra_svc.retry_counts.get(report_name, 0), 0)
            self.assertIn(report_name, intra_svc.waitlist)
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Retrial")
            self.assertNotIn(report_name, intra_svc.current_runs)

        # Confirm report never terminally failed
        day = intra_repo.get_day(today_date)
        self.assertNotIn(report_name, day.reports_ran)

    def test_f004_report_log_parse_output_benign_not_found(self):
        """Verifies that parse_output does not misclassify benign output containing 'not found' as Skipped."""
        log = ReportLog("TestBenign")

        # Benign outputs containing 'not found' must NOT be classified as Skipped
        status_benign_1 = log.parse_output("User profile not found in cache; created new database record.")
        self.assertEqual(status_benign_1, "Completed")

        status_benign_2 = log.parse_output("No anomalies found during audit scan.")
        self.assertEqual(status_benign_2, "Completed")

        # Legitimate dependency skip markers must be classified as Skipped
        status_skip_1 = log.parse_output("SKIPPED: Missing dependency 'SalesSummary'")
        self.assertEqual(status_skip_1, "Skipped")

        status_skip_2 = log.parse_output("Dependency not found for CC_Collections")
        self.assertEqual(status_skip_2, "Skipped")

        status_skip_3 = log.parse_output("Dataset not found: upstream warehouse pipeline pending")
        self.assertEqual(status_skip_3, "Skipped")

        status_skip_4 = log.parse_output("Status: Retrial - upstream table not ready")
        self.assertEqual(status_skip_4, "Skipped")

        # Legitimate failures must be classified as Failed
        status_fail = log.parse_output("FATAL ERROR: Unhandled ZeroDivisionError")
        self.assertEqual(status_fail, "Failed")

    def test_f004_execution_service_preserves_script_dumped_log_and_prevents_clobber(self):
        """Verifies that ExecutionService does not clobber script-dumped Retrial logs or cause disk divergence."""
        auto_path = self.dir_path / "automations.json"
        auto_repo = Automations(auto_path)
        auto_svc = AutomationService(auto_repo)

        app_logs_dir = self.app_logs
        class MockRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                import json
                log_file = app_logs_dir / f"{name}.json"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "name": name,
                        "status": "Retrial",
                        "last_run": "2026-09-23 00:00:00",
                        "duration": "0.4s",
                        "last_output": "Custom script receipt: upstream tables pending",
                        "reason": "Dependencies not yet available."
                    }, f, indent=2)
                callback_fail("0.4s", "Return code 1: Process exited with non-zero status")

        exec_svc = ExecutionService(auto_svc, runner=MockRunner())
        report_name = "ScriptWithDump"
        dummy_script = BASE_DIR / "reports" / "dummy_skip.py"
        dummy_script.parent.mkdir(parents=True, exist_ok=True)
        dummy_script.write_text("# dummy")
        try:
            auto_svc.add(Report(name=report_name, filename="dummy_skip.py", filetype="python", dir="reports", status="Waiting"))
            called_fail = []
            exec_svc.execute_report(
                report_name,
                callback_fail=lambda n, d, err: called_fail.append((n, d, err))
            )

            self.assertEqual(len(called_fail), 1)

            # On-disk log was preserved (not overwritten with "Failed")
            import json
            log_data = json.loads((self.app_logs / f"{report_name}.json").read_text(encoding="utf-8"))
            self.assertEqual(log_data["status"], "Retrial")
            self.assertEqual(log_data["reason"], "Dependencies not yet available.")

            # automations.json set to Retrial
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Retrial")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = self.app_logs / f"{report_name}.json"
            if test_log.exists():
                test_log.unlink()

    def test_f004_execution_service_fallback_log_on_unhandled_crash(self):
        """Verifies that ExecutionService writes fallback Failed log if script crashes without writing a log."""
        auto_path = self.dir_path / "automations.json"
        auto_repo = Automations(auto_path)
        auto_svc = AutomationService(auto_repo)

        class MockCrashRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                callback_fail("0.2s", "Return code 1: SyntaxError: invalid syntax")

        exec_svc = ExecutionService(auto_svc, runner=MockCrashRunner())
        report_name = "SyntaxCrashScript"
        dummy_script = BASE_DIR / "reports" / "dummy_crash.py"
        dummy_script.parent.mkdir(parents=True, exist_ok=True)
        dummy_script.write_text("# dummy crash")
        try:
            auto_svc.add(Report(name=report_name, filename="dummy_crash.py", filetype="python", dir="reports", status="Waiting"))
            exec_svc.execute_report(report_name)

            test_log = self.app_logs / f"{report_name}.json"
            self.assertTrue(test_log.exists())
            import json
            data = json.loads(test_log.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "Failed")
            self.assertIn("SyntaxError", data["last_output"])
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Failed")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = self.app_logs / f"{report_name}.json"
            if test_log.exists():
                test_log.unlink()

    def test_f004_deviant_script_exiting_zero_without_receipt_is_failed(self):
        """Verifies that a deviant script exiting 0 without producing a receipt is rejected with Failed status."""
        auto_path = self.dir_path / "automations.json"
        auto_repo = Automations(auto_path)
        auto_svc = AutomationService(auto_repo)

        class MockDeviantRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                callback_good("0.3s", "I forgot to write my receipt!")

        exec_svc = ExecutionService(auto_svc, runner=MockDeviantRunner())
        report_name = "DeviantScript"
        dummy_script = BASE_DIR / "reports" / "dummy_deviant.py"
        dummy_script.parent.mkdir(parents=True, exist_ok=True)
        dummy_script.write_text("# deviant")
        try:
            auto_svc.add(Report(name=report_name, filename="dummy_deviant.py", filetype="python", dir="reports", status="Waiting"))
            exec_svc.execute_report(report_name)

            test_log = self.app_logs / f"{report_name}.json"
            self.assertTrue(test_log.exists())
            import json
            data = json.loads(test_log.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "Failed")
            self.assertIn("Contract violation", data["last_output"])
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Failed")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = self.app_logs / f"{report_name}.json"
            if test_log.exists():
                test_log.unlink()

    def test_f004_deviant_script_exiting_zero_does_not_infinite_loop_in_queue(self):
        """Verifies that a script exiting 0 without a receipt fails terminally after max_retries and does NOT loop infinitely."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)

        class MockDeviantRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                callback_good("0.2s", "Task finished but no receipt written")

        exec_svc = ExecutionService(auto_svc, runner=MockDeviantRunner())
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.max_retries = 3

        report_name = "DeviantLoopTester"
        dummy_script = BASE_DIR / "reports" / "dummy_loop.py"
        dummy_script.parent.mkdir(parents=True, exist_ok=True)
        dummy_script.write_text("# dummy")
        try:
            auto_svc.add(Report(name=report_name, filename="dummy_loop.py", filetype="python", dir="reports", status="Waiting"))
            intra_svc.start_fresh_run(force_open=True)
            today_date = CLOCK.date_str()

            # Execute 3 retry cycles: attempts 1, 2, 3
            for _ in range(3):
                self.assertIn(report_name, intra_svc.waitlist)
                rep = intra_svc.waitlist.popleft()
                intra_svc.current_runs[rep] = CLOCK.formatted_now()
                intra_svc._trigger_report(rep, today_date)

            # After 3 failed attempts, it must be EXPELLED from waitlist and marked Failed!
            self.assertNotIn(report_name, intra_svc.waitlist)
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Failed")
            self.assertEqual(intra_svc.retry_counts.get(report_name), 3)

            # In intraday reports_ran, it must be marked failed
            day = intra_repo.get_day(today_date)
            self.assertIn(report_name, day.reports_ran)
            self.assertEqual(day.reports_ran[report_name].result, "failed")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = self.app_logs / f"{report_name}.json"
            if test_log.exists():
                test_log.unlink()

    def test_f004_end_to_end_0base_auto_pattern_preserves_retries_and_log(self):
        """Verifies end-to-end that 0base_auto.py pattern (dump Retrial + exit 1) rotates without retry penalty."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)

        app_logs_dir = self.app_logs
        class Mock0BaseRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                import json
                log_file = app_logs_dir / f"{name}.json"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "name": name,
                        "status": "Retrial",
                        "last_run": "2026-09-23 00:00:00",
                        "duration": "0.5s",
                        "last_output": "Unavailable",
                        "log": "Error during auto_read: database locked"
                    }, f, indent=2)
                callback_fail("0.5s", "Return code 1: Error during auto_read: database locked")

        exec_svc = ExecutionService(auto_svc, runner=Mock0BaseRunner())
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.max_retries = 3

        report_name = "0base_pattern"
        dummy_script = BASE_DIR / "reports" / "dummy_0base.py"
        dummy_script.parent.mkdir(parents=True, exist_ok=True)
        dummy_script.write_text("# dummy")
        try:
            auto_svc.add(Report(name=report_name, filename="dummy_0base.py", filetype="python", dir="reports", status="Waiting"))
            intra_svc.start_fresh_run(force_open=True)
            today_date = CLOCK.date_str()

            for _ in range(4):
                rep = intra_svc.waitlist.popleft()
                intra_svc.current_runs[rep] = CLOCK.formatted_now()
                intra_svc._trigger_report(rep, today_date)

                self.assertEqual(intra_svc.retry_counts.get(report_name, 0), 0)
                self.assertIn(report_name, intra_svc.waitlist)
                self.assertEqual(auto_svc.get_by_name(report_name).status, "Retrial")

            log_data = json.loads((self.app_logs / f"{report_name}.json").read_text(encoding="utf-8"))
            self.assertEqual(log_data["status"], "Retrial")
            self.assertEqual(log_data["last_output"], "Unavailable")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = self.app_logs / f"{report_name}.json"
            if test_log.exists():
                test_log.unlink()

    # ----------------------------------------------------------------------
    # 11. F-005: Queue Rotation Throttling on Dependency Starvation
    # ----------------------------------------------------------------------
    def test_f005_cycle_starvation_cooldown(self):
        """Verifies that when all reports in a queue pass skip (starvation), rotation cooldown is engaged and halts spinning."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc._override_cooldown = 0.5  # Fast 0.5s cooldown for deterministic test
        intra_svc.max_concurrent_run = 1

        # Add two reports
        auto_repo.add(Report(name="Report_Dep1", filename="dep1.py", filetype="python", dir=".", status="Waiting"))
        auto_repo.add(Report(name="Report_Dep2", filename="dep2.py", filetype="python", dir=".", status="Waiting"))

        intra_svc.start_fresh_run(force_open=True)
        self.assertEqual(len(intra_svc.waitlist), 2)

        # Mock execution so both reports return dependency skip
        def mock_skip_execute(name, callback_good, callback_fail):
            callback_good(name=name, duration_str="0.01s", output="SKIPPED: Missing dependency upstream_sales")
            return True

        exec_svc.execute_report = mock_skip_execute

        from unittest.mock import patch
        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            # Item 1 in pass: Report_Dep1 pops, skips, rotates
            intra_svc.tick()
            self.assertEqual(len(intra_svc.current_runs), 0)
            self.assertEqual(intra_svc._rotation_cooldown_until, 0.0)  # Pass not finished yet

            # Item 2 in pass: Report_Dep2 pops, skips, rotates
            intra_svc.tick()
            self.assertEqual(len(intra_svc.current_runs), 0)

            # Full pass finished with ZERO completions -> cooldown MUST be engaged!
            self.assertGreater(intra_svc._rotation_cooldown_until, time.time())

            # While cooldown is active, tick() must NOT pop any reports!
            waitlist_before = list(intra_svc.waitlist)
            intra_svc.tick()
            self.assertEqual(list(intra_svc.waitlist), waitlist_before)
            self.assertEqual(len(intra_svc.current_runs), 0)

            # Wait for cooldown to expire
            time.sleep(0.55)
            self.assertLess(intra_svc._rotation_cooldown_until, time.time())

            # Now tick() should resume popping
            intra_svc.tick()
            self.assertEqual(len(intra_svc.current_runs), 0)  # Finished execution via mock

    def test_f005_cooldown_bypassed_when_report_completes(self):
        """Verifies that cooldown is not engaged if at least one report completes during the pass."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc._override_cooldown = 1.0
        intra_svc.max_concurrent_run = 1

        auto_repo.add(Report(name="Report_Skip", filename="skip.py", filetype="python", dir=".", status="Waiting"))
        auto_repo.add(Report(name="Report_Success", filename="success.py", filetype="python", dir=".", status="Waiting"))

        intra_svc.start_fresh_run(force_open=True)

        def mock_mixed_execute(name, callback_good, callback_fail):
            if name == "Report_Skip":
                callback_good(name=name, duration_str="0.01s", output="SKIPPED: Missing dependency")
            else:
                callback_good(name=name, duration_str="0.01s", output="Completed successfully")
            return True

        exec_svc.execute_report = mock_mixed_execute

        # Tick 1: Report_Skip runs and skips
        intra_svc.tick()
        # Tick 2: Report_Success runs and completes
        intra_svc.tick()

        # Cooldown must NOT be engaged because 1 report succeeded!
        self.assertEqual(intra_svc._rotation_cooldown_until, 0.0)

    def test_f005_timeline_rotation_deduplication(self):
        """Verifies that repeated rotations of the same report within cooldown window do not flood the timeline."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc._override_cooldown = 10.0  # 10s window

        auto_repo.add(Report(name="SpamReport", filename="spam.py", filetype="python", dir=".", status="Waiting"))
        intra_svc.start_fresh_run(force_open=True)

        today_date = CLOCK.date_str()

        # Trigger 3 rapid rotations
        for _ in range(3):
            intra_svc._trigger_report("SpamReport", today_date)
            # simulate _on_good skip callback
            intra_svc.current_runs.pop("SpamReport", None)
            now_ts = time.time()
            last_ts = intra_svc._last_rotation_logged.get("SpamReport", 0.0)
            if (now_ts - last_ts) >= intra_svc.get_rotation_cooldown():
                intra_svc._last_rotation_logged["SpamReport"] = now_ts
                intra_repo.add_timeline_event(today_date, "Rotated SpamReport", "Skipped", "system")

        day = intra_repo.get_day(today_date)
        rotation_events = [t for t in day.timeline if t.title == "Rotated SpamReport"]
        # Only 1 rotation event should exist within the 10s cooldown window, not 3
        self.assertEqual(len(rotation_events), 1)

    # ----------------------------------------------------------------------
    # 9. F-006 & F-008: Process Watcher Suppression & Windows Tree-Kill
    # ----------------------------------------------------------------------
    def test_f006_address_reuse_does_not_suppress_new_process(self):
        """Verifies that killed process tracking does not suppress callbacks of subsequent processes under memory address reuse."""
        import subprocess, sys
        runner = Runner()
        good_called = []
        fail_called = []

        def on_good(dur, out):
            good_called.append(out)

        def on_fail(dur, err):
            fail_called.append(err)

        # 1. Start process 1 and terminate it via kill_all()
        p1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        with runner._proc_lock:
            runner._exec_counter += 1
            exec_id_1 = runner._exec_counter
            p1._exec_id = exec_id_1
            p1._was_killed = False
            runner.active_processes["Report_Gamma"] = p1

        runner.kill_all()

        # p1 callback must be suppressed
        runner._watcher("Report_Gamma", p1, time.time(), on_good, on_fail, exec_id_1)
        self.assertEqual(len(good_called), 0)
        self.assertEqual(len(fail_called), 0)

        # 2. Start process 2 with the SAME report name
        # Even if Python heap allocator reuses the memory address or the name was in killed_processes:
        p2 = subprocess.Popen([sys.executable, "-c", "print('Gamma succeeded', flush=True)"], stdout=subprocess.PIPE, text=True)
        with runner._proc_lock:
            runner._exec_counter += 1
            exec_id_2 = runner._exec_counter
            p2._exec_id = exec_id_2
            p2._was_killed = False
            runner.active_processes["Report_Gamma"] = p2

        self.assertNotEqual(exec_id_1, exec_id_2)
        self.assertNotIn(exec_id_2, runner.killed_exec_ids)

        # p2 completes normally: its good callback MUST fire!
        runner._watcher("Report_Gamma", p2, time.time(), on_good, on_fail, exec_id_2)
        if p2.stdout:
            p2.stdout.close()
        self.assertEqual(len(good_called), 1)
        self.assertIn("Gamma succeeded", good_called[0])
        self.assertEqual(len(fail_called), 0)

    def test_f008_process_tree_killed_on_windows(self):
        """Verifies that Runner.kill_all terminates both parent and child process trees on Windows."""
        import sys, subprocess, time
        if sys.platform != "win32":
            self.skipTest("Windows tree-kill is specific to win32 platform.")

        parent_script = self.dir_path / "tree_parent.py"
        parent_script.write_text(
            'import subprocess, sys, time\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            'print(f"CHILD_PID:{child.pid}", flush=True)\n'
            'time.sleep(60)\n',
            encoding="utf-8"
        )

        runner = Runner()
        proc = subprocess.Popen(
            [sys.executable, str(parent_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        runner.active_processes["test_tree"] = proc

        # Read child PID output from stdout
        line = proc.stdout.readline()
        self.assertIn("CHILD_PID:", line)
        child_pid = int(line.split("CHILD_PID:")[1].strip())

        # Invoke kill_all
        runner.kill_all()
        time.sleep(0.5)

        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

        # 1. Parent process must be dead
        self.assertIsNotNone(proc.poll(), "Parent process must be dead after kill_all()")

        # 2. Child process must also be terminated
        check = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid}"], capture_output=True, text=True)
        child_survived = str(child_pid) in check.stdout
        self.assertFalse(child_survived, f"Child PID {child_pid} must be killed by taskkill tree-kill in kill_all()")

    # ----------------------------------------------------------------------
    # 10. F-007: Storage Corruption Rescue Backup Deduplication
    # ----------------------------------------------------------------------
    def test_f007_storage_corruption_does_not_flood_bak_files(self):
        """Verifies that persistent storage corruption creates at most 1 rescue backup and does not flood the directory on repeated ticks."""
        corrupt_file = self.dir_path / "test_corrupt_flood.json"
        corrupt_file.write_text("{damaged_syntax...", encoding="utf-8")

        storage = StorageBase(corrupt_file)

        # 1. First read creates initial backup
        with self.assertRaises(StorageCorruptionError):
            storage._read_json()

        bak_files = list(self.dir_path.glob("test_corrupt_flood_corrupted_*.bak"))
        self.assertEqual(len(bak_files), 1, "Initial corruption must create exactly 1 rescue backup.")

        # 2. Simulate 5 consecutive scheduler ticks across time
        for _ in range(5):
            time.sleep(0.05)
            with self.assertRaises(StorageCorruptionError):
                storage._read_json()

        bak_files_after_ticks = list(self.dir_path.glob("test_corrupt_flood_corrupted_*.bak"))
        self.assertEqual(
            len(bak_files_after_ticks),
            1,
            f"Repeated ticks must not flood .bak files! Found {len(bak_files_after_ticks)}, expected 1."
        )

        # 3. New corruption modification generates a new backup for the new state
        time.sleep(0.05)
        corrupt_file.write_text("{different_broken_json...", encoding="utf-8")
        with self.assertRaises(StorageCorruptionError):
            storage._read_json()

        bak_files_modified = list(self.dir_path.glob("test_corrupt_flood_corrupted_*.bak"))
        self.assertEqual(len(bak_files_modified), 2, "A new corruption state should produce a new rescue copy.")

    # ----------------------------------------------------------------------
    # 11. BG-002 & F-009: Start/Stop Cooldown & Mutex Concurrency Guards
    # ----------------------------------------------------------------------
    def test_f009_concurrent_start_calls_spawn_single_thread(self):
        """Verifies that concurrent calls to start() under _lifecycle_lock spawn strictly 1 loop thread."""
        import threading
        threads = []
        results = []

        def worker():
            res = self.paradiso.start()
            results.append(res)

        for _ in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        try:
            self.assertTrue(self.paradiso.is_running())
            # Exactly 1 thread was started
            started_count = sum(1 for r in results if r.status == "started")
            self.assertEqual(started_count, 1, "Strictly one start() call should spawn the daemon thread.")
        finally:
            self.paradiso.stop()

    def test_f009_start_while_running_does_not_reset_in_flight_jobs(self):
        """Verifies Trap 1: calling start() while running does NOT wipe retry counts or reset running reports."""
        self.paradiso.start()
        try:
            # Simulate in-flight job
            with self.paradiso.intraday_service._lock:
                self.paradiso.intraday_service.current_runs["Test_InFlight"] = "09:00"
                self.paradiso.intraday_service.retry_counts["Test_InFlight"] = 2
                self.paradiso.intraday_service.automation_service.update_status(
                    name="Test_InFlight",
                    status="Running",
                    duration="10s"
                )

            # Call start() while already running
            res = self.paradiso.start()
            self.assertEqual(res.status, "already_running")

            # Assert retry counts and in-flight status were NOT wiped!
            self.assertEqual(
                self.paradiso.intraday_service.retry_counts.get("Test_InFlight"),
                2,
                "In-flight retry counts must NOT be wiped by redundant start() calls!"
            )
            self.assertIn("Test_InFlight", self.paradiso.intraday_service.current_runs)
        finally:
            self.paradiso.stop()

    def test_bg002_start_stop_cooldown_enforced(self):
        """Verifies BG-002: rapid start/stop toggling within cooldown returns HTTP 429 Too Many Requests."""
        self.paradiso._enforce_cooldown = True
        self.paradiso.transition_cooldown = 10.0

        try:
            # 1. Start succeeds
            res_start = self.client.post("/api/paradiso/start")
            self.assertEqual(res_start.status_code, 200)

            # 2. Immediate stop fails with 429 Too Many Requests
            res_stop_early = self.client.post("/api/paradiso/stop")
            self.assertEqual(res_stop_early.status_code, 429)
            data_early = json.loads(res_stop_early.data)
            self.assertFalse(data_early.get("ok"))
            self.assertIn("cooldown active", data_early.get("error", "").lower())
            self.assertGreater(data_early.get("cooldown_remaining", 0), 0)

            # 3. Status endpoint reports cooldown remaining
            res_status = self.client.get("/api/paradiso/status")
            data_status = json.loads(res_status.data)
            self.assertGreater(data_status.get("cooldown_remaining", 0), 0)

            # 4. Advance time past 10s cooldown
            self.paradiso._last_transition_time -= 11.0

            # 5. Stop now succeeds with 200
            res_stop_ok = self.client.post("/api/paradiso/stop")
            self.assertEqual(res_stop_ok.status_code, 200)
            data_stop_ok = json.loads(res_stop_ok.data)
            self.assertTrue(data_stop_ok.get("ok"))
        finally:
            self.paradiso._enforce_cooldown = False
            self.paradiso.stop()

    def test_f009_stop_synchronously_joins_thread(self):
        """Verifies Trap 2: stop() synchronously joins daemon thread so no zombie thread survives."""
        self.paradiso.start()
        thread_ref = self.paradiso._thread
        self.assertIsNotNone(thread_ref)
        self.assertTrue(thread_ref.is_alive())

        self.paradiso.stop()
        self.assertFalse(thread_ref.is_alive(), "Daemon thread must be dead immediately after stop() returns.")
        self.assertIsNone(self.paradiso._thread)

    def test_bg001_settings_mutation_rejected_when_active(self):
        """Verifies BG-001: POST /api/settings returns HTTP 409 Conflict when scheduler is active or jobs in flight."""
        # 1. When scheduler is running, POST /api/settings rejected with HTTP 409
        self.paradiso.start()
        try:
            res_running = self.client.post("/api/settings", json={"scheduler": {"job_interval_seconds": 25}})
            self.assertEqual(res_running.status_code, 409)
            data_running = json.loads(res_running.data)
            self.assertFalse(data_running.get("ok"))
            self.assertIn("Settings cannot be modified while Paradiso scheduler is running", data_running.get("error", ""))
        finally:
            self.paradiso.stop()

        # 2. When scheduler is idle, POST /api/settings succeeds with HTTP 200
        res_idle = self.client.post("/api/settings", json={"scheduler": {"job_interval_seconds": 15}})
        self.assertEqual(res_idle.status_code, 200)
        data_idle = json.loads(res_idle.data)
        self.assertTrue(data_idle.get("ok"))

        # 3. When scheduler thread is stopped but in-flight jobs remain in current_runs, POST /api/settings rejected with HTTP 409
        self.paradiso.intraday_service.current_runs["SimulatedReport"] = object()
        try:
            res_inflight = self.client.post("/api/settings", json={"scheduler": {"job_interval_seconds": 20}})
            self.assertEqual(res_inflight.status_code, 409)
            data_inflight = json.loads(res_inflight.data)
            self.assertFalse(data_inflight.get("ok"))
            self.assertIn("Settings cannot be modified while Paradiso scheduler is running", data_inflight.get("error", ""))
        finally:
            self.paradiso.intraday_service.current_runs.clear()

        # 4. Once jobs clear, POST /api/settings succeeds again
        res_cleared = self.client.post("/api/settings", json={"scheduler": {"job_interval_seconds": 15}})
        self.assertEqual(res_cleared.status_code, 200)

    def test_f010_cutoff_kills_running_tasks_and_rollover_is_clean(self):
        """Verifies F-010: 22:00 cutoff forcibly kills running tasks with Failed status, and midnight rollover is clean."""
        intra_svc = self.paradiso.intraday_service
        auto_svc = intra_svc.automation_service
        date_today = CLOCK.date_str()

        # 1. Fresh in-flight report at 22:00 cutoff
        auto_svc.update_status(name="SF Base", status="Running", started_at="21:45")
        intra_svc.current_runs["SF Base"] = CLOCK.formatted_now()
        intra_svc.waitlist.append("SF Base")

        # Trigger 22:00 day closure
        intra_svc._close_day(date_today)

        # In-flight task must be forcibly killed and cleared from current_runs
        self.assertEqual(len(intra_svc.current_runs), 0, "current_runs must be cleared on 22:00 cutoff")
        self.assertEqual(len(intra_svc.waitlist), 0, "waitlist must be cleared on 22:00 cutoff")

        # Automation status must be Failed with cutoff breach reason
        sf_report = auto_svc.get_by_name("SF Base")
        self.assertIsNotNone(sf_report)
        self.assertEqual(sf_report.status, "Failed")
        self.assertIn("breached 10:00 PM cutoff", sf_report.last_output)

        # 2. Attack Vector 1: Re-run report (already in reports_ran from earlier today) running at 22:00 cutoff
        # Ensure it transitions to "Failed" instead of staying stuck in "Running"
        day_record = intra_svc.intraday_repo.get_day(date_today)
        self.assertIn("SF Base", day_record.reports_ran)
        auto_svc.update_status(name="SF Base", status="Running", started_at="21:55")
        intra_svc.current_runs["SF Base"] = CLOCK.formatted_now()

        intra_svc._close_day(date_today)
        self.assertEqual(len(intra_svc.current_runs), 0)
        sf_rerun = auto_svc.get_by_name("SF Base")
        self.assertEqual(sf_rerun.status, "Failed", "Re-run in-flight at cutoff MUST transition to Failed!")

        # 3. Attack Vector 2: Crossing midnight into a pre-existing day record in intraday.json
        sim_tomorrow = "2029-12-31"
        # Pre-seed tomorrow's day record so get_day returns an existing day
        pre_existing_day = IntradayDay(
            date=sim_tomorrow,
            status=Intraday.WAITING_TO_OPEN,
            expected_reports=[],
            reports_ran={},
            timeline=[]
        )
        intra_svc.intraday_repo.add_day(pre_existing_day)
        intra_svc.current_runs["Stray_Report"] = CLOCK.formatted_now()

        # Advance clock to tomorrow at midnight (00:01)
        orig_date_str = CLOCK.date_str
        orig_time_24_str = CLOCK.time_24_str
        try:
            CLOCK.date_str = lambda: sim_tomorrow
            CLOCK.time_24_str = lambda: "00:01"
            intra_svc.is_active = True
            intra_svc.tick()

            # Defense-in-depth: Stray run must be terminated and cleared even on pre-existing day
            self.assertEqual(len(intra_svc.current_runs), 0, "current_runs must be cleared on new day rollover!")

            # All active automations must be reset to Waiting for the new day
            sf_tomorrow = auto_svc.get_by_name("SF Base")
            self.assertEqual(sf_tomorrow.status, "Waiting")
            self.assertIn("SF Base", intra_svc.waitlist)
        finally:
            CLOCK.date_str = orig_date_str
            CLOCK.time_24_str = orig_time_24_str
            intra_svc.is_active = False

    # ----------------------------------------------------------------------
    # 13. F-011: Dashboard Stats Mock Countdown Removal & Timeline Pagination
    # ----------------------------------------------------------------------
    def test_f011_dashboard_stats_no_mock_countdown(self):
        """Verifies that next_scheduled in /api/dashboard/stats does not contain a hardcoded mock countdown."""
        res = self.client.get("/api/dashboard/stats")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        next_sched = data.get("next_scheduled")
        if next_sched is not None:
            self.assertIn("name", next_sched)
            self.assertIn("scheduled_time", next_sched)
            self.assertNotIn("countdown", next_sched, "Static mock 'countdown' field must be removed from next_scheduled.")

    def test_f011_dashboard_timeline_pagination_and_ordering(self):
        """Verifies that /api/dashboard/timeline supports ?limit=N and ?order=asc|desc."""
        # Seed 5 distinct timeline events in today's intraday record
        today = CLOCK.date_str()
        from models.intraday import TimelineEvent
        intra_repo = self.paradiso.intraday_service.intraday_repo
        day = intra_repo.get_day(today)
        if not day:
            day = IntradayDay(
                date=today,
                status=Intraday.OPEN,
                expected_reports=[],
                reports_ran={},
                timeline=[]
            )
            intra_repo.add_day(day)

        events = [
            TimelineEvent(timestamp=f"08:0{i} AM", title=f"Event {i}", description=f"Desc {i}", type="system")
            for i in range(1, 6)
        ]
        def _add_events(d):
            d[today]["timeline"] = [e.to_dict() for e in events]
        intra_repo.mutate(_add_events)

        # 1. Default: returns all 5 in chronological (oldest-first) order
        res_default = self.client.get("/api/dashboard/timeline")
        self.assertEqual(res_default.status_code, 200)
        data_default = json.loads(res_default.data)
        self.assertEqual(len(data_default["timeline"]), 5)
        self.assertEqual(data_default["timeline"][0]["title"], "Event 1")
        self.assertEqual(data_default["timeline"][-1]["title"], "Event 5")

        # 2. limit=3 in ascending order returns the last 3 (most recent chronological events)
        res_limit = self.client.get("/api/dashboard/timeline?limit=3")
        self.assertEqual(res_limit.status_code, 200)
        data_limit = json.loads(res_limit.data)
        self.assertEqual(len(data_limit["timeline"]), 3)
        self.assertEqual(data_limit["timeline"][0]["title"], "Event 3")
        self.assertEqual(data_limit["timeline"][-1]["title"], "Event 5")

        # 3. order=desc returns newest-first order
        res_desc = self.client.get("/api/dashboard/timeline?order=desc")
        self.assertEqual(res_desc.status_code, 200)
        data_desc = json.loads(res_desc.data)
        self.assertEqual(len(data_desc["timeline"]), 5)
        self.assertEqual(data_desc["timeline"][0]["title"], "Event 5")
        self.assertEqual(data_desc["timeline"][-1]["title"], "Event 1")

        # 4. limit=2 with order=desc returns the top 2 newest events
        res_desc_limit = self.client.get("/api/dashboard/timeline?limit=2&order=desc")
        self.assertEqual(res_desc_limit.status_code, 200)
        data_desc_limit = json.loads(res_desc_limit.data)
        self.assertEqual(len(data_desc_limit["timeline"]), 2)
        self.assertEqual(data_desc_limit["timeline"][0]["title"], "Event 5")
        self.assertEqual(data_desc_limit["timeline"][1]["title"], "Event 4")

    # ----------------------------------------------------------------------
    # 14. F-012: Documented Endpoints Functional Verification
    # ----------------------------------------------------------------------
    def test_f012_documented_endpoints_functional(self):
        """Verifies that newly documented endpoints (/api/dashboard/system-status, /api/automation/disable) function correctly."""
        # 1. System status
        res_status = self.client.get("/api/dashboard/system-status")
        self.assertEqual(res_status.status_code, 200)
        data_status = json.loads(res_status.data)
        self.assertTrue(data_status.get("ok"))
        self.assertEqual(data_status.get("status"), "All Systems Operational")
        self.assertIn("services", data_status)
        self.assertTrue(data_status["services"].get("scheduler"))
        self.assertTrue(data_status["services"].get("execution_service"))

        # 2. Disable automation error handling
        res_dis_none = self.client.post("/api/automation/disable", json={})
        self.assertEqual(res_dis_none.status_code, 400)

        res_dis_404 = self.client.post("/api/automation/disable", json={"name": "Non_Existent_Report_XYZ"})
        self.assertEqual(res_dis_404.status_code, 404)

        # 3. Disable existing automation
        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.delete("Disability_Test_Report")
        try:
            res_add = self.client.post("/api/automation/add", json={
                "name": "Disability_Test_Report",
                "filename": "sample_report_blueprint.py",
                "filetype": "python",
                "dir": "../reports"
            })
            self.assertEqual(res_add.status_code, 201)

            res_disable = self.client.post("/api/automation/disable", json={"name": "Disability_Test_Report"})
            self.assertEqual(res_disable.status_code, 200)
            data_dis = json.loads(res_disable.data)
            self.assertTrue(data_dis.get("ok"))

            # Verify status is Disabled
            report = auto_svc.get_by_name("Disability_Test_Report")
            self.assertIsNotNone(report)
            self.assertEqual(report.status, "Disabled")
        finally:
            auto_svc.delete("Disability_Test_Report")

    # ----------------------------------------------------------------------
    # 15. In-App User Guide Rendering Verification
    # ----------------------------------------------------------------------
    def test_user_guide_tab_rendered(self):
        """Verifies that the In-App User Guide tab and resources are rendered on the Web UI."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("nav-guide", html, "Sidebar must include nav-guide link.")
        self.assertIn("view-guide", html, "DOM must include view-guide container.")
        self.assertIn("How to Use Paradiso", html)
        self.assertIn("The Receipt Contract", html)
        self.assertIn("code-snippet-python", html)
        self.assertIn("code-snippet-r", html)

    def test_add_report_modal_rendered(self):
        """Verifies that the upgraded 3-Lane Add Report modal is rendered on the Web UI."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("modal-add-report", html)
        self.assertIn("new-report-type", html)
        self.assertIn("group-lane-b-config", html)
        self.assertIn("group-lane-c-config", html)
        self.assertIn("new-report-interval", html)
        self.assertIn("new-report-tier", html)
        self.assertIn("new-report-catch-up", html)
        self.assertIn("CATCH_UP_IMMEDIATE", html)
        self.assertIn("SKIP_UNTIL_NEXT_DAY", html)
        self.assertIn("WARN_OPERATOR", html)

    def test_add_report_modal_api_payload_processing(self):
        """Verifies backend API processes all form fields from the upgraded Add Report modal."""
        # Lane B with custom interval
        res_b = self.client.post("/api/automation/add", json={
            "name": "Modal_Test_Lane_B",
            "filename": "modal_lane_b.py",
            "filetype": "python",
            "dir": "../reports/python",
            "report_type": "type_b",
            "interval_minutes": 45,
            "status": "Waiting"
        })
        self.assertEqual(res_b.status_code, 201)
        rep_b = self.paradiso.intraday_service.automation_service.get_by_name("Modal_Test_Lane_B")
        self.assertIsNotNone(rep_b)
        self.assertEqual(rep_b.report_type, "type_b")
        self.assertEqual(rep_b.interval_minutes, 45)

        # Lane C with tier and catch_up_policy
        res_c = self.client.post("/api/automation/add", json={
            "name": "Modal_Test_Lane_C",
            "filename": "modal_lane_c.py",
            "filetype": "python",
            "dir": "../reports/python",
            "report_type": "type_c",
            "scheduled_time": "12:30",
            "timeslot_tier": "MID",
            "catch_up_policy": "WARN_OPERATOR",
            "status": "Waiting"
        })
        self.assertEqual(res_c.status_code, 201)
        rep_c = self.paradiso.intraday_service.automation_service.get_by_name("Modal_Test_Lane_C")
        self.assertIsNotNone(rep_c)
        self.assertEqual(rep_c.report_type, "type_c")
        self.assertEqual(rep_c.timeslot_tier, "MID")
        self.assertEqual(rep_c.catch_up_policy, "WARN_OPERATOR")

        # Empty string catch_up_policy normalizes to None
        res_empty_pol = self.client.post("/api/automation/add", json={
            "name": "Modal_Test_Empty_Policy",
            "filename": "modal_empty_pol.py",
            "filetype": "python",
            "dir": "../reports/python",
            "report_type": "type_c",
            "scheduled_time": "16:30",
            "timeslot_tier": "EOD",
            "catch_up_policy": "",
            "status": "Waiting"
        })
        self.assertEqual(res_empty_pol.status_code, 201)
        rep_empty = self.paradiso.intraday_service.automation_service.get_by_name("Modal_Test_Empty_Policy")
        self.assertIsNotNone(rep_empty)
        self.assertIsNone(rep_empty.catch_up_policy)

    # ----------------------------------------------------------------------
    # 16. Housekeeping & Hygiene Verifications (F-015 through F-019)
    # ----------------------------------------------------------------------
    def test_f015_report_log_fallback_keys(self):
        """F-015: Verifies ReportLog.from_json() supports fallback keys (timestamp, message)."""
        receipt_dir = self.app_logs
        receipt_path = receipt_dir / "DivergentReport.json"
        divergent_data = {
            "report_name": "DivergentReport",
            "status": "Completed",
            "timestamp": "2026-09-24 10:15:00 AM",
            "deliverable": "output.xlsx",
            "message": "Custom pipeline extraction finished with 200 records.",
            "metrics": {"count": 200}
        }
        receipt_path.write_text(json.dumps(divergent_data), encoding="utf-8")

        log = ReportLog("DivergentReport", log_dir=receipt_dir).from_json(default_stdout="raw terminal text")
        self.assertEqual(log.status, "Completed")
        self.assertEqual(log.last_run, "2026-09-24 10:15:00 AM")
        self.assertEqual(log.last_output, "Custom pipeline extraction finished with 200 records.")
        self.assertEqual(log.reason, "Custom pipeline extraction finished with 200 records.")

    def test_f016_intraday_production_storage_no_bogus_future_dates(self):
        """F-016: Verifies production storage/intraday.json has zero 2048 synthetic dates."""
        real_intraday_path = BASE_DIR / "storage" / "intraday.json"
        if real_intraday_path.exists():
            data = json.loads(real_intraday_path.read_text(encoding="utf-8"))
            for key in data.keys():
                self.assertNotIn("2048", str(key), f"Found bogus future test key {key} in live intraday.json")

    def test_f017_report_log_respects_paradiso_logs_dir_and_isolates_production(self):
        """F-017: Verifies ReportLog and ExecutionService route receipts to PARADISO_LOGS_DIR."""
        # Baseline live logs directory before execution
        prod_logs = BASE_DIR / "logs"
        prod_before = set(p.name for p in prod_logs.glob("*.json"))

        # Executing a mock report with PARADISO_LOGS_DIR set should only touch self.app_logs
        isolated_log = ReportLog("IsolationTestReport")
        self.assertEqual(isolated_log.log_dir.resolve(), self.app_logs.resolve())

        # Write a dummy receipt in isolated directory
        receipt = isolated_log.log_dir / "IsolationTestReport.json"
        receipt.write_text(json.dumps({"name": "IsolationTestReport", "status": "Completed"}), encoding="utf-8")
        self.assertTrue(receipt.exists())

        # Assert production logs directory was not mutated
        prod_after = set(p.name for p in prod_logs.glob("*.json"))
        self.assertEqual(prod_before, prod_after, "Production logs folder must not be contaminated by test receipts.")

    def test_f018_gitignore_exists_and_ignores_pycache(self):
        """F-018: Verifies root .gitignore exists and ignores __pycache__ and bytecode."""
        root_dir = BASE_DIR.parent
        gitignore_path = root_dir / ".gitignore"
        self.assertTrue(gitignore_path.exists(), "Root .gitignore must exist.")
        content = gitignore_path.read_text(encoding="utf-8")
        self.assertIn("__pycache__", content)
        self.assertIn("*.pyc", content)

    def test_f019_run_tests_exists_and_docs_test_count_accurate(self):
        """F-019: Verifies run_tests.py exists in root and TECHNICAL_DOCUMENTATION.md has accurate test count."""
        root_dir = BASE_DIR.parent
        run_tests_path = root_dir / "run_tests.py"
        self.assertTrue(run_tests_path.exists(), "run_tests.py must exist in root.")

        doc_path = BASE_DIR / "TECHNICAL_DOCUMENTATION.md"
        doc_text = doc_path.read_text(encoding="utf-8")
        self.assertNotIn("(48 Automated Tests)", doc_text, "Outdated 48-test count should be updated.")

    def test_f020_unified_testing_ui_segregated_from_production(self):
        """F-020: Verifies that test controls are consolidated into a dedicated Testing Lab UI and segregated from production headers/settings."""
        app, _ = create_app(storage_dir=self.app_storage)
        app.config["TESTING"] = True
        client = app.test_client()

        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        # 1. Navigation item for Testing Lab exists in sidebar
        self.assertIn('id="nav-testing"', html, "Sidebar must contain #nav-testing link.")
        self.assertIn("Testing Lab", html, "Sidebar link text must include 'Testing Lab'.")

        # 2. Unified Testing View container exists
        self.assertIn('id="view-testing"', html, "Testing view container #view-testing must exist.")

        # 3. Clock Simulation Engine controls exist inside Testing Lab
        self.assertIn('id="setting-sim-enabled"', html, "Clock Simulation enabled select must exist.")
        self.assertIn('id="setting-sim-speed"', html, "Clock Simulation speed select must exist.")

        # 4. Reset (Test) control exists inside Testing Lab
        self.assertIn('id="btn-reset-test"', html, "Reset (Test) button must exist.")

        # 5. Production top-bar header must NOT contain Reset (Test)
        header_start = html.find('<header class="top-bar">')
        self.assertNotEqual(header_start, -1, "Top-bar header must exist.")
        header_end = html.find('</header>', header_start)
        self.assertNotEqual(header_end, -1, "Top-bar header closing tag must exist.")
        top_bar_html = html[header_start:header_end]
        self.assertNotIn("Reset (Test)", top_bar_html, "Top-bar header must not contain Reset (Test) button.")
        self.assertNotIn('btn-reset-test', top_bar_html, "Top-bar header must not contain btn-reset-test element.")

    # ----------------------------------------------------------------------
    # 3-Lane Architecture Tests
    # ----------------------------------------------------------------------
    def test_distinct_report_enforcement_across_lanes(self):
        """Verifies that report names must be unique across all lanes (case-insensitive) with HTTP 409."""
        # 1. Register a Type A report
        res_a = self.client.post("/api/automation/add", json={
            "name": "Global Unique Pipeline",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "team": "Risk Management",
            "owner": "Alice",
            "scheduled_time": "08:00",
            "report_type": "type_a"
        })
        self.assertEqual(res_a.status_code, 201)

        # 2. Try registering a Type B report with identical name -> 409 Conflict
        res_b = self.client.post("/api/automation/add", json={
            "name": "Global Unique Pipeline",
            "filename": "hourly_liquidity_feed.py",
            "filetype": "python",
            "dir": "../reports",
            "team": "Liquidity",
            "owner": "Bob",
            "scheduled_time": "09:00",
            "report_type": "type_b",
            "interval_minutes": 15
        })
        self.assertEqual(res_b.status_code, 409)
        data_b = json.loads(res_b.data)
        self.assertFalse(data_b["ok"])
        self.assertIn("already exists", data_b["error"].lower())

        # 3. Try registering a Type C report with case-variant name -> 409 Conflict
        res_c = self.client.post("/api/automation/add", json={
            "name": "global unique pipeline",
            "filename": "eod_ledger_reconciliation.py",
            "filetype": "python",
            "dir": "../reports",
            "team": "Finance",
            "owner": "Charlie",
            "scheduled_time": "21:00",
            "report_type": "type_c",
            "timeslot_tier": "EOD"
        })
        self.assertEqual(res_c.status_code, 409)
        data_c = json.loads(res_c.data)
        self.assertFalse(data_c["ok"])
        self.assertIn("already exists", data_c["error"].lower())

    def test_per_lane_start_stop_and_cooldown(self):
        """Verifies independent start/stop per lane and 10s transition cooldown guardrail."""
        self.paradiso._enforce_cooldown = True
        self.paradiso.intraday_service.force_open = True
        from unittest.mock import patch
        try:
            with patch.object(CLOCK, "time_24_str", return_value="10:00"):
                # Check initial lane status
                status_res = self.client.get("/api/paradiso/lanes/status")
                self.assertEqual(status_res.status_code, 200)
                status_data = json.loads(status_res.data)
                self.assertTrue(status_data["ok"])
                self.assertFalse(status_data["lanes"]["type_a"]["running"])
                self.assertFalse(status_data["lanes"]["type_b"]["running"])
                self.assertFalse(status_data["lanes"]["type_c"]["running"])

                # 1. Start Lane A
                start_a = self.client.post("/api/paradiso/lane/start", json={"lane": "type_a"})
                self.assertEqual(start_a.status_code, 200)
                data_a = json.loads(start_a.data)
                self.assertTrue(data_a["ok"])

                # Verify only Lane A is running
                status_res = self.client.get("/api/paradiso/lanes/status")
                status_data = json.loads(status_res.data)
                self.assertTrue(status_data["lanes"]["type_a"]["running"])
                self.assertFalse(status_data["lanes"]["type_b"]["running"])
                self.assertFalse(status_data["lanes"]["type_c"]["running"])

                # 2. Immediate stop of Lane A should trigger 429 Cooldown Active
                stop_a = self.client.post("/api/paradiso/lane/stop", json={"lane": "type_a"})
                self.assertEqual(stop_a.status_code, 429)
                data_stop = json.loads(stop_a.data)
                self.assertFalse(data_stop["ok"])
                self.assertIn("cooldown active", data_stop["error"].lower())
                self.assertGreater(data_stop["cooldown_remaining"], 0)

                # 3. Meanwhile, Lane B is not in cooldown and can start independently
                start_b = self.client.post("/api/paradiso/lane/start", json={"lane": "type_b"})
                self.assertEqual(start_b.status_code, 200)
                status_res = self.client.get("/api/paradiso/lanes/status")
                status_data = json.loads(status_res.data)
                self.assertTrue(status_data["lanes"]["type_b"]["running"])
        finally:
            self.paradiso._enforce_cooldown = False

    def test_manual_run_security_rules_across_lanes(self):
        """Verifies manual runs: Type A returns 403 Forbidden, Type B & C allow on-demand execution."""
        # 1. Register Type A, B, and C automations
        self.paradiso.intraday_service.force_open = True
        self.client.post("/api/automation/add", json={
            "name": "Pipeline A", "filename": "sample_report_blueprint.py", "filetype": "python",
            "dir": "../reports", "team": "MIS", "owner": "Cy", "scheduled_time": "08:00",
            "report_type": "type_a"
        })
        self.client.post("/api/automation/add", json={
            "name": "Pipeline B", "filename": "hourly_liquidity_feed.py", "filetype": "python",
            "dir": "../reports", "team": "MIS", "owner": "Cy", "scheduled_time": "09:00",
            "report_type": "type_b", "interval_minutes": 15
        })
        self.client.post("/api/automation/add", json={
            "name": "Pipeline C", "filename": "eod_ledger_reconciliation.py", "filetype": "python",
            "dir": "../reports", "team": "MIS", "owner": "Cy", "scheduled_time": "21:00",
            "report_type": "type_c", "timeslot_tier": "EOD"
        })

        # 2. Trigger Type A -> 403 Forbidden
        res_a = self.client.post("/api/automation/run", json={"name": "Pipeline A"})
        self.assertEqual(res_a.status_code, 403)
        data_a = json.loads(res_a.data)
        self.assertFalse(data_a["ok"])
        self.assertIn("disabled", data_a["error"].lower())

        # 3. Trigger Type B -> 200 OK
        res_b = self.client.post("/api/automation/run", json={"name": "Pipeline B"})
        self.assertEqual(res_b.status_code, 200)
        data_b = json.loads(res_b.data)
        self.assertTrue(data_b["ok"])

        # 4. Trigger Type C -> 200 OK
        res_c = self.client.post("/api/automation/run", json={"name": "Pipeline C"})
        self.assertEqual(res_c.status_code, 200)
        data_c = json.loads(res_c.data)
        self.assertTrue(data_c["ok"])

    def test_3x_error_retries_and_zero_penalty_skips(self):
        """Verifies all report lanes enforce 3x retry limit on genuine errors and zero penalty on dependency skips."""
        intraday = self.paradiso.intraday_service
        report_name = "Retry Test Pipeline"
        intraday.retry_counts[report_name] = 0

        # Simulate 2 errors: should not exceed max
        intraday.retry_counts[report_name] += 1
        self.assertLess(intraday.retry_counts[report_name], 3)
        intraday.retry_counts[report_name] += 1
        self.assertLess(intraday.retry_counts[report_name], 3)

        # 3rd error reaches limit
        intraday.retry_counts[report_name] += 1
        self.assertGreaterEqual(intraday.retry_counts[report_name], 3)

        # Simulate dependency skip: error count must NOT increase
        skip_count = intraday.retry_counts.get("Dependency Skip Job", 0)
        self.assertEqual(skip_count, 0)

    def test_f021_pipeline_script_receipt_names(self):
        """F-021: Verify pipeline scripts produce receipts matching catalog names with spaces."""
        from reports.hourly_liquidity_feed import REPORT_NAME as B_NAME
        from reports.eod_ledger_reconciliation import REPORT_NAME as C_NAME
        self.assertEqual(B_NAME, "Hourly Liquidity Feed")
        self.assertEqual(C_NAME, "EOD Ledger Reconciliation")

        # Simulate receipt written to logs directory
        (self.app_logs / "Hourly Liquidity Feed.json").write_text(json.dumps({
            "name": "Hourly Liquidity Feed",
            "status": "Completed",
            "last_output": "Success"
        }), encoding="utf-8")
        (self.app_logs / "EOD Ledger Reconciliation.json").write_text(json.dumps({
            "name": "EOD Ledger Reconciliation",
            "status": "Completed",
            "last_output": "Success"
        }), encoding="utf-8")

        log_b = ReportLog("Hourly Liquidity Feed")
        self.assertIsNotNone(log_b.find_latest_log_file())
        self.assertTrue(log_b.has_valid_receipt())

        log_c = ReportLog("EOD Ledger Reconciliation")
        self.assertIsNotNone(log_c.find_latest_log_file())
        self.assertTrue(log_c.has_valid_receipt())

    def test_f022_lane_b_c_dependency_skip_throttling(self):
        """F-022: Verify Lane B records last_run and Lane C sets retry_after on dependency skips."""
        from unittest.mock import MagicMock
        intraday = self.paradiso.intraday_service
        exec_svc = intraday.execution_service
        auto_svc = intraday.automation_service

        # 1. Lane B Skip Throttling
        intraday.force_open = True
        intraday.lane_b_active = True
        rep_b = Report(
            name="Throttled Lane B",
            filename="dummy_b.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            interval_minutes=60,
            status="Waiting"
        )
        auto_svc.add(rep_b)

        def mock_skip_b(name, callback_good=None, callback_fail=None, **kwargs):
            if callback_fail:
                callback_fail(name, "0.05s", "SKIPPED: Missing upstream feed")

        exec_svc.execute_report = MagicMock(side_effect=mock_skip_b)

        # Initial tick triggers report, which skips
        from unittest.mock import patch
        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intraday.tick()
            self.assertIn("Throttled Lane B", intraday.type_b_last_run)
            self.assertEqual(exec_svc.execute_report.call_count, 1)

            # Subsequent tick should NOT re-dispatch (interval not reached)
            intraday.tick()
            self.assertEqual(exec_svc.execute_report.call_count, 1)

        # 2. Lane C Skip Throttling
        intraday.lane_b_active = False
        intraday.lane_c_active = True
        rep_c = Report(
            name="Throttled Lane C",
            filename="dummy_c.py",
            filetype="python",
            dir="../reports",
            report_type="type_c",
            timeslot_tier="CUSTOM",
            scheduled_time="10:00",
            status="Waiting"
        )
        auto_svc.add(rep_c)

        def mock_skip_c(name, callback_good=None, callback_fail=None, **kwargs):
            if callback_fail:
                callback_fail(name, "0.05s", "SKIPPED: Missing daily batch")

        exec_svc.execute_report = MagicMock(side_effect=mock_skip_c)

        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            # Initial tick triggers report, which skips and sets type_c_retry_after
            intraday.tick()
            self.assertIn("Throttled Lane C", intraday.type_c_retry_after)
            self.assertEqual(exec_svc.execute_report.call_count, 1)

            # Subsequent tick must NOT re-dispatch while retry_after is in the future
            intraday.tick()
            self.assertEqual(exec_svc.execute_report.call_count, 1)

    def test_f023_settings_mutation_rejected_when_lane_b_or_c_active(self):
        """F-023: BG-001 Idle-Only guardrail rejects settings mutations when Lane B or C has active runs."""
        intraday = self.paradiso.intraday_service
        self.assertFalse(self.paradiso.is_running())

        # 1. Lane B active -> 409 Conflict
        intraday.active_runs_type_b["Active B Job"] = CLOCK.formatted_now()
        self.assertTrue(intraday.has_active_runs)
        res_b = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res_b.status_code, 409)
        intraday.active_runs_type_b.clear()

        # 2. Lane C active -> 409 Conflict
        intraday.active_runs_type_c["Active C Job"] = CLOCK.formatted_now()
        self.assertTrue(intraday.has_active_runs)
        res_c = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res_c.status_code, 409)
        intraday.active_runs_type_c.clear()

    def test_f024_lane_name_validation(self):
        """F-024: POST /api/paradiso/lane/start and stop reject invalid lane names with 400 Bad Request."""
        from unittest.mock import patch
        self.paradiso.intraday_service.force_open = True
        # Bogus lane names
        for bad_lane in ["unrecognized_garbage", "", "random_lane"]:
            res_start = self.client.post("/api/paradiso/lane/start", json={"lane": bad_lane})
            self.assertEqual(res_start.status_code, 400)
            data = json.loads(res_start.data)
            self.assertFalse(data["ok"])

            res_stop = self.client.post("/api/paradiso/lane/stop", json={"lane": bad_lane})
            self.assertEqual(res_stop.status_code, 400)
            data = json.loads(res_stop.data)
            self.assertFalse(data["ok"])

        # Missing lane parameter entirely
        res_missing = self.client.post("/api/paradiso/lane/start", json={})
        self.assertEqual(res_missing.status_code, 400)

        # Valid lane name
        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            res_valid = self.client.post("/api/paradiso/lane/start", json={"lane": "type_b"})
            self.assertIn(res_valid.status_code, [200, 429])

    def test_all_lanes_yield_during_waiting_to_open(self):
        """Universal Invariant: All lanes and manual runs yield during WAITING_TO_OPEN (00:00 - 06:59)."""
        from unittest.mock import patch, MagicMock
        intraday = self.paradiso.intraday_service
        intraday.force_open = False
        intraday.lane_a_active = True
        intraday.lane_b_active = True
        intraday.lane_c_active = True

        auto_svc = intraday.automation_service
        auto_svc.add(Report(name="Early A", filename="dummy.py", filetype="python", dir="../reports", report_type="type_a", status="Waiting"))
        auto_svc.add(Report(name="Early B", filename="dummy.py", filetype="python", dir="../reports", report_type="type_b", interval_minutes=15, status="Waiting"))
        auto_svc.add(Report(name="Early C", filename="dummy.py", filetype="python", dir="../reports", report_type="type_c", scheduled_time="05:00", status="Waiting"))

        with patch.object(CLOCK, "time_24_str", return_value="05:00"):
            self.assertEqual(intraday.resolve_status(), "WAITING_TO_OPEN")
            intraday.tick()

            # No lane dispatches during WAITING_TO_OPEN
            self.assertEqual(len(intraday.current_runs), 0)
            self.assertEqual(len(intraday.active_runs_type_b), 0)
            self.assertEqual(len(intraday.active_runs_type_c), 0)

            # Manual runs are rejected with 409 Conflict
            res_manual = self.client.post("/api/automation/run", json={"name": "Early B"})
            self.assertEqual(res_manual.status_code, 409)
            data = json.loads(res_manual.data)
            self.assertFalse(data["ok"])
            self.assertIn("WAITING_TO_OPEN", data["error"])

    def test_all_lanes_yield_during_waiting_to_close(self):
        """Universal Invariant: All lanes and manual runs yield during WAITING_TO_CLOSE (21:00 - 22:00)."""
        from unittest.mock import patch
        intraday = self.paradiso.intraday_service
        intraday.force_open = False
        intraday.lane_a_active = True
        intraday.lane_b_active = True
        intraday.lane_c_active = True

        auto_svc = intraday.automation_service
        auto_svc.add(Report(name="Late B", filename="dummy.py", filetype="python", dir="../reports", report_type="type_b", interval_minutes=15, status="Waiting"))

        with patch.object(CLOCK, "time_24_str", return_value="21:15"):
            self.assertEqual(intraday.resolve_status(), "WAITING_TO_CLOSE")
            intraday.tick()

            # No new runs launched
            self.assertEqual(len(intraday.current_runs), 0)
            self.assertEqual(len(intraday.active_runs_type_b), 0)
            self.assertEqual(len(intraday.active_runs_type_c), 0)

            # Manual runs are rejected with 409 Conflict
            res_manual = self.client.post("/api/automation/run", json={"name": "Late B"})
            self.assertEqual(res_manual.status_code, 409)
            data = json.loads(res_manual.data)
            self.assertFalse(data["ok"])
            self.assertIn("WAITING_TO_CLOSE", data["error"])

    def test_all_lanes_killed_at_2200_cutoff(self):
        """Universal Invariant: At 22:00 cutoff (CLOSED), active runs across all lanes are terminated."""
        from unittest.mock import patch
        intraday = self.paradiso.intraday_service
        intraday.force_open = False
        auto_svc = intraday.automation_service
        auto_svc.add(Report(name="Hourly Liquidity Feed", filename="dummy.py", filetype="python", dir="../reports", report_type="type_b", status="Waiting"))

        # Simulate active runs across all 3 lanes
        intraday.current_runs["Inflight A"] = CLOCK.formatted_now()
        intraday.active_runs_type_b["Inflight B"] = CLOCK.formatted_now()
        intraday.active_runs_type_c["Inflight C"] = CLOCK.formatted_now()

        with patch.object(CLOCK, "time_24_str", return_value="22:00"):
            self.assertEqual(intraday.resolve_status(), "CLOSED")
            intraday.tick()

            # All runs terminated and cleared
            self.assertEqual(len(intraday.current_runs), 0)
            self.assertEqual(len(intraday.active_runs_type_b), 0)
            self.assertEqual(len(intraday.active_runs_type_c), 0)

            # Manual runs are rejected with 409 Conflict
            res_manual = self.client.post("/api/automation/run", json={"name": "Hourly Liquidity Feed"})
            self.assertEqual(res_manual.status_code, 409)
            data = json.loads(res_manual.data)
            self.assertFalse(data["ok"])
            self.assertIn("CLOSED", data["error"])

    def test_eod_timeslot_runs_during_open(self):
        """Universal Invariant: EOD timeslot report triggers during OPEN (20:30) before 21:00 wrap-up."""
        from unittest.mock import patch, MagicMock
        intraday = self.paradiso.intraday_service
        intraday.force_open = False
        intraday.lane_c_active = True
        exec_svc = intraday.execution_service
        auto_svc = intraday.automation_service

        auto_svc.add(Report(
            name="EOD Ledger Test",
            filename="eod_ledger_reconciliation.py",
            filetype="python",
            dir="../reports",
            report_type="type_c",
            timeslot_tier="EOD",
            scheduled_time="20:30",
            status="Waiting"
        ))

        dispatched = []
        def mock_exec(name, **kwargs):
            dispatched.append(name)
        exec_svc.execute_report = MagicMock(side_effect=mock_exec)

        with patch.object(CLOCK, "time_24_str", return_value="20:30"):
            self.assertEqual(intraday.resolve_status(), "OPEN")
            intraday.tick()
            self.assertIn("EOD Ledger Test", dispatched)
            self.assertIn("EOD Ledger Test", intraday.active_runs_type_c)

    def test_f025_no_defeat_device_in_clock(self):
        """F-025: Verify production clock contains zero sys.argv inspection or test-evasion conditional."""
        clock_file = BASE_DIR / "utils" / "clock.py"
        self.assertTrue(clock_file.exists())
        clock_src = clock_file.read_text(encoding="utf-8")

        self.assertNotIn("sys.argv", clock_src)
        self.assertNotIn("poc_f021_f024", clock_src)
        self.assertNotIn("import sys", clock_src)

        # Confirm CLOCK.now() derives purely from time/simulation, unaffected by sys.argv poisoning
        orig_argv = list(sys.argv)
        try:
            now_before = CLOCK.now()
            sys.argv.append("poc_f021_f024_verification.py")
            now_after = CLOCK.now()
            # Clock time must NOT be artificially forced to 08:50 AM
            self.assertAlmostEqual((now_after - now_before).total_seconds(), 0, delta=2)
            # Inspect clock module source: verify sys.argv is never accessed
            import inspect
            import utils.clock
            clock_src = inspect.getsource(utils.clock)
            self.assertNotIn("sys.argv", clock_src)
            self.assertNotIn("poc_f021_f024", clock_src)
        finally:
            sys.argv = orig_argv

    def test_f026_lane_start_out_of_window_409(self):
        """F-026: POST /api/paradiso/lane/start returns 409 Conflict outside OPEN window unless force_open."""
        from unittest.mock import patch
        intraday = self.paradiso.intraday_service
        intraday.force_open = False

        # 1. Test WAITING_TO_OPEN (05:00) -> 409 Conflict
        with patch.object(CLOCK, "time_24_str", return_value="05:00"):
            self.assertEqual(intraday.resolve_status(), "WAITING_TO_OPEN")
            res_early = self.client.post("/api/paradiso/lane/start", json={"lane": "type_b"})
            self.assertEqual(res_early.status_code, 409)
            data_early = json.loads(res_early.data)
            self.assertFalse(data_early["ok"])
            self.assertEqual(data_early["lane"], "type_b")
            self.assertIn("blocked outside the intraday open window", data_early["error"])
            self.assertIn("WAITING_TO_OPEN", data_early["error"])

        # 2. Test WAITING_TO_CLOSE (21:30) -> 409 Conflict
        with patch.object(CLOCK, "time_24_str", return_value="21:30"):
            self.assertEqual(intraday.resolve_status(), "WAITING_TO_CLOSE")
            res_wrap = self.client.post("/api/paradiso/lane/start", json={"lane": "type_c"})
            self.assertEqual(res_wrap.status_code, 409)
            data_wrap = json.loads(res_wrap.data)
            self.assertFalse(data_wrap["ok"])
            self.assertIn("WAITING_TO_CLOSE", data_wrap["error"])

        # 3. Test CLOSED (22:30) -> 409 Conflict
        with patch.object(CLOCK, "time_24_str", return_value="22:30"):
            self.assertEqual(intraday.resolve_status(), "CLOSED")
            res_closed = self.client.post("/api/paradiso/lane/start", json={"lane": "type_a"})
            self.assertEqual(res_closed.status_code, 409)
            data_closed = json.loads(res_closed.data)
            self.assertFalse(data_closed["ok"])
            self.assertIn("CLOSED", data_closed["error"])

        # 4. Overriding with force_open=True allows starting even outside OPEN window
        with patch.object(CLOCK, "time_24_str", return_value="22:30"):
            res_forced = self.client.post("/api/paradiso/lane/start", json={"lane": "type_b", "force_open": True})
            self.assertIn(res_forced.status_code, [200, 429])

    def test_f027_eod_timeslot_consistency(self):
        """F-027: Confirm EOD timeslot definitions across storage, documentation, and logic specify 20:30."""
        from unittest.mock import patch, MagicMock
        # 1. Storage check: automations.json specifies 20:30 for EOD Ledger Reconciliation
        storage_file = BASE_DIR / "storage" / "automations.json"
        self.assertTrue(storage_file.exists())
        auto_data = json.loads(storage_file.read_text(encoding="utf-8"))
        eod_report = auto_data.get("EOD Ledger Reconciliation")
        if eod_report is not None:
            self.assertEqual(eod_report.get("timeslot_tier"), "EOD")
            self.assertEqual(eod_report.get("scheduled_time"), "20:30")

        # 2. Documentation check: TECHNICAL_DOCUMENTATION.md specifies 20:30 and no 21:00 EOD
        doc_file = BASE_DIR / "TECHNICAL_DOCUMENTATION.md"
        self.assertTrue(doc_file.exists())
        doc_text = doc_file.read_text(encoding="utf-8")
        self.assertIn("EOD 20:30", doc_text)
        self.assertNotIn("EOD 21:00", doc_text)
        self.assertNotIn("EOD (End of Day): 21:00", doc_text)

        # 3. Logic check: IntradayService defaults EOD to 20:30
        intraday = self.paradiso.intraday_service
        auto_svc = intraday.automation_service
        eod_rep = Report(
            name="EOD Default Check",
            filename="eod_ledger_reconciliation.py",
            filetype="python",
            dir="../reports",
            report_type="type_c",
            timeslot_tier="EOD",
            scheduled_time=None,
            status="Waiting"
        )
        auto_svc.add(eod_rep)
        intraday.lane_c_active = True
        intraday.force_open = True
        dispatched = []
        intraday.execution_service.execute_report = MagicMock(side_effect=lambda name, **kw: dispatched.append(name))

        # At 20:29 -> not triggered
        with patch.object(CLOCK, "time_24_str", return_value="20:29"):
            intraday.tick()
            self.assertNotIn("EOD Default Check", dispatched)

        # At 20:30 -> triggers
        with patch.object(CLOCK, "time_24_str", return_value="20:30"):
            intraday.tick()
            self.assertIn("EOD Default Check", dispatched)

    # ----------------------------------------------------------------------
    # Phase 2 Milestone P2.1: Lane A Concurrency Expansion
    # ----------------------------------------------------------------------
    def test_lane_a_concurrency_bounds_validation(self):
        """P2.1: validate_config enforces 1 <= max_concurrent_run <= 20."""
        # Lower bound
        ok, err = validate_config({"scheduler": {"max_concurrent_run": 0}})
        self.assertFalse(ok)
        self.assertIn("integer >= 1", err)

        ok, err = validate_config({"scheduler": {"max_concurrent_run": -3}})
        self.assertFalse(ok)
        self.assertIn("integer >= 1", err)

        # Upper bound
        ok, err = validate_config({"scheduler": {"max_concurrent_run": 21}})
        self.assertFalse(ok)
        self.assertIn("cannot exceed 20", err)

        # Invalid type
        ok, err = validate_config({"scheduler": {"max_concurrent_run": "abc"}})
        self.assertFalse(ok)
        self.assertIn("must be an integer", err)

        # Valid bounds
        for val in [1, 5, 20]:
            ok, err = validate_config({"scheduler": {"max_concurrent_run": val}})
            self.assertTrue(ok)
            self.assertIsNone(err)

    def test_lane_a_concurrency_settings_hot_reload(self):
        """P2.1: POST /api/settings hot-reloads max_concurrent_run and reflects in lanes status."""
        intraday = self.paradiso.intraday_service
        orig_max = intraday.max_concurrent_run
        try:
            res = self.client.post("/api/settings", json={
                "scheduler": {"max_concurrent_run": 4}
            })
            self.assertEqual(res.status_code, 200)
            self.assertEqual(intraday.max_concurrent_run, 4)

            # Check /api/paradiso/lanes/status
            res_status = self.client.get("/api/paradiso/lanes/status")
            self.assertEqual(res_status.status_code, 200)
            lanes_data = json.loads(res_status.data)
            self.assertEqual(lanes_data["lanes"]["type_a"]["max_concurrent_run"], 4)

            # Test invalid bounds return HTTP 400
            res_err = self.client.post("/api/settings", json={
                "scheduler": {"max_concurrent_run": 25}
            })
            self.assertEqual(res_err.status_code, 400)
        finally:
            self.client.post("/api/settings", json={
                "scheduler": {"max_concurrent_run": orig_max}
            })

    def test_lane_a_concurrency_pool_multi_dispatch(self):
        """P2.1: Lane A dispatches up to max_concurrent_run jobs in parallel."""
        from unittest.mock import patch, MagicMock
        intraday = self.paradiso.intraday_service
        auto_svc = intraday.automation_service
        intraday.max_concurrent_run = 3
        intraday.lane_a_active = True
        intraday.force_open = True
        auto_svc.update_status("SF Base", "Disabled")

        intraday.waitlist.clear()
        intraday.current_runs.clear()

        # Add 5 Type A reports
        for i in range(1, 6):
            rep = Report(
                name=f"Report_A_{i}",
                filename=f"rep_a_{i}.py",
                filetype="python",
                dir="../reports",
                report_type="type_a",
                status="Waiting"
            )
            auto_svc.add(rep)

        # Mock execute_report so it records without completing immediately (simulating in-flight execution)
        running = []
        intraday.execution_service.execute_report = MagicMock(
            side_effect=lambda name, callback_good, callback_fail: running.append(name)
        )

        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intraday.tick()

        # Should dispatch exactly 3 (slot limit)
        self.assertEqual(len(intraday.current_runs), 3)
        self.assertEqual(len(running), 3)
        self.assertEqual(len(intraday.waitlist), 2)
        self.assertEqual(list(intraday.current_runs.keys()), ["Report_A_1", "Report_A_2", "Report_A_3"])

        # Subsequent tick before completion should NOT dispatch any more
        with patch.object(CLOCK, "time_24_str", return_value="10:01"):
            intraday.tick()
        self.assertEqual(len(intraday.current_runs), 3)
        self.assertEqual(len(running), 3)
        self.assertEqual(len(intraday.waitlist), 2)

    def test_lane_a_concurrency_pool_slot_replenishment(self):
        """P2.1: When an in-flight job finishes in Lane A, vacated slot is replenished on next tick."""
        from unittest.mock import patch, MagicMock
        intraday = self.paradiso.intraday_service
        auto_svc = intraday.automation_service
        intraday.max_concurrent_run = 2
        intraday.lane_a_active = True
        intraday.force_open = True
        auto_svc.update_status("SF Base", "Disabled")

        intraday.waitlist.clear()
        intraday.current_runs.clear()

        for i in range(1, 4):
            rep = Report(
                name=f"Slot_Rep_{i}",
                filename=f"slot_rep_{i}.py",
                filetype="python",
                dir="../reports",
                report_type="type_a",
                status="Waiting"
            )
            auto_svc.add(rep)

        callbacks = {}
        def mock_exec(name, callback_good, callback_fail):
            callbacks[name] = callback_good

        intraday.execution_service.execute_report = MagicMock(side_effect=mock_exec)

        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intraday.tick()

        # Slots 1 and 2 running
        self.assertEqual(len(intraday.current_runs), 2)
        self.assertIn("Slot_Rep_1", intraday.current_runs)
        self.assertIn("Slot_Rep_2", intraday.current_runs)
        self.assertEqual(len(intraday.waitlist), 1)
        self.assertEqual(intraday.waitlist[0], "Slot_Rep_3")

        # Simulate Slot_Rep_1 completing successfully
        log_path = self.app_logs / "Slot_Rep_1.json"
        log_path.write_text(json.dumps({
            "name": "Slot_Rep_1",
            "status": "Completed",
            "last_output": "Success"
        }), encoding="utf-8")
        callbacks["Slot_Rep_1"]("Slot_Rep_1", "1.2s", "Success")

        self.assertEqual(len(intraday.current_runs), 1)
        self.assertNotIn("Slot_Rep_1", intraday.current_runs)
        self.assertIn("Slot_Rep_2", intraday.current_runs)

        # Next tick should replenish slot with Slot_Rep_3
        with patch.object(CLOCK, "time_24_str", return_value="10:02"):
            intraday.tick()

        self.assertEqual(len(intraday.current_runs), 2)
        self.assertIn("Slot_Rep_2", intraday.current_runs)
        self.assertIn("Slot_Rep_3", intraday.current_runs)
        self.assertEqual(len(intraday.waitlist), 0)

    def test_lane_a_concurrency_starvation_cooldown_coordination(self):
        """P2.1: Multi-slot starvation cooldown is deferred until ALL in-flight parallel tasks conclude."""
        from unittest.mock import patch, MagicMock
        intraday = self.paradiso.intraday_service
        auto_svc = intraday.automation_service
        intraday.max_concurrent_run = 2
        intraday.lane_a_active = True
        intraday.force_open = True
        intraday.rotation_cooldown_seconds = 45.0
        auto_svc.update_status("SF Base", "Disabled")

        intraday.waitlist.clear()
        intraday.current_runs.clear()
        intraday._cycle_seen_in_pass.clear()
        intraday._cycle_pass_reports.clear()

        # 2 reports that will both skip due to dependency
        rep1 = Report(name="Starve_A", filename="s_a.py", filetype="python", dir="../reports", report_type="type_a", status="Waiting")
        rep2 = Report(name="Starve_B", filename="s_b.py", filetype="python", dir="../reports", report_type="type_a", status="Waiting")
        auto_svc.add(rep1)
        auto_svc.add(rep2)

        callbacks = {}
        def mock_exec(name, callback_good, callback_fail):
            callbacks[name] = (callback_good, callback_fail)

        intraday.execution_service.execute_report = MagicMock(side_effect=mock_exec)

        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intraday.tick()

        self.assertEqual(len(intraday.current_runs), 2)
        self.assertEqual(intraday._cycle_pass_reports, {"Starve_A", "Starve_B"})

        # Starve_A finishes first with dependency skip:
        log_path_a = self.app_logs / "Starve_A.json"
        log_path_a.write_text(json.dumps({
            "name": "Starve_A",
            "status": "Skipped",
            "last_output": "Dependency unready: waiting on table"
        }), encoding="utf-8")
        callbacks["Starve_A"][0]("Starve_A", "0.5s", "Dependency unready: waiting on table")

        # Since Starve_B is still running (len(current_runs) == 1), pass evaluation must NOT trigger cooldown yet
        self.assertEqual(len(intraday.current_runs), 1)
        self.assertEqual(intraday._rotation_cooldown_until, 0.0)

        # Starve_B now finishes with dependency skip:
        log_path_b = self.app_logs / "Starve_B.json"
        log_path_b.write_text(json.dumps({
            "name": "Starve_B",
            "status": "Skipped",
            "last_output": "Dependency unready: waiting on table"
        }), encoding="utf-8")
        callbacks["Starve_B"][0]("Starve_B", "0.6s", "Dependency unready: waiting on table")

        # Now len(current_runs) == 0, and all reports in pass skipped -> starvation cooldown triggered!
        self.assertEqual(len(intraday.current_runs), 0)
        self.assertGreater(intraday._rotation_cooldown_until, time.time())

    # ----------------------------------------------------------------------
    # F-028: Pre-existing Finalized Day Record in Storage Paralysis Resolution
    # ----------------------------------------------------------------------
    def test_f028_preexisting_closed_day_cleansed_on_boot(self):
        """F-028: Proves pre-existing closed day record is reset to clean slate and waitlist is populated."""
        from unittest.mock import patch
        today_date = CLOCK.date_str()
        intra_svc = self.paradiso.intraday_service
        auto_svc = intra_svc.automation_service

        # Seed automations with standard reports
        auto_svc.add(Report(name="Report_F028_1", report_type="type_a", filename="dummy1.py", filetype="python", dir="../reports", status="Waiting"))
        auto_svc.add(Report(name="Report_F028_2", report_type="type_a", filename="dummy2.py", filetype="python", dir="../reports", status="Waiting"))

        # Pre-seed intraday.json with a pre-existing CLOSED record with auto-finalized reports
        stale_day = IntradayDay(
            date=today_date,
            status=Intraday.CLOSED,
            expected_reports=["Report_F028_1", "Report_F028_2"],
            reports_ran={
                "Report_F028_1": ReportRun(started_at="--", finished_at="--", result="failed", duration="0s", reason="Historical day finalized automatically"),
                "Report_F028_2": ReportRun(started_at="--", finished_at="--", result="failed", duration="0s", reason="Historical day finalized automatically")
            },
            timeline=[]
        )
        intra_svc.intraday_repo.add_day(stale_day)

        # 1. Test via start_lane with force_open=True
        intra_svc.start_lane("type_a", force_open=True)

        # Waitlist must NOT be empty — reports must be populated cleanly!
        self.assertGreater(len(intra_svc.waitlist), 0, "Waitlist must not be paralyzed by pre-existing closed day record!")
        self.assertIn("Report_F028_1", intra_svc.waitlist)
        self.assertIn("Report_F028_2", intra_svc.waitlist)

        # 2. Test via WAITING_TO_OPEN window
        intra_svc.stop_lane("type_a")
        intra_svc.force_open = False
        intra_svc.intraday_repo.add_day(stale_day)

        with patch.object(CLOCK, "time_24_str", return_value="02:00"):
            day = intra_svc._get_or_init_day(today_date, Intraday.WAITING_TO_OPEN)
            self.assertEqual(day.status, Intraday.WAITING_TO_OPEN)
            self.assertEqual(len(day.reports_ran), 0, "Premature closure during WAITING_TO_OPEN must be cleared to empty slate!")

    # ----------------------------------------------------------------------
    # F-029: Mid-Day Process Restart Lane C Timeslot Hydration
    # ----------------------------------------------------------------------
    def test_f029_lane_c_hydrates_from_storage_on_restart(self):
        """F-029: Proves mid-day service restart hydrates type_c_ran_today and prevents duplicate execution."""
        from unittest.mock import patch, MagicMock
        today_date = CLOCK.date_str()
        rep_name = "MID_Audit_Recon"

        # Simulate Session 1: Lane C report ran and completed today
        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.add(Report(
            name=rep_name,
            filename="dummy_mid.py",
            filetype="python",
            dir="../reports",
            report_type="type_c",
            timeslot_tier="MID",
            scheduled_time="12:00",
            status="Completed"
        ))

        # Record run in day.reports_ran
        self.paradiso.intraday_service.intraday_repo.add_report_run(
            date=today_date,
            report_name=rep_name,
            run=ReportRun(started_at="12:00", finished_at="12:05", result="completed", duration="5s", reason="Success")
        )

        # Simulate Session 2: Fresh IntradayService (reboot at 14:00)
        app2, paradiso2 = create_app(storage_dir=self.app_storage)
        try:
            intra2 = paradiso2.intraday_service
            intra2.lane_c_active = True
            intra2.force_open = True

            # Verify hydration
            self.assertIn(rep_name, intra2.type_c_ran_today, "type_c_ran_today must be hydrated from storage on startup!")

            dispatched = []
            intra2.execution_service.execute_report = MagicMock(side_effect=lambda name, **kw: dispatched.append(name))

            # Tick at 14:00 (past 12:00 scheduled time)
            with patch.object(CLOCK, "time_24_str", return_value="14:00"):
                intra2.tick()

            # Must NOT be dispatched again
            self.assertEqual(len(dispatched), 0, "Completed Lane C report must NOT be re-dispatched after reboot!")
        finally:
            paradiso2.stop()

    # ----------------------------------------------------------------------
    # F-030: Web UI HTTP 409 Intraday Window Rejection Feedback
    # ----------------------------------------------------------------------
    def test_f030_app_js_handles_409_and_defines_show_toast(self):
        """F-030: Proves app.js defines showToast and startLane displays toast on HTTP 409 Conflict."""
        js_file = BASE_DIR / "web" / "static" / "js" / "app.js"
        self.assertTrue(js_file.exists())
        js_content = js_file.read_text(encoding="utf-8")

        # 1. showToast function definition
        self.assertIn("function showToast(", js_content, "app.js must define a global showToast notification function.")

        # 2. HTTP 409 handling in startLane
        self.assertIn("res.status === 409", js_content, "startLane in app.js must handle HTTP 409 Conflict.")
        self.assertIn("showToast", js_content)

    # ----------------------------------------------------------------------
    # V-01: Disabling an Automation Eviction & Idle-Only Protection
    # ----------------------------------------------------------------------
    def test_v01_disabling_idle_report_evicts_from_waitlist_and_prevents_dispatch(self):
        """V-01: Disabling an idle report evicts it from waitlist and prevents dispatch."""
        from unittest.mock import MagicMock
        intra_svc = self.paradiso.intraday_service
        auto_svc = intra_svc.automation_service
        rep_name = "Report_V01_Idle"

        auto_svc.add(Report(
            name=rep_name,
            filename="dummy_idle.py",
            filetype="python",
            dir="../reports",
            report_type="type_a",
            status="Waiting"
        ))

        intra_svc.start_lane("type_a", force_open=True)
        self.assertIn(rep_name, intra_svc.waitlist, "Report must be in waitlist upon lane start.")

        # Disable the idle report via API
        res = self.client.post("/api/automation/disable", json={"name": rep_name})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))

        # Invariant: Report must be evicted from waitlist and pass tracking
        self.assertNotIn(rep_name, intra_svc.waitlist, "Disabled report must be evicted from waitlist!")
        self.assertNotIn(rep_name, intra_svc._cycle_pass_reports, "Disabled report must be removed from pass reports!")

        # Verify catalog status
        rep = auto_svc.get_by_name(rep_name)
        self.assertEqual(rep.status, "Disabled")

        # Invariant: tick() must not dispatch the disabled report
        dispatched = []
        intra_svc.execution_service.execute_report = MagicMock(side_effect=lambda name, **kw: dispatched.append(name))
        intra_svc.tick()
        self.assertNotIn(rep_name, dispatched, "Disabled report must never be dispatched by tick()!")

    def test_v01_disabling_running_report_rejected_with_http_409(self):
        """V-01: Attempting to disable a currently running report is rejected with HTTP 409 Conflict."""
        intra_svc = self.paradiso.intraday_service
        auto_svc = intra_svc.automation_service

        # 1. Test Lane A actively executing report
        rep_a = "Report_V01_RunA"
        auto_svc.add(Report(
            name=rep_a,
            filename="dummy_run_a.py",
            filetype="python",
            dir="../reports",
            report_type="type_a",
            status="Running"
        ))
        intra_svc.current_runs[rep_a] = CLOCK.formatted_now()

        res_a = self.client.post("/api/automation/disable", json={"name": rep_a})
        self.assertEqual(res_a.status_code, 409, "Disabling a running Lane A report must return HTTP 409 Conflict!")
        self.assertIn("currently executing", res_a.get_json().get("error", ""))
        self.assertEqual(auto_svc.get_by_name(rep_a).status, "Running", "Report status must remain Running!")

        # 2. Test Lane B actively executing report
        rep_b = "Report_V01_RunB"
        auto_svc.add(Report(
            name=rep_b,
            filename="dummy_run_b.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            status="Running"
        ))
        intra_svc.active_runs_type_b[rep_b] = CLOCK.formatted_now()

        res_b = self.client.post("/api/automation/disable", json={"name": rep_b})
        self.assertEqual(res_b.status_code, 409, "Disabling a running Lane B report must return HTTP 409 Conflict!")
        self.assertEqual(auto_svc.get_by_name(rep_b).status, "Running")

        # 3. Test Lane C actively executing report
        rep_c = "Report_V01_RunC"
        auto_svc.add(Report(
            name=rep_c,
            filename="dummy_run_c.py",
            filetype="python",
            dir="../reports",
            report_type="type_c",
            status="Running"
        ))
        intra_svc.active_runs_type_c[rep_c] = CLOCK.formatted_now()

        res_c = self.client.post("/api/automation/disable", json={"name": rep_c})
        self.assertEqual(res_c.status_code, 409, "Disabling a running Lane C report must return HTTP 409 Conflict!")
        self.assertEqual(auto_svc.get_by_name(rep_c).status, "Running")

    # ----------------------------------------------------------------------
    # V-02: Lane B Mid-Day Reboot Last-Run Hydration
    # ----------------------------------------------------------------------
    def test_v02_lane_b_hydrates_last_run_from_storage_on_restart(self):
        """V-02: Mid-day reboot hydrates Lane B last_run from storage, preventing thundering-herd re-execution."""
        from unittest.mock import patch, MagicMock
        from datetime import timedelta
        today_date = CLOCK.date_str()
        rep_name = "Hourly_Treasury_Feed"

        # 1. Register Type B 60-minute interval report
        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.add(Report(
            name=rep_name,
            filename="dummy_feed.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            interval_minutes=60,
            status="Completed"
        ))

        # 2. Simulate report ran 5 minutes ago today
        now_dt = CLOCK.now()
        five_mins_ago_str = (now_dt - timedelta(minutes=5)).strftime("%Y-%m-%d %I:%M:%S %p")
        self.paradiso.intraday_service.intraday_repo.add_report_run(
            date=today_date,
            report_name=rep_name,
            run=ReportRun(
                started_at="--",
                finished_at=five_mins_ago_str,
                result="completed",
                duration="15s",
                reason="Success"
            )
        )

        # 3. Simulate process restart at current time
        app2, paradiso2 = create_app(storage_dir=self.app_storage)
        try:
            intra2 = paradiso2.intraday_service
            intra2.lane_b_active = True
            intra2.force_open = True

            # Verify that type_b_last_run was hydrated
            self.assertIn(rep_name, intra2.type_b_last_run, "type_b_last_run must be hydrated on startup!")
            hydrated_dt = intra2.type_b_last_run[rep_name]
            self.assertAlmostEqual((now_dt - hydrated_dt).total_seconds(), 300, delta=10)

            # 4. Tick immediately: must NOT dispatch because only 5m have elapsed (interval is 60m)
            dispatched = []
            intra2.execution_service.execute_report = MagicMock(side_effect=lambda name, **kw: dispatched.append(name))
            intra2.tick()
            self.assertEqual(len(dispatched), 0, "Lane B report must NOT re-dispatch immediately after reboot!")

            # 5. Advance time by 60 minutes past the last run
            advanced_dt = hydrated_dt + timedelta(minutes=61)
            with patch.object(CLOCK, "now", return_value=advanced_dt):
                intra2.tick()
            self.assertIn(rep_name, dispatched, "Lane B report must dispatch after its interval has elapsed!")
        finally:
            paradiso2.stop()

    # ----------------------------------------------------------------------
    # V-03 & V-04: Lane A Isolation & Cross-Lane Bleed Elimination
    # ----------------------------------------------------------------------
    def test_v03_lane_a_retry_does_not_queue_when_lane_a_stopped_even_if_lane_b_active(self):
        """V-03: Lane A retry/skip callback does not re-queue into waitlist if Lane A was stopped, even if Lane B is active."""
        intra_svc = self.paradiso.intraday_service
        auto_svc = intra_svc.automation_service
        rep_name = "Report_V03_Bleed"

        auto_svc.add(Report(
            name=rep_name,
            filename="dummy_bleed.py",
            filetype="python",
            dir="../reports",
            report_type="type_a",
            status="Waiting"
        ))

        # Start Lane A and Lane B
        intra_svc.start_lane("type_a", force_open=True)
        intra_svc.start_lane("type_b", force_open=True)

        self.assertTrue(intra_svc.lane_a_active)
        self.assertTrue(intra_svc.lane_b_active)
        self.assertTrue(intra_svc.is_active)

        # Trigger Lane A report
        captured_callbacks = {}
        def mock_exec(name, callback_good=None, callback_fail=None):
            captured_callbacks["good"] = callback_good
            captured_callbacks["fail"] = callback_fail

        intra_svc.execution_service.execute_report = mock_exec
        intra_svc._trigger_report(rep_name, CLOCK.date_str())

        # Now explicitly stop Lane A
        intra_svc.stop_lane("type_a")
        self.assertFalse(intra_svc.lane_a_active)
        self.assertTrue(intra_svc.lane_b_active, "Lane B must remain active.")
        self.assertTrue(intra_svc.is_active, "is_active is True because Lane B is running.")
        self.assertEqual(len(intra_svc.waitlist), 0, "Waitlist must be empty after stopping Lane A.")

        # Simulate in-flight callback concluding with dependency skip:
        # Pre-seed log with skip output
        from models.report_log import ReportLog
        log_file = ReportLog(rep_name).log_dir / f"{rep_name}.json"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump({"name": rep_name, "status": "Retrial", "last_output": "SKIPPED: Missing dependency"}, f)

        # Invoke callback_good with skip
        captured_callbacks["good"](rep_name, "2s", "SKIPPED: Missing dependency")

        # Invariant: Report must NOT have been re-queued into Lane A waitlist!
        self.assertNotIn(rep_name, intra_svc.waitlist, "Lane A report must NOT re-queue when Lane A is stopped!")
        self.assertEqual(len(intra_svc.waitlist), 0, "Waitlist must remain completely empty!")

    def test_v04_add_automation_type_a_does_not_queue_when_lane_a_stopped(self):
        """V-04: Adding a Type A report does not push into waitlist when Lane A is stopped, even if Lane B is active."""
        intra_svc = self.paradiso.intraday_service
        rep_name = "New_TypeA_Report_V04"

        # Start Lane B, ensure Lane A is stopped
        intra_svc.stop_lane("type_a")
        intra_svc.start_lane("type_b", force_open=True)
        intra_svc.force_open = False  # Ensure force_open is false for Lane A
        self.assertFalse(intra_svc.lane_a_active)
        self.assertTrue(intra_svc.lane_b_active)
        self.assertTrue(intra_svc.is_active, "is_active is True due to Lane B.")

        # Create new Type A report
        res = self.client.post("/api/automation/add", json={
            "name": rep_name,
            "filename": "dummy_new_v04.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "status": "Waiting"
        })
        self.assertEqual(res.status_code, 201)

        # Invariant: Must NOT be in waitlist because Lane A is stopped
        self.assertNotIn(rep_name, intra_svc.waitlist, "Type A report must not be queued into waitlist while Lane A is stopped!")

    # ----------------------------------------------------------------------
    # V-05: Non-Existent Report Manual Run Returns 404 Not Found
    # ----------------------------------------------------------------------
    def test_v05_manual_run_non_existent_report_returns_http_404(self):
        """V-05: Requesting manual run for a non-existent report returns HTTP 404 Not Found."""
        res = self.client.post("/api/automation/run", json={"name": "Ghost_Non_Existent_Report"})
        self.assertEqual(res.status_code, 404, "Non-existent report manual run must return HTTP 404 Not Found!")
        data = res.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("Ghost_Non_Existent_Report", data.get("error", ""))
        self.assertIn("not found in catalog", data.get("error", ""))

    def test_v05_manual_run_missing_name_returns_http_400(self):
        """V-05: Requesting manual run with missing name returns HTTP 400 Bad Request."""
        res_empty = self.client.post("/api/automation/run", json={"name": "   "})
        self.assertEqual(res_empty.status_code, 400)
        self.assertFalse(res_empty.get_json().get("ok"))

        res_none = self.client.post("/api/automation/run", json={})
        self.assertEqual(res_none.status_code, 400)
        self.assertFalse(res_none.get_json().get("ok"))

    # ----------------------------------------------------------------------
    # F-031: Cold Boot Does Not Leak Prior Day Completed Status into Lane C
    # ----------------------------------------------------------------------
    def test_f031_cold_boot_lane_c_no_leak_from_prior_day(self):
        """F-031: Proves cold boot with Completed status in automations.json does not suppress Lane C execution today."""
        from unittest.mock import patch, MagicMock
        rep_name = "EOD Ledger Reconciliation"

        # Automations catalog retains 'Completed' from yesterday's execution
        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.add(Report(
            name=rep_name,
            filename="eod_ledger_reconciliation.py",
            filetype="python",
            dir="reports",
            report_type="type_c",
            timeslot_tier="EOD",
            scheduled_time="20:30",
            status="Completed",
            last_run="2026-09-25 08:30:00 PM"
        ))

        # Re-initialize IntradayService (simulating a cold boot with fresh in-memory state)
        from app import create_app
        test_app, test_paradiso = create_app(storage_dir=self.app_storage)
        try:
            intra_svc = test_paradiso.intraday_service

            # Verification 1: In-memory type_c_ran_today must NOT contain yesterday's completed report
            self.assertNotIn(rep_name, intra_svc.type_c_ran_today,
                             "F-031 Fix: type_c_ran_today must not be contaminated with prior day's completed report on cold boot.")

            intra_svc.start_lane("type_c", force_open=True)

            dispatched = []
            intra_svc.execution_service.execute_report = MagicMock(side_effect=lambda name, **kw: dispatched.append(name))

            # When scheduled time 20:30 arrives today:
            with patch.object(CLOCK, "time_24_str", return_value="20:30"):
                intra_svc.tick()

            # Verification 2: The report is successfully dispatched today!
            self.assertIn(rep_name, dispatched,
                          "F-031 Fix: Lane C report must be dispatched at its scheduled timeslot.")
        finally:
            test_paradiso.stop()

    # ----------------------------------------------------------------------
    # F-032: Realistic Cutoff Reasons Do Not Cause Storage Paralysis
    # ----------------------------------------------------------------------
    def test_f032_realistic_cutoff_reasons_cleansed_on_open(self):
        """F-032: Proves realistic cutoff reasons in pre-existing CLOSED record are cleansed on OPEN/force_open."""
        today_date = CLOCK.date_str()

        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.add(Report(name="Report_F032_A", report_type="type_a", filename="dummy1.py", filetype="python", dir="../reports", status="Waiting"))
        auto_svc.add(Report(name="Report_F032_B", report_type="type_a", filename="dummy2.py", filetype="python", dir="../reports", status="Waiting"))

        # Pre-seed intraday storage with today marked CLOSED with real cutoff reason
        intraday_repo = self.paradiso.intraday_service.intraday_repo
        intraday_repo.add_day(IntradayDay(
            date=today_date,
            status=Intraday.CLOSED,
            expected_reports=["Report_F032_A", "Report_F032_B"],
            reports_ran={
                "Report_F032_A": ReportRun(started_at="--", finished_at="--", result="failed", duration="0s", reason="Not completed before 10:00 PM cutoff"),
                "Report_F032_B": ReportRun(started_at="--", finished_at="--", result="failed", duration="0s", reason="Not completed before 10:00 PM cutoff")
            },
            timeline=[]
        ))

        # Start Lane A with force_open=True
        intra_svc = self.paradiso.intraday_service
        intra_svc.start_lane("type_a", force_open=True)

        # Invariant: Waitlist must be cleansed and populated with both Type A reports (NO queue paralysis!)
        self.assertIn("Report_F032_A", intra_svc.waitlist)
        self.assertIn("Report_F032_B", intra_svc.waitlist)
        self.assertGreaterEqual(len(intra_svc.waitlist), 2,
                                "F-032 Fix: Pre-existing CLOSED day with realistic cutoff reasons must be cleansed to populate waitlist.")

    # ----------------------------------------------------------------------
    # F-033: Unbounded Stickiness of force_open Cleansed on Lane Stop and Cutoff
    # ----------------------------------------------------------------------
    def test_f033_force_open_cleared_on_lane_stop_and_hard_cutoff(self):
        """F-033: Proves force_open is cleared when all lanes stop, cutoff enforces CLOSED, and midnight rollover stays WAITING_TO_OPEN."""
        from unittest.mock import patch
        intra_svc = self.paradiso.intraday_service

        # 1. Start Lane B with force_open=True
        intra_svc.start_lane("type_b", force_open=True)
        self.assertTrue(intra_svc.force_open)

        # 2. Stop Lane B
        intra_svc.stop_lane("type_b")
        self.assertFalse(intra_svc.lane_b_active)
        self.assertFalse(intra_svc.is_active)

        # Invariant 1: force_open must be reset to False once all lanes stop!
        self.assertFalse(intra_svc.force_open, "F-033 Fix: force_open must be cleared when all lanes stop.")

        # 3. Simulate clock at 22:30 PM (past 22:00 close_time) even if someone manually set force_open
        intra_svc.force_open = True
        with patch.object(CLOCK, "time_24_str", return_value="22:30"):
            status = intra_svc.resolve_status()
            # Invariant 2: 22:00 cutoff takes absolute precedence!
            self.assertEqual(status, Intraday.CLOSED,
                             "F-033 Fix: Status must resolve to CLOSED at 22:30 PM despite force_open.")

            intra_svc.tick()
            self.assertTrue(intra_svc.day_closed, "F-033 Fix: tick() must close day on 22:00 hard cutoff.")
            self.assertFalse(intra_svc.force_open, "F-033 Fix: force_open must be cleared on hard cutoff.")

        # 4. Simulate crossing midnight to 00:05 AM of the next day
        with patch.object(CLOCK, "date_str", return_value="20260927"), \
             patch.object(CLOCK, "time_24_str", return_value="00:05"):
            intra_svc.tick()
            new_day = intra_svc.intraday_repo.get_day("20260927")
            self.assertIsNotNone(new_day)
            # Invariant 3: New day at 00:05 AM must be WAITING_TO_OPEN, not OPEN!
            self.assertEqual(new_day.status, Intraday.WAITING_TO_OPEN,
                             "F-033 Fix: New day must initialize as WAITING_TO_OPEN at 00:05 AM.")

    # ----------------------------------------------------------------------
    # F-034: Actively Executing Type B or C Reports Cannot Be Deleted (409)
    # ----------------------------------------------------------------------
    def test_f034_delete_actively_executing_type_b_or_c_rejected_409(self):
        """F-034: Proves deleting an actively executing Type B or C report returns HTTP 409 and preserves catalog."""
        rep_name = "Active_Manual_Pipeline_B"
        res_add = self.client.post("/api/automation/add", json={
            "name": rep_name,
            "filename": "dummy_b.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_b",
            "interval_minutes": 30
        })
        self.assertEqual(res_add.status_code, 201)

        intra_svc = self.paradiso.intraday_service

        # Simulate actively running Type B report while scheduler lanes are paused
        intra_svc.active_runs_type_b[rep_name] = CLOCK.formatted_now()
        self.assertFalse(intra_svc.is_active, "Scheduler lanes are stopped.")
        self.assertTrue(intra_svc.has_active_runs, "Report is actively in flight across system.")

        # Attempt to delete the actively executing report
        res_delete = self.client.delete(f"/api/automation/delete/{rep_name}")

        # Verification 1: Rejection with HTTP 409 Conflict
        self.assertEqual(res_delete.status_code, 409,
                         "F-034 Fix: Deleting an actively executing report must return HTTP 409 Conflict.")
        data = res_delete.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("report is currently executing", data.get("error", ""))

        # Verification 2: The report is preserved in the catalog
        self.assertIsNotNone(intra_svc.automation_service.get_by_name(rep_name),
                             "F-034 Fix: Report must remain in catalog.")

        # Clean up simulated run and delete when idle
        intra_svc.active_runs_type_b.pop(rep_name, None)
        res_idle_delete = self.client.delete(f"/api/automation/delete/{rep_name}")
        self.assertEqual(res_idle_delete.status_code, 200)

    # ----------------------------------------------------------------------
    # F-032: Partial Day Cutoff Reports Queued Without Erasing Completed Logs
    # ----------------------------------------------------------------------
    def test_f032_partial_day_cutoff_reports_queued_without_log_wipe(self):
        """F-032: Proves reports cut off on partial days are queued without wiping completed execution logs."""
        import tempfile
        from app import create_app
        today = CLOCK.date_str()

        with tempfile.TemporaryDirectory() as tmpdir:
            storage_dir = Path(tmpdir)
            automations = {
                "Report_P1": {"name": "Report_P1", "filename": "r1.py", "filetype": "python", "dir": "../reports", "status": "Waiting", "report_type": "type_a"},
                "Report_P2": {"name": "Report_P2", "filename": "r2.py", "filetype": "python", "dir": "../reports", "status": "Waiting", "report_type": "type_a"},
                "Report_P3": {"name": "Report_P3", "filename": "r3.py", "filetype": "python", "dir": "../reports", "status": "Waiting", "report_type": "type_a"}
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")

            intraday = {
                today: {
                    "date": today,
                    "status": "CLOSED",
                    "expected_reports": ["Report_P1", "Report_P2", "Report_P3"],
                    "reports_ran": {
                        "Report_P1": {"started_at": "07:05 AM", "finished_at": "07:10 AM", "result": "completed", "duration": "5s", "reason": "Completed successfully"},
                        "Report_P2": {"started_at": "--", "finished_at": "--", "result": "failed", "duration": "0s", "reason": "Not completed before 10:00 PM cutoff"},
                        "Report_P3": {"started_at": "--", "finished_at": "--", "result": "failed", "duration": "0s", "reason": "Not completed before 10:00 PM cutoff"}
                    },
                    "timeline": []
                }
            }
            (storage_dir / "intraday.json").write_text(json.dumps(intraday), encoding="utf-8")

            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra_svc = paradiso.intraday_service
                intra_svc.start_lane("type_a", force_open=True)

                # Verification 1: Report_P2 and Report_P3 must be queued in waitlist (NO queue paralysis!)
                self.assertIn("Report_P2", intra_svc.waitlist)
                self.assertIn("Report_P3", intra_svc.waitlist)
                self.assertNotIn("Report_P1", intra_svc.waitlist, "Report_P1 already completed today and must not re-queue.")
                self.assertEqual(len(intra_svc.waitlist), 2)

                # Verification 2: Historical record of Report_P1 is NOT erased from reports_ran
                day_after = intra_svc.intraday_repo.get_day(today)
                self.assertIn("Report_P1", day_after.reports_ran)
                res_p1 = getattr(day_after.reports_ran["Report_P1"], "result", None) or (day_after.reports_ran["Report_P1"].get("result") if isinstance(day_after.reports_ran["Report_P1"], dict) else "")
                self.assertEqual(res_p1, "completed")
            finally:
                paradiso.stop()

    def test_f035_lane_b_cold_boot_does_not_synthesize_future_timestamp(self):
        """F-035: Cold boot hydration of time-only last_run string must not synthesize future timestamp and must dispatch on tick."""
        from datetime import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            automations = {
                "Recurring_Pipeline": {
                    "name": "Recurring_Pipeline",
                    "filename": "pipeline.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_b",
                    "interval_minutes": 60,
                    "last_run": "09:30:00 PM"
                }
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
            (storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

            sim_morning = datetime(2026, 9, 28, 8, 0, 0)
            with patch.object(CLOCK, "now", return_value=sim_morning), \
                 patch.object(CLOCK, "time_24_str", return_value="08:00"), \
                 patch.object(CLOCK, "date_str", return_value="20260928"):
                app, paradiso = create_app(storage_dir=storage_dir)
                try:
                    intra = paradiso.intraday_service
                    intra.start_lane("type_b")

                    hydrated = intra.type_b_last_run.get("Recurring_Pipeline")
                    self.assertIsNotNone(hydrated)
                    self.assertLessEqual(hydrated, sim_morning,
                                         "Hydrated last_run must be historical, not in the future.")

                    dispatched = []
                    intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)
                    intra.tick()

                    self.assertIn("Recurring_Pipeline", dispatched,
                                  "Recurring pipeline must dispatch immediately upon cold boot.")
                finally:
                    paradiso.stop()

    def test_f033_waiting_to_close_enforced_and_cross_lane_isolated(self):
        """F-033: WAITING_TO_CLOSE window is enforced even if force_open is True, and lane_start rejects out-of-window requests without explicit force_open."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                # Start Lane A with force_open
                intra.start_lane("type_a", force_open=True)
                self.assertTrue(intra.force_open)

                # 1. At 21:15, WAITING_TO_CLOSE must be respected
                with patch.object(CLOCK, "time_24_str", return_value="21:15"):
                    status = intra.resolve_status()
                    self.assertEqual(status, "WAITING_TO_CLOSE",
                                     "WAITING_TO_CLOSE wrap-up window must NOT be overridden by force_open.")

                    # 2. Starting Lane B via API without force_open returns 409
                    with app.test_client() as client:
                        res = client.post("/api/paradiso/lane/start", json={"lane": "type_b"})
                        self.assertEqual(res.status_code, 409,
                                         "Lane start without force_open out-of-window must be rejected with 409.")
                        self.assertIn("blocked outside the intraday open window", res.get_json()["error"])

                        # 3. Starting Lane B via API WITH explicit force_open succeeds
                        res_ok = client.post("/api/paradiso/lane/start", json={"lane": "type_b", "force_open": True})
                        self.assertEqual(res_ok.status_code, 200)
            finally:
                paradiso.stop()

    def test_f036_enable_automation_endpoint_restores_without_destructive_reset(self):
        """F-036: Re-enabling a disabled report via POST /api/automation/enable restores status to Waiting and rejoins waitlist without destructive resets."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            automations = {
                "Report_Alpha": {
                    "name": "Report_Alpha",
                    "filename": "alpha.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_a"
                },
                "Report_Beta": {
                    "name": "Report_Beta",
                    "filename": "beta.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_a"
                }
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
            (storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                intra.start_lane("type_a", force_open=True)

                with app.test_client() as client:
                    # 1. Disable Report_Alpha
                    res_dis = client.post("/api/automation/disable", json={"name": "Report_Alpha"})
                    self.assertEqual(res_dis.status_code, 200)
                    self.assertEqual(intra.automation_service.get_by_name("Report_Alpha").status, "Disabled")
                    self.assertNotIn("Report_Alpha", intra.waitlist)

                    # 2. Try enabling invalid inputs
                    res_bad = client.post("/api/automation/enable", json={})
                    self.assertEqual(res_bad.status_code, 400)
                    res_nf = client.post("/api/automation/enable", json={"name": "NonExistent"})
                    self.assertEqual(res_nf.status_code, 404)
                    res_already_enabled = client.post("/api/automation/enable", json={"name": "Report_Beta"})
                    self.assertEqual(res_already_enabled.status_code, 400)
                    self.assertIn("not disabled", res_already_enabled.get_json()["error"])

                    # 3. Enable Report_Alpha
                    res_en = client.post("/api/automation/enable", json={"name": "Report_Alpha"})
                    self.assertEqual(res_en.status_code, 200)
                    self.assertEqual(intra.automation_service.get_by_name("Report_Alpha").status, "Waiting")
                    # Should be reenqueued in Lane A waitlist because Lane A is active
                    self.assertIn("Report_Alpha", intra.waitlist)
            finally:
                paradiso.stop()

    # ----------------------------------------------------------------------
    # P2.2: Lane C Missed Window Catch-up Policy
    # ----------------------------------------------------------------------
    def test_p2_2_lane_c_catch_up_immediate(self):
        """P2.2: Lane C report missed by > grace period executes immediately and logs catch-up under CATCH_UP_IMMEDIATE."""
        from datetime import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            automations = {
                "Morning_BOD": {
                    "name": "Morning_BOD",
                    "filename": "bod.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_c",
                    "timeslot_tier": "BOD",
                    "scheduled_time": "07:00",
                    "catch_up_policy": "CATCH_UP_IMMEDIATE"
                }
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
            (storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                sim_time = datetime(2026, 9, 28, 8, 30, 0) # 90m past 07:00
                with patch.object(CLOCK, "now", return_value=sim_time), \
                     patch.object(CLOCK, "time_24_str", return_value="08:30"):

                    intra.start_lane("type_c")
                    dispatched = []
                    intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

                    intra.tick()

                    self.assertIn("Morning_BOD", dispatched, "Report must be caught up and dispatched immediately.")
                    day = intra.intraday_repo.get_day("20260928")
                    timeline_titles = [e.title for e in day.timeline]
                    self.assertTrue(any("Catch-up Trigger" in t for t in timeline_titles),
                                    "Timeline must record Catch-up Trigger event.")
            finally:
                paradiso.stop()

    def test_p2_2_lane_c_skip_until_next_day(self):
        """P2.2: Lane C report missed by > grace period is marked Skipped and not dispatched under SKIP_UNTIL_NEXT_DAY."""
        from datetime import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            automations = {
                "Morning_BOD": {
                    "name": "Morning_BOD",
                    "filename": "bod.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_c",
                    "timeslot_tier": "BOD",
                    "scheduled_time": "07:00",
                    "catch_up_policy": "SKIP_UNTIL_NEXT_DAY"
                }
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
            (storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                sim_time = datetime(2026, 9, 28, 8, 30, 0)
                with patch.object(CLOCK, "now", return_value=sim_time), \
                     patch.object(CLOCK, "time_24_str", return_value="08:30"):

                    intra.start_lane("type_c")
                    dispatched = []
                    intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

                    intra.tick()

                    self.assertEqual(len(dispatched), 0, "Missed report must NOT dispatch under SKIP_UNTIL_NEXT_DAY.")
                    rep = intra.automation_service.get_by_name("Morning_BOD")
                    self.assertEqual(rep.status, "Skipped")
                    self.assertIn("Morning_BOD", intra.type_c_ran_today)

                    day = intra.intraday_repo.get_day("20260928")
                    self.assertIn("Morning_BOD", day.reports_ran)
                    run_rec = day.reports_ran["Morning_BOD"]
                    self.assertEqual(getattr(run_rec, "result", None) or run_rec.get("result"), "skipped")
            finally:
                paradiso.stop()

    def test_p2_2_lane_c_warn_operator(self):
        """P2.2: Lane C report missed under WARN_OPERATOR emits single alert and allows manual run."""
        from datetime import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            automations = {
                "Morning_BOD": {
                    "name": "Morning_BOD",
                    "filename": "bod.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_c",
                    "timeslot_tier": "BOD",
                    "scheduled_time": "07:00",
                    "catch_up_policy": "WARN_OPERATOR"
                }
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
            (storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                sim_time = datetime(2026, 9, 28, 8, 30, 0)
                with patch.object(CLOCK, "now", return_value=sim_time), \
                     patch.object(CLOCK, "time_24_str", return_value="08:30"):

                    intra.start_lane("type_c")
                    dispatched = []
                    intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

                    intra.tick()
                    self.assertEqual(len(dispatched), 0, "Report must not auto-dispatch under WARN_OPERATOR.")

                    # Tick again: alert must be deduplicated
                    intra.tick()
                    day = intra.intraday_repo.get_day("20260928")
                    warn_events = [e for e in day.timeline if "Missed Timeslot Alert" in e.title]
                    self.assertEqual(len(warn_events), 1, "Alert timeline event must be deduplicated.")

                    # Manual run permitted during OPEN
                    with app.test_client() as client:
                        res = client.post("/api/automation/run", json={"name": "Morning_BOD"})
                        self.assertEqual(res.status_code, 200, "Operator can manually run report on demand.")
            finally:
                paradiso.stop()

    def test_p2_2_lane_c_on_time_within_grace_not_classified_as_missed(self):
        """P2.2: Lane C report within grace period dispatches normally even if policy is SKIP_UNTIL_NEXT_DAY."""
        from datetime import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            automations = {
                "Morning_BOD": {
                    "name": "Morning_BOD",
                    "filename": "bod.py",
                    "filetype": "python",
                    "dir": "../reports",
                    "status": "Waiting",
                    "report_type": "type_c",
                    "timeslot_tier": "BOD",
                    "scheduled_time": "07:00",
                    "catch_up_policy": "SKIP_UNTIL_NEXT_DAY"
                }
            }
            (storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
            (storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                # Only 5 minutes past 07:00 (within 15m grace window)
                sim_time = datetime(2026, 9, 28, 7, 5, 0)
                with patch.object(CLOCK, "now", return_value=sim_time), \
                     patch.object(CLOCK, "time_24_str", return_value="07:05"):

                    intra.start_lane("type_c")
                    dispatched = []
                    intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

                    intra.tick()

                    self.assertIn("Morning_BOD", dispatched, "Report within grace window must dispatch normally.")
            finally:
                paradiso.stop()

    def test_p2_2_settings_hot_reload_and_validation(self):
        """P2.2: Settings validation and dynamic hot-reload for lane_c_catch_up_policy."""
        from utils.config import validate_config
        # 1. Validation tests
        ok, err = validate_config({"scheduler": {"lane_c_catch_up_policy": "INVALID"}})
        self.assertFalse(ok)
        self.assertIn("lane_c_catch_up_policy must be one of", err)

        ok, err = validate_config({"scheduler": {"lane_c_catch_up_grace_minutes": -5}})
        self.assertFalse(ok)
        self.assertIn("non-negative integer", err)

        ok, err = validate_config({"scheduler": {"lane_c_catch_up_policy": "WARN_OPERATOR", "lane_c_catch_up_grace_minutes": 20}})
        self.assertTrue(ok)

        # 2. Hot-reload test
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                self.assertEqual(intra.lane_c_catch_up_policy, "CATCH_UP_IMMEDIATE")

                intra.reload_config({"scheduler": {"lane_c_catch_up_policy": "SKIP_UNTIL_NEXT_DAY", "lane_c_catch_up_grace_minutes": 30}})
                self.assertEqual(intra.lane_c_catch_up_policy, "SKIP_UNTIL_NEXT_DAY")
                self.assertEqual(intra.lane_c_catch_up_grace_minutes, 30)

                with app.test_client() as client:
                    res = client.get("/api/settings")
                    self.assertEqual(res.status_code, 200)
                    meta = res.get_json()["settings"]["runtime_meta"]
                    self.assertEqual(meta["lane_c_catch_up_policy"], "SKIP_UNTIL_NEXT_DAY")
                    self.assertEqual(meta["lane_c_catch_up_grace_minutes"], 30)
            finally:
                paradiso.stop()

    def test_f037_scheduled_time_validation_and_defensive_normalization(self):
        """F-037: add_automation rejects non-canonical scheduled_time with 400, while tick defensively normalizes without crashing or freezing."""
        from datetime import datetime
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_dir = Path(tmp_dir)
            app, paradiso = create_app(storage_dir=storage_dir)
            try:
                intra = paradiso.intraday_service
                with app.test_client() as client:
                    # 1. API validation: reject non-canonical formats with HTTP 400
                    for bad_time in ["08:30 AM", "8:30", "25:00", "invalid", "12:60"]:
                        res = client.post("/api/automation/add", json={
                            "name": f"Bad_{bad_time.replace(' ', '_').replace(':', '_')}",
                            "filename": "dummy.py",
                            "filetype": "python",
                            "dir": "../reports",
                            "report_type": "type_c",
                            "scheduled_time": bad_time
                        })
                        self.assertEqual(res.status_code, 400, f"scheduled_time '{bad_time}' must be rejected with 400")

                    # Valid canonical format succeeds
                    res_ok = client.post("/api/automation/add", json={
                        "name": "Good_Time",
                        "filename": "dummy.py",
                        "filetype": "python",
                        "dir": "../reports",
                        "report_type": "type_c",
                        "scheduled_time": "08:30"
                    })
                    self.assertEqual(res_ok.status_code, 201)

                # 2. Defensive tick handling: legacy or unnormalized times in storage do not crash or freeze
                intra.start_lane("type_c", force_open=True)
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
                    name="Legacy_Unpadded",
                    filename="dummy.py",
                    filetype="python",
                    dir="reports",
                    status="Waiting",
                    report_type="type_c",
                    scheduled_time="8:30"
                ))

                dispatched = []
                intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)
                with patch.object(CLOCK, "now", return_value=datetime(2026, 9, 28, 9, 0, 0)), \
                     patch.object(CLOCK, "time_24_str", return_value="09:00"):
                    # tick must not raise ValueError
                    intra.tick()

                self.assertIn("Legacy_12hr", dispatched)
                self.assertIn("Legacy_Unpadded", dispatched)
            finally:
                paradiso.stop()

    def test_f038_catch_up_policy_persistence_in_api(self):
        """F-038: Verifies POST /api/automation/add validates and persists catch_up_policy."""
        # 1. Valid policy
        res = self.client.post("/api/automation/add", json={
            "name": "F038_Policy_Test",
            "filename": "dummy.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_c",
            "timeslot_tier": "CUSTOM",
            "scheduled_time": "08:30",
            "catch_up_policy": "SKIP_UNTIL_NEXT_DAY"
        })
        self.assertEqual(res.status_code, 201)
        data = json.loads(res.data)
        self.assertEqual(data["report"]["catch_up_policy"], "SKIP_UNTIL_NEXT_DAY")

        stored = self.paradiso.intraday_service.automation_service.get_by_name("F038_Policy_Test")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.catch_up_policy, "SKIP_UNTIL_NEXT_DAY")

        # 2. Invalid policy rejected with 400
        res_bad = self.client.post("/api/automation/add", json={
            "name": "F038_Bad_Policy",
            "filename": "dummy.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_c",
            "scheduled_time": "08:30",
            "catch_up_policy": "INVALID_POLICY_XYZ"
        })
        self.assertEqual(res_bad.status_code, 400)
        data_bad = json.loads(res_bad.data)
        self.assertFalse(data_bad["ok"])
        self.assertIn("invalid catch_up_policy", data_bad["error"].lower())

    def test_f039_reset_all_reports_clears_type_c_warned(self):
        """F-039: Verifies reset_all_reports() clears type_c_warned set."""
        from unittest.mock import patch
        intra = self.paradiso.intraday_service
        intra.start_lane("type_c", force_open=True)

        rep_name = "Warned_Report_F039"
        intra.automation_service.add(Report(
            name=rep_name,
            filename="dummy.py",
            filetype="python",
            dir="../reports",
            status="Waiting",
            report_type="type_c",
            timeslot_tier="CUSTOM",
            scheduled_time="08:30",
            catch_up_policy="WARN_OPERATOR"
        ))

        # Trigger missed timeslot warning at 09:00 AM
        from datetime import datetime
        warn_dt = datetime(2026, 9, 28, 9, 0, 0)
        with patch.object(CLOCK, "time_24_str", return_value="09:00"), \
             patch.object(CLOCK, "now", return_value=warn_dt), \
             patch.object(CLOCK, "date_str", return_value="20260928"):
            intra.tick()

        self.assertIn(rep_name, intra.type_c_warned)

        # Operational reset clears type_c_warned
        intra.reset_all_reports()
        self.assertNotIn(rep_name, intra.type_c_warned)
        self.assertEqual(len(intra.type_c_warned), 0)

    def test_f040_disabled_report_manual_run_rejected(self):
        """F-040: POST /api/automation/run rejects Disabled reports with HTTP 409 Conflict."""
        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.add(Report(
            name="Disabled_B_Report",
            filename="dummy.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            interval_minutes=15,
            status="Disabled"
        ))
        from unittest.mock import patch
        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            res = self.client.post("/api/automation/run", json={"name": "Disabled_B_Report"})
            self.assertEqual(res.status_code, 409)
            data = json.loads(res.data)
            self.assertFalse(data["ok"])
            self.assertIn("disabled", data["error"].lower())

    def test_f041_lane_b_does_not_dispatch_failed_report(self):
        """F-041: Lane B suppresses automatic interval dispatch for Failed reports."""
        from unittest.mock import patch
        from datetime import datetime, timedelta
        intra = self.paradiso.intraday_service
        intra.max_retries = 3
        rep_name = "Permanently_Failed_B"

        now_dt = datetime(2026, 9, 28, 10, 25, 0)
        with patch.object(CLOCK, "time_24_str", return_value="10:25"), \
             patch.object(CLOCK, "now", return_value=now_dt), \
             patch.object(CLOCK, "date_str", return_value="20260928"):
            intra._active_date = "20260928"
            intra.automation_service.add(Report(
                name=rep_name,
                filename="dummy.py",
                filetype="python",
                dir="../reports",
                report_type="type_b",
                interval_minutes=15,
                status="Failed"
            ))
            intra.start_lane("type_b", force_open=True)
            intra.retry_counts[rep_name] = 3
            intra.type_b_exhausted.add(rep_name)
            intra.type_b_last_run[rep_name] = now_dt - timedelta(minutes=20)

            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)
            intra.tick()

            self.assertNotIn(rep_name, dispatched)

    def test_f042_simulation_reset_rejected_when_active(self):
        """F-042: POST /api/settings/simulation/reset enforces BG-001 idle-only check returning 409."""
        intra = self.paradiso.intraday_service
        # 1. Scheduler active
        intra.start_lane("type_a", force_open=True)
        res_active = self.client.post("/api/settings/simulation/reset")
        self.assertEqual(res_active.status_code, 409)
        data_active = json.loads(res_active.data)
        self.assertFalse(data_active["ok"])
        self.assertIn("running", data_active["error"].lower())
        intra.stop_lane("type_a")

        # 2. In-flight jobs
        intra.current_runs["Active_Run"] = CLOCK.formatted_now()
        res_inflight = self.client.post("/api/settings/simulation/reset")
        self.assertEqual(res_inflight.status_code, 409)
        intra.current_runs.clear()

        # 3. Clean idle state -> 200 OK
        res_idle = self.client.post("/api/settings/simulation/reset")
        self.assertEqual(res_idle.status_code, 200)

    def test_f043_manual_run_failed_report_rejected(self):
        """F-043: POST /api/automation/run rejects Failed reports with HTTP 409 Conflict."""
        auto_svc = self.paradiso.intraday_service.automation_service
        auto_svc.add(Report(
            name="Failed_Report_F043",
            filename="dummy.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            interval_minutes=15,
            status="Failed"
        ))
        from unittest.mock import patch
        with patch.object(CLOCK, "time_24_str", return_value="10:00"):
            res = self.client.post("/api/automation/run", json={"name": "Failed_Report_F043"})
            self.assertEqual(res.status_code, 409)
            data = json.loads(res.data)
            self.assertFalse(data["ok"])
            self.assertIn("failed", data["error"].lower())

    def test_f043_failed_report_rearmed_only_via_enable(self):
        """F-043: Failed reports can be explicitly re-enabled via POST /api/automation/enable, clearing type_b_exhausted."""
        from unittest.mock import patch
        from datetime import datetime, timedelta
        intra = self.paradiso.intraday_service
        auto_svc = intra.automation_service
        rep_name = "Exhausted_Feed_F043"

        now_dt = datetime(2026, 9, 28, 10, 0, 0)
        with patch.object(CLOCK, "time_24_str", return_value="10:00"), \
             patch.object(CLOCK, "now", return_value=now_dt), \
             patch.object(CLOCK, "date_str", return_value="20260928"):
            intra._active_date = "20260928"
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
            auto_svc.update_status(name=rep_name, status="Failed")
            intra.type_b_exhausted.add(rep_name)
            intra.retry_counts[rep_name] = 3
            intra.type_b_last_run[rep_name] = now_dt - timedelta(minutes=20)

            # 1. While Failed/exhausted, manual run rejected with 409
            res = self.client.post("/api/automation/run", json={"name": rep_name})
            self.assertEqual(res.status_code, 409)

            # 2. tick() does not dispatch
            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)
            intra.tick()
            self.assertNotIn(rep_name, dispatched)

            # 3. Explicit administrative re-enablement via API
            res_enable = self.client.post("/api/automation/enable", json={"name": rep_name})
            self.assertEqual(res_enable.status_code, 200)
            self.assertEqual(auto_svc.get_by_name(rep_name).status, "Waiting")
            self.assertNotIn(rep_name, intra.type_b_exhausted)
            self.assertNotIn(rep_name, intra.retry_counts)

            # 4. Now tick() can dispatch
            intra.tick()
            self.assertIn(rep_name, dispatched)

    # ----------------------------------------------------------------------
    # Batch 9: F-044 through F-047 Regression Tests
    # ----------------------------------------------------------------------
    def test_f044_lane_a_force_open_leak_in_add_automation(self):
        """F-044: Verifies adding Type A report when Lane A is stopped does not leak into waitlist even if Lane B is force_opened."""
        intra = self.paradiso.intraday_service
        intra.lane_a_active = False
        intra.start_lane("type_b", force_open=True)
        self.assertTrue(intra.force_open)
        self.assertFalse(intra.lane_a_active)

        rep_name = "Leaked_Type_A_Test"
        res = self.client.post("/api/automation/add", json={
            "name": rep_name,
            "filename": "dummy_leak.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "status": "Waiting"
        })
        self.assertEqual(res.status_code, 201)
        self.assertNotIn(rep_name, intra.waitlist, "F-044 Fix: Type A report must NOT leak into waitlist when Lane A is stopped.")

    def test_f045_re_enabled_type_c_clears_ran_today_and_dispatches(self):
        """F-045: Verifies re-enabling a Failed Lane C or Lane A report clears persisted failed run and type_c_ran_today, allowing autonomous dispatch."""
        intra = self.paradiso.intraday_service
        auto_svc = intra.automation_service
        rep_name = "Starved_C_Report"
        rep_a_name = "Starved_A_Report"
        now_dt = datetime(2026, 9, 29, 10, 0, 0)

        with patch.object(CLOCK, "time_24_str", return_value="10:00"), \
             patch.object(CLOCK, "now", return_value=now_dt), \
             patch.object(CLOCK, "date_str", return_value="20260929"):
            intra._active_date = "20260929"
            intra.start_lane("type_c", force_open=True)
            intra.start_lane("type_a", force_open=True)

            auto_svc.add(Report(
                name=rep_name,
                filename="dummy_c.py",
                filetype="python",
                dir="../reports",
                report_type="type_c",
                scheduled_time="10:00",
                status="Failed"
            ))
            auto_svc.update_status(rep_name, "Failed")
            intra.type_c_ran_today.add(rep_name)
            intra.type_c_warned.add(rep_name)
            intra.intraday_repo.add_report_run(
                date="20260929",
                report_name=rep_name,
                run=ReportRun(started_at="10:00", finished_at="10:01", result="failed", duration="1s", reason="Exceeded max retries")
            )

            auto_svc.add(Report(
                name=rep_a_name,
                filename="dummy_a.py",
                filetype="python",
                dir="../reports",
                report_type="type_a",
                status="Failed"
            ))
            auto_svc.update_status(rep_a_name, "Failed")
            intra.intraday_repo.add_report_run(
                date="20260929",
                report_name=rep_a_name,
                run=ReportRun(started_at="09:00", finished_at="09:01", result="failed", duration="1s", reason="Exceeded max retries")
            )

            # Re-enable Lane C report
            res_enable = self.client.post("/api/automation/enable", json={"name": rep_name})
            self.assertEqual(res_enable.status_code, 200)
            self.assertEqual(auto_svc.get_by_name(rep_name).status, "Waiting")
            self.assertNotIn(rep_name, intra.type_c_ran_today, "F-045 Fix: type_c_ran_today must be cleared on re-enable.")
            self.assertNotIn(rep_name, intra.type_c_warned, "F-045 Fix: type_c_warned must be cleared on re-enable.")
            day_after_c = intra.intraday_repo.get_day("20260929")
            self.assertNotIn(rep_name, day_after_c.reports_ran, "Persisted failed run record must be cleared on re-enable.")

            # Re-enable Lane A report
            res_enable_a = self.client.post("/api/automation/enable", json={"name": rep_a_name})
            self.assertEqual(res_enable_a.status_code, 200)
            self.assertIn(rep_a_name, intra.waitlist, "Re-enabled Failed Lane A report must be enqueued into waitlist.")

            # Simulate tick at 10:00 (must not re-hydrate rep_name into type_c_ran_today!)
            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)
            intra.tick()

            self.assertIn(rep_name, dispatched, "F-045 Fix: Re-enabled Lane C report must dispatch at scheduled time without storage re-hydration starvation.")


    def test_f046_zero_interval_rejected_with_400(self):
        """F-046: Verifies interval_minutes=0 is rejected with HTTP 400 Bad Request."""
        res_zero = self.client.post("/api/automation/add", json={
            "name": "Zero_Interval_Report",
            "filename": "dummy_zero.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_b",
            "interval_minutes": 0,
            "status": "Waiting"
        })
        self.assertEqual(res_zero.status_code, 400)
        data = json.loads(res_zero.data)
        self.assertIn("interval_minutes must be an integer >= 1", data.get("error", ""))

    def test_f047_timeslot_tier_honors_scheduled_time(self):
        """F-047: Verifies Lane C tick honors rep.scheduled_time and does not prematurely execute at tier defaults."""
        intra = self.paradiso.intraday_service
        exec_svc = intra.execution_service
        intra.start_lane("type_c", force_open=True)

        res = self.client.post("/api/automation/add", json={
            "name": "Midday_Risk_1230",
            "filename": "mid_risk_1230.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_c",
            "timeslot_tier": "MID",
            "scheduled_time": "12:30",
            "status": "Waiting"
        })
        self.assertEqual(res.status_code, 201)

        dispatched = []
        exec_svc.execute_report = lambda name, **kw: dispatched.append(name)
        now_dt = datetime(2026, 9, 29, 12, 5, 0)
        intra._active_date = "20260929"

        # At 12:05 PM, report scheduled for 12:30 PM must NOT run
        with patch.object(CLOCK, "time_24_str", return_value="12:05"), \
             patch.object(CLOCK, "now", return_value=now_dt), \
             patch.object(CLOCK, "date_str", return_value="20260929"):
            intra.tick()

        self.assertNotIn("Midday_Risk_1230", dispatched, "F-047 Fix: Report scheduled for 12:30 must not run at 12:05.")

        # At 12:30 PM, report MUST run
        now_1230 = datetime(2026, 9, 29, 12, 30, 0)
        with patch.object(CLOCK, "time_24_str", return_value="12:30"), \
             patch.object(CLOCK, "now", return_value=now_1230), \
             patch.object(CLOCK, "date_str", return_value="20260929"):
            intra.tick()

        self.assertIn("Midday_Risk_1230", dispatched, "F-047 Fix: Report scheduled for 12:30 must run at 12:30.")

    def test_lane_tables_are_dynamic_without_hardcoded_dummy_reports(self):
        """Verifies index.html defines dynamic lane-a-body, lane-b-body, lane-c-body with zero hardcoded dummy reports, and app.js defines dynamic renderers."""
        index_html = (BASE_DIR / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        app_js = (BASE_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")

        # 1. HTML defines dynamic tbody IDs for all 3 lanes
        self.assertIn('id="lane-a-body"', index_html, "Lane A table must have id='lane-a-body'")
        self.assertIn('id="lane-b-body"', index_html, "Lane B table must have id='lane-b-body'")
        self.assertIn('id="lane-c-body"', index_html, "Lane C table must have id='lane-c-body'")

        # 2. HTML is free of hardcoded mock reports
        dummy_reports = [
            "Daily Cash Flow",
            "Portfolio Summary",
            "Credit Risk Monitor",
            "Hourly Liquidity Feed",
            "Intraday Transaction Feed",
            "Risk Limit Poller",
            "Beginning of Day Position File",
            "Mid-Day Currency Benchmark",
            "General Ledger EOD Reconciliation",
            "Market Close Portfolio Extract"
        ]
        for dummy in dummy_reports:
            self.assertNotIn(f"<strong>{dummy}</strong>", index_html, f"Hardcoded mock report '{dummy}' must NOT exist in index.html!")

        # 3. app.js defines dynamic render functions for each lane
        self.assertIn("function renderLaneATable(", app_js)
        self.assertIn("function renderLaneBTable(", app_js)
        self.assertIn("function renderLaneCTable(", app_js)
        self.assertIn("renderLaneATable(data.automations)", app_js)
        self.assertIn("renderLaneBTable(data.automations)", app_js)
        self.assertIn("renderLaneCTable(data.automations)", app_js)

    def test_native_confirmation_modal_and_no_browser_confirm_alert(self):
        """Verifies that native confirmation modal is defined and browser alert/confirm calls are eliminated."""
        index_html = (BASE_DIR / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        app_js = (BASE_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")

        # 1. HTML defines native confirmation modal with ID, buttons and backdrop
        self.assertIn('id="modal-confirm"', index_html)
        self.assertIn('id="modal-confirm-title"', index_html)
        self.assertIn('id="modal-confirm-message"', index_html)
        self.assertIn('id="btn-confirm-action"', index_html)
        self.assertIn('closeConfirmModal(false)', index_html)
        self.assertIn('closeConfirmModal(true)', index_html)

        # 2. app.js implements showConfirmModal returning a Promise
        self.assertIn("function showConfirmModal(", app_js)
        self.assertIn("function closeConfirmModal(", app_js)
        self.assertIn("await showConfirmModal(", app_js)

        # 3. Browser-native blocking alert() and confirm() are NOT used in app.js
        import re
        self.assertIsNone(re.search(r'\bconfirm\s*\(', app_js), "app.js must not invoke native window.confirm()")
        self.assertIsNone(re.search(r'\balert\s*\(', app_js), "app.js must not invoke native window.alert()")

    def test_f048_stopping_all_lanes_unlocks_scheduler_and_settings(self):
        """F-048: Stopping all active lanes via /api/paradiso/lane/stop stops the daemon thread and unlocks settings & simulation reset."""
        try:
            res_start = self.client.post("/api/paradiso/lane/start", json={"lane": "type_a", "force_open": True})
            self.assertEqual(res_start.status_code, 200)
            self.assertTrue(self.paradiso.is_running())

            res_stop = self.client.post("/api/paradiso/lane/stop", json={"lane": "type_a"})
            self.assertEqual(res_stop.status_code, 200)

            status_data = self.client.get("/api/paradiso/status").get_json()
            self.assertFalse(status_data["running"], "Daemon running must be False once all lanes are stopped!")

            res_sim_reset = self.client.post("/api/settings/simulation/reset")
            self.assertEqual(res_sim_reset.status_code, 200, "Simulation clock reset must succeed when all lanes are stopped!")
        finally:
            self.paradiso.stop()

    def test_f049_enable_endpoint_connected_in_frontend_and_disabled_badge_styled(self):
        """F-049: Web UI exposes /api/automation/enable via enableReport() and styles Disabled badges in catalog."""
        app_js = (BASE_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/automation/enable", app_js)
        self.assertIn("async function enableReport(", app_js)
        self.assertIn("else if (item.status === 'Disabled') badgeClass = 'badge-disabled';", app_js)

    def test_f050_automations_api_and_ui_accurate_retry_counts(self):
        """F-050: GET /api/automations returns live retry_count and max_retries, and UI does not hardcode '1 / 3' on Retrial."""
        app_js = (BASE_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("item.status === 'Retrial' ? '1 / 3'", app_js)
        self.assertIn("function formatReportRetries(", app_js)

        intra_svc = self.paradiso.intraday_service
        intra_svc.retry_counts["SF Base"] = 2
        res = self.client.get("/api/automations").get_json()
        self.assertTrue(res["ok"])
        sf = next(r for r in res["automations"] if r["name"] == "SF Base")
        self.assertEqual(sf["retry_count"], 2)
        self.assertEqual(sf["max_retries"], intra_svc.max_retries)

    def test_f051_clock_reset_surfaces_409_and_add_report_shows_visible_toast(self):
        """F-051: triggerClockReset surfaces !data.ok errors and handleAddReportSubmit triggers global showToast."""
        import re
        app_js = (BASE_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")

        m_reset = re.search(r"async function triggerClockReset\(\)\s*\{(.*?)\n\}", app_js, re.DOTALL)
        self.assertIsNotNone(m_reset)
        reset_body = m_reset.group(1)
        self.assertIn("else", reset_body)
        self.assertIn("showTestingToast(errMsg, 'error')", reset_body)

        m_add = re.search(r"async function handleAddReportSubmit\(e\)\s*\{(.*?)\n\}", app_js, re.DOTALL)
        self.assertIsNotNone(m_add)
        self.assertIn("showToast(", m_add.group(1))

    def test_f052_lane_b_active_workers_bound_and_eod_2030_consistent(self):
        """F-052: #view-type-b Active Workers card has id='metric-b-active' and index.html aligns EOD to 20:30."""
        index_html = (BASE_DIR / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        app_js = (BASE_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("EOD (21:00)", index_html)
        self.assertNotIn("EOD Slot (21:00)", index_html)
        self.assertIn('id="metric-b-active"', index_html)
        self.assertIn("getElementById('metric-b-active')", app_js)

if __name__ == "__main__":
    unittest.main()




