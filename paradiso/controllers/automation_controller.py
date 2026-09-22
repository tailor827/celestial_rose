from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, request
from models.report import Report
from services.automation_service import AutomationService
from services.intraday_service import IntradayService

class AutomationController:
    """REST API Controller for automations CRUD operations."""
    def __init__(self, app: Flask, automation_service: AutomationService, intraday_service: Optional[IntradayService] = None):
        self.automation_service = automation_service
        self.intraday_service = intraday_service
        self._register_routes(app)

    def _register_routes(self, app: Flask):
        app.add_url_rule("/api/automations", "get_automations", self.get_automations, methods=["GET"])
        app.add_url_rule("/api/automations/reset", "reset_automations", self.reset_automations, methods=["POST"])
        app.add_url_rule("/api/automation/add", "add_automation", self.add_automation, methods=["POST"])
        app.add_url_rule("/api/automation/delete/<string:name>", "delete_automation", self.delete_automation, methods=["DELETE"])
        app.add_url_rule("/api/automation/disable", "disable_automation", self.disable_automation, methods=["POST"])

    def reset_automations(self):
        if self.intraday_service:
            self.intraday_service.reset_all_reports()
        else:
            self.automation_service.set_waiting_all()
        return jsonify({"ok": True, "message": "All reports reset to Waiting"}), 200

    def get_automations(self):
        reports = self.automation_service.get_all(serialized=True)
        return jsonify({"ok": True, "automations": reports}), 200

    def add_automation(self):
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "").strip()
        filename = str(data.get("filename") or "").strip()
        if not name or not filename:
            return jsonify({"ok": False, "error": "Name and filename are required"}), 400

        # Validate filename against path traversal and separators
        if "/" in filename or "\\" in filename or ".." in filename or Path(filename).is_absolute():
            return jsonify({"ok": False, "error": "Invalid filename: must be a plain filename without directory separators or traversal characters."}), 400

        filetype = str(data.get("filetype") or "python").strip().lower()
        if filetype not in ["python", "r"]:
            return jsonify({"ok": False, "error": "Invalid filetype: must be 'python' or 'r'."}), 400

        if filetype == "python" and not filename.endswith(".py"):
            return jsonify({"ok": False, "error": "Invalid filename: Python report filename must end with .py"}), 400

        if filetype == "r" and not (filename.endswith(".r") or filename.endswith(".R")):
            return jsonify({"ok": False, "error": "Invalid filename: R report filename must end with .r or .R"}), 400

        # Whitelist permitted directories (Python vs R hygiene)
        raw_dir = str(data.get("dir") or ("../reports/python" if filetype == "python" else "../reports/r")).strip()
        ALLOWED_DIRS = {"../reports", "../reports/python", "../reports/r", "reports", "reports/python", "reports/r"}
        if raw_dir not in ALLOWED_DIRS:
            return jsonify({"ok": False, "error": f"Invalid directory '{raw_dir}': must be an authorized reports directory (e.g. '../reports', '../reports/python', '../reports/r')."}), 400

        if self.automation_service.get_by_name(name):
            return jsonify({"ok": False, "error": f"Report '{name}' already exists"}), 409

        initial_status = str(data.get("status") or "Waiting").strip()
        if initial_status not in ["Waiting", "Inactive", "Disabled"]:
            initial_status = "Waiting"

        report = Report(
            name=name,
            filename=filename,
            filetype=filetype,
            dir=raw_dir,
            team=str(data.get("team") or "General").strip(),
            owner=str(data.get("owner") or "User").strip(),
            scheduled_time=str(data.get("scheduled_time") or "08:30").strip(),
            status=initial_status
        )
        self.automation_service.add(report)

        if self.intraday_service and self.intraday_service.is_active and initial_status == "Waiting":
            with self.intraday_service._lock:
                if name not in self.intraday_service.waitlist and name not in self.intraday_service.current_runs:
                    self.intraday_service.waitlist.append(name)

        return jsonify({"ok": True, "message": f"Report '{name}' created successfully", "report": report.to_dict()}), 201

    def delete_automation(self, name: str):
        name = name.strip()
        if not self.automation_service.get_by_name(name):
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404

        if self.intraday_service and self.intraday_service.is_active:
            return jsonify({
                "ok": False,
                "error": f"Cannot delete '{name}': catalog is locked while intraday scheduler is active. Stop the scheduler to delete reports."
            }), 409

        if self.intraday_service:
            with self.intraday_service._lock:
                if name in self.intraday_service.waitlist:
                    self.intraday_service.waitlist.remove(name)
                self.intraday_service.current_runs.pop(name, None)
                self.intraday_service.retry_counts.pop(name, None)

        self.automation_service.delete(name)
        return jsonify({"ok": True, "message": f"Report '{name}' deleted successfully"}), 200

    def disable_automation(self):
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        if not name:
            return jsonify({"ok": False, "error": "Missing name parameter"}), 400

        success = self.automation_service.disable(name)
        if not success:
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404
        return jsonify({"ok": True, "message": f"Report '{name}' disabled"}), 200
