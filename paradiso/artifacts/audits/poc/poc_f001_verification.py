"""
Verification script for F-001 resolution.
Tests both defense layers:
1. HTTP 409 Conflict when deleting during active scheduler (Brick Wall policy).
2. Clean recovery without deadlock if a non-existent report is triggered in IntradayService.
"""
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from app import create_app
from models.automation import Automations
from models.intraday import Intraday
from models.report import Report
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from utils.clock import CLOCK

def test_delete_rejection_while_active():
    app, paradiso = create_app(auto_start=False)
    app.config["TESTING"] = True
    client = app.test_client()

    report_name = "BAU_Test_Active_Delete"
    paradiso.intraday_service.automation_service.add(Report(
        name=report_name,
        filename="dummy.py",
        filetype="python",
        dir="../reports",
        status="Waiting"
    ))

    # Activate scheduler
    paradiso.start()
    assert paradiso.intraday_service.is_active is True

    # 1. Attempt DELETE while active -> Expect 409 Conflict
    res = client.delete(f"/api/automation/delete/{report_name}")
    print(f"Delete while active status code: {res.status_code}")
    print(f"Delete response: {res.get_json()}")
    assert res.status_code == 409, f"Expected 409, got {res.status_code}"
    assert paradiso.intraday_service.automation_service.get_by_name(report_name) is not None

    # Stop scheduler
    paradiso.stop()
    assert paradiso.intraday_service.is_active is False

    # 2. Attempt DELETE while stopped -> Expect 200 OK
    res_stop = client.delete(f"/api/automation/delete/{report_name}")
    print(f"Delete while stopped status code: {res_stop.status_code}")
    assert res_stop.status_code == 200
    assert paradiso.intraday_service.automation_service.get_by_name(report_name) is None
    print("[+] Layer 1 Verified: DELETE blocked with 409 while scheduler is active.")

def test_ghost_report_no_deadlock():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        auto_repo = Automations(dir_path / "automations.json")
        intra_repo = Intraday(dir_path / "intraday.json")
        auto_svc = AutomationService(auto_repo)
        exec_svc = ExecutionService(auto_svc)
        intra_svc = IntradayService(auto_svc, exec_svc)
        intra_svc.intraday_repo = intra_repo
        intra_svc.max_retries = 3

        intra_svc.start_fresh_run(force_open=True)

        # Inject a ghost report (not in catalog) directly into waitlist
        intra_svc.waitlist.append("Ghost_Report")
        print(f"Initial waitlist: {list(intra_svc.waitlist)}")

        today = CLOCK.date_str()

        # Tick 1: Attempt 1
        intra_svc.tick()
        print(f"After Tick 1: current_runs={list(intra_svc.current_runs.keys())}, waitlist={list(intra_svc.waitlist)}")
        assert "Ghost_Report" not in intra_svc.current_runs
        assert intra_svc.retry_counts["Ghost_Report"] == 1

        # Tick 2: Attempt 2
        intra_svc.tick()
        print(f"After Tick 2: current_runs={list(intra_svc.current_runs.keys())}, waitlist={list(intra_svc.waitlist)}")
        assert "Ghost_Report" not in intra_svc.current_runs
        assert intra_svc.retry_counts["Ghost_Report"] == 2

        # Tick 3: Attempt 3 -> hits max_retries, marked failed, purged from waitlist
        intra_svc.tick()
        print(f"After Tick 3: current_runs={list(intra_svc.current_runs.keys())}, waitlist={list(intra_svc.waitlist)}")
        assert "Ghost_Report" not in intra_svc.waitlist, "Ghost_Report must be expelled from waitlist after max retries"
        assert len(intra_svc.current_runs) == 0, "current_runs must be empty"

        # Now add a valid report R2 to confirm the queue can continue normally
        r2 = Report(name="Valid_Report_2", filename="r2.py", filetype="python", dir=".", status="Waiting")
        auto_svc.add(r2)
        intra_svc.waitlist.append("Valid_Report_2")

        intra_svc.tick()
        print(f"After Tick 4 (processing Valid_Report_2): current_runs={list(intra_svc.current_runs.keys())}")
        assert "Valid_Report_2" in intra_svc.current_runs, "Queue must process Valid_Report_2 without deadlock!"

        print("[+] Layer 2 Verified: Missing report cleanly fails, leaves current_runs, and does NOT deadlock the queue.")

if __name__ == "__main__":
    test_delete_rejection_while_active()
    test_ghost_report_no_deadlock()

