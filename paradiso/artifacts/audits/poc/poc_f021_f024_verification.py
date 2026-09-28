"""
Adversarial Verification Suite for F-021, F-022, F-023, and F-024 Remediations.
Covers:
1. F-021: Exact Receipt Naming Match & Section 12 Receipt Discovery for Type B & C Reports.
2. F-022: Unbounded 500ms Rapid Spin Elimination via Interval & Backoff Throttling.
3. F-023: BG-001 Idle-Only Settings Guardrail Multi-Lane Protection (409 Conflict).
4. F-024: Strict Lane Name Whitelist Validation & HTTP 400 Rejection on Malformed Input.
"""
import os
import sys
import json
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from app import create_app
from models.automation import Automations
from models.intraday import Intraday
from models.report import Report
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from utils.clock import CLOCK

class TestF021ThroughF024Verification(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.test_dir.name)
        self.storage_dir = self.temp_path / "storage"
        self.logs_dir = self.temp_path / "logs"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        (self.storage_dir / "automations.json").write_text("{}", encoding="utf-8")
        (self.storage_dir / "intraday.json").write_text("{}", encoding="utf-8")

        self.old_storage_env = os.environ.get("PARADISO_STORAGE_DIR")
        self.old_logs_env = os.environ.get("PARADISO_LOGS_DIR")
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)

        self.app, self.paradiso = create_app(storage_dir=self.storage_dir)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.intra_svc = self.paradiso.intraday_service
        self.auto_svc = self.intra_svc.automation_service
        self.exec_svc = self.intra_svc.execution_service

    def tearDown(self):
        try:
            self.paradiso.stop()
            self.exec_svc.runner.kill_all()
        except Exception:
            pass

        if self.old_storage_env is not None:
            os.environ["PARADISO_STORAGE_DIR"] = self.old_storage_env
        else:
            os.environ.pop("PARADISO_STORAGE_DIR", None)

        if self.old_logs_env is not None:
            os.environ["PARADISO_LOGS_DIR"] = self.old_logs_env
        else:
            os.environ.pop("PARADISO_LOGS_DIR", None)

        try:
            self.test_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # F-021: Receipt Naming & Discovery
    # -------------------------------------------------------------------------
    def test_f021_receipt_exact_match_and_discovery(self):
        """F-021: Pipeline scripts emit exact registered filenames and pass receipt validation."""
        script_b = (BASE.parent / "reports" / "hourly_liquidity_feed.py").resolve()
        script_c = (BASE.parent / "reports" / "eod_ledger_reconciliation.py").resolve()

        self.assertTrue(script_b.exists(), f"Missing script {script_b}")
        self.assertTrue(script_c.exists(), f"Missing script {script_c}")

        env = {
            "PARADISO_LOGS_DIR": str(self.logs_dir),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows")
        }

        # Run both reports in isolated logs dir
        res_b = subprocess.run([sys.executable, str(script_b)], env=env, capture_output=True, text=True)
        res_c = subprocess.run([sys.executable, str(script_c)], env=env, capture_output=True, text=True)

        self.assertEqual(res_b.returncode, 0, f"Hourly liquidity feed failed: {res_b.stderr}")
        self.assertEqual(res_c.returncode, 0, f"EOD ledger reconciliation failed: {res_c.stderr}")

        # Check emitted filenames match exact registered names with spaces
        written_files = set(f.name for f in self.logs_dir.iterdir())
        self.assertIn("Hourly Liquidity Feed.json", written_files)
        self.assertIn("EOD Ledger Reconciliation.json", written_files)
        self.assertNotIn("Hourly_Liquidity_Feed.json", written_files)
        self.assertNotIn("EOD_Ledger_Reconciliation.json", written_files)

        # Verify ReportLog discovery
        log_b = ReportLog("Hourly Liquidity Feed", log_dir=self.logs_dir)
        self.assertIsNotNone(log_b.find_latest_log_file())
        self.assertTrue(log_b.has_valid_receipt())

        log_c = ReportLog("EOD Ledger Reconciliation", log_dir=self.logs_dir)
        self.assertIsNotNone(log_c.find_latest_log_file())
        self.assertTrue(log_c.has_valid_receipt())

    # -------------------------------------------------------------------------
    # F-022: Dependency Skip Throttling (Lanes B & C)
    # -------------------------------------------------------------------------
    def test_f022_lane_b_dependency_skip_throttled_by_interval(self):
        """F-022: Lane B records type_b_last_run on dependency skip, preventing 500ms rapid spin."""
        self.intra_svc.force_open = True
        self.intra_svc.lane_b_active = True
        rep = Report(
            name="Recurring_Feed_B",
            filename="feed_b.py",
            filetype="python",
            dir="../reports",
            report_type="type_b",
            interval_minutes=60,
            status="Waiting"
        )
        self.auto_svc.add(rep)

        dispatches = 0
        def mock_skip(name, callback_good=None, callback_fail=None, **kwargs):
            nonlocal dispatches
            dispatches += 1
            if callback_fail:
                callback_fail(name, "0.01s", "SKIPPED: Missing dependency 'upstream'")

        self.exec_svc.execute_report = MagicMock(side_effect=mock_skip)

        # First tick dispatches
        self.intra_svc.tick()
        self.assertEqual(dispatches, 1)
        self.assertIn("Recurring_Feed_B", self.intra_svc.type_b_last_run)

        # Next 5 consecutive ticks must NOT re-dispatch (interval not reached)
        for _ in range(5):
            self.intra_svc.tick()
        self.assertEqual(dispatches, 1)

    def test_f022_lane_c_dependency_skip_throttled_by_retry_after(self):
        """F-022: Lane C sets 5m backoff in type_c_retry_after on skip, preventing 500ms rapid spin."""
        self.intra_svc.force_open = True
        self.intra_svc.lane_b_active = False
        self.intra_svc.lane_c_active = True
        now_time = CLOCK.time_24_str()
        rep = Report(
            name="Timeslot_EOD_C",
            filename="eod_c.py",
            filetype="python",
            dir="../reports",
            report_type="type_c",
            timeslot_tier="CUSTOM",
            scheduled_time=now_time,
            status="Waiting"
        )
        self.auto_svc.add(rep)

        dispatches = 0
        def mock_skip(name, callback_good=None, callback_fail=None, **kwargs):
            nonlocal dispatches
            dispatches += 1
            if callback_fail:
                callback_fail(name, "0.01s", "SKIPPED: Missing ledger file")

        self.exec_svc.execute_report = MagicMock(side_effect=mock_skip)

        # First tick dispatches and skips
        self.intra_svc.tick()
        self.assertEqual(dispatches, 1)
        self.assertIn("Timeslot_EOD_C", self.intra_svc.type_c_retry_after)
        self.assertGreater(self.intra_svc.type_c_retry_after["Timeslot_EOD_C"], CLOCK.now())

        # Next 5 consecutive ticks must NOT re-dispatch while in cooldown
        for _ in range(5):
            self.intra_svc.tick()
        self.assertEqual(dispatches, 1)

    # -------------------------------------------------------------------------
    # F-023: BG-001 Settings Guardrail Multi-Lane Protection
    # -------------------------------------------------------------------------
    def test_f023_settings_mutation_rejected_across_all_active_lanes(self):
        """F-023: SettingsController rejects updates with 409 Conflict if ANY lane has running jobs."""
        self.assertFalse(self.paradiso.is_running())

        # 1. Lane A active run -> 409 Conflict
        self.intra_svc.current_runs["Lane_A_Job"] = CLOCK.formatted_now()
        res_a = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res_a.status_code, 409)
        self.intra_svc.current_runs.clear()

        # 2. Lane B active run -> 409 Conflict
        self.intra_svc.active_runs_type_b["Lane_B_Job"] = CLOCK.formatted_now()
        res_b = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res_b.status_code, 409)
        self.intra_svc.active_runs_type_b.clear()

        # 3. Lane C active run -> 409 Conflict
        self.intra_svc.active_runs_type_c["Lane_C_Job"] = CLOCK.formatted_now()
        res_c = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res_c.status_code, 409)
        self.intra_svc.active_runs_type_c.clear()

        # 4. Completely idle -> 200 OK
        res_idle = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res_idle.status_code, 200)

    # -------------------------------------------------------------------------
    # F-024: Lane Name Whitelist Validation
    # -------------------------------------------------------------------------
    def test_f024_lane_name_strict_whitelist_validation(self):
        """F-024: Lane start and stop endpoints strictly reject non-canonical lane identifiers with 400."""
        invalid_lanes = ["unrecognized", "type_d", "lane_x", "123", "", None]
        for bad_lane in invalid_lanes:
            res_start = self.client.post("/api/paradiso/lane/start", json={"lane": bad_lane})
            self.assertEqual(res_start.status_code, 400, f"Expected 400 for start bad lane: {bad_lane}")
            data_start = res_start.get_json()
            self.assertFalse(data_start["ok"])
            self.assertIn("Invalid lane", data_start["error"])

            res_stop = self.client.post("/api/paradiso/lane/stop", json={"lane": bad_lane})
            self.assertEqual(res_stop.status_code, 400, f"Expected 400 for stop bad lane: {bad_lane}")
            data_stop = res_stop.get_json()
            self.assertFalse(data_stop["ok"])
            self.assertIn("Invalid lane", data_stop["error"])

        # IntradayService._normalize_lane raises ValueError directly
        with self.assertRaises(ValueError):
            self.intra_svc._normalize_lane("invalid_lane_identifier")

        # Canonical lanes succeed
        for valid_lane in ["type_a", "type_b", "type_c"]:
            self.assertEqual(self.intra_svc._normalize_lane(valid_lane), valid_lane)

def main():
    unittest.main()

if __name__ == "__main__":
    main()
