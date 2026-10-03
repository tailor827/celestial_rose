"""
PoC Verification Suite for Pre-Production Final Audit (Batch 15: F-066 to F-070)
=================================================================================
Strictly isolated in tempfile.TemporaryDirectory() — zero mutation of live storage/logs.

Findings Tested:
- F-066: start_lane() / start_fresh_run() do not update self._active_date when starting
         on a new calendar day after the server was idle overnight, causing the very first
         tick() to trigger a false midnight rollover that revokes force_open=True, kills
         in-flight manual runs, wipes today's timeline/reports_ran, and re-queues completed runs.
- F-067: wake_lane_a_queue(reset_pass=True) omits resetting _cycle_completions_in_pass = 0
         (defeating starvation cooldown on the pass after any report completion), AND under
         multi-slot concurrency (max_concurrent_run: 4 in config.yaml) wipes in-flight sibling
         reports from _cycle_seen_in_pass while keeping them in _cycle_pass_reports, preventing
         _evaluate_pass_completion() from detecting pass completion or sorting waitlist by priority.
- F-068: "Inactive" (staged) reports are treated as active pending reports by get_pending(),
         get_pending_by_type(), set_waiting_all(), tick(), and _close_day() (which only exclude
         "Disabled"), causing staged "Inactive" reports to be immediately dispatched in PROD
         or overwritten to "Failed" at 22:00 and "Waiting" at 00:00; meanwhile /api/automation/enable
         rejects "Inactive" reports with HTTP 400.
- F-069: POST /api/automation/add does not validate report `name` against path separators (/ or \\),
         traversal (..), or filesystem/glob special characters, allowing ReportLog(name).clean_slate()
         to delete arbitrary .json files outside logs/ and trapping reports with `/` in automations.json
         because DELETE /api/automation/delete/<string:name> returns 404.
- F-070: _close_day() at 22:00 discards the actual `started_at` timestamp of in-flight killed reports
         (and fabricates a 22:00 `started_at` timestamp for unstarted reports instead of "--"), leaves
         Type B reports with prior completions stuck in "Retrial" status after 22:00, and fails to
         reset Lane A pass-tracking and starvation cooldown state (_consecutive_starvation_passes,
         _rotation_cooldown_until, _cycle_pass_reports, _cycle_seen_in_pass).
"""

import sys
import time
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

# Add paradiso to sys.path
PARADISO_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(PARADISO_DIR) not in sys.path:
    sys.path.insert(0, str(PARADISO_DIR))

from flask import Flask
from models.report import Report
from models.automation import Automations
from models.intraday import Intraday, ReportRun
from models.report_log import ReportLog
from services.automation_service import AutomationService
from services.execution_service import ExecutionService
from services.intraday_service import IntradayService
from controllers.automation_controller import AutomationController


def make_sandbox(tmp_dir: Path):
    storage_dir = tmp_dir / "storage"
    logs_dir = tmp_dir / "logs"
    storage_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    auto_file = storage_dir / "automations.json"
    intra_file = storage_dir / "intraday.json"

    automations = Automations(file_path=auto_file)
    intraday_repo = Intraday(file_path=intra_file)
    auto_service = AutomationService(automations=automations)
    exec_service = ExecutionService(automation_service=auto_service, log_dir=logs_dir)
    intra_service = IntradayService(
        automation_service=auto_service,
        execution_service=exec_service,
        intraday_repo=intraday_repo,
    )
    return auto_service, exec_service, intra_service, intraday_repo, logs_dir, storage_dir


def test_f066_new_day_start_lane_false_midnight_rollover() -> bool:
    """
    F-066: Server boots on Day 1 (e.g. Sunday 20261004) in Standby Mode (auto_start: false).
    On Day 2 (Monday 20261005), operator triggers a manual run or starts Lane A with force_open=True.
    Because start_lane() / start_fresh_run() never update self._active_date = today_date,
    the very first tick() sees today_date > self._active_date ("20261005" > "20261004") and
    triggers a destructive false midnight rollover!
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("services.intraday_service.CLOCK") as mock_clock, \
             patch("services.automation_service.CLOCK", mock_clock):
            # Boot on Sunday 20261004
            mock_clock.date_str.return_value = "20261004"
            mock_clock.formatted_date.return_value = "2026-10-04"
            mock_clock.time_24_str.return_value = "20:00"
            mock_clock.time_str.return_value = "08:00 PM"
            mock_clock.formatted_now.return_value = "2026-10-04 08:00:00 PM"
            mock_clock.now.return_value = datetime(2026, 10, 4, 20, 0, 0)
            mock_clock.simulation_mode = False

            auto_service, exec_service, intra_service, intraday_repo, logs_dir, _ = make_sandbox(tmp_path)
            auto_service.add(Report(
                name="Prod_Report_A1", filename="sample_a_01.py", filetype="python",
                dir="../reports/python", status="Waiting", report_type="type_a"
            ))
            auto_service.add(Report(
                name="Prod_Report_C1", filename="sample_c_01.py", filetype="python",
                dir="../reports/python", status="Waiting", report_type="type_c", scheduled_time="08:00"
            ))

            # Advance clock to Monday morning 20261005 at 06:45 AM
            mock_clock.date_str.return_value = "20261005"
            mock_clock.formatted_date.return_value = "2026-10-05"
            mock_clock.time_24_str.return_value = "06:45"
            mock_clock.time_str.return_value = "06:45 AM"
            mock_clock.formatted_now.return_value = "2026-10-05 06:45:00 AM"
            mock_clock.now.return_value = datetime(2026, 10, 5, 6, 45, 0)

            # Suppose Prod_Report_C1 was already completed earlier on Monday morning
            intra_service._get_or_init_day("20261005", "WAITING_TO_OPEN", force_open=True)
            auto_service.update_status("Prod_Report_C1", "Completed", duration="2s", last_output="Done")
            intraday_repo.add_report_run(
                date="20261005",
                report_name="Prod_Report_C1",
                run=ReportRun(started_at="06:40 AM", finished_at="06:42 AM", result="completed", duration="2s", reason="Done")
            )

            # Operator starts Lane A on Monday morning with force_open=True
            intra_service.start_lane("type_a", force_open=True)

            # Immediately, the daemon thread runs its first tick()
            with patch.object(intra_service, "_trigger_report"):
                intra_service.tick()

            day_after = intraday_repo.get_day("20261005")
            c1_after = auto_service.get_by_name("Prod_Report_C1")
            titles = [t.title for t in (day_after.timeline if day_after else [])]

            passed = (
                intra_service.force_open is True
                and day_after is not None
                and "Prod_Report_C1" in (day_after.reports_ran or {})
                and c1_after.status == "Completed"
                and "Lane A (Sequential) started" in titles
            )
            print(f"[F-066] force_open={intra_service.force_open}, C1_in_reports_ran={'Prod_Report_C1' in (day_after.reports_ran or {})}, C1_status={c1_after.status}, timeline={titles} -> {'PASS' if passed else 'FAIL (BUG CONFIRMED)'}")
            return passed


def test_f067_multi_slot_and_completion_pass_tracking() -> bool:
    """
    F-067:
    Part A (1-slot or multi-slot): When R1 completes, _on_good increments _cycle_completions_in_pass += 1
    and calls wake_lane_a_queue(reset_pass=True), which forgets to reset _cycle_completions_in_pass = 0.
    When remaining report R2 skips, _evaluate_pass_completion sees _cycle_completions_in_pass == 1 != 0
    and FAILS to engage starvation cooldown!
    Part B (multi-slot max_concurrent_run=4): R1 and R2 launch concurrently. R1 completes while R2 is
    in-flight. wake_lane_a_queue(reset_pass=True) clears _cycle_seen_in_pass while keeping R2 in
    _cycle_pass_reports. When R2 finishes with a dependency skip, R2 is not in _cycle_seen_in_pass,
    so _evaluate_pass_completion() fails to recognize pass completion or engage cooldown!
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("services.intraday_service.CLOCK") as mock_clock, \
             patch("services.automation_service.CLOCK", mock_clock), \
             patch("models.report_log.BASE_DIR", tmp_path):
            mock_clock.date_str.return_value = "20261005"
            mock_clock.formatted_date.return_value = "2026-10-05"
            mock_clock.time_24_str.return_value = "08:00"
            mock_clock.time_str.return_value = "08:00 AM"
            mock_clock.formatted_now.return_value = "2026-10-05 08:00:00 AM"
            mock_clock.now.return_value = datetime(2026, 10, 5, 8, 0, 0)
            mock_clock.simulation_mode = False

            auto_service, exec_service, intra_service, intraday_repo, logs_dir, _ = make_sandbox(tmp_path)
            intra_service.max_concurrent_run = 4

            for r_name in ("R1", "R2"):
                auto_service.add(Report(
                    name=r_name, filename=f"{r_name}.py", filetype="python",
                    dir="../reports/python", status="Waiting", report_type="type_a"
                ))

            intra_service.start_lane("type_a")

            callbacks = {}
            def fake_execute(name, callback_good=None, callback_fail=None):
                callbacks[name] = (callback_good, callback_fail)
                return True

            with patch.object(exec_service, "execute_report", side_effect=fake_execute):
                intra_service.tick()  # Launches both R1 and R2 into slots 1 & 2

            (logs_dir / "R1.json").write_text(json.dumps({"status": "Completed", "message": "OK"}), encoding="utf-8")
            (logs_dir / "R2.json").write_text(json.dumps({"status": "Retrial", "message": "SKIPPED: upstream missing"}), encoding="utf-8")

            # 1. R1 completes while R2 is still running in slot 2
            callbacks["R1"][0]("R1", "1s", "OK")

            # 2. Now R2 finishes with a dependency skip (Retrial)
            callbacks["R2"][0]("R2", "2s", "SKIPPED: upstream missing")

            starvation_after_r2_skip = intra_service._consecutive_starvation_passes
            completions_leaked = intra_service._cycle_completions_in_pass

            # Also test 1-slot mode where R1 completes FIRST, and THEN R2 launches and skips:
            intra_service.reset_all_reports()
            intra_service.max_concurrent_run = 1
            intra_service.start_lane("type_a")
            callbacks.clear()
            with patch.object(exec_service, "execute_report", side_effect=fake_execute):
                intra_service.tick()  # Launches R1 only
            (logs_dir / "R1.json").write_text(json.dumps({"status": "Completed", "message": "OK"}), encoding="utf-8")
            callbacks["R1"][0]("R1", "1s", "OK")

            with patch.object(exec_service, "execute_report", side_effect=fake_execute):
                intra_service.tick()  # Launches R2 in the new pass after wake_lane_a_queue()
            (logs_dir / "R2.json").write_text(json.dumps({"status": "Retrial", "message": "SKIPPED: upstream missing"}), encoding="utf-8")
            callbacks["R2"][0]("R2", "1s", "SKIPPED: upstream missing")

            starvation_1slot = intra_service._consecutive_starvation_passes

            passed = (
                starvation_after_r2_skip >= 1
                and completions_leaked == 0
                and starvation_1slot == 1
            )
            print(f"[F-067] multi_slot_starvation={starvation_after_r2_skip}, leaked_completions={completions_leaked}, 1slot_starvation_after_completion={starvation_1slot} -> {'PASS' if passed else 'FAIL (BUG CONFIRMED)'}")
            return passed


def test_f068_inactive_reports_dispatched_and_corrupted() -> bool:
    """
    F-068: Operator registers a staged report with status="Inactive" ("Inactive (Staged / Not queued)").
    1. get_pending_by_type("type_a") includes "Inactive" reports, so tick() immediately dispatches it!
    2. Attempting to enable it via /api/automation/enable fails with HTTP 400.
    3. At 22:00 (_close_day), it is overwritten from "Inactive" to "Failed".
    4. At 00:00 midnight rollover (set_waiting_all), it is overwritten from "Inactive" to "Waiting"!
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("services.intraday_service.CLOCK") as mock_clock, \
             patch("services.automation_service.CLOCK", mock_clock), \
             patch("controllers.automation_controller.CLOCK", mock_clock):
            mock_clock.date_str.return_value = "20261005"
            mock_clock.formatted_date.return_value = "2026-10-05"
            mock_clock.time_24_str.return_value = "08:00"
            mock_clock.time_str.return_value = "08:00 AM"
            mock_clock.formatted_now.return_value = "2026-10-05 08:00:00 AM"
            mock_clock.now.return_value = datetime(2026, 10, 5, 8, 0, 0)
            mock_clock.simulation_mode = False

            auto_service, exec_service, intra_service, intraday_repo, logs_dir, _ = make_sandbox(tmp_path)
            app = Flask(__name__)
            AutomationController(app, auto_service, intra_service)
            client = app.test_client()

            # Register a staged report with status="Inactive"
            res_add = client.post("/api/automation/add", json={
                "name": "Staged_Prod_Report",
                "filename": "sample_a_01.py",
                "filetype": "python",
                "dir": "../reports/python",
                "status": "Inactive",
                "report_type": "type_a"
            })
            assert res_add.status_code == 201

            # 1. Check if get_pending_by_type("type_a") or set_waiting_all() wrongly includes Inactive report
            in_pending = "Staged_Prod_Report" in auto_service.get_pending_by_type("type_a")

            # 2. Try to enable the Inactive report via /api/automation/enable
            res_enable = client.post("/api/automation/enable", json={"name": "Staged_Prod_Report"})
            enable_ok = (res_enable.status_code == 200)

            # Reset back to Inactive to test _close_day() and set_waiting_all()
            rep = auto_service.get_by_name("Staged_Prod_Report")
            rep.status = "Inactive"
            auto_service.add(rep)

            # 3. Run 22:00 _close_day()
            intra_service._close_day("20261005")
            status_after_close = auto_service.get_by_name("Staged_Prod_Report").status

            # 4. Reset to Inactive and test set_waiting_all()
            rep = auto_service.get_by_name("Staged_Prod_Report")
            rep.status = "Inactive"
            auto_service.add(rep)
            waiting_list = auto_service.set_waiting_all()
            status_after_set_waiting = auto_service.get_by_name("Staged_Prod_Report").status

            passed = (
                not in_pending
                and enable_ok
                and status_after_close == "Inactive"
                and status_after_set_waiting == "Inactive"
                and "Staged_Prod_Report" not in waiting_list
            )
            print(f"[F-068] in_pending={in_pending}, enable_http={res_enable.status_code}, status_at_2200={status_after_close}, status_after_set_waiting={status_after_set_waiting} -> {'PASS' if passed else 'FAIL (BUG CONFIRMED)'}")
            return passed


def test_f069_unvalidated_report_name_path_traversal_and_slash_trap() -> bool:
    """
    F-069: POST /api/automation/add does not validate `name` against path traversal (`..`),
    path separators (`/` or `\\`), or illegal filename characters (`:`, `*`, `?`, etc.).
    1. Creating a report with `name = "../storage/canary"` and running clean_slate() deletes
       `storage/canary.json` outside `logs/`!
    2. Creating a report with `name = "AR/AP Aging"` succeeds (201), but `DELETE /api/automation/delete/AR/AP Aging`
       returns 404 in Flask, trapping the report in automations.json!
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auto_service, exec_service, intra_service, intraday_repo, logs_dir, storage_dir = make_sandbox(tmp_path)
        app = Flask(__name__)
        AutomationController(app, auto_service, intra_service)
        client = app.test_client()

        canary_file = storage_dir / "canary.json"
        canary_file.write_text('{"secret": "do_not_delete"}', encoding="utf-8")

        # 1. Attempt to register traversal report name
        res_trav = client.post("/api/automation/add", json={
            "name": "../storage/canary",
            "filename": "sample_a_01.py",
            "filetype": "python",
            "dir": "../reports/python",
            "status": "Waiting",
            "report_type": "type_a"
        })
        if res_trav.status_code == 201:
            ReportLog("../storage/canary", log_dir=logs_dir).clean_slate()

        canary_survived = canary_file.exists()

        # 2. Attempt to register report name with slash "AR/AP Aging"
        res_slash = client.post("/api/automation/add", json={
            "name": "AR/AP Aging",
            "filename": "sample_a_01.py",
            "filetype": "python",
            "dir": "../reports/python",
            "status": "Waiting",
            "report_type": "type_a"
        })

        passed = (
            res_trav.status_code == 400
            and canary_survived
            and res_slash.status_code == 400
        )
        print(f"[F-069] traversal_add_http={res_trav.status_code}, canary_survived={canary_survived}, slash_add_http={res_slash.status_code} -> {'PASS' if passed else 'FAIL (BUG CONFIRMED)'}")
        return passed


def test_f070_close_day_started_at_and_stale_state() -> bool:
    """
    F-070: At 22:00 _close_day():
    1. In-flight report 'InFlight_A' (started at '2026-10-05 08:50:00 PM') has its started_at
       overwritten with 22:00 ('2026-10-05 10:00:00 PM'), while unstarted report 'Unstarted_A'
       is also given started_at='2026-10-05 10:00:00 PM' instead of '--'.
    2. Type B report 'Recurring_B' that completed at 08:00 AM but failed a later interval (status='Retrial')
       is left stuck in status='Retrial' after 22:00 CLOSED.
    3. Lane A starvation state (_consecutive_starvation_passes, _rotation_cooldown_until, _cycle_pass_reports)
       is not cleared on _close_day().
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("services.intraday_service.CLOCK") as mock_clock, \
             patch("services.automation_service.CLOCK", mock_clock):
            mock_clock.date_str.return_value = "20261005"
            mock_clock.formatted_date.return_value = "2026-10-05"
            mock_clock.time_24_str.return_value = "22:00"
            mock_clock.time_str.return_value = "10:00 PM"
            mock_clock.formatted_now.return_value = "2026-10-05 10:00:00 PM"
            mock_clock.now.return_value = datetime(2026, 10, 5, 22, 0, 0)
            mock_clock.simulation_mode = False

            auto_service, exec_service, intra_service, intraday_repo, logs_dir, _ = make_sandbox(tmp_path)
            auto_service.add(Report(name="InFlight_A", filename="a1.py", filetype="python", dir="../reports/python", status="Running", report_type="type_a"))
            auto_service.add(Report(name="Unstarted_A", filename="a2.py", filetype="python", dir="../reports/python", status="Waiting", report_type="type_a"))
            auto_service.add(Report(name="Recurring_B", filename="b1.py", filetype="python", dir="../reports/python", status="Retrial", report_type="type_b"))

            intra_service._get_or_init_day("20261005", "OPEN")
            # Record that Recurring_B completed at 08:00 AM, then later entered Retrial at 20:30
            intraday_repo.add_report_run(
                date="20261005",
                report_name="Recurring_B",
                run=ReportRun(started_at="08:00 AM", finished_at="08:01 AM", result="completed", duration="1m", reason="OK")
            )
            auto_service.update_status("Recurring_B", "Retrial", last_output="Error on 20:30 interval")

            intra_service.current_runs["InFlight_A"] = "2026-10-05 08:50:00 PM"
            intra_service._consecutive_starvation_passes = 3
            intra_service._rotation_cooldown_until = time.time() + 120.0
            intra_service._cycle_pass_reports = {"Unstarted_A"}

            intra_service._close_day("20261005")

            day = intraday_repo.get_day("20261005")
            inflight_run = day.reports_ran.get("InFlight_A")
            unstarted_run = day.reports_ran.get("Unstarted_A")
            b_status = auto_service.get_by_name("Recurring_B").status

            passed = (
                inflight_run is not None and inflight_run.started_at == "2026-10-05 08:50:00 PM"
                and unstarted_run is not None and unstarted_run.started_at == "--"
                and b_status != "Retrial"
                and intra_service._consecutive_starvation_passes == 0
                and intra_service._rotation_cooldown_until == 0.0
                and len(intra_service._cycle_pass_reports) == 0
            )
            print(f"[F-070] inflight_started_at={getattr(inflight_run, 'started_at', None)}, unstarted_started_at={getattr(unstarted_run, 'started_at', None)}, b_status={b_status}, starvation_passes={intra_service._consecutive_starvation_passes} -> {'PASS' if passed else 'FAIL (BUG CONFIRMED)'}")
            return passed


if __name__ == "__main__":
    print("=" * 72)
    print("PARADISO PRE-PROD FINAL AUDIT POC SUITE (F-066 TO F-070)")
    print("=" * 72)
    results = {
        "F-066": test_f066_new_day_start_lane_false_midnight_rollover(),
        "F-067": test_f067_multi_slot_and_completion_pass_tracking(),
        "F-068": test_f068_inactive_reports_dispatched_and_corrupted(),
        "F-069": test_f069_unvalidated_report_name_path_traversal_and_slash_trap(),
        "F-070": test_f070_close_day_started_at_and_stale_state(),
    }
    print("=" * 72)
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL (DEFECT REPRODUCED)'}")
    print("=" * 72)
