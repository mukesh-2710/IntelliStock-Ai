"""End-to-end CLI:  python -m src.pipeline --scale starter --out output
generate -> validate baseline -> forecast (temporal holdout) -> replenish -> inject labelled anomalies -> detect -> export."""
import argparse, hashlib, json, os, platform, sqlite3, time
import numpy as np, pandas as pd
from config.settings import SEED, SCALES, HOLDOUT_DAYS
from src import schema, forecasting, replenishment, validation, anomaly_detection, injection
from src.generator import generate, daily_frames, block_size

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def build(scale="starter", seed=SEED, **ov):
    cfg = {**SCALES[scale], **{k: v for k, v in ov.items() if v is not None}}
    sim = generate(cfg["n_skus"], cfg["n_stores"], cfg["assortment"], seed); tb = sim.tables; T = len(sim.dates)
    dow = sim.dates.dayofweek.values; as_of = sim.dates[-1]; fut = pd.date_range(as_of + pd.Timedelta(days=1), periods=31)
    bt = forecasting.run_backtest(sim.sold, sim.stock, sim.live, sim.promo, dow, sim.demand, HOLDOUT_DAYS)
    tb["forecast"] = forecasting.build_forecast_table(sim.pairs, sim.sold, sim.stock, sim.live, sim.promo, dow, fut, bt)[schema.columns("forecast")]
    state = pd.DataFrame(dict(store_id=sim.pairs.store_id, sku_id=sim.pairs.sku_id, on_hand=sim.closing[:, -1], on_order=sim.on_order[:, -1]))
    tb["purchase_recommendation"] = replenishment.recommend(tb, tb["forecast"], state, as_of.strftime("%Y-%m-%d"))
    tb["recommendation_event"] = replenishment.make_events(tb["purchase_recommendation"])
    return cfg, sim, tb, bt

def run(scale="starter", out="output", seed=SEED, sqlite=False, **ov):
    t0 = time.time(); os.makedirs(f"{out}/ground_truth", exist_ok=True); os.makedirs(f"{out}/reports", exist_ok=True)
    cfg, sim, tb, bt = build(scale, seed, **ov)
    rep = validation.validate_small(tb); drep, nrows = validation.validate_daily(sim, tb); base = validation.summarize(rep + drep)   # BASELINE (clean)
    T2, flag, truth = injection.inject(sim, tb, cfg["n_inject"], seed); T2["recommendation_event"] = replenishment.make_events(T2["purchase_recommendation"])
    bs = block_size(sim)
    daily_batches = (
        daily_frames(sim, p0, min(p0 + bs, len(sim.pairs)), flag)
        for p0 in range(0, len(sim.pairs), bs)
    )
    det = anomaly_detection.detect_all(T2, daily_batches); dm, overall = anomaly_detection.evaluate_detection(det, truth)
    files = {}
    def w(name, df, sub=""):
        p = f"{out}/{sub}{name}"; df.to_csv(p, index=False, lineterminator="\n"); files[sub + name] = len(df)
    for t, df in T2.items(): w(f"{t}.csv", df[schema.columns(t)])
    for name, fn in (("sales_history", lambda s, i: s), ("inventory_snapshot", lambda s, i: i)):
        p = f"{out}/{name}.csv"; first = True; n = 0; bs = block_size(sim)
        for p0 in range(0, len(sim.pairs), bs):
            d = fn(*daily_frames(sim, p0, p0 + bs, flag))[schema.columns(name)]; d.to_csv(p, mode="w" if first else "a", header=first, index=False, lineterminator="\n"); first = False; n += len(d)
        files[f"{name}.csv"] = n
    w("ground_truth.csv", truth, "ground_truth/")
    # hidden true demand on censored (stockout) days = lost-sales ground truth; never an input feature
    rows = []; bs = block_size(sim)
    for p0 in range(0, len(sim.pairs), bs):
        m = sim.stock[p0:p0 + bs] & sim.live[p0:p0 + bs]; pi, ti = np.nonzero(m); gp = pi + p0
        rows.append(pd.DataFrame(dict(sale_id="SALE-" + sim.pair_key[gp] + "-" + sim.iso[ti], true_demand=sim.demand[gp, ti], observed_sales=sim.sold[gp, ti])))
    w("true_demand_on_stockout_days.csv", pd.concat(rows), "ground_truth/")
    json.dump(sim.params, open(f"{out}/ground_truth/generation_params.json", "w"), indent=1, sort_keys=True); files["ground_truth/generation_params.json"] = 1
    w("forecast_backtest_metrics.csv", bt["metrics"].round(5), "reports/"); w("detection_metrics.csv", dm.round(5), "reports/"); w("exceptions_detected.csv", det, "reports/")
    r = T2["purchase_recommendation"]; b = tb["purchase_recommendation"]; fcb = tb["forecast"]
    summary = dict(scale=scale, params=cfg, seed=seed, daily_rows_per_table=nrows, baseline_validation=dict(total_checks=base["total_checks"], passed=base["passed"], failed=base["failed"]),
        baseline_checks=base["checks"], detection=dict(overall=overall, per_issue=dm.round(4).to_dict("records")),
        forecast=dict(holdout_days=HOLDOUT_DAYS, interval_90_coverage_on_holdout=round(bt["holdout_interval_coverage"], 4), metrics=bt["metrics"].round(4).to_dict("records")),
        recommendations=dict(total=len(b), decisions=b.decision.value_counts().to_dict(), compliance_pack_moq_capacity=1.0 if not validation.summarize(rep)["failed"] else None,
            units=int(b.recommended_qty.sum()), cost=float(b.total_cost.sum())), forecast_confidence=fcb.confidence.value_counts().to_dict())
    json.dump(summary, open(f"{out}/reports/validation_summary.json", "w"), indent=1, default=str)
    if sqlite: export_sqlite(out, tb, sim)
    manifest = dict(project="IntelliStock AI", seed=seed, scale=scale, params=cfg, generator_command=f"python -m src.pipeline --scale {scale} --out {out} --seed {seed}",
        source="100% synthetic (numpy PCG64, fixed seed); no external/public data, no personal data", license="MIT (code); synthetic data free to use",
        env=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__),
        files=[dict(file=f, rows=n, sha256=sha256(f"{out}/{f}")) for f, n in sorted(files.items())])
    json.dump(manifest, open(f"{out}/manifest.json", "w"), indent=1)
    json.dump(dict(seconds=round(time.time() - t0, 1)), open(f"{out}/reports/run_log.json", "w"))
    return summary, manifest

def export_sqlite(out, tables, sim):
    """Export the clean baseline with enforced constraints; seed.sql omits large daily tables."""
    path = f"{out}/intellistock.db"
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    fk = schema.fks()
    for t, rows in schema.SPEC.items():
        ty = {"string": "TEXT", "date": "TEXT", "int": "INTEGER", "float": "REAL"}
        cols = [
            f'"{r["field"]}" {ty[r["type"]]}'
            + (" NOT NULL" if r["required"] == "Y" or r["key"] == "PK" else "")
            + (" PRIMARY KEY" if r["key"] == "PK" else "")
            for r in rows
        ]
        cols += [f'FOREIGN KEY("{f}") REFERENCES "{pt}"("{pf}")' for (tt, f, pt, pf) in fk if tt == t]
        cols += [f"CHECK ({check})" for check in schema.sqlite_checks(t)]
        con.execute(f'CREATE TABLE "{t}" ({", ".join(cols)})')
    if con.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        con.close()
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
    for t, df in tables.items():
        df.to_sql(t, con, if_exists="append", index=False, chunksize=200_000)
    bs = block_size(sim)
    for p0 in range(0, len(sim.pairs), bs):
        sales, inventory = daily_frames(sim, p0, min(p0 + bs, len(sim.pairs)))
        sales.to_sql("sales_history", con, if_exists="append", index=False, chunksize=200_000)
        inventory.to_sql("inventory_snapshot", con, if_exists="append", index=False, chunksize=200_000)
    con.executescript("""
        CREATE TRIGGER recommendation_event_not_before_order
        BEFORE INSERT ON recommendation_event
        WHEN date(NEW.event_ts) < (
            SELECT order_date FROM purchase_recommendation
            WHERE recommendation_id = NEW.recommendation_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'event cannot predate recommendation order');
        END;
        CREATE TRIGGER recommendation_event_chronological
        BEFORE INSERT ON recommendation_event
        WHEN EXISTS (
            SELECT 1 FROM recommendation_event
            WHERE recommendation_id = NEW.recommendation_id
              AND event_ts >= NEW.event_ts
        )
        BEGIN
            SELECT RAISE(ABORT, 'recommendation events must be chronological');
        END;
    """)
    con.commit()
    skip = ('INSERT INTO "sales_history"', 'INSERT INTO "inventory_snapshot"')   # daily tables ship as CSV / .db only
    with open(f"{out}/seed.sql", "w") as seed:
        seed.write("\n".join(l for l in con.iterdump() if not l.startswith(skip)))
    con.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--scale", default="starter", choices=SCALES); ap.add_argument("--out", default="output")
    ap.add_argument("--seed", type=int, default=SEED); ap.add_argument("--sqlite", action="store_true")
    for k in ("n_skus", "n_stores", "n_inject"): ap.add_argument(f"--{k.replace('_', '-')}", type=int)
    ap.add_argument("--assortment", type=float); a = ap.parse_args()
    s, m = run(a.scale, a.out, a.seed, a.sqlite, n_skus=a.n_skus, n_stores=a.n_stores, n_inject=a.n_inject, assortment=a.assortment)
    print(json.dumps(dict(baseline=f"{s['baseline_validation']['passed']}/{s['baseline_validation']['total_checks']} checks PASS", detection=s["detection"]["overall"],
        holdout={r["model"]: (r["WAPE"], r["bias"]) for r in s["forecast"]["metrics"]}, decisions=s["recommendations"]["decisions"]), indent=1))
