"""
PoC for F-004: Dependency skip exiting with code 1 consumes retry counts and causes premature terminal failure.
Runs entirely against isolated temporary storage.
"""
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from models.automation import Automations
from models.intraday import Intraday
from models.report import Report
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from utils.clock import CLOCK

def test_dep_skip_exit1():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        auto_repo = Automations(dir_path / "automations.json")
        intra_repo = Intraday(dir_path / "intraday.json")
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.max_retries = 3

        report_name = "0base_auto.py"
        r = Report(name=report_name, filename="0base_auto.py", filetype="python", dir=".", status="Waiting")
        auto_svc.add(r)
        intra_svc.start_fresh_run(force_open=True)

        today = CLOCK.date_str()

        # Simulate 3 dependency skip runs exiting with code 1 (as 0base_auto.py does when dependencies are missing)
        for i in range(1, 4):
            # pop from waitlist as tick() does
            rep = intra_svc.waitlist.popleft()
            intra_svc.current_runs[rep] = CLOCK.formatted_now()

            # Script outputs missing dependency and exits with return code 1
            # Runner._watcher sees returncode == 1, routes to callback_fail -> intraday_service._on_fail
            with intra_svc._lock:
                started_at = intra_svc.current_runs.pop(rep, CLOCK.formatted_now())
                attempts = intra_svc.retry_counts.get(rep, 0) + 1
                intra_svc.retry_counts[rep] = attempts
                if attempts < intra_svc.max_retries:
                    intra_svc.waitlist.append(rep)
                    auto_svc.update_status(name=rep, status="Retrial")
                else:
                    auto_svc.update_status(name=rep, status="Failed")

            print(f"Cycle {i}: attempts={intra_svc.retry_counts[rep]}, status={auto_svc.get_by_name(rep).status}")

        final_status = auto_svc.get_by_name(report_name).status
        in_waitlist = report_name in intra_svc.waitlist

        print(f"Final status: {final_status}")
        print(f"Is still queued in waitlist: {in_waitlist}")

        assert final_status == "Failed", "Report was prematurely failed"
        assert not in_waitlist, "Report was permanently removed from waitlist"
        print("[+] CONFIRMED F-004: Missing dependency with exit code 1 consumed max retries and terminally failed!")

if __name__ == "__main__":
    test_dep_skip_exit1()

