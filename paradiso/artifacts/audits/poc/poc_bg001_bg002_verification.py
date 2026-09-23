"""
Adversarial verification script for BG-001 (Idle-Only Settings Guardrail)
and BG-002 / F-009 (Start/Stop Transition Cooldown & Mutex Concurrency Guards).
"""
import sys
import time
import json
import threading
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from app import create_app
from services.paradiso import Paradiso

class TestBG001BG002AdversarialVerification(unittest.TestCase):
    def setUp(self):
        self.app, self.paradiso = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            self.paradiso.stop()
        except Exception:
            pass

    def test_bg001_settings_mutation_blocked_during_active_scheduler(self):
        """Attacks BG-001: Attempts to modify runtime settings while scheduler is active."""
        self.paradiso.start()
        self.assertTrue(self.paradiso.is_running())

        # Attempt to modify settings via API
        res = self.client.post("/api/settings", json={
            "scheduler": {
                "job_interval_seconds": 99.0
            }
        })

        self.assertEqual(res.status_code, 409, "Active scheduler must reject settings mutations with HTTP 409 Conflict.")
        data = res.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("cannot be modified while Paradiso scheduler is running", data.get("error", ""))

    def test_bg001_settings_mutation_blocked_when_jobs_in_flight(self):
        """Attacks BG-001: Scheduler thread is stopped, but an in-flight report is still executing."""
        self.assertFalse(self.paradiso.is_running())

        # Simulate in-flight report in intraday service
        with self.paradiso.intraday_service._lock:
            self.paradiso.intraday_service.current_runs["Adversarial_InFlight_Report"] = "09:00"

        try:
            res = self.client.post("/api/settings", json={
                "scheduler": {
                    "job_interval_seconds": 99.0
                }
            })
            self.assertEqual(res.status_code, 409, "In-flight jobs must block settings mutation even if scheduler thread is stopped.")
            data = res.get_json()
            self.assertFalse(data.get("ok"))
            self.assertIn("cannot be modified while Paradiso scheduler is running", data.get("error", ""))
        finally:
            with self.paradiso.intraday_service._lock:
                self.paradiso.intraday_service.current_runs.clear()

    def test_bg002_rapid_burst_concurrent_starts_spawn_strictly_one_loop(self):
        """Attacks F-009 / BG-002: 25 simultaneous concurrent threads hammer start() to race thread creation."""
        threads = []
        outcomes = []

        def attack_worker():
            res = self.paradiso.start()
            outcomes.append(res)

        for _ in range(25):
            t = threading.Thread(target=attack_worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertTrue(self.paradiso.is_running())

        # Exactly 1 thread must have succeeded with 'started'
        started_count = sum(1 for r in outcomes if r.status == "started")
        already_running_count = sum(1 for r in outcomes if r.status == "already_running")

        self.assertEqual(started_count, 1, f"Expected exactly 1 started outcome, got {started_count}")
        self.assertEqual(already_running_count, 24, f"Expected 24 already_running outcomes, got {already_running_count}")

    def test_bg002_transition_cooldown_enforcement(self):
        """Attacks BG-002: Rapid start/stop cycling within 10s cooldown must trigger HTTP 429."""
        self.paradiso._enforce_cooldown = True
        self.paradiso.transition_cooldown = 10.0

        try:
            # 1. Start scheduler
            res1 = self.client.post("/api/paradiso/start")
            self.assertEqual(res1.status_code, 200)

            # 2. Immediate stop must be blocked with HTTP 429 Too Many Requests
            res2 = self.client.post("/api/paradiso/stop")
            self.assertEqual(res2.status_code, 429, "Immediate stop within cooldown must return HTTP 429.")
            data2 = res2.get_json()
            self.assertFalse(data2.get("ok"))
            self.assertIn("cooldown active", data2.get("error", "").lower())
            self.assertGreater(data2.get("cooldown_remaining", 0), 0)

            # 3. Simulate passage of 11 seconds
            self.paradiso._last_transition_time -= 11.0

            # 4. Stop succeeds now
            res3 = self.client.post("/api/paradiso/stop")
            self.assertEqual(res3.status_code, 200)

            # 5. Immediate restart blocked with HTTP 429
            res4 = self.client.post("/api/paradiso/start")
            self.assertEqual(res4.status_code, 429, "Immediate restart within cooldown must return HTTP 429.")
        finally:
            self.paradiso._enforce_cooldown = False
            self.paradiso.stop()

    def test_f009_start_while_running_does_not_wipe_in_flight_state(self):
        """Attacks F-009 Trap 1: Calling start() while running must not wipe retry_counts or reset Running jobs."""
        self.paradiso.start()

        # Seed in-flight execution state
        with self.paradiso.intraday_service._lock:
            self.paradiso.intraday_service.current_runs["Active_Tax_Report"] = "09:30"
            self.paradiso.intraday_service.retry_counts["Active_Tax_Report"] = 2
            self.paradiso.intraday_service.automation_service.update_status(
                name="Active_Tax_Report",
                status="Running",
                duration="45s"
            )

        # Attack: redundant start call
        res = self.paradiso.start()
        self.assertEqual(res.status, "already_running")

        # Invariant check: retry_counts and current_runs must be pristine
        self.assertEqual(
            self.paradiso.intraday_service.retry_counts.get("Active_Tax_Report"),
            2,
            "Redundant start() call wiped retry_counts!"
        )
        self.assertIn(
            "Active_Tax_Report",
            self.paradiso.intraday_service.current_runs,
            "Redundant start() call evicted in-flight task from current_runs!"
        )
        report = self.paradiso.intraday_service.automation_service.get_by_name("Active_Tax_Report")
        if report:
            self.assertEqual(report.status, "Running", "In-flight report was prematurely reset from Running to Waiting!")

    def test_f009_stop_synchronously_eliminates_zombie_threads(self):
        """Attacks F-009 Trap 2: Verified that stop() leaves zero zombie threads alive."""
        self.paradiso.start()
        running_thread = self.paradiso._thread
        self.assertIsNotNone(running_thread)
        self.assertTrue(running_thread.is_alive())

        self.paradiso.stop()
        self.assertFalse(running_thread.is_alive(), "stop() must synchronously join and terminate the loop thread.")
        self.assertIsNone(self.paradiso._thread)

if __name__ == "__main__":
    unittest.main()
