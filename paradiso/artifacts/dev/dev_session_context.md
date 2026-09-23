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
5. **Legacy Test Integrity Protection (Hard Invariant):**
   - Legacy test suites (`tests/test_api.py`, `tests/test_services.py`, `tests/test_settings.py`, `tests/test_storage.py`) are strictly read-only and immutable.
   - Do NOT modify legacy test files under any circumstances without explicit user authorization.
   - All new remediation and audit fix verification tests reside exclusively in `tests/test_audit_fixes.py`.

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
| **F-006** | HIGH | CONCURRENCY | **RESOLVED** | Process watcher suppression vulnerability due to CPython `id(process)` heap memory address reuse. Resolved via direct object attribute stamping (`_was_killed = True`) and monotonic integer launch IDs (`_exec_counter` / `killed_exec_ids`). Verified in `tests/test_audit_fixes.py`. |
| **F-007** | HIGH | STORAGE | **RESOLVED** | Storage corruption causes runaway `.bak` file generation flood on active 0.5s scheduler loop. Resolved via in-memory `(mtime_ns, size)` deduplication cache, byte-for-byte disk match detection, and 5-file retention pruning in `StorageBase`. Verified in `tests/test_audit_fixes.py`. |
| **F-008** | MEDIUM | PROCESS | **RESOLVED** | Child process trees survive `Runner.kill_all()` on Windows. Resolved via `taskkill /F /T /PID` tree-kill and synchronous `wait(timeout=1.0)` in `Runner.kill_all()`. Verified in `tests/test_audit_fixes.py`. |
| **F-009** | MEDIUM | CONCURRENCY | **RESOLVED** | Concurrent `POST /api/paradiso/start` calls spawn duplicate scheduler loops. Resolved via `_lifecycle_lock` re-entrant mutex, pre-check before `start_fresh_run()`, synchronous thread join, and fresh stop events. Verified in `tests/test_audit_fixes.py`. |
| **F-010** | MEDIUM | STATE MACHINE | **RESOLVED** | 22:00 cutoff forcibly kills lingering running tasks with `runner.kill_all()`, logs them as `Failed`, clears `current_runs` and `waitlist`. Midnight rollover cleans stray runs defense-in-depth and initializes new day cleanly. Verified in `tests/test_audit_fixes.py`. |
| **F-011** | LOW | UI | **RESOLVED** | Removed static mock `"countdown": "32 min"` placeholder from `DashboardController.get_stats()`. Decoupled `fetchTimeline()` to 5-second polling interval in `app.js` with server-side `?limit=50`. Added client-side time pre-validation in `handleSettingsSubmit`. Added `?limit=N` and `?order=asc|desc` support to `DashboardController.get_timeline()`. Verified in `tests/test_audit_fixes.py`. |
| **F-012** | LOW | DOC-DRIFT | **RESOLVED** | Updated Section 9 in `TECHNICAL_DOCUMENTATION.md` to document default chronological (oldest-first) timeline ordering with `?limit=N` and `?order=asc|desc` query parameters, and documented active endpoints `POST /api/automation/disable` and `GET /api/dashboard/system-status`. Verified in `tests/test_audit_fixes.py`. |
| **F-013** | HIGH | STORAGE / QUEUE | **RESOLVED** | Active automation broken due to deleted report script (`0base_auto.py`). Resolved by updating `storage/automations.json` to point to authorized blueprint `sample_report_blueprint.py` with clean initial state. |
| **F-014** | LOW | CONCURRENCY | **RESOLVED** | Blocking `process.wait(timeout=1.0)` held under `_proc_lock` in `kill_all()`. Resolved by moving the process wait loop outside the `_proc_lock` scope, reducing lock hold time to $< 1$ms. Verified across full test suite and adversarial PoC. |
| **BG-001** | HIGH | SECURITY / INTEGRITY | **RESOLVED** | **Idle-Only Configuration Guardrail:** Enforced HTTP 409 Conflict in `SettingsController.update_settings` when scheduler is active or jobs are in flight. Disabled Save button and displayed amber alert banner in Web UI. Verified in `tests/test_audit_fixes.py`. |
| **BG-002** | HIGH | STABILITY / CONCURRENCY | **RESOLVED** | **Start/Stop Transition Cooldown & Mutex Guard (dovetails with F-009):** Enforced `_lifecycle_lock` and 10-second transition cooldown on `/api/paradiso/start` and `/api/paradiso/stop` rejecting rapid calls with HTTP 429 and disabling UI action buttons with a 10-second countdown indicator. Verified in `tests/test_audit_fixes.py`. |

---

## 4. Current State of Blueprints & UI
- **Web UI:** Renamed all occurrences of `PARADISO ALTER` to `PARADISO` in `index.html` (title, sidebar brand, Gabriel card). Added 10-second transition cooldown and settings lock banner with button disablement.
- **Blueprints:** `reports/sample_report_blueprint.py` (Python) and `reports/sample_report_blueprint.R` (R base) are standalone templates with zero CLI args, writing structured receipts directly to `paradiso/logs/{REPORT_NAME}.json`.
- **Documentation:** `paradiso/TECHNICAL_DOCUMENTATION.md` updated with Section 12 formally establishing the Receipt Contract.

---

## 5. Phase 9 Resolution: F-011 & F-012
1. **F-011 (UI Polling Backoff & Dead Mock Countdown Removal):**
   - In `paradiso/controllers/dashboard_controller.py`: Removed dead static mock `"countdown": "32 min"` placeholder from `next_scheduled` in `get_stats()`. Added support for query parameters `?limit=N` and `?order=asc|desc` in `get_timeline()`.
   - In `paradiso/web/static/js/app.js`: Decoupled `fetchTimeline()` from 1-second interval to a dedicated 5-second interval (`5000ms`), requesting `/api/dashboard/timeline?limit=50`. Added client-side time pre-validation in `handleSettingsSubmit()`.
2. **F-012 (Documentation Drift Correction):**
   - In `paradiso/TECHNICAL_DOCUMENTATION.md`: Corrected Section 9 REST API table to accurately describe `GET /api/dashboard/timeline` chronological (oldest-first) default ordering with `?limit=N` and `?order=asc|desc` query parameters. Added documentation for `POST /api/automation/disable` and `GET /api/dashboard/system-status`.

---

## 6. Verification Commands
- **Full Test Suite:** `py -3 -m unittest discover tests` (inside `paradiso/`, 75 passing, 0 failures)
- **Adversarial Verification Suites:**
  - `py -3 paradiso/artifacts/audits/poc/poc_bg001_bg002_verification.py` (6 passing)
  - `py -3 paradiso/artifacts/audits/poc/poc_f007_verification.py` (4 passing)
  - `py -3 paradiso/artifacts/audits/poc/poc_f006_f008_verification.py` (3 passing)
  - `py -3 paradiso/artifacts/audits/poc/poc_f004_verification.py` (4 passing)
  - `py -3 paradiso/artifacts/audits/poc/poc_f010_verification.py` (5 passing / defect eliminated)

---

## 7. Developer Handover Dossier

### 7.1 Current System State & Status
- **Progress:** All 14 audit findings are completely **RESOLVED and VERIFIED** (F-001 through F-014, BG-001, BG-002).
- **Test Integrity:** 75/75 unit tests passing in ~5.3s. All legacy test files (`tests/test_api.py`, `tests/test_services.py`, `tests/test_settings.py`, `tests/test_storage.py`) are **strictly frozen and untouched**.
- **Audit Files:** The `artifacts/audits/` directory is **strictly read-only**.

### 7.2 Core Architectural Invariants Enforced
1. **The Receipt Contract (F-004):** Reports must write receipts to `paradiso/logs/{name}.json` (or `{name}_*.json`). Scripts exiting without receipts are contract violations and route to failure after retries. Dependency skips dumped by scripts rotate with zero retry penalty.
2. **Process Watcher Identification (F-006):** Uses monotonic launch integer `_exec_id` and stamps `_was_killed = True` directly onto `Popen` objects, eliminating CPython heap address reuse bugs.
3. **Windows Subprocess Tree Termination (F-008):** `Runner.kill_all()` invokes `taskkill /F /T /PID` to eliminate parent, child, and grandchild trees on Windows, followed by synchronous `wait()` outside `_proc_lock` (F-014).
4. **Storage Rescue Deduplication (F-007):** Two-tier `(mtime_ns, size)` cache and latest `.bak` byte matching prevent runaway backup floods during storage corruption, retaining at most 5 latest `.bak` files.
5. **Lifecycle Mutex & 10s Cooldown (BG-002 & F-009):** `Paradiso` guards `start()`, `start_daemon()`, and `stop()` with `_lifecycle_lock`. A 10-second transition cooldown is enforced (HTTP 429 on rapid toggles), and `start()` checks `is_running()` before touching `start_fresh_run()`, preventing in-flight job resets.
6. **Idle-Only Settings Guardrail (BG-001):** `POST /api/settings` returns HTTP 409 Conflict if the scheduler is active or jobs are in flight. The Web UI disables the Save button with an amber banner.
7. **22:00 Cutoff Hard Kill & Clean Midnight Rollover (F-010):**
   - At 22:00 cutoff (`_close_day`), all active tasks in `current_runs` (including re-runs) are killed and marked `Failed` (`"Forcibly terminated: breached 10:00 PM cutoff"`).
   - In `tick()`, `is_new_day = (today_date != self._active_date)` triggers full rollover even if tomorrow's date record already exists in storage, clearing stray runs and resetting automations to `"Waiting"`.
8. **UI Polling Rate, Timeline Pagination & API Alignment (F-011 & F-012):**
   - Mock `"countdown": "32 min"` eliminated from `DashboardController.get_stats()`.
   - Timeline polling throttled to 5s in UI with `limit=50`. Controller supports `?limit=N` and `?order=asc|desc`.
   - Documentation accurately reflects chronological ordering and catalogs all active endpoints (`/api/automation/disable`, `/api/dashboard/system-status`).

### 7.3 Operating Mandate Reminder
- **Never modify project files without explicit user GO.**
- **Never modify legacy test files.** Add tests only to `paradiso/tests/test_audit_fixes.py`.
- **Never edit anything inside `artifacts/audits/`.**

