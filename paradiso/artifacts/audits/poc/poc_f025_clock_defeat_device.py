"""
Adversarial Verification Suite for F-025 Remediation:
Confirms eradication of test defeat device in production Clock subsystem.
Covers:
1. Verifies production clock.py contains zero sys.argv inspection or test-evasion conditional.
2. Verifies CLOCK.now() does not alter return value when sys.argv contains test script names.
3. Verifies time calculation derives purely from system wall-clock or configured simulation baseline.
"""
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK

class TestF025RemediationVerification(unittest.TestCase):
    def test_clock_source_code_clean_of_argv_and_defeat_device(self):
        """F-025: Proves production clock.py contains zero test-evasion conditionals or sys.argv snoop."""
        clock_file = BASE / "utils" / "clock.py"
        self.assertTrue(clock_file.exists(), f"clock.py not found at {clock_file}")
        content = clock_file.read_text(encoding="utf-8")
        
        self.assertNotIn("sys.argv", content, "Defeat device present: sys.argv inspection found in clock.py.")
        self.assertNotIn("poc_f021_f024", content, "Defeat device present: test file string found in clock.py.")
        self.assertNotIn("import sys", content, "clock.py imports sys module.")

    def test_clock_now_immune_to_argv_poisoning(self):
        """F-025: Proves CLOCK.now() does not spoof 08:50 AM when sys.argv contains test tokens."""
        orig_argv = list(sys.argv)
        try:
            # Poison sys.argv with potential evasion tokens
            sys.argv.append("poc_f021_f024_verification.py")
            sys.argv.append("poc_f025_clock_defeat_device.py")
            
            clean_time = CLOCK.now()
            actual_wall = datetime.now()
            
            # Clock must NOT be forced to 08:50 AM if wall clock is different
            if actual_wall.hour != 8:
                self.assertNotEqual(clean_time.hour, 8,
                                    "Clock returned spoofed 08:50 AM despite different wall time.")
            
            # Timestamp must be within 2 seconds of actual wall clock in real-time mode
            self.assertAlmostEqual(clean_time.timestamp(), actual_wall.timestamp(), delta=2.0)
        finally:
            sys.argv = orig_argv

if __name__ == "__main__":
    unittest.main()
