"""
PoC: F-044 — Cross-Lane Isolation Leak in AutomationController.add_automation
=============================================================================
HYPOTHESIS: When Lane B (or C) is started with force_open=True while Lane A is
stopped, AutomationController.add_automation evaluates lane_a_active as True due
to `lane_a_active or force_open`. Consequently, registering a new Type A report
pushes it into waitlist even though Lane A is stopped.

This breaches Invariant I-1 (Cross-Lane Isolation) and Invariant V-04.
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app

class TestF044LaneAForceOpenLeakInAddAutomation(unittest.TestCase):
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

    def test_adding_type_a_while_lane_a_stopped_leaks_into_waitlist_if_lane_b_force_opened(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        client = app.test_client()
        intra = paradiso.intraday_service

        # 1. Lane A is explicitly stopped. Lane B is started with force_open=True.
        intra.stop_lane("type_a")
        intra.start_lane("type_b", force_open=True)

        self.assertFalse(intra.lane_a_active, "Lane A must be stopped")
        self.assertTrue(intra.lane_b_active, "Lane B is active")
        self.assertTrue(intra.force_open, "force_open is set for Lane B out-of-window run")

        # 2. Register a new Type A report via API
        res = client.post("/api/automation/add", json={
            "name": "Leaked_Type_A_Report",
            "filename": "leaked_script.py",
            "filetype": "python",
            "dir": "../reports/python",
            "report_type": "type_a",
            "status": "Waiting"
        })
        self.assertEqual(res.status_code, 201)

        # 3. DEFECT ASSERTION: The newly added Type A report must NOT be in waitlist
        # because Lane A is STOPPED.
        self.assertNotIn(
            "Leaked_Type_A_Report",
            list(intra.waitlist),
            "F-044 Defect: Type A report leaked into waitlist while Lane A is stopped due to cross-lane force_open!"
        )

if __name__ == "__main__":
    unittest.main()
