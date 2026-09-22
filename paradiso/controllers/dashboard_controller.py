from flask import Flask, jsonify
from services.automation_service import AutomationService
from services.intraday_service import IntradayService
from utils.clock import CLOCK

class DashboardController:
    """REST API Controller providing stats and timeline aggregations for the target dashboard UI."""
    def __init__(self, app: Flask, automation_service: AutomationService, intraday_service: IntradayService):
        self.automation_service = automation_service
        self.intraday_service = intraday_service
        self._register_routes(app)

    def _register_routes(self, app: Flask):
        app.add_url_rule("/api/dashboard/stats", "dashboard_stats", self.get_stats, methods=["GET"])
        app.add_url_rule("/api/dashboard/timeline", "dashboard_timeline", self.get_timeline, methods=["GET"])
        app.add_url_rule("/api/dashboard/system-status", "dashboard_system_status", self.get_system_status, methods=["GET"])

    def get_stats(self):
        reports = self.automation_service.get_all(serialized=False)
        total = len(reports)
        completed = sum(1 for r in reports if r.status == "Completed")
        running = sum(1 for r in reports if r.status == "Running")
        retrial = sum(1 for r in reports if r.status == "Retrial")
        waiting = sum(1 for r in reports if r.status == "Waiting")
        failed = sum(1 for r in reports if r.status == "Failed")

        success_rate = round((completed / total * 100)) if total > 0 else 0
        running_rate = round((running / total * 100)) if total > 0 else 0
        retrial_rate = round((retrial / total * 100)) if total > 0 else 0
        waiting_rate = round((waiting / total * 100)) if total > 0 else 0
        failure_rate = round((failed / total * 100)) if total > 0 else 0

        # Find next scheduled waiting or retrial report
        pending_reports = [r for r in reports if r.status in ["Waiting", "Retrial"]]
        next_scheduled = None
        if pending_reports:
            r = pending_reports[0]
            next_scheduled = {
                "name": r.name,
                "team": r.team,
                "scheduled_time": r.scheduled_time,
                "countdown": "32 min"
            }
        if not CLOCK.simulation_mode or CLOCK.speed_multiplier <= 1.0:
            sim_speed_str = "Realtime"
        elif CLOCK.speed_multiplier == 600.0:
            sim_speed_str = "10m/s"
        elif CLOCK.speed_multiplier == 300.0:
            sim_speed_str = "5m/s"
        elif CLOCK.speed_multiplier == 60.0:
            sim_speed_str = "1m/s"
        elif CLOCK.speed_multiplier == 10.0:
            sim_speed_str = "10s/s"
        else:
            sim_speed_str = f"{int(CLOCK.speed_multiplier)}x"

        return jsonify({
            "ok": True,
            "metrics": {
                "total": total,
                "completed": completed,
                "running": running,
                "retrial": retrial,
                "waiting": waiting,
                "failed": failed,
                "rates": {
                    "success": f"{success_rate}%",
                    "running": f"{running_rate}%",
                    "retrial": f"{retrial_rate}%",
                    "waiting": f"{waiting_rate}%",
                    "failure": f"{failure_rate}%"
                }
            },
            "next_scheduled": next_scheduled,
            "intraday_status": self.intraday_service.resolve_status(),
            "time": CLOCK.time_str(),
            "date": CLOCK.formatted_date(),
            "sim_speed": sim_speed_str,
            "sim_mode": CLOCK.simulation_mode
        }), 200

    def get_timeline(self):
        timeline = self.intraday_service.get_today_timeline()
        return jsonify({"ok": True, "timeline": timeline}), 200

    def get_system_status(self):
        return jsonify({
            "ok": True,
            "status": "All Systems Operational",
            "last_checked": CLOCK.time_str(),
            "services": {
                "scheduler": True,
                "execution_service": True,
                "file_storage": True,
                "notifications": True
            }
        }), 200

