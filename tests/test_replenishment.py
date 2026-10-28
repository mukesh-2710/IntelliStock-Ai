import numpy as np, pandas as pd, pytest
from src import replenishment as R

def test_worked_example_rop_and_pack_rounding():
    assert 20 * 5 + 30 == 130                                 # ROP = mu*L + SS
    assert R.order_qty(90, 48, 12, 500) == (96, "OK")         # 90 -> next pack multiple
    assert R.order_qty(10, 48, 12, 500) == (48, "OK")         # MOQ dominates
    assert R.order_qty(50, 48, 12, 500) == (60, "OK")         # 50 -> 60 (multiple of 12)
    assert R.order_qty(0, 48, 12, 500) == (0, "NONE")

def test_capacity_cap_and_infeasible_never_violate_constraints():
    assert R.order_qty(90, 48, 12, 70) == (60, "CAPPED")      # round room DOWN to pack multiple, still >= MOQ
    assert R.order_qty(90, 48, 12, 40) == (0, "INFEASIBLE")   # MOQ cannot fit -> explicit infeasible
    q, _ = R.order_qty(np.array([90, 5]), np.array([48, 6]), np.array([12, 3]), np.array([70, 100])); assert list(q) == [60, 6]

def test_safety_stock_formula():
    assert abs(R.safety_stock(1.645, 20, 5, 5, 1) - 1.645 * np.sqrt(5 * 25 + 400 * 1)) < 1e-9
    assert R.safety_stock(1.645, 20, 5, 5, 0) < R.safety_stock(1.645, 20, 5, 5, 2)    # lead-time variability raises SS

def test_all_baseline_recommendations_respect_constraints(built):
    r = built[2]["purchase_recommendation"]; b = r[r.recommended_qty > 0]
    assert len(b) > 0
    assert (b.recommended_qty % b.supplier_pack_size.astype(float) == 0).all() and (b.recommended_qty >= b.supplier_moq.astype(float)).all()
    assert (b.inventory_position + b.recommended_qty <= b.max_stock_units).all()

def test_decision_rules_and_exceptions(built):
    _, _, tb, _ = built; r = tb["purchase_recommendation"]; sku = tb["sku"].set_index("sku_id")
    assert (r[r.decision.str.startswith("REORDER")].inventory_position <= r[r.decision.str.startswith("REORDER")].reorder_point_units).all()   # boundary: IP<=ROP
    no = r[(r.decision == "NO_ORDER") & (r.daily_demand_forecast > .01)]; assert (no.inventory_position > no.reorder_point_units).all()
    assert (r[r.decision.str.startswith("BLOCKED") | (r.decision == "INFEASIBLE_CAPACITY")].recommended_qty == 0).all()
    d = r[sku.loc[r.sku_id, "lifecycle_status"].values == "DISCONTINUED"]; assert len(d) and (d.recommended_qty == 0).all() and (d.decision == "BLOCKED_DISCONTINUED").all()
    assert {"INFEASIBLE_CAPACITY", "BLOCKED_NO_SUPPLIER"} <= set(r.decision)                    # exception paths exercised
    assert r.explanation.str.len().min() > 30 and r.explanation.str.contains("ROP=").all()

def test_lineage_and_status_events(built):
    _, _, tb, _ = built; r, ev = tb["purchase_recommendation"], tb["recommendation_event"]
    assert r.forecast_id.isin(tb["forecast"].forecast_id).all() and r.policy_id.isin(tb["reorder_policy"].policy_id).all()
    assert len(ev) == 2 * len(r) and ev.event_id.is_unique
    order_dates = r.set_index("recommendation_id").order_date
    event_dates = pd.to_datetime(ev.event_ts, utc=True)
    assert (event_dates.dt.strftime("%Y-%m-%d").values >= ev.recommendation_id.map(order_dates).values).all()
    assert ev.groupby("recommendation_id", sort=False).event_ts.apply(lambda ts: ts.is_monotonic_increasing).all()

def test_make_events_rejects_duplicate_recommendations(built):
    recs = built[2]["purchase_recommendation"].iloc[:2].copy()
    recs.iloc[1, recs.columns.get_loc("recommendation_id")] = recs.iloc[0].recommendation_id
    with pytest.raises(ValueError, match="recommendation IDs must be unique"):
        R.make_events(recs)

def test_lifecycle_transitions_and_duplicate_approval():
    e1 = R.transition("PO-2026-000001", "GENERATED", "VALIDATED", "system", "ok", "t1")
    e2 = R.transition("PO-2026-000001", "VALIDATED", "PENDING_APPROVAL", "system", "ok", "t2", [e1])
    e3 = R.transition("PO-2026-000001", "PENDING_APPROVAL", "APPROVED", "ops_manager", "ok", "t3", [e1, e2])
    with pytest.raises(ValueError): R.transition("PO-2026-000001", "APPROVED", "APPROVED", "x", "dup", "t4", [e1, e2, e3])
    with pytest.raises(ValueError): R.transition("PO-2026-000001", "GENERATED", "COMPLETED", "x", "skip", "t4")
    with pytest.raises(ValueError): R.transition("PO-2026-000001", "REJECTED", "APPROVED", "x", "terminal", "t4")
