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
        from models.report_log import ReportLog

        report_logger = ReportLog(name)
        log_file = report_logger.log_dir / f"{name}.json"

        # Clean slate: remove or truncate previous receipts before launching
        report_logger.clean_slate()

        def _write_fallback_log(status_str: str, duration_str: str, log_output: str):
            try:
                report_logger.log_dir.mkdir(parents=True, exist_ok=True)
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
            has_receipt = report_logger.has_valid_receipt()
            if has_receipt:
                script_log = ReportLog(name).from_json(default_stdout=output)
                # If script explicitly recorded a fatal Failed status despite exit 0:
                if script_log.status == "Failed":
                    auto_status = "Failed"
                    last_out = script_log.last_output or "Script dumped Failed status"
                    self.automation_service.update_status(name=name, status=auto_status, duration=duration_str, last_output=last_out)
                    if callback_fail:
                        callback_fail(name, duration_str, last_out)
                    return

                auto_status = "Retrial" if ReportLog.is_dependency_skip(script_log.status, script_log.last_output) else "Completed"
                last_out = script_log.last_output or output
                self.automation_service.update_status(name=name, status=auto_status, duration=duration_str, last_output=last_out)
                if callback_good:
                    callback_good(name, duration_str, output)
            else:
                # No receipt written: check if stdout has explicit skip marker
                if ReportLog.is_dependency_skip("", output):
                    auto_status = "Retrial"
                    _write_fallback_log("Skipped", duration_str, output)
                    last_out = output
                    self.automation_service.update_status(name=name, status=auto_status, duration=duration_str, last_output=last_out)
                    if callback_good:
                        callback_good(name, duration_str, output)
                else:
                    # CONTRACT VIOLATION: Exited 0 without writing required receipt file!
                    auto_status = "Failed"
                    err_msg = f"Contract violation: Script '{name}' exited 0 without writing receipt to logs/{name}.json"
                    _write_fallback_log("Failed", duration_str, err_msg)
                    last_out = err_msg
                    self.automation_service.update_status(name=name, status=auto_status, duration=duration_str, last_output=last_out)
                    if callback_fail:
                        callback_fail(name, duration_str, err_msg)

        def _on_fail(duration_str: str, error: str):
            has_receipt = report_logger.has_valid_receipt()
            if has_receipt:
                script_log = ReportLog(name).from_json(default_stdout=error)
                auto_status = "Retrial" if ReportLog.is_dependency_skip(script_log.status, script_log.last_output or error) else "Failed"
                last_out = script_log.last_output or error
            else:
                if ReportLog.is_dependency_skip("", error):
                    auto_status = "Retrial"
                    _write_fallback_log("Skipped", duration_str, error)
                else:
                    auto_status = "Failed"
                    _write_fallback_log("Failed", duration_str, error)
                last_out = error

            self.automation_service.update_status(name=name, status=auto_status, duration=duration_str, last_output=last_out)
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
            _on_fail("0s", error_msg)
            return False

        # Immediate failure if script file doesn't physically exist on disk
        if not script_path.exists():
            error_msg = f"Report script not found on disk: {script_path}"
            _on_fail("0s", error_msg)
            return False

        if report.filetype.lower() == "r":
            self.runner.run_r(script_path, callback_good=_on_good, callback_fail=_on_fail, name=name)
        else:
            self.runner.run_python(script_path, callback_good=_on_good, callback_fail=_on_fail, name=name)

        return True

