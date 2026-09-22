import json
from pathlib import Path
from typing import Optional
from utils.config import BASE_DIR, CONFIG

class ReportLog:
    """Helper to parse report output logs (JSON file or process stdout)."""
    def __init__(self, name: str, log_dir: Optional[Path] = None):
        self.name = name
        self.log_dir = log_dir or (BASE_DIR / "logs")
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

    def clean_slate(self):
        """Removes or truncates existing log files for this report before a fresh run."""
        exact_file = self.log_dir / f"{self.name}.json"
        pattern_files = list(self.log_dir.glob(f"{self.name}_*.json"))
        for f in [exact_file] + pattern_files:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                try:
                    with open(f, "w", encoding="utf-8") as h:
                        h.truncate(0)
                except Exception:
                    pass

    def has_valid_receipt(self) -> bool:
        """Returns True if a non-empty receipt exists on disk."""
        latest = self.find_latest_log_file()
        return bool(latest and latest.exists() and latest.stat().st_size > 0)

    DEPENDENCY_MARKERS = (
        "SKIPPED",
        "MISSING DEPENDENCY",
        "DEPENDENCY NOT READY",
        "DEPENDENCY NOT FOUND",
        "DATASET NOT FOUND",
        "TABLE NOT FOUND",
        "UPSTREAM NOT READY",
        "STATUS: RETRIAL",
    )

    @classmethod
    def is_dependency_skip(cls, status: str = "", text: str = "") -> bool:
        """Single canonical source of truth for dependency skip / retrial detection."""
        s = (status or "").upper()
        if s in ("SKIPPED", "RETRIAL"):
            return True
        t = (text or "").upper()
        return any(marker in t for marker in cls.DEPENDENCY_MARKERS)

    def parse_output(self, stdout_or_error: str) -> str:
        """Fallback log status parser from process stdout text."""
        if self.is_dependency_skip("", stdout_or_error):
            return "Skipped"
        txt = (stdout_or_error or "").upper()
        if "FAILED" in txt or "ERROR" in txt or "EXCEPTION" in txt:
            return "Failed"
        return "Completed"

    def from_json(self, default_stdout: str = "") -> "ReportLog":
        log_file = self.find_latest_log_file()
        if not log_file or (log_file.exists() and log_file.stat().st_size == 0):
            self.status = self.parse_output(default_stdout)
            self.last_output = default_stdout or "No log file written"
            return self

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_status = data.get("status")
                if raw_status:
                    self.status = "Skipped" if raw_status in ("Skipped", "Retrial") else raw_status
                else:
                    self.status = self.parse_output(default_stdout)
                self.last_run = data.get("last_run", "--")
                self.last_output = data.get("last_output", default_stdout)
                self.reason = data.get("reason", "") or data.get("log", "")
        except Exception:
            self.status = self.parse_output(default_stdout)
            self.last_output = default_stdout
        return self
