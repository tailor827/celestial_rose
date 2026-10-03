"""
Adversarial Proof-of-Concept & Verification Suite — Batch 14 (F-061 through F-065)
Target:
  - F-061: Mid-pass cross-lane completion (wake_lane_a_queue) fails to prevent end-of-pass
           starvation cooldown and leaves pre-wakeup skipped P0 reports marked as seen.
  - F-062: Unvalidated settings parameters (max_retries, max_rotation_cooldown_seconds, and
           null scheduler fields) in validate_config() allow disk config corruption, HTTP 500
           crashes, and complete Lane B / cooldown paralysis.
  - F-063: Substring check '"cutoff" in str(reason).lower()' in _get_completed_or_exhausted_reports()
           misclassifies genuine script failures mentioning "cutoff", causing infinite re-execution.
  - F-064: Pre-start timeline events (disable, enable, or manual run) on a new day create an
           uninitialized day record in intraday.json, causing _get_or_init_day() to skip
           set_waiting_all() and starve all prior-day Completed reports (plus start_lane()
           omitting crashed "Running" report recovery).
  - F-065: Manual execution (POST /api/automation/run) of a Lane B or Lane C report while its
           lane is in Standby permanently fails on attempt 1 / max_retries with
           "Exceeded max retries (1/N)".

Execution Isolation:
  All tests run strictly inside tempfile.TemporaryDirectory() sandboxes with
  PARADISO_STORAGE_DIR, PARADISO_LOGS_DIR, and isolated config files. Zero production files are touched.
"""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from app import create_app
from utils.clock import CLOCK
from utils.config import CONFIG


class TestBatch14AuditFindings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sandbox = Path(self._tmp.name)
        self.storage_dir = self.sandbox / "storage"
        self.logs_dir = self.sandbox / "logs"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self._orig_storage_env = os.environ.get("PARADISO_STORAGE_DIR")
        self._orig_logs_env = os.environ.get("PARADISO_LOGS_DIR")
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)

        self._orig_config = copy.deepcopy(dict(CONFIG))
        self.clock = CLOCK
        self._orig_sim_mode = CLOCK.simulation_mode
        self._orig_speed = CLOCK.speed_multiplier
        CLOCK.simulation_mode = True
        CLOCK.speed_multiplier = 2.0
        CLOCK.start_real_time = time.time()
        CLOCK.start_sim_time = datetime(2026, 10, 3, 9, 0, 0)

        self.flask_app, self.paradiso = create_app(storage_dir=self.storage_dir)
        self.flask_app.config["TESTING"] = True
        self.client = self.flask_app.test_client()

        self.intra_svc = self.paradiso.intraday_service
        self.auto_svc = self.intra_svc.automation_service
        self.exec_svc = self.intra_svc.execution_service
        self.exec_svc.log_dir = self.logs_dir

        for r in list(self.auto_svc.get_all()):
            self.auto_svc.delete(r.name)

    def tearDown(self):
        try:
            self.paradiso.stop()
        except Exception:
            pass
        CONFIG.clear()
        CONFIG.update(self._orig_config)
        self.clock.simulation_mode = self._orig_sim_mode
        self.clock.speed_multiplier = self._orig_speed
        if self._orig_storage_env is None:
            os.environ.pop("PARADISO_STORAGE_DIR", None)
        else:
            os.environ["PARADISO_STORAGE_DIR"] = self._orig_storage_env
        if self._orig_logs_env is None:
            os.environ.pop("PARADISO_LOGS_DIR", None)
        else:
            os.environ["PARADISO_LOGS_DIR"] = self._orig_logs_env
        self._tmp.cleanup()

    def _write_receipt(self, name: str, status: str, message: str):
        receipt_path = self.logs_dir / f"{name}.json"
        data = {
            "report_name": name,
            "status": status,
            "timestamp": self.clock.formatted_now(),
            "deliverable": "None",
            "message": message,
        }
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    # =========================================================================
    # F-061: Mid-pass cross-lane completion (wake_lane_a_queue) fails to prevent
    #        end-of-pass starvation cooldown and leaves pre-wakeup skipped P0
    #        reports marked as seen
    # =========================================================================
    def test_f061_mid_pass_cross_lane_completion_prevents_cooldown_and_wakes_p0(self):
        """
        F-061:
        Suppose Lane A has Rep_P0 (waiting on Feed_B in Lane B) and Rep_P2 (waiting on Rep_P0).
        1. Tick 1: Rep_P0 runs in Lane A and Feed_B starts in Lane B.
        2. Rep_P0 checks Feed_B (not done yet) and skips (Retrial).
        3. Feed_B finishes in Lane B (Completed) -> calls wake_lane_a_queue().
        4. Next tick in Lane A:
           - Rep_P0 should be eligible to run (since Feed_B completed after Rep_P0's skip),
             OR even if Rep_P2 runs first and skips, the pass MUST NOT enter a 30s starvation
             cooldown because Feed_B completed during the pass!
        """
        from models.report import Report

        self.auto_svc.add(Report(
            name="Rep_P0", filename="sample_lane_a_01.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a", priority="P0"
        ))
        self.auto_svc.add(Report(
            name="Rep_P2", filename="sample_lane_a_02.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a", priority="P2"
        ))
        self.auto_svc.add(Report(
            name="Feed_B", filename="sample_lane_a_03.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_b", interval_minutes=30
        ))

        self.intra_svc.max_concurrent_run = 1
        self.intra_svc._override_cooldown = 30.0
        callbacks = {}

        def fake_execute(name, callback_good=None, callback_fail=None):
            self.auto_svc.update_status(name=name, status="Running", started_at=self.clock.time_str())
            callbacks[name] = (callback_good, callback_fail)
            return True

        self.exec_svc.execute_report = fake_execute

        self.intra_svc.start_lane("type_a")
        self.intra_svc.start_lane("type_b")

        # Tick 1: dispatches Rep_P0 (Lane A) and Feed_B (Lane B)
        self.intra_svc.tick()
        self.assertIn("Rep_P0", callbacks)
        self.assertIn("Feed_B", callbacks)

        # Step 1: Rep_P0 finishes first and skips because Feed_B hasn't completed yet
        cb_good_p0, _ = callbacks.pop("Rep_P0")
        self._write_receipt("Rep_P0", "Retrial", "SKIPPED: waiting for Feed_B")
        self.auto_svc.update_status(name="Rep_P0", status="Retrial", duration="1s", last_output="SKIPPED")
        cb_good_p0("Rep_P0", "1s", "SKIPPED")

        # Step 2: Feed_B finishes in Lane B (Completed) -> triggers wake_lane_a_queue()!
        cb_good_b, _ = callbacks.pop("Feed_B")
        self._write_receipt("Feed_B", "Completed", "Feed_B delivered")
        self.auto_svc.update_status(name="Feed_B", status="Completed", duration="1s", last_output="OK")
        cb_good_b("Feed_B", "1s", "OK")

        # Step 3: Next tick(s) in Lane A. If Rep_P2 is dispatched, it skips because Rep_P0 hasn't completed yet.
        self.intra_svc.tick()
        if "Rep_P2" in callbacks:
            cb_good_p2, _ = callbacks.pop("Rep_P2")
            self._write_receipt("Rep_P2", "Retrial", "SKIPPED: waiting for Rep_P0")
            self.auto_svc.update_status(name="Rep_P2", status="Retrial", duration="1s", last_output="SKIPPED")
            cb_good_p2("Rep_P2", "1s", "SKIPPED")

        # Because Feed_B completed after Rep_P0 skipped, Lane A MUST NOT be locked in a 30s starvation cooldown!
        self.assertEqual(
            self.intra_svc._rotation_cooldown_until,
            0.0,
            f"F-061: Lane A entered starvation cooldown (until={self.intra_svc._rotation_cooldown_until}) despite Feed_B completing mid-pass!"
        )

    # =========================================================================
    # F-062: Unvalidated settings parameters in validate_config() allow disk
    #        corruption, HTTP 500 crashes, and Lane B / cooldown paralysis
    # =========================================================================
    def test_f062_settings_validation_prevents_invalid_max_retries_cooldown_and_nulls(self):
        """
        F-062:
        1. max_retries <= 0 must be rejected with HTTP 400 (not 200 OK).
        2. max_retries = "not_an_int" must be rejected with HTTP 400 WITHOUT corrupting CONFIG / config.yaml.
        3. max_rotation_cooldown_seconds <= 0 or < rotation_cooldown_seconds must be rejected with HTTP 400.
        4. lane_c_catch_up_grace_minutes = None must be rejected with HTTP 400 (not HTTP 500 TypeError).
        5. intraday_start_time = None must be rejected with HTTP 400 (not 200 OK crashing resolve_status).
        6. lane_c_catch_up_policy = None must be rejected with HTTP 400 or preserve valid policy (not set "NONE").
        """
        from utils import config as config_mod

        temp_cfg_file = self.sandbox / "test_config.yaml"
        with open(BASE / "config.yaml", "r", encoding="utf-8") as f:
            temp_cfg_file.write_text(f.read(), encoding="utf-8")

        orig_save = config_mod.save_config
        from controllers import settings_controller as sc_mod

        def sandboxed_save(new_values, file_path=None):
            return orig_save(new_values, file_path=temp_cfg_file)

        sc_mod.save_config = sandboxed_save
        try:
            # 1. max_retries: 0 must be rejected with 400
            res1 = self.client.post("/api/settings", json={"scheduler": {"max_retries": 0}})
            self.assertEqual(res1.status_code, 400, f"F-062: max_retries=0 accepted with {res1.status_code}")

            # 2. max_retries: "abc" must be rejected without corrupting temp_cfg_file
            res2 = self.client.post("/api/settings", json={"scheduler": {"max_retries": "abc"}})
            self.assertEqual(res2.status_code, 400)
            loaded = config_mod.load_config(file_path=temp_cfg_file)
            self.assertIsInstance(
                loaded["scheduler"]["max_retries"],
                int,
                f"F-062: Invalid max_retries='abc' was persisted to config.yaml before reload_config failed: {loaded['scheduler']['max_retries']}"
            )

            # 3. max_rotation_cooldown_seconds: -10 must be rejected with 400
            res3 = self.client.post("/api/settings", json={"scheduler": {"max_rotation_cooldown_seconds": -10}})
            self.assertEqual(res3.status_code, 400, f"F-062: max_rotation_cooldown_seconds=-10 accepted with {res3.status_code}")

            # 4. lane_c_catch_up_grace_minutes: None must return 400 (not 500)
            res4 = self.client.post("/api/settings", json={"scheduler": {"lane_c_catch_up_grace_minutes": None}})
            self.assertEqual(res4.status_code, 400, f"F-062: lane_c_catch_up_grace_minutes=None returned {res4.status_code}")

            # 5. intraday_start_time: None must return 400 (not 200 crashing resolve_status)
            res5 = self.client.post("/api/settings", json={"scheduler": {"intraday_start_time": None}})
            self.assertEqual(res5.status_code, 400, f"F-062: intraday_start_time=None returned {res5.status_code}")
            # Ensure resolve_status() still works without TypeError
            self.assertIsInstance(self.intra_svc.resolve_status(), str)
        finally:
            sc_mod.save_config = orig_save

    # =========================================================================
    # F-063: Substring check '"cutoff" in str(reason).lower()' in
    #        _get_completed_or_exhausted_reports() misclassifies genuine script
    #        failures mentioning "cutoff", causing infinite re-execution
    # =========================================================================
    def test_f063_failed_report_with_cutoff_in_error_message_does_not_loop_infinitely(self):
        """
        F-063:
        When a Lane A script fails and its error output mentions the word 'cutoff'
        (e.g. 'Database error: missing EOD cutoff timestamp'), once it exhausts max_retries
        and is marked Failed ('Exceeded max retries (2/2): Database error: missing EOD cutoff timestamp'),
        _get_completed_or_exhausted_reports() must treat it as exhausted and NOT re-queue it on subsequent ticks.
        """
        from models.report import Report

        self.auto_svc.add(Report(
            name="Rep_Cutoff_Query", filename="sample_lane_a_01.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a", priority="P0"
        ))
        self.intra_svc.max_retries = 2
        run_count = 0

        def fake_execute(name, callback_good=None, callback_fail=None):
            nonlocal run_count
            run_count += 1
            self.auto_svc.update_status(name=name, status="Running", started_at=self.clock.time_str())
            err = "SQL Error: missing EOD cutoff date in ledger table"
            self._write_receipt(name, "Failed", err)
            self.auto_svc.update_status(name=name, status="Failed", duration="1s", last_output=err)
            callback_fail(name, "1s", err)
            return True

        self.exec_svc.execute_report = fake_execute
        self.intra_svc.start_lane("type_a")

        # Tick 1 (attempt 1/2), Tick 2 (attempt 2/2 -> permanently Failed), Tick 3 & Tick 4 (should NOT run!)
        for _ in range(4):
            self.intra_svc.tick()

        self.assertEqual(
            run_count,
            2,
            f"F-063: Permanently failed report with 'cutoff' in error message ran {run_count} times (expected max_retries=2)!"
        )
        self.assertEqual(self.auto_svc.get_by_name("Rep_Cutoff_Query").status, "Failed")
        self.assertNotIn("Rep_Cutoff_Query", list(self.intra_svc.waitlist))

    # =========================================================================
    # F-064: Pre-start timeline events (disable/enable/run) on a new day create
    #        an uninitialized day record in intraday.json, causing _get_or_init_day()
    #        to skip set_waiting_all() and starve all prior-day Completed reports
    # =========================================================================
    def test_f064_pre_start_disable_or_enable_on_new_day_does_not_skip_set_waiting_all(self):
        """
        F-064:
        Suppose yesterday Rep_Daily_A (Lane A) and Rep_Daily_C (Lane C) completed
        (so their status in automations.json is 'Completed'), and Rep_Aux is Waiting.
        Today at 09:00 AM (cold boot in Standby Mode), before starting any lane, the operator
        disables Rep_Aux via POST /api/automation/disable (which logs a timeline event for today).
        When the operator then starts Lane A and Lane C via start_lane(), _get_or_init_day()
        must still initialize today's day and reset Rep_Daily_A and Rep_Daily_C from yesterday's
        'Completed' back to 'Waiting' so they are queued and executed today!
        """
        from models.report import Report

        self.auto_svc.add(Report(
            name="Rep_Daily_A", filename="sample_lane_a_01.py", filetype="python",
            dir="../reports", status="Completed", last_run="2026-10-02 10:00:00 AM",
            report_type="type_a", priority="P0"
        ))
        self.auto_svc.add(Report(
            name="Rep_Daily_C", filename="sample_lane_a_02.py", filetype="python",
            dir="../reports", status="Completed", last_run="2026-10-02 08:30:00 AM",
            scheduled_time="08:30", timeslot_tier="CUSTOM", report_type="type_c"
        ))
        self.auto_svc.add(Report(
            name="Rep_Aux", filename="sample_lane_a_03.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a", priority="P2"
        ))

        self.auto_svc.add(Report(
            name="Rep_Crashed_A", filename="sample_lane_a_04.py", filetype="python",
            dir="../reports", status="Running", last_run="2026-10-02 11:00:00 AM",
            report_type="type_a", priority="P1"
        ))

        # Operator disables Rep_Aux in Standby Mode before starting lanes today
        res = self.client.post("/api/automation/disable", json={"name": "Rep_Aux"})
        self.assertEqual(res.status_code, 200)

        # Operator starts Lane A and Lane C
        self.intra_svc.start_lane("type_a")
        self.intra_svc.start_lane("type_c")

        self.assertEqual(
            self.auto_svc.get_by_name("Rep_Daily_A").status,
            "Waiting",
            "F-064: Rep_Daily_A remained stuck in yesterday's 'Completed' status because pre-start disable created a bare day record!"
        )
        self.assertIn(
            "Rep_Daily_A",
            list(self.intra_svc.waitlist),
            "F-064: Rep_Daily_A was starved from today's Lane A waitlist!"
        )
        self.assertEqual(
            self.auto_svc.get_by_name("Rep_Daily_C").status,
            "Waiting",
            "F-064: Rep_Daily_C remained stuck in yesterday's 'Completed' status!"
        )
        self.assertEqual(
            self.auto_svc.get_by_name("Rep_Crashed_A").status,
            "Waiting",
            "F-064: Rep_Crashed_A left in 'Running' from a crashed session was not recovered to 'Waiting' on start_lane!"
        )

    # =========================================================================
    # F-065: Manual execution (POST /api/automation/run) of a Lane B or Lane C
    #        report while its lane is in Standby permanently fails on attempt
    #        1 / max_retries with "Exceeded max retries (1/N)"
    # =========================================================================
    def test_f065_manual_run_while_lane_standby_does_not_permanently_fail_on_first_attempt(self):
        """
        F-065:
        When a Type B or Type C report is triggered manually via POST /api/automation/run
        during OPEN while its lane is in Standby (lane_b_active == False / lane_c_active == False),
        and the script encounters 1 error (with max_retries = 5):
        - It must NOT be marked permanently Failed ("Exceeded max retries (1/5)") or added to
          type_b_exhausted / type_c_ran_today on attempt 1 of 5!
        - When the operator subsequently starts Lane B / Lane C, the report must still have 4
          remaining retries and be eligible to run.
        """
        from models.report import Report

        self.auto_svc.add(Report(
            name="Rep_Manual_B", filename="sample_lane_a_01.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_b", interval_minutes=15
        ))
        self.auto_svc.add(Report(
            name="Rep_Manual_C", filename="sample_lane_a_02.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_c", scheduled_time="08:30", timeslot_tier="CUSTOM"
        ))
        self.intra_svc.max_retries = 5

        def fake_execute(name, callback_good=None, callback_fail=None):
            self.auto_svc.update_status(name=name, status="Running", started_at=self.clock.time_str())
            self._write_receipt(name, "Failed", "Transient network timeout")
            self.auto_svc.update_status(name=name, status="Failed", duration="1s", last_output="Transient network timeout")
            callback_fail(name, "1s", "Transient network timeout")
            return True

        self.exec_svc.execute_report = fake_execute

        # Trigger manual run while Lane B and Lane C are in Standby
        res_b = self.client.post("/api/automation/run", json={"name": "Rep_Manual_B"})
        self.assertEqual(res_b.status_code, 200)
        res_c = self.client.post("/api/automation/run", json={"name": "Rep_Manual_C"})
        self.assertEqual(res_c.status_code, 200)

        rep_b = self.auto_svc.get_by_name("Rep_Manual_B")
        self.assertNotIn(
            "Rep_Manual_B",
            self.intra_svc.type_b_exhausted,
            f"F-065: Manual run failure on attempt 1/5 prematurely exhausted Rep_Manual_B (last_output={rep_b.last_output})!"
        )
        self.assertEqual(
            rep_b.status,
            "Retrial",
            f"F-065: Expected status 'Retrial' after 1/5 failure, got '{rep_b.status}' ({rep_b.last_output})"
        )

        rep_c = self.auto_svc.get_by_name("Rep_Manual_C")
        self.assertNotIn(
            "Rep_Manual_C",
            self.intra_svc.type_c_ran_today,
            f"F-065: Manual run failure on attempt 1/5 prematurely marked Rep_Manual_C in type_c_ran_today (last_output={rep_c.last_output})!"
        )
        self.assertEqual(
            rep_c.status,
            "Retrial",
            f"F-065: Expected status 'Retrial' after 1/5 failure, got '{rep_c.status}' ({rep_c.last_output})"
        )


if __name__ == "__main__":
    unittest.main()
