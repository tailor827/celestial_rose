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
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from services.runner import Runner
from services.paradiso import Paradiso
from utils.clock import CLOCK
from utils.config import CONFIG

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

if __name__ == "__main__":
    unittest.main()

