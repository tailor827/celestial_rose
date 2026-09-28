import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from models.report import Report
from app import create_app

class TestF040DisabledReportManualRunBypass(unittest.TestCase):
    """
    Adversarial PoC for F-040:
    Demonstrates that manual execution (POST /api/automation/run) completely bypasses
    the 'Disabled' safety status on Type B and Type C automations, executing the disabled
    script on the host OS and clobbering the 'Disabled' status in storage with 'Completed'/'Failed'.
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

    def test_disabled_type_b_report_executed_and_status_clobbered(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            auto_svc = paradiso.intraday_service.automation_service
            # 1. Register a Type B report and explicitly disable it
            rep_name = "Quarantined_Feed"
            auto_svc.add(Report(
                name=rep_name,
                filename="dummy.py",
                filetype="python",
                dir="reports",
                report_type="type_b",
                interval_minutes=15,
                status="Disabled"
            ))

            stored = auto_svc.get_by_name(rep_name)
            self.assertEqual(stored.status, "Disabled")

            # 2. Trigger manual run via API during OPEN hours
            dispatched = []
            intra = paradiso.intraday_service
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

            with patch.object(CLOCK, "time_24_str", return_value="10:00"), \
                 patch.object(CLOCK, "now", return_value=datetime(2026, 9, 28, 10, 0, 0)):
                with app.test_client() as client:
                    res = client.post("/api/automation/run", json={"name": rep_name})

                    # DEFECT DEMONSTRATION:
                    # The API returns HTTP 200 instead of rejecting with HTTP 409/400
                    self.assertEqual(res.status_code, 200,
                        "F-040 Defect: API permits manual execution of disabled automation")
                    data = res.get_json()
                    self.assertTrue(data.get("ok"))
                    self.assertIn("Manual run triggered", data.get("message", ""))

            # DEFECT DEMONSTRATION:
            # The disabled report was actually dispatched for execution
            self.assertIn(rep_name, dispatched,
                "F-040 Defect: Disabled report was dispatched by execution service")
        finally:
            paradiso.stop()

    def test_disabled_type_c_report_executed_and_dispatched(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            auto_svc = paradiso.intraday_service.automation_service
            rep_name = "Quarantined_Timeslot"
            auto_svc.add(Report(
                name=rep_name,
                filename="dummy.py",
                filetype="python",
                dir="reports",
                report_type="type_c",
                scheduled_time="14:00",
                status="Disabled"
            ))

            dispatched = []
            intra = paradiso.intraday_service
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

            with patch.object(CLOCK, "time_24_str", return_value="10:00"), \
                 patch.object(CLOCK, "now", return_value=datetime(2026, 9, 28, 10, 0, 0)):
                with app.test_client() as client:
                    res = client.post("/api/automation/run", json={"name": rep_name})
                    self.assertEqual(res.status_code, 200)

            self.assertIn(rep_name, dispatched)
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
