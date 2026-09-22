"""
================================================================================
PARADISO — PRODUCTION REPORT BLUEPRINT (PYTHON)
================================================================================
Fully self-contained, standalone report script. No command-line arguments needed.

To configure for your report:
  1. Set REPORT_NAME below.
  2. Put your dependency checks in check_dependencies().
  3. Put your data reading, calculation, and saving logic in run_report().
Everything else (logging receipts, error catching, queue rotation) is automated.
================================================================================
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path
from datetime import datetime

# ==============================================================================
# 1. CONFIGURATION (Edit Here)
# ==============================================================================
REPORT_NAME = "Sample_Report_Blueprint"

# Automatic date determination (defaults to today's date YYYYMMDD)
TODAY = datetime.now().strftime("%Y%m%d")


# ==============================================================================
# 2. YOUR REPORT LOGIC (Edit Here)
# ==============================================================================
def check_dependencies() -> bool:
    """Check if upstream files, database tables, or prerequisite reports are ready.
    
    Return True  -> Dependencies ready, proceed to execute report.
    Return False -> Prerequisite not ready yet; Paradiso will rotate to the back
                    of the queue and retry later WITHOUT penalizing retry limits.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking upstream dependencies for date {TODAY}...")
    
    # --- Example checks you can adapt ---
    # upstream_file = Path(f"C:/datasets/raw_feed_{TODAY}.parquet")
    # return upstream_file.exists()
    
    return True  # Change to your real check


def run_report() -> str:
    """Your main report workload: extract, transform, and publish deliverables.
    
    Returns:
        A short summary message (e.g. '1,500 records processed') to log in Paradiso.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting data processing for {TODAY}...")
    
    # --- WRITE YOUR PANDAS / POLARS / SQL LOGIC HERE ---
    # Example:
    # df = pd.read_excel("input.xlsx")
    # summary = df.groupby("Team")["Amount"].sum()
    # summary.to_parquet(f"output_{TODAY}.parquet")
    
    total_records = 1500
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Publishing report outputs...")
    
    return f"Successfully processed {total_records} records for {TODAY}."


# ==============================================================================
# 3. PARADISO AUTOMATION ENGINE (Boilerplate — Do Not Modify)
# ==============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
PARADISO_LOGS = WORKSPACE_DIR / "paradiso" / "logs"
PARADISO_LOGS.mkdir(parents=True, exist_ok=True)
RECEIPT_FILE = PARADISO_LOGS / f"{REPORT_NAME}.json"

def _write_receipt(status: str, last_output: str, reason: str = "", duration: str = "--"):
    payload = {
        "name": REPORT_NAME,
        "status": status,
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": duration,
        "last_output": last_output,
        "reason": reason or last_output
    }
    try:
        with open(RECEIPT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as exc:
        print(f"[Warning] Failed to write receipt: {exc}", file=sys.stderr)

def main():
    start_time = time.time()
    print("=" * 60)
    print(f"Running: {REPORT_NAME} | Date: {TODAY}")
    print("=" * 60)

    try:
        # Step 1: Upstream Dependency Check
        if not check_dependencies():
            skip_msg = f"SKIPPED: Missing dependency for {REPORT_NAME} on {TODAY} (waiting for upstream data)"
            print(f"[*] {skip_msg}")
            _write_receipt(
                status="Retrial",
                last_output=skip_msg,
                reason="Dependencies not yet available. Re-queued for queue rotation.",
                duration=f"{time.time() - start_time:.1f}s"
            )
            sys.exit(0)

        # Step 2: Run Report
        summary_msg = run_report()

        # Step 3: Success Completion
        elapsed = f"{time.time() - start_time:.1f}s"
        full_msg = f"{REPORT_NAME} completed in {elapsed}. {summary_msg}"
        print(f"[+] {full_msg}")
        _write_receipt(
            status="Completed",
            last_output=full_msg,
            reason="Execution completed successfully",
            duration=elapsed
        )
        sys.exit(0)

    except Exception as exc:
        # Step 4: Error Handling
        elapsed = f"{time.time() - start_time:.1f}s"
        err_msg = f"FAILED: Unhandled exception in {REPORT_NAME}: {str(exc)}"
        print(f"[-] {err_msg}", file=sys.stderr)
        traceback.print_exc()
        _write_receipt(
            status="Failed",
            last_output=err_msg,
            reason=traceback.format_exc(),
            duration=elapsed
        )
        sys.exit(1)

if __name__ == "__main__":
    main()
