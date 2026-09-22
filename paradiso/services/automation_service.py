from typing import List, Dict, Any, Optional
from models.automation import Automations
from models.report import Report
from utils.clock import CLOCK

class AutomationService:
    """Business operations layer for automations."""
    def __init__(self, automations: Optional[Automations] = None):
        self.automations = automations or Automations()

    def get_all(self, serialized: bool = False) -> List[Any]:
        return self.automations.get_all(serialized=serialized)

    def get_by_name(self, name: str) -> Optional[Report]:
        return self.automations.get_by_name(name)

    def add(self, report: Report) -> None:
        self.automations.add(report)

    def delete(self, name: str) -> None:
        self.automations.delete(name)

    def disable(self, name: str) -> bool:
        report = self.get_by_name(name)
        if not report:
            return False
        report.status = "Disabled"
        self.add(report)
        return True

    def get_waiting(self) -> List[str]:
        return self.automations.get_waiting()

    def get_pending(self) -> List[str]:
        return self.automations.get_pending()

    def set_waiting_all(self) -> List[str]:
        return self.automations.set_waiting_all()

    def update_status(self, name: str, status: str, started_at: str = "--", duration: str = "--", last_output: str = "Unavailable") -> None:
        now_str = CLOCK.formatted_now()
        def _update(data):
            if name in data:
                data[name]["status"] = status
                if started_at != "--":
                    data[name]["started_at"] = started_at
                if duration != "--":
                    data[name]["duration"] = duration
                data[name]["last_run"] = now_str
                data[name]["last_output"] = last_output
        self.automations.mutate(_update)

