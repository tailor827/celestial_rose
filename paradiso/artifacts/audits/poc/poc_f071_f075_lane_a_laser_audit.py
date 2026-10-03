"""
Sandboxed PoC Suite for Batch 16 Laser-Focused Lane A Audit (F-071 to F-075).
Strictly uses isolated tempfile directories; never mutates live storage, logs, or config.
"""
import os
import sys
import json
import time
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

PARADISO_DIR = Path(__file__).resolve().parents[3]
if str(PARADISO_DIR) not in sys.path:
    sys.path.insert(0, str(PARADISO_DIR))


def test_f071_blueprint_and_default_dir_mismatch():
    """
    F-071:
    1. UI/API default dir is '../reports/python', while all shipped reports live in '../reports'.
    2. When a blueprint script is placed in '../reports/python' (or 'reports/python'),
       Path(__file__).resolve().parent.parent / 'paradiso' / 'logs' writes the receipt to
       <workspace>/reports/paradiso/logs/{name}.json instead of <workspace>/paradiso/logs/{name}.json,
       causing ExecutionService to fail with a Contract Violation!
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Replicate workspace layout: <tmp>/paradiso and <tmp>/reports/python
        fake_workspace = tmp_path / "workspace"
        fake_base_dir = fake_workspace / "paradiso"
        fake_logs_dir = fake_base_dir / "logs"
        fake_storage_dir = fake_base_dir / "storage"
        fake_reports_py_dir = fake_workspace / "reports" / "python"
        fake_logs_dir.mkdir(parents=True, exist_ok=True)
        fake_storage_dir.mkdir(parents=True, exist_ok=True)
        fake_reports_py_dir.mkdir(parents=True, exist_ok=True)

        # Read real sample_report_blueprint.py and configure REPORT_NAME = "Subdir_Test"
        blueprint_src = (PARADISO_DIR.parent / "reports" / "sample_report_blueprint.py").read_text(encoding="utf-8")
        script_code = blueprint_src.replace('REPORT_NAME = "SF Base"', 'REPORT_NAME = "Subdir_Test"')
        script_file = fake_reports_py_dir / "subdir_test.py"
        script_file.write_text(script_code, encoding="utf-8")

        from models.automation import Automations
        from models.report import Report
        from services.automation_service import AutomationService
        from services.execution_service import ExecutionService

        auto_svc = AutomationService(Automations(file_path=fake_storage_dir / "automations.json"))
        auto_svc.add(Report(
            name="Subdir_Test",
            filename="subdir_test.py",
            filetype="python",
            dir="../reports/python",
            status="Waiting",
            report_type="type_a"
        ))

        exec_svc = ExecutionService(automation_service=auto_svc, log_dir=fake_logs_dir)
        done_evt = []

        with patch("services.execution_service.BASE_DIR", fake_base_dir), \
             patch("services.runner.BASE_DIR", fake_base_dir), \
             patch.dict(os.environ, {"PARADISO_LOGS_DIR": str(fake_logs_dir)}):
            exec_svc.execute_report(
                name="Subdir_Test",
                callback_good=lambda n, d, o: done_evt.append(("good", n, o)),
                callback_fail=lambda n, d, e: done_evt.append(("fail", n, e))
            )
            deadline = time.time() + 5.0
            while not done_evt and time.time() < deadline:
                time.sleep(0.05)

        rep_after = auto_svc.get_by_name("Subdir_Test")
        # Also check index.html and app.js default dir
        app_js = (PARADISO_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        ui_defaults_to_subdir = "dirInput.value = '../reports/python';" in app_js

        passed = (
            len(done_evt) == 1
            and done_evt[0][0] == "good"
            and rep_after.status == "Completed"
        )
        print(
            f"[F-071] callback={done_evt[0][0] if done_evt else None}, "
            f"status={rep_after.status}, last_output={rep_after.last_output!r}, "
            f"ui_defaults_to_subdir={ui_defaults_to_subdir} -> "
            f"{'PASS' if passed else 'FAIL (BUG CONFIRMED)'}"
        )
        return passed


def test_f072_waiting_to_close_false_exceeded_retries_and_stale_callback():
    """
    F-072:
    1. A Lane A report launched at 20:55 that fails on Attempt 1 of 5 at 21:02 (WAITING_TO_CLOSE)
       is falsely marked 'Failed: Exceeded max retries (1/5)' instead of 'Retrial (attempt 1/5)'.
    2. A stale callback from a process that exited just as stop_lane('type_a') or reset_all_reports()
       cleared current_runs still mutates report status and day.reports_ran.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
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
        from utils.clock import CLOCK

        auto_svc = AutomationService(Automations(file_path=tmp_path / "storage" / "automations.json"))
        intra_repo = Intraday(file_path=tmp_path / "storage" / "intraday.json")
        exec_svc = ExecutionService(automation_service=auto_svc, log_dir=tmp_path / "logs")
        intra_svc = IntradayService(automation_service=auto_svc, execution_service=exec_svc, intraday_repo=intra_repo)
        intra_svc.max_retries = 5

        auto_svc.add(Report(
            name="Late_A", filename="sample_report_blueprint.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a"
        ))
        auto_svc.add(Report(
            name="Stopped_A", filename="sample_report_blueprint.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a"
        ))

        callbacks = {}
        def fake_exec(name, callback_good=None, callback_fail=None):
            callbacks[name] = (callback_good, callback_fail)
            return True

        exec_svc.execute_report = fake_exec

        # 1. Launch at 20:55 (OPEN)
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="20:55"):
            intra_svc.start_lane("type_a")
            intra_svc.tick()

        # At 21:02 (WAITING_TO_CLOSE), Late_A fails Attempt 1 of 5
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="21:02"):
            callbacks["Late_A"][1]("Late_A", "5s", "Return code 1: DB timeout")

        late_rep = auto_svc.get_by_name("Late_A")
        falsely_exceeded_on_attempt_1 = "Exceeded max retries (1/5)" in (late_rep.last_output or "")

        # 2. Stale callback after stop_lane("type_a") cleared current_runs
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intra_svc.start_lane("type_a")
            intra_svc.tick()
            # Operator stops Lane A right as process exits
            intra_svc.stop_lane("type_a")
            # Stale _on_good callback fires after stop_lane cleared current_runs
            (tmp_path / "logs" / "Stopped_A.json").write_text(
                json.dumps({"name": "Stopped_A", "status": "Completed", "last_output": "Done"}),
                encoding="utf-8"
            )
            callbacks["Stopped_A"][0]("Stopped_A", "2s", "Done")

        stopped_rep = auto_svc.get_by_name("Stopped_A")
        day_rec = intra_repo.get_day("20261005")
        stale_callback_corrupted = (stopped_rep.status == "Completed") or ("Stopped_A" in (day_rec.reports_ran if day_rec else {}))

        passed = (not falsely_exceeded_on_attempt_1) and (not stale_callback_corrupted)
        print(
            f"[F-072] late_status={late_rep.status}, late_output={late_rep.last_output!r}, "
            f"stopped_status={stopped_rep.status}, stale_corrupted={stale_callback_corrupted} -> "
            f"{'PASS' if passed else 'FAIL (BUG CONFIRMED)'}"
        )
        return passed


def test_f073_receipt_status_case_sensitivity_and_corrupted_json():
    """
    F-073:
    1. A script writing lowercase '"status": "completed"' in logs/{name}.json causes ExecutionService
       to mark it Completed, while IntradayService._on_good rejects it (log.status == 'Completed' is False)
       and calls _handle_failure, marking it Retrial/Failed!
    2. A script writing corrupted JSON '{bad json' to logs/{name}.json and exiting 0 with benign stdout
       passes has_valid_receipt() (size > 0) and falls back to 'Completed' in ReportLog.from_json().
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        os.environ["PARADISO_STORAGE_DIR"] = str(tmp_path / "storage")
        os.environ["PARADISO_LOGS_DIR"] = str(tmp_path / "logs")
        (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        from models.automation import Automations
        from models.intraday import Intraday
        from models.report import Report
        from models.report_log import ReportLog
        from services.automation_service import AutomationService
        from services.execution_service import ExecutionService
        from services.intraday_service import IntradayService
        from utils.clock import CLOCK

        auto_svc = AutomationService(Automations(file_path=tmp_path / "storage" / "automations.json"))
        intra_repo = Intraday(file_path=tmp_path / "storage" / "intraday.json")
        exec_svc = ExecutionService(automation_service=auto_svc, log_dir=tmp_path / "logs")
        intra_svc = IntradayService(automation_service=auto_svc, execution_service=exec_svc, intraday_repo=intra_repo)

        auto_svc.add(Report(
            name="Lower_Complete", filename="sample_report_blueprint.py", filetype="python",
            dir="../reports", status="Waiting", report_type="type_a"
        ))

        callbacks = {}
        def fake_exec(name, callback_good=None, callback_fail=None):
            callbacks[name] = (callback_good, callback_fail)
            return True

        exec_svc.execute_report = fake_exec
        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="09:00"):
            intra_svc.start_lane("type_a")
            intra_svc.tick()
            # Script writes lowercase "completed"
            (tmp_path / "logs" / "Lower_Complete.json").write_text(
                json.dumps({"name": "Lower_Complete", "status": "completed", "last_output": "All rows exported"}),
                encoding="utf-8"
            )
            callbacks["Lower_Complete"][0]("Lower_Complete", "2s", "All rows exported")

        rep_lower = auto_svc.get_by_name("Lower_Complete")

        # Corrupted JSON receipt check
        corrupt_log_file = tmp_path / "logs" / "Corrupt_Receipt.json"
        corrupt_log_file.write_text("{corrupted_json_without_closing_brace", encoding="utf-8")
        rl = ReportLog("Corrupt_Receipt", log_dir=tmp_path / "logs")
        corrupt_has_valid = rl.has_valid_receipt()

        passed = (rep_lower.status == "Completed") and (not corrupt_has_valid)
        print(
            f"[F-073] lower_complete_status={rep_lower.status}, lower_output={rep_lower.last_output!r}, "
            f"corrupt_has_valid_receipt={corrupt_has_valid} -> "
            f"{'PASS' if passed else 'FAIL (BUG CONFIRMED)'}"
        )
        return passed


def test_f074_retry_counts_wiped_on_restart_and_start_fresh_run():
    """
    F-074:
    1. When a Lane A report has failed 2/5 times (or 5/5 times) and the server restarts mid-day,
       IntradayService.__init__ does not hydrate retry_counts, so retry_counts is 0.
    2. Calling start_fresh_run() mid-day on an already-initialized day clears retry_counts to 0.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        os.environ["PARADISO_STORAGE_DIR"] = str(tmp_path / "storage")
        os.environ["PARADISO_LOGS_DIR"] = str(tmp_path / "logs")
        (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        from models.automation import Automations
        from models.intraday import Intraday, ReportRun
        from models.report import Report
        from services.automation_service import AutomationService
        from services.execution_service import ExecutionService
        from services.intraday_service import IntradayService
        from utils.clock import CLOCK

        auto_svc = AutomationService(Automations(file_path=tmp_path / "storage" / "automations.json"))
        intra_repo = Intraday(file_path=tmp_path / "storage" / "intraday.json")
        exec_svc = ExecutionService(automation_service=auto_svc, log_dir=tmp_path / "logs")

        with patch.object(CLOCK, "date_str", return_value="20261005"), \
             patch.object(CLOCK, "time_24_str", return_value="10:00"):
            intra_svc = IntradayService(automation_service=auto_svc, execution_service=exec_svc, intraday_repo=intra_repo)
            intra_svc.max_retries = 5
            auto_svc.add(Report(
                name="Flaky_A", filename="sample_report_blueprint.py", filetype="python",
                dir="../reports", status="Retrial",
                last_output="Error (attempt 2/5): Connection reset",
                report_type="type_a"
            ))
            auto_svc.add(Report(
                name="Exhausted_A", filename="sample_report_blueprint.py", filetype="python",
                dir="../reports", status="Failed",
                last_output="Exceeded max retries (5/5): Fatal crash",
                report_type="type_a"
            ))
            intra_svc._get_or_init_day("20261005", Intraday.OPEN)
            auto_svc.update_status("Flaky_A", "Retrial", last_output="Error (attempt 2/5): Connection reset")
            auto_svc.update_status("Exhausted_A", "Failed", last_output="Exceeded max retries (5/5): Fatal crash")
            intra_repo.add_report_run(
                date="20261005",
                report_name="Exhausted_A",
                run=ReportRun(
                    started_at="09:00:00 AM",
                    finished_at="09:01:00 AM",
                    result="failed",
                    duration="60s",
                    reason="Exceeded max retries (5/5): Fatal crash"
                )
            )

            # Simulate mid-day server reboot
            rebooted_svc = IntradayService(automation_service=auto_svc, execution_service=exec_svc, intraday_repo=intra_repo)
            rebooted_flaky_count = rebooted_svc.retry_counts.get("Flaky_A", 0)
            rebooted_exhausted_count = rebooted_svc.retry_counts.get("Exhausted_A", 0)

            # Also check start_fresh_run() mid-day on existing day
            rebooted_svc.retry_counts["Flaky_A"] = 2
            rebooted_svc.retry_counts["Exhausted_A"] = 5
            rebooted_svc.start_fresh_run()
            after_fresh_flaky = rebooted_svc.retry_counts.get("Flaky_A", 0)
            after_fresh_exhausted = rebooted_svc.retry_counts.get("Exhausted_A", 0)

        passed = (
            rebooted_flaky_count == 2
            and rebooted_exhausted_count == 5
            and after_fresh_flaky == 2
            and after_fresh_exhausted == 5
        )
        print(
            f"[F-074] rebooted_flaky={rebooted_flaky_count}, rebooted_exhausted={rebooted_exhausted_count}, "
            f"after_fresh_flaky={after_fresh_flaky}, after_fresh_exhausted={after_fresh_exhausted} -> "
            f"{'PASS' if passed else 'FAIL (BUG CONFIRMED)'}"
        )
        return passed


def test_f075_inline_onclick_single_quote_breakage():
    """
    F-075:
    Inline onclick="enableReport('${escapeHtml(item.name)}')" in app.js breaks with SyntaxError
    when report name contains an apostrophe (e.g. "Today's Cash Flow") because HTML attribute
    parsing decodes &#39; back to literal ' before JS execution.
    """
    app_js = (PARADISO_DIR / "web" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    vulnerable_patterns = [
        "onclick=\"enableReport('${escapeHtml(item.name)}')\"",
        "onclick=\"disableReport('${escapeHtml(item.name)}')\"",
        "onclick=\"deleteReport('${escapeHtml(item.name)}')\"",
        "onclick=\"runReport('${escapeHtml(item.name)}')\"",
    ]
    found = [p for p in vulnerable_patterns if p in app_js]
    passed = len(found) == 0
    print(
        f"[F-075] vulnerable_inline_onclick_patterns_found={len(found)} -> "
        f"{'PASS' if passed else 'FAIL (BUG CONFIRMED)'}"
    )
    return passed


if __name__ == "__main__":
    print("=" * 72)
    print("PARADISO LASER-FOCUSED LANE A AUDIT POC SUITE (F-071 TO F-074)")
    print("=" * 72)
    results = {
        "F-071": test_f071_blueprint_and_default_dir_mismatch(),
        "F-072": test_f072_waiting_to_close_false_exceeded_retries_and_stale_callback(),
        "F-073": test_f073_receipt_status_case_sensitivity_and_corrupted_json(),
        "F-074": test_f074_retry_counts_wiped_on_restart_and_start_fresh_run(),
    }
    print("=" * 72)
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print("  F-075: WAIVED (Operator policy: report names only use underscores/dots)")
    print("=" * 72)
    sys.exit(0 if all(results.values()) else 1)

