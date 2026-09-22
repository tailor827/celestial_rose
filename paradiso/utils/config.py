import os
import sys
import time
import copy
import shutil
import re
import yaml
import threading
from pathlib import Path
from typing import Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
_config_lock = threading.RLock()

def _deep_merge(target: dict, source: dict) -> dict:
    for k, v in source.items():
        if isinstance(v, dict) and k in target and isinstance(target[k], dict):
            _deep_merge(target[k], v)
        else:
            target[k] = v
    return target

def validate_config(cfg: dict) -> Tuple[bool, Optional[str]]:
    sched = cfg.get("scheduler", {})
    if "job_interval_seconds" in sched:
        try:
            val = float(sched["job_interval_seconds"])
            if val <= 0:
                return False, "scheduler.job_interval_seconds must be a positive number."
        except (ValueError, TypeError):
            return False, "scheduler.job_interval_seconds must be numeric."

    if "rotation_cooldown_seconds" in sched:
        try:
            val = float(sched["rotation_cooldown_seconds"])
            if val < 0:
                return False, "scheduler.rotation_cooldown_seconds must be a non-negative number."
        except (ValueError, TypeError):
            return False, "scheduler.rotation_cooldown_seconds must be numeric."

    time_regex = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    start_time = sched.get("intraday_start_time")
    idle_time = sched.get("intraday_idle_time")
    close_time = sched.get("intraday_close_time")

    for field_name, t_val in [
        ("intraday_start_time", start_time),
        ("intraday_idle_time", idle_time),
        ("intraday_close_time", close_time)
    ]:
        if t_val is not None and not (isinstance(t_val, str) and time_regex.match(t_val)):
            return False, f"scheduler.{field_name} must be in 24-hour HH:MM format (e.g., '07:00')."

    if start_time and idle_time and close_time:
        if not (start_time < idle_time <= close_time):
            return False, "Scheduler times must satisfy: intraday_start_time < intraday_idle_time <= intraday_close_time."

    log_cfg = cfg.get("logging", {})
    if "level" in log_cfg:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if str(log_cfg["level"]).upper() not in allowed:
            return False, f"logging.level must be one of: {', '.join(sorted(allowed))}."

    sim_cfg = cfg.get("simulation", {})
    if "speed_multiplier" in sim_cfg:
        try:
            val = float(sim_cfg["speed_multiplier"])
            if val <= 0:
                return False, "simulation.speed_multiplier must be a positive number."
        except (ValueError, TypeError):
            return False, "simulation.speed_multiplier must be numeric."

    exec_cfg = cfg.get("executables", {})
    if "python_path" in exec_cfg and exec_cfg["python_path"]:
        p_val = str(exec_cfg["python_path"]).strip()
        if p_val:
            p = Path(p_val)
            if not p.is_file():
                return False, f"executables.python_path '{p_val}' does not exist or is not a valid file."
            py_pattern = re.compile(r"^python(?:w)?(?:\d+(?:\.\d+)?)?(?:\.exe)?$", re.IGNORECASE)
            if not py_pattern.match(p.name):
                return False, f"executables.python_path '{p.name}' is not an authorized Python executable (must be python.exe, python3, etc.)."

    if "rscript_path" in exec_cfg and exec_cfg["rscript_path"]:
        r_val = str(exec_cfg["rscript_path"]).strip()
        if r_val:
            p = Path(r_val)
            if not p.is_file():
                return False, f"executables.rscript_path '{r_val}' does not exist or is not a valid file."
            r_pattern = re.compile(r"^rscript(?:\.exe)?$", re.IGNORECASE)
            if not r_pattern.match(p.name):
                return False, f"executables.rscript_path '{p.name}' is not an authorized Rscript executable (must be Rscript.exe or Rscript)."

    return True, None

def load_config(file_path: Optional[Path] = None) -> dict:
    with _config_lock:
        config_path = file_path or (BASE_DIR / "config.yaml")
        cfg = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

        # Corporate Environment Variable Overrides
        flask_cfg = cfg.setdefault("flask", {})
        if "PARADISO_HOST" in os.environ:
            flask_cfg["HOST"] = os.environ["PARADISO_HOST"]
        if "PARADISO_PORT" in os.environ:
            try:
                flask_cfg["PORT"] = int(os.environ["PARADISO_PORT"])
            except ValueError:
                pass
        if "PARADISO_SECRET_KEY" in os.environ:
            cfg["secret_key"] = os.environ["PARADISO_SECRET_KEY"]

        return cfg

def save_config(new_values: dict, file_path: Optional[Path] = None) -> dict:
    with _config_lock:
        config_path = file_path or (BASE_DIR / "config.yaml")
        current_raw = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                current_raw = yaml.safe_load(f) or {}

        incoming = copy.deepcopy(new_values)
        if incoming.get("secret_key") in (None, "", "••••••••"):
            incoming.pop("secret_key", None)

        merged = _deep_merge(copy.deepcopy(current_raw), incoming)

        valid, err = validate_config(merged)
        if not valid:
            raise ValueError(err)

        temp_path = config_path.with_name(f"{config_path.stem}_temp.yaml")
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, sort_keys=False, default_flow_style=False)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                os.replace(str(temp_path), str(config_path))
                break
            except (PermissionError, OSError) as e:
                if attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))
                else:
                    raise e

        CONFIG.clear()
        CONFIG.update(merged)

        return merged

def get_sanitized_config() -> dict:
    with _config_lock:
        sanitized = copy.deepcopy(CONFIG)
        if "secret_key" in sanitized:
            sanitized["secret_key"] = "••••••••"

        sanitized["runtime_meta"] = {
            "detected_python": sys.executable,
            "detected_rscript": shutil.which("Rscript") or "",
            "base_dir": str(BASE_DIR),
        }
        return sanitized

CONFIG = load_config()
