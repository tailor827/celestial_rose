import time
import random
import sys
import json
from pathlib import Path
from datetime import datetime

SCRIPT_NAME = "Agency_Performance"
FAILURE_CHANCE = 0.50

REPORTS_DIR = Path(__file__).resolve().parent
LOGS_DIR = REPORTS_DIR.parent / "paradiso_alter" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / f"{SCRIPT_NAME}.json"

print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting {SCRIPT_NAME} execution...")

# Simulate 30% random failure
if random.random() < FAILURE_CHANCE:
    msg = f"FAILED: Connection timeout / database error during {SCRIPT_NAME} processing."
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump({
            "name": SCRIPT_NAME,
            "status": "Failed",
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_output": msg,
            "reason": msg
        }, f, indent=2)
    sys.exit(1)

duration = random.randint(10, 30)
print(f"[*] Dependencies ready! Simulating report workload for {duration} seconds...")
time.sleep(duration)

msg = f"{SCRIPT_NAME} completed successfully in {duration}s!"
print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
with open(log_file, "w", encoding="utf-8") as f:
    json.dump({
        "name": SCRIPT_NAME,
        "status": "Completed",
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": f"{duration}s",
        "last_output": msg,
        "reason": msg
    }, f, indent=2)

sys.exit(0)
