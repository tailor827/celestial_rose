import re
from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, request
from models.report import Report
from services.automation_service import AutomationService
from services.intraday_service import IntradayService
from utils.clock import CLOCK

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
        app.add_url_rule("/api/automation/enable", "enable_automation", self.enable_automation, methods=["POST"])

    def reset_automations(self):
        if self.intraday_service:
            self.intraday_service.reset_all_reports()
        else:
            self.automation_service.set_waiting_all()
        return jsonify({"ok": True, "message": "All reports reset to Waiting"}), 200

    def get_automations(self):
        reports = self.automation_service.get_all(serialized=True)
        if self.intraday_service:
            max_retries = self.intraday_service.max_retries
            for rep in reports:
                name = rep.get("name", "")
                rep["retry_count"] = self.intraday_service.retry_counts.get(name, 0)
                rep["max_retries"] = max_retries
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

        existing_reports = self.automation_service.get_all()
        for er in existing_reports:
            if er.name.lower() == name.lower():
                return jsonify({"ok": False, "error": f"Report '{name}' already exists in lane '{er.report_type}'. Reports must be distinct across all lanes."}), 409

        initial_status = str(data.get("status") or "Waiting").strip()
        if initial_status not in ["Waiting", "Inactive", "Disabled"]:
            initial_status = "Waiting"

        report_type = str(data.get("report_type") or data.get("type") or "type_a").strip().lower()
        if report_type not in ["type_a", "type_b", "type_c"]:
            return jsonify({"ok": False, "error": "Invalid report_type: must be strictly 'type_a', 'type_b', or 'type_c'."}), 400

        raw_interval = data.get("interval_minutes")
        if raw_interval is None:
            interval_minutes = 30
        else:
            try:
                interval_minutes = int(raw_interval)
                if interval_minutes < 1:
                    return jsonify({"ok": False, "error": "interval_minutes must be an integer >= 1."}), 400
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "interval_minutes must be a valid integer."}), 400

        timeslot_tier = str(data.get("timeslot_tier") or "CUSTOM").strip().upper()
        if timeslot_tier not in ["BOD", "MID", "EOD", "CUSTOM"]:
            timeslot_tier = "CUSTOM"

        scheduled_time = str(data.get("scheduled_time") or "08:30").strip()
        time_regex = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
        if not time_regex.match(scheduled_time):
            return jsonify({
                "ok": False,
                "error": f"Invalid scheduled_time '{scheduled_time}': must be in canonical 24-hour HH:MM format (00:00 - 23:59)."
            }), 400

        catch_up_policy = data.get("catch_up_policy")
        if catch_up_policy is not None:
            catch_up_policy = str(catch_up_policy).strip().upper()
            if not catch_up_policy:
                catch_up_policy = None
            elif catch_up_policy not in ["CATCH_UP_IMMEDIATE", "SKIP_UNTIL_NEXT_DAY", "WARN_OPERATOR"]:
                return jsonify({
                    "ok": False,
                    "error": f"Invalid catch_up_policy '{catch_up_policy}': must be one of CATCH_UP_IMMEDIATE, SKIP_UNTIL_NEXT_DAY, WARN_OPERATOR."
                }), 400

        raw_priority = str(data.get("priority") or "P2").strip().upper()
        if raw_priority not in ["P0", "P1", "P2"]:
            return jsonify({
                "ok": False,
                "error": f"Invalid priority '{raw_priority}': must be one of 'P0' (Critical), 'P1' (High), or 'P2' (Normal)."
            }), 400

        report = Report(
            name=name,
            filename=filename,
            filetype=filetype,
            dir=raw_dir,
            team=str(data.get("team") or "General").strip(),
            owner=str(data.get("owner") or "User").strip(),
            scheduled_time=scheduled_time,
            status=initial_status,
            report_type=report_type,
            interval_minutes=interval_minutes,
            timeslot_tier=timeslot_tier,
            catch_up_policy=catch_up_policy,
            priority=raw_priority
        )
        self.automation_service.add(report)

        lane_a_active = bool(self.intraday_service.lane_a_active) if self.intraday_service else False
        if self.intraday_service and lane_a_active and initial_status == "Waiting" and report_type == "type_a":
            with self.intraday_service._lock:
                if name not in self.intraday_service.waitlist and name not in self.intraday_service.current_runs:
                    self.intraday_service._enqueue_lane_a_by_priority(name)
                    self.intraday_service._rotation_cooldown_until = 0.0
                    self.intraday_service._cycle_pass_reports.add(name)

        return jsonify({"ok": True, "message": f"Report '{name}' created successfully", "report": report.to_dict()}), 201

    def delete_automation(self, name: str):
        name = name.strip()
        report = self.automation_service.get_by_name(name)
        if not report:
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404

        if self.intraday_service:
            if self.intraday_service.is_active:
                return jsonify({
                    "ok": False,
                    "error": f"Cannot delete '{name}': catalog is locked while intraday scheduler is active. Stop the scheduler to delete reports."
                }), 409

            with self.intraday_service._lock:
                is_running = (
                    name in self.intraday_service.current_runs
                    or name in self.intraday_service.active_runs_type_b
                    or name in self.intraday_service.active_runs_type_c
                    or report.status == "Running"
                )
                if is_running:
                    return jsonify({
                        "ok": False,
                        "error": f"Cannot delete '{name}': report is currently executing."
                    }), 409

                if name in self.intraday_service.waitlist:
                    self.intraday_service.waitlist.remove(name)
                self.intraday_service.current_runs.pop(name, None)
                self.intraday_service.active_runs_type_b.pop(name, None)
                self.intraday_service.active_runs_type_c.pop(name, None)
                self.intraday_service.retry_counts.pop(name, None)
                self.intraday_service.type_c_ran_today.discard(name)
                self.intraday_service.type_c_retry_after.pop(name, None)
                self.intraday_service.type_c_warned.discard(name)
                self.intraday_service.type_b_exhausted.discard(name)
                self.intraday_service.type_b_last_run.pop(name, None)
                self.intraday_service._cycle_pass_reports.discard(name)
                self.intraday_service._cycle_seen_in_pass.discard(name)
                self.intraday_service._last_rotation_logged.pop(name, None)

                today_date = CLOCK.date_str()
                self.intraday_service.intraday_repo.purge_report_from_day(today_date, name)
                self.intraday_service._evaluate_pass_completion(today_date)

        self.automation_service.delete(name)
        return jsonify({"ok": True, "message": f"Report '{name}' deleted successfully"}), 200

    def disable_automation(self):
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Missing name parameter"}), 400

        report = self.automation_service.get_by_name(name)
        if not report:
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404

        # Enforce idle-only disabling: users cannot disable currently running reports
        if self.intraday_service:
            with self.intraday_service._lock:
                is_running = (
                    name in self.intraday_service.current_runs
                    or name in self.intraday_service.active_runs_type_b
                    or name in self.intraday_service.active_runs_type_c
                    or report.status == "Running"
                )
                if is_running:
                    return jsonify({
                        "ok": False,
                        "error": f"Cannot disable '{name}': report is currently executing. Wait for the run to finish or stop the lane."
                    }), 409

                # Report is idle: evict from queue and pass tracking
                if name in self.intraday_service.waitlist:
                    self.intraday_service.waitlist.remove(name)
                self.intraday_service._cycle_pass_reports.discard(name)
                self.intraday_service._cycle_seen_in_pass.discard(name)
                self.intraday_service.retry_counts.pop(name, None)
                self.intraday_service.type_c_retry_after.pop(name, None)
                self.intraday_service._evaluate_pass_completion(CLOCK.date_str(), defer_seen_clear=True)
        elif report.status == "Running":
            return jsonify({
                "ok": False,
                "error": f"Cannot disable '{name}': report is currently executing."
            }), 409

        success = self.automation_service.disable(name)
        if not success:
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404

        if self.intraday_service:
            today_date = CLOCK.date_str()
            self.intraday_service.intraday_repo.add_timeline_event(
                date=today_date,
                title=f"Disabled {name}",
                description="Report disabled and evicted from execution queue",
                event_type="system"
            )

        return jsonify({"ok": True, "message": f"Report '{name}' disabled"}), 200

    def enable_automation(self):
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Report name is required"}), 400

        report = self.automation_service.get_by_name(name)
        if not report:
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404

        if report.status not in ("Disabled", "Failed"):
            return jsonify({"ok": False, "error": f"Report '{name}' is not disabled or failed (current status: {report.status})"}), 400

        success = self.automation_service.enable(name)
        if not success:
            return jsonify({"ok": False, "error": f"Report '{name}' not found"}), 404

        if self.intraday_service:
            with self.intraday_service._lock:
                today_date = CLOCK.date_str()
                self.intraday_service.type_b_exhausted.discard(name)
                self.intraday_service.type_c_ran_today.discard(name)
                self.intraday_service.type_c_retry_after.pop(name, None)
                self.intraday_service.type_c_warned.discard(name)
                self.intraday_service.retry_counts.pop(name, None)
                self.intraday_service.intraday_repo.clear_non_completed_run(today_date, name)
                if report.report_type == "type_a" and self.intraday_service.lane_a_active:
                    day = self.intraday_service.intraday_repo.get_day(today_date)
                    already_ran = self.intraday_service._get_completed_or_exhausted_reports(day) if day else set()
                    if name not in already_ran and name not in self.intraday_service.waitlist and name not in self.intraday_service.current_runs:
                        self.intraday_service._enqueue_lane_a_by_priority(name)
                        self.intraday_service.all_completed = False
                        self.intraday_service._rotation_cooldown_until = 0.0
                        self.intraday_service._cycle_pass_reports.add(name)

                self.intraday_service.intraday_repo.add_timeline_event(
                    date=today_date,
                    title=f"Enabled {name}",
                    description="Report re-enabled and restored to catalog",
                    event_type="system"
                )

        return jsonify({"ok": True, "message": f"Report '{name}' enabled"}), 200

