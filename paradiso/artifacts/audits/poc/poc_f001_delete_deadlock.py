"""
PoC for F-001: Deleting an active executing report causes permanent scheduler queue deadlock.
Runs entirely against isolated temporary storage.
"""
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from collections import deque
from models.automation import Automations
from models.intraday import Intraday, IntradayDay
from models.report import Report
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from utils.clock import CLOCK

def reproduce():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        auto_repo = Automations(dir_path / "automations.json")
        intra_repo = Intraday(dir_path / "intraday.json")
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.force_open = True

        # 1. Register report R1
        r1 = Report(name="Report_1", filename="r1.py", filetype="python", dir=".", status="Waiting")
        auto_svc.add(r1)

        # 2. Start scheduler
        intra_svc.start_fresh_run(force_open=True)

        # Simulate Report_1 executing
        intra_svc.waitlist.clear()
        intra_svc.current_runs["Report_1"] = CLOCK.formatted_now()

        print(f"Initial state: current_runs={list(intra_svc.current_runs.keys())}, waitlist={list(intra_svc.waitlist)}")

        # 3. User deletes Report_1 via API while it is executing
        auto_svc.delete("Report_1")
        if "Report_1" in intra_svc.waitlist:
            intra_svc.waitlist.remove("Report_1")

        print(f"After deletion: Report_1 in automations={auto_svc.get_by_name('Report_1') is not None}")

        # 4. Report_1 finishes with dependency skip: _on_good re-queues it
        started = intra_svc.current_runs.pop("Report_1")
        intra_svc.waitlist.append("Report_1")

        print(f"After skip rotation: waitlist={list(intra_svc.waitlist)}, current_runs={list(intra_svc.current_runs.keys())}")

        # 5. Next tick: pops Report_1, calls _trigger_report, calls execute_report
        next_report = intra_svc.waitlist.popleft()
        intra_svc.current_runs[next_report] = CLOCK.formatted_now()
        success = exec_svc.execute_report(next_report)

        print(f"execute_report('{next_report}') returned: {success}")
        print(f"current_runs after execute_report: {list(intra_svc.current_runs.keys())}")

        # 6. Subsequent tick attempts to process any new reports
        status = intra_svc.resolve_status()
        can_run_next = (status == Intraday.OPEN and len(intra_svc.current_runs) == 0 and len(intra_svc.waitlist) > 0)
        print(f"len(current_runs) == 0: {len(intra_svc.current_runs) == 0}")
        print(f"Can scheduler run new reports? {can_run_next}")

        assert len(intra_svc.current_runs) == 1, "Report_1 must remain stuck in current_runs"
        assert "Report_1" in intra_svc.current_runs, "Report_1 remains stuck in current_runs"
        print("[+] CONFIRMED F-001: Queue is permanently deadlocked with orphan in current_runs!")

if __name__ == "__main__":
    reproduce()

