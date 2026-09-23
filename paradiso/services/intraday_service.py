import time
import threading
from collections import deque
from typing import List, Dict, Optional, Set
from models.intraday import Intraday, IntradayDay, ReportRun, TimelineEvent
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from utils.clock import CLOCK
from utils.config import CONFIG

class IntradayService:
    """Decoupled thread-safe intraday queue manager with automated queue rotation for retries."""
    def __init__(self, automation_service: AutomationService, execution_service: ExecutionService):
        self.intraday_repo = Intraday()
        self.automation_service = automation_service
        self.execution_service = execution_service
        
        self.start_time = CONFIG.get("scheduler", {}).get("intraday_start_time", "07:00")
        self.idle_time = CONFIG.get("scheduler", {}).get("intraday_idle_time", "21:00")
        self.close_time = CONFIG.get("scheduler", {}).get("intraday_close_time", "22:00")
        self.max_retries = int(CONFIG.get("scheduler", {}).get("max_retries", 3))
        self.retry_counts: Dict[str, int] = {}

        self._lock = threading.RLock()
        self.waitlist: deque = deque()
        self.current_runs: Dict[str, str] = {} # report_name -> started_at
        self.day_closed: bool = False
        self.is_active: bool = False
        self.force_open: bool = False
        self._active_date: str = CLOCK.date_str()

        # Queue pass tracking and starvation cooldown (F-005)
        self._cycle_pass_reports: Set[str] = set()
        self._cycle_seen_in_pass: Set[str] = set()
        self._cycle_completions_in_pass: int = 0
        self._cycle_skips_in_pass: int = 0
        self._cycle_errors_in_pass: int = 0
        self._rotation_cooldown_until: float = 0.0
        self._last_rotation_logged: Dict[str, float] = {}
        self.rotation_cooldown_seconds: float = float(CONFIG.get("scheduler", {}).get("rotation_cooldown_seconds", 30.0))

    def reload_config(self, cfg: Optional[dict] = None) -> None:
        """Dynamically reloads time window thresholds from configuration."""
        c = cfg or CONFIG
        sched = c.get("scheduler", {})
        with self._lock:
            self.start_time = sched.get("intraday_start_time", self.start_time)
            self.idle_time = sched.get("intraday_idle_time", self.idle_time)
            self.close_time = sched.get("intraday_close_time", self.close_time)
            self.max_retries = int(sched.get("max_retries", self.max_retries))
            self.rotation_cooldown_seconds = float(sched.get("rotation_cooldown_seconds", self.rotation_cooldown_seconds))

    def get_rotation_cooldown(self) -> float:
        """Returns cooldown delay in seconds. Respects testing overrides and simulation scaling."""
        if hasattr(self, "_override_cooldown") and self._override_cooldown is not None:
            return self._override_cooldown
        if CLOCK.simulation_mode:
            return 5.0
        return self.rotation_cooldown_seconds

    def _evaluate_pass_completion(self, date: str):
        """Checks if a full pass over all waiting reports has completed, engaging cooldown if all were skipped."""
        if self._cycle_pass_reports and self._cycle_pass_reports.issubset(self._cycle_seen_in_pass):
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
            # Reset pass tracking for the next pass
            self._cycle_pass_reports = set(self.waitlist)
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

    def resolve_status(self) -> str:
        if self.force_open:
            return Intraday.OPEN
        t = CLOCK.time_24_str()
        if t < self.start_time:
            return Intraday.WAITING_TO_OPEN
        elif t < self.idle_time:
            return Intraday.OPEN
        elif t < self.close_time:
            return Intraday.WAITING_TO_CLOSE
        else:
            return Intraday.CLOSED

    def start_fresh_run(self, force_open: bool = False):
        with self._lock:
            self.is_active = True
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
            day = self.intraday_repo.get_day(today_date)
            if not day:
                # Cold boot on a new day: reset all non-disabled reports to Waiting and initialize day record
                waiting = self.automation_service.set_waiting_all()
                day = IntradayDay(
                    date=today_date,
                    status=status,
                    expected_reports=waiting,
                    reports_ran={},
                    timeline=[TimelineEvent(
                        timestamp=CLOCK.time_str(),
                        title="Day Initialized",
                        description=f"Paradiso day initialized for {today_date} (All reports reset to Waiting)",
                        type="system"
                    )]
                )
                self.intraday_repo.add_day(day)
                queue_items = waiting
            else:
                if day.status != status:
                    self.intraday_repo.update_status(today_date, status)
                pending = self.automation_service.get_pending()
                already_ran = set(day.reports_ran.keys())
                queue_items = [r for r in pending if r not in already_ran and r not in self.current_runs]

            self.waitlist = deque(queue_items)
            self.day_closed = False
            self._rotation_cooldown_until = 0.0
            self._cycle_pass_reports = set(self.waitlist)
            self._cycle_seen_in_pass.clear()
            self._cycle_completions_in_pass = 0
            self._last_rotation_logged.clear()
            self.intraday_repo.add_timeline_event(
                date=today_date,
                title="Scheduler started",
                description=f"Sequential queue execution initiated for {len(self.waitlist)} pending report(s)",
                event_type="system"
            )

    def stop_scheduler(self):
        """Pauses scheduler execution, terminates active subprocesses, and logs stop event."""
        with self._lock:
            self.is_active = False
            self.force_open = False
            self.waitlist.clear()
            self._rotation_cooldown_until = 0.0
            self._cycle_pass_reports.clear()
            self._cycle_seen_in_pass.clear()
            self._cycle_completions_in_pass = 0
            self._last_rotation_logged.clear()

            # Terminate active running subprocesses & reset their statuses in automation service
            self.execution_service.runner.kill_all()
            for report_name in list(self.current_runs.keys()):
                self.automation_service.update_status(
                    name=report_name,
                    status="Waiting",
                    duration="0s",
                    last_output="Stopped by user"
                )
            self.current_runs.clear()

            today_date = CLOCK.date_str()
            self.intraday_repo.add_timeline_event(
                date=today_date,
                title="Scheduler stopped",
                description="Queue execution paused by user; active runs terminated",
                event_type="system"
            )

    def reset_all_reports(self):
        """Resets all scheduled reports to Waiting, kills running processes, and sets scheduler to Standby."""
        with self._lock:
            self.is_active = False
            self.force_open = False
            self.waitlist.clear()
            self.retry_counts.clear()
            self._rotation_cooldown_until = 0.0
            self._cycle_pass_reports.clear()
            self._cycle_seen_in_pass.clear()
            self._cycle_completions_in_pass = 0
            self._last_rotation_logged.clear()

            # Kill any active processes and clear current_runs
            self.execution_service.runner.kill_all()
            self.current_runs.clear()

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
            is_new_day = (today_date != self._active_date)

            if not day or is_new_day:
                self._active_date = today_date
                # Reconcile past days upon crossing midnight
                self._reconcile_past_days(today_date)

                # F-010 Defense-in-depth: Ensure zero lingering processes or runs cross into the new day
                if self.current_runs:
                    self.execution_service.runner.kill_all()
                    for r_name in list(self.current_runs.keys()):
                        self.automation_service.update_status(
                            name=r_name,
                            status="Failed",
                            last_output="Forcibly terminated at midnight rollover"
                        )
                    self.current_runs.clear()

                self.retry_counts.clear()
                self.waitlist.clear()

                waiting = self.automation_service.set_waiting_all()
                if not day:
                    day = IntradayDay(
                        date=today_date,
                        status=status,
                        expected_reports=waiting,
                        reports_ran={},
                        timeline=[TimelineEvent(
                            timestamp=CLOCK.time_str(),
                            title="Day Initialized",
                            description=f"Paradiso day initialized for {today_date} (All reports reset to Waiting)",
                            type="system"
                        )]
                    )
                    self.intraday_repo.add_day(day)
                else:
                    if day.status != status:
                        self.intraday_repo.update_status(today_date, status)
                    self.intraday_repo.add_timeline_event(
                        date=today_date,
                        title="Day Initialized",
                        description=f"Paradiso day initialized for {today_date} (All reports reset to Waiting)",
                        event_type="system"
                    )

                if self.is_active:
                    self.waitlist = deque(waiting)
                self.day_closed = False
            else:
                if day.status != status:
                    self.intraday_repo.update_status(today_date, status)
                
                # Reconcile waitlist deck during WAITING_TO_OPEN or OPEN if scheduler is active
                if self.is_active and status in [Intraday.WAITING_TO_OPEN, Intraday.OPEN]:
                    already_ran = set(day.reports_ran.keys())
                    uncompleted = [r for r in day.expected_reports if r not in already_ran and r not in self.current_runs]
                    for r in uncompleted:
                        if r not in self.waitlist:
                            self.waitlist.append(r)

            # Do not schedule or process queue if in Standby
            if not self.is_active:
                return

            # End of day cutoff logic at 22:00 (CLOSED)
            if status == Intraday.CLOSED:
                if not self.day_closed:
                    self.day_closed = True
                    self._close_day(today_date)
                return
            else:
                self.day_closed = False

            # WAITING_TO_CLOSE (21:00 - 22:00): Do not pop new reports, wait for in-flight processes
            if status == Intraday.WAITING_TO_CLOSE:
                return

            # OPEN window (07:00 - 21:00): Sequential queue execution (1 by 1)
            if status == Intraday.OPEN and len(self.current_runs) == 0 and len(self.waitlist) > 0:
                if time.time() < self._rotation_cooldown_until:
                    return
                next_report = self.waitlist.popleft()
                self._trigger_report(next_report, today_date)

    def _close_day(self, date: str):
        """Terminate lingering processes and mark remaining uncompleted reports as failed at 10:00 PM cutoff."""
        self.execution_service.runner.kill_all()
        running_reports = set(self.current_runs.keys())
        self.current_runs.clear()

        day = self.intraday_repo.get_day(date)
        already_ran = set(day.reports_ran.keys()) if day else set()
        all_reports = self.automation_service.get_all()

        for r in all_reports:
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
        self.intraday_repo.add_timeline_event(
            date=date,
            title="Paradiso closed",
            description="Intraday execution window closed at 10:00 PM; all running tasks forcibly killed and uncompleted reports logged as Failed",
            event_type="system"
        )

    def _trigger_report(self, report_name: str, date: str):
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
                    scheduler_is_active = self.is_active or self.force_open
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
            scheduler_is_active = self.is_active or self.force_open
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
                scheduler_is_active = self.is_active or self.force_open

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

