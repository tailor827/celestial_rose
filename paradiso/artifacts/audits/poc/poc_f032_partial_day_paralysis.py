import os
import sys
import json
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from models.intraday import Intraday, IntradayDay, ReportRun
from models.report import Report
from app import create_app

class TestF032PartialDayParalysis(unittest.TestCase):
    """
    Adversarial PoC for F-032:
    Proves that DEV's _has_completed_runs() heuristic in _get_or_init_day() causes complete
    queue paralysis when a day record has 1 completed report and remaining reports cut off.
    """
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.tmpdir.name)
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("PARADISO_STORAGE_DIR", None)

    def test_partial_day_causes_complete_queue_paralysis(self):
        today = CLOCK.date_str()

        # 3 reports configured in catalog
        automations = {
            "Report_1": {"name": "Report_1", "filename": "r1.py", "filetype": "python", "dir": "../reports", "status": "Waiting", "report_type": "type_a"},
            "Report_2": {"name": "Report_2", "filename": "r2.py", "filetype": "python", "dir": "../reports", "status": "Waiting", "report_type": "type_a"},
            "Report_3": {"name": "Report_3", "filename": "r3.py", "filetype": "python", "dir": "../reports", "status": "Waiting", "report_type": "type_a"}
        }
        (self.storage_dir / "automations.json").write_text(json.dumps(automations), encoding="utf-8")

        # Today has a pre-existing CLOSED record: Report_1 completed, but Report_2 and Report_3 were failed via cutoff
        intraday = {
            today: {
                "date": today,
                "status": "CLOSED",
                "expected_reports": ["Report_1", "Report_2", "Report_3"],
                "reports_ran": {
                    "Report_1": {"started_at": "07:05 AM", "finished_at": "07:10 AM", "result": "completed", "duration": "5s", "reason": "Completed successfully"},
                    "Report_2": {"started_at": "--", "finished_at": "--", "result": "failed", "duration": "0s", "reason": "Not completed before 10:00 PM cutoff"},
                    "Report_3": {"started_at": "--", "finished_at": "--", "result": "failed", "duration": "0s", "reason": "Not completed before 10:00 PM cutoff"}
                },
                "timeline": []
            }
        }
        (self.storage_dir / "intraday.json").write_text(json.dumps(intraday), encoding="utf-8")

        app, paradiso = create_app(storage_dir=self.storage_dir)
        intra = paradiso.intraday_service

        # Start Lane A during OPEN window
        intra.start_lane("type_a", force_open=True)

        # DEFECT DEMONSTRATION:
        # Because Report_1 completed, _has_completed_runs() evaluated to True.
        # The day was NOT cleansed, and already_ran locked out Report_2 and Report_3.
        # Queue length is 0 instead of 2.
        self.assertEqual(len(intra.waitlist), 0,
                         "F-032 Defect: Partial day completion causes total queue paralysis for remaining reports.")

if __name__ == "__main__":
    unittest.main()
