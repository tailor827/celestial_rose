"""
Adversarial Verification Suite Runner — Paradiso Alter
Executes all 8 active adversarial PoC verification test suites sequentially and reports unified status.
"""
import sys
import time
import subprocess
from pathlib import Path

POC_DIR = Path(__file__).resolve().parent

VERIFICATION_SCRIPTS = [
    ("BG-001/BG-002", "poc_bg001_bg002_verification.py", "Idle 409 guard, 25-thread burst mutex, 10s throttle"),
    ("F-001", "poc_f001_verification.py", "Active deletion 409 guard & missing queue recovery"),
    ("F-002", "poc_f002_verification.py", "Path traversal defense (14 attack vectors rejected)"),
    ("F-003", "poc_f003_verification.py", "Executable path whitelist & host execution rejection"),
    ("F-004", "poc_f004_verification.py", "Section 12 receipt contract & retry counter non-consumption"),
    ("F-006/F-008", "poc_f006_f008_verification.py", "Monotonic PID heap reuse & Windows 3-tier tree kill"),
    ("F-007", "poc_f007_verification.py", "Storage corruption backup deduplication & 5-backup cap"),
    ("F-010", "poc_f010_verification.py", "22:00 cutoff termination & pre-existing day rollover"),
    ("F-021..F-024", "poc_f021_f024_verification.py", "Receipt discovery, Lane B/C skip throttle, 409 guard, 400 lane check"),
    ("F-025", "poc_f025_clock_defeat_device.py", "Clock sys.argv defeat device inspection and bypass proof"),
    ("F-026", "poc_f026_out_of_window_stall.py", "Out-of-window lane start stall vs manual run 409 divergence"),
    ("F-028", "poc_f028_preexisting_day_paralysis.py", "Pre-existing closed day record in storage cleansed on boot"),
    ("F-029", "poc_f029_lane_c_reboot_duplication.py", "Mid-day reboot hydrates Lane C timeslots preventing duplicate runs"),
    ("F-031", "poc_f031_cold_boot_lane_c_leak.py", "Cold boot automations leak into type_c_ran_today suppressing runs"),
    ("F-032", "poc_f032_f028_fragile_string_paralysis.py", "Fragile string check bypass in _get_or_init_day causing queue paralysis"),
    ("F-033", "poc_f033_sticky_force_open_cutoff_bypass.py", "Sticky force_open bypassing 22:00 cutoff and mutating rollover state"),
    ("F-034", "poc_f034_delete_active_report_orphaning.py", "Active Type B/C report deletion leaving orphaned process and runs"),
]

def main():
    print("=" * 80)
    print("PARADISO ALTER — ADVERSARIAL VERIFICATION SUITE")
    print(f"Target Directory: {POC_DIR}")
    print(f"Interpreter:      {sys.executable}")
    print("=" * 80)

    total_start = time.time()
    results = []
    any_failed = False

    for target_id, script_name, description in VERIFICATION_SCRIPTS:
        script_path = POC_DIR / script_name
        if not script_path.exists():
            print(f"[-] ERROR: Script {script_name} not found!")
            results.append((target_id, script_name, "MISSING", 0.0))
            any_failed = True
            continue

        print(f"\n>>> Running {target_id}: {script_name}...")
        print(f"    Description: {description}")
        t0 = time.time()
        res = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True)
        dur = time.time() - t0

        if res.returncode == 0:
            print(f"    [+] PASS ({dur:.2f}s)")
            results.append((target_id, script_name, "PASS", dur))
        else:
            print(f"    [-] FAIL (code {res.returncode}, {dur:.2f}s)")
            if res.stdout:
                print("--- STDOUT ---")
                print(res.stdout.strip())
            if res.stderr:
                print("--- STDERR ---")
                print(res.stderr.strip())
            results.append((target_id, script_name, "FAIL", dur))
            any_failed = True

    total_dur = time.time() - total_start
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    print(f"{'Finding':<14} {'Script':<35} {'Result':<10} {'Duration'}")
    print("-" * 80)
    for target_id, script_name, status, dur in results:
        status_str = "[+] PASS" if status == "PASS" else "[-] " + status
        print(f"{target_id:<14} {script_name:<35} {status_str:<10} {dur:.2f}s")
    print("=" * 80)
    passed_count = sum(1 for _, _, s, _ in results if s == "PASS")
    total_count = len(results)
    print(f"Final Result: {passed_count}/{total_count} suites passed in {total_dur:.2f}s")

    if any_failed:
        print("[-] One or more adversarial verification suites FAILED!")
        sys.exit(1)
    else:
        print("[+] All adversarial verification suites PASSED without defect.")
        sys.exit(0)

if __name__ == "__main__":
    main()
