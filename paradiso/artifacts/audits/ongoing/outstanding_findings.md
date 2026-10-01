# OUTSTANDING FINDINGS DOSSIER (ACTIVE AUDIT BASELINE)

**Target System:** Paradiso Daemon Scheduling Engine & Web UI  
**Audit Baseline Report:** [`artifacts/audits/ongoing/audit_20261001_2315.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20261001_2315.md)  
**Historical Archive:** [`artifacts/audits/resolved/resolved_findings_registry.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/resolved_findings_registry.md)  
**Mandate Reference:** [`artifacts/audits/AUDITOR.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/AUDITOR.md)  
**Last Updated:** 2026-10-01 23:47 (Local Time)  
**Active Unresolved Findings:** **0 (All 52 findings verified resolved)**

---

## 1. Executive Status

Following the Batch 9 Frontend-to-Backend Integrity remediation verification pass, **there are zero (0) outstanding findings**. All 5 Frontend-to-Backend Integrity defects (`F-048` through `F-052`) have been independently verified as resolved and archived into [`artifacts/audits/resolved/resolved_findings_registry.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/resolved/resolved_findings_registry.md).

| Metric | Count | Status |
|---|---|---|
| **Active Unresolved Findings** | **0** | **CLEAN SLATE** |
| **Total Historical Findings Resolved (`F-001` – `F-052`)** | **52** | **100% VERIFIED** |
| **Systemic Hardening Items Verified (`V-01` – `V-05`)** | **5** | **100% VERIFIED** |
| **Production Unit & Regression Test Suite** | **146 / 146** | **100% PASSING** |

---

## 2. Recently Closed Batch 9 Findings (Archived)

| ID | Severity | Category | Invariant | Title | Resolution Verification |
|---|---|---|---|---|---|
| **F-048** | HIGH | STATE-MACHINE / API / UI | I-7, I-8, I-10, BG-001 | Stopping All Lanes via Web UI Leaves `Paradiso` Daemon Running, Permanently Locking Settings & Simulation Clock Reset (`HTTP 409`) | **RESOLVED & VERIFIED** (`poc_f048_f052_frontend_backend_integrity.py` PASS, `test_f048_stopping_all_lanes_unlocks_scheduler_and_settings` PASS) |
| **F-049** | HIGH | UI / API | I-7, I-8 | `POST /api/automation/enable` Orphaned from Web UI & Missing `badge-disabled` Class in Catalog | **RESOLVED & VERIFIED** (`poc_f048_f052_frontend_backend_integrity.py` PASS, `test_f049_enable_endpoint_connected_in_frontend_and_disabled_badge_styled` PASS) |
| **F-050** | MEDIUM | UI / API | I-2, I-7, I-8 | Hardcoded Frontend Retry Telemetry Falsely Reports `1 / 3` Error Retries on Zero-Penalty Dependency Skips | **RESOLVED & VERIFIED** (`poc_f048_f052_frontend_backend_integrity.py` PASS, `test_f050_automations_api_and_ui_accurate_retry_counts` PASS) |
| **F-051** | MEDIUM | UI / HONEST API | I-7, BG-001 | Silent Frontend Suppression of HTTP 409 Error on Simulation Clock Reset and Hidden Toast Notification on Report Registration | **RESOLVED & VERIFIED** (`poc_f048_f052_frontend_backend_integrity.py` PASS, `test_f051_clock_reset_surfaces_409_and_add_report_shows_visible_toast` PASS) |
| **F-052** | LOW | UI / DOC-DRIFT | I-3, I-7 | Unbound Lane B "Active Workers" Metric Card (`0 In-Flight`) and Residual `EOD (21:00)` Schedule Labels in `index.html` | **RESOLVED & VERIFIED** (`poc_f048_f052_frontend_backend_integrity.py` PASS, `test_f052_lane_b_active_workers_bound_and_eod_2030_consistent` PASS) |

---

## 3. Verification Commands

```bash
# 1. Full Automated Unit & Regression Test Suite (146/146 tests passing)
py -3 run_tests.py

# 2. Batch 9 Frontend-to-Backend Integrity PoC Suite (5/5 passing)
py -3 paradiso/artifacts/audits/poc/poc_f048_f052_frontend_backend_integrity.py
```
