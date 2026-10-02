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
from models.intraday import ReportRun
from utils.clock import CLOCK

class PoCConcurrencySpinAndDeleteLeakVerification(unittest.TestCase):
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

        # Create isolated Flask test app
        self.flask_app, self.paradiso = create_app(storage_dir=self.storage_dir)
        self.flask_app.config["TESTING"] = True
        self.client = self.flask_app.test_client()

        self.intra_svc = self.paradiso.intraday_service
        self.auto_svc = self.intra_svc.automation_service
        self.intraday_repo = self.intra_svc.intraday_repo

        # Set clock baseline to 09:00:00 (OPEN)
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

    def test_f053_concurrency_pool_seen_reports_do_not_fast_spin(self):
        """
        F-053 VERIFIED: Lane A Multi-Slot Concurrency Starvation Cooldown & Seen Reports Protection.
        When max_concurrent_run > 1 and jobs skip due to unready dependencies,
        already-seen jobs must NOT be popped and re-dispatched into freed slots mid-pass.
        Once all jobs in the pass conclude, pass cooldown engages.
        """
        self.intra_svc.max_concurrent_run = 2
        self.intra_svc.rotation_cooldown_seconds = 30.0
        self.intra_svc._override_cooldown = 30.0

        res1 = self.client.post("/api/automation/add", json={
            "name": "Fast_Skip_Rep",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P1"
        })
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post("/api/automation/add", json={
            "name": "Slow_Skip_Rep",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P2"
        })
        self.assertEqual(res2.status_code, 201)

        self.intra_svc.start_lane("type_a", force_open=True)
        self.assertEqual(list(self.intra_svc.waitlist), ["Fast_Skip_Rep", "Slow_Skip_Rep"])
        self.assertEqual(self.intra_svc._cycle_pass_reports, {"Fast_Skip_Rep", "Slow_Skip_Rep"})

        dispatch_counts = {"Fast_Skip_Rep": 0, "Slow_Skip_Rep": 0}

        def mock_trigger(name, date):
            dispatch_counts[name] += 1
            self.intra_svc.current_runs[name] = "09:00:00"
            self.intra_svc._cycle_seen_in_pass.add(name)

        self.intra_svc._trigger_report = mock_trigger

        self.intra_svc.tick()
        self.assertEqual(dispatch_counts["Fast_Skip_Rep"], 1)
        self.assertEqual(dispatch_counts["Slow_Skip_Rep"], 1)
        self.assertEqual(len(self.intra_svc.current_runs), 2)
        self.assertEqual(len(self.intra_svc.waitlist), 0)

        # Fast_Skip_Rep completes with a dependency skip while Slow_Skip_Rep is still running
        self.intra_svc.current_runs.pop("Fast_Skip_Rep")
        self.intra_svc.waitlist.append("Fast_Skip_Rep")
        self.intra_svc._cycle_skips_in_pass += 1
        self.intra_svc._evaluate_pass_completion(CLOCK.date_str())

        # While Slow_Skip_Rep is in-flight, next tick must NOT re-dispatch Fast_Skip_Rep
        self.intra_svc.tick()
        self.assertEqual(
            dispatch_counts["Fast_Skip_Rep"], 1,
            "Fast_Skip_Rep must not re-dispatch mid-pass while already seen."
        )

        # Slow_Skip_Rep finishes with dependency skip
        self.intra_svc.current_runs.pop("Slow_Skip_Rep")
        self.intra_svc.waitlist.append("Slow_Skip_Rep")
        self.intra_svc._cycle_skips_in_pass += 1
        self.intra_svc._evaluate_pass_completion(CLOCK.date_str())

        # Starvation cooldown MUST engage now that the full pass concluded
        self.assertGreater(
            self.intra_svc._rotation_cooldown_until, time.time(),
            "Queue cooldown must engage once all pass items have completed."
        )
        self.assertEqual(len(self.intra_svc._cycle_seen_in_pass), 0)

    def test_f054_delete_automation_purges_runtime_and_storage_state(self):
        """
        F-054 VERIFIED: delete_automation completely purges runtime tracking sets and
        storage run history, allowing re-created automations to be dispatched without starvation.
        """
        today_date = CLOCK.date_str()

        # --- Subtest 1: Lane C Re-creation ---
        res_c = self.client.post("/api/automation/add", json={
            "name": "Timeslot_Report_C",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_c",
            "scheduled_time": "09:00",
            "timeslot_tier": "CUSTOM"
        })
        self.assertEqual(res_c.status_code, 201)

        self.intra_svc.type_c_ran_today.add("Timeslot_Report_C")
        self.intra_svc.type_c_retry_after["Timeslot_Report_C"] = time.time() + 300
        self.intra_svc.type_c_warned.add("Timeslot_Report_C")

        self.intra_svc.stop_scheduler()
        res_del = self.client.delete("/api/automation/delete/Timeslot_Report_C")
        self.assertEqual(res_del.status_code, 200)

        # Verify state is purged
        self.assertNotIn("Timeslot_Report_C", self.intra_svc.type_c_ran_today)
        self.assertNotIn("Timeslot_Report_C", self.intra_svc.type_c_retry_after)
        self.assertNotIn("Timeslot_Report_C", self.intra_svc.type_c_warned)

        # Re-create Timeslot_Report_C
        res_readd = self.client.post("/api/automation/add", json={
            "name": "Timeslot_Report_C",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_c",
            "scheduled_time": "09:00",
            "timeslot_tier": "CUSTOM"
        })
        self.assertEqual(res_readd.status_code, 201)

        # Start Lane C and tick()
        self.intra_svc.start_lane("type_c", force_open=True)
        dispatched_c = []
        self.intra_svc._trigger_type_c_report = lambda name, date: dispatched_c.append(name)
        self.intra_svc.tick()
        self.assertEqual(dispatched_c, ["Timeslot_Report_C"], "Re-created Lane C report dispatches cleanly.")

        # --- Subtest 2: Lane B Re-creation ---
        res_b = self.client.post("/api/automation/add", json={
            "name": "Recurring_Report_B",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_b",
            "interval_minutes": 15
        })
        self.assertEqual(res_b.status_code, 201)

        self.intra_svc.type_b_exhausted.add("Recurring_Report_B")
        self.intra_svc.type_b_last_run["Recurring_Report_B"] = time.time()

        self.intra_svc.stop_scheduler()
        res_del_b = self.client.delete("/api/automation/delete/Recurring_Report_B")
        self.assertEqual(res_del_b.status_code, 200)

        self.assertNotIn("Recurring_Report_B", self.intra_svc.type_b_exhausted)
        self.assertNotIn("Recurring_Report_B", self.intra_svc.type_b_last_run)

        res_readd_b = self.client.post("/api/automation/add", json={
            "name": "Recurring_Report_B",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_b",
            "interval_minutes": 15
        })
        self.assertEqual(res_readd_b.status_code, 201)

        self.intra_svc.start_lane("type_b", force_open=True)
        dispatched_b = []
        self.intra_svc._trigger_type_b_report = lambda name, date: dispatched_b.append(name)
        self.intra_svc.tick()
        self.assertEqual(dispatched_b, ["Recurring_Report_B"], "Re-created Lane B report dispatches cleanly.")

        # --- Subtest 3: Lane A Re-creation via day.reports_ran ---
        res_a = self.client.post("/api/automation/add", json={
            "name": "Sequential_Report_A",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P0"
        })
        self.assertEqual(res_a.status_code, 201)

        self.intraday_repo.add_report_run(
            date=today_date,
            report_name="Sequential_Report_A",
            run=ReportRun(
                started_at="09:00:00",
                finished_at="09:01:00",
                result="completed",
                duration="60s",
                reason="Done"
            )
        )

        self.intra_svc.stop_scheduler()
        res_del_a = self.client.delete("/api/automation/delete/Sequential_Report_A")
        self.assertEqual(res_del_a.status_code, 200)

        day = self.intraday_repo.get_day(today_date)
        self.assertNotIn("Sequential_Report_A", day.reports_ran)

        res_readd_a = self.client.post("/api/automation/add", json={
            "name": "Sequential_Report_A",
            "filename": "sample_report_blueprint.py",
            "filetype": "python",
            "dir": "../reports",
            "report_type": "type_a",
            "priority": "P0"
        })
        self.assertEqual(res_readd_a.status_code, 201)

        self.intra_svc.start_lane("type_a", force_open=True)
        self.assertIn("Sequential_Report_A", self.intra_svc.waitlist, "Re-created Lane A report enqueued into waitlist.")

if __name__ == "__main__":
    unittest.main()
