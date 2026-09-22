import unittest
import json
from unittest.mock import patch
from app import create_app
from utils.config import CONFIG
from utils.clock import CLOCK

class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.app, self.paradiso = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_index_route(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"PARADISO", res.data)

    def test_get_automations_route(self):
        res = self.client.get("/api/automations")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("automations", data)
        self.assertIsInstance(data["automations"], list)

    def test_dashboard_stats_route(self):
        res = self.client.get("/api/dashboard/stats")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("metrics", data)

    def test_dashboard_timeline_route(self):
        res = self.client.get("/api/dashboard/timeline")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("timeline", data)
        self.assertIsInstance(data["timeline"], list)
        if len(data["timeline"]) > 0:
            first_event = data["timeline"][0]
            self.assertIn("timestamp", first_event)
            self.assertIn("title", first_event)
            self.assertIn("description", first_event)
            self.assertIn("type", first_event)

    def test_standby_on_startup_no_automatic_execution(self):
        """Ensures that on app launch, nothing starts automatically unless explicitly triggered from UI."""
        # 1. Verify scheduler thread is NOT running initially
        res_status = self.client.get("/api/paradiso/status")
        data_status = json.loads(res_status.data)
        self.assertFalse(data_status.get("running"), "Scheduler must boot in standby mode (running=False).")

        # 2. Verify intraday service force_open flag is False
        self.assertFalse(self.paradiso.intraday_service.force_open, "Intraday service force_open must be False on boot.")

        # 3. Verify metrics show zero reports running automatically on boot
        res_stats = self.client.get("/api/dashboard/stats")
        data_stats = json.loads(res_stats.data)
        metrics = data_stats.get("metrics", {})
        self.assertEqual(metrics.get("running"), 0, "No reports should be running automatically on boot.")

        # 4. Explicit UI trigger via POST /api/paradiso/start is required to launch scheduler
        res_start = self.client.post("/api/paradiso/start")
        self.assertTrue(json.loads(res_start.data).get("ok"))

        # Verify scheduler is now running after explicit UI trigger
        res_status_active = self.client.get("/api/paradiso/status")
        self.assertTrue(json.loads(res_status_active.data).get("running"))

        # Clean up: stop scheduler to return to standby
        self.client.post("/api/paradiso/stop")

    def test_paradiso_scheduler_start_stop_status(self):
        # Initial status should be standby (running = False)
        res_status = self.client.get("/api/paradiso/status")
        self.assertEqual(res_status.status_code, 200)
        data_status = json.loads(res_status.data)
        self.assertFalse(data_status.get("running"))

        # Trigger start
        res_start = self.client.post("/api/paradiso/start")
        self.assertEqual(res_start.status_code, 200)
        data_start = json.loads(res_start.data)
        self.assertTrue(data_start.get("ok"))

        # Verify running status
        res_status2 = self.client.get("/api/paradiso/status")
        data_status2 = json.loads(res_status2.data)
        self.assertTrue(data_status2.get("running"))

        # Trigger stop
        res_stop = self.client.post("/api/paradiso/stop")
        self.assertEqual(res_stop.status_code, 200)
        data_stop = json.loads(res_stop.data)
        self.assertTrue(data_stop.get("ok"))

        # Verify stopped status
        res_status3 = self.client.get("/api/paradiso/status")
        data_status3 = json.loads(res_status3.data)
        self.assertFalse(data_status3.get("running"))

    def test_reset_automations_route(self):
        res = self.client.post("/api/automations/reset")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))

    def test_trigger_single_automation_run(self):
        """Verifies that manual trigger attempts on Type A intraday reports return 403 Disabled error."""
        res = self.client.post("/api/automation/run", json={"name": "Delinquency_RollRate"})
        self.assertEqual(res.status_code, 403)
        data = json.loads(res.data)
        self.assertFalse(data.get("ok"))
        self.assertIn("disabled", data.get("error", "").lower())

    def test_executions_history_route(self):
        res = self.client.get("/api/executions/history")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)
        self.assertIsInstance(data["history"], list)

    def test_executions_log_route(self):
        res = self.client.get("/api/executions/log/Delinquency_RollRate")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("name"), "Delinquency_RollRate")
        self.assertIn("log", data)

    def test_dashboard_stats_simulation_metadata(self):
        """Verifies stats endpoint returns date, sim_speed, sim_mode, and 12-hr AM/PM formatted time."""
        CLOCK.set_simulation_mode(True)
        CLOCK.set_speed(600.0)
        try:
            res = self.client.get("/api/dashboard/stats")
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data.get("ok"))
            self.assertIn("date", data)
            self.assertEqual(data.get("sim_speed"), "10m/s")
            self.assertTrue(data.get("sim_mode"))
            self.assertTrue("AM" in data.get("time", "") or "PM" in data.get("time", ""))

            # Verify disabled simulation mode returns "Realtime"
            CLOCK.set_simulation_mode(False)
            res_real = self.client.get("/api/dashboard/stats")
            self.assertEqual(res_real.status_code, 200)
            data_real = json.loads(res_real.data)
            self.assertEqual(data_real.get("sim_speed"), "Realtime")
            self.assertFalse(data_real.get("sim_mode"))
        finally:
            CLOCK.set_simulation_mode(True)
            CLOCK.set_speed(600.0)

    def test_auto_start_configuration_starts_scheduler(self):
        """Verifies that auto_start=True via parameter or CONFIG['scheduler']['auto_start'] activates the scheduler on app launch."""
        # 1. Verify direct create_app(auto_start=True) boots in active mode
        app_auto, paradiso_auto = create_app(auto_start=True)
        try:
            self.assertTrue(paradiso_auto.is_running(), "Scheduler must be running when auto_start=True is passed.")
            self.assertTrue(paradiso_auto.intraday_service.is_active, "IntradayService must be active when auto_start=True.")
        finally:
            paradiso_auto.stop()
        self.assertFalse(paradiso_auto.is_running())

        # 2. Verify CONFIG["scheduler"]["auto_start"] = True activates scheduler on standard boot
        with patch.dict(CONFIG, {"scheduler": {"auto_start": True}}, clear=False):
            app_cfg, paradiso_cfg = create_app()
            try:
                self.assertTrue(paradiso_cfg.is_running(), "Scheduler must start on boot when CONFIG['scheduler']['auto_start'] is True.")
                self.assertTrue(paradiso_cfg.intraday_service.is_active)
            finally:
                paradiso_cfg.stop()

        # 3. Verify CONFIG["scheduler"]["auto_start"] = False leaves scheduler in standby mode
        with patch.dict(CONFIG, {"scheduler": {"auto_start": False}}, clear=False):
            app_std, paradiso_std = create_app()
            self.assertFalse(paradiso_std.is_running(), "Scheduler must stay dormant on boot when CONFIG['scheduler']['auto_start'] is False.")
            self.assertFalse(paradiso_std.intraday_service.is_active)

    def test_add_and_delete_automation_endpoints(self):
        """Verifies adding a report via POST /api/automation/add and removing it via DELETE /api/automation/delete/<name>."""
        test_name = "Test_Custom_Report"
        auto_svc = self.paradiso.intraday_service.automation_service
        try:
            # 1. Add valid report
            payload = {
                "name": test_name,
                "filename": "custom_script.py",
                "filetype": "python",
                "dir": "../reports",
                "team": "Analytics",
                "owner": "Test User",
                "scheduled_time": "14:00",
                "status": "Waiting"
            }
            res = self.client.post("/api/automation/add", json=payload)
            self.assertEqual(res.status_code, 201)
            data = json.loads(res.data)
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("report", {}).get("name"), test_name)

            # Verify presence in automation service
            report = auto_svc.get_by_name(test_name)
            self.assertIsNotNone(report)
            self.assertEqual(report.filename, "custom_script.py")
            self.assertEqual(report.team, "Analytics")

            # 2. Duplicate addition returns 409 Conflict
            res_dup = self.client.post("/api/automation/add", json=payload)
            self.assertEqual(res_dup.status_code, 409)
            data_dup = json.loads(res_dup.data)
            self.assertFalse(data_dup.get("ok"))
            self.assertIn("already exists", data_dup.get("error", "").lower())

            # 3. Delete report returns 200
            res_del = self.client.delete(f"/api/automation/delete/{test_name}")
            self.assertEqual(res_del.status_code, 200)
            data_del = json.loads(res_del.data)
            self.assertTrue(data_del.get("ok"))

            # Verify deletion
            self.assertIsNone(auto_svc.get_by_name(test_name))
        finally:
            # Ensure cleanup
            auto_svc.delete(test_name)

    def test_add_automation_validation_errors(self):
        """Verifies 400 Bad Request on empty or missing name and filename."""
        res_empty = self.client.post("/api/automation/add", json={})
        self.assertEqual(res_empty.status_code, 400)
        self.assertFalse(json.loads(res_empty.data).get("ok"))

        res_no_file = self.client.post("/api/automation/add", json={"name": "NoFileReport"})
        self.assertEqual(res_no_file.status_code, 400)

        res_no_name = self.client.post("/api/automation/add", json={"filename": "test.py"})
        self.assertEqual(res_no_name.status_code, 400)

    def test_delete_automation_not_found(self):
        """Verifies 404 Not Found when deleting non-existent report."""
        res = self.client.delete("/api/automation/delete/NonExistentReportXYZ123")
        self.assertEqual(res.status_code, 404)
        data = json.loads(res.data)
        self.assertFalse(data.get("ok"))
        self.assertIn("not found", data.get("error", "").lower())

    def test_add_automation_enqueues_to_active_intraday_scheduler(self):
        """Verifies adding a Waiting report enqueues into waitlist when intraday_service is active."""
        test_name = "Test_Queue_Report"
        auto_svc = self.paradiso.intraday_service.automation_service
        try:
            self.paradiso.start()
            self.assertTrue(self.paradiso.intraday_service.is_active)

            payload = {
                "name": test_name,
                "filename": "queue_test.py",
                "status": "Waiting"
            }
            res = self.client.post("/api/automation/add", json=payload)
            self.assertEqual(res.status_code, 201)

            with self.paradiso.intraday_service._lock:
                self.assertIn(test_name, self.paradiso.intraday_service.waitlist)

            # Deleting while active is rejected with 409 (Brick Wall policy)
            res_del = self.client.delete(f"/api/automation/delete/{test_name}")
            self.assertEqual(res_del.status_code, 409)

            # Stopping scheduler allows deletion
            self.paradiso.stop()
            res_del_stopped = self.client.delete(f"/api/automation/delete/{test_name}")
            self.assertEqual(res_del_stopped.status_code, 200)

            with self.paradiso.intraday_service._lock:
                self.assertNotIn(test_name, self.paradiso.intraday_service.waitlist)
        finally:
            self.paradiso.stop()
            auto_svc.delete(test_name)

if __name__ == "__main__":
    unittest.main()

