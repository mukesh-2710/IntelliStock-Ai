# IntelliStock AI

**SKU-store demand forecasting and constraint-aware replenishment**

IntelliStock AI is a synthetic retail planning pipeline. It generates demand and inventory data, compares baseline forecasts, creates purchase recommendations under supplier and capacity constraints, injects labeled data-quality anomalies, and reports validation and detection results.

> The project uses synthetic data only. It is a challenge/demo project, not a production inventory system.

## What it does

- Simulates SKU, store, supplier, sales, inventory, and replenishment-policy data.
- Accounts for censored sales: a stockout is not treated as zero demand during model training.
- Backtests moving-average, exponential-smoothing, Croston-SBA, and seasonal-naive forecasts using a chronological holdout.
- Calculates reorder points and safety stock, then applies MOQ, pack-size, and storage-capacity constraints.
- Injects five labeled anomaly types and measures detection precision and recall.
- Exports CSV reports, a SHA-256 manifest, and an optional constraint-checked SQLite database.

## Quick start

From the project root, install the dependencies and run the starter pipeline:

```bash
python -m pip install -r requirements.txt
python -m src.pipeline --scale starter --out output
python -m pytest -q
```

Expected checks: **30 tests pass**, **110/110 baseline validation checks pass**, and injected-anomaly detection reports **1.0 precision and 1.0 recall** on the starter run.

To include the SQLite export:

```bash
python -m src.pipeline --scale starter --out output --sqlite
```

To regenerate the data twice and compare row counts and checksums:

```bash
python scripts/reproduce.py --scale starter
```

The script prints `REPRODUCIBLE` when both generated runs match.

## Run the interfaces

```bash
streamlit run app/dashboard.py
```

```bash
uvicorn app.api:app --reload
```

The API exposes `/health`, `/recommendations`, `/exceptions`, and `/whatif`. The dashboard and API require their optional packages, which are listed in `requirements.txt`.

## Pipeline and output

Run a larger configuration with:

```bash
python -m src.pipeline --scale medium --out output_medium
python -m src.pipeline --scale full --out output_full
```

Available scales and defaults are in [`config/settings.py`](config/settings.py). You can override `--n-skus`, `--n-stores`, `--assortment`, and `--n-inject`.

The output directory contains generated entity tables, `sales_history.csv`, `inventory_snapshot.csv`, `manifest.json`, and reports under `reports/`. Ground-truth labels and hidden-demand evaluation data are stored under `ground_truth/`.

The default full configuration has 2,000 SKUs and 100 stores, but only 5% of SKU-store relationships are active. It produces **3,986,399 daily rows per table**, not the complete 73-million-cell matrix. Set `--assortment 1.0` to activate all possible pairs; this configuration is RAM-intensive and has not been benchmarked.

When `--sqlite` is used, SQLite stores the clean baseline data with primary keys, foreign keys, and row-level checks. Deliberately injected invalid records remain in the CSV outputs so the anomalies can be examined. SQLite foreign-key enforcement is connection-specific; clients should run `PRAGMA foreign_keys = ON`.

## Verified results

The full scale was run in the development workspace. Results:

| Measure | Result |
|---|---:|
| Daily sales rows | 3,986,399 |
| Baseline validation | 110/110 passed |
| Injected anomalies | 1,000 |
| Detection precision / recall | 1.00 / 1.00 |
| Selected forecast WAPE | 0.436 |
| Selected forecast bias | -18.4% |
| Runtime | 83.4 seconds |
| Generated output size | About 705 MB |

Two same-seed full-scale runs produced matching row counts and SHA-256 checksums. See [`docs/reproducibility_report_full.txt`](docs/reproducibility_report_full.txt). Runtime and output size vary by machine.

Detection scores measure performance on the project’s rule-defined synthetic anomalies; they are not evidence of equivalent real-world detection accuracy. Forecast metrics are measured on a synthetic 28-day temporal holdout and should not be interpreted as production performance.

## Project documentation

- [Architecture](docs/architecture.md)
- [Data dictionary](docs/data_dictionary.md)
- [Schema and lifecycle](docs/schema.md)
- [Assumptions, decisions, and limitations](docs/REASONING.md)
- [AI-use disclosure](docs/AI_USAGE.md)
- [Prompt history](docs/PROMPT_HISTORY.md)

## Repository structure

```text
app/       Streamlit dashboard and FastAPI service
config/    Scale and generator settings
data/      Sample synthetic data and manifests
docs/      Architecture, schema, reasoning, and disclosures
scripts/   Reproducibility utilities
src/       Generator, forecasting, replenishment, validation, and pipeline
tests/     Automated tests
```

## Scope and limitations

- Synthetic data only; real-world forecast performance is unknown.
- One year of history, a one-month forecast, and no yearly seasonal index.
- Promotion calendars are not supplied as forecast inputs.
- One supplier is selected per SKU; there is no shared warehouse-capacity optimizer.
- Baseline orders are modeled as fully received; partial receipts and cancellations are not simulated.
- Authentication, role-based access control, and idempotent API writes are not implemented.
