import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from models.report import Report
from app import create_app

class TestF037ScheduledTimeFormatFailures(unittest.TestCase):
    """
    Adversarial PoC for F-037:
    Proves that non-canonical scheduled_time formats cause:
    1. Unhandled ValueError crash in tick() for 12-hour format ('08:30 AM').
    2. Silent permanent execution freeze for unpadded hour ('8:30').
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

    def test_12hr_format_crashes_tick_with_value_error(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.start_lane("type_c", force_open=True)

            intra.automation_service.add(Report(
                name="Crash_Report_12hr",
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                timeslot_tier="CUSTOM",
                scheduled_time="08:30 AM"
            ))

            # DEFECT DEMONSTRATION 1:
            # At 09:00 AM, tick() raises unhandled ValueError on strptime('%H:%M')
            with patch.object(CLOCK, "time_24_str", return_value="09:00"):
                with self.assertRaises(ValueError):
                    intra.tick()
        finally:
            paradiso.stop()

    def test_unpadded_hour_is_never_dispatched_across_entire_day(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.start_lane("type_c", force_open=True)

            intra.automation_service.add(Report(
                name="Frozen_Report_Unpadded",
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                timeslot_tier="CUSTOM",
                scheduled_time="8:30"
            ))

            dispatched = []
            intra.execution_service.execute_report = lambda name, **kw: dispatched.append(name)

            # DEFECT DEMONSTRATION 2:
            # Lexicographical comparison '08:30' >= '8:30' is False for all hours
            for test_time in ["08:30", "09:00", "12:00", "15:00", "20:30"]:
                with patch.object(CLOCK, "time_24_str", return_value=test_time):
                    intra.tick()

            self.assertNotIn("Frozen_Report_Unpadded", dispatched,
                             "F-037 Defect: Report with unpadded scheduled_time '8:30' is never dispatched.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
