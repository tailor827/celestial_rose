from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Literal
from pathlib import Path
from models.storage_base import StorageBase
from utils.config import BASE_DIR
from utils.clock import CLOCK

@dataclass
class ReportRun:
    started_at: str
    finished_at: str
    result: Literal["completed", "failed", "skipped"]
    duration: str = "--"
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReportRun":
        return cls(
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
            result=data.get("result", "completed"),
            duration=data.get("duration", "--"),
            reason=data.get("reason")
        )

@dataclass
class TimelineEvent:
    timestamp: str
    title: str
    description: str
    type: Literal["system", "start", "success", "failed"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineEvent":
        return cls(
            timestamp=data.get("timestamp", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            type=data.get("type", "system")
        )

@dataclass
class IntradayDay:
    date: str
    status: Literal["WAITING_TO_OPEN", "OPEN", "WAITING_TO_CLOSE", "CLOSED"]
    expected_reports: List[str] = field(default_factory=list)
    reports_ran: Dict[str, ReportRun] = field(default_factory=dict)
    timeline: List[TimelineEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "expected_reports": self.expected_reports,
            "reports_ran": {k: v.to_dict() for k, v in self.reports_ran.items()},
            "timeline": [t.to_dict() for t in self.timeline]
        }

    @classmethod
    def from_dict(cls, date: str, data: Dict[str, Any]) -> "IntradayDay":
        return cls(
            date=date,
            status=data.get("status", "WAITING_TO_OPEN"),
            expected_reports=data.get("expected_reports", []),
            reports_ran={k: ReportRun.from_dict(v) for k, v in data.get("reports_ran", {}).items()},
            timeline=[TimelineEvent.from_dict(t) for t in data.get("timeline", [])]
        )

class Intraday(StorageBase):
    """Manages intraday execution history in storage/intraday.json."""

    WAITING_TO_OPEN = "WAITING_TO_OPEN"
    OPEN = "OPEN"
    WAITING_TO_CLOSE = "WAITING_TO_CLOSE"
    CLOSED = "CLOSED"

    def __init__(self, file_path: Optional[Path] = None):
        target = file_path or (BASE_DIR / "storage" / "intraday.json")
        super().__init__(target)

    def get_day(self, date: str) -> Optional[IntradayDay]:
        data = self._read_json()
        raw = data.get(date)
        if raw:
            return IntradayDay.from_dict(date, raw)
        return None

    def add_day(self, day: IntradayDay) -> None:
        def _mutate(data):
            data[day.date] = day.to_dict()
        self.mutate(_mutate)

    def update_status(self, date: str, status: str) -> None:
        def _mutate(data):
            if date in data:
                data[date]["status"] = status
        self.mutate(_mutate)

    def add_timeline_event(self, date: str, title: str, description: str, event_type: str = "system") -> None:
        event = TimelineEvent(
            timestamp=CLOCK.time_str(),
            title=title,
            description=description,
            type=event_type
        ).to_dict()
        def _mutate(data):
            if date not in data:
                data[date] = {
                    "status": self.OPEN,
                    "expected_reports": [],
                    "reports_ran": {},
                    "timeline": []
                }
            data[date].setdefault("timeline", []).append(event)
        self.mutate(_mutate)

    def add_report_run(self, date: str, report_name: str, run: ReportRun) -> None:
        run_dict = run.to_dict()
        def _mutate(data):
            if date not in data:
                data[date] = {
                    "status": self.OPEN,
                    "expected_reports": [],
                    "reports_ran": {},
                    "timeline": []
                }
            data[date].setdefault("reports_ran", {})[report_name] = run_dict
        self.mutate(_mutate)

