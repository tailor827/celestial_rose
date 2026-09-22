import time
import threading
from datetime import datetime, timedelta

class Clock:
    """Encapsulates system time and test time simulation for Paradiso Alter."""
    def __init__(self, simulation_mode: bool = True, speed_multiplier: float = 600.0):
        self._lock = threading.RLock()
        self.simulation_mode = simulation_mode
        self.speed_multiplier = speed_multiplier  # 600.0x = 10 simulated minutes per 1 real second
        self._reset_sim_baseline_unlocked()

    def _reset_sim_baseline_unlocked(self):
        self.start_real_time = time.time()
        now_dt = datetime.now()
        # Start simulation at 00:00:00 midnight of current day
        self.start_sim_time = datetime(now_dt.year, now_dt.month, now_dt.day, 0, 0, 0)

    def _reset_sim_baseline(self):
        with self._lock:
            self._reset_sim_baseline_unlocked()

    def set_speed(self, multiplier: float):
        with self._lock:
            current_sim = self._get_sim_now()
            self.start_real_time = time.time()
            self.start_sim_time = current_sim
            self.speed_multiplier = multiplier

    def set_simulation_mode(self, enabled: bool):
        with self._lock:
            if self.simulation_mode != enabled:
                self.simulation_mode = enabled
                self._reset_sim_baseline_unlocked()

    def reset_simulation(self):
        with self._lock:
            self._reset_sim_baseline_unlocked()

    def _get_sim_now(self) -> datetime:
        if not self.simulation_mode or self.speed_multiplier <= 1.0:
            return datetime.now()
        
        elapsed_real = time.time() - self.start_real_time
        elapsed_sim_seconds = elapsed_real * self.speed_multiplier
        return self.start_sim_time + timedelta(seconds=elapsed_sim_seconds)

    def now(self) -> datetime:
        with self._lock:
            return self._get_sim_now()

    def time_str(self) -> str:
        return self.now().strftime("%I:%M %p")

    def time_24_str(self) -> str:
        return self.now().strftime("%H:%M")

    def date_str(self) -> str:
        return self.now().strftime("%Y%m%d")

    def formatted_date(self) -> str:
        return self.now().strftime("%Y-%m-%d")

    def formatted_now(self) -> str:
        return self.now().strftime("%Y-%m-%d %I:%M:%S %p")

from utils.config import CONFIG

_sim_cfg = CONFIG.get("simulation", {})
CLOCK = Clock(
    simulation_mode=_sim_cfg.get("enabled", True),
    speed_multiplier=float(_sim_cfg.get("speed_multiplier", 600.0))
)

