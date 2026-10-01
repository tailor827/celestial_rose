"""
PoC: F-045 — Re-Enabled Lane C Report Starvation in AutomationController.enable_automation
========================================================================================
HYPOTHESIS: When a Lane C report reaches terminal failure, it is recorded in
`type_c_ran_today`. When an operator calls `POST /api/automation/enable` to restore
the failed report, `enable_automation` discards `name` from `type_b_exhausted` and
`retry_counts`, but completely fails to evict `name` from `type_c_ran_today`.
Consequently, the API claims HTTP 200 OK ("enabled"), but subsequent tick() calls
continue to skip the report because `rep.name in type_c_ran_today`, starving the
re-enabled report autonomously for the remainder of the calendar day.
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

class TestF045TypeCEnableStarvation(unittest.TestCase):
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

    def test_re_enabled_type_c_report_is_not_starved_in_lane_c_tick(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        client = app.test_client()
        intra = paradiso.intraday_service
        auto_svc = intra.automation_service
        exec_svc = intra.execution_service

        # 1. Initialize today's day and start Lane C
        intra.start_lane("type_c", force_open=True)

        rep_name = "Starved_Lane_C_Report"
        auto_svc.add(Report(
            name=rep_name,
            filename="dummy_c.py",
            filetype="python",
            dir="../reports/python",
            report_type="type_c",
            scheduled_time="10:00",
            timeslot_tier="CUSTOM",
            status="Failed"
        ))

        # 2. Simulate report having exhausted retries and placed into type_c_ran_today
        intra.type_c_ran_today.add(rep_name)
        self.assertEqual(auto_svc.get_by_name(rep_name).status, "Failed")

        # 3. Operator explicitly calls POST /api/automation/enable
        res = client.post("/api/automation/enable", json={"name": rep_name})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(auto_svc.get_by_name(rep_name).status, "Waiting")

        # 4. Advance time past scheduled_time and tick()
        dispatched = []
        exec_svc.execute_report = lambda name, **kw: dispatched.append(name)
        now_dt = datetime(2026, 9, 29, 10, 30, 0)

        with patch.object(CLOCK, "time_24_str", return_value="10:30"), \
             patch.object(CLOCK, "now", return_value=now_dt), \
             patch.object(CLOCK, "date_str", return_value="20260929"):
            intra.tick()

        # 5. DEFECT ASSERTION: The re-enabled report must be dispatched by Lane C!
        self.assertIn(
            rep_name,
            dispatched,
            "F-045 Defect: Re-enabled Lane C report was starved because type_c_ran_today was not cleared!"
        )

if __name__ == "__main__":
    unittest.main()
