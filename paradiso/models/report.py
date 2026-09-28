from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

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
    report_type: str = "type_a" # Strictly one of: "type_a", "type_b", "type_c"
    interval_minutes: int = 30
    timeslot_tier: str = "CUSTOM" # "BOD", "MID", "EOD", "CUSTOM"
    catch_up_policy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Report":
        raw_type = str(data.get("report_type") or data.get("type") or "type_a").lower()
        if raw_type not in ("type_a", "type_b", "type_c"):
            raw_type = "type_a"

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
            last_output=data.get("last_output", "Unavailable"),
            report_type=raw_type,
            interval_minutes=int(data.get("interval_minutes") or 30),
            timeslot_tier=str(data.get("timeslot_tier") or "CUSTOM").upper(),
            catch_up_policy=str(data["catch_up_policy"]).upper() if data.get("catch_up_policy") else None
        )

