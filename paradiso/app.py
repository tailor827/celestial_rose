import os
from flask import Flask, render_template
from waitress import serve

from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from services.paradiso import Paradiso

from controllers.automation_controller import AutomationController
from controllers.execution_controller import ExecutionController
from controllers.paradiso_controller import ParadisoController
from controllers.dashboard_controller import DashboardController
from controllers.settings_controller import SettingsController

from typing import Optional, Tuple
from utils.config import CONFIG

def create_app(auto_start: Optional[bool] = None) -> Tuple[Flask, Paradiso]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(base_dir, "web", "static"),
        template_folder=os.path.join(base_dir, "web", "templates")
    )
    app.config["SECRET_KEY"] = CONFIG.get("secret_key", "paradiso-alter-secret")

    # Shared Services Layer
    automation_service = AutomationService()
    execution_service = ExecutionService(automation_service)
    intraday_service = IntradayService(automation_service, execution_service)
    paradiso = Paradiso(intraday_service)

    # Controller Layer (Route Registrations)
    AutomationController(app, automation_service, intraday_service)
    ExecutionController(app, execution_service, intraday_service, automation_service)
    ParadisoController(app, paradiso)
    DashboardController(app, automation_service, intraday_service)
    SettingsController(app, intraday_service)

    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route("/")
    def index():
        return render_template("index.html")

    if auto_start is None:
        auto_start = CONFIG.get("scheduler", {}).get("auto_start", False)

    if auto_start:
        paradiso.start()

    return app, paradiso

app, paradiso = create_app()

if __name__ == "__main__":
    host = CONFIG.get("flask", {}).get("HOST", "0.0.0.0")
    port = CONFIG.get("flask", {}).get("PORT", 8080)

    if paradiso.is_running():
        print(f"[*] PARADISO ALTER framework running at http://localhost:{port} (Autonomous Mode: Active 24-hr cycle)")
    else:
        print(f"[*] PARADISO ALTER framework running at http://localhost:{port} (Standby Mode: Waiting for UI trigger)")

    serve(app, host=host, port=port)
