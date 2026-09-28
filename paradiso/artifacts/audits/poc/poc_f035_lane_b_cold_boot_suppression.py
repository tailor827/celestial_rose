import os
import sys
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from app import create_app

class TestF035LaneBColdBootSuppression(unittest.TestCase):
    """
    Adversarial PoC for F-035:
    Proves that _hydrate_type_b_last_run() synthesizes today's date onto a time-only
    last_run string in automations.json, producing a future timestamp that suppresses
    Lane B recurring execution for the entire day.
    """
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.tmpdir.name)
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("PARADISO_STORAGE_DIR", None)

    def test_time_only_last_run_synthesizes_future_date_and_suppresses_execution(self):
        # Type B report with time-only last_run from yesterday evening at 09:30 PM
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
        (self.storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")
        (self.storage_dir / "intraday.json").write_text(json.dumps({}), encoding="utf-8")

        app, paradiso = create_app(storage_dir=self.storage_dir)
        intra = paradiso.intraday_service

        # Simulate morning execution at 08:00 AM
        sim_morning = datetime(2026, 9, 28, 8, 0, 0)
        with patch.object(CLOCK, "now", return_value=sim_morning), \
             patch.object(CLOCK, "time_24_str", return_value="08:00"):

            intra.start_lane("type_b")

            # DEFECT DEMONSTRATION 1:
            # The hydrated last_run is synthesized as 2026-09-28 21:30:00 (tonight!)
            hydrated = intra.type_b_last_run.get("Recurring_Pipeline")
            self.assertIsNotNone(hydrated)
            self.assertGreater(hydrated, sim_morning,
                               "F-035 Defect: last_run was hydrated as a future timestamp.")

            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

            intra.tick()

            # DEFECT DEMONSTRATION 2:
            # The report is suppressed because (now - last_run) is negative!
            self.assertEqual(len(dispatched), 0,
                             "F-035 Defect: Recurring pipeline was suppressed due to future timestamp calculation.")

if __name__ == "__main__":
    unittest.main()
