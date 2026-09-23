# Resolved Findings Registry — Paradiso

**Date:** 2026-09-23 15:00  
**Auditor:** Independent Adversarial Auditor  
**Location:** `artifacts/audits/resolved/resolved_findings_registry.md`

---

## 1. RESOLVED FINDINGS MASTER INDEX

| ID | Severity | Category | Invariant | Title | Resolution Verification |
|---|---|---|---|---|---|
| **F-001** | CRITICAL | QUEUE | I-1, I-8 | Deletion of running automation causes permanent queue deadlock | Verified in `tests/test_audit_fixes.py` (`test_f001_delete_running_automation_fails_gracefully`) |
| **F-002** | CRITICAL | SECURITY | I-9 | Arbitrary script execution via path traversal in `/api/automation/add` | Verified in `tests/test_audit_fixes.py` (`test_f002_path_traversal_blocked`) |
| **F-003** | HIGH | SECURITY | I-9 | Unvalidated interpreter paths in `/api/settings` allow arbitrary host execution | Verified in `tests/test_audit_fixes.py` (`test_f003_invalid_interpreters_rejected`) |
| **F-004** | HIGH | QUEUE | I-2, I-8 | Dependency skip exit code 1 retried as failure and log receipts clobbered | Verified in `tests/test_audit_fixes.py` & `poc_f004_verification.py` (4 passing tests) |
| **F-005** | HIGH | QUEUE | I-2, I-6 | Fast-spinning dependency starvation causes timeline & storage write flood | Verified in `tests/test_audit_fixes.py` (`test_f005_dependency_starvation_pauses_queue`) |
| **F-006** | HIGH | CONCURRENCY | I-5, I-8 | Process watcher suppression via CPython heap address reuse (`id(process)`) | Verified in `tests/test_audit_fixes.py` & `poc_f006_f008_verification.py` |
| **F-007** | HIGH | STORAGE | I-6 | Storage corruption runaway `.bak` file flood deduplication | Verified in `tests/test_audit_fixes.py` & `poc_f007_verification.py` (4 passing tests) |
| **F-008** | MEDIUM | PROCESS | I-5 | Child process trees survive `Runner.kill_all()` on Windows | Verified in `tests/test_audit_fixes.py` & `poc_f006_f008_verification.py` |
| **F-009** | MEDIUM | CONCURRENCY | I-1, I-3 | Concurrent `POST /api/paradiso/start` spawns duplicate scheduler loops | Verified in `tests/test_audit_fixes.py` & `poc_bg001_bg002_verification.py` |
| **F-010** | MEDIUM | STATE MACHINE | I-3, I-4 | Midnight rollover duplicates queue entries & in-flight cutoff termination | Verified in `tests/test_audit_fixes.py` & `poc_f010_verification.py` (5 passing tests) |
| **F-013** | HIGH | STORAGE / QUEUE | I-8 | Active automation broken due to deleted report script (`0base_auto.py`) | Migrated `"SF Base"` to `sample_report_blueprint.py` in `automations.json` |
| **F-014** | LOW | CONCURRENCY | I-11 | Blocking `process.wait(timeout=1.0)` held under `_proc_lock` in `kill_all()` | Moved `wait()` loop outside `_proc_lock`, reducing hold time to $< 1\text{ms}$ |
| **BG-001** | HIGH | SECURITY / INTEGRITY | I-7, I-9 | Idle-Only Configuration Guardrail: Settings mutation while scheduler active | Verified in `tests/test_audit_fixes.py` & `poc_bg001_bg002_verification.py` (HTTP 409 Conflict) |
| **BG-002** | HIGH | STABILITY / CONCURRENCY | I-1, I-3 | Start/Stop Transition Cooldown & Mutex Guard | Verified in `tests/test_audit_fixes.py` & `poc_bg001_bg002_verification.py` (HTTP 429 Cooldown) |

---

## 2. SUMMARY OF RESOLUTION DETAILS

### F-001: Deletion Deadlock
- **Mechanism:** Added HTTP 409 Conflict guard in `AutomationController.delete_automation` while scheduler is active, plus fail-safe callback triggering in `ExecutionService.execute_report` if an automation is removed while queued.
- **Evidence:** Queue continues sequential processing without hung states.

### F-002: Arbitrary Script Execution (Path Traversal)
- **Mechanism:** Strict whitelist check against `ALLOWED_DIRS` (`reports`, `data`, `scripts`), sanitization of `filename` via `os.path.basename` / `Path.name`, and rejection of traversal sequences (`..`).
- **Evidence:** Malicious paths outside authorized directories rejected with HTTP 400.

### F-003: Unvalidated Interpreter Paths
- **Mechanism:** In `validate_config()`, interpreter paths must strictly match approved binary naming patterns (`python*`, `rscript*`), exist on the filesystem as regular files, and possess executable permissions.
- **Evidence:** Arbitrary system binaries (`cmd.exe`, `calc.exe`) rejected with HTTP 400.

### F-004: Dependency Skip Receipts & Retry Penalties
- **Mechanism:** Established Section 12 Receipt Contract. Consolidated dependency skip heuristics in `ReportLog.is_dependency_skip`. Skips rotate to `Retrial` with zero penalty against `max_retries`. Dumped receipts in `paradiso/logs` preserved on failure instead of being clobbered with generic failure JSON.
- **Evidence:** All 4 attack vectors in `poc_f004_verification.py` pass.

### F-005: Dependency Starvation Fast-Spinning
- **Mechanism:** Added queue pass tracking and starvation cooldown in `IntradayService`. When all remaining waitlist reports skip in a single pass, queue execution pauses until the next tick cycle rather than fast-spinning. Deduplicated timeline rotation entries within cooldown window.
- **Evidence:** Timeline writes drop from thousands per second to 1 per starvation cycle.

### F-006: Process Watcher Suppression (Heap Address Reuse)
- **Mechanism:** Implemented monotonic integer execution IDs (`_exec_counter`, `_exec_id`) and stamped `process._was_killed = True` directly on `Popen` instances. Eliminated `id(process)` and removed fragile name-fallback checks.
- **Evidence:** Killed processes do not suppress subsequent launches of reports with the same name.

### F-007: Storage Corruption Backup Flood Deduplication
- **Mechanism:** `StorageBase._global_corrupted_states` caches `(st_mtime_ns, st_size)`. Cold boot scans latest backup and checks byte equality (`latest_bak.read_bytes() == self.file_path.read_bytes()`). Capped backup retention at 5 latest copies.
- **Evidence:** 20 consecutive ticks generate exactly 1 backup; rotation cap preserves exactly 5 files.

### F-008: Windows Process Tree Termination
- **Mechanism:** In `Runner.kill_all()`, added `taskkill /F /T /PID <pid>` on Windows with `CREATE_NO_WINDOW`, terminating parent, child, and grandchild trees before calling `process.kill()`.
- **Evidence:** 3-tier deep process trees confirmed dead in Windows `tasklist`.

### F-009: Concurrent Start Loops & In-Flight Reset
- **Mechanism:** Guarded `Paradiso` lifecycle with `_lifecycle_lock` re-entrant mutex. Added `is_running()` check before `start_fresh_run()` so in-flight tasks and retry counters are never reset by redundant calls. Replaced cleared event with newly instantiated `threading.Event()`. In `stop()`, synchronously joined loop thread with `join(timeout=2.0)`.
- **Evidence:** 25 concurrent threads trigger strictly 1 loop thread; in-flight jobs and retry counts remain completely intact.

### F-010: Midnight Rollover & 22:00 Cutoff Process Termination
- **Mechanism:** In `_close_day()`, in-flight jobs (`r.name in running_reports`) are evaluated explicitly, killed via `Runner.kill_all()`, and marked `"Failed"`, regardless of prior executions. In `tick()`, `self._active_date` tracks day changes independently of day record presence in storage.
- **Evidence:** Re-run jobs in-flight at cutoff transition to Failed; crossing midnight into pre-existing day records cleanly clears stray jobs and resets reports.

### F-013: Automation Broken by Deleted Script
- **Mechanism:** Re-bound `"SF Base"` in `storage/automations.json` to existing `reports/sample_report_blueprint.py` with clean `"Waiting"` status.
- **Evidence:** Pipeline executes successfully without file-not-found failures.

### F-014: Blocking Lock Hold in `kill_all()`
- **Mechanism:** Moved synchronous `process.wait(timeout=1.0)` reaping loop outside `with self._proc_lock:` critical section.
- **Evidence:** Lock hold time reduced from $N$ seconds to $< 1\text{ms}$.

### BG-001: Idle-Only Configuration Guardrail
- **Mechanism:** Enforced HTTP 409 Conflict in `SettingsController.update_settings` when `self.paradiso.is_running()` or `intraday_service.current_runs` is non-empty. In frontend UI, dynamically displayed an amber configuration locked banner and disabled the "Save Settings" button with a `not-allowed` cursor.
- **Evidence:** Settings mutations strictly blocked during active execution; allowed when idle.

### BG-002: Start/Stop Transition Cooldown & Mutex Guard
- **Mechanism:** Enforced 10-second transition cooldown on `/api/paradiso/start` and `/api/paradiso/stop`. Rapid calls within cooldown rejected with HTTP 429 and `cooldown_remaining` payload. Frontend UI displays a visual countdown on the button (`⏳ Cooldown (Xs)`) and disables action buttons until expiration.
- **Evidence:** Rapid start/stop cycling blocked with HTTP 429; transitions succeed cleanly upon cooldown expiration.
