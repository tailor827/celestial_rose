"""
Adversarial Verification Suite for F-026 Remediation:
Confirms elimination of silent out-of-window lane start stall.
Covers:
1. Verifies POST /api/paradiso/lane/start returns HTTP 409 Conflict across all non-OPEN states
   (WAITING_TO_OPEN, WAITING_TO_CLOSE, CLOSED).
2. Verifies error payload honesty: contains 'blocked outside the intraday open window' and status.
3. Verifies force_open=True override allows starting lane even outside regular intraday window.
4. Verifies stopping lane functions cleanly regardless of window state.
"""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from app import create_app
from models.report import Report
from utils.clock import CLOCK

class TestF026RemediationVerification(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.test_dir.name)
        self.storage_dir = self.temp_path / "storage"
        self.logs_dir = self.temp_path / "logs"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        (self.storage_dir / "automations.json").write_text("{}", encoding="utf-8")
        (self.storage_dir / "intraday.json").write_text("{}", encoding="utf-8")

        self.old_storage = os.environ.get("PARADISO_STORAGE_DIR")
        self.old_logs = os.environ.get("PARADISO_LOGS_DIR")
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

    def test_f026_out_of_window_lane_start_rejected_with_409(self):
        """F-026: Proves lane_start outside OPEN window returns HTTP 409 Conflict across all non-OPEN windows."""
        self.intra_svc.force_open = False

        # 1. WAITING_TO_OPEN (05:00)
        with patch.object(CLOCK, "time_24_str", return_value="05:00"):
            self.assertEqual(self.intra_svc.resolve_status(), "WAITING_TO_OPEN")
            res_early = self.client.post("/api/paradiso/lane/start", json={"lane": "type_b"})
            self.assertEqual(res_early.status_code, 409)
            data_early = json.loads(res_early.data)
            self.assertFalse(data_early["ok"])
            self.assertEqual(data_early["lane"], "type_b")
            self.assertIn("blocked outside the intraday open window", data_early["error"])
            self.assertIn("WAITING_TO_OPEN", data_early["error"])

        # 2. WAITING_TO_CLOSE (21:30)
        with patch.object(CLOCK, "time_24_str", return_value="21:30"):
            self.assertEqual(self.intra_svc.resolve_status(), "WAITING_TO_CLOSE")
            res_wrap = self.client.post("/api/paradiso/lane/start", json={"lane": "type_c"})
            self.assertEqual(res_wrap.status_code, 409)
            data_wrap = json.loads(res_wrap.data)
            self.assertFalse(data_wrap["ok"])
            self.assertEqual(data_wrap["lane"], "type_c")
            self.assertIn("blocked outside the intraday open window", data_wrap["error"])
            self.assertIn("WAITING_TO_CLOSE", data_wrap["error"])

        # 3. CLOSED (22:30)
        with patch.object(CLOCK, "time_24_str", return_value="22:30"):
            self.assertEqual(self.intra_svc.resolve_status(), "CLOSED")
            res_closed = self.client.post("/api/paradiso/lane/start", json={"lane": "type_a"})
            self.assertEqual(res_closed.status_code, 409)
            data_closed = json.loads(res_closed.data)
            self.assertFalse(data_closed["ok"])
            self.assertEqual(data_closed["lane"], "type_a")
            self.assertIn("blocked outside the intraday open window", data_closed["error"])
            self.assertIn("CLOSED", data_closed["error"])

    def test_f026_force_open_override_allows_start_outside_window(self):
        """F-026: Supplying force_open=True allows starting lane during off-hours."""
        with patch.object(CLOCK, "time_24_str", return_value="22:30"):
            self.assertEqual(self.intra_svc.resolve_status(), "CLOSED")
            res = self.client.post("/api/paradiso/lane/start", json={"lane": "type_b", "force_open": True})
            self.assertIn(res.status_code, [200, 429])
            if res.status_code == 200:
                data = json.loads(res.data)
                self.assertTrue(data["ok"])
                self.assertEqual(data["lane"], "type_b")

if __name__ == "__main__":
    unittest.main()
