# Outstanding Findings Dossier — Paradiso

**Date:** 2026-09-23 15:00  
**Auditor:** Independent Adversarial Auditor  
**Scope:** Active and unmitigated findings awaiting Builder resolution.  
**Target:** `artifacts/audits/ongoing/outstanding_findings.md`

---

## 1. SUMMARY OF OUTSTANDING FINDINGS

| ID | Severity | Confidence | Category | Invariant | Title | Current Status |
|---|---|---|---|---|---|---|
| **F-011** | LOW | CONFIRMED | UI / PERFORMANCE | I-7 | Aggressive 1-second unpaginated timeline polling & hardcoded 32-minute countdown in dashboard stats | OPEN |
| **F-012** | LOW | CONFIRMED | DOC-DRIFT | I-7 | Documentation claims `/api/dashboard/timeline` returns newest-first (actually returns oldest-first); unlisted endpoints | OPEN |

---

## 2. RECENTLY RESOLVED (ARCHIVED IN REGISTRY)

| ID | Title | Verification Artifact |
|---|---|---|
| **F-010** | Midnight Rollover & 22:00 Cutoff Process Termination & In-Flight Preservation | Verified via `poc_f010_verification.py` (5 passing tests) |
| **BG-001** | Idle-Only Configuration Guardrail | Verified via `poc_bg001_bg002_verification.py` |
| **BG-002 / F-009** | Start/Stop Transition Cooldown & Mutex Guard | Verified via `poc_bg001_bg002_verification.py` |
| **F-007** | Storage Corruption Rescue Backup Flood Deduplication | Verified via `poc_f007_verification.py` |

---

## 3. DETAILED ACTIVE FINDINGS DOSSIER

### F-011: Aggressive 1-Second Unpaginated Timeline Polling & Hardcoded Dashboard Countdown

- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Category:** UI / PERFORMANCE
- **Invariants:** I-7 (Honest API)
- **Affected Files:**
  - `paradiso/web/static/js/app.js:210-230`
  - `paradiso/controllers/dashboard_controller.py:18-35`

#### OBSERVATION
1. `app.js` polls `/api/dashboard/timeline` on a 1-second interval (`setInterval(..., 1000)`). The endpoint returns the entire unbounded timeline array from `intraday.json`. As days accumulate events, the JSON response grows indefinitely and causes browser DOM thrashing.
2. In `DashboardController.get_stats()`, the returned dictionary contains a hardcoded countdown string `"countdown": "32 min"` instead of a dynamically calculated time-to-next-window value.

#### EVIDENCE
In `paradiso/controllers/dashboard_controller.py`:
```python
stats = {
    ...
    "countdown": "32 min",  # Static placeholder
    ...
}
```
In `paradiso/web/static/js/app.js`:
```javascript
setInterval(loadTimeline, 1000); // 1-second unpaginated poll
```

#### CONSEQUENCE
1. Unnecessary network/CPU overhead and unbounded DOM node growth over extended sessions.
2. The UI dashboard displays a static, incorrect countdown duration regardless of actual clock time.

#### VERIFICATION CRITERION
- Timeline polling interval is decoupled from sub-second rates ($\ge 5\text{s}$ or event-driven).
- Dashboard stats endpoint returns countdown reflecting actual time remaining until the next scheduled window or report.

---

### F-012: Documentation Drift on Timeline Ordering and Undocumented API Endpoints

- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Category:** DOC-DRIFT
- **Invariants:** I-7 (Honest API)
- **Affected Files:**
  - `paradiso/TECHNICAL_DOCUMENTATION.md`
  - `paradiso/controllers/automation_controller.py`
  - `paradiso/controllers/dashboard_controller.py`

#### OBSERVATION
1. `TECHNICAL_DOCUMENTATION.md` asserts that `/api/dashboard/timeline` returns entries in reverse-chronological order (newest first). In implementation, `intraday.json` appends timeline items chronologically (oldest first), and `get_timeline()` returns the list in chronological order.
2. Active controller endpoints `/api/automation/disable` and `/api/system-status` exist in source code but are missing from the technical documentation API table.

#### EVIDENCE
`TECHNICAL_DOCUMENTATION.md` API specification states:
```markdown
| `/api/dashboard/timeline` | GET | List of recent events (newest first) |
```
Source in `DashboardController.get_timeline`:
```python
def get_timeline(self):
    day = self.intraday_repo.get_day(CLOCK.date_str())
    return jsonify({"ok": True, "timeline": day.get("timeline", [])})
```
Items are appended to the list over time, so index 0 is the oldest event of the day.

#### CONSEQUENCE
Consumers expecting reverse-chronological order render the timeline in inverted order. Integration documentation does not reflect all available endpoints.

#### VERIFICATION CRITERION
- Documentation matches actual endpoint sorting behavior and documents all active endpoints in `controllers/`.
