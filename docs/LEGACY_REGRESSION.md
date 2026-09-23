# V1 legacy regression and V1/V2 comparison

V1 is preserved as an immutable audit reference. The regression report is a
three-way check:

1. **V1 Excel → V1 JSON (authoritative PASS/FAIL):** the V1 workbook contains the
   full-precision daily returns used by the original engine. The report
   reconstructs V1's 12-1 Momentum and FIP, including the original denominator
   rule where FIP uses the union of BIST trading days across all equities in the
   legacy window. Rounded results must match the published V1 top-level JSON.
2. **V1 JSON self-reconstruction (informational):** daily returns in detail JSON
   are rounded to 6 decimals, so compounded Momentum cannot always reproduce the
   full-precision Excel result bit-for-bit. This is not the authoritative gate.
3. **V1 vs V2 (descriptive only):** V1 uses a 12-1 calendar-month window; V2 uses
   fixed 252/126/63/21 trading-day windows. Differences are expected and are not
   a PASS/FAIL criterion.

## As-of protection

The archived V1 workbook has date headers extending beyond the published V1
output date. Therefore the report does **not** infer V1 as-of from the maximum
Excel header or maximum numeric Excel cell. It infers the published as-of date
from the detail JSON daily rows, then applies that date to the Excel regression.
This prevents future/preallocated columns from silently changing the legacy
window.

Run:

```bash
python run.py legacy-report \
  --legacy-detail-dir migration/legacy/json \
  --legacy-excel migration/legacy/excel/Claude_Momentum_Screener_BIST_Labyrinth.xlsx \
  --legacy-report-out migration/reports/v1_v2_comparison.json
```
