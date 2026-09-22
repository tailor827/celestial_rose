from pathlib import Path
from typing import List, Dict, Any, Optional
from models.storage_base import StorageBase
from models.report import Report
from utils.config import BASE_DIR

class Automations(StorageBase):
    """Manages automations stored in storage/automations.json."""

    def __init__(self, file_path: Optional[Path] = None):
        target = file_path or (BASE_DIR / "storage" / "automations.json")
        super().__init__(target)

    def get_all(self, serialized: bool = False) -> List[Any]:
        data = self._read_json()
        if serialized:
            return list(data.values())
        return [Report.from_dict(v) for v in data.values()]

    def get_by_name(self, name: str) -> Optional[Report]:
        data = self._read_json()
        raw = data.get(name)
        if raw:
            return Report.from_dict(raw)
        return None

    def add(self, report: Report) -> None:
        def _mutate(data):
            data[report.name] = report.to_dict()
        self.mutate(_mutate)

    def delete(self, name: str) -> None:
        def _mutate(data):
            data.pop(name, None)
        self.mutate(_mutate)

    def get_waiting(self) -> List[str]:
        reports = self.get_all(serialized=False)
        return [r.name for r in reports if r.status == "Waiting"]

    def get_pending(self) -> List[str]:
        """Returns report names that are in a non-terminal state (not Completed and not Disabled)."""
        reports = self.get_all(serialized=False)
        return [r.name for r in reports if r.status not in ["Completed", "Disabled"]]

    def set_waiting_all(self) -> List[str]:
        updated_waiting = []
        def _mutate(data):
            for k, v in data.items():
                if v.get("status") != "Disabled":
                    v["status"] = "Waiting"
                    updated_waiting.append(k)
        self.mutate(_mutate)
        return updated_waiting


