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

class TestF039ResetAllReportsTypeCWarnedRetention(unittest.TestCase):
    """
    Adversarial PoC for F-039:
    Proves that reset_all_reports() fails to clear self.type_c_warned,
    permanently suppressing operator warnings after an operational reset.
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

    def test_reset_all_reports_leaves_type_c_warned_populated(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.start_lane("type_c", force_open=True)

            rep_name = "Warned_Report"
            intra.automation_service.add(Report(
                name=rep_name,
                filename="dummy.py",
                filetype="python",
                dir="reports",
                status="Waiting",
                report_type="type_c",
                timeslot_tier="CUSTOM",
                scheduled_time="08:30",
                catch_up_policy="WARN_OPERATOR"
            ))

            # 1. Trigger missed timeslot warning at 09:00 AM
            with patch.object(CLOCK, "time_24_str", return_value="09:00"):
                intra.tick()

            self.assertIn(rep_name, intra.type_c_warned)

            # 2. Operator resets all reports to Waiting via API / reset_all_reports()
            intra.reset_all_reports()

            # DEFECT DEMONSTRATION:
            # type_c_warned is NOT cleared, leaving the report in warned set
            self.assertIn(rep_name, intra.type_c_warned,
                          "F-039 Defect: type_c_warned retained report after reset_all_reports().")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
