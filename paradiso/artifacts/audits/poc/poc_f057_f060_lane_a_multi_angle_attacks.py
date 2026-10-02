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


class PoCLaneAMultiAngleAttacks(unittest.TestCase):
    """
    Batch 13 Multi-Angle Adversarial Suite Targeting Lane A:
    - F-057: Re-enabling a Failed Lane A report via POST /api/automation/enable fails to
             remove it from _cycle_seen_in_pass, causing lower-priority unseen reports
             to bypass it or causing the pass to end without executing the re-enabled report.
    - F-058: When the final report in a pass Completes or Permanently Fails, _cycle_pass_reports
             is emptied prior to _evaluate_pass_completion(), leaving _cycle_completions_in_pass,
             _cycle_errors_in_pass, and _cycle_seen_in_pass dirty and bypassing starvation cooldown
             for subsequently added/enabled reports.
    - F-059: start_lane("type_a"), stop_lane("type_a"), start_fresh_run(), and reset_all_reports()
             fail to reset _cycle_skips_in_pass and _cycle_errors_in_pass to 0, poisoning
             starvation cooldown evaluation after a lane stop/restart or full report reset.
    - F-060: defer_seen_clear=True in disable_automation leaves completed-pass reports in
             _cycle_seen_in_pass; adding or enabling a lower-priority report before the next tick
             inverts priority order and starves the P0 report for the entire subsequent pass.
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

        for r in list(self.auto_svc.get_all()):
            self.auto_svc.delete(r.name)

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

    def test_f057_reenabled_failed_report_retains_seen_flag_and_is_bypassed(self):
        """
        F-057: When a P0 Lane A report permanently fails, its name remains in _cycle_seen_in_pass.
        Re-enabling it via POST /api/automation/enable places it at the front of waitlist,
        but because _cycle_seen_in_pass still contains its name, tick() filters it out of
        unseen_candidates and dispatches P2 reports ahead of P0 (or starves it in multi-slot mode).
        """
        self.intra_svc.max_concurrent_run = 1
        self.intra_svc.max_retries = 1
        today = CLOCK.date_str()

        self.client.post("/api/automation/add", json={
            "name": "P0_Crit",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P0"
        })
        self.client.post("/api/automation/add", json={
            "name": "P2_Norm",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P2"
        })

        self.intra_svc.start_lane("type_a", force_open=True)
        dispatches = []

        def mock_trigger(name, date):
            dispatches.append(name)
            self.intra_svc.current_runs[name] = "09:00:00"
            self.intra_svc._cycle_seen_in_pass.add(name)

        self.intra_svc._trigger_report = mock_trigger

        # Tick 1: P0_Crit is dispatched and permanently fails (attempts=1 >= max_retries=1)
        self.intra_svc.tick()
        self.assertEqual(dispatches, ["P0_Crit"])
        self.intra_svc.current_runs.pop("P0_Crit")
        self.intra_svc._cycle_errors_in_pass += 1
        self.intra_svc._cycle_pass_reports.discard("P0_Crit")
        self.auto_svc.update_status("P0_Crit", "Failed", last_output="Exceeded max retries (1/1)")
        self.intra_svc._evaluate_pass_completion(today)

        # Operator fixes P0_Crit and re-enables it via POST /api/automation/enable
        res_en = self.client.post("/api/automation/enable", json={"name": "P0_Crit"})
        self.assertEqual(res_en.status_code, 200)
        self.assertEqual(list(self.intra_svc.waitlist), ["P0_Crit", "P2_Norm"])

        # INVARIANT: Re-enabled P0_Crit must NOT be marked as already seen in the current pass,
        # and must be dispatched ahead of P2_Norm on the next tick.
        self.assertNotIn(
            "P0_Crit", self.intra_svc._cycle_seen_in_pass,
            "F-057: Re-enabled report must be cleared from _cycle_seen_in_pass so it can execute!"
        )
        self.intra_svc.tick()
        self.assertEqual(
            dispatches[-1], "P0_Crit",
            "F-057: Re-enabled P0_Crit at head of waitlist was bypassed by lower-priority P2_Norm!"
        )

    def test_f058_terminal_completion_of_last_pass_report_leaves_counters_dirty(self):
        """
        F-058: When the last report in a pass Completes (or Permanently Fails),
        _cycle_pass_reports.discard(name) empties _cycle_pass_reports BEFORE _evaluate_pass_completion()
        runs, causing _evaluate_pass_completion() to early-return without resetting
        _cycle_completions_in_pass, _cycle_errors_in_pass, or _cycle_seen_in_pass.
        When a new report is subsequently added and skips, starvation cooldown is bypassed!
        """
        self.intra_svc.max_concurrent_run = 1
        self.intra_svc.rotation_cooldown_seconds = 30.0
        self.intra_svc._override_cooldown = 30.0
        today = CLOCK.date_str()

        self.client.post("/api/automation/add", json={
            "name": "Initial_Rep",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P0"
        })

        self.intra_svc.start_lane("type_a", force_open=True)
        dispatches = []

        def mock_trigger(name, date):
            dispatches.append(name)
            self.intra_svc.current_runs[name] = "09:00:00"
            self.intra_svc._cycle_seen_in_pass.add(name)

        self.intra_svc._trigger_report = mock_trigger

        # Initial_Rep runs and completes
        self.intra_svc.tick()
        self.intra_svc.current_runs.pop("Initial_Rep")
        self.intra_svc._cycle_completions_in_pass += 1
        self.intra_svc._cycle_pass_reports.discard("Initial_Rep")
        self.auto_svc.update_status("Initial_Rep", "Completed", last_output="Success")
        self.intra_svc._evaluate_pass_completion(today)

        # Operator adds New_Skip_Rep which skips due to unready dependency
        self.client.post("/api/automation/add", json={
            "name": "New_Skip_Rep",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P1"
        })
        self.intra_svc.tick()
        self.assertEqual(dispatches[-1], "New_Skip_Rep")

        # New_Skip_Rep finishes with dependency skip
        self.intra_svc.current_runs.pop("New_Skip_Rep")
        self.intra_svc.waitlist.append("New_Skip_Rep")
        self.intra_svc._cycle_skips_in_pass += 1
        self.intra_svc._evaluate_pass_completion(today)

        # INVARIANT: Since New_Skip_Rep is the only active report in its pass and skipped,
        # starvation cooldown MUST engage (not be poisoned by Initial_Rep's earlier completion).
        self.assertGreater(
            self.intra_svc._rotation_cooldown_until, time.time(),
            "F-058: Stale _cycle_completions_in_pass from drained pass prevented starvation cooldown!"
        )

    def test_f059_lifecycle_methods_fail_to_reset_skips_and_errors_in_pass(self):
        """
        F-059: start_lane('type_a'), stop_lane('type_a'), start_fresh_run(), and reset_all_reports()
        reset _cycle_completions_in_pass = 0 but omit _cycle_skips_in_pass = 0 and _cycle_errors_in_pass = 0.
        An error prior to stop/restart or reset leaks _cycle_errors_in_pass > 0 into the fresh run,
        bypassing starvation cooldown on the first pass of dependency skips.
        """
        self.intra_svc._cycle_errors_in_pass = 2
        self.intra_svc._cycle_skips_in_pass = 3

        self.intra_svc.stop_lane("type_a")
        self.assertEqual(
            self.intra_svc._cycle_errors_in_pass, 0,
            "F-059: stop_lane('type_a') must reset _cycle_errors_in_pass to 0"
        )
        self.assertEqual(
            self.intra_svc._cycle_skips_in_pass, 0,
            "F-059: stop_lane('type_a') must reset _cycle_skips_in_pass to 0"
        )

        self.intra_svc._cycle_errors_in_pass = 2
        self.intra_svc._cycle_skips_in_pass = 3
        self.intra_svc.start_lane("type_a", force_open=True)
        self.assertEqual(
            self.intra_svc._cycle_errors_in_pass, 0,
            "F-059: start_lane('type_a') must reset _cycle_errors_in_pass to 0"
        )
        self.assertEqual(
            self.intra_svc._cycle_skips_in_pass, 0,
            "F-059: start_lane('type_a') must reset _cycle_skips_in_pass to 0"
        )

        self.intra_svc._cycle_errors_in_pass = 2
        self.intra_svc._cycle_skips_in_pass = 3
        self.intra_svc.reset_all_reports()
        self.assertEqual(
            self.intra_svc._cycle_errors_in_pass, 0,
            "F-059: reset_all_reports() must reset _cycle_errors_in_pass to 0"
        )
        self.assertEqual(
            self.intra_svc._cycle_skips_in_pass, 0,
            "F-059: reset_all_reports() must reset _cycle_skips_in_pass to 0"
        )

    def test_f060_defer_seen_clear_on_disable_inverts_priority_and_starves_p0_pass(self):
        """
        F-060: Calling _evaluate_pass_completion(..., defer_seen_clear=True) in disable_automation
        leaves completed-pass reports in _cycle_seen_in_pass. If a lower-priority report (P2) is added
        or enabled before the next tick, _enqueue_lane_a_by_priority places P2 ahead of P0, and tick()
        runs only P2 before ending Pass 2 without executing P0 at all!
        """
        self.intra_svc.max_concurrent_run = 1
        self.intra_svc.rotation_cooldown_seconds = 30.0
        self.intra_svc._override_cooldown = 30.0
        today = CLOCK.date_str()

        self.client.post("/api/automation/add", json={
            "name": "RepB_P0",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P0"
        })
        self.client.post("/api/automation/add", json={
            "name": "RepC_P1",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P1"
        })

        self.intra_svc.start_lane("type_a", force_open=True)
        dispatches = []

        def mock_trigger(name, date):
            dispatches.append(name)
            self.intra_svc.current_runs[name] = "09:00:00"
            self.intra_svc._cycle_seen_in_pass.add(name)

        self.intra_svc._trigger_report = mock_trigger

        # Pass 1: RepB_P0 runs and skips
        self.intra_svc.tick()
        self.intra_svc.current_runs.pop("RepB_P0")
        self.intra_svc.waitlist.append("RepB_P0")
        self.intra_svc._cycle_skips_in_pass += 1
        self.intra_svc._evaluate_pass_completion(today)

        # Operator disables idle RepC_P1 -> Pass 1 is now complete
        res_dis = self.client.post("/api/automation/disable", json={"name": "RepC_P1"})
        self.assertEqual(res_dis.status_code, 200)

        # Operator adds lower-priority RepD_P2 during cooldown before next tick
        self.client.post("/api/automation/add", json={
            "name": "RepD_P2",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P2"
        })

        # INVARIANT: Since Pass 1 completed when RepC_P1 was disabled, RepB_P0 (P0) must be unseen
        # for Pass 2 and ordered ahead of RepD_P2 (P2).
        self.assertEqual(
            list(self.intra_svc.waitlist), ["RepB_P0", "RepD_P2"],
            "F-060: Priority inverted! P2 report placed ahead of P0 report because _cycle_seen_in_pass was not cleared on pass completion."
        )
        self.intra_svc.tick()
        self.assertEqual(
            dispatches[-1], "RepB_P0",
            "F-060: P0 report was skipped in Pass 2 in favor of P2 report!"
        )


if __name__ == "__main__":
    unittest.main()
