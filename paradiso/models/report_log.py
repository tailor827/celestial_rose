import os
import json
from pathlib import Path
from typing import Optional
from utils.config import BASE_DIR, CONFIG

class ReportLog:
    """Helper to parse report output logs (JSON file or process stdout)."""
    def __init__(self, name: str, log_dir: Optional[Path] = None):
        self.name = name
        if log_dir is not None:
            self.log_dir = Path(log_dir)
        elif "PARADISO_LOGS_DIR" in os.environ:
            self.log_dir = Path(os.environ["PARADISO_LOGS_DIR"])
        else:
            self.log_dir = BASE_DIR / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.status = "Completed"
        self.last_run = "--"
        self.last_output = ""
        self.reason = ""

    def _is_safe_name(self) -> bool:
        """Returns False if report name contains path traversal, separators, or unsafe glob/filesystem characters."""
        if not self.name or self.name in (".", "..") or ".." in self.name:
            return False
        unsafe_chars = set('/\\:*?"<>|[]')
        if any(ch in unsafe_chars or ord(ch) < 32 for ch in self.name):
            return False
        return True

    def _is_confined_path(self, candidate: Path) -> bool:
        """Verifies that a candidate path resolves strictly within self.log_dir."""
        try:
            base_resolved = self.log_dir.resolve()
            cand_resolved = candidate.resolve()
            return cand_resolved.parent == base_resolved
        except Exception:
            return False

    def find_latest_log_file(self) -> Optional[Path]:
        """Finds direct {name}.json or latest glob matching {name}_*.json file confined to self.log_dir."""
        if not self._is_safe_name():
            return None
        exact_file = self.log_dir / f"{self.name}.json"
        if self._is_confined_path(exact_file) and exact_file.exists():
            return exact_file

        try:
            pattern_files = sorted([
                p for p in self.log_dir.glob(f"{self.name}_*.json")
                if self._is_confined_path(p)
            ])
            if pattern_files:
                return pattern_files[-1]
        except Exception:
            pass

        return None

    def clean_slate(self):
        """Removes or truncates existing log files for this report before a fresh run (strictly confined to self.log_dir)."""
        if not self._is_safe_name():
            return
        exact_file = self.log_dir / f"{self.name}.json"
        candidates = []
        if self._is_confined_path(exact_file):
            candidates.append(exact_file)
        try:
            for p in self.log_dir.glob(f"{self.name}_*.json"):
                if self._is_confined_path(p):
                    candidates.append(p)
        except Exception:
            pass
        for f in candidates:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                try:
                    with open(f, "w", encoding="utf-8") as h:
                        h.truncate(0)
                except Exception:
                    pass

    def has_valid_receipt(self) -> bool:
        """Returns True if a non-empty, syntactically valid JSON receipt object exists on disk."""
        latest = self.find_latest_log_file()
        if not (latest and latest.exists() and latest.stat().st_size > 0):
            return False
        try:
            with open(latest, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data:
                return False
            return any(k in data for k in ("status", "last_output", "message", "reason", "log"))
        except Exception:
            return False

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
                if not isinstance(data, dict):
                    raise ValueError("Receipt payload is not a JSON object")
                raw_status = str(data.get("status") or "").strip()
                norm_status = raw_status.lower()
                if norm_status in ("completed", "complete", "success", "ok", "passed"):
                    self.status = "Completed"
                elif norm_status in ("skipped", "skip", "retrial", "retry", "waiting"):
                    self.status = "Skipped"
                elif norm_status in ("failed", "fail", "error", "errored"):
                    self.status = "Failed"
                elif raw_status:
                    self.status = raw_status
                else:
                    self.status = self.parse_output(default_stdout)
                self.last_run = data.get("last_run") or data.get("timestamp") or "--"
                self.last_output = data.get("last_output") or data.get("message") or default_stdout
                self.reason = data.get("reason", "") or data.get("log", "") or data.get("message", "")
        except Exception:
            self.status = self.parse_output(default_stdout)
            self.last_output = default_stdout
        return self
