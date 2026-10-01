"""
PoC: F-047 — Timeslot Tier Resolution Desync Between UI and Backend Scheduler
=============================================================================
HYPOTHESIS: In the newly introduced Add Report Modal, Timeslot Tiers auto-fill
and advertise timeslot run times:
- BOD: "08:30"
- MID: "12:30"
- EOD: "16:30"
However, in IntradayService.tick():
- BOD unconditionally executes at self.start_time (07:00), ignoring scheduled_time (runs 90m early)
- MID unconditionally executes at "12:00", ignoring scheduled_time (runs 30m early)
- EOD violates F-027 (which standardizes EOD as 20:30 across docs and config)

This causes reports configured for 12:30 PM (MID) to trigger prematurely at 12:00 PM,
completely ignoring the user-configured scheduled_time.
"""

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

class TestF047TimeslotTierDesync(unittest.TestCase):
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

    def test_mid_tier_dispatches_at_1200_ignoring_1230_scheduled_time(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        client = app.test_client()
        intra = paradiso.intraday_service
        exec_svc = intra.execution_service

        intra.start_lane("type_c", force_open=True)

        # Register report via UI form parameters: tier=MID, scheduled_time=12:30
        res = client.post("/api/automation/add", json={
            "name": "Midday_Risk_Report",
            "filename": "mid_risk.py",
            "filetype": "python",
            "dir": "../reports/python",
            "report_type": "type_c",
            "timeslot_tier": "MID",
            "scheduled_time": "12:30",
            "status": "Waiting"
        })
        self.assertEqual(res.status_code, 201)

        # Clock is at 12:05 PM (before 12:30 PM scheduled time)
        dispatched = []
        exec_svc.execute_report = lambda name, **kw: dispatched.append(name)
        now_dt = datetime(2026, 9, 29, 12, 5, 0)

        with patch.object(CLOCK, "time_24_str", return_value="12:05"), \
             patch.object(CLOCK, "now", return_value=now_dt), \
             patch.object(CLOCK, "date_str", return_value="20260929"):
            intra.tick()

        # DEFECT ASSERTION: At 12:05 PM, a report scheduled for 12:30 PM must NOT run!
        # But because the backend hardcodes MID to 12:00, it prematurely executes at 12:05!
        self.assertNotIn(
            "Midday_Risk_Report",
            dispatched,
            "F-047 Defect: Report scheduled for 12:30 PM (MID) prematurely executed at 12:05 PM because backend hardcodes MID to 12:00!"
        )

if __name__ == "__main__":
    unittest.main()
