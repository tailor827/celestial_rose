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
        self.killed_exec_ids: set[int] = set()
        self._exec_counter: int = 0
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
        """Terminates all currently running child subprocesses immediately, including process trees."""
        with self._proc_lock:
            procs = list(self.active_processes.items())
            for name, process in procs:
                self.killed_processes.add(name)
                setattr(process, "_was_killed", True)
                exec_id = getattr(process, "_exec_id", None)
                if exec_id is not None:
                    self.killed_exec_ids.add(exec_id)

                pid = getattr(process, "pid", None)
                if pid and sys.platform == "win32":
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                        )
                    except Exception:
                        pass

                try:
                    process.terminate()
                    process.kill()
                except Exception:
                    pass

            self.active_processes.clear()

        # Wait for processes to exit and release OS handles outside the lock
        for name, process in procs:
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass

    def _watcher(self, name: str, process: subprocess.Popen, start_time: float, callback_good: Callable, callback_fail: Callable, exec_id: Optional[int] = None):
        stdout, stderr = process.communicate()
        proc_exec_id = exec_id if exec_id is not None else getattr(process, "_exec_id", None)
        with self._proc_lock:
            # Only remove from active_processes if this exact process instance is still the registered one
            if self.active_processes.get(name) is process:
                self.active_processes.pop(name, None)
            
            was_killed = getattr(process, "_was_killed", False) or (proc_exec_id is not None and proc_exec_id in self.killed_exec_ids)
            if proc_exec_id is not None:
                self.killed_exec_ids.discard(proc_exec_id)
            if name in self.killed_processes and self.active_processes.get(name) is not process:
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
                self._exec_counter += 1
                exec_id = self._exec_counter
                process._exec_id = exec_id
                process._was_killed = False
                self.active_processes[name] = process

            threading.Thread(
                target=self._watcher,
                args=(name, process, start_time, callback_good, callback_fail, exec_id),
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
                self._exec_counter += 1
                exec_id = self._exec_counter
                process._exec_id = exec_id
                process._was_killed = False
                self.active_processes[name] = process

            threading.Thread(
                target=self._watcher,
                args=(name, process, start_time, callback_good, callback_fail, exec_id),
                daemon=True
            ).start()
        except Exception as e:
            callback_fail("0s", f"Failed to launch R process: {str(e)}")

