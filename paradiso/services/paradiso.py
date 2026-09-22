import time
import threading
from typing import Optional
from services.intraday_service import IntradayService
from utils.config import CONFIG

from utils.clock import CLOCK

class Paradiso:
    """Daemon scheduler engine for Paradiso Alter."""
    def __init__(self, intraday_service: IntradayService, interval: Optional[float] = None):
        self.intraday_service = intraday_service
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._custom_interval = interval

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
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def start_daemon(self) -> bool:
        """Starts daemon thread for automatic time window monitoring without force_open override."""
        if self.is_running():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def start(self) -> bool:
        self.intraday_service.start_fresh_run()
        if self.is_running():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        self._stop_event.set()
        self.intraday_service.stop_scheduler()
        self._thread = None
        return True

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.intraday_service.tick()
            except Exception as e:
                print(f"[Paradiso Scheduler Error]: {e}")
            self._stop_event.wait(timeout=self.interval)
