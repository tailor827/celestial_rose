from flask import Flask, jsonify
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

