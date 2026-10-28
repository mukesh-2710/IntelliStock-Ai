# IntelliStock AI — SKU-Location Demand Forecasting & Constraint-Aware Replenishment
YottaFlex.ai Round 2 (Associate AI Forward Deployed Engineer). Fully synthetic, fixed seed `20261022`, one generator for starter and full scale.

## Quick start
```bash
pip install -r requirements.txt            # numpy, pandas, pytest (+ streamlit/plotly/fastapi optional)
python -m src.pipeline --scale starter --out output --sqlite     # 60 SKUs x 8 stores, seconds
python -m src.pipeline --scale full --out output_full            # 2,000 SKUs x 100 stores x 365 days
pytest -q                                   # 30 tests
python scripts/reproduce.py --scale starter # regenerate twice, compare rows + SHA-256
streamlit run app/dashboard.py              # 5 tabs: overview, forecasting, replenishment, exceptions, what-if
uvicorn app.api:app                         # /recommendations /exceptions /whatif /health
```
Scales: `starter` · `medium` · `full` (see `config/settings.py`); override with `--n-skus --n-stores --assortment --n-inject`.
**Volume note:** 2,000×100×365 = 73M possible cells. The default `assortment=0.05` activates about 10k SKU-store pairs (≈100 SKUs/store) and produces **3,986,399 rows per daily table**; it is not the literal full SKU-store matrix. Use `--assortment 1.0` for all 73M cells (RAM-heavy; not benchmarked here).

## Verify key behavior (≈2 minutes)
```bash
pytest -q                                    # 30 passed
python scripts/reproduce.py                  # prints REPRODUCIBLE
python -m src.pipeline --scale starter --out output
# expect: "110/110 checks PASS", detection precision/recall 1.0, holdout metrics per model
head -3 output/ground_truth/ground_truth.csv output/reports/exceptions_detected.csv
```
Submission-guideline docs: [`docs/REASONING.md`](docs/REASONING.md) (assumptions, trade-offs, limits, walkthrough points) · [`docs/AI_USAGE.md`](docs/AI_USAGE.md) · [`docs/PROMPT_HISTORY.md`](docs/PROMPT_HISTORY.md) · `scripts/git_history.sh` (meaningful commits).

## Pipeline (`src/pipeline.py`)
1. **Generate** master data (SKU, Store, Supplier, SupplierSKU bridge, ReorderPolicy = the SKU/store matrix) → true demand (base × seasonality × trend × promo × store × weekday × holiday, Poisson, intermittent profiles, spikes, staggered launches, discontinuations) → inventory/replenishment simulation. **Sales are censored by availability**; `stockout_flag` is stored separately from zero demand. Lead times come from per-supplier distributions with random delays; MOQ/pack sizes/capacity are enforced in the simulation.
2. **Validate baseline** (110 schema-driven checks: PK, FK, enums, required, ID formats, date order, reconciliation, lifecycle, duplicates, overlapping effective dates, event timestamps/order). Must be clean *before* any injection.
3. **Forecast** (`src/forecasting.py`): moving average, exponential smoothing, Croston-SBA, weekday seasonal-naive; trained only on uncensored days with promo uplift removed; per-pair model chosen on a validation window; **temporal holdout** (last 28 days) scored vs true demand; 90% intervals calibrated on the validation window; cold-start/launch pairs → `category_fallback` with LOW confidence. Forecast for **2026-01** (`FC-<store>-<sku>-2026-01`).
4. **Replenish** (`src/replenishment.py`): `SS = z·√(L·σd² + μ²·σL²)`, `ROP = μL + SS`, order-up-to `μ(L+R)+SS`, then **MOQ → pack multiple → capacity**; if no valid quantity exists the result is `INFEASIBLE_CAPACITY` (qty 0), never a silent violation. Supplier terms are the ones *effective on the order date*. Every row has an explanation, forecast/policy lineage and append-only status events (`GENERATED → VALIDATED/BLOCKED/NO_ACTION`, plus an enforced approval workflow in `replenishment.transition`).
5. **Inject** 5 labelled edge cases into a *copy* (`src/injection.py`) and write `ground_truth/ground_truth.csv` (ID, entity, record, issue_type, rule, original → injected value). True demand lives only in `ground_truth/` and is never an input.
6. **Detect** (`src/anomaly_detection.py`, rules only look at inputs) and score precision/recall against ground truth.
7. **Export** CSV (+ optional constrained SQLite baseline and `seed.sql`), `manifest.json` (rows + SHA-256, seed, command, env, provenance), `reports/validation_summary.json`.

The rule-based stockout detector consumes the sales and inventory rows (in chunks), rather than reading the simulator arrays. Recommendation status events are dated to the recommendation's `order_date` and ordered deterministically within that date. When `--sqlite` is used, the database contains the clean baseline tables and daily rows; deliberately injected anomalies remain in the CSV outputs and reports. SQLite enforces declared foreign keys, required fields, row-level checks, and recommendation-event date/order triggers. Applications must enable `PRAGMA foreign_keys = ON` on each SQLite connection.

## Required edge cases
| Edge case | Injected as | Detection rule |
|---|---|---|
| Stockout mistaken for zero demand | `stockout_flag` cleared on a no-stock zero-sale day | zero sale ∧ opening+received = 0 ∧ flag = 0 |
| Qty ignores pack size | qty+1 on a pack≥2 order | qty % pack ≠ 0 or qty < MOQ |
| Discontinued SKU recommended | blocked row flipped to REORDER | SKU DISCONTINUED ∧ qty > 0 |
| Negative lead time | received before order | lead_time ≤ 0 or received < order |
| Forecast uses future sales | `data_cutoff_date` after forecast start | cutoff ≥ forecast_start |

Natural (non-injected) exception paths also exercised: infeasible capacity (MOQ > room), capacity-capped orders, no valid supplier agreement (expired contract), suspended supplier, closed store, discontinued/planned SKUs, cold start.

## Measured results (reproduce with the commands above)
| | Starter | Medium | Full (2k×100×365) |
|---|---|---|---|
| Daily rows per table | 88,594 | 543,500 | 3,986,399 |
| Baseline validation | 110/110 PASS | 110/110 | 110/110 |
| Injected anomalies detected (P / R) | 50 → 1.00 / 1.00 | 221 → 1.00 / 1.00 | 1,000 → 1.00 / 1.00 |
| Holdout WAPE: best single model / selected | 0.499 / 0.500 | 0.434 / 0.436 | 0.440 / 0.436 |
| Holdout bias (selected) | −13% | −19% | −18.4% |
| Reproducible (2 runs, matching rows+SHA-256) | yes | – | yes (`docs/reproducibility_report_full.txt`) |
| Runtime (observed in this workspace) | ~3 s | ~7 s | 83.4 s |
| Generated output size (observed) | – | – | 705 MB |

Honest reading: WAPE ≈ 0.44–0.50 is expected at SKU-store-day granularity with Poisson noise and low volumes (many items sell <2 units/day); the 28-day holdout also includes holiday-season effects the models cannot see from one year of history, which explains the persistent under-forecast bias. Censoring-aware training reduces bias vs ignoring stockouts (−18.4% vs −22.5% at full scale). Detection is 100% only because the synthetic anomalies are rule-defined; forecast figures are real holdout results. 90% intervals cover 87–90% of holdout totals.

## Repository layout
`src/` generator, schema (data dictionary as code), forecasting, replenishment, injection, anomaly_detection, validation, pipeline · `app/` dashboard + API · `tests/` 30 tests · `docs/` data_dictionary, schema (ER, cardinality, lifecycle), architecture, reproducibility reports · `data/sample/` committed starter dataset (CSV + reports) · `data/ground_truth.csv`, `data/manifest.json` · `scripts/reproduce.py`.

## Assumptions & limitations
- Synthetic only; no external data (provenance in `manifest.json`). Future promotion calendars are not used as forecast inputs (baseline demand only); one year of history means no yearly seasonal index.
- Forecast covers one month (2026-01) at version 1; lead-time distributions per SKU use observed receipts (supplier-level fallback, then 7±2 days).
- Replenishment uses one supplier per SKU per date (primary first, then cheapest eligible); single-echelon, no budget or multi-SKU capacity allocation.
- Baseline orders are fully received (partial receipts, cancellations not modelled). Not implemented: auth/RBAC, idempotent API writes.
