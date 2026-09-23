import os
import json
import time
import shutil
import threading
from pathlib import Path
from typing import Dict, Any

class StorageCorruptionError(Exception):
    """Raised when an existing storage file contains invalid or corrupted JSON data."""
    pass

class StorageBase:
    """Base thread-safe storage class using atomic file replacements with transaction locking."""
    _global_lock = threading.RLock()
    _global_corrupted_states: Dict[Path, Any] = {}

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.temp_path = file_path.with_name(f"{file_path.stem}_temp.json")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_json_unlocked(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            return {}
        try:
            if self.file_path.stat().st_size == 0:
                return {}
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._global_corrupted_states.pop(self.file_path.resolve(), None)
            return data
        except json.JSONDecodeError as e:
            # Create emergency backup of damaged file before failing, deduplicated by state and content
            try:
                st = self.file_path.stat()
                stat_key = (st.st_mtime_ns, st.st_size)
                resolved = self.file_path.resolve()

                already_backed_up = False
                if self._global_corrupted_states.get(resolved) == stat_key:
                    already_backed_up = True
                else:
                    existing_baks = sorted(
                        list(self.file_path.parent.glob(f"{self.file_path.stem}_corrupted_*.bak")),
                        key=lambda p: p.stat().st_mtime
                    )
                    if existing_baks:
                        latest_bak = existing_baks[-1]
                        try:
                            if latest_bak.stat().st_size == st.st_size and latest_bak.read_bytes() == self.file_path.read_bytes():
                                already_backed_up = True
                                self._global_corrupted_states[resolved] = stat_key
                        except Exception:
                            pass

                if not already_backed_up:
                    self._global_corrupted_states[resolved] = stat_key
                    ts = int(time.time())
                    backup_path = self.file_path.with_name(f"{self.file_path.stem}_corrupted_{ts}.bak")
                    if backup_path.exists():
                        backup_path = self.file_path.with_name(f"{self.file_path.stem}_corrupted_{time.time_ns()}.bak")
                    shutil.copy2(str(self.file_path), str(backup_path))

                    # Keep at most the 5 latest rescue backups
                    existing_baks = sorted(
                        list(self.file_path.parent.glob(f"{self.file_path.stem}_corrupted_*.bak")),
                        key=lambda p: p.stat().st_mtime
                    )
                    if len(existing_baks) > 5:
                        for old_bak in existing_baks[:-5]:
                            try:
                                old_bak.unlink()
                            except Exception:
                                pass
            except Exception:
                pass
            raise StorageCorruptionError(
                f"Storage file {self.file_path} is corrupted: {e}. A rescue copy was created."
            ) from e
        except OSError as e:
            raise StorageCorruptionError(
                f"OS error reading storage file {self.file_path}: {e}"
            ) from e

    def _write_json_unlocked(self, data: Dict[str, Any]) -> None:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                with open(self.temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
                # os.replace is atomic on both Windows and Posix when target is on same volume
                os.replace(str(self.temp_path), str(self.file_path))
                self._global_corrupted_states.pop(self.file_path.resolve(), None)
                return
            except (PermissionError, OSError) as e:
                if attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))
                else:
                    raise e

    def _read_json(self) -> Dict[str, Any]:
        with self._global_lock:
            return self._read_json_unlocked()

    def _write_json(self, data: Dict[str, Any]) -> None:
        with self._global_lock:
            self._write_json_unlocked(data)

    def mutate(self, update_fn) -> Any:
        """Atomically read, modify via callback, and write JSON under global transaction lock."""
        with self._global_lock:
            data = self._read_json_unlocked()
            result = update_fn(data)
            self._write_json_unlocked(data)
            return result

