# Architecture
```
config/settings.py ─┐
                    ▼
 generator ─► Sim arrays (true demand, censored sales, inventory) + master tables
     │                          │
     │                    validation (baseline, must be clean)
     ▼                          ▼
 forecasting (temporal holdout, intervals) ─► forecast ─► replenishment ─► recommendation + events
                                                        │
                       injection (copy + labels) ─► row-based anomaly_detection ─► precision/recall vs ground_truth/
                                                        ▼
                         export: CSV · SQLite/seed.sql · manifest (SHA-256) · reports ─► dashboard / API
```
Design decisions
- **Schema as code** (`src/schema.py`): dictionary, validators, SQLite DDL and docs share one definition.
- **Vectorised + chunked**: simulation is NumPy over all pairs per day; daily tables are streamed in blocks. Full-scale CSV output was about 705 MB in the verified run; peak RAM was not measured.
- **Determinism**: single PCG64 stream, stable ordering, `\n` line endings, no timestamps in manifests; verified by `scripts/reproduce.py`.
- **Ground-truth isolation**: injected labels, true demand and hidden generator parameters are written only under `ground_truth/`; forecasters/detectors never import them (tested).
- **Leakage control**: `fit_predict` slices `[0,e)`; `assert_no_leakage`; changing future sales provably leaves forecasts unchanged (tested); holdout is chronological and scored on true demand only for evaluation.
- **Failure over silence**: infeasible orders return `INFEASIBLE_CAPACITY` with an explanation rather than violating MOQ/pack/capacity.
- **Database integrity**: SQLite export uses the clean baseline, turns on foreign-key enforcement during writes, and includes schema-driven row checks plus event chronology triggers. Injected invalid rows remain visible in CSV outputs.
