# Resolved Findings Registry — Paradiso

**Date:** 2026-09-25 23:05 (Local Time)  
**Auditor:** Independent Adversarial Auditor  
**Location:** `artifacts/audits/resolved/resolved_findings_registry.md`

---

## 1. ARCHIVED AUDIT REPORTS INDEX

The following historical audit reports have had all reported findings independently verified as resolved and have been archived in this directory pursuant to Section 12 of `AUDITOR.md`:

| Report File | Scope / Focus | Primary Findings Addressed | Archive Status |
|---|---|---|---|
| [`audit_20260922_0054.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260922_0054.md) | Initial comprehensive adversarial audit | F-001 through F-009 | **RESOLVED & ARCHIVED** |
| [`audit_20260923_1315.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260923_1315.md) | Remediation verification pass | F-001 - F-009 initial fixes | **RESOLVED & ARCHIVED** |
| [`audit_20260923_1350.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260923_1350.md) | Secondary hardening & regression audit | BG-001, BG-002, F-011 - F-014 | **RESOLVED & ARCHIVED** |
| [`audit_20260923_1440_f010.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260923_1440_f010.md) | Dedicated F-010 deep-dive & race audit | F-010 (midnight & 22:00 cutoff) | **RESOLVED & ARCHIVED** |
| [`audit_20260924_1005.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260924_1005.md) | Housekeeping & project hygiene audit | F-015 through F-019 | **RESOLVED & ARCHIVED** |
| [`audit_20260924_1130.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260924_1130.md) | Verification of F-015 - F-019 remediations | F-015 through F-019 verification | **RESOLVED & ARCHIVED** |
| [`audit_20260924_1515.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260924_1515.md) | Testing Lab UI segregation & production cleanup | F-020 (Testing Lab segregation) | **RESOLVED & ARCHIVED** |
| [`audit_20260925_0830.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/audit_20260925_0830.md) | 3-Lane Scheduling Engine comprehensive audit | F-021 through F-024 (initial findings) | **RESOLVED & ARCHIVED** |
| [`audit_20260925_0850.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260925_0850.md) | Verification of F-021 - F-024 remediations | F-021 through F-024 verification | **RESOLVED & ARCHIVED** |
| [`audit_20260925_2245.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260925_2245.md) | Unified execution window audit & defeat device discovery | F-025 through F-027 (initial findings) | **RESOLVED & ARCHIVED** |
| [`audit_20260925_2305.md`](file:///c:/Users/desktop/Documents/work\celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260925_2305.md) | Verification of F-025 - F-027 remediations | F-025 through F-027 verification | **RESOLVED & ARCHIVED** |
| [`audit_20260926_0055.md`](file:///c:/Users/desktop/Documents/work\celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260926_0055.md) | Midnight rollover & Concurrency expansion audit | F-028 through F-030 initial findings | **RESOLVED & ARCHIVED** |
| [`audit_20260926_0730.md`](file:///c:/Users/desktop/Documents/work\celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260926_0730.md) | Batch 4 Adversarial Audit: Cold boot & lifecycle leakage | F-031 through F-034 initial findings | **RESOLVED & ARCHIVED** |
| [`audit_20260928_1945.md`](file:///c:/Users/desktop/Documents/work\celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260928_1945.md) | Batch 5 Remediation Audit: Heuristic & window leakage | F-032, F-035, F-033, F-036 verification | **RESOLVED & ARCHIVED** |
| [`audit_20260928_2030.md`](file:///c:/Users/desktop/Documents/work\celestial_rose/paradiso/artifacts/audits/ongoing/audit_20260928_2030.md) | Milestone P2.2 Investigation: Catch-up policies & timeslots | F-037 through F-039 verification | **RESOLVED & ARCHIVED** |

---

## 2. RESOLVED FINDINGS MASTER INDEX

| ID | Severity | Category | Invariant | Title | Resolution Verification |
|---|---|---|---|---|---|
| **F-001** | CRITICAL | QUEUE | I-1, I-8 | Deletion of running automation causes permanent queue deadlock | Verified in `tests/test_audit_fixes.py` & `poc_f001_verification.py` |
| **F-002** | CRITICAL | SECURITY | I-9 | Arbitrary script execution via path traversal in `/api/automation/add` | Verified in `tests/test_audit_fixes.py` & `poc_f002_verification.py` (14 attacks blocked) |
| **F-003** | HIGH | SECURITY | I-9 | Unvalidated interpreter paths in `/api/settings` allow arbitrary host execution | Verified in `tests/test_audit_fixes.py` & `poc_f003_verification.py` (6 attacks blocked) |
| **F-004** | HIGH | QUEUE | I-2, I-8 | Dependency skip exit code 1 retried as failure and log receipts clobbered | Verified in `tests/test_audit_fixes.py` & `poc_f004_verification.py` (4 passing tests) |
| **F-005** | HIGH | QUEUE | I-2, I-6 | Fast-spinning dependency starvation causes timeline & storage write flood | Verified in `tests/test_audit_fixes.py` (`test_f005_dependency_starvation_pauses_queue`) |
| **F-006** | HIGH | CONCURRENCY | I-5, I-8 | Process watcher suppression via CPython heap address reuse (`id(process)`) | Verified in `tests/test_audit_fixes.py` & `poc_f006_f008_verification.py` |
| **F-007** | HIGH | STORAGE | I-6 | Storage corruption runaway `.bak` file flood deduplication | Verified in `tests/test_audit_fixes.py` & `poc_f007_verification.py` (4 passing tests) |
| **F-008** | MEDIUM | PROCESS | I-5 | Child process trees survive `Runner.kill_all()` on Windows | Verified in `tests/test_audit_fixes.py` & `poc_f006_f008_verification.py` |
| **F-009** | MEDIUM | CONCURRENCY | I-1, I-3 | Concurrent `POST /api/paradiso/start` spawns duplicate scheduler loops | Verified in `tests/test_audit_fixes.py` & `poc_bg001_bg002_verification.py` |
| **F-010** | MEDIUM | STATE MACHINE | I-3, I-4 | Midnight rollover duplicates queue entries & in-flight cutoff termination | Verified in `tests/test_audit_fixes.py` & `poc_f010_verification.py` (5 passing tests) |
| **F-011** | LOW | UI | I-7 | 1-second unpaginated timeline polling & hardcoded dashboard countdown | Verified in `tests/test_audit_fixes.py` (`test_f011_*`) |
| **F-012** | LOW | DOC-DRIFT | I-7 | Documentation drift on timeline ordering & undocumented API endpoints | Verified in `tests/test_audit_fixes.py` (`test_f012_*`) |
| **F-013** | HIGH | STORAGE / QUEUE | I-8 | Active automation broken due to deleted report script (`0base_auto.py`) | Migrated `"SF Base"` to `sample_report_blueprint.py` in `automations.json` |
| **F-014** | LOW | CONCURRENCY | I-11 | Blocking `process.wait(timeout=1.0)` held under `_proc_lock` in `kill_all()` | Moved `wait()` loop outside `_proc_lock`, reducing hold time to $< 1\text{ms}$ |
| **BG-001** | HIGH | SECURITY / INTEGRITY | I-7, I-9 | Idle-Only Configuration Guardrail: Settings mutation while scheduler active | Verified in `tests/test_audit_fixes.py` & `poc_bg001_bg002_verification.py` (HTTP 409 Conflict) |
| **BG-002** | HIGH | STABILITY / CONCURRENCY | I-1, I-3 | Start/Stop Transition Cooldown & Mutex Guard | Verified in `tests/test_audit_fixes.py` & `poc_bg001_bg002_verification.py` (HTTP 429 Cooldown) |
| **F-015** | LOW | RECEIPT CONTRACT | I-7, I-8 | Receipt JSON field divergence between spec and report scripts | Dual-path support in `ReportLog.from_json()` & canonical keys in scripts; verified in `test_f015_*` |
| **F-016** | MEDIUM | TEST HYGIENE | I-6, I-8 | Synthetic future test dates (`2048-xx-xx`) in live storage | `storage/intraday.json` purged of 2048 records; PoCs and tests sandboxed; verified in `test_f016_*` |
| **F-017** | LOW | LOG HYGIENE | I-7, I-8 | Test receipt contamination of production `paradiso/logs/` | `PARADISO_LOGS_DIR` isolation across test fixtures; 8 debris logs purged; verified in `test_f017_*` |
| **F-018** | LOW | REPO HYGIENE | I-9 | Missing `.gitignore` & tracked bytecode cache (`.pyc`) | Root `.gitignore` created; `.pyc` untracked from git index; verified in `test_f018_*` |
| **F-019** | LOW | DOC-DRIFT | I-7 | Missing `run_tests.py` entry point & outdated 48-test doc count | `run_tests.py` created at root and `paradiso/`; doc updated to 82 tests; verified in `test_f019_*` |
| **F-020** | LOW | UI / SAFETY | I-7, I-9 | Segregation of testing controls into unified Testing Lab UI | Segregated `#view-testing` tab, live mode badge, top-bar reset removal; verified in `test_f020_*` |
| **F-021** | CRITICAL | RECEIPT CONTRACT | I-7, I-8 | Exact receipt naming mismatch in Type B & C pipeline scripts | Emitted exact registered filenames with spaces; verified in `poc_f021_f024_verification.py` & `test_f021_*` |
| **F-022** | HIGH | QUEUE & CONCURRENCY | I-2, I-6 | Unbounded 500ms rapid spin on dependency skips across Lane B and Lane C | Lane B interval stamping + Lane C 5m backoff cooldown; verified in `poc_f021_f024_verification.py` & `test_f022_*` |
| **F-023** | HIGH | SECURITY & INTEGRITY | BG-001, I-7, I-9 | BG-001 Settings guardrail bypassed during Lane B or Lane C runs | Multi-lane `has_active_runs` enforcement (HTTP 409); verified in `poc_f021_f024_verification.py` & `test_f023_*` |
| **F-024** | LOW | API CONTRACT | I-7 | Input validation laxity on lane names in `lane_start` and `lane_stop` | `VALID_LANES` strict whitelist with HTTP 400 Bad Request; verified in `poc_f021_f024_verification.py` & `test_f024_*` |
| **F-025** | CRITICAL | SECURITY / TEST-GAP | I-3, I-7, I-9 | Hardcoded test defeat device in `Clock._get_sim_now()` inspecting `sys.argv` | Excised `sys.argv` inspection; verified in `poc_f025_clock_defeat_device.py` & `test_f025_*` |
| **F-026** | HIGH | STATE MACHINE / API | I-3, I-7 | Silent out-of-window stall on independent lane starts outside `OPEN` | Enforced HTTP 409 Conflict guard on `lane_start` with `force_open` override; verified in `poc_f026_*` |
| **F-027** | LOW | DOC-DRIFT | none | Documentation drift on Lane C EOD timeslot: Section 1 (21:00) vs Section 3 (20:30) | Section 1 updated to `20:30` matching storage and logic; verified in `test_f027_*` |
| **F-028** | CRITICAL | STORAGE / STATE-MACHINE | I-4, I-6, I-8 | Pre-existing Finalized Day Record in Storage Paralyses Daily Execution | Cleanse stale records via `_get_or_init_day()`; verified in `poc_f028_*` & `test_f028_*` |
| **F-029** | HIGH | STATE-MACHINE / CONCURRENCY | I-1, I-4 | Mid-Day Process Restart Causes Duplicate Execution of Lane C Timeslot Reports | Hydrate `type_c_ran_today` from `day.reports_ran`; verified in `poc_f029_*` & `test_f029_*` |
| **F-030** | MEDIUM | UI / HONEST API | I-7 | Web UI Silently Swallows HTTP 409 Intraday Window Rejection on Lane Start | Universal `showToast()` defined in `app.js`; verified in `test_f030_*` |
| **F-031** | CRITICAL | COLD BOOT & STORAGE LEAK | I-1, I-4 | Cold Boot Lane C Catalog Leak Suppresses Daily Timeslot Execution | Removed catalog iteration from `_hydrate_type_c_ran_today()`; verified in `test_f031_*` |
| **F-032** | CRITICAL | STORAGE / QUEUE | I-4, I-6, I-8 | Partial-Day Storage Paralysis & Failure Log Erasure | Implemented `_get_completed_or_exhausted_reports()`; verified in `test_f032_*` |
| **F-033** | HIGH | STATE MACHINE / API | I-3, I-7 | Sticky `force_open` Cutoff Bypass & Cross-Lane Start Leakage | `WAITING_TO_CLOSE` precedence in `resolve_status()` & per-lane gating; verified in `test_f033_*` |
| **F-034** | MEDIUM | PROCESS ORPHANING | I-5, I-8, BG-001 | Deleting Actively Executing Type B/C Reports Allowed | Added `is_running` guard returning HTTP 409 Conflict; verified in `test_f034_*` |
| **F-035** | CRITICAL | TIME SYNTHESIS / DISPATCH | I-1, I-4 | Cold Boot Lane B Time-Only `last_run` Synthesizes Future Timestamp | Shifted non-today catalog timestamps to historical in `_hydrate_type_b_last_run()`; verified in `test_f035_*` |
| **F-036** | MEDIUM | API / QUEUE HYGIENE | I-7, I-8 | Asymmetric Automation Disabling Forces Destructive Queue Resets | Implemented `POST /api/automation/enable` endpoint; verified in `test_f036_*` |
| **F-037** | CRITICAL | INPUT VALIDATION & STABILITY | I-1, I-7, I-9 | Non-Canonical `scheduled_time` Strings Cause Unhandled Crashes or Starvation | Regex 24-hr `HH:MM` validation in API + defensive `_normalize_timeslot` in `tick()`; verified in `poc_f037_f039_verification.py` & `test_f037_*` |
| **F-038** | MEDIUM | API & CONTRACT INTEGRITY | I-7, I-8 | `POST /api/automation/add` Silently Discards `catch_up_policy` Parameter | Parameter extraction, validation, and persistence in `Report`; verified in `poc_f038_catch_up_policy_dropped_in_api.py` & `test_f038_*` |
| **F-039** | MEDIUM | STATE MACHINE & NOTIFICATIONS | I-4, I-7, I-8 | `reset_all_reports()` Fails to Clear `self.type_c_warned` | Added `self.type_c_warned.clear()` to `reset_all_reports()`; verified in `poc_f039_reset_all_reports_type_c_warned_retention.py` & `test_f039_*` |
| **F-040** | HIGH | SAFETY & STATE HYGIENE | I-7, I-8 | `POST /api/automation/run` Bypasses "Disabled" State | HTTP 409 guard in controller + False in service; verified in `test_f040_*` |
| **F-041** | CRITICAL | DISPATCH & RESOURCE EXHAUSTION | I-1, I-6 | Lane B Dispatches Permanently Failed Reports in Unbounded Infinite Loop | `type_b_exhausted` + retry budget check in `tick()`; verified in `test_f041_*` |
| **F-042** | MEDIUM | CLOCK INTEGRITY & GUARDRAILS | BG-001, I-3, I-7 | `POST /api/settings/simulation/reset` Bypasses BG-001 Idle-Only Guardrail | Multi-lane active check returning HTTP 409 Conflict; verified in `test_f042_*` |
| **F-043** | MEDIUM | DISPATCH & STATE INTEGRITY | I-1, I-8 | Manual Run of Failed Lane B Report Silently Re-Arms Automatic Dispatch | HTTP 409 guard on Failed/exhausted runs + enable required; verified in `test_f043_*` |

---

## 3. SUMMARY OF RESOLUTION DETAILS

### F-001: Deletion Deadlock
- **Mechanism:** Added HTTP 409 Conflict guard in `AutomationController.delete_automation` while scheduler is active, plus fail-safe callback triggering in `ExecutionService.execute_report` if an automation is removed while queued.
- **Evidence:** Queue continues sequential processing without hung states. Verified in `poc_f001_verification.py`.

### F-002: Arbitrary Script Execution (Path Traversal)
- **Mechanism:** Strict whitelist check against `ALLOWED_DIRS` (`reports`, `data`, `scripts`), sanitization of `filename` via `os.path.basename` / `Path.name`, and rejection of traversal sequences (`..`).
- **Evidence:** Malicious paths outside authorized directories rejected with HTTP 400. Verified in `poc_f002_verification.py`.

### F-003: Unvalidated Interpreter Paths
- **Mechanism:** In `validate_config()`, interpreter paths must strictly match approved binary naming patterns (`python*`, `rscript*`), exist on the filesystem as regular files, and possess executable permissions.
- **Evidence:** Arbitrary system binaries (`cmd.exe`, `calc.exe`) rejected with HTTP 400. Verified in `poc_f003_verification.py`.

### F-004: Dependency Skip Receipts & Retry Penalties
- **Mechanism:** Established Section 12 Receipt Contract. Consolidated dependency skip heuristics in `ReportLog.is_dependency_skip`. Skips rotate to `Retrial` with zero penalty against `max_retries`. Dumped receipts in `paradiso/logs` preserved on failure instead of being clobbered with generic failure JSON.
- **Evidence:** All 4 attack vectors in `poc_f004_verification.py` pass.

### F-005: Dependency Starvation Fast-Spinning
- **Mechanism:** Added queue pass tracking and starvation cooldown in `IntradayService`. When all remaining waitlist reports skip in a single pass, queue execution pauses until the next tick cycle rather than fast-spinning. Deduplicated timeline rotation entries within cooldown window.
- **Evidence:** Timeline writes drop from thousands per second to 1 per starvation cycle.

### F-006: Process Watcher Suppression (Heap Address Reuse)
- **Mechanism:** Implemented monotonic integer execution IDs (`_exec_counter`, `_exec_id`) and stamped `process._was_killed = True` directly on `Popen` instances. Eliminated `id(process)` and removed fragile name-fallback checks.
- **Evidence:** Killed processes do not suppress subsequent launches of reports with the same name. Verified in `poc_f006_f008_verification.py`.

### F-007: Storage Corruption Backup Flood Deduplication
- **Mechanism:** `StorageBase._global_corrupted_states` caches `(st_mtime_ns, st_size)`. Cold boot scans latest backup and checks byte equality (`latest_bak.read_bytes() == self.file_path.read_bytes()`). Capped backup retention at 5 latest copies.
- **Evidence:** 20 consecutive ticks generate exactly 1 backup; rotation cap preserves exactly 5 files. Verified in `poc_f007_verification.py`.

### F-008: Windows Process Tree Termination
- **Mechanism:** In `Runner.kill_all()`, added `taskkill /F /T /PID <pid>` on Windows with `CREATE_NO_WINDOW`, terminating parent, child, and grandchild trees before calling `process.kill()`.
- **Evidence:** 3-tier deep process trees confirmed dead in Windows `tasklist`. Verified in `poc_f006_f008_verification.py`.

### F-009: Concurrent Start Loops & In-Flight Reset
- **Mechanism:** Guarded `Paradiso` lifecycle with `_lifecycle_lock` re-entrant mutex. Added `is_running()` check before `start_fresh_run()` so in-flight tasks and retry counters are never reset by redundant calls. Replaced cleared event with newly instantiated `threading.Event()`. In `stop()`, synchronously joined loop thread with `join(timeout=2.0)`.
- **Evidence:** 25 concurrent threads trigger strictly 1 loop thread; in-flight jobs and retry counts remain completely intact. Verified in `poc_bg001_bg002_verification.py`.

### F-010: Midnight Rollover & 22:00 Cutoff Process Termination
- **Mechanism:** In `_close_day()`, in-flight jobs (`r.name in running_reports`) are evaluated explicitly, killed via `Runner.kill_all()`, and marked `"Failed"`, regardless of prior executions. In `tick()`, `self._active_date` tracks day changes independently of day record presence in storage.
- **Evidence:** Re-run jobs in-flight at cutoff transition to Failed; crossing midnight into pre-existing day records cleanly clears stray jobs and resets reports. Verified in `poc_f010_verification.py`.

### F-013: Automation Broken by Deleted Script
- **Mechanism:** Re-bound `"SF Base"` in `storage/automations.json` to existing `reports/sample_report_blueprint.py` with clean `"Waiting"` status.
- **Evidence:** Pipeline executes successfully without file-not-found failures.

### F-014: Blocking Lock Hold in `kill_all()`
- **Mechanism:** Moved synchronous `process.wait(timeout=1.0)` reaping loop outside `with self._proc_lock:` critical section.
- **Evidence:** Lock hold time reduced from $N$ seconds to $< 1\text{ms}$.

### BG-001: Idle-Only Configuration Guardrail
- **Mechanism:** Enforced HTTP 409 Conflict in `SettingsController.update_settings` when `self.paradiso.is_running()` or `intraday_service.current_runs` is non-empty. In frontend UI, dynamically displayed an amber configuration locked banner and disabled the "Save Settings" button with a `not-allowed` cursor.
- **Evidence:** Settings mutations strictly blocked during active execution; allowed when idle. Verified in `poc_bg001_bg002_verification.py`.

### BG-002: Start/Stop Transition Cooldown & Mutex Guard
- **Mechanism:** Enforced 10-second transition cooldown on `/api/paradiso/start` and `/api/paradiso/stop`. Rapid calls within cooldown rejected with HTTP 429 and `cooldown_remaining` payload. Frontend UI displays a visual countdown on the button (`⏳ Cooldown (Xs)`) and disables action buttons until expiration.
- **Evidence:** Rapid start/stop cycling blocked with HTTP 429; transitions succeed cleanly upon cooldown expiration. Verified in `poc_bg001_bg002_verification.py`.

### F-011: UI Polling Rate & Dashboard Countdown
- **Mechanism:** Decoupled `fetchTimeline()` from the 1-second polling loop into a dedicated 5-second `setInterval`. Added server-side `?limit=N` and `?order=asc|desc` query parameters to `DashboardController.get_timeline()`. Frontend now requests `?limit=50`. Removed static `"countdown": "32 min"` placeholder from `DashboardController.get_stats()` — `next_scheduled` returns only `name`, `team`, and `scheduled_time`.
- **Evidence:** Timeline polling reduced from 1000ms to 5000ms. Payload bounded to 50 events. No `countdown` field in stats response.

### F-012: Documentation Drift & Endpoint Discovery
- **Mechanism:** Corrected `TECHNICAL_DOCUMENTATION.md` API table: `/api/dashboard/timeline` documented as returning chronological (oldest-first) order by default with `?order=asc|desc` support. Added entries for `/api/dashboard/system-status` and `/api/automation/disable` to the API reference table.
- **Evidence:** Documentation matches implementation. All newly documented endpoints verified functional.

### F-015: Receipt Contract Dual-Path Resolution
- **Mechanism:** Updated `ReportLog.from_json()` to support fallback reads (`data.get("last_run") or data.get("timestamp")`, `data.get("last_output") or data.get("message")`, `data.get("reason") or data.get("message")`). Standardized `reports/credit_risk_monitor.py`, `daily_cash_flow.py`, and `portfolio_summary.py` to write both Section 12 canonical keys and supplementary analyst metadata.
- **Evidence:** `storage/automations.json` populates structured single-line output summaries. Verified in `test_f015_report_log_fallback_keys`.

### F-016: Live Storage Future Date Purge & Complete Isolation
- **Mechanism:** Cleaned `storage/intraday.json` to purge all synthetic future year-2048 records. Refactored all Auditor PoC scripts (`poc_f001_verification.py`, `poc_bg001_bg002_verification.py`, `poc_f010_verification.py`) and unit test fixtures to use `tempfile.TemporaryDirectory` with `create_app(storage_dir=...)` and `PARADISO_STORAGE_DIR`.
- **Evidence:** Live `intraday.json` contains only verified dates (`20260924`, `20260925`, `20260926`). Running test suites leaves zero modification to disk. Verified in `test_f016_intraday_production_storage_no_bogus_future_dates`.

### F-017: Log Directory Isolation & Test Debris Purge
- **Mechanism:** Modified `ReportLog`, `ExecutionService`, and `ExecutionController` to inspect `os.environ["PARADISO_LOGS_DIR"]`. Configured test fixtures to redirect log writing to ephemeral sandboxes. Purged test residue files (`BrokenReport.json`, `EscapedReport.json`, `SpamReport.json`, etc.) from production `paradiso/logs/`.
- **Evidence:** Production `paradiso/logs/` contains only 5 legitimate scheduled pipeline receipts. Full test run causes zero new file creations in `paradiso/logs/`. Verified in `test_f017_report_log_respects_paradiso_logs_dir_and_isolates_production`.

### F-018: Root `.gitignore` & Bytecode Untracking
- **Mechanism:** Added comprehensive `.gitignore` at repository root ignoring `__pycache__/`, `*.pyc`, `*.bak`, `.pytest_cache/`, and ephemeral files. Removed all tracked `.pyc` files from the git index via `git rm --cached`.
- **Evidence:** Git status confirms all bytecode caches untracked and ignored. Verified in `test_f018_gitignore_exists_and_ignores_pycache`.

### F-019: Test Runner Wrapper & Accurate Documentation
- **Mechanism:** Created `run_tests.py` test runner wrapper at repository root and inside `paradiso/`. Updated Section 11 of `TECHNICAL_DOCUMENTATION.md` to accurately document the 82 automated tests and module breakdown.
- **Evidence:** `py -3 run_tests.py` runs cleanly from both root and `paradiso/` executing all 82 unit tests in ~6s. Verified in `test_f019_run_tests_exists_and_docs_test_count_accurate`.

### F-020: Unified Testing Lab UI & Operational Segregation
- **Mechanism:** Excised destructive `Reset (Test)` button from operational top-bar header. Removed simulation controls from General Settings. Created segregated `#view-testing` ("Testing Lab") view with live execution mode badge, simulation configuration card, and state reset card with warning banner. Integrated dual-layer defense (client-side scheduler running check + server-side BG-001 409 Conflict guardrail).
- **Evidence:** Accidental mid-day reset risk eliminated from operational UI. Verified in `tests/test_audit_fixes.py` (`test_f020_unified_testing_ui_segregated_from_production`).

### F-021: Exact Receipt Naming Match in Pipeline Scripts
- **Mechanism:** Updated `REPORT_NAME` inside `reports/hourly_liquidity_feed.py` and `reports/eod_ledger_reconciliation.py` to match exact registered names with spaces (`"Hourly Liquidity Feed"` and `"EOD Ledger Reconciliation"`), preserving 1-to-1 exact matching without backend string transformations.
- **Evidence:** Emitted receipt files match registered catalog keys on disk; `ReportLog.find_latest_log_file()` and `has_valid_receipt()` evaluate to True. Verified in `poc_f021_f024_verification.py` and `test_audit_fixes.py` (`test_f021_pipeline_script_receipt_names`).

### F-022: Dependency Skip Throttling (Lanes B & C)
- **Mechanism:** In Lane B (`_trigger_type_b_report`), recorded `self.type_b_last_run[name] = CLOCK.now()` upon dependency skips and errors, enforcing the full configured interval before re-execution. In Lane C (`_trigger_type_c_report`), applied a 5-minute backoff cooldown (`self.type_c_retry_after[name] = CLOCK.now() + 300s`) upon dependency skips and retryable failures, with `tick()` checking `CLOCK.now() < retry_after`.
- **Evidence:** Rapid-fire 500ms re-execution loops eliminated. Over 5 simulated ticks, dispatches dropped from 5 to 1. Verified in `poc_f021_f024_verification.py` and `test_audit_fixes.py` (`test_f022_lane_b_c_dependency_skip_throttling`).

### F-023: BG-001 Idle-Only Settings Guardrail Multi-Lane Protection
- **Mechanism:** Added `has_active_runs` property to `IntradayService` checking `current_runs`, `active_runs_type_b`, and `active_runs_type_c` under lock. `SettingsController.update_settings()` evaluates `self.intraday_service.is_active or self.intraday_service.has_active_runs`, rejecting updates with HTTP 409 Conflict whenever ANY task is actively running.
- **Evidence:** Mutation attempts while Lane B or Lane C processes run in the background return HTTP 409 Conflict. Verified in `poc_f021_f024_verification.py` and `test_audit_fixes.py` (`test_f023_settings_mutation_rejected_when_lane_b_or_c_active`).

### F-024: Strict Lane Name Whitelist Validation
- **Mechanism:** Enforced `VALID_LANES = {"type_a", "type_b", "type_c"}` in `ParadisoController.lane_start()` and `lane_stop()`, rejecting non-canonical lane identifiers with HTTP 400 Bad Request. In `IntradayService._normalize_lane()`, raised `ValueError` on unrecognized lane strings.
- **Evidence:** Malformed lane requests return HTTP 400 Bad Request without mutating Lane A. Verified in `poc_f021_f024_verification.py` and `test_audit_fixes.py` (`test_f024_lane_name_validation`).

### F-025: Defeat Device Eradication in Production Clock Subsystem
- **Mechanism:** Completely excised `import sys` and `sys.argv` inspection from `paradiso/utils/clock.py:Clock._get_sim_now()`. The clock derives time strictly from wall-clock time or configured simulation baselines without argument snooping.
- **Evidence:** Poisoning `sys.argv` with test names no longer alters `CLOCK.now()`. Source code contains zero test evasion conditionals. Verified in `poc_f025_clock_defeat_device.py` and `test_audit_fixes.py` (`test_f025_no_defeat_device_in_clock`).

### F-026: Honest Window Gating for Independent Lane Starts
- **Mechanism:** Added intraday window gating to `ParadisoController.lane_start()` returning HTTP 409 Conflict when current status is not `OPEN` (unless `force_open: true` is explicitly provided). Added `force_open` pass-through to `Paradiso.start_lane()`.
- **Evidence:** Starting Lane A, B, or C during `WAITING_TO_OPEN`, `WAITING_TO_CLOSE`, or `CLOSED` returns HTTP 409 Conflict with descriptive error. Passing `force_open: true` succeeds. Verified in `poc_f026_out_of_window_stall.py` and `test_audit_fixes.py` (`test_f026_lane_start_out_of_window_409`).

### F-027: Documentation Synchronization on Lane C EOD Timeslot
- **Mechanism:** Aligned Section 1 line 9 of `TECHNICAL_DOCUMENTATION.md` to specify `EOD 20:30`.
- **Evidence:** All references across Section 1, Section 3, `storage/automations.json`, and `IntradayService` consistently specify `20:30`. Verified in `test_audit_fixes.py` (`test_f027_eod_timeslot_consistency`).

### F-028: Pre-existing Closed Day Record Cleansing on Boot
- **Mechanism:** Introduced `_get_or_init_day()` in `IntradayService` detecting stale/premature day closures (e.g. during `WAITING_TO_OPEN` or on `force_open`) and cleansing `reports_ran` to re-initialize a clean operational day slate.
- **Evidence:** Under baseline conditions, pre-existing closed day records in storage are reset and `waitlist` is populated with expected reports. Verified in `poc_f028_preexisting_day_paralysis.py` and `test_audit_fixes.py` (`test_f028_preexisting_closed_day_cleansed_on_boot`). *(See active finding F-032 for edge fragility).*

### F-029: Mid-Day Process Restart Lane C Hydration
- **Mechanism:** Added `_hydrate_type_c_ran_today()` reading completed/failed runs from `day.reports_ran` for the current date upon startup, `start_lane`, `start_fresh_run`, and `tick()`.
- **Evidence:** Restarting the process mid-day preserves completed status for time-pinned reports and prevents duplicate execution. Verified in `poc_f029_lane_c_reboot_duplication.py` and `test_audit_fixes.py` (`test_f029_lane_c_hydrates_from_storage_on_restart`). *(See active finding F-031 for cold boot catalog leakage).*

### F-030: Web UI HTTP 409 Intraday Window Rejection Feedback
- **Mechanism:** Implemented universal `showToast(msg, type)` in `paradiso/web/static/js/app.js` using CSS `.settings-toast` styles. Updated `startLane()` and `stopLane()` to inspect `res.status === 409` and display error toast notifications to operators.
- **Evidence:** Operators receive immediate visual toast feedback when starting or stopping lanes outside open hours or during conflict states. Verified in `test_audit_fixes.py` (`test_f030_app_js_handles_409_and_defines_show_toast`).

### F-031: Lane C Cold Boot Hydration Derived Strictly from Storage
- **Mechanism:** Removed `automations.json` catalog iteration from `_hydrate_type_c_ran_today()`. Now derives solely from `day.reports_ran` for the current calendar date in `intraday.json`.
- **Evidence:** Cold boot of a new day with prior day's "Completed" reports in catalog does not populate `type_c_ran_today`. Pinned reports execute at scheduled timeslots. Verified in `tests/test_audit_fixes.py` (`test_f031_cold_boot_lane_c_no_leak_from_prior_day`).

### F-032: Storage Waitlist Preservation on Partial Days & Cutoffs
- **Mechanism:** Replaced all-or-nothing day cleansing with `_get_completed_or_exhausted_reports(day)`. Uncompleted reports (unstarted or terminated via cutoff) are enqueued into `waitlist` without erasing historical execution records from `day.reports_ran`.
- **Evidence:** Pre-existing closed day records with completed reports and cutoff reports populate uncompleted runs into `waitlist` without queue paralysis (`len(waitlist) == 2`). Historical logs are preserved on disk. Verified in `tests/test_audit_fixes.py` (`test_f032_partial_day_does_not_paralyze_queue_and_preserves_logs`).

### F-033: 21:00 WAITING_TO_CLOSE Wrap-Up Window Precedence & Per-Lane Gating
- **Mechanism:** Enforced `t >= self.idle_time -> WAITING_TO_CLOSE` ahead of `force_open` in `resolve_status()`. Removed global `force_open` leakage in `ParadisoController.lane_start()`, requiring explicit per-lane `force_open: true` for out-of-window requests.
- **Evidence:** At 21:15, `resolve_status()` returns `WAITING_TO_CLOSE`. Lane starts without `force_open` return HTTP 409 Conflict. Verified in `tests/test_audit_fixes.py` (`test_f033_waiting_to_close_enforced_and_cross_lane_isolated`).

### F-034: Actively Executing Type B and C Deletion Guardrail
- **Mechanism:** In `AutomationController.delete_automation()`, added `is_running` check evaluating `current_runs`, `active_runs_type_b`, `active_runs_type_c`, and `report.status == "Running"`, rejecting deletion with HTTP 409 Conflict.
- **Evidence:** Attempting to delete an in-flight report returns HTTP 409 Conflict; catalog record and host subprocess remain intact. Idle reports delete cleanly with HTTP 200 OK. Verified in `tests/test_audit_fixes.py` (`test_f034_delete_actively_executing_type_b_or_c_rejected_409`).

### F-035: Cold Boot Lane B Time-Only last_run Future Timestamp Prevention
- **Mechanism:** In `_hydrate_type_b_last_run()`, adjusted parsed catalog timestamps lacking today's explicit calendar date or evaluated as future times to historical (`parsed_dt - timedelta(days=1)`), guaranteeing `parsed_dt <= CLOCK.now()`.
- **Evidence:** Cold boot with time-only `last_run: "09:30:00 PM"` hydrates as historical timestamp, allowing recurring interval calculation to trigger immediate dispatch upon morning startup. Verified in `tests/test_audit_fixes.py` (`test_f035_lane_b_cold_boot_does_not_synthesize_future_timestamp`).

### F-036: Symmetrical Automation Enablement Endpoint
- **Mechanism:** Implemented `enable(name)` in `AutomationService` and `POST /api/automation/enable` in `AutomationController`, restoring status to `Waiting` and enqueuing into active Lane A queue without destructive reset.
- **Evidence:** Calling `POST /api/automation/enable` restores a disabled report to `Waiting` and enqueues it into `waitlist` without clearing `reports_ran` or interrupting active runs. Verified in `tests/test_audit_fixes.py` (`test_f036_enable_automation_endpoint_restores_without_destructive_reset`).

### F-037: Input Validation & Defensive Normalization for Lane C Timeslots
- **Mechanism:** Implemented regex pre-validation `r"^([01]\d|2[0-3]):[0-5]\d$"` in `AutomationController.add_automation()` rejecting 12-hour AM/PM formats, unpadded single-digit hours, and invalid values with HTTP 400 Bad Request. Implemented defensive `_normalize_timeslot()` in `IntradayService` converting existing storage/catalog timestamps into canonical zero-padded `HH:MM` and emitting a non-crashing warning timeline event for corrupt times.
- **Evidence:** `POST /api/automation/add` with `"08:30 AM"` or `"8:30"` returns HTTP 400 Bad Request. Legacy storage items with unpadded hours or 12-hour formats dispatch without throwing `ValueError` crashes or freezing. Verified in `tests/test_audit_fixes.py` (`test_f037_scheduled_time_format_validation_and_defensive_tick`) and adversarial verification suite (`poc_f037_f039_verification.py`).

### F-038: Missed Window Catch-Up Policy Persistence via API
- **Mechanism:** In `AutomationController.add_automation()`, extracted `catch_up_policy`, validated against canonical enum values (`CATCH_UP_IMMEDIATE`, `SKIP_UNTIL_NEXT_DAY`, `WARN_OPERATOR`), passed to `Report` constructor, and persisted to `automations.json`. Unrecognized policies rejected with HTTP 400 Bad Request.
- **Evidence:** `POST /api/automation/add` with `"catch_up_policy": "SKIP_UNTIL_NEXT_DAY"` serializes the policy in the HTTP 201 response and persists it in `automations.json`. Invalid strings return HTTP 400 Bad Request. Verified in `tests/test_audit_fixes.py` (`test_f038_catch_up_policy_persistence_in_api`) and adversarial verification suite (`poc_f037_f039_verification.py`).

### F-039: Type C Missed Timeslot Warning State Reset
- **Mechanism:** In `IntradayService.reset_all_reports()`, added `self.type_c_warned.clear()`, resetting warned report names alongside other per-day tracking collections. Also maintained on new day rollover and `start_fresh_run()`.
- **Evidence:** Calling `POST /api/automations/reset` clears `self.type_c_warned`. On subsequent ticks where a report remains outside its grace window, a new warning alert is emitted rather than being permanently silenced. Verified in `tests/test_audit_fixes.py` (`test_f039_reset_all_reports_clears_type_c_warned`) and adversarial verification suite (`poc_f037_f039_verification.py`).

### F-040: Manual Execution of Disabled Automations Blocked
- **Mechanism:** In `ExecutionController.run_automation()`, added HTTP 409 Conflict guard blocking manual execution if `report.status == "Disabled"`. In `IntradayService.trigger_manual_run()`, added defensive check returning `False` for disabled reports.
- **Evidence:** `POST /api/automation/run` with a Disabled Type B or Type C report returns HTTP 409 Conflict; no subprocess is dispatched and catalog status is preserved. Verified in `tests/test_audit_fixes.py` (`test_f040_disabled_report_manual_run_rejected`).

### F-041: Lane B Unbounded Failed Subprocess Dispatch Suppressed
- **Mechanism:** In `IntradayService.tick()`, added `type_b_exhausted` and `retry_counts >= max_retries` checks to Lane B loop, immediately halting automatic dispatch when a report enters terminal `Failed` status or exhausts its retry budget.
- **Evidence:** Once a recurring report permanently fails (exhausting `max_retries`), subsequent interval elapsed ticks skip execution without spawning subprocesses or generating timeline spam. Verified in `tests/test_audit_fixes.py` (`test_f041_lane_b_does_not_dispatch_failed_report`).

### F-042: Simulation Clock Reset Guarded by BG-001 Idle Check
- **Mechanism:** In `SettingsController.reset_simulation_clock()`, added active execution checks verifying `paradiso.is_running()`, `intraday_service.is_active`, and `intraday_service.has_active_runs`, rejecting clock resets with HTTP 409 Conflict while jobs are in flight or scheduler is running.
- **Evidence:** Calling `POST /api/settings/simulation/reset` while scheduler is running or jobs are active returns HTTP 409 Conflict. Resets are only permitted in clean idle state. Verified in `tests/test_audit_fixes.py` (`test_f042_simulation_reset_rejected_when_active`).

### F-043: Manual Run Execution Guarded Against Failed/Exhausted Re-Arming
- **Mechanism:** In `ExecutionController.run_automation()` and `IntradayService.trigger_manual_run()`, blocked manual execution for reports that are in `Failed` status or present in `type_b_exhausted` with HTTP 409 Conflict. Updated `IntradayService._trigger_type_b_report._on_good()` to prevent clearing `retry_counts` if the report is in `type_b_exhausted`. Mandated that re-arming requires explicit administrative re-enablement via `POST /api/automation/enable`.
- **Evidence:** Calling `POST /api/automation/run` on a Failed or exhausted Type B report returns HTTP 409 Conflict. Autonomous scheduling remains suppressed until explicitly re-enabled via `POST /api/automation/enable`. Verified in `tests/test_audit_fixes.py` (`test_f043_manual_run_failed_report_rejected` and `test_f043_failed_report_rearmed_only_via_enable`).
