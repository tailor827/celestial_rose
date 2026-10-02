import time
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Any, Tuple
from models.intraday import Intraday, IntradayDay, ReportRun, TimelineEvent
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from utils.clock import CLOCK
from utils.config import CONFIG

class IntradayService:
    """Decoupled thread-safe intraday queue manager with automated queue rotation for retries."""
    def __init__(self, automation_service: AutomationService, execution_service: ExecutionService, intraday_repo: Optional[Intraday] = None):
        self.intraday_repo = intraday_repo or Intraday()
        self.automation_service = automation_service
        self.execution_service = execution_service
        
        self.start_time = CONFIG.get("scheduler", {}).get("intraday_start_time", "07:00")
        self.idle_time = CONFIG.get("scheduler", {}).get("intraday_idle_time", "21:00")
        self.close_time = CONFIG.get("scheduler", {}).get("intraday_close_time", "22:00")
        self.max_retries = int(CONFIG.get("scheduler", {}).get("max_retries", 3))
        self.max_concurrent_run = int(CONFIG.get("scheduler", {}).get("max_concurrent_run", 1))
        self.retry_counts: Dict[str, int] = {}

        self._lock = threading.RLock()
        self.waitlist: deque = deque()
        self.current_runs: Dict[str, str] = {} # report_name -> started_at (Lane A)
        self.active_runs_type_b: Dict[str, str] = {} # report_name -> started_at (Lane B)
        self.active_runs_type_c: Dict[str, str] = {} # report_name -> started_at (Lane C)
        self.type_b_last_run: Dict[str, Any] = {} # report_name -> datetime of last execution
        self.type_b_exhausted: Set[str] = set() # report names permanently failed or exhausted retries today (Lane B)
        self.type_c_ran_today: Set[str] = set() # report names completed/exhausted today
        self.type_c_retry_after: Dict[str, Any] = {} # report_name -> datetime of retry cooldown
        self.type_c_warned: Set[str] = set() # report names warned for missed timeslot today
        self.lane_c_catch_up_policy: str = str(CONFIG.get("scheduler", {}).get("lane_c_catch_up_policy", "CATCH_UP_IMMEDIATE")).upper()
        self.lane_c_catch_up_grace_minutes: int = int(CONFIG.get("scheduler", {}).get("lane_c_catch_up_grace_minutes", 15))

        self.day_closed: bool = False
        self.lane_a_active: bool = False
        self.lane_b_active: bool = False
        self.lane_c_active: bool = False
        self.force_open: bool = False
        self._active_date: str = CLOCK.date_str()
        self._hydrate_type_b_last_run(self._active_date)
        self._hydrate_type_c_ran_today(self._active_date)

        # Queue pass tracking and starvation cooldown (F-005)
        self._cycle_pass_reports: Set[str] = set()
        self._cycle_seen_in_pass: Set[str] = set()
        self._cycle_completions_in_pass: int = 0
        self._cycle_skips_in_pass: int = 0
        self._cycle_errors_in_pass: int = 0
        self._rotation_cooldown_until: float = 0.0
        self._last_rotation_logged: Dict[str, float] = {}
        self.rotation_cooldown_seconds: float = float(CONFIG.get("scheduler", {}).get("rotation_cooldown_seconds", 30.0))

    @property
    def has_active_runs(self) -> bool:
        """Returns True if any report is actively executing across any lane (A, B, or C)."""
        with self._lock:
            return len(self.current_runs) > 0 or len(self.active_runs_type_b) > 0 or len(self.active_runs_type_c) > 0

    @property
    def is_active(self) -> bool:
        """Returns True if any scheduling lane is currently active."""
        return self.lane_a_active or self.lane_b_active or self.lane_c_active

    @is_active.setter
    def is_active(self, val: bool) -> None:
        """Sets active status across all lanes for backward compatibility."""
        self.lane_a_active = bool(val)
        self.lane_b_active = bool(val)
        self.lane_c_active = bool(val)

    def reload_config(self, cfg: Optional[dict] = None) -> None:
        """Dynamically reloads time window thresholds and concurrency from configuration."""
        c = cfg or CONFIG
        sched = c.get("scheduler", {})
        with self._lock:
            self.start_time = sched.get("intraday_start_time", self.start_time)
            self.idle_time = sched.get("intraday_idle_time", self.idle_time)
            self.close_time = sched.get("intraday_close_time", self.close_time)
            self.max_retries = int(sched.get("max_retries", self.max_retries))
            self.max_concurrent_run = int(sched.get("max_concurrent_run", self.max_concurrent_run))
            self.rotation_cooldown_seconds = float(sched.get("rotation_cooldown_seconds", self.rotation_cooldown_seconds))
            if "lane_c_catch_up_policy" in sched:
                self.lane_c_catch_up_policy = str(sched["lane_c_catch_up_policy"]).upper()
            if "lane_c_catch_up_grace_minutes" in sched:
                self.lane_c_catch_up_grace_minutes = int(sched["lane_c_catch_up_grace_minutes"])

    def get_rotation_cooldown(self) -> float:
        """Returns cooldown delay in seconds. Respects testing overrides and simulation scaling."""
        if hasattr(self, "_override_cooldown") and self._override_cooldown is not None:
            return self._override_cooldown
        if CLOCK.simulation_mode:
            return 5.0
        return self.rotation_cooldown_seconds

    def _priority_rank(self, report_name: str) -> int:
        """Returns numeric priority rank for a report: P0 -> 0, P1 -> 1, P2 -> 2 (default)."""
        rep = self.automation_service.get_by_name(report_name)
        prio = str(getattr(rep, "priority", "P2") if rep else "P2").strip().upper()
        return {"P0": 0, "P1": 1, "P2": 2}.get(prio, 2)

    def _enqueue_lane_a_by_priority(self, report_name: str) -> None:
        """Inserts a fresh/enabled Lane A report into waitlist according to priority tier without starving rotated items."""
        if report_name in self.waitlist:
            return
        target_rank = self._priority_rank(report_name)
        items = list(self.waitlist)
        insert_idx = len(items)
        for idx, existing in enumerate(items):
            if existing in self._cycle_seen_in_pass or self._priority_rank(existing) > target_rank:
                insert_idx = idx
                break
        items.insert(insert_idx, report_name)
        self.waitlist = deque(items)

    def _evaluate_pass_completion(self, date: str, defer_seen_clear: bool = False):
        """Checks if a full pass over all waiting reports has completed, engaging cooldown if all were skipped."""
        if self._cycle_pass_reports and self._cycle_pass_reports.issubset(self._cycle_seen_in_pass):
            # With multi-slot concurrency (max_concurrent_run > 1), wait for all in-flight jobs in the pass to finish
            if len(self.current_runs) > 0:
                return

            # Starvation: Every item in the pass was skipped due to unready dependencies
            if self._cycle_skips_in_pass > 0 and self._cycle_completions_in_pass == 0 and self._cycle_errors_in_pass == 0 and len(self.waitlist) > 0:
                cooldown = self.get_rotation_cooldown()
                self._rotation_cooldown_until = time.time() + cooldown
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title="Queue Cooldown",
                    description=f"All {len(self._cycle_seen_in_pass)} pending report(s) waiting on dependencies. Queue paused for {int(cooldown)}s.",
                    event_type="system"
                )
            # Re-order waitlist by priority tier (P0 -> P1 -> P2, stable within tier) for the next pass
            if len(self.waitlist) > 1:
                self.waitlist = deque(sorted(self.waitlist, key=self._priority_rank))
            # Reset pass tracking for the next pass
            self._cycle_pass_reports = set(self.waitlist)
            if not defer_seen_clear:
                self._cycle_seen_in_pass.clear()
            self._cycle_completions_in_pass = 0
            self._cycle_skips_in_pass = 0
            self._cycle_errors_in_pass = 0

    def _reconcile_past_days(self, current_date: str) -> None:
        """Scans intraday history and marks unfinalized past days as CLOSED."""
        def _mutate(data):
            for d_key, day_data in data.items():
                if str(d_key) < str(current_date) and day_data.get("status") != Intraday.CLOSED:
                    day_data["status"] = Intraday.CLOSED
                    reports_ran = day_data.setdefault("reports_ran", {})
                    expected = day_data.get("expected_reports", [])
                    for exp_rep in expected:
                        if exp_rep not in reports_ran:
                            reports_ran[exp_rep] = {
                                "started_at": "--",
                                "finished_at": "--",
                                "result": "failed",
                                "duration": "0s",
                                "reason": "Historical day finalized automatically"
                            }
                    day_data.setdefault("timeline", []).append({
                        "timestamp": "22:00",
                        "title": "Paradiso closed (auto-reconciled)",
                        "description": f"Historical intraday window for {d_key} automatically marked CLOSED",
                        "type": "system"
                    })
        self.intraday_repo.mutate(_mutate)

    @staticmethod
    def _parse_timestamp(ts_str: Optional[str], today_date: str) -> Optional[datetime]:
        """Parses various timestamp strings from reports_ran or automations into a datetime object."""
        if not ts_str or ts_str == "--":
            return None
        ts = str(ts_str).strip()
        formats = [
            "%Y-%m-%d %I:%M:%S %p",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d %H:%M",
            "%Y%m%d %H:%M:%S",
            "%Y%m%d %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                pass

        time_formats = [
            "%I:%M:%S %p",
            "%I:%M %p",
            "%H:%M:%S",
            "%H:%M",
        ]
        for t_fmt in time_formats:
            try:
                t = datetime.strptime(ts, t_fmt).time()
                try:
                    base_dt = datetime.strptime(today_date, "%Y%m%d")
                    return datetime.combine(base_dt.date(), t)
                except ValueError:
                    pass
            except ValueError:
                pass
        return None

    def _normalize_timeslot(self, t_str: Any) -> Optional[Tuple[str, Any]]:
        """Defensively parses timeslot string into (canonical_HH_MM, time_obj)."""
        if not t_str:
            return None
        s = str(t_str).strip()
        for fmt in ("%H:%M", "%I:%M %p", "%I:%M:%S %p", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(s, fmt).time()
                return parsed_time.strftime("%H:%M"), parsed_time
            except ValueError:
                pass
        return None

    def _hydrate_type_b_last_run(self, date: str) -> None:
        """Hydrates in-memory type_b_last_run from persisted reports_ran in intraday storage and automation catalog."""
        day = self.intraday_repo.get_day(date)
        b_reports = self.automation_service.get_by_type("type_b")
        now_dt = CLOCK.now()
        for rep in b_reports:
            if rep.name in self.type_b_last_run:
                continue
            parsed_dt = None
            ran_today = False
            if day and day.reports_ran and rep.name in day.reports_ran:
                run_data = day.reports_ran[rep.name]
                finished_at = getattr(run_data, "finished_at", None) or (run_data.get("finished_at") if isinstance(run_data, dict) else None)
                parsed_dt = self._parse_timestamp(finished_at, date)
                if parsed_dt:
                    ran_today = True
            if not parsed_dt and rep.last_run and rep.last_run != "--":
                parsed_dt = self._parse_timestamp(rep.last_run, date)
                if parsed_dt and not ran_today:
                    if parsed_dt > now_dt or not any(d_fmt in str(rep.last_run) for d_fmt in [CLOCK.date_str(), CLOCK.formatted_date()]):
                        parsed_dt = parsed_dt - timedelta(days=1)
            if parsed_dt:
                if parsed_dt > now_dt:
                    parsed_dt = parsed_dt - timedelta(days=1)
                if parsed_dt <= now_dt:
                    self.type_b_last_run[rep.name] = parsed_dt

    def _hydrate_type_c_ran_today(self, date: str) -> None:
        """Hydrates in-memory type_c_ran_today from persisted reports_ran in intraday storage for the specified date."""
        day = self.intraday_repo.get_day(date)
        if day and day.reports_ran:
            c_reports = {r.name for r in self.automation_service.get_by_type("type_c")}
            for name, run_data in day.reports_ran.items():
                if name in c_reports:
                    result = getattr(run_data, "result", None) or (run_data.get("result") if isinstance(run_data, dict) else "")
                    if result in ("completed", "failed", "skipped"):
                        self.type_c_ran_today.add(name)

    def _get_completed_or_exhausted_reports(self, day: Optional[IntradayDay]) -> Set[str]:
        """Returns reports that should NOT be queued today (completed or exhausted max retries)."""
        if not day or not day.reports_ran:
            return set()
        excluded = set()
        for name, run in day.reports_ran.items():
            result = getattr(run, "result", None) or (run.get("result") if isinstance(run, dict) else "")
            reason = getattr(run, "reason", "") or (run.get("reason", "") if isinstance(run, dict) else "")
            started_at = getattr(run, "started_at", "") or (run.get("started_at", "") if isinstance(run, dict) else "")
            if result == "completed":
                excluded.add(name)
            elif result == "failed":
                is_cutoff_or_unstarted = (
                    started_at == "--"
                    or "cutoff" in str(reason).lower()
                    or "finalized automatically" in str(reason).lower()
                )
                if not is_cutoff_or_unstarted:
                    excluded.add(name)
        return excluded

    def _get_or_init_day(self, today_date: str, status: str, force_open: bool = False, is_new_day: bool = False) -> IntradayDay:
        """Retrieves today's day record, resetting prematurely finalized or stale records during WAITING_TO_OPEN or forced open."""
        day = self.intraday_repo.get_day(today_date)
        is_stale_or_premature = False

        if is_new_day:
            is_stale_or_premature = True
        elif day:
            # 1. During WAITING_TO_OPEN (00:00 - 06:59), the day has not opened yet.
            # A CLOSED status or pre-existing reports_ran is premature/stale.
            if status == Intraday.WAITING_TO_OPEN:
                if day.status == Intraday.CLOSED or len(day.reports_ran) > 0:
                    is_stale_or_premature = True

        if not day or is_stale_or_premature:
            waiting = self.automation_service.set_waiting_all()
            effective_status = Intraday.OPEN if force_open else status
            day = IntradayDay(
                date=today_date,
                status=effective_status,
                expected_reports=waiting,
                reports_ran={},
                timeline=[TimelineEvent(
                    timestamp=CLOCK.time_str(),
                    title="Day Initialized",
                    description=f"Paradiso day initialized for {today_date}" + (" (Clean slate from premature closure)" if is_stale_or_premature and not is_new_day else ""),
                    type="system"
                )]
            )
            self.intraday_repo.add_day(day)
        else:
            if (force_open or status == Intraday.OPEN) and day.status != Intraday.OPEN:
                self.intraday_repo.update_status(today_date, Intraday.OPEN)
                day.status = Intraday.OPEN
            elif day.status != status and not force_open:
                self.intraday_repo.update_status(today_date, status)
                day.status = status

        return day

    def resolve_status(self) -> str:
        t = CLOCK.time_24_str()
        if t >= self.close_time:
            return Intraday.CLOSED
        if t >= self.idle_time:
            return Intraday.WAITING_TO_CLOSE
        if self.force_open:
            return Intraday.OPEN
        if t < self.start_time:
            return Intraday.WAITING_TO_OPEN
        return Intraday.OPEN

    def _normalize_lane(self, lane: str) -> str:
        l = str(lane or "").lower().strip()
        if l in ("type_a", "lane_a", "a"):
            return "type_a"
        if l in ("type_b", "lane_b", "b"):
            return "type_b"
        if l in ("type_c", "lane_c", "c"):
            return "type_c"
        raise ValueError(f"Invalid lane identifier: '{lane}'. Must be 'type_a', 'type_b', or 'type_c'.")

    def start_lane(self, lane: str, force_open: bool = False):
        """Starts an individual execution lane (type_a, type_b, or type_c)."""
        norm = self._normalize_lane(lane)
        with self._lock:
            if force_open:
                self.force_open = True
            today_date = CLOCK.date_str()
            self._reconcile_past_days(today_date)
            status = self.resolve_status()
            day = self._get_or_init_day(today_date, status, force_open=force_open)

            if norm == "type_a":
                self.lane_a_active = True
                pending = self.automation_service.get_pending_by_type("type_a")
                already_ran = self._get_completed_or_exhausted_reports(day)
                queue_items = [r for r in pending if r not in already_ran and r not in self.current_runs]
                self.waitlist = deque(queue_items)
                self._rotation_cooldown_until = 0.0
                self._cycle_pass_reports = set(self.waitlist)
                self._cycle_seen_in_pass.clear()
                self._cycle_completions_in_pass = 0
                self._last_rotation_logged.clear()
                self.intraday_repo.add_timeline_event(
                    date=today_date,
                    title="Lane A (Sequential) started",
                    description=f"Sequential queue execution initiated for {len(self.waitlist)} pending report(s)",
                    event_type="system"
                )
            elif norm == "type_b":
                self.lane_b_active = True
                self._hydrate_type_b_last_run(today_date)
                self.intraday_repo.add_timeline_event(
                    date=today_date,
                    title="Lane B (Recurring) started",
                    description="Recurring interval execution initiated",
                    event_type="system"
                )
            elif norm == "type_c":
                self.lane_c_active = True
                self._hydrate_type_c_ran_today(today_date)
                self.intraday_repo.add_timeline_event(
                    date=today_date,
                    title="Lane C (Timeslots) started",
                    description="Fixed timeslot monitoring initiated",
                    event_type="system"
                )

    def stop_lane(self, lane: str):
        """Stops an individual execution lane, terminates its running processes, and resets status to Waiting."""
        norm = self._normalize_lane(lane)
        with self._lock:
            today_date = CLOCK.date_str()
            if norm == "type_a":
                self.lane_a_active = False
                self.waitlist.clear()
                self._rotation_cooldown_until = 0.0
                self._cycle_pass_reports.clear()
                self._cycle_seen_in_pass.clear()
                self._cycle_completions_in_pass = 0
                self._last_rotation_logged.clear()
                for report_name in list(self.current_runs.keys()):
                    self.execution_service.runner.kill_process(report_name)
                    self.automation_service.update_status(
                        name=report_name,
                        status="Waiting",
                        duration="0s",
                        last_output="Stopped by user"
                    )
                self.current_runs.clear()
                self.intraday_repo.add_timeline_event(
                    date=today_date,
                    title="Lane A (Sequential) stopped",
                    description="Sequential lane paused by user; active runs terminated",
                    event_type="system"
                )
            elif norm == "type_b":
                self.lane_b_active = False
                for report_name in list(self.active_runs_type_b.keys()):
                    self.execution_service.runner.kill_process(report_name)
                    self.automation_service.update_status(
                        name=report_name,
                        status="Waiting",
                        duration="0s",
                        last_output="Stopped by user"
                    )
                self.active_runs_type_b.clear()
                self.intraday_repo.add_timeline_event(
                    date=today_date,
                    title="Lane B (Recurring) stopped",
                    description="Recurring lane paused by user; active runs terminated",
                    event_type="system"
                )
            elif norm == "type_c":
                self.lane_c_active = False
                for report_name in list(self.active_runs_type_c.keys()):
                    self.execution_service.runner.kill_process(report_name)
                    self.automation_service.update_status(
                        name=report_name,
                        status="Waiting",
                        duration="0s",
                        last_output="Stopped by user"
                    )
                self.active_runs_type_c.clear()
                self.type_c_warned.clear()
                self.intraday_repo.add_timeline_event(
                    date=today_date,
                    title="Lane C (Timeslots) stopped",
                    description="Timeslot lane paused by user; active runs terminated",
                    event_type="system"
                )
            if not self.lane_a_active and not self.lane_b_active and not self.lane_c_active:
                self.force_open = False

    def start_fresh_run(self, force_open: bool = False):
        """Initiates fresh run across all lanes for backward compatibility."""
        with self._lock:
            self.lane_a_active = True
            self.lane_b_active = True
            self.lane_c_active = True
            self.force_open = force_open
            today_date = CLOCK.date_str()
            self.retry_counts.clear()

            # Reconcile historical days stuck in OPEN
            self._reconcile_past_days(today_date)

            # Recover any reports left in "Running" status from crashed session
            for r in self.automation_service.get_all():
                if r.status == "Running":
                    self.automation_service.update_status(
                        name=r.name,
                        status="Waiting",
                        last_output="Reset from previous session shutdown/crash"
                    )

            status = self.resolve_status()
            day = self._get_or_init_day(today_date, status, force_open=self.force_open)
            pending = self.automation_service.get_pending_by_type("type_a")
            already_ran = self._get_completed_or_exhausted_reports(day)
            queue_items = [r for r in pending if r not in already_ran and r not in self.current_runs]

            self.waitlist = deque(queue_items)
            self._hydrate_type_b_last_run(today_date)
            self._hydrate_type_c_ran_today(today_date)
            self.day_closed = False
            self.type_c_retry_after.clear()
            self._rotation_cooldown_until = 0.0
            self._cycle_pass_reports = set(self.waitlist)
            self._cycle_seen_in_pass.clear()
            self._cycle_completions_in_pass = 0
            self._last_rotation_logged.clear()
            self.intraday_repo.add_timeline_event(
                date=today_date,
                title="Scheduler started",
                description=f"Multi-lane execution initiated ({len(self.waitlist)} Type A queued)",
                event_type="system"
            )

    def stop_scheduler(self):
        """Pauses all scheduling lanes, terminates active subprocesses, and logs stop event."""
        with self._lock:
            self.stop_lane("type_a")
            self.stop_lane("type_b")
            self.stop_lane("type_c")
            self.force_open = False
            today_date = CLOCK.date_str()
            self.intraday_repo.add_timeline_event(
                date=today_date,
                title="Scheduler stopped",
                description="All lanes paused by user; active runs terminated",
                event_type="system"
            )

    def reset_all_reports(self):
        """Resets all scheduled reports to Waiting, kills running processes, and sets scheduler to Standby."""
        with self._lock:
            self.lane_a_active = False
            self.lane_b_active = False
            self.lane_c_active = False
            self.force_open = False
            self.waitlist.clear()
            self.retry_counts.clear()
            self._rotation_cooldown_until = 0.0
            self._cycle_pass_reports.clear()
            self._cycle_seen_in_pass.clear()
            self._cycle_completions_in_pass = 0
            self._last_rotation_logged.clear()
            self.type_b_last_run.clear()
            self.type_b_exhausted.clear()
            self.type_c_ran_today.clear()
            self.type_c_retry_after.clear()
            self.type_c_warned.clear()

            # Kill any active processes and clear all run tracking maps
            self.execution_service.runner.kill_all()
            self.current_runs.clear()
            self.active_runs_type_b.clear()
            self.active_runs_type_c.clear()

            waiting = self.automation_service.set_waiting_all()
            today_date = CLOCK.date_str()
            day = self.intraday_repo.get_day(today_date)
            if day:
                day.reports_ran = {}
                self.intraday_repo.add_day(day)

            self.intraday_repo.add_timeline_event(
                date=today_date,
                title="Reports reset",
                description="All report statuses reset to Waiting (Scheduler Standby)",
                event_type="system"
            )

    def tick(self):
        with self._lock:
            today_date = CLOCK.date_str()
            day = self.intraday_repo.get_day(today_date)
            status = self.resolve_status()
            is_new_day = (today_date > self._active_date)
            if today_date < self._active_date:
                self._active_date = today_date

            if not day or is_new_day:
                self._active_date = today_date
                if is_new_day:
                    self.force_open = False
                    status = self.resolve_status()
                # Reconcile past days upon crossing midnight
                self._reconcile_past_days(today_date)

                # Midnight rollover cleanup: kill lingering processes across all lanes
                all_active = list(self.current_runs.keys()) + list(self.active_runs_type_b.keys()) + list(self.active_runs_type_c.keys())
                if all_active:
                    self.execution_service.runner.kill_all()
                    for r_name in all_active:
                        self.automation_service.update_status(
                            name=r_name,
                            status="Failed",
                            last_output="Forcibly terminated at midnight rollover"
                        )
                    self.current_runs.clear()
                    self.active_runs_type_b.clear()
                    self.active_runs_type_c.clear()

                self.retry_counts.clear()
                self.waitlist.clear()
                self.type_b_last_run.clear()
                self.type_b_exhausted.clear()
                self.type_c_ran_today.clear()
                self.type_c_retry_after.clear()
                self.type_c_warned.clear()

                day = self._get_or_init_day(today_date, status, force_open=self.force_open, is_new_day=True)

                if self.lane_a_active:
                    pending_a = self.automation_service.get_pending_by_type("type_a")
                    self.waitlist = deque(pending_a)
                    self._rotation_cooldown_until = 0.0
                    self._cycle_pass_reports = set(self.waitlist)
                    self._cycle_seen_in_pass.clear()
                    self._cycle_completions_in_pass = 0
                    self._cycle_skips_in_pass = 0
                    self._cycle_errors_in_pass = 0
                    self._last_rotation_logged.clear()
                self.day_closed = False
            else:
                # Same day: if day was prematurely closed or stale, ensure clean day
                if day and day.status == Intraday.CLOSED and (status == Intraday.WAITING_TO_OPEN or self.force_open or status == Intraday.OPEN):
                    day = self._get_or_init_day(today_date, status, force_open=self.force_open)
                elif day and day.status != status and not self.force_open:
                    self.intraday_repo.update_status(today_date, status)
                    day.status = status

            # End of day cutoff logic at 22:00 (CLOSED)
            if status == Intraday.CLOSED:
                self.force_open = False
                if not self.day_closed:
                    self.day_closed = True
                    self._close_day(today_date)
                return
            else:
                self.day_closed = False

            # WAITING_TO_CLOSE (21:00 - 22:00): Do not pop new reports, wait for in-flight processes
            if status == Intraday.WAITING_TO_CLOSE:
                return

            # Check if any lane should execute during OPEN (07:00 - 21:00) or force_open
            if status == Intraday.OPEN or self.force_open:
                # --- LANE A: Sequential queue execution (up to max_concurrent_run) ---
                if self.lane_a_active:
                    already_ran = self._get_completed_or_exhausted_reports(day)
                    pending_a = self.automation_service.get_pending_by_type("type_a")
                    uncompleted = [r for r in pending_a if r not in already_ran and r not in self.current_runs and r not in self.waitlist]
                    for r in uncompleted:
                        self._enqueue_lane_a_by_priority(r)
                        self._cycle_pass_reports.add(r)

                    if not self._cycle_pass_reports and self.waitlist:
                        self._cycle_pass_reports = set(self.waitlist)

                    if len(self.waitlist) > 0 and len(self.current_runs) < self.max_concurrent_run:
                        unseen_candidates = [r for r in self.waitlist if r not in self._cycle_seen_in_pass]
                        if len(self.current_runs) == 0 and len(self.waitlist) > 0 and not unseen_candidates:
                            self._evaluate_pass_completion(today_date)
                            unseen_candidates = [r for r in self.waitlist if r not in self._cycle_seen_in_pass]

                        if time.time() >= self._rotation_cooldown_until:
                            available_slots = self.max_concurrent_run - len(self.current_runs)
                            launched = 0
                            for next_report in unseen_candidates:
                                if launched >= available_slots:
                                    break
                                self.waitlist.remove(next_report)
                                rep = self.automation_service.get_by_name(next_report)
                                if not rep or rep.status == "Disabled":
                                    self._cycle_pass_reports.discard(next_report)
                                    self._evaluate_pass_completion(today_date)
                                    continue
                                self._trigger_report(next_report, today_date)
                                launched += 1

                # --- LANE B: Recurring at intervals (concurrent, self-overlap prevented) ---
                if self.lane_b_active:
                    self._hydrate_type_b_last_run(today_date)
                    b_reports = self.automation_service.get_by_type("type_b")
                    for rep in b_reports:
                        if rep.name in self.type_b_exhausted:
                            continue
                        if rep.status in ("Disabled", "Failed"):
                            if rep.status == "Failed":
                                self.type_b_exhausted.add(rep.name)
                            continue
                        if self.retry_counts.get(rep.name, 0) >= self.max_retries:
                            self.type_b_exhausted.add(rep.name)
                            continue
                        if rep.name in self.active_runs_type_b:
                            continue  # Self-overlap prevention
                        last_run = self.type_b_last_run.get(rep.name)
                        interval_sec = (rep.interval_minutes or 30) * 60
                        should_run = False
                        if last_run is None:
                            should_run = True
                        else:
                            elapsed = (CLOCK.now() - last_run).total_seconds()
                            if elapsed >= interval_sec:
                                should_run = True
                        if should_run:
                            self._trigger_type_b_report(rep.name, today_date)

                # --- LANE C: Fixed and custom timeslots (once per day) ---
                if self.lane_c_active:
                    self._hydrate_type_c_ran_today(today_date)
                    c_reports = self.automation_service.get_by_type("type_c")
                    now_dt = CLOCK.now()
                    now_time_str = CLOCK.time_24_str()

                    for rep in c_reports:
                        if rep.status in ("Completed", "Disabled", "Skipped"):
                            continue
                        if rep.name in self.active_runs_type_c:
                            continue
                        if rep.name in self.type_c_ran_today:
                            continue

                        retry_after = self.type_c_retry_after.get(rep.name)
                        if retry_after and now_dt < retry_after:
                            continue

                        tier = (rep.timeslot_tier or "CUSTOM").upper()
                        if rep.scheduled_time:
                            target_time = rep.scheduled_time
                        elif tier == "BOD":
                            target_time = self.start_time or "07:00"
                        elif tier == "MID":
                            target_time = "12:00"
                        elif tier == "EOD":
                            target_time = "20:30"
                        else:
                            target_time = "08:30"

                        norm = self._normalize_timeslot(target_time)
                        if not norm:
                            if rep.name not in self.type_c_warned:
                                self.type_c_warned.add(rep.name)
                                self.intraday_repo.add_timeline_event(
                                    date=today_date,
                                    title=f"Invalid Timeslot: {rep.name}",
                                    description=f"Cannot parse scheduled_time '{target_time}'. Must be HH:MM format.",
                                    event_type="warning"
                                )
                            continue

                        canonical_time, time_obj = norm
                        if now_time_str >= canonical_time:
                            target_dt = datetime.combine(now_dt.date(), time_obj)
                            elapsed_minutes = (now_dt - target_dt).total_seconds() / 60.0
                            policy = (getattr(rep, "catch_up_policy", None) or self.lane_c_catch_up_policy).upper()
                            is_missed = elapsed_minutes > self.lane_c_catch_up_grace_minutes

                            if not is_missed or policy == "CATCH_UP_IMMEDIATE":
                                if is_missed:
                                    self.intraday_repo.add_timeline_event(
                                        date=today_date,
                                        title=f"Catch-up Trigger: {rep.name}",
                                        description=f"Missed timeslot ({target_time}) caught up after {int(elapsed_minutes)}m delay.",
                                        event_type="system"
                                    )
                                self._trigger_type_c_report(rep.name, today_date)

                            elif policy == "SKIP_UNTIL_NEXT_DAY":
                                self.type_c_ran_today.add(rep.name)
                                self.automation_service.update_status(
                                    name=rep.name,
                                    status="Skipped",
                                    last_output=f"Missed timeslot ({target_time}) by {int(elapsed_minutes)}m - skipped until next day"
                                )
                                self.intraday_repo.add_report_run(
                                    date=today_date,
                                    report_name=rep.name,
                                    run=ReportRun(
                                        started_at="--",
                                        finished_at=CLOCK.time_str(),
                                        result="skipped",
                                        duration="0s",
                                        reason=f"Missed timeslot ({target_time}) by {int(elapsed_minutes)}m - skipped until next day"
                                    )
                                )
                                self.intraday_repo.add_timeline_event(
                                    date=today_date,
                                    title=f"Timeslot Skipped: {rep.name}",
                                    description=f"Scheduled for {target_time}, current time is {now_time_str} (exceeded {self.lane_c_catch_up_grace_minutes}m grace). Skipped until next day.",
                                    event_type="system"
                                )

                            elif policy == "WARN_OPERATOR":
                                if rep.name not in self.type_c_warned:
                                    self.type_c_warned.add(rep.name)
                                    self.intraday_repo.add_timeline_event(
                                        date=today_date,
                                        title=f"Missed Timeslot Alert: {rep.name}",
                                        description=f"Scheduled for {target_time}, current time is {now_time_str} (missed by {int(elapsed_minutes)}m). Operator review required.",
                                        event_type="warning"
                                    )

    def _close_day(self, date: str):
        """Terminate lingering processes and mark remaining uncompleted reports as failed at 10:00 PM cutoff."""
        self.execution_service.runner.kill_all()
        running_reports = set(self.current_runs.keys()) | set(self.active_runs_type_b.keys()) | set(self.active_runs_type_c.keys())
        self.current_runs.clear()
        self.active_runs_type_b.clear()
        self.active_runs_type_c.clear()

        day = self.intraday_repo.get_day(date)
        already_ran = set(day.reports_ran.keys()) if day else set()
        all_reports = self.automation_service.get_all()

        for r in all_reports:
            if r.status == "Disabled":
                continue
            if r.name in running_reports or (r.name not in already_ran and r.status != "Completed"):
                reason = "Forcibly terminated: breached 10:00 PM cutoff (exceeded grace window)" if r.name in running_reports else "Not completed before 10:00 PM cutoff"
                self.automation_service.update_status(
                    name=r.name,
                    status="Failed",
                    last_output=reason
                )
                self.intraday_repo.add_report_run(
                    date=date,
                    report_name=r.name,
                    run=ReportRun(
                        started_at=CLOCK.formatted_now(),
                        finished_at=CLOCK.formatted_now(),
                        result="failed",
                        duration="0s",
                        reason=reason
                    )
                )
        self.waitlist.clear()
        self.type_c_retry_after.clear()
        self.intraday_repo.add_timeline_event(
            date=date,
            title="Paradiso closed",
            description="Intraday execution window closed at 10:00 PM; all running tasks forcibly killed and uncompleted reports logged as Failed",
            event_type="system"
        )

    def _trigger_report(self, report_name: str, date: str):
        rep = self.automation_service.get_by_name(report_name)
        if rep and rep.status == "Disabled":
            self._cycle_pass_reports.discard(report_name)
            return

        self.current_runs[report_name] = CLOCK.formatted_now()
        if not self._cycle_pass_reports:
            self._cycle_pass_reports = set(self.waitlist) | {report_name}
        self._cycle_seen_in_pass.add(report_name)
        
        self.intraday_repo.add_timeline_event(
            date=date,
            title=f"Started {report_name}",
            description="Currently running",
            event_type="start"
        )

        def _on_good(name: str, duration_str: str, output: str):
            with self._lock:
                started_at = self.current_runs.pop(name, CLOCK.formatted_now())
                log = ReportLog(name).from_json(default_stdout=output)

                if log.status == "Completed":
                    # Terminal Success: record in intraday repo & remove from waitlist
                    self._cycle_completions_in_pass += 1
                    self._cycle_pass_reports.discard(name)
                    self._rotation_cooldown_until = 0.0

                    self.intraday_repo.add_report_run(
                        date=date,
                        report_name=name,
                        run=ReportRun(
                            started_at=started_at,
                            finished_at=CLOCK.formatted_now(),
                            result="completed",
                            duration=duration_str,
                            reason=log.last_output
                        )
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Completed {name}",
                        description=f"Finished in {duration_str}",
                        event_type="success"
                    )
                    self._evaluate_pass_completion(date)
                elif ReportLog.is_dependency_skip(log.status, log.last_output or output):
                    # Non-completed dependency skip / retrial: Rotate to back of waitlist if scheduler active
                    self._cycle_skips_in_pass += 1
                    scheduler_is_active = self.lane_a_active and (self.resolve_status() == Intraday.OPEN or self.force_open)
                    if scheduler_is_active:
                        self.waitlist.append(name)
                    self.automation_service.update_status(
                        name=name,
                        status="Retrial",
                        duration=duration_str,
                        last_output=f"Skipped/Dependency unready: {log.last_output}"
                    )
                    desc = "Skipped (missing dependency), rotated to back of queue" if scheduler_is_active else "Skipped (missing dependency), scheduler paused"
                    
                    now_ts = time.time()
                    last_ts = self._last_rotation_logged.get(name, 0.0)
                    cooldown = self.get_rotation_cooldown()
                    if (now_ts - last_ts) >= cooldown:
                        self._last_rotation_logged[name] = now_ts
                        self.intraday_repo.add_timeline_event(
                            date=date,
                            title=f"Rotated {name}",
                            description=desc,
                            event_type="system"
                        )
                    self._evaluate_pass_completion(date)
                else:
                    # Non-completed, non-skip result (e.g. Failed status or contract violation):
                    _handle_failure(name, started_at, duration_str, log.last_output or "Execution did not complete successfully", log)

        def _handle_failure(name: str, started_at: str, duration_str: str, error: str, log: ReportLog):
            scheduler_is_active = self.lane_a_active and (self.resolve_status() == Intraday.OPEN or self.force_open)
            self._cycle_errors_in_pass += 1
            attempts = self.retry_counts.get(name, 0) + 1
            self.retry_counts[name] = attempts

            if attempts < self.max_retries and scheduler_is_active:
                self.waitlist.append(name)
                self.automation_service.update_status(
                    name=name,
                    status="Retrial",
                    duration=duration_str,
                    last_output=f"Error (attempt {attempts}/{self.max_retries}): {error}"
                )
                desc = f"Re-queued for retry ({attempts}/{self.max_retries}): {error[:60]}"
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title=f"{name} encountered error",
                    description=desc,
                    event_type="failed"
                )
                self._evaluate_pass_completion(date)
            else:
                self._cycle_pass_reports.discard(name)
                self.automation_service.update_status(
                    name=name,
                    status="Failed",
                    duration=duration_str,
                    last_output=f"Exceeded max retries ({attempts}/{self.max_retries}): {error}"
                )
                self.intraday_repo.add_report_run(
                    date=date,
                    report_name=name,
                    run=ReportRun(
                        started_at=started_at,
                        finished_at=CLOCK.formatted_now(),
                        result="failed",
                        duration=duration_str,
                        reason=f"Exceeded max retries ({attempts}/{self.max_retries}): {error}"
                    )
                )
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title=f"{name} permanently failed",
                    description=f"Exceeded max retries ({attempts}/{self.max_retries}): {error[:60]}",
                    event_type="failed"
                )
                self._evaluate_pass_completion(date)

        def _on_fail(name: str, duration_str: str, error: str):
            with self._lock:
                started_at = self.current_runs.pop(name, CLOCK.formatted_now())
                log = ReportLog(name).from_json(default_stdout=error)
                scheduler_is_active = self.lane_a_active and (self.resolve_status() == Intraday.OPEN or self.force_open)

                # Check if this failure was actually a dependency skip / retrial dumped by the script
                is_dependency_skip = (
                    ReportLog.is_dependency_skip(log.status, error) or
                    ReportLog.is_dependency_skip(log.status, log.last_output)
                )

                if is_dependency_skip:
                    # Dependency skip / wait: Rotate to back of waitlist WITHOUT incrementing retry_counts
                    self._cycle_skips_in_pass += 1
                    if scheduler_is_active:
                        self.waitlist.append(name)
                    self.automation_service.update_status(
                        name=name,
                        status="Retrial",
                        duration=duration_str,
                        last_output=f"Skipped/Dependency unready: {log.last_output or log.reason or error}"
                    )
                    desc = "Skipped (missing dependency), rotated to back of queue" if scheduler_is_active else "Skipped (missing dependency), scheduler paused"
                    
                    now_ts = time.time()
                    last_ts = self._last_rotation_logged.get(name, 0.0)
                    cooldown = self.get_rotation_cooldown()
                    if (now_ts - last_ts) >= cooldown:
                        self._last_rotation_logged[name] = now_ts
                        self.intraday_repo.add_timeline_event(
                            date=date,
                            title=f"Rotated {name}",
                            description=desc,
                            event_type="system"
                        )
                    self._evaluate_pass_completion(date)
                    return

                _handle_failure(name, started_at, duration_str, error, log)

        self.execution_service.execute_report(
            name=report_name,
            callback_good=_on_good,
            callback_fail=_on_fail
        )

    def _trigger_type_b_report(self, report_name: str, date: str):
        self.active_runs_type_b[report_name] = CLOCK.formatted_now()
        self.intraday_repo.add_timeline_event(
            date=date,
            title=f"Started {report_name}",
            description="Currently running (Type B)",
            event_type="start"
        )

        def _on_good(name: str, duration_str: str, output: str):
            with self._lock:
                started_at = self.active_runs_type_b.pop(name, CLOCK.formatted_now())
                self.type_b_last_run[name] = CLOCK.now()
                log = ReportLog(name).from_json(default_stdout=output)

                if log.status == "Completed":
                    if name not in self.type_b_exhausted:
                        self.retry_counts[name] = 0
                    self.intraday_repo.add_report_run(
                        date=date,
                        report_name=name,
                        run=ReportRun(
                            started_at=started_at,
                            finished_at=CLOCK.formatted_now(),
                            result="completed",
                            duration=duration_str,
                            reason=log.last_output
                        )
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Completed {name}",
                        description=f"Finished in {duration_str} (Type B)",
                        event_type="success"
                    )
                elif ReportLog.is_dependency_skip(log.status, log.last_output or output):
                    self.automation_service.update_status(
                        name=name,
                        status="Retrial",
                        duration=duration_str,
                        last_output=f"Skipped/Dependency unready: {log.last_output}"
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Skipped {name}",
                        description="Dependency unready (Type B), will retry on next interval",
                        event_type="system"
                    )
                else:
                    _handle_failure(name, started_at, duration_str, log.last_output or "Execution did not complete successfully")

        def _handle_failure(name: str, started_at: str, duration_str: str, error: str):
            attempts = self.retry_counts.get(name, 0) + 1
            self.retry_counts[name] = attempts
            scheduler_is_active = self.lane_b_active or self.force_open

            if attempts < self.max_retries and scheduler_is_active:
                self.type_b_last_run[name] = CLOCK.now()
                self.automation_service.update_status(
                    name=name,
                    status="Retrial",
                    duration=duration_str,
                    last_output=f"Error (attempt {attempts}/{self.max_retries}): {error}"
                )
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title=f"{name} encountered error",
                    description=f"Retry queued ({attempts}/{self.max_retries}) (Type B): {error[:60]}",
                    event_type="failed"
                )
            else:
                self.type_b_exhausted.add(name)
                self.type_b_last_run[name] = CLOCK.now()
                self.automation_service.update_status(
                    name=name,
                    status="Failed",
                    duration=duration_str,
                    last_output=f"Exceeded max retries ({attempts}/{self.max_retries}): {error}"
                )
                self.intraday_repo.add_report_run(
                    date=date,
                    report_name=name,
                    run=ReportRun(
                        started_at=started_at,
                        finished_at=CLOCK.formatted_now(),
                        result="failed",
                        duration=duration_str,
                        reason=f"Exceeded max retries ({attempts}/{self.max_retries}): {error}"
                    )
                )
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title=f"{name} permanently failed",
                    description=f"Exceeded max retries ({attempts}/{self.max_retries}) (Type B): {error[:60]}",
                    event_type="failed"
                )

        def _on_fail(name: str, duration_str: str, error: str):
            with self._lock:
                started_at = self.active_runs_type_b.pop(name, CLOCK.formatted_now())
                self.type_b_last_run[name] = CLOCK.now()
                log = ReportLog(name).from_json(default_stdout=error)
                if ReportLog.is_dependency_skip(log.status, error) or ReportLog.is_dependency_skip(log.status, log.last_output):
                    self.automation_service.update_status(
                        name=name,
                        status="Retrial",
                        duration=duration_str,
                        last_output=f"Skipped/Dependency unready: {log.last_output or log.reason or error}"
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Skipped {name}",
                        description="Dependency unready (Type B), will retry on next interval",
                        event_type="system"
                    )
                    return
                _handle_failure(name, started_at, duration_str, error)

        self.execution_service.execute_report(
            name=report_name,
            callback_good=_on_good,
            callback_fail=_on_fail
        )

    def _trigger_type_c_report(self, report_name: str, date: str):
        self.active_runs_type_c[report_name] = CLOCK.formatted_now()
        self.intraday_repo.add_timeline_event(
            date=date,
            title=f"Started {report_name}",
            description="Currently running (Type C)",
            event_type="start"
        )

        def _on_good(name: str, duration_str: str, output: str):
            with self._lock:
                started_at = self.active_runs_type_c.pop(name, CLOCK.formatted_now())
                log = ReportLog(name).from_json(default_stdout=output)

                if log.status == "Completed":
                    self.type_c_ran_today.add(name)
                    self.type_c_retry_after.pop(name, None)
                    self.retry_counts[name] = 0
                    self.intraday_repo.add_report_run(
                        date=date,
                        report_name=name,
                        run=ReportRun(
                            started_at=started_at,
                            finished_at=CLOCK.formatted_now(),
                            result="completed",
                            duration=duration_str,
                            reason=log.last_output
                        )
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Completed {name}",
                        description=f"Finished in {duration_str} (Type C)",
                        event_type="success"
                    )
                elif ReportLog.is_dependency_skip(log.status, log.last_output or output):
                    self.type_c_retry_after[name] = CLOCK.now() + timedelta(seconds=300)
                    self.automation_service.update_status(
                        name=name,
                        status="Retrial",
                        duration=duration_str,
                        last_output=f"Skipped/Dependency unready: {log.last_output}"
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Skipped {name}",
                        description="Dependency unready (Type C), will retry in 5m",
                        event_type="system"
                    )
                else:
                    _handle_failure(name, started_at, duration_str, log.last_output or "Execution did not complete successfully")

        def _handle_failure(name: str, started_at: str, duration_str: str, error: str):
            attempts = self.retry_counts.get(name, 0) + 1
            self.retry_counts[name] = attempts
            scheduler_is_active = self.lane_c_active or self.force_open

            if attempts < self.max_retries and scheduler_is_active:
                self.type_c_retry_after[name] = CLOCK.now() + timedelta(seconds=300)
                self.automation_service.update_status(
                    name=name,
                    status="Retrial",
                    duration=duration_str,
                    last_output=f"Error (attempt {attempts}/{self.max_retries}): {error}"
                )
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title=f"{name} encountered error",
                    description=f"Retry queued ({attempts}/{self.max_retries}) (Type C): {error[:60]}",
                    event_type="failed"
                )
            else:
                self.type_c_ran_today.add(name)
                self.type_c_retry_after.pop(name, None)
                self.automation_service.update_status(
                    name=name,
                    status="Failed",
                    duration=duration_str,
                    last_output=f"Exceeded max retries ({attempts}/{self.max_retries}): {error}"
                )
                self.intraday_repo.add_report_run(
                    date=date,
                    report_name=name,
                    run=ReportRun(
                        started_at=started_at,
                        finished_at=CLOCK.formatted_now(),
                        result="failed",
                        duration=duration_str,
                        reason=f"Exceeded max retries ({attempts}/{self.max_retries}): {error}"
                    )
                )
                self.intraday_repo.add_timeline_event(
                    date=date,
                    title=f"{name} permanently failed",
                    description=f"Exceeded max retries ({attempts}/{self.max_retries}) (Type C): {error[:60]}",
                    event_type="failed"
                )

        def _on_fail(name: str, duration_str: str, error: str):
            with self._lock:
                started_at = self.active_runs_type_c.pop(name, CLOCK.formatted_now())
                log = ReportLog(name).from_json(default_stdout=error)
                if ReportLog.is_dependency_skip(log.status, error) or ReportLog.is_dependency_skip(log.status, log.last_output):
                    self.type_c_retry_after[name] = CLOCK.now() + timedelta(seconds=300)
                    self.automation_service.update_status(
                        name=name,
                        status="Retrial",
                        duration=duration_str,
                        last_output=f"Skipped/Dependency unready: {log.last_output or log.reason or error}"
                    )
                    self.intraday_repo.add_timeline_event(
                        date=date,
                        title=f"Skipped {name}",
                        description="Dependency unready (Type C), will retry in 5m",
                        event_type="system"
                    )
                    return
                _handle_failure(name, started_at, duration_str, error)

        self.execution_service.execute_report(
            name=report_name,
            callback_good=_on_good,
            callback_fail=_on_fail
        )

    def trigger_manual_run(self, name: str) -> bool:
        """Triggers manual execution for a Type B or Type C report, strictly yielding to intraday open window."""
        report = self.automation_service.get_by_name(name)
        if (
            not report
            or report.report_type == "type_a"
            or getattr(report, "status", "") in ("Disabled", "Failed")
            or name in self.type_b_exhausted
        ):
            return False
        with self._lock:
            status = self.resolve_status()
            if status != Intraday.OPEN and not self.force_open:
                return False
            today_date = CLOCK.date_str()
            if report.report_type == "type_b":
                if name in self.active_runs_type_b:
                    return False
                self._trigger_type_b_report(name, today_date)
                return True
            elif report.report_type == "type_c":
                if name in self.active_runs_type_c:
                    return False
                self.type_c_retry_after.pop(name, None)
                self._trigger_type_c_report(name, today_date)
                return True
        return False

    def get_lanes_status(self) -> Dict[str, Any]:
        """Returns runtime execution metrics across all three scheduling lanes."""
        with self._lock:
            return {
                "type_a": {
                    "active": self.lane_a_active,
                    "running_count": len(self.current_runs),
                    "running_reports": list(self.current_runs.keys()),
                    "pending_count": len(self.waitlist),
                    "max_concurrent_run": self.max_concurrent_run,
                    "max_retries": self.max_retries
                },
                "type_b": {
                    "active": self.lane_b_active,
                    "running_count": len(self.active_runs_type_b),
                    "running_reports": list(self.active_runs_type_b.keys()),
                    "max_retries": self.max_retries
                },
                "type_c": {
                    "active": self.lane_c_active,
                    "running_count": len(self.active_runs_type_c),
                    "running_reports": list(self.active_runs_type_c.keys()),
                    "completed_today": list(self.type_c_ran_today),
                    "max_retries": self.max_retries
                }
            }

    def get_today_timeline(self) -> List[Dict]:
        day = self.intraday_repo.get_day(CLOCK.date_str())
        if day:
            return [t.to_dict() for t in day.timeline]
        return []

    def get_all_execution_history(self) -> List[Dict]:
        """Retrieves all historical execution run records across all dates, newest first."""
        with self._lock:
            data = self.intraday_repo._read_json()
            history = []
            for date, day_data in data.items():
                reports_ran = day_data.get("reports_ran", {})
                for report_name, run_data in reports_ran.items():
                    result = run_data.get("result", "completed")
                    status = "Completed" if result == "completed" else ("Failed" if result == "failed" else "Skipped")
                    history.append({
                        "id": f"{date}_{report_name}",
                        "date": date,
                        "report_name": report_name,
                        "started_at": run_data.get("started_at", "--"),
                        "finished_at": run_data.get("finished_at", "--"),
                        "duration": run_data.get("duration", "--"),
                        "status": status,
                        "reason": run_data.get("reason", "")
                    })
            history.sort(key=lambda x: (x["date"], x["started_at"]), reverse=True)
            return history

