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
from app import create_app

class TestF042SimulationResetBypassesIdleGuardrail(unittest.TestCase):
    """
    Adversarial PoC for F-042:
    Demonstrates that POST /api/settings/simulation/reset lacks the BG-001
    idle-only guardrail, allowing clock rewinds while the scheduler or jobs are active.
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

    def test_simulation_reset_allowed_while_scheduler_active(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            # 1. Start scheduler with active lane
            intra = paradiso.intraday_service
            intra.start_lane("type_a", force_open=True)
            self.assertTrue(intra.is_active)

            # 2. While scheduler is actively running, attempt to reset simulation clock
            with app.test_client() as client:
                res = client.post("/api/settings/simulation/reset")

                # DEFECT DEMONSTRATION:
                # Returns HTTP 200 instead of HTTP 409 Conflict
                self.assertEqual(res.status_code, 200,
                    "F-042 Defect: POST /api/settings/simulation/reset returned 200 while scheduler active")
                data = res.get_json()
                self.assertTrue(data.get("ok"))
                self.assertEqual(data.get("message"), "Simulation clock reset to midnight.")
        finally:
            paradiso.stop()

    def test_simulation_reset_allowed_while_jobs_in_flight(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra = paradiso.intraday_service
            intra.current_runs["Active_Report"] = CLOCK.formatted_now()
            self.assertTrue(intra.has_active_runs)

            with app.test_client() as client:
                res = client.post("/api/settings/simulation/reset")
                self.assertEqual(res.status_code, 200,
                    "F-042 Defect: Clock reset permitted while jobs are in flight")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
