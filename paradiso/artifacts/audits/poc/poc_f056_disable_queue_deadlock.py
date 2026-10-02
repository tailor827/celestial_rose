import os
import sys
import time
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK

class PoCDisableQueueDeadlockVerification(unittest.TestCase):
    """
    F-056: Disabling an idle Lane A report while the scheduler is active leaves
    the queue pass unfinalized, resulting in permanent queue stall where seen
    reports in waitlist never dispatch and cooldown never engages.
    """
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox_path = Path(self.temp_dir.name)
        self.storage_dir = self.sandbox_path / "storage"
        self.logs_dir = self.sandbox_path / "logs"
        self.reports_dir = self.sandbox_path / "reports"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)

        self.flask_app, self.paradiso = create_app(storage_dir=self.storage_dir)
        self.flask_app.config["TESTING"] = True
        self.client = self.flask_app.test_client()

        self.intra_svc = self.paradiso.intraday_service
        self.auto_svc = self.intra_svc.automation_service
        self.intraday_repo = self.intra_svc.intraday_repo

        CLOCK.simulation_mode = True
        CLOCK.speed_multiplier = 2.0
        CLOCK.start_real_time = time.time()
        CLOCK.start_sim_time = datetime(2026, 10, 2, 9, 0, 0)

    def tearDown(self):
        CLOCK.simulation_mode = False
        self.paradiso.stop()
        self.temp_dir.cleanup()
        os.environ.pop("PARADISO_STORAGE_DIR", None)
        os.environ.pop("PARADISO_LOGS_DIR", None)

    def test_f056_disabling_idle_report_freezes_lane_a_queue(self):
        """
        Demonstrates that disabling an idle report causes Lane A queue deadlock:
        The remaining skipped report in waitlist is already in _cycle_seen_in_pass,
        so unseen_candidates is empty and it will never dispatch again.
        """
        self.intra_svc.max_concurrent_run = 1
        self.intra_svc.rotation_cooldown_seconds = 30.0
        self.intra_svc._override_cooldown = 30.0

        # Add two Lane A reports
        res_a = self.client.post("/api/automation/add", json={
            "name": "Report_A_P0",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P0"
        })
        self.assertEqual(res_a.status_code, 201)

        res_b = self.client.post("/api/automation/add", json={
            "name": "Report_B_P1",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P1"
        })
        self.assertEqual(res_b.status_code, 201)

        self.intra_svc.start_lane("type_a", force_open=True)

        dispatches = []
        def mock_trigger(name, date):
            dispatches.append(name)
            self.intra_svc.current_runs[name] = "09:00:00"
            self.intra_svc._cycle_seen_in_pass.add(name)

        self.intra_svc._trigger_report = mock_trigger

        # Tick 1: Report_A_P0 is popped and launched
        self.intra_svc.tick()
        self.assertEqual(dispatches, ["Report_A_P0"])
        self.assertIn("Report_A_P0", self.intra_svc.current_runs)

        # Report_A_P0 completes with a dependency skip (zero-penalty retrial)
        self.intra_svc.current_runs.pop("Report_A_P0")
        self.intra_svc.waitlist.append("Report_A_P0")
        self.intra_svc._cycle_skips_in_pass += 1
        self.intra_svc._evaluate_pass_completion(CLOCK.date_str())

        # At this point:
        # waitlist has [Report_B_P1, Report_A_P0]
        # _cycle_seen_in_pass has {'Report_A_P0'}
        # _cycle_pass_reports has {'Report_A_P0', 'Report_B_P1'}
        self.assertEqual(list(self.intra_svc.waitlist), ["Report_B_P1", "Report_A_P0"])
        self.assertEqual(self.intra_svc._cycle_seen_in_pass, {"Report_A_P0"})

        # Operator disables Report_B_P1 (which is currently idle in waitlist)
        res_dis = self.client.post("/api/automation/disable", json={"name": "Report_B_P1"})
        self.assertEqual(res_dis.status_code, 200)

        # After disable:
        # Report_B_P1 is removed from waitlist and discarded from _cycle_pass_reports
        self.assertEqual(list(self.intra_svc.waitlist), ["Report_A_P0"])
        self.assertEqual(self.intra_svc._cycle_pass_reports, {"Report_A_P0"})
        self.assertEqual(len(self.intra_svc.current_runs), 0)

        # Now, tick() is executed across multiple cycles
        dispatches_before = len(dispatches)
        for _ in range(10):
            self.intra_svc.tick()

        # EXPECTED INVARIANT:
        # Since Report_A_P0 was the only remaining report in the pass and skipped,
        # disabling Report_B_P1 must complete the pass, engage starvation cooldown,
        # and clear _cycle_seen_in_pass so Report_A_P0 is not stranded in permanent deadlock.
        self.assertGreater(
            self.intra_svc._rotation_cooldown_until, time.time(),
            "F-056: Queue is deadlocked! Disabling an idle report failed to complete the pass and engage cooldown."
        )
        self.assertEqual(
            len(self.intra_svc._cycle_seen_in_pass), 0,
            "F-056: _cycle_seen_in_pass must be cleared at pass completion so remaining reports can dispatch on next pass."
        )

if __name__ == "__main__":
    unittest.main()
