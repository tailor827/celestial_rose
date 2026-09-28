# Outstanding Findings Dossier — Paradiso

**Date:** 2026-09-28 21:30 (Local Time)  
**Auditor:** Independent Adversarial Auditor  
**Scope:** Active and unmitigated findings awaiting Builder resolution.  
**Target:** `artifacts/audits/ongoing/outstanding_findings.md`

---

## 1. SUMMARY OF OUTSTANDING FINDINGS

| ID | Severity | Confidence | Category | Invariant | Title | Current Status |
|---|---|---|---|---|---|---|
| *None* | — | — | — | — | **Zero active/unmitigated defects identified.** | **ALL FINDINGS RESOLVED** |

---

## 2. RECENTLY RESOLVED (BATCH 6 REMEDIATIONS: P2.2 INVESTIGATION)

| ID | Severity | Category | Invariant | Title | Verification Artifact |
|---|---|---|---|---|---|
| **F-037** | CRITICAL | INPUT VALIDATION & STABILITY | I-1, I-7, I-9 | Non-Canonical `scheduled_time` Strings Cause Unhandled Crashes or Starvation | Regex 24-hr `HH:MM` validation in API + defensive `_normalize_timeslot` in `tick()`; verified in `poc_f037_f039_verification.py` & `test_f037_*` |
| **F-038** | MEDIUM | API & CONTRACT INTEGRITY | I-7, I-8 | `POST /api/automation/add` Silently Discards `catch_up_policy` Parameter | Parameter extraction, validation, and persistence in `Report`; verified in `poc_f038_catch_up_policy_dropped_in_api.py` & `test_f038_*` |
| **F-039** | MEDIUM | STATE MACHINE & NOTIFICATIONS | I-4, I-7, I-8 | `reset_all_reports()` Fails to Clear `self.type_c_warned` | Added `self.type_c_warned.clear()` to `reset_all_reports()`; verified in `poc_f039_reset_all_reports_type_c_warned_retention.py` & `test_f039_*` |

---

## 3. HISTORICALLY RESOLVED (BATCH 4 & 5 REMEDIATIONS)

| ID | Severity | Category | Invariant | Title | Verification Artifact |
|---|---|---|---|---|---|
| **F-032** | CRITICAL | STORAGE / QUEUE | I-4, I-6, I-8 | `_get_completed_or_exhausted_reports()` distinguishes completed/exhausted runs from cutoff terminations, enqueuing uncompleted runs without erasing logs | Verified in `test_f032_partial_day_does_not_paralyze_queue_and_preserves_logs` |
| **F-035** | CRITICAL | TIME SYNTHESIS / DISPATCH | I-1, I-4 | `_hydrate_type_b_last_run()` detects future synthesized timestamps from time-only catalog logs and shifts to historical (`- timedelta(days=1)`), allowing immediate morning dispatch | Verified in `test_f035_lane_b_cold_boot_does_not_synthesize_future_timestamp` |
| **F-033** | HIGH | STATE MACHINE / API | I-3, I-7 | `resolve_status()` enforces 21:00 `WAITING_TO_CLOSE` wrap-up window ahead of `force_open`; `lane_start()` rejects out-of-window requests without explicit per-lane `force_open: true` | Verified in `test_f033_waiting_to_close_enforced_and_cross_lane_isolated` |
| **F-036** | MEDIUM | API / QUEUE HYGIENE | I-7, I-8 | Symmetrical `POST /api/automation/enable` endpoint re-enables disabled automations and rejoins active Lane A queue without destructive reset | Verified in `test_f036_enable_automation_endpoint_restores_without_destructive_reset` |
| **F-031** | CRITICAL | COLD BOOT & STORAGE LEAK | I-1, I-4 | Lane C Cold Boot Hydration Derived Strictly from Storage | Catalog inspection removed from `_hydrate_type_c_ran_today`; `test_f031_*` |
| **F-034** | MEDIUM | INTEGRITY & PROCESS ORPHANING | I-5, I-8, BG-001 | Deleting Actively Executing Type B/C Reports Blocked with HTTP 409 | `is_running` check across `current_runs` & `active_runs_type_b/c`; `test_f034_*` |

---

## 4. ACTIVE FINDINGS DOSSIER

*None. All findings F-001 through F-039 are verified as resolved and archived into `artifacts/audits/resolved/resolved_findings_registry.md`.*
