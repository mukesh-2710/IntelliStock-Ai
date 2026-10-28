# Reasoning: problem, assumptions, decisions, trade-offs, testing, limitations
## Problem as understood
Forecast SKU-store demand and recommend replenishment under lead time, safety stock, MOQ, pack size and capacity, on synthetic data with exceptions, traceability, ground truth, and reproducibility.
## Key assumptions
1. Observed sales are *censored* by stock availability; true demand is hidden ground truth. 2. Only a subset of the SKU×store matrix is stocked (5% at full scale) — 73M daily rows per table would be unusable. 3. One year of history (2025) forecasts the month 2026-01. 4. Boundary rule: inventory position == reorder point → reorder. 5. Supplier terms apply as of the *order* date.
## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| Schema as code (`schema.py`) | one source for dictionary, validators, DDL, docs | tuple DSL is terse |
| Simulate inventory to create sales | stockouts/censoring arise from rules, not random labels (brief step 5) | more complex generator |
| Exclude stockout days from training | zero ≠ no demand (required edge case) | fewer training days for fragile items |
| 4 simple models + per-pair selection | robust, explainable, cheap at 10k pairs | no ML model; selection ≈ best single model |
| Calibrated intervals on a validation window | honest coverage vs holdout (87–90%) | global ratio quantiles, not per-SKU |
| Infeasible ≠ silently violate | hard constraints stay hard | many INFEASIBLE rows for large-MOQ slow items |
| Inject into a *copy* after clean baseline | anomalies are labelled, nothing else corrupted | injection is deterministic, easy to detect |
## Testing approach
Unit tests on formulas (worked example 90→96, capacity cap, infeasible); property tests on generated data (reconciliation, lifecycle, censoring flag = availability); leakage test (changing future sales leaves forecasts unchanged); validator negative tests; detection P/R on injected labels; export-vs-dictionary and double-run checksum test.
## How I know it works / what I do not know
Known: constraints hold in 100% of baseline recommendations; reproducibility holds; detectors find all labelled rows with no alerts on clean data. Not known: forecast quality on real retail data; dashboard/API behaviour beyond compile checks; generator realism beyond the distributions I chose.
## Limitations
No promo calendar as forecast input; no yearly seasonal index; one supplier per SKU per date; full receipts only; no RBAC/idempotency; WAPE ~0.44 and ~−18% bias at full scale.
## Walkthrough talking points
(1) Why censoring matters — show `moving_avg_censoring_ignored` vs `moving_avg` bias. (2) Walk one explanation string: ROP, order-up-to, MOQ→pack→capacity. (3) Show clean baseline then `ground_truth.csv` vs `reports/exceptions_detected.csv`. (4) Run `scripts/reproduce.py`. (5) Be ready to say what you would do next: promo calendar features, per-SKU interval calibration, partial receipts, LightGBM comparison.
