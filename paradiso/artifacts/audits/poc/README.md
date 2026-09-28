# Adversarial Proof-of-Concept & Verification Suites

This directory contains the independent adversarial test suites, regression verifications, and historical vulnerability reproduction scripts maintained by the Independent Adversarial Auditor for Paradiso Alter.

---

## 1. Quick Verification

To run all 9 active adversarial verification suites in a single command:

```bash
# From workspace root:
py -3 paradiso/artifacts/audits/poc/verify_all.py

# Or from inside this directory:
py -3 verify_all.py
```

All suites execute against isolated sandboxes (`tempfile.TemporaryDirectory`, `PARADISO_STORAGE_DIR`, `PARADISO_LOGS_DIR`) and will not mutate production application files.

---

## 2. Active Verification Suites Index

| Suite | Finding Target | Description | Verified Invariants |
|---|---|---|---|
| **`poc_bg001_bg002_verification.py`** | BG-001, BG-002, F-009 | Idle-only configuration mutation (409 Conflict), 25-thread start mutex, 10s cooldown throttle (429) | I-1, I-3, I-7, I-9 |
| **`poc_f001_verification.py`** | F-001 | Deletion rejection while active (409 Conflict) and queue auto-recovery on missing automation | I-1, I-8 |
| **`poc_f002_verification.py`** | F-002 | Path traversal & extension whitelist protection across 14 malicious payload vectors | I-9 |
| **`poc_f003_verification.py`** | F-003 | Host binary execution rejection & interpreter regex whitelist validation | I-9 |
| **`poc_f004_verification.py`** | F-004 | Section 12 receipt contract adherence: exit 1 skips, retry non-consumption, receipt preservation | I-2, I-8 |
| **`poc_f006_f008_verification.py`** | F-006, F-008 | Monotonic PID heap address reuse immunity & Windows 3-tier deep process tree termination | I-5, I-8 |
| **`poc_f007_verification.py`** | F-007 | Storage corruption backup deduplication (rapid ticks, mtime cache, 5-backup rotation cap) | I-6 |
| **`poc_f010_verification.py`** | F-010 | 22:00 cutoff OS process termination, re-run failure handling, pre-existing day rollover | I-3, I-4 |
| **`poc_f021_f024_verification.py`** | F-021, F-022, F-023, F-024 | Exact receipt discovery, Lane B/C skip throttling, multi-lane BG-001 409 guard, HTTP 400 lane check | I-2, I-6, I-7, I-8, I-9, BG-001 |

---

## 3. Historical Exploit Reproductions (`historical_exploits/`)

The [`historical_exploits/`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/poc/historical_exploits/) directory archives the original defect reproduction scripts generated during initial audit cycles. These scripts were designed to prove the presence of vulnerabilities prior to remediation and are archived for historical reference:
- `poc_f001_delete_deadlock.py`: Queue deadlock on deleting active executing report.
- `poc_f002_path_traversal.py`: Script path traversal and directory escape.
- `poc_f003_unvalidated_executables.py`: Unvalidated interpreter path arbitrary execution.
- `poc_f004_dep_skip_exit1.py`: Dependency skips with exit 1 consuming retry limit.
- `poc_f007_bak_flood.py`: Storage corruption rapid-fire backup file flood.
- `poc_f008_orphan_process_tree.py`: Windows orphan subprocess tree survival.
- `poc_f021_receipt_mismatch.py`: Exact receipt filename mismatch breaking discovery.
- `poc_f022_lane_b_c_spin.py`: Unbounded 500ms rapid-fire re-execution loop on dependency skips.
- `poc_f023_bg001_lane_b_c_bypass.py`: BG-001 idle-only settings mutation guardrail bypass during Lane B/C runs.
