# Auditor Session Context (`auditor_session_context.md`)

**Last Updated:** `2026-10-03 14:30:00 +08:00`  
**Role:** Sovereign Box-Office Auditor (Read-Only Mandate)

---

## 1. Current Audit State
- **Active Batch:** Batch 16 (Laser-Focused Lane A Audit — `F-071` through `F-075`)
- **Active Ongoing Report:** [`paradiso/artifacts/audits/ongoing/audit_20261003_1430.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20261003_1430.md)
- **Active PoC Script:** [`paradiso/artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/poc/poc_f071_f075_lane_a_laser_audit.py) (`5/5 FAIL`)
- **Historical Resolved Findings:** `F-001` through `F-070` (70/70 archived in `paradiso/artifacts/audits/resolved/`).

## 2. Summary of Active Open Findings (`F-071`–`F-075`)
1. **`F-071` (HIGH):** UI/API default script directory (`../reports/python` and `../reports/r`) conflicts with the actual `../reports` directory where all shipped scripts live AND conflicts with `sample_report_blueprint.py` / `sample_report_blueprint.R` / User Guide receipt path resolution (`Path(__file__).resolve().parent.parent / "paradiso" / "logs"`), which writes receipts to `<workspace>/reports/paradiso/logs/` when placed in `reports/python/` or `reports/r/`, causing every execution to fail with `"Contract violation"`.
2. **`F-072` (HIGH):** (a) In `IntradayService._trigger_report._handle_failure`, `if attempts < self.max_retries and scheduler_is_active:` evaluates to `False` during `21:00–22:00` (`WAITING_TO_CLOSE`), causing an in-flight Lane A report that fails on Attempt `1` of `5` at `21:02` to be falsely marked `"Failed: Exceeded max retries (1/5)"` (`"{name} permanently failed"`). (b) Neither `_on_good` nor `_on_fail` checks `if name not in self.current_runs: return` under `self._lock`, so a process exiting simultaneously with `stop_lane("type_a")`, `reset_all_reports()`, `_close_day()`, or midnight rollover overwrites the stopped/reset state.
3. **`F-073` (MEDIUM):** `ReportLog.from_json()` does not case-normalize receipt `status` strings (`"completed"` vs `"Completed"`, `"failed"` vs `"Failed"`), causing `ExecutionService` to mark a `"status": "completed"` report as `"Completed"` while `IntradayService._on_good` treats it as a failure (`"Retrial"`/`"Failed"`). Additionally, `ReportLog.has_valid_receipt()` only checks `st_size > 0`, allowing corrupted/non-JSON receipts to fall back to `"Completed"`.
4. **`F-074` (MEDIUM):** `IntradayService` never hydrates `self.retry_counts` from persisted state on server restart and `start_fresh_run()` unconditionally clears `self.retry_counts` mid-day, resetting retry limits and showing `0 / N` in the Lane A UI `Error Retries` column.
5. **`F-075` (LOW):** Inline `onclick="enableReport('${escapeHtml(item.name)}')"` handlers in `app.js` break with `Uncaught SyntaxError` when a report name contains an apostrophe (`'`).
