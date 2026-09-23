"""
Adversarial verification script for F-006 (Process Watcher Suppression) and F-008 (Windows Process Tree Termination).
Tests deep process trees (grandchild), address/name reuse, and graceful handling of dead PIDs.
"""
import sys
import time
import subprocess
import unittest
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from services.runner import Runner

class TestF006F008AdversarialVerification(unittest.TestCase):
    def setUp(self):
        self.runner = Runner()

    def test_f006_same_name_after_kill_not_suppressed(self):
        """Attacks F-006: process killed, then new process with identical name completes."""
        report_name = "Rapid_Recycle_Report"
        good_fired = []
        fail_fired = []

        def on_good(dur, out): good_fired.append(out)
        def on_fail(dur, err): fail_fired.append(err)

        # 1. Spawn Process 1
        p1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        with self.runner._proc_lock:
            self.runner._exec_counter += 1
            exec_id_1 = self.runner._exec_counter
            p1._exec_id = exec_id_1
            p1._was_killed = False
            self.runner.active_processes[report_name] = p1

        # Kill Process 1
        self.runner.kill_all()
        self.assertTrue(getattr(p1, "_was_killed", False))
        self.assertIn(exec_id_1, self.runner.killed_exec_ids)

        # Watcher for P1 runs
        self.runner._watcher(report_name, p1, time.time(), on_good, on_fail, exec_id_1)
        self.assertEqual(len(good_fired), 0, "Killed process P1 must be suppressed")
        self.assertEqual(len(fail_fired), 0, "Killed process P1 must be suppressed")

        # 2. Spawn Process 2 with the EXACT same name
        p2 = subprocess.Popen([sys.executable, "-c", "print('P2 SUCCESS', flush=True)"], stdout=subprocess.PIPE, text=True)
        with self.runner._proc_lock:
            self.runner._exec_counter += 1
            exec_id_2 = self.runner._exec_counter
            p2._exec_id = exec_id_2
            p2._was_killed = False
            self.runner.active_processes[report_name] = p2

        # P2 completes
        self.runner._watcher(report_name, p2, time.time(), on_good, on_fail, exec_id_2)
        if p2.stdout:
            p2.stdout.close()

        self.assertEqual(len(good_fired), 1, "Process P2 callback MUST fire despite matching name of killed process")
        self.assertIn("P2 SUCCESS", good_fired[0])

    def test_f008_deep_process_tree_eliminated(self):
        """Attacks F-008: parent spawns child, child spawns grandchild. All must die on kill_all()."""
        if sys.platform != "win32":
            self.skipTest("Windows taskkill tree-kill test is win32 specific.")

        with tempfile.TemporaryDirectory() as td:
            # Script that creates a 3-tier process tree: Parent -> Child -> Grandchild
            grandchild_code = "import time; time.sleep(60)"
            child_code = (
                f"import subprocess, sys, time\n"
                f"gc = subprocess.Popen([sys.executable, '-c', '{grandchild_code}'])\n"
                f"print('GC_PID:' + str(gc.pid), flush=True)\n"
                f"time.sleep(60)\n"
            )
            parent_code = (
                f"import subprocess, sys, time\n"
                f"c = subprocess.Popen([sys.executable, '-c', {repr(child_code)}], stdout=subprocess.PIPE, text=True)\n"
                f"line = c.stdout.readline()\n"
                f"print('CHILD_PID:' + str(c.pid) + ',' + line.strip(), flush=True)\n"
                f"time.sleep(60)\n"
            )

            parent_file = Path(td) / "parent_tree.py"
            parent_file.write_text(parent_code, encoding="utf-8")

            proc = subprocess.Popen(
                [sys.executable, str(parent_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self.runner.active_processes["deep_tree"] = proc

            # Read Child and Grandchild PIDs
            line = proc.stdout.readline()
            self.assertIn("CHILD_PID:", line)
            parts = line.split("CHILD_PID:")[1].split(",")
            child_pid = int(parts[0].strip())
            gc_pid = int(parts[1].split("GC_PID:")[1].strip())
            parent_pid = proc.pid

            print(f"Parent PID: {parent_pid}, Child PID: {child_pid}, Grandchild PID: {gc_pid}")

            # Execute kill_all
            self.runner.kill_all()
            time.sleep(0.5)

            if proc.stdout: proc.stdout.close()
            if proc.stderr: proc.stderr.close()

            # Verify Parent, Child, and Grandchild are all DEAD
            for pid_name, pid_val in [("Parent", parent_pid), ("Child", child_pid), ("Grandchild", gc_pid)]:
                check = subprocess.run(["tasklist", "/FI", f"PID eq {pid_val}"], capture_output=True, text=True)
                is_alive = str(pid_val) in check.stdout
                self.assertFalse(is_alive, f"{pid_name} PID {pid_val} survived kill_all()!")

    def test_kill_all_handles_already_exited_process_gracefully(self):
        """Attacks kill_all with already-terminated processes and non-existent PIDs."""
        p_dead = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
        p_dead.wait()

        self.runner.active_processes["dead_proc"] = p_dead
        # Must not raise an exception or crash
        try:
            self.runner.kill_all()
        except Exception as e:
            self.fail(f"kill_all raised an unhandled exception on already-dead process: {e}")

if __name__ == "__main__":
    unittest.main()
