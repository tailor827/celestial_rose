from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class Report:
    name: str
    filename: str
    filetype: str
    dir: str
    team: str = "General"
    owner: str = "System"
    scheduled_time: str = "08:30"
    status: str = "Inactive"
    last_run: str = "--/--/--"
    started_at: str = "--"
    duration: str = "--"
    last_output: str = "Unavailable"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Report":
        return cls(
            name=data.get("name", ""),
            filename=data.get("filename", ""),
            filetype=data.get("filetype", "python"),
            dir=data.get("dir", "scripts"),
            team=data.get("team") or data.get("group") or "General",
            owner=data.get("owner", "System"),
            scheduled_time=data.get("scheduled_time", "08:30"),
            status=data.get("status", "Inactive"),
            last_run=data.get("last_run", "--/--/--"),
            started_at=data.get("started_at", "--"),
            duration=data.get("duration", "--"),
            last_output=data.get("last_output", "Unavailable")
        )

