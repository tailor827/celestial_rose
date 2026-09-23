from typing import Optional, TYPE_CHECKING
from flask import Flask, jsonify, request
from services.intraday_service import IntradayService
from utils.config import get_sanitized_config, save_config
from utils.clock import CLOCK

if TYPE_CHECKING:
    from services.paradiso import Paradiso

class SettingsController:
    """REST API Controller for configuration management and dynamic runtime updates."""
    def __init__(self, app: Flask, intraday_service: IntradayService, paradiso: Optional["Paradiso"] = None):
        self.intraday_service = intraday_service
        self.paradiso = paradiso
        self._register_routes(app)

    def _register_routes(self, app: Flask):
        app.add_url_rule("/api/settings", "get_settings", self.get_settings, methods=["GET"])
        app.add_url_rule("/api/settings", "update_settings", self.update_settings, methods=["POST"])
        app.add_url_rule("/api/settings/simulation/reset", "reset_sim_clock", self.reset_simulation_clock, methods=["POST"])

    def get_settings(self):
        cfg = get_sanitized_config()
        cfg["runtime_meta"]["clock_time"] = CLOCK.time_str()
        cfg["runtime_meta"]["clock_date"] = CLOCK.formatted_date()
        cfg["runtime_meta"]["sim_mode"] = CLOCK.simulation_mode
        cfg["runtime_meta"]["sim_speed"] = CLOCK.speed_multiplier
        cfg["runtime_meta"]["intraday_start_time"] = self.intraday_service.start_time
        cfg["runtime_meta"]["intraday_idle_time"] = self.intraday_service.idle_time
        cfg["runtime_meta"]["intraday_close_time"] = self.intraday_service.close_time
        return jsonify({"ok": True, "settings": cfg}), 200

    def update_settings(self):
        # BG-001: Idle-Only Configuration Guardrail
        is_active = False
        if self.paradiso and self.paradiso.is_running():
            is_active = True
        elif self.intraday_service and (self.intraday_service.is_active or len(self.intraday_service.current_runs) > 0):
            is_active = True

        if is_active:
            return jsonify({
                "ok": False,
                "error": "Settings cannot be modified while Paradiso scheduler is running. Please stop Paradiso before updating settings."
            }), 409

        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"ok": False, "error": "Invalid JSON body provided."}), 400

        try:
            updated_cfg = save_config(data)

            # Hot-reload IntradayService thresholds
            self.intraday_service.reload_config(updated_cfg)

            # Hot-reload CLOCK if simulation parameters supplied
            sim = updated_cfg.get("simulation", {})
            if "enabled" in sim:
                CLOCK.set_simulation_mode(bool(sim["enabled"]))
            if "speed_multiplier" in sim:
                CLOCK.set_speed(float(sim["speed_multiplier"]))

            sanitized = get_sanitized_config()
            return jsonify({
                "ok": True,
                "message": "Configuration saved and applied successfully.",
                "settings": sanitized
            }), 200
        except ValueError as ve:
            return jsonify({"ok": False, "error": str(ve)}), 400
        except Exception as e:
            return jsonify({"ok": False, "error": f"Failed to save settings: {str(e)}"}), 500

    def reset_simulation_clock(self):
        CLOCK.reset_simulation()
        return jsonify({
            "ok": True,
            "message": "Simulation clock reset to midnight.",
            "time": CLOCK.time_str(),
            "date": CLOCK.formatted_date()
        }), 200

