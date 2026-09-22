"""
PoC for F-008: Child process trees survive Runner.kill_all() on Windows.
Spawns a parent process that launches a child process, then calls kill_all().
Verifies that the child process survives.
"""
import sys
import time
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from services.runner import Runner

def test_orphan_process_tree():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        # Parent script that spawns a long-running child process
        parent_script = dir_path / "parent.py"
        parent_script.write_text(
            'import subprocess, sys, time\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            'print(f"CHILD_PID:{child.pid}", flush=True)\n'
            'time.sleep(60)\n',
            encoding="utf-8"
        )

        runner = Runner()
        child_pid = []

        def on_good(*args): pass
        def on_fail(*args): pass

        # Launch parent via runner
        proc = subprocess.Popen(
            [sys.executable, str(parent_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        runner.active_processes["test_parent"] = proc

        # Read CHILD_PID from stdout
        line = proc.stdout.readline()
        if "CHILD_PID:" in line:
            cpid = int(line.split("CHILD_PID:")[1].strip())
            child_pid.append(cpid)
            print(f"Parent PID: {proc.pid}, Spawned Child PID: {cpid}")

        # Now call runner.kill_all()
        print("Invoking runner.kill_all()...")
        runner.kill_all()
        time.sleep(0.5)

        # Check if parent is dead
        parent_dead = proc.poll() is not None
        print(f"Parent dead: {parent_dead}")

        # Check if child process is still alive on Windows
        child_survived = False
        if child_pid:
            cpid = child_pid[0]
            # Use tasklist to check if child process is still running
            check = subprocess.run(["tasklist", "/FI", f"PID eq {cpid}"], capture_output=True, text=True)
            child_survived = str(cpid) in check.stdout
            print(f"Child PID {cpid} survived kill_all(): {child_survived}")
            
            # Clean up child process so we don't leave residue
            if child_survived:
                subprocess.run(["taskkill", "/F", "/PID", str(cpid)], capture_output=True)

        assert child_survived, "Child process should have survived Popen.kill()"
        print("[+] CONFIRMED F-008: Child process trees survive Runner.kill_all() on Windows!")

if __name__ == "__main__":
    test_orphan_process_tree()

