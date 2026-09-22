# Developer Session Context — Paradiso

**Date:** 2026-09-23  
**Role:** Primary Engineering and Implementation Agent ("Builder")  
**Application:** Paradiso daemon scheduling engine & Web UI (Type A sequential intraday reporting pipelines)  
**Location:** `artifacts/dev/dev_session_context.md`  

---

## 1. Operating Rules & Mandate Summary

As specified in [`artifacts/dev/dev.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/dev/dev.md):
1. **Change Authorization (Hard Requirement):**
   - **No code or project files may be modified without an explicit GO signal from the user.**
   - Pre-GO actions are strictly limited to inspection, analysis, root cause diagnosis, and proposing implementation plans.
2. **Authorized Scope:**
   - Permitted: `paradiso/`, `artifacts/dev/`, `tests/`, `README.md`, `session_context.md`, `reports/`.
   - **Strictly Read-Only / Immutable:** `artifacts/audits/` (auditor findings and reproduction scripts).
3. **Auditor Independence:**
   - Auditor findings are evidence/hypotheses to investigate, NOT implementation instructions.
   - All root causes and solutions must be independently designed, verified, and tested.
4. **Architectural Philosophy:**
   - Prioritize dead-simple, unbreakable walls over clever workarounds.
   - Bank-grade zero tolerance: no silent closures, strict receipt contracts for pipeline reports.

---

## 2. System Architecture & Core Invariants

### 4-Tier Architecture
```mermaid
graph TD
    UI[Web UI (app.js, index.html)] -->|REST APIs| Controllers[Controllers Layer]
    Controllers --> Services[Services Layer (IntradayService, AutomationService, ExecutionService)]
    Services --> Storage[Storage Repositories (StorageBase)]
    Services --> Runner[Runner Engine (Process Supervision)]
    Storage --> AutoJSON[(automations.json)]
    Storage --> IntradayJSON[(intraday.json)]
    Clock[Clock Subsystem (utils/clock.py)] -.-> IntradayService
    Config[Config Subsystem (utils/config.py)] -.-> Services
```

### Intraday State Machine (24-Hour Cycle)
- `00:00 – 06:59` (`WAITING_TO_OPEN`): Day reset; report statuses reset to `Waiting`.
- `07:00 – 20:59` (`OPEN`): Queue opens; strict sequential 1-at-a-time execution from `waitlist`.
- `21:00 – 21:59` (`WAITING_TO_CLOSE`): Queue stops launching new reports; in-flight tasks complete naturally.
- `22:00 – 23:59` (`CLOSED`): Hard cutoff; in-flight processes killed (`runner.kill_all()`), remaining reports marked `Failed`.

### Key Business & Queue Rules
- **The Receipt Contract:** Every pipeline report must write its structured JSON receipt to `paradiso/logs/{name}.json` (or `{name}_*.json`). Scripts that exit without writing a receipt are rejected as **Contract Violations** and failed after `max_retries`.
- **Dependency Skips:** When a report outputs `SKIPPED` or dumps `status: Retrial`, it rotates to the back of `waitlist` with zero retry penalty.
- **Failures / Crashes:** Genuine non-dependency errors increment `retry_counts` up to `max_retries` (default: 3) before terminal `Failed` state.
- **Atomic Persistence:** All storage operations use `StorageBase.mutate()` with re-entrant locking and atomic replace (`os.replace`).

---

## 3. Audit Findings Status Registry

Based on [`artifacts/audits/ongoing/audit_20260922_0054.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260922_0054.md):

| Finding | Severity | Category | Status | Summary & Verification |
|---|---|---|---|---|
| **F-001** | CRITICAL | QUEUE | **RESOLVED** | Deleting an executing report caused permanent queue deadlock. Resolved via 409 guard in `AutomationController.delete_automation` when scheduler is active, plus fail callback in `ExecutionService.execute_report`. Verified in `tests/test_audit_fixes.py`. |
| **F-002** | CRITICAL | SECURITY | **RESOLVED** | Arbitrary script execution via unsanitized `dir`/`filename` in `/api/automation/add`. Resolved with `ALLOWED_DIRS` check, filename path traversal checks, and execution path defense-in-depth. Verified in `tests/test_audit_fixes.py`. |
| **F-003** | HIGH | SECURITY | **RESOLVED** | Unvalidated interpreter paths in `/api/settings` allowed arbitrary host binary execution. Resolved via strict filename pattern matching (`python*`, `rscript*`) and file existence checks in `validate_config()` and defense-in-depth in `Runner`. Verified in `tests/test_audit_fixes.py`. |
| **F-004** | HIGH | QUEUE | **RESOLVED** | Bank-grade receipt contract enforcement: logs locked strictly to `paradiso/logs`, script-dumped logs preserved, zero retry penalty on dependency skips, contract violators routed to failure without infinite queue loops, `ReportLog.clean_slate()` and `has_valid_receipt()` supporting dated receipts, DRY `is_dependency_skip`, and documented in `TECHNICAL_DOCUMENTATION.md` Section 12. Verified across 63 tests and `poc_f004_verification.py`. |
| **F-005** | HIGH | QUEUE | **RESOLVED** | Unbounded fast-spinning on dependency starvation caused timeline and disk write amplification. Resolved by introducing queue pass tracking and starvation cooldown (pausing pops when all pass items skip) and deduplicating timeline rotation events. Verified in `tests/test_audit_fixes.py`. |
| **F-006** | HIGH | CONCURRENCY | **OPEN** | Process watcher suppression vulnerability due to CPython `id(process)` heap memory address reuse. Solution designed: object attribute stamping (`_was_killed = True`) + monotonic integer launch IDs. |
| **F-007** | HIGH | STORAGE | **OPEN** | Storage corruption causes runaway `.bak` file generation flood on active 0.5s scheduler loop. Requires deduplication by file mtime/hash. |
| **F-008** | MEDIUM | PROCESS | **OPEN** | Child process trees survive `Runner.kill_all()` on Windows. Requires `taskkill /F /T /PID` on `win32`. |
| **F-009** | MEDIUM | CONCURRENCY | **OPEN** | Concurrent `POST /api/paradiso/start` calls spawn duplicate scheduler loops. Requires synchronization lock guarding `start()`, `start_daemon()`, `stop()`. |
| **F-010** | MEDIUM | STATE MACHINE | **OPEN** | Midnight rollover resets running reports and duplicates queue entries. Requires excluding `self.current_runs` from the new day's initial `Waiting` batch and waitlist. |
| **F-011** | LOW | UI | **OPEN** | 1-second unpaginated timeline polling in `app.js` and hardcoded `"countdown": "32 min"` in `DashboardController.get_stats()`. |
| **F-012** | LOW | DOC-DRIFT | **OPEN** | Documentation claims `/api/dashboard/timeline` returns newest-first (actually returns chronological/oldest-first); unlisted endpoints (`disable_automation`, `system-status`). |

---

## 4. Current State of Blueprints & UI
- **Web UI:** Renamed all occurrences of `PARADISO ALTER` to `PARADISO` in `index.html` (title, sidebar brand, Gabriel card).
- **Blueprints:** `reports/sample_report_blueprint.py` (Python) and `reports/sample_report_blueprint.R` (R base) are standalone templates with zero CLI args, writing structured receipts directly to `paradiso/logs/{REPORT_NAME}.json`.
- **Documentation:** `paradiso/TECHNICAL_DOCUMENTATION.md` updated with Section 12 formally establishing the Receipt Contract.

---

## 5. Next Steps for Tomorrow (Phase 4: F-006)
1. **Target:** `paradiso/services/runner.py` (and test suite `paradiso/tests/test_audit_fixes.py`).
2. **Issue:** CPython heap address recycling causes newly launched processes to share memory addresses with killed processes, leading to watcher suppression and permanent queue deadlock.
3. **Proposed Fix:**
   - Stamp `process._was_killed = True` directly on `subprocess.Popen` instances before killing.
   - Maintain a monotonic integer execution counter `self._exec_counter` (`1, 2, 3...`) passed to `_watcher`.
   - Discard `id(process)` completely.

---

## 6. Verification Commands
- **Full Test Suite:** `py -3 -m unittest discover tests` (inside `paradiso/`, 63 passing)
- **Adversarial Verification:** `py -3 paradiso/artifacts/audits/poc/poc_f004_verification.py` (4 passing)
