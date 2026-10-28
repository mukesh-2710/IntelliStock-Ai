import json, os, tempfile, shutil
import pandas as pd
import sqlite3
import pytest
from src import schema, validation, injection, anomaly_detection as AD
from src.pipeline import run
from src.generator import daily_frames, block_size

def daily_batches(sim, flag=None):
    bs = block_size(sim)
    return (
        daily_frames(sim, p0, min(p0 + bs, len(sim.pairs)), flag)
        for p0 in range(0, len(sim.pairs), bs)
    )

def test_baseline_has_zero_validation_failures(built):
    _, sim, tb, _ = built; rep = validation.validate_small(tb); d, n = validation.validate_daily(sim, tb)
    assert n > 10_000 and not [r for r in rep + d if r["status"] == "FAIL"]

def test_validator_catches_broken_data(built):
    tb = {k: v.copy() for k, v in built[2].items()}
    tb["sku"].loc[1, "sku_id"] = tb["sku"].loc[0, "sku_id"]; tb["reorder_policy"].loc[0, "store_id"] = "STORE-999999"; tb["store"].loc[0, "region"] = "Mars"
    bad = {(r["check"], r["table"]) for r in validation.validate_small(tb) if r["status"] == "FAIL"}
    assert ("pk_unique", "sku") in bad and ("fk:store_id->store.store_id", "reorder_policy") in bad and ("enum:region", "store") in bad

def test_injection_is_labelled_complete_and_detected(built):
    cfg, sim, tb, _ = built; T2, flag, truth = injection.inject(sim, tb, 8, 1)
    assert set(truth.issue_type) == set(AD.ISSUES) and truth.record_id.is_unique
    det = AD.detect_all(T2, daily_batches(sim, flag)); m, overall = AD.evaluate_detection(det, truth)
    assert overall["recall"] == 1.0 and overall["precision"] == 1.0 and (m.injected > 0).all()
    base = AD.detect_all(tb, daily_batches(sim)); assert len(base) == 0            # clean baseline raises no alerts

def test_injection_touches_only_labelled_rows(built):
    _, sim, tb, _ = built; T2, flag, truth = injection.inject(sim, tb, 8, 1)
    for t, e in (("lead_time_observation", "NEGATIVE_LEAD_TIME"), ("forecast", "FORECAST_USES_FUTURE_SALES")):
        pk = schema.pks()[t]; ids = set(truth[truth.issue_type == e].record_id); diff = (T2[t] != tb[t]).any(axis=1)
        assert set(T2[t][diff][pk]) == ids

def test_ground_truth_not_leaked_into_inputs(built):
    _, sim, tb, _ = built; banned = {"issue_type", "true_demand", "ground_truth", "demand_profile", "profile"}
    for t, df in tb.items(): assert not banned & set(df.columns), t

def test_export_matches_dictionary_and_is_reproducible():
    d1, d2 = tempfile.mkdtemp(), tempfile.mkdtemp()
    try:
        _, m1 = run("starter", d1, n_skus=25, n_stores=4, n_inject=4); _, m2 = run("starter", d2, n_skus=25, n_stores=4, n_inject=4)
        assert [(f["file"], f["rows"], f["sha256"]) for f in m1["files"]] == [(f["file"], f["rows"], f["sha256"]) for f in m2["files"]]
        for t in schema.SPEC: assert list(pd.read_csv(f"{d1}/{t}.csv", nrows=2).columns) == schema.columns(t)
        s = json.load(open(f"{d1}/reports/validation_summary.json")); assert not s["baseline_validation"]["failed"] and s["detection"]["overall"]["recall"] == 1.0
        assert os.path.exists(f"{d1}/ground_truth/ground_truth.csv")
    finally: shutil.rmtree(d1); shutil.rmtree(d2)

def test_sqlite_export_enforces_constraints_on_clean_baseline():
    out = tempfile.mkdtemp()
    try:
        run("starter", out, n_skus=25, n_stores=4, n_inject=4, sqlite=True)
        con = sqlite3.connect(os.path.join(out, "intellistock.db"))
        try:
            con.execute("PRAGMA foreign_keys = ON")
            assert con.execute("PRAGMA foreign_key_check").fetchall() == []
            sku_id = con.execute("SELECT sku_id FROM sku LIMIT 1").fetchone()[0]
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    """INSERT INTO supplier_sku
                    (supplier_sku_id, supplier_id, sku_id, pack_size, moq_units, unit_cost,
                     effective_from, effective_to, status, is_primary)
                    VALUES ('SSK-999999', 'SUP-999999', ?, 1, 1, 1.0, '2026-01-01', NULL, 'ACTIVE', 0)""",
                    (sku_id,),
                )
            with pytest.raises(sqlite3.IntegrityError):
                con.execute("UPDATE sku SET list_price = 0 WHERE sku_id = ?", (sku_id,))
            rec_id = con.execute("SELECT recommendation_id FROM purchase_recommendation LIMIT 1").fetchone()[0]
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    """INSERT INTO recommendation_event
                    (event_id, recommendation_id, previous_status, new_status, actor, reason, event_ts)
                    VALUES ('EVT-2026-999999', ?, 'GENERATED', 'VALIDATED', 'system', 'test',
                            '2025-12-31T23:59:59Z')""",
                    (rec_id,),
                )
        finally:
            con.close()
    finally:
        shutil.rmtree(out)
