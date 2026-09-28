from flask import Flask, jsonify, request
from services.paradiso import Paradiso

class ParadisoController:
    """REST API Controller for managing the Paradiso daemon scheduler."""
    def __init__(self, app: Flask, paradiso: Paradiso):
        self.app = app
        self.paradiso = paradiso
        self._register_routes(app)

    def _register_routes(self, app: Flask):
        app.add_url_rule("/api/paradiso/start", "paradiso_start", self.start, methods=["POST"])
        app.add_url_rule("/api/paradiso/stop", "paradiso_stop", self.stop, methods=["POST"])
        app.add_url_rule("/api/paradiso/status", "paradiso_status", self.status, methods=["GET"])
        app.add_url_rule("/api/paradiso/lane/start", "paradiso_lane_start", self.lane_start, methods=["POST"])
        app.add_url_rule("/api/paradiso/lane/stop", "paradiso_lane_stop", self.lane_stop, methods=["POST"])
        app.add_url_rule("/api/paradiso/lanes/status", "paradiso_lanes_status", self.lanes_status, methods=["GET"])

    def _is_cooldown_enforced(self) -> bool:
        if self.app.config.get("TESTING") and not getattr(self.paradiso, "_enforce_cooldown", False):
            return False
        return True

    def start(self):
        res = self.paradiso.start(check_cooldown=self._is_cooldown_enforced())
        if res.status == "cooldown":
            return jsonify({
                "ok": False,
                "error": f"Scheduler transition cooldown active. Please wait {int(res.remaining) + 1}s before toggling again.",
                "cooldown_remaining": res.remaining
            }), 429
        if res.status == "already_running":
            return jsonify({"ok": False, "message": "Paradiso scheduler is already running"}), 200
        return jsonify({"ok": True, "message": "Paradiso scheduler started"}), 200

    def stop(self):
        res = self.paradiso.stop(check_cooldown=self._is_cooldown_enforced())
        if res.status == "cooldown":
            return jsonify({
                "ok": False,
                "error": f"Scheduler transition cooldown active. Please wait {int(res.remaining) + 1}s before toggling again.",
                "cooldown_remaining": res.remaining
            }), 429
        if res.status == "not_running":
            return jsonify({"ok": False, "message": "Paradiso scheduler was not running"}), 200
        return jsonify({"ok": True, "message": "Paradiso scheduler stopped"}), 200

    def status(self):
        return jsonify({
            "ok": True,
            "running": self.paradiso.is_running(),
            "cooldown_remaining": self.paradiso.get_cooldown_remaining()
        }), 200

    VALID_LANES = {"type_a", "type_b", "type_c"}

    def lane_start(self):
        data = request.get_json(silent=True) or {}
        raw_lane = data.get("lane")
        if not raw_lane or str(raw_lane).strip().lower() not in self.VALID_LANES:
            return jsonify({
                "ok": False,
                "error": f"Invalid lane '{raw_lane}'. Must be one of: 'type_a', 'type_b', 'type_c'"
            }), 400
        lane = str(raw_lane).strip().lower()
        force_open = bool(data.get("force_open", False))

        status = self.paradiso.intraday_service.resolve_status()
        if status != "OPEN" and not force_open:
            return jsonify({
                "ok": False,
                "lane": lane,
                "error": f"Lane start is blocked outside the intraday open window (07:00 - 21:00). Current status: {status}."
            }), 409

        res = self.paradiso.start_lane(lane, force_open=force_open, check_cooldown=self._is_cooldown_enforced())
        if res.status == "cooldown":
            return jsonify({
                "ok": False,
                "lane": lane,
                "error": f"Lane transition cooldown active. Please wait {int(res.remaining) + 1}s before toggling again.",
                "cooldown_remaining": res.remaining
            }), 429
        if res.status == "already_running":
            return jsonify({"ok": False, "lane": lane, "message": f"Lane '{lane}' is already running"}), 200
        return jsonify({"ok": True, "lane": lane, "message": f"Lane '{lane}' started"}), 200

    def lane_stop(self):
        data = request.get_json(silent=True) or {}
        raw_lane = data.get("lane")
        if not raw_lane or str(raw_lane).strip().lower() not in self.VALID_LANES:
            return jsonify({
                "ok": False,
                "error": f"Invalid lane '{raw_lane}'. Must be one of: 'type_a', 'type_b', 'type_c'"
            }), 400
        lane = str(raw_lane).strip().lower()
        res = self.paradiso.stop_lane(lane, check_cooldown=self._is_cooldown_enforced())
        if res.status == "cooldown":
            return jsonify({
                "ok": False,
                "lane": lane,
                "error": f"Lane transition cooldown active. Please wait {int(res.remaining) + 1}s before toggling again.",
                "cooldown_remaining": res.remaining
            }), 429
        if res.status == "not_running":
            return jsonify({"ok": False, "lane": lane, "message": f"Lane '{lane}' was not running"}), 200
        return jsonify({"ok": True, "lane": lane, "message": f"Lane '{lane}' stopped"}), 200

    def lanes_status(self):
        lanes_info = self.paradiso.intraday_service.get_lanes_status()
        for lane_key in ["type_a", "type_b", "type_c"]:
            lanes_info[lane_key]["cooldown_remaining"] = self.paradiso.get_lane_cooldown_remaining(lane_key)
            lanes_info[lane_key]["running"] = self.paradiso.is_lane_running(lane_key)
        return jsonify({
            "ok": True,
            "running": self.paradiso.is_running(),
            "lanes": lanes_info
        }), 200

