# Outstanding Audit Findings Ledger

**Last Updated:** `2026-10-03 15:28:00 +08:00`
**Active Audit Batch:** [`audit_20261003_1525.md`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/ongoing/audit_20261003_1525.md) (Batch 17 - Lane A)
**Active PoC:** [`poc_f076_lane_a_stale_exec_write.py`](file:///c:/Users/desktop/Documents/work/celestial_rose/paradiso/artifacts/audits/poc/poc_f076_lane_a_stale_exec_write.py) (`2/2 FAIL`)

## Active Open Findings

None.
## Waived / Accepted Risk
- **F-075 (LOW):** apostrophe in inline onclick - waived (names use only alphanumerics, `_` and `.`).
- **F-076 (LOW):** stale ExecutionService write at 22:00 cutoff - ACCEPTED RISK by operator (2026-10-03 15:28 +08:00); needs a report to exit within the split second before the cutoff tick, effect is a cosmetic catalog/ledger mismatch.

## Historical Resolved Batches
- **Batches 1-16 (F-001 through F-074):** Verified & Archived in `paradiso/artifacts/audits/resolved/`.


