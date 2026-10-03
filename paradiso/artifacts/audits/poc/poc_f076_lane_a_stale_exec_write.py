"""
Sandboxed PoC for Batch 17 (F-076). Isolated tempdirs only; never touches live storage/logs.

F-076: The F-072 PoC replaced ExecutionService.execute_report with a fake, so it never exercised
ExecutionService's own _on_good/_on_fail closures. Those closures write automations.json BEFORE
IntradayService's stale guard runs, and their own guard only recognises the 'Stopped by user'
sentinel. A process that exits naturally just before reset_all_reports() or _close_day()
(so Runner does not flag it as killed) therefore still overwrites catalog state.
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

PARADISO_DIR = Path(__file__).resolve().parents[3]
if str(PARADISO_DIR) not in sys.path:
    sys.path.insert(0, str(PARADISO_DIR))


class CapturingRunner:
    """Stands in for Runner: records callbacks instead of spawning processes."""
    def __init__(self):
        self.cbs = {}
        self.log_dir = None
    def run_python(self, script_path, callback_good, callback_fail, name="report"):
        self.cbs[name] = (callback_good, callback_fail)
    run_r = run_python
    def kill_all(self):
        pass  # process already exited naturally -> not flagged as killed
    def kill_process(self, name):
        pass


def _setup(tmp_path):
    os.environ["PARADISO_STORAGE_DIR"] = str(tmp_path / "storage")
    os.environ["PARADISO_LOGS_DIR"] = str(tmp_path / "logs")
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    from models.automation import Automations
    from models.intraday import Intraday
    from models.report import Report
    from services.automation_service import AutomationService
    from services.execution_service import ExecutionService
    from services.intraday_service import IntradayService
    auto_svc = AutomationService(Automations(file_path=tmp_path / "storage" / "automations.json"))
    intra_repo = Intraday(file_path=tmp_path / "storage" / "intraday.json")
    exec_svc = ExecutionService(automation_service=auto_svc, log_dir=tmp_path / "logs")
    exec_svc.runner = CapturingRunner()
    intra_svc = IntradayService(automation_service=auto_svc, execution_service=exec_svc, intraday_repo=intra_repo)
    auto_svc.add(Report(name="Race_A", filename="sample_report_blueprint.py", filetype="python",
                        dir="../reports", status="Waiting", report_type="type_a"))
    return auto_svc, intra_repo, exec_svc, intra_svc


def _write_receipt(tmp_path):
    (tmp_path / "logs" / "Race_A.json").write_text(
        json.dumps({"name": "Race_A", "status": "Completed", "last_output": "Done"}), encoding="utf-8")


def scenario_reset():
    from utils.clock import CLOCK
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auto_svc, intra_repo, exec_svc, intra_svc = _setup(tmp_path)
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intra_svc.start_lane("type_a")
            intra_svc.tick()
            launched = "Race_A" in exec_svc.runner.cbs
            intra_svc.reset_all_reports()          # operator: Reset All
            _write_receipt(tmp_path)
            if launched:
                exec_svc.runner.cbs["Race_A"][0]("2s", "Done")   # watcher fires late
            rep = auto_svc.get_by_name("Race_A")
            pending = auto_svc.get_pending_by_type("type_a")
        ok = launched and rep.status == "Waiting" and "Race_A" in pending
        print(f"[F-076a reset]    launched={launched}, status_after={rep.status}, "
              f"still_pending={'Race_A' in pending} -> {'PASS' if ok else 'FAIL (BUG CONFIRMED)'}")
        return ok


def scenario_close_day():
    from utils.clock import CLOCK
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auto_svc, intra_repo, exec_svc, intra_svc = _setup(tmp_path)
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="20:58"):
            intra_svc.start_lane("type_a")
            intra_svc.tick()
            launched = "Race_A" in exec_svc.runner.cbs
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="22:00"):
            intra_svc.tick()                       # 22:00 cutoff -> _close_day
            _write_receipt(tmp_path)
            if launched:
                exec_svc.runner.cbs["Race_A"][0]("2s", "Done")
            rep = auto_svc.get_by_name("Race_A")
            day = intra_repo.get_day("20261005")
            run = day.reports_ran.get("Race_A") if day else None
            ledger = getattr(run, "result", None)
        ok = launched and rep.status == ("Completed" if ledger == "completed" else "Failed")
        print(f"[F-076b close]    launched={launched}, catalog_status={rep.status}, "
              f"intraday_ledger={ledger} -> {'PASS' if ok else 'FAIL (BUG CONFIRMED)'}")
        return ok


if __name__ == "__main__":
    print("=" * 72)
    print("PARADISO LANE A AUDIT POC (BATCH 17: F-076)")
    print("=" * 72)
    r = {"F-076a": scenario_reset(), "F-076b": scenario_close_day()}
    print("=" * 72)
    for k, v in r.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    sys.exit(0 if all(r.values()) else 1)
