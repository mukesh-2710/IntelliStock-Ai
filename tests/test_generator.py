import numpy as np, pandas as pd
from src import schema, validation
from src.generator import generate, daily_frames

def test_ids_are_zero_padded_and_deterministic_format(built):
    _, sim, tb, _ = built
    rep = [r for r in validation.validate_small(tb) if r["check"].startswith("id_format")]
    assert rep and all(r["status"] == "PASS" for r in rep)
    s, i = daily_frames(sim, 0, 2)
    assert s.sale_id.iloc[0] == f"SALE-{s.store_id.iloc[0]}-{s.sku_id.iloc[0]}-{s.sale_date.iloc[0]}"
    assert tb["forecast"].forecast_id.iloc[0] == f"FC-{tb['forecast'].store_id.iloc[0]}-{tb['forecast'].sku_id.iloc[0]}-2026-01"
    assert tb["purchase_recommendation"].recommendation_id.iloc[0] == "PO-2026-000001"

def test_same_seed_same_data_and_different_seed_differs():
    a, b, c = generate(25, 4, .6, seed=7), generate(25, 4, .6, seed=7), generate(25, 4, .6, seed=8)
    assert (a.demand == b.demand).all() and (a.sold == b.sold).all()
    for k in a.tables: pd.testing.assert_frame_equal(a.tables[k], b.tables[k])
    assert not (a.demand.shape == c.demand.shape and (a.demand == c.demand).all())

def test_scale_is_parameterised():
    s = generate(30, 3, 1.0, seed=1); assert len(s.pairs) >= 30 and s.tables["store"].shape[0] == 3 and s.demand.shape[1] == 365

def test_stockout_is_recorded_separately_from_zero_demand(built):
    _, sim, _, _ = built; avail = sim.opening + sim.received
    assert (sim.stock & sim.live).sum() > 0
    assert (sim.stock[sim.live] == ((avail == 0) | (sim.demand > avail))[sim.live]).all()        # flag derived from availability
    true_zero = sim.live & (sim.demand == 0) & (avail > 0)
    assert true_zero.sum() > 0 and not sim.stock[true_zero].any()                                  # zero demand is NOT a stockout
    assert (sim.demand - sim.sold)[sim.live].sum() > 0 and (sim.sold <= sim.demand).all()          # lost sales exist, observed <= true

def test_inventory_reconciles_and_never_negative(built):
    _, sim, _, _ = built; m = sim.live
    assert (sim.closing == sim.opening + sim.received - sim.sold)[m].all() and (sim.closing >= 0).all()

def test_lifecycle_launch_and_discontinuation(built):
    _, sim, tb, _ = built; sku = tb["sku"].set_index("sku_id"); launch = sku.loc[sim.pairs.sku_id, "launch_date"].values
    for p in range(len(sim.pairs)):
        first = sim.iso[sim.live[p]][:1]
        if len(first): assert first[0] >= launch[p] or launch[p] < "2025-01-01"
    planned = set(sku[sku.lifecycle_status == "PLANNED"].index); assert planned and not sim.live[sim.pairs.sku_id.isin(planned).values].any()
    disc = sku.discontinue_date.dropna()
    for sid, d in disc.items():
        rows = np.where(sim.pairs.sku_id.values == sid)[0]; late = sim.iso > d
        assert sim.sold[np.ix_(rows, np.where(late)[0])].sum() == 0

def test_intermittent_demand_and_variation_present(built):
    _, sim, _, _ = built; prof = sim.pairs.profile.values; zeros = (sim.demand == 0)[sim.live]
    inter = (sim.demand[prof == "intermittent"] == 0)[sim.live[prof == "intermittent"]].mean()
    assert inter > .5 and set(np.unique(prof)) == {"stable", "intermittent", "seasonal", "trending"} and sim.promo.any()

def test_supplier_terms_and_lead_times(built):
    _, _, tb, _ = built; ss = tb["supplier_sku"]
    assert (ss.pack_size >= 1).all() and (ss.moq_units >= ss.pack_size).all()
    assert ss.groupby("sku_id").supplier_id.nunique().max() >= 2                     # N:M: some SKUs have several suppliers
    assert tb["lead_time_observation"].lead_time_days.min() >= 1 and tb["lead_time_observation"].lead_time_days.nunique() > 5
