import unittest
import tempfile
import json
import yaml
from pathlib import Path
from unittest.mock import patch

from app import create_app
from utils.config import (
    load_config,
    save_config,
    validate_config,
    get_sanitized_config,
    CONFIG
)
from utils.clock import CLOCK

class TestSettingsSubsystem(unittest.TestCase):
    def setUp(self):
        self.config_path = Path(__file__).resolve().parent.parent / "config.yaml"
        self.original_config_content = self.config_path.read_text(encoding="utf-8")
        self.app, self.paradiso = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.config_path.write_text(self.original_config_content, encoding="utf-8")
        load_config(self.config_path)
        CLOCK.set_simulation_mode(True)
        CLOCK.set_speed(600.0)

    def test_load_and_save_config_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "test_config.yaml"
            initial_data = {
                "scheduler": {
                    "enabled": True,
                    "auto_start": False,
                    "job_interval_seconds": 15,
                    "intraday_start_time": "07:00",
                    "intraday_idle_time": "21:00",
                    "intraday_close_time": "22:00"
                },
                "secret_key": "super-secret"
            }
            with open(cfg_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(initial_data, f)

            loaded = load_config(cfg_file)
            self.assertEqual(loaded["scheduler"]["intraday_start_time"], "07:00")

            # Update configuration
            update_data = {
                "scheduler": {
                    "intraday_start_time": "08:00",
                    "intraday_idle_time": "20:00",
                    "intraday_close_time": "21:00"
                },
                "simulation": {
                    "enabled": True,
                    "speed_multiplier": 300.0
                }
            }
            saved = save_config(update_data, file_path=cfg_file)
            self.assertEqual(saved["scheduler"]["intraday_start_time"], "08:00")
            self.assertEqual(saved["secret_key"], "super-secret", "Secret key must be preserved when not updated")

            # Verify persisted YAML on disk
            with open(cfg_file, "r", encoding="utf-8") as f:
                disk_data = yaml.safe_load(f)
            self.assertEqual(disk_data["scheduler"]["intraday_start_time"], "08:00")
            self.assertEqual(disk_data["simulation"]["speed_multiplier"], 300.0)

    def test_validation_rules(self):
        # 1. Valid config
        valid_cfg = {
            "scheduler": {
                "job_interval_seconds": 10,
                "intraday_start_time": "06:00",
                "intraday_idle_time": "20:00",
                "intraday_close_time": "21:00"
            },
            "logging": {"level": "DEBUG"},
            "simulation": {"speed_multiplier": 600.0}
        }
        ok, err = validate_config(valid_cfg)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # 2. Invalid interval
        invalid_interval = {"scheduler": {"job_interval_seconds": -5}}
        ok, err = validate_config(invalid_interval)
        self.assertFalse(ok)
        self.assertIn("positive", err)

        # 3. Invalid time format
        invalid_time = {"scheduler": {"intraday_start_time": "25:00"}}
        ok, err = validate_config(invalid_time)
        self.assertFalse(ok)
        self.assertIn("HH:MM", err)

        # 4. Inverted time ordering (start >= idle)
        inverted_order = {
            "scheduler": {
                "intraday_start_time": "22:00",
                "intraday_idle_time": "07:00",
                "intraday_close_time": "23:00"
            }
        }
        ok, err = validate_config(inverted_order)
        self.assertFalse(ok)
        self.assertIn("start_time < intraday_idle_time", err)

        # 5. Invalid log level
        invalid_log = {"logging": {"level": "VERBOSE"}}
        ok, err = validate_config(invalid_log)
        self.assertFalse(ok)
        self.assertIn("logging.level", err)

    def test_get_settings_masks_secret_and_includes_meta(self):
        res = self.client.get("/api/settings")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        settings = data.get("settings", {})
        self.assertEqual(settings.get("secret_key"), "••••••••", "Secret key must be masked in API output")
        self.assertIn("runtime_meta", settings)
        self.assertIn("detected_python", settings["runtime_meta"])
        self.assertIn("sim_speed", settings["runtime_meta"])

    def test_post_settings_hot_reloads_intraday_service_and_clock(self):
        # Save original config to restore later
        original_start = self.paradiso.intraday_service.start_time
        original_idle = self.paradiso.intraday_service.idle_time
        original_close = self.paradiso.intraday_service.close_time
        original_speed = CLOCK.speed_multiplier

        try:
            update_payload = {
                "scheduler": {
                    "auto_start": False,
                    "intraday_start_time": "06:30",
                    "intraday_idle_time": "20:45",
                    "intraday_close_time": "21:45",
                    "job_interval_seconds": 12
                },
                "simulation": {
                    "enabled": True,
                    "speed_multiplier": 300.0
                }
            }
            res = self.client.post("/api/settings", json=update_payload)
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data.get("ok"))

            # Verify runtime hot-reloading
            self.assertEqual(self.paradiso.intraday_service.start_time, "06:30")
            self.assertEqual(self.paradiso.intraday_service.idle_time, "20:45")
            self.assertEqual(self.paradiso.intraday_service.close_time, "21:45")
            self.assertEqual(CLOCK.speed_multiplier, 300.0)
        finally:
            # Restore
            self.client.post("/api/settings", json={
                "scheduler": {
                    "intraday_start_time": original_start,
                    "intraday_idle_time": original_idle,
                    "intraday_close_time": original_close
                },
                "simulation": {
                    "speed_multiplier": original_speed
                }
            })

    def test_post_settings_validation_errors(self):
        # Invalid time format
        res = self.client.post("/api/settings", json={
            "scheduler": {"intraday_start_time": "invalid_time"}
        })
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data.get("ok"))
        self.assertIn("HH:MM", data.get("error", ""))

        # Inverted times
        res2 = self.client.post("/api/settings", json={
            "scheduler": {
                "intraday_start_time": "23:00",
                "intraday_idle_time": "21:00",
                "intraday_close_time": "22:00"
            }
        })
        self.assertEqual(res2.status_code, 400)
        data2 = json.loads(res2.data)
        self.assertFalse(data2.get("ok"))

    def test_simulation_clock_reset(self):
        res = self.client.post("/api/settings/simulation/reset")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("midnight", data.get("message", "").lower())

    def test_post_settings_toggle_simulation_mode_no_deadlock(self):
        """Verifies changing simulation mode via settings API does not deadlock Clock._lock."""
        res1 = self.client.post("/api/settings", json={"simulation": {"enabled": False}})
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(CLOCK.simulation_mode)

        res2 = self.client.post("/api/settings", json={"simulation": {"enabled": True}})
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(CLOCK.simulation_mode)

if __name__ == "__main__":
    unittest.main()
