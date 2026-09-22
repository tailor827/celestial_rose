from flask import Flask, jsonify
from services.paradiso import Paradiso

class ParadisoController:
    """REST API Controller for managing the Paradiso daemon scheduler."""
    def __init__(self, app: Flask, paradiso: Paradiso):
        self.paradiso = paradiso
        self._register_routes(app)

    def _register_routes(self, app: Flask):
        app.add_url_rule("/api/paradiso/start", "paradiso_start", self.start, methods=["POST"])
        app.add_url_rule("/api/paradiso/stop", "paradiso_stop", self.stop, methods=["POST"])
        app.add_url_rule("/api/paradiso/status", "paradiso_status", self.status, methods=["GET"])

    def start(self):
        started = self.paradiso.start()
        if started:
            return jsonify({"ok": True, "message": "Paradiso scheduler started"}), 200
        return jsonify({"ok": False, "message": "Paradiso scheduler is already running"}), 200

    def stop(self):
        stopped = self.paradiso.stop()
        if stopped:
            return jsonify({"ok": True, "message": "Paradiso scheduler stopped"}), 200
        return jsonify({"ok": False, "message": "Paradiso scheduler was not running"}), 200

    def status(self):
        return jsonify({
            "ok": True,
            "running": self.paradiso.is_running()
        }), 200

