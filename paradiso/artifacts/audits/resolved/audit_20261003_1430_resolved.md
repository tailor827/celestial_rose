# Laser-Focused Lane A Production Audit — Batch 16

- **Audit Timestamp:** `2026-10-03 14:30:00 +08:00`
- **Target Scope:** Lane A End-to-End Pipeline (Report Blueprints & Registration $\rightarrow$ Subprocess Execution & Receipt Contract $\rightarrow$ `21:00–22:00` Wind-Down & Stop/Reset Callback Races $\rightarrow$ Mid-Day Restart & Retry Persistence $\rightarrow$ Lane A UI Controls)
- **Verification PoC Suite:** [`paradiso/artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py) (`5/5 FAIL` on current `HEAD`)

---

## Executive Summary

A deep, laser-focused audit of **Lane A** uncovered **5 reproducible defects (`F-071` through `F-075`)** across the Lane A script execution contract, `21:00–22:00` wind-down error handling, subprocess watcher race conditions, retry counter persistence, and UI action handlers. All 5 findings were empirically confirmed in an isolated sandbox (`5/5 FAIL`).

| Finding ID | Severity | Lane A Subsystem | Title | Status |
| :--- | :---: | :--- | :--- | :---: |
| **F-071** | **HIGH** | Report Registration & Blueprints (`app.js`, `index.html`, `automation_controller.py`, `sample_report_blueprint.*`, `runner.py`) | UI/API Default Directory (`../reports/python` & `../reports/r`) Conflicts with Blueprint Receipt Path Resolution (`parent.parent / "paradiso" / "logs"`), Causing Immediate Contract-Violation or Missing-Script Failures | **OPEN** |
| **F-072** | **HIGH** | Wind-Down & Subprocess Lifecycle (`intraday_service.py`, `execution_service.py`, `runner.py`) | Lane A Error During `WAITING_TO_CLOSE` (`21:00–22:00`) Falsely Marks Report `"Exceeded max retries (1/N)"` on First Attempt, and Stale Watcher Callbacks After `stop_lane()` / `reset_all_reports()` / `_close_day()` Mutate State | **OPEN** |
| **F-073** | **MEDIUM** | Receipt Contract & Log Parser (`report_log.py`, `execution_service.py`, `intraday_service.py`) | Case-Sensitive Receipt Status Parsing (`"completed"` vs `"Completed"`) Causes Successful Reports to Fail in `IntradayService`, While Corrupted/Status-less JSON Receipts Bypass `has_valid_receipt()` | **OPEN** |
| **F-074** | **MEDIUM** | Retry Counter Persistence (`intraday_service.py`, `automation_controller.py`) | `retry_counts` Is Never Hydrated on Server Restart and Is Wiped Mid-Day by `start_fresh_run()`, Resetting Retry Limits and Displaying `0 / N` Error Retries in the Lane A UI | **OPEN** |
| ~~**F-075**~~ | **LOW** | Lane A & Catalog Web UI (`web/static/js/app.js`) | Inline `onclick="enableReport('${escapeHtml(item.name)}')"` Handlers Break with `SyntaxError` When a Report Name Contains an Apostrophe (`'`) | **WAIVED** *(Operator convention: report names only use underscores and dots)* |

---

## Detailed Findings (Standard Triad Format)

### [F-071] [HIGH] UI/API Default Directory (`../reports/python` & `../reports/r`) Conflicts with Blueprint Receipt Path Resolution (`parent.parent / "paradiso" / "logs"`), Causing Immediate Contract-Violation or Missing-Script Failures

- **OBSERVATION:**
  1. In [`paradiso/web/templates/index.html`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/templates/index.html#L1668), [`paradiso/web/static/js/app.js`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/static/js/app.js#L1158) (`handleFileTypeChange`, `openAddReportModal` line 1191, `handleAddReportSubmit` line 1250), and [`AutomationController.add_automation`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/controllers/automation_controller.py#L72-L73), the default script directory is set to `"../reports/python"` (for Python) and `"../reports/r"` (for R), while all 18 shipped scripts on disk (`reports/sample_lane_a_01.py`..`10.py`, `reports/sample_report_blueprint.py`, `reports/sample_report_blueprint.R`) reside in `"../reports"` and the subdirectories `reports/python` and `reports/r` do not exist.
  2. When an operator places a script based on [`reports/sample_report_blueprint.py`](file:///c:/Users/desktop/Documents/work/celestial_rose/reports/sample_report_blueprint.py#L74-L78), [`reports/sample_report_blueprint.R`](file:///c:/Users/desktop/Documents/work/celestial_rose/reports/sample_report_blueprint.R#L69-L75), or the User Guide template ([`paradiso/web/templates/index.html`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/templates/index.html#L1317)) inside `"../reports/python"`, `"../reports/r"`, `"reports/python"`, or `"reports/r"`, the blueprint computes:
     ```python
     SCRIPT_DIR = Path(__file__).resolve().parent
     WORKSPACE_DIR = SCRIPT_DIR.parent
     PARADISO_LOGS = WORKSPACE_DIR / "paradiso" / "logs"
     ```
     Because `SCRIPT_DIR` is `<workspace>/reports/python`, `SCRIPT_DIR.parent` is `<workspace>/reports` (not `<workspace>`), so the script writes its JSON receipt to `<workspace>/reports/paradiso/logs/{name}.json` instead of `<workspace>/paradiso/logs/{name}.json`! Furthermore, [`ExecutionService.execute_report`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/execution_service.py#L46-L47) and [`Runner.run_python` / `run_r`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/runner.py#L157-L163) do not export `PARADISO_LOGS_DIR` into the child process environment.

- **EVIDENCE:**
  ```text
  $ python artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py
  [F-071] callback=fail, status=Failed, last_output="Contract violation: Script 'Subdir_Test' exited 0 without writing receipt to logs/Subdir_Test.json", ui_defaults_to_subdir=True -> FAIL (BUG CONFIRMED)
  ```

- **CONSEQUENCE:**
  Any Lane A report registered using the Web UI's default directory (`../reports/python` or `../reports/r`) either fails immediately with `"Report script not found on disk"` (if the script was saved in `reports/`) or fails every execution with `"Contract violation: Script exited 0 without writing receipt to logs/{name}.json"` (if the blueprint script was saved in `reports/python/` or `reports/r/`).

- **VERIFICATION CRITERION:**
  1. `Runner.run_python` and `Runner.run_r` (or `ExecutionService`) must pass the active `PARADISO_LOGS_DIR` in the child subprocess environment, and the official blueprints (`sample_report_blueprint.py`, `sample_report_blueprint.R`, and the User Guide snippets in `index.html`) must resolve the receipt directory via `PARADISO_LOGS_DIR` (or by locating `paradiso/logs` / `Path.cwd() / "logs"` regardless of whether the script is placed in `../reports`, `../reports/python`, `../reports/r`, `reports`, `reports/python`, or `reports/r`).
  2. The default directory in the Add Report UI/API must align with the repository's actual `../reports` directory (or ensure `reports/python` and `reports/r` work seamlessly).

---

### [F-072] [HIGH] Lane A Error During `WAITING_TO_CLOSE` (`21:00–22:00`) Falsely Marks Report `"Exceeded max retries (1/N)"` on First Attempt, and Stale Watcher Callbacks After `stop_lane()` / `reset_all_reports()` / `_close_day()` Mutate State

- **OBSERVATION:**
  1. **False `"Exceeded max retries (1/N)"` during `21:00–22:00` (`WAITING_TO_CLOSE`):**
     In [`IntradayService._trigger_report._handle_failure`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/intraday_service.py#L1075-L1124), line 1076 computes:
     `scheduler_is_active = self.lane_a_active and (self.resolve_status() == Intraday.OPEN or self.force_open)`
     and line 1081 checks:
     `if attempts < self.max_retries and scheduler_is_active:`
     When a Lane A report launched before `21:00` (e.g., at `20:55`) encounters an error at `21:02` during the `WAITING_TO_CLOSE` wind-down window on **Attempt 1 of 5** (`attempts = 1 < self.max_retries = 5`), `scheduler_is_active` is `False` because `resolve_status()` is `WAITING_TO_CLOSE`. Consequently, `_handle_failure` enters the `else:` branch (line 1098) and marks the report permanently `"Failed"` with `last_output = "Exceeded max retries (1/5): ..."` and logs `"{name} permanently failed"` on Attempt 1 of 5! (Compare this with dependency skips at line 1049, which set `status = "Retrial"` and only gate `self.waitlist.append(name)` on `if scheduler_is_active:`.)
  2. **Stale watcher callback race after `stop_lane("type_a")`, `reset_all_reports()`, `_close_day()`, or midnight rollover:**
     In [`Runner._watcher`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/runner.py#L126-L153), `process.communicate()` returns and pops `name` from `self.active_processes` (line 132) *before* [`ExecutionService._on_good` / `_on_fail`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/execution_service.py#L68-L123) or [`IntradayService._trigger_report._on_good` / `_on_fail`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/intraday_service.py#L1014-L1167) acquires `IntradayService._lock`. If `stop_lane("type_a")`, `reset_all_reports()`, `_close_day()`, or midnight rollover executes in that window and clears `self.current_runs`, the watcher callback still runs `self.current_runs.pop(name, CLOCK.formatted_now())` without checking `if name not in self.current_runs: return`, overwriting the stopped/reset report status and inserting stale entries into `day.reports_ran` and `day.timeline`.

- **EVIDENCE:**
  ```text
  $ python artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py
  [F-072] late_status=Failed, late_output='Exceeded max retries (1/5): Return code 1: DB timeout', stopped_status=Waiting, stale_corrupted=True -> FAIL (BUG CONFIRMED)
  ```

- **CONSEQUENCE:**
  Any in-flight Lane A report that encounters a transient error during the `21:00–22:00` wind-down window on Attempt `1` of `5` is falsely recorded in the audit log and UI as `"Exceeded max retries (1/5)"` (`"{name} permanently failed"`). Additionally, a process finishing concurrently with `Stop Lane A`, `Reset All`, or the `22:00` cutoff corrupts the stopped/reset catalog and `day.reports_ran` state.

- **VERIFICATION CRITERION:**
  1. In `_trigger_report._on_good` and `_on_fail`, if `name not in self.current_runs` upon acquiring `self._lock` (meaning the run was already aborted/cleared by `stop_lane`, `reset_all_reports`, `_close_day`, or midnight rollover), the callback must abort without mutating `automations.json` (restoring the pre-callback status if `ExecutionService` touched it, or deferring status mutation until verified active) or `intraday.json`.
  2. In `_handle_failure`, when `attempts < self.max_retries` but `not scheduler_is_active` (e.g., during `WAITING_TO_CLOSE`), the report must be set to `"Retrial"` with `f"Error (attempt {attempts}/{self.max_retries}): {error}"` (without appending to `self.waitlist`), reserving `"Exceeded max retries"` strictly for `attempts >= self.max_retries`.

---

### [F-073] [MEDIUM] Case-Sensitive Receipt Status Parsing (`"completed"` vs `"Completed"`) Causes Successful Reports to Fail in `IntradayService`, While Corrupted/Status-less JSON Receipts Bypass `has_valid_receipt()`

- **OBSERVATION:**
  1. In [`ReportLog.from_json`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/models/report_log.py#L120-L141), line 130 reads `raw_status = data.get("status")` without case-normalizing `"completed"`, `"failed"`, `"skipped"`, or `"retrial"`.
     - If a script writes `"status": "completed"` (or `"COMPLETED"`, `"Success"`) in `logs/{name}.json` and exits `0`, [`ExecutionService._on_good`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/execution_service.py#L81) marks the report `"Completed"` in `automations.json`, but [`IntradayService._trigger_report._on_good`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/intraday_service.py#L1019) checks `if log.status == "Completed":` (which is `False` for `"completed"`), falls into the `else:` branch (`_handle_failure`), and marks the report as **`"Retrial"` (`"Error (attempt 1/5)"`)** and eventually **`"Failed"`**!
     - Similarly, if a script writes `"status": "failed"` or `"FAILED"` and exits `0`, `ExecutionService._on_good` (line 73: `if script_log.status == "Failed":`) misses it and calls `callback_good` instead of `callback_fail`.
  2. In [`ReportLog.has_valid_receipt`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/models/report_log.py#L86-L90), validity is checked solely via `latest.exists() and latest.stat().st_size > 0`. If a script writes malformed/corrupted JSON (e.g. `"{corrupted"`) or an empty JSON object `{}` to `logs/{name}.json` and exits `0` with benign stdout, `has_valid_receipt()` returns `True` and `from_json()` catches the `JSONDecodeError` and falls back to `self.parse_output(default_stdout)` (`"Completed"`).

- **EVIDENCE:**
  ```text
  $ python artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py
  [F-073] lower_complete_status=Retrial, lower_output='Error (attempt 1/5): All rows exported', corrupt_has_valid_receipt=True -> FAIL (BUG CONFIRMED)
  ```

- **CONSEQUENCE:**
  Custom analyst scripts that write case-variant status strings (`"completed"`, `"COMPLETED"`, `"failed"`, `"FAILED"`, `"skipped"`, `"retrial"`) in their receipt JSON either fail after succeeding or desynchronize between `ExecutionService` and `IntradayService`, while scripts that write corrupted/truncated JSON receipts silently pass as `"Completed"`.

- **VERIFICATION CRITERION:**
  `ReportLog.from_json()` must normalize receipt `status` values case-insensitively to canonical statuses (`"Completed"`, `"Skipped"`, `"Failed"`), and `ReportLog.has_valid_receipt()` must verify that the receipt file is valid JSON containing a non-empty dictionary with a recognized/non-empty status or output payload.

---

### [F-074] [MEDIUM] `retry_counts` Is Never Hydrated on Server Restart and Is Wiped Mid-Day by `start_fresh_run()`, Resetting Retry Limits and Displaying `0 / N` Error Retries in the Lane A UI

- **OBSERVATION:**
  1. In [`IntradayService.__init__`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/intraday_service.py#L25-L48), `self.retry_counts` is initialized to `{}` and — unlike `_hydrate_type_b_last_run` and `_hydrate_type_c_ran_today` — is never hydrated from persisted report state (`automations.json` `last_output` / `intraday.json` `reports_ran`).
  2. In [`IntradayService.start_fresh_run`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/services/intraday_service.py#L595), `self.retry_counts.clear()` is executed unconditionally even when `today_date` is already initialized and active on the same day.

- **EVIDENCE:**
  ```text
  $ python artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py
  [F-074] rebooted_flaky=0, rebooted_exhausted=0, after_fresh_flaky=0, after_fresh_exhausted=0 -> FAIL (BUG CONFIRMED)
  ```

- **CONSEQUENCE:**
  If the server is restarted mid-day (or if `start_fresh_run()` is invoked on an already-initialized day), any Lane A report in `"Retrial"` (`"Error (attempt 2/5): ..."`) or `"Failed"` (`"Exceeded max retries (5/5): ..."`) has its retry count reset to `0`, causing the Lane A UI `Error Retries` column (`GET /api/automations`) to display `0 / 5` instead of `2 / 5` or `5 / 5`, and granting mid-retry reports a fresh set of `max_retries` attempts.

- **VERIFICATION CRITERION:**
  `IntradayService` must hydrate `self.retry_counts` on startup for the active day from persisted report state (`"Error (attempt X/Y)"` / `"Exceeded max retries (X/Y)"` in `automations.json` and `day.reports_ran`), and `start_fresh_run()` must only clear `self.retry_counts` when initializing a new/stale day (or preserve existing same-day retry counts just like `start_lane()`).

---

### [F-075] [LOW] Inline `onclick="enableReport('${escapeHtml(item.name)}')"` Handlers Break with `SyntaxError` When a Report Name Contains an Apostrophe (`'`)

- **OBSERVATION:**
  In [`paradiso/web/static/js/app.js`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/static/js/app.js#L725-L728) (`renderDashboardTable`), [`L800`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/static/js/app.js#L800) (`renderLaneATable`), [`L838-L839`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/static/js/app.js#L838-L839) (`renderLaneBTable`), [`L881-L882`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/static/js/app.js#L881-L882) (`renderLaneCTable`), and [`L1068-L1077`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/web/static/js/app.js#L1068-L1077) (`filterAutomationsCatalog`), action buttons are rendered using inline HTML attributes such as:
  `onclick="enableReport('${escapeHtml(item.name)}')"`
  Because the browser decodes HTML entities (`&#39;` $\rightarrow$ `'`) inside HTML event attributes before parsing the JavaScript string literal, any report name containing an apostrophe (e.g. `"Today's Cash Flow"`) produces `enableReport('Today's Cash Flow')`, throwing `Uncaught SyntaxError`.

- **EVIDENCE:**
  ```text
  $ python artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py
  [F-075] vulnerable_inline_onclick_patterns_found=4 -> FAIL (BUG CONFIRMED)
  ```

- **CONSEQUENCE:**
  Clicking `▶ Enable`, `⏸ Disable`, or `🗑 Delete` in the Web UI for any report whose name contains an apostrophe (`'`) fails with a JavaScript `SyntaxError`.

- **VERIFICATION CRITERION:**
  Action buttons in `app.js` must either escape single quotes/backslashes for JS string literals before HTML-escaping (or pass report names via `data-*` attributes / `addEventListener`, as already done for `btn-view-log` at line 2212).

---
## Resolution (2026-10-03 15:18 +08:00)
- F-071..F-074: VERIFIED RESOLVED (PoC 4/4 PASS; run_tests.py 173/173 OK).
- F-075: WAIVED (operator naming convention).
- Residual notes: ExecutionService stale guard keys on 'Waiting'/'Stopped by user' sentinel; Runner.log_dir is shared mutable state.
