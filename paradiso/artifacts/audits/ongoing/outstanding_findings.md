# Outstanding Findings Dossier — Paradiso

**Date:** 2026-09-28 22:35 (Local Time)  
**Auditor:** Independent Adversarial Auditor  
**Scope:** Active and unmitigated findings awaiting Builder resolution.  
**Target:** `artifacts/audits/ongoing/outstanding_findings.md`

---

## 1. SUMMARY OF OUTSTANDING FINDINGS

| ID | Severity | Confidence | Category | Invariant | Title | Current Status |
|---|---|---|---|---|---|---|
| **F-043** | MEDIUM | 100% | DISPATCH & STATE INTEGRITY | I-1, I-8 | Manual Run of Failed Lane B Report Silently Re-Arms Automatic Dispatch | **ACTIVE / AWAITING DEV REMEDIATION** |

---

## 2. RECENTLY RESOLVED (BATCH 7 REMEDIATIONS: F-040, F-041, F-042)

| ID | Severity | Category | Invariant | Title | Verification Artifact |
|---|---|---|---|---|---|
| **F-040** | HIGH | SAFETY & STATE HYGIENE | I-7, I-8 | `POST /api/automation/run` Bypasses "Disabled" State and Re-Arms Quarantined Automations | Dual-guard in controller (HTTP 409) + service layer; verified in `poc_f040_*` & `test_f040_*` |
| **F-041** | CRITICAL | DISPATCH & RESOURCE EXHAUSTION | I-1, I-6 | Lane B Dispatches Permanently Failed Reports in Unbounded Infinite Loop | Dual-guard (`status in ("Disabled", "Failed")` + `retry_counts >= max_retries`); verified in `poc_f041_*` & `test_f041_*` |
| **F-042** | MEDIUM | CLOCK INTEGRITY & GUARDRAILS | BG-001, I-3, I-7 | `POST /api/settings/simulation/reset` Bypasses BG-001 Idle-Only Guardrail | Structural BG-001 replication; verified in `poc_f042_*` & `test_f042_*` |

---

## 3. PREVIOUSLY RESOLVED (BATCH 6 REMEDIATIONS: P2.2 INVESTIGATION)

| ID | Severity | Category | Invariant | Title | Verification Artifact |
|---|---|---|---|---|---|
| **F-037** | CRITICAL | INPUT VALIDATION & STABILITY | I-1, I-7, I-9 | Non-Canonical `scheduled_time` Strings Cause Unhandled Crashes or Starvation | Regex 24-hr `HH:MM` validation in API + defensive `_normalize_timeslot` in `tick()` |
| **F-038** | MEDIUM | API & CONTRACT INTEGRITY | I-7, I-8 | `POST /api/automation/add` Silently Discards `catch_up_policy` Parameter | Parameter extraction, validation, and persistence in `Report` |
| **F-039** | MEDIUM | STATE MACHINE & NOTIFICATIONS | I-4, I-7, I-8 | `reset_all_reports()` Fails to Clear `self.type_c_warned` | Added `self.type_c_warned.clear()` to `reset_all_reports()` |

---

## 4. HISTORICALLY RESOLVED (BATCH 4 & 5 REMEDIATIONS)

| ID | Severity | Category | Invariant | Title | Verification Artifact |
|---|---|---|---|---|---|
| **F-032** | CRITICAL | STORAGE / QUEUE | I-4, I-6, I-8 | Partial Day Queue Paralysis & Log Erasure | `_get_completed_or_exhausted_reports()` distinguishes completed/exhausted |
| **F-035** | CRITICAL | TIME SYNTHESIS / DISPATCH | I-1, I-4 | Cold Boot Time-Only `last_run` Future Timestamp Synthesis | `_hydrate_type_b_last_run()` shifts future timestamps |
| **F-033** | HIGH | STATE MACHINE / API | I-3, I-7 | `force_open` Wrap-Up Bypass & Cross-Lane Leak | `resolve_status()` enforces idle_time precedence |
| **F-036** | MEDIUM | API / QUEUE HYGIENE | I-7, I-8 | Asymmetric Automation Disabling API | `POST /api/automation/enable` endpoint |
| **F-031** | CRITICAL | COLD BOOT & STORAGE LEAK | I-1, I-4 | Lane C Cold Boot Hydration Derived Strictly from Storage | Storage-only `_hydrate_type_c_ran_today()` |
| **F-034** | MEDIUM | INTEGRITY & PROCESS ORPHANING | I-5, I-8, BG-001 | Deleting Actively Executing Reports Blocked with HTTP 409 | `is_running` guard on `delete_automation()` |

---

## 5. ACTIVE FINDINGS DOSSIER

### F-043: Manual Run of Failed Lane B Report Silently Re-Arms Automatic Dispatch

- **Severity:** MEDIUM
- **Invariants Breached:** I-1, I-8
- **Source Location:** `paradiso/services/intraday_service.py:trigger_manual_run:1197-1218`, `paradiso/services/intraday_service.py:_trigger_type_b_report._on_good:959-966`, `paradiso/controllers/execution_controller.py:run_automation:38-42`
- **Adversarial Asset:** `paradiso/artifacts/audits/poc/poc_f043_manual_run_rearms_failed_report.py`

#### OBSERVATION
Neither `ExecutionController.run_automation()` (line 38) nor `IntradayService.trigger_manual_run()` (line 1200) checks for `report.status == "Failed"`. They only check for `"Disabled"`. A `"Failed"` Lane B report passes both guards and enters `_trigger_type_b_report()`. Upon successful completion, `_on_good()` resets `retry_counts[name] = 0` (line 966) and `ExecutionService` sets status to `"Completed"`. Both F-041 guard conditions (`status in ("Disabled", "Failed")` and `retry_counts >= max_retries`) are now reset.

#### EVIDENCE
Demonstrated deterministically in `poc_f043_manual_run_rearms_failed_report.py`:
1. Register a Type B report with `interval_minutes: 15` and `max_retries: 3`.
2. Initialize day, exhaust retries → `status="Failed"`, `retry_counts=3`.
3. Verify `tick()` does NOT dispatch (F-041 fix working).
4. Simulate successful manual run → `retry_counts=0`, `status="Completed"`.
5. Advance clock past interval → `tick()` dispatches the report automatically.

#### CONSEQUENCE
A permanently failed Lane B report can be silently resurrected for continuous automatic interval dispatch by a single successful manual run, without explicit administrative re-enablement.

#### VERIFICATION CRITERION
Either (a) `trigger_manual_run()` and `run_automation()` must reject `"Failed"` reports, OR (b) the manual run success callback must preserve the exhausted retry budget so `tick()` continues to suppress dispatch. Deliberate re-enablement should require an explicit administrative action distinct from a one-off manual execution.
