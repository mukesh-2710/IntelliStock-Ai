import numpy as np, pytest
from src import forecasting as F

def _inputs(sim): return sim.sold, sim.stock, sim.live, sim.promo, sim.dates.dayofweek.values

def test_no_future_leakage_changing_future_sales_does_not_change_forecast(built):
    _, sim, _, _ = built; sold, stock, live, promo, dow = _inputs(sim); e = 300
    a = F.fit_predict(sold, stock, live, promo, dow, e, dow[e:e + 28])
    s2 = sold.copy(); s2[:, e:] = 999
    b = F.fit_predict(s2, stock, live, promo, dow, e, dow[e:e + 28])
    for m in F.MODELS: assert np.allclose(a["preds"][m], b["preds"][m])

def test_leakage_guard_raises():
    with pytest.raises(ValueError): F.assert_no_leakage(310, 300)
    F.assert_no_leakage(300, 300)

def test_forecasts_are_nonnegative_and_finite(built):
    _, sim, _, _ = built; sold, stock, live, promo, dow = _inputs(sim)
    r = F.fit_predict(sold, stock, live, promo, dow, 365, dow[:31])
    for m, p in r["preds"].items(): assert (p >= 0).all() and np.isfinite(p).all()

def test_temporal_holdout_and_metrics(built):
    _, _, _, bt = built; m = bt["metrics"].set_index("model")
    assert set(F.MODELS) | {"selected_per_pair", "moving_avg_censoring_ignored"} == set(m.index)
    assert (m.holdout_days == 28).all() and (m.pairs_evaluated > 50).all()
    assert (m.WAPE > 0).all() and (m.WAPE < 1.0).all() and 0.7 < bt["holdout_interval_coverage"] <= 1.0

def test_censoring_aware_training_reduces_underforecast(built):
    _, _, _, bt = built; m = bt["metrics"].set_index("model")
    assert m.loc["moving_avg", "bias"] >= m.loc["moving_avg_censoring_ignored", "bias"]       # stockouts are not zero demand

def test_croston_returns_zero_for_no_demand_history():
    z = np.zeros((2, 100), int); live = np.ones((2, 100), bool); st = np.zeros((2, 100), bool)
    r = F.fit_predict(z, st, live, st, np.arange(100) % 7, 100, np.arange(7))
    assert (r["preds"]["croston_sba"] == 0).all()

def test_forecast_table_integrity(built):
    _, sim, tb, _ = built; f = tb["forecast"]
    assert len(f) == len(sim.pairs) and f.forecast_id.is_unique and (f.data_cutoff_date < f.forecast_start_date).all()
    assert (f.lower_90 <= f.total_forecast).all() and (f.total_forecast <= f.upper_90).all()
    assert "category_fallback" in set(f.model_name) and (f[f.model_name == "category_fallback"].confidence == "LOW").all()   # cold start / launches
