import os
import sys
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Dict, List, Any
from utils.config import BASE_DIR, CONFIG

class Runner:
    """Process execution engine with duration tracking and active process management."""
    def __init__(self):
        self.python_exe = self._resolve_python()
        self.rscript_exe = self._resolve_rscript()
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.killed_processes: set[str] = set()
        self.killed_process_ids: set[int] = set()
        self._proc_lock = threading.RLock()

    def _resolve_python(self) -> Path:
        configured = CONFIG.get("executables", {}).get("python_path")
        if configured:
            p = Path(configured)
            py_pattern = re.compile(r"^python(?:w)?(?:\d+(?:\.\d+)?)?(?:\.exe)?$", re.IGNORECASE)
            if p.is_file() and py_pattern.match(p.name):
                return p
        return Path(sys.executable)

    def _resolve_rscript(self) -> Optional[Path]:
        configured = CONFIG.get("executables", {}).get("rscript_path")
        if configured:
            p = Path(configured)
            r_pattern = re.compile(r"^rscript(?:\.exe)?$", re.IGNORECASE)
            if p.is_file() and r_pattern.match(p.name):
                return p
        found = shutil.which("Rscript") or shutil.which("rscript")
        return Path(found) if found else None

    def _format_duration(self, seconds: float) -> str:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        if mins > 0:
            return f"{mins}m {secs:02d}s"
        return f"{secs}s"

    def kill_all(self):
        """Terminates all currently running child subprocesses immediately."""
        with self._proc_lock:
            for name, process in list(self.active_processes.items()):
                self.killed_processes.add(name)
                self.killed_process_ids.add(id(process))
                try:
                    process.terminate()
                    process.kill()
                except Exception:
                    pass
            self.active_processes.clear()

    def _watcher(self, name: str, process: subprocess.Popen, start_time: float, callback_good: Callable, callback_fail: Callable):
        stdout, stderr = process.communicate()
        with self._proc_lock:
            # Only remove from active_processes if this exact process instance is still the registered one
            if self.active_processes.get(name) is process:
                self.active_processes.pop(name, None)
            
            was_killed = id(process) in self.killed_process_ids or (name in self.killed_processes and self.active_processes.get(name) is not process)
            self.killed_process_ids.discard(id(process))
            if name in self.killed_processes and not any(id(p) in self.killed_process_ids for p in self.active_processes.values()):
                self.killed_processes.discard(name)

        if was_killed:
            # Process was intentionally killed by system stop/reset — do NOT trigger fail callback!
            return

        elapsed = time.time() - start_time
        duration_str = self._format_duration(elapsed)
        output_parts = [p.strip() for p in (stdout, stderr) if p and p.strip()]
        output_snippet = "\n".join(output_parts) if output_parts else "No output"

        if process.returncode == 0:
            callback_good(duration_str, output_snippet)
        else:
            callback_fail(duration_str, f"Return code {process.returncode}: {output_snippet}")

    def run_python(self, script_path: Path, callback_good: Callable, callback_fail: Callable, name: str = "report"):
        try:
            start_time = time.time()
            process = subprocess.Popen(
                [str(self.python_exe), str(script_path)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            with self._proc_lock:
                self.active_processes[name] = process

            threading.Thread(
                target=self._watcher,
                args=(name, process, start_time, callback_good, callback_fail),
                daemon=True
            ).start()
        except Exception as e:
            callback_fail("0s", f"Failed to launch Python process: {str(e)}")

    def run_r(self, script_path: Path, callback_good: Callable, callback_fail: Callable, name: str = "report"):
        if not self.rscript_exe:
            callback_fail("0s", "Rscript executable not found on host machine.")
            return

        try:
            start_time = time.time()
            process = subprocess.Popen(
                [str(self.rscript_exe), str(script_path)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            with self._proc_lock:
                self.active_processes[name] = process

            threading.Thread(
                target=self._watcher,
                args=(name, process, start_time, callback_good, callback_fail),
                daemon=True
            ).start()
        except Exception as e:
            callback_fail("0s", f"Failed to launch R process: {str(e)}")

