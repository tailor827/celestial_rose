"""
PoC: F-048 through F-052 — Frontend-to-Backend Integrity Audit Reproduction Suite
=================================================================================
Reproduces and verifies 5 frontend-to-backend integrity defects in isolated storage:

- F-048 (HIGH): Stopping all lanes via `POST /api/paradiso/lane/stop` leaves `Paradiso._thread`
  running (`GET /api/paradiso/status -> running: True`), permanently locking Settings
  (`POST /api/settings -> 409`) and Simulation Clock Reset (`POST /api/settings/simulation/reset -> 409`)
  with no global Stop button in the Web UI.
- F-049 (HIGH): `POST /api/automation/enable` is completely orphaned from the Web UI (`app.js` /
  `index.html` have zero references to `/api/automation/enable`), leaving Disabled and Failed
  reports with no UI control to re-enable them, while `filterAutomationsCatalog` also omits
  `badge-disabled` styling.
- F-050 (MEDIUM): `GET /api/automations` omits live retry counts from `IntradayService`, and
  `app.js` (`renderLaneATable`, `renderLaneBTable`, `renderLaneCTable`) hardcodes
  `item.status === 'Retrial' ? '1 / 3' : '0 / 3'`, falsely displaying 1/3 error retries on
  zero-penalty dependency skips (breaching Invariant I-2) and masking 2/3 genuine failures.
- F-051 (MEDIUM): `triggerClockReset()` in `app.js` silently drops HTTP 409 Conflict responses
  from `POST /api/settings/simulation/reset` (no `else` branch when `!data.ok`), and
  `handleAddReportSubmit()` calls `showSettingsToast()` (which renders inside hidden `#view-settings`)
  instead of `showToast()`.
- F-052 (LOW): `#view-type-b` Active Workers metric card in `index.html` is hardcoded to
  `0 In-Flight` (never updated from `lanes.type_b.running_count`), and `index.html` lines 168,
  535, and 570 still display `EOD (21:00)` instead of `EOD (20:30)`.
"""

import os
import re
import sys
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from app import create_app
from models.report import Report


class TestFrontendBackendIntegrityAudit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.tmpdir.name)
        self.logs_dir = self.storage_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)
        os.environ["PARADISO_LOGS_DIR"] = str(self.logs_dir)
        self.app_js_path = BASE / "web" / "static" / "js" / "app.js"
        self.index_html_path = BASE / "web" / "templates" / "index.html"

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("PARADISO_STORAGE_DIR", None)
        os.environ.pop("PARADISO_LOGS_DIR", None)

    def test_f048_stopping_all_lanes_leaves_scheduler_locked_and_blocks_settings_409(self):
        """F-048: Starting and stopping a lane via UI endpoints leaves paradiso.is_running() True, locking Settings & Sim Reset with 409."""
        app, paradiso = create_app(storage_dir=self.storage_dir)
        app.config["TESTING"] = True
        client = app.test_client()

        try:
            # 1. Operator starts Lane A via UI endpoint
            res_start = client.post("/api/paradiso/lane/start", json={"lane": "type_a", "force_open": True})
            self.assertEqual(res_start.status_code, 200)

            # 2. Operator stops Lane A via UI endpoint (all lanes are now stopped)
            res_stop = client.post("/api/paradiso/lane/stop", json={"lane": "type_a"})
            self.assertEqual(res_stop.status_code, 200)

            lanes_data = client.get("/api/paradiso/lanes/status").get_json()
            self.assertFalse(lanes_data["lanes"]["type_a"]["running"])
            self.assertFalse(lanes_data["lanes"]["type_b"]["running"])
            self.assertFalse(lanes_data["lanes"]["type_c"]["running"])

            # 3. Verify that despite all lanes being stopped, /api/paradiso/status reports running=False
            # and settings / clock reset are NOT locked out with 409!
            status_data = client.get("/api/paradiso/status").get_json()
            res_sim_reset = client.post("/api/settings/simulation/reset")

            self.assertFalse(
                status_data["running"],
                "F-048 Defect: /api/paradiso/status still reports running=True after all lanes are stopped!"
            )
            self.assertEqual(
                res_sim_reset.status_code,
                200,
                f"F-048 Defect: Simulation clock reset rejected with {res_sim_reset.status_code} even though all lanes are stopped!"
            )
        finally:
            paradiso.stop()

    def test_f049_enable_endpoint_connected_in_frontend_and_disabled_badge_styled(self):
        """F-049: Web UI must provide a way to call /api/automation/enable and style Disabled badges in catalog."""
        app_js = self.app_js_path.read_text(encoding="utf-8")
        self.assertIn(
            "/api/automation/enable",
            app_js,
            "F-049 Defect: /api/automation/enable is never called anywhere in app.js! Disabled/Failed reports cannot be re-enabled from the UI."
        )

    def test_f050_automations_api_and_ui_accurate_retry_counts(self):
        """F-050: Dependency-skipped (Retrial) report with 0 error retries must not be hardcoded to '1 / 3' in UI."""
        app_js = self.app_js_path.read_text(encoding="utf-8")
        hardcoded_pattern = "item.status === 'Retrial' ? '1 / 3'"
        self.assertNotIn(
            hardcoded_pattern,
            app_js,
            "F-050 Defect: app.js hardcodes '1 / 3' for all Retrial reports, violating zero-penalty dependency skips (I-2) and masking 2/3 retries!"
        )

    def test_f051_clock_reset_surfaces_409_and_add_report_shows_visible_toast(self):
        """F-051: triggerClockReset must surface !data.ok errors, and handleAddReportSubmit must trigger a visible toast."""
        app_js = self.app_js_path.read_text(encoding="utf-8")

        # Extract triggerClockReset function body
        m_reset = re.search(r"async function triggerClockReset\(\)\s*\{(.*?)\n\}", app_js, re.DOTALL)
        self.assertIsNotNone(m_reset)
        reset_body = m_reset.group(1)
        self.assertTrue(
            "else" in reset_body or "!data.ok" in reset_body or "!res.ok" in reset_body,
            "F-051 Defect: triggerClockReset() has no else/!data.ok branch and silently swallows HTTP 409 errors!"
        )

        # Extract handleAddReportSubmit success branch
        m_add = re.search(r"async function handleAddReportSubmit\(e\)\s*\{(.*?)\n\}", app_js, re.DOTALL)
        self.assertIsNotNone(m_add)
        add_body = m_add.group(1)
        self.assertIn(
            "showToast(",
            add_body,
            "F-051 Defect: handleAddReportSubmit() only calls showSettingsToast() (hidden inside #view-settings) and never calls global showToast()!"
        )

    def test_f052_lane_b_active_workers_bound_and_eod_2030_consistent(self):
        """F-052: #view-type-b Active Workers card must be dynamically bound and index.html must not say EOD (21:00)."""
        index_html = self.index_html_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "EOD (21:00)",
            index_html,
            "F-052 Defect: index.html still contains stale 'EOD (21:00)' labels contradicting the 20:30 EOD standard (F-027/F-047)!"
        )
        self.assertIn(
            "metric-b-active",
            index_html,
            "F-052 Defect: #view-type-b Active Workers metric card has no DOM id and is hardcoded to '0 In-Flight'!"
        )


if __name__ == "__main__":
    unittest.main()
