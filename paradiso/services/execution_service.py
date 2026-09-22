from pathlib import Path
from typing import Callable, Optional
from services.automation_service import AutomationService
from services.runner import Runner
from utils.config import BASE_DIR
from utils.clock import CLOCK

class ExecutionService:
    """Orchestrates process runner with automation service status updates."""
    def __init__(self, automation_service: AutomationService, runner: Optional[Runner] = None):
        self.automation_service = automation_service
        self.runner = runner or Runner()

    def execute_report(
        self,
        name: str,
        callback_good: Optional[Callable] = None,
        callback_fail: Optional[Callable] = None
    ) -> bool:
        report = self.automation_service.get_by_name(name)
        if not report:
            if callback_fail:
                callback_fail(name, "0s", f"Report '{name}' not found in catalog")
            return False

        script_dir = BASE_DIR / report.dir
        script_path = script_dir / report.filename

        started_at = CLOCK.time_str()
        self.automation_service.update_status(
            name=name,
            status="Running",
            started_at=started_at,
            last_output="Executing script..."
        )

        import json

        def _write_log(status_str: str, duration_str: str, log_output: str):
            try:
                logs_dir = BASE_DIR / "logs"
                logs_dir.mkdir(exist_ok=True)
                log_file = logs_dir / f"{name}.json"
                log_data = {
                    "name": name,
                    "status": status_str,
                    "last_run": CLOCK.formatted_now(),
                    "duration": duration_str,
                    "last_output": log_output,
                    "reason": log_output
                }
                with open(log_file, "w", encoding="utf-8") as f:
                    json.dump(log_data, f, indent=2)
            except Exception:
                pass

        def _on_good(duration_str: str, output: str):
            from models.report_log import ReportLog
            parsed_status = ReportLog(name).parse_output(output)
            is_skipped = (parsed_status == "Skipped") or ("SKIPPED" in output.upper())

            if is_skipped:
                log_status = "Skipped"
                auto_status = "Retrial"
            else:
                log_status = "Completed"
                auto_status = "Completed"

            _write_log(log_status, duration_str, output)
            self.automation_service.update_status(
                name=name,
                status=auto_status,
                duration=duration_str,
                last_output=output
            )
            if callback_good:
                callback_good(name, duration_str, output)

        def _on_fail(duration_str: str, error: str):
            _write_log("Failed", duration_str, error)
            self.automation_service.update_status(
                name=name,
                status="Failed",
                duration=duration_str,
                last_output=error
            )
            if callback_fail:
                callback_fail(name, duration_str, error)

        # Security: ensure resolved script_path remains strictly within project workspace
        project_root = BASE_DIR.parent.resolve()
        try:
            resolved_script = script_path.resolve()
            is_authorized = resolved_script.is_relative_to(project_root)
        except Exception:
            is_authorized = False

        if not is_authorized:
            error_msg = f"Security violation: script '{script_path}' resolves outside project directory"
            import threading
            threading.Thread(target=lambda: _on_fail("0s", error_msg), daemon=True).start()
            return False

        # Immediate failure if script file doesn't physically exist on disk
        if not script_path.exists():
            error_msg = f"Report script not found on disk: {script_path}"
            import threading
            threading.Thread(target=lambda: _on_fail("0s", error_msg), daemon=True).start()
            return False

        if report.filetype.lower() == "r":
            self.runner.run_r(script_path, callback_good=_on_good, callback_fail=_on_fail, name=name)
        else:
            self.runner.run_python(script_path, callback_good=_on_good, callback_fail=_on_fail, name=name)

        return True

