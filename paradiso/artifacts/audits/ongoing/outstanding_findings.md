# OUTSTANDING FINDINGS DOSSIER (ACTIVE AUDIT BASELINE)

**Target System:** Paradiso Daemon Scheduling Engine & Web UI  
**Primary Baseline Report:** [`artifacts/audits/ongoing/audit_20261003_0135.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20261003_0135.md)  
**Historical Archive:** [`artifacts/audits/resolved/resolved_findings_registry.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/resolved_findings_registry.md)  
**Mandate Reference:** [`artifacts/audits/AUDITOR.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/AUDITOR.md)  
**Last Updated:** 2026-10-03 01:40 (Local Time)  
**Active Unresolved Findings:** **4 (`F-057`, `F-058`, `F-059`, `F-060`)**

---

## 1. Executive Status

Following a multi-angle adversarial audit of the Lane A queue engine (`paradiso/services/intraday_service.py` and `paradiso/controllers/automation_controller.py`), **four (4) new findings (`F-057`, `F-058`, `F-059`, `F-060`)** have been discovered and reproduced with deterministic proof-of-concept tests. All fifty-six (56) prior findings (`F-001` through `F-056`) remain verified resolved.

| Metric | Count | Status |
|---|---|---|
| **Active Unresolved Findings (Batch 13)** | **4** | **OPEN (`F-057`, `F-058`, `F-059`, `F-060`)** |
| **Total Historical Findings Resolved (`F-001` – `F-056`)** | **56** | **100% VERIFIED** |
| **Systemic Hardening Items Verified (`V-01` – `V-05`)** | **5** | **100% VERIFIED** |
| **Batch 13 PoC Suite (`poc_f057_f060_lane_a_multi_angle_attacks.py`)** | **4 / 4** | **FAILING (PROVES ACTIVE DEFECTS)** |
| **Production Unit & Regression Test Suite** | **151 / 151** | **PASSING** |

---

## 2. Active Findings Roster (Batch 13 — Lane A Multi-Angle Attack)

Full Standard Triad details (`OBSERVATION -> EVIDENCE -> CONSEQUENCE -> VERIFICATION CRITERION`) are documented in [`artifacts/audits/ongoing/audit_20261003_0135.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20261003_0135.md).

| ID | Severity | Category | Invariant | Title | PoC Test Case |
|---|---|---|---|---|---|
| **F-057** | **HIGH** | QUEUE / PRIORITY / STATE MACHINE | I-1, I-7, I-8, F-005 | `enable_automation` Fails to Clear `_cycle_seen_in_pass`, Bypassing and Starving Re-Enabled Failed `P0` Reports Behind `P2` Reports | `test_f057_reenable_failed_p0_report_starved_behind_p2_due_to_stale_seen` |
| **F-058** | **HIGH** | QUEUE / COOLDOWN / STATE MACHINE | I-1, I-2, I-8, F-005 | Terminal Completion or Failure of the Final Report in a Pass Leaves Pass Counters Dirty, Bypassing Starvation Cooldown for Subsequent Reports | `test_f058_completion_of_last_report_leaves_dirty_counters_bypassing_cooldown` |
| **F-059** | **MEDIUM** | QUEUE / LIFECYCLE / COOLDOWN | I-2, I-8, F-005 | `start_lane("type_a")`, `stop_lane("type_a")`, `start_fresh_run()`, and `reset_all_reports()` Fail to Reset `_cycle_skips_in_pass` and `_cycle_errors_in_pass` | `test_f059_start_stop_and_reset_leak_cycle_errors_in_pass` |
| **F-060** | **HIGH** | QUEUE / PRIORITY / STARVATION | I-1, I-8, F-005 | Deferred `_cycle_seen_in_pass` Clearing (`defer_seen_clear=True`) on `disable_automation` Inverts Priority Order and Starves `P0` Reports When Reports Are Added/Enabled | `test_f060_defer_seen_clear_priority_inversion_and_p0_starvation_on_add` |

---

## 3. Recently Resolved Findings (Batch 11 & Batch 12)

| ID | Severity | Category | Invariant | Title | Resolution Status |
|---|---|---|---|---|---|
| **F-056** | **HIGH** | QUEUE / STATE MACHINE / DEADLOCK | I-1, I-7, I-8, F-005 | Disabling an Idle Lane A Report Stalls Queue Pass Evaluation, Stranding Skipped Reports in Permanent Deadlock | **RESOLVED & VERIFIED** (`poc_f056_disable_queue_deadlock.py`, `test_f056_disabling_idle_report_completes_pass_without_deadlock`) |
| **F-053** | **HIGH** | QUEUE / CONCURRENCY / STARVATION | I-1, I-2, F-005 | Multi-Slot Concurrency Starvation Cooldown Bypass & Asymmetric Fast-Spinning on Lane A Dependency Skips (`max_concurrent_run > 1`) | **RESOLVED & VERIFIED** (`poc_f053_f054_concurrency_spin_and_delete_leak.py`, `test_f053_multi_slot_seen_reports_do_not_fast_spin_in_same_pass`) |
| **F-054** | **HIGH** | STATE MACHINE / STORAGE / QUEUE | I-7, I-8 | `delete_automation` Leaks Runtime Execution State and Storage Run History, Permanently Starving Re-created Reports | **RESOLVED & VERIFIED** (`poc_f053_f054_concurrency_spin_and_delete_leak.py`, `test_f054_delete_automation_purges_runtime_and_intraday_state`) |
| **F-055** | **MEDIUM** | TEST INTEGRITY / CATALOG DRIFT | I-1, I-7 | Replacement of Blueprint `"SF Base"` in `storage/automations.json` Breaks `test_trigger_single_automation_run` Regression Suite (`404 != 403`) | **RESOLVED & VERIFIED** (`tests/test_api.py` 16/16 passing) |

---

## 4. Verification Commands

```bash
# 1. Batch 13 PoC Verification Suite (F-057, F-058, F-059, F-060: must pass 4/4 after remediation)
py -3 paradiso/artifacts/audits/poc/poc_f057_f060_lane_a_multi_angle_attacks.py

# 2. Batch 12 PoC Verification Suite (F-056 verified: 1/1 passing)
py -3 paradiso/artifacts/audits/poc/poc_f056_disable_queue_deadlock.py

# 3. Batch 11 PoC Verification Suite (F-053 & F-054 verified: 2/2 passing)
py -3 paradiso/artifacts/audits/poc/poc_f053_f054_concurrency_spin_and_delete_leak.py

# 4. Automated Production Test Suite (151/151 passing, 0 failures)
py -3 run_tests.py
```
