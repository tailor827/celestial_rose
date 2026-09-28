"""
PoC for F-034: Actively Executing Type B and Type C Reports Can Be Deleted
via DELETE /api/automation/delete/<name>, Leaving Orphaned Host Processes.

Proves:
1. In AutomationController.delete_automation (automation_controller.py:114-118), the deletion guard
   only checks: if self.intraday_service and self.intraday_service.is_active: return 409
2. When a Type B or Type C report is executing on-demand (POST /api/automation/run) while scheduler
   lanes are stopped, self.intraday_service.is_active is False, even though has_active_runs is True.
3. DELETE /api/automation/delete/<name> returns HTTP 200 OK and deletes the report from the catalog.
4. The running OS process is never terminated, leaving an orphaned process executing in the background
   and contaminating active_runs_type_b / active_runs_type_c with dangling entries.
"""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK

class TestF034DeleteActiveReportOrphaning(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.test_dir.name)
        self.storage_dir = self.temp_path / "storage"
        self.logs_dir = self.temp_path / "logs"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.old_storage = os.environ.get("PARADISO_STORAGE_DIR")
        self.old_logs = os.environ.get("PARADISO_LOGS_DIR")
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)

    def tearDown(self):
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

    def test_delete_active_report_allowed_and_leaves_orphaned_state(self):
        """Proves that DELETE /api/automation/delete/<name> succeeds on actively executing Type B report."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        client = app.test_client()
        try:
            rep_name = "Active_Manual_Pipeline_B"
            # 1. Register Type B automation
            res_add = client.post("/api/automation/add", json={
                "name": rep_name,
                "filename": "dummy_b.py",
                "filetype": "python",
                "dir": "../reports",
                "report_type": "type_b",
                "interval_minutes": 30
            })
            self.assertEqual(res_add.status_code, 201)

            intra_svc = paradiso.intraday_service

            # 2. Simulate actively running Type B report
            intra_svc.active_runs_type_b[rep_name] = CLOCK.formatted_now()
            self.assertFalse(intra_svc.is_active, "Scheduler lanes are stopped.")
            self.assertTrue(intra_svc.has_active_runs, "Report is actively in flight across system.")

            # 3. Request deletion of the actively executing report
            res_delete = client.delete(f"/api/automation/delete/{rep_name}")

            # DEFECT DEMONSTRATION 1: Deletion succeeds with HTTP 200 OK instead of HTTP 409 Conflict
            self.assertEqual(res_delete.status_code, 200,
                             "F-034 Defect: Actively executing report was deleted with HTTP 200 OK.")
            data = res_delete.get_json()
            self.assertTrue(data.get("ok"))

            # DEFECT DEMONSTRATION 2: The report was removed from catalog
            self.assertIsNone(intra_svc.automation_service.get_by_name(rep_name),
                              "F-034 Defect: Report removed from catalog while process still running.")

            # DEFECT DEMONSTRATION 3: Run tracking in IntradayService is orphaned/dangling
            self.assertIn(rep_name, intra_svc.active_runs_type_b,
                          "F-034 Defect: active_runs_type_b retains dangling entry for deleted report.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
