import json
from pathlib import Path
from typing import Optional
from utils.config import BASE_DIR, CONFIG

class ReportLog:
    """Helper to parse report output logs (JSON file or process stdout)."""
    def __init__(self, name: str, log_dir: Optional[Path] = None):
        self.name = name
        configured_dir = CONFIG.get("logging", {}).get("dir", "logs")
        self.log_dir = log_dir or (BASE_DIR / configured_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.status = "Completed"
        self.last_run = "--"
        self.last_output = ""
        self.reason = ""

    def find_latest_log_file(self) -> Optional[Path]:
        """Finds direct {name}.json or latest glob matching {name}_*.json file."""
        exact_file = self.log_dir / f"{self.name}.json"
        if exact_file.exists():
            return exact_file

        pattern_files = sorted(list(self.log_dir.glob(f"{self.name}_*.json")))
        if pattern_files:
            return pattern_files[-1]

        return None

    def parse_output(self, stdout_or_error: str) -> str:
        """Fallback log status parser from process stdout text."""
        txt = (stdout_or_error or "").upper()
        if "SKIPPED" in txt or "MISSING DEPENDENCY" in txt or "DEPENDENCY NOT READY" in txt or "NOT FOUND" in txt:
            return "Skipped"
        elif "FAILED" in txt or "ERROR" in txt or "EXCEPTION" in txt:
            return "Failed"
        return "Completed"

    def from_json(self, default_stdout: str = "") -> "ReportLog":
        log_file = self.find_latest_log_file()
        if not log_file:
            self.status = self.parse_output(default_stdout)
            self.last_output = default_stdout or "No log file written"
            return self

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.status = data.get("status", self.parse_output(default_stdout))
                self.last_run = data.get("last_run", "--")
                self.last_output = data.get("last_output", default_stdout)
                self.reason = data.get("reason", "") or data.get("log", "")
        except Exception:
            self.status = self.parse_output(default_stdout)
            self.last_output = default_stdout
        return self
