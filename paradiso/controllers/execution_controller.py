import json
from pathlib import Path
from flask import Flask, jsonify, request
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from services.automation_service import AutomationService
from utils.config import BASE_DIR

class ExecutionController:
    """REST API Controller for triggering executions, retrieving audit history & console logs."""
    def __init__(
        self,
        app: Flask,
        execution_service: ExecutionService,
        intraday_service: IntradayService,
        automation_service: AutomationService
    ):
        self.execution_service = execution_service
        self.intraday_service = intraday_service
        self.automation_service = automation_service
        self._register_routes(app)

    def _register_routes(self, app: Flask):
        app.add_url_rule("/api/automation/run", "run_automation", self.run_automation, methods=["POST"])
        app.add_url_rule("/api/executions/history", "get_execution_history", self.get_execution_history, methods=["GET"])
        app.add_url_rule("/api/executions/log/<name>", "get_execution_log", self.get_execution_log, methods=["GET"])

    def run_automation(self):
        return jsonify({
            "ok": False,
            "error": "Manual execution is disabled for intraday sequential reports. Paradiso manages execution automatically."
        }), 403

    def get_execution_history(self):
        history = self.intraday_service.get_all_execution_history()
        return jsonify({"ok": True, "history": history}), 200

    def get_execution_log(self, name: str):
        # Prevent directory traversal attacks
        if not name or ".." in name or "/" in name or "\\" in name:
            return jsonify({"ok": False, "error": "Invalid report name provided."}), 400

        logs_dir = (BASE_DIR / "logs").resolve()
        safe_name = Path(name).name
        if safe_name != name:
            return jsonify({"ok": False, "error": "Invalid report name provided."}), 400

        log_file = (logs_dir / f"{safe_name}.json").resolve()
        try:
            if not log_file.is_relative_to(logs_dir):
                return jsonify({"ok": False, "error": "Invalid report path."}), 400
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid report path."}), 400

        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    return jsonify({"ok": True, "name": safe_name, "log": content}), 200
            except Exception:
                pass

        # Fallback to report model output if no log file written yet
        rep = self.automation_service.get_by_name(safe_name)
        if rep:
            return jsonify({
                "ok": True,
                "name": safe_name,
                "log": {
                    "name": safe_name,
                    "status": rep.status,
                    "last_run": rep.started_at or "--",
                    "duration": rep.duration or "--",
                    "last_output": rep.last_output or "No log output recorded yet.",
                    "reason": rep.last_output or ""
                }
            }), 200

        return jsonify({"ok": False, "error": f"Log for '{safe_name}' not found"}), 404


