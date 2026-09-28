"""
PoC for F-033: Unbounded Stickiness of force_open Across Independent Lane Lifecycles
Bypasses 22:00 Hard Cutoff and Mutates Status Machine.

Proves:
1. Starting an individual lane with force_open=True sets self.force_open = True on IntradayService.
2. Stopping that lane via stop_lane() does NOT clear self.force_open (it remains True).
3. At 22:30 PM (well past the 22:00 close_time), resolve_status() returns 'OPEN' instead of 'CLOSED'.
4. tick() never reaches status == CLOSED, so _close_day() is never invoked, completely disabling
   the 22:00 hard cutoff and process termination.
5. At midnight (00:05 AM), the new day is initialized with status 'OPEN' instead of 'WAITING_TO_OPEN',
   violating the daily state machine lifecycle.
"""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK
from models.intraday import Intraday

class TestF033StickyForceOpenCutoffBypass(unittest.TestCase):
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

    def test_sticky_force_open_persists_after_lane_stop_and_bypasses_cutoff(self):
        """Proves that force_open remains True after stopping lane, bypassing 22:00 cutoff."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        try:
            intra_svc = paradiso.intraday_service

            # 1. Start Lane B with force_open=True
            intra_svc.start_lane("type_b", force_open=True)
            self.assertTrue(intra_svc.force_open)

            # 2. Stop Lane B
            intra_svc.stop_lane("type_b")
            self.assertFalse(intra_svc.lane_b_active)
            self.assertFalse(intra_svc.is_active)

            # DEFECT DEMONSTRATION 1: force_open is still True even though all lanes are stopped!
            self.assertTrue(intra_svc.force_open,
                            "F-033 Defect: force_open remained sticky True after lane was stopped.")

            # 3. Simulate clock at 22:30 PM (past 22:00 close_time)
            with patch.object(CLOCK, "time_24_str", return_value="22:30"):
                # DEFECT DEMONSTRATION 2: resolve_status returns OPEN instead of CLOSED
                status = intra_svc.resolve_status()
                self.assertEqual(status, Intraday.OPEN,
                                 "F-033 Defect: Status resolved to OPEN at 22:30 PM due to sticky force_open.")

                # DEFECT DEMONSTRATION 3: tick() fails to close the day
                intra_svc.tick()
                self.assertFalse(intra_svc.day_closed,
                                 "F-033 Defect: day_closed is False; 22:00 cutoff was bypassed.")

            # 4. Simulate crossing midnight to 00:05 AM of the next day
            with patch.object(CLOCK, "date_str", return_value="20260927"), \
                 patch.object(CLOCK, "time_24_str", return_value="00:05"):
                intra_svc.tick()
                new_day = intra_svc.intraday_repo.get_day("20260927")
                self.assertIsNotNone(new_day)
                # DEFECT DEMONSTRATION 4: New day initialized as OPEN at 00:05 AM instead of WAITING_TO_OPEN
                self.assertEqual(new_day.status, Intraday.OPEN,
                                 "F-033 Defect: New day initialized as OPEN at 00:05 AM in the middle of the night.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
