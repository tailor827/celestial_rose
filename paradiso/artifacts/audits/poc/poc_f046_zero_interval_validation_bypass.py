"""
PoC: F-046 — Zero-Interval Validation Bypass in AutomationController.add_automation
===================================================================================
HYPOTHESIS: In AutomationController.add_automation, interval_minutes is parsed via:
`interval_minutes = int(data.get("interval_minutes") or 30)`
Because 0 evaluates to False in Python boolean expressions, passing
`{"interval_minutes": 0}` (an invalid interval < 1) silently coerces to 30,
bypassing the `< 1` check and returning HTTP 201 Created with interval_minutes: 30
instead of HTTP 400 Bad Request.
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app

class TestF046ZeroIntervalValidationBypass(unittest.TestCase):
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

    def test_interval_zero_must_be_rejected_with_400(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        client = app.test_client()

        # Submit interval_minutes = 0 (invalid interval < 1)
        res = client.post("/api/automation/add", json={
            "name": "Zero_Interval_Bypass",
            "filename": "zero.py",
            "filetype": "python",
            "dir": "../reports/python",
            "report_type": "type_b",
            "interval_minutes": 0,
            "status": "Waiting"
        })

        # DEFECT ASSERTION: The API must reject 0 with HTTP 400 Bad Request,
        # exactly as it rejects negative numbers like -5.
        self.assertEqual(
            res.status_code,
            400,
            f"F-046 Defect: API accepted interval_minutes=0 with status {res.status_code} (silently coerced to 30)!"
        )

if __name__ == "__main__":
    unittest.main()
