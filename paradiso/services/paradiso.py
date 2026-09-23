import time
import threading
from typing import Optional, Tuple
from services.intraday_service import IntradayService
from utils.config import CONFIG
from utils.clock import CLOCK

class TransitionResult:
    """Structured result for scheduler lifecycle transitions with boolean backward-compatibility."""
    def __init__(self, ok: bool, status: str, remaining: float = 0.0):
        self.ok = ok
        self.status = status
        self.remaining = remaining

    def __bool__(self) -> bool:
        return self.ok

    def __iter__(self):
        return iter((self.ok, self.status, self.remaining))

class Paradiso:
    """Daemon scheduler engine for Paradiso."""
    def __init__(self, intraday_service: IntradayService, interval: Optional[float] = None):
        self.intraday_service = intraday_service
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._custom_interval = interval
        self._lifecycle_lock = threading.RLock()
        self.transition_cooldown: float = 10.0
        self._last_transition_time: float = 0.0
        self._override_cooldown: Optional[float] = None

    @property
    def interval(self) -> float:
        if self._custom_interval is not None:
            return self._custom_interval
        # Fast 0.5s tick when time simulation is enabled; configured seconds when in realtime
        if CLOCK.simulation_mode:
            return 0.5
        return float(CONFIG.get("scheduler", {}).get("job_interval_seconds", 15.0))

    @interval.setter
    def interval(self, val: float) -> None:
        self._custom_interval = val

    def get_tick_interval(self) -> float:
        return self.interval

    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def get_effective_cooldown(self) -> float:
        if self._override_cooldown is not None:
            return self._override_cooldown
        return self.transition_cooldown

    def get_cooldown_remaining(self) -> float:
        cooldown = self.get_effective_cooldown()
        if cooldown <= 0:
            return 0.0
        elapsed = time.time() - self._last_transition_time
        remaining = cooldown - elapsed
        return max(0.0, remaining)

    def start_daemon(self, check_cooldown: bool = False) -> TransitionResult:
        """Starts daemon thread for automatic time window monitoring without force_open override."""
        with self._lifecycle_lock:
            if self.is_running():
                return TransitionResult(True, "already_running", 0.0)

            if check_cooldown:
                remaining = self.get_cooldown_remaining()
                if remaining > 0:
                    return TransitionResult(False, "cooldown", remaining)

            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            self._last_transition_time = time.time()
            return TransitionResult(True, "started", 0.0)

    def start(self, check_cooldown: bool = False) -> TransitionResult:
        """Initiates fresh intraday run and starts the daemon loop."""
        with self._lifecycle_lock:
            if self.is_running():
                return TransitionResult(False, "already_running", 0.0)

            if check_cooldown:
                remaining = self.get_cooldown_remaining()
                if remaining > 0:
                    return TransitionResult(False, "cooldown", remaining)

            # Only initiate fresh run when transitioning from stopped -> started
            self.intraday_service.start_fresh_run()
            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            self._last_transition_time = time.time()
            return TransitionResult(True, "started", 0.0)

    def stop(self, check_cooldown: bool = False) -> TransitionResult:
        """Pauses scheduler execution, terminates active subprocesses, and joins daemon thread."""
        with self._lifecycle_lock:
            if not self.is_running():
                return TransitionResult(False, "not_running", 0.0)

            if check_cooldown:
                remaining = self.get_cooldown_remaining()
                if remaining > 0:
                    return TransitionResult(False, "cooldown", remaining)

            self._stop_event.set()
            self.intraday_service.stop_scheduler()

            # Synchronously join dying thread so it cannot become a zombie
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            self._last_transition_time = time.time()
            return TransitionResult(True, "stopped", 0.0)

    def _loop(self):
        stop_evt = self._stop_event
        while not stop_evt.is_set():
            try:
                self.intraday_service.tick()
            except Exception as e:
                print(f"[Paradiso Scheduler Error]: {e}")
            stop_evt.wait(timeout=self.interval)
