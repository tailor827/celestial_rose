import os
import json
import time
import tempfile
import unittest
from pathlib import Path

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

class TestAuditFixes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)
        self.app, self.paradiso = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
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

        class MockRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                import json
                log_file = BASE_DIR / "logs" / f"{name}.json"
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
            log_data = json.loads((BASE_DIR / "logs" / f"{report_name}.json").read_text(encoding="utf-8"))
            self.assertEqual(log_data["status"], "Retrial")
            self.assertEqual(log_data["reason"], "Dependencies not yet available.")

            # automations.json set to Retrial
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Retrial")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = BASE_DIR / "logs" / f"{report_name}.json"
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

            test_log = BASE_DIR / "logs" / f"{report_name}.json"
            self.assertTrue(test_log.exists())
            import json
            data = json.loads(test_log.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "Failed")
            self.assertIn("SyntaxError", data["last_output"])
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Failed")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = BASE_DIR / "logs" / f"{report_name}.json"
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

            test_log = BASE_DIR / "logs" / f"{report_name}.json"
            self.assertTrue(test_log.exists())
            import json
            data = json.loads(test_log.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "Failed")
            self.assertIn("Contract violation", data["last_output"])
            self.assertEqual(auto_svc.get_by_name(report_name).status, "Failed")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = BASE_DIR / "logs" / f"{report_name}.json"
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
            test_log = BASE_DIR / "logs" / f"{report_name}.json"
            if test_log.exists():
                test_log.unlink()

    def test_f004_end_to_end_0base_auto_pattern_preserves_retries_and_log(self):
        """Verifies end-to-end that 0base_auto.py pattern (dump Retrial + exit 1) rotates without retry penalty."""
        auto_path = self.dir_path / "automations.json"
        intra_path = self.dir_path / "intraday.json"
        auto_repo = Automations(auto_path)
        intra_repo = Intraday(intra_path)
        auto_svc = AutomationService(auto_repo)

        class Mock0BaseRunner:
            def run_python(self, script_path, callback_good, callback_fail, name):
                import json
                log_file = BASE_DIR / "logs" / f"{name}.json"
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

            log_data = json.loads((BASE_DIR / "logs" / f"{report_name}.json").read_text(encoding="utf-8"))
            self.assertEqual(log_data["status"], "Retrial")
            self.assertEqual(log_data["last_output"], "Unavailable")
        finally:
            if dummy_script.exists():
                dummy_script.unlink()
            test_log = BASE_DIR / "logs" / f"{report_name}.json"
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

        # Advance clock to tomorrow
        orig_date_str = CLOCK.date_str
        try:
            CLOCK.date_str = lambda: sim_tomorrow
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

if __name__ == "__main__":
    unittest.main()


