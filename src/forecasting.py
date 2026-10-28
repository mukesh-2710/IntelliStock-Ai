"""Censoring-aware demand forecasting with temporal holdout.
Models: moving average, exponential smoothing, Croston-SBA (intermittent), seasonal-naive (weekday).
Stockout days are EXCLUDED from training (censored, not zero demand). Training never sees data at/after `e`."""
import numpy as np, pandas as pd
from config.settings import HOLDOUT_DAYS, MIN_VALID_DAYS
MODELS = ["moving_avg", "exp_smooth", "croston_sba", "seasonal_naive"]

def assert_no_leakage(train_end_idx, target_start_idx):
    if train_end_idx > target_start_idx: raise ValueError("temporal leakage: training window overlaps forecast period")

def fit_predict(sold, stock, live, promo, dow, e, fut_dow, W=56):
    """Fit on days [0,e) only; return daily forecasts [P,h] per model + diagnostics."""
    valid = (live & ~stock)[:, :e]; x = sold[:, :e].astype(float); pr = promo[:, :e]
    a, b = valid & pr, valid & ~pr
    u = float(np.clip(x[a].mean() / max(x[b].mean(), 1e-9), 1, 3)) if a.sum() > 50 and b.sum() > 0 else 1.0
    x = x / np.where(pr, u, 1.0)                                                # strip promo uplift -> baseline demand
    tot = (x * valid).sum() / max(valid.sum(), 1); f = np.ones(7)
    for d in range(7):
        m = valid & (dow[:e] == d)[None, :]; f[d] = (x * m).sum() / max(m.sum(), 1) / max(tot, 1e-9)
    f = np.clip(f, .5, 1.8); xd = x / f[dow[:e]][None, :]; lo = max(0, e - W)
    n = np.maximum(valid[:, lo:].sum(1), 1)
    ma = (xd[:, lo:] * valid[:, lo:]).sum(1) / n
    w = 0.97 ** (e - 1 - np.arange(e)); es = (xd * valid * w).sum(1) / np.maximum((valid * w).sum(1), 1e-9)
    z = np.zeros(len(x)); p = np.ones(len(x)); q = np.zeros(len(x)); init = np.zeros(len(x), bool)
    for t in range(e):                                                          # Croston / SBA, alpha=0.1
        vt = valid[:, t]; xt = xd[:, t]; q = q + vt; hit = vt & (xt > 0); first = hit & ~init
        z = np.where(first, xt, np.where(hit, z + .1 * (xt - z), z)); p = np.where(first, q, np.where(hit, p + .1 * (q - p), p))
        q = np.where(hit, 0, q); init |= hit
    cr = np.where(init, (1 - .05) * z / np.maximum(p, 1e-9), 0.0)
    sn = np.zeros((len(x), 7)); lo4 = max(0, e - 56)
    for d in range(7):
        m = valid[:, lo4:] & (dow[lo4:e] == d)[None, :]; k = m.sum(1)
        sn[:, d] = np.where(k > 0, (x[:, lo4:] * m).sum(1) / np.maximum(k, 1), ma * f[d])
    preds = {"moving_avg": ma[:, None] * f[fut_dow][None, :], "exp_smooth": es[:, None] * f[fut_dow][None, :],
             "croston_sba": cr[:, None] * f[fut_dow][None, :], "seasonal_naive": sn[:, fut_dow]}
    preds = {k: np.maximum(v, 0) for k, v in preds.items()}                      # non-negative forecasts
    lo9 = max(0, e - 90); vv = valid[:, lo9:]; xx = x[:, lo9:]; k = np.maximum(vv.sum(1), 1)
    mean = (xx * vv).sum(1) / k; sd = np.sqrt(np.maximum((xx ** 2 * vv).sum(1) / k - mean ** 2, 0))
    return dict(preds=preds, n_valid=valid.sum(1), sd=sd, factors=f, uplift=u)

def _metrics(fc, act):
    err = fc - act; s = max(act.sum(), 1e-9)
    return dict(MAE=float(np.abs(err).mean()), RMSE=float(np.sqrt((err ** 2).mean())),
                WAPE=float(np.abs(err).sum() / s) if act.sum() > 0 else float("nan"), bias=float(err.sum() / s) if act.sum() > 0 else float("nan"))

def run_backtest(sold, stock, live, promo, dow, demand_true, H=HOLDOUT_DAYS):
    """Rolling-origin: validation window picks the model per pair (observed, uncensored sales only);
    the final holdout is scored against TRUE demand (evaluation-only; never used in fitting)."""
    T = sold.shape[1]; e_test, e_val = T - H, T - 2 * H
    assert_no_leakage(e_val, e_val); assert_no_leakage(e_test, e_test)
    pv = fit_predict(sold, stock, live, promo, dow, e_val, dow[e_val:e_val + H])
    ok = (live & ~stock)[:, e_val:e_val + H]; obs = sold[:, e_val:e_val + H]
    E = np.stack([(np.abs(pv["preds"][m] - obs) * ok).sum(1) for m in MODELS], 1); sel = E.argmin(1)
    sel_val = np.take_along_axis(np.stack([pv["preds"][m] for m in MODELS], 2), sel[:, None, None], 2)[:, :, 0]
    good = pv["n_valid"] >= MIN_VALID_DAYS
    ratio = (obs.sum(1)[good] + 1) / (sel_val.sum(1)[good] + 1)                  # calibrate 90% interval on validation window
    qlo, qhi = (float(np.quantile(ratio, .05)), float(np.quantile(ratio, .95))) if good.sum() > 10 else (.5, 1.5)
    pt = fit_predict(sold, stock, live, promo, dow, e_test, dow[e_test:]); act = demand_true[:, e_test:].astype(float)
    elig = (pt["n_valid"] >= MIN_VALID_DAYS) & live[:, e_test:].all(1)
    rows = []
    for m in MODELS: rows.append(dict(model=m, **_metrics(pt["preds"][m][elig], act[elig])))
    stk = np.stack([pt["preds"][m] for m in MODELS], 2); selp = np.take_along_axis(stk, sel[:, None, None], 2)[:, :, 0]
    rows.append(dict(model="selected_per_pair", **_metrics(selp[elig], act[elig])))
    nc = fit_predict(sold, np.zeros_like(stock), live, promo, dow, e_test, dow[e_test:])   # EC-001 impact: censoring ignored
    rows.append(dict(model="moving_avg_censoring_ignored", **_metrics(nc["preds"]["moving_avg"][elig], act[elig])))
    tf = (selp.sum(1) + 1); ta = act.sum(1) + 1; cov = float(((ta >= tf * qlo) & (ta <= tf * qhi))[elig].mean())
    m = pd.DataFrame(rows); m["pairs_evaluated"] = int(elig.sum()); m["holdout_days"] = H
    return dict(metrics=m, selection=sel, qlo=qlo, qhi=qhi, holdout_interval_coverage=cov)

def build_forecast_table(pairs, sold, stock, live, promo, dow, fut_dates, bt):
    T = sold.shape[1]; h = len(fut_dates); fut_dow = fut_dates.dayofweek.values; assert_no_leakage(T, T)
    r = fit_predict(sold, stock, live, promo, dow, T, fut_dow)
    stk = np.stack([r["preds"][m] for m in MODELS], 2); fc = np.take_along_axis(stk, bt["selection"][:, None, None], 2)[:, :, 0]
    name = np.array(MODELS, dtype=object)[bt["selection"]]; nv = r["n_valid"]; weak = nv < MIN_VALID_DAYS
    cat = pairs.category.values; daily = fc.mean(1); cm = pd.Series(daily[~weak]).groupby(cat[~weak]).mean()
    fb = pd.Series(cat).map(cm).fillna(daily[~weak].mean() if (~weak).any() else 0.0).values
    daily = np.where(weak, fb, daily); name = np.where(weak, "category_fallback", name)
    sd = np.where(weak, np.sqrt(np.maximum(daily, .01)), r["sd"])               # cold start: Poisson-style sd
    total = daily * h; lo = np.maximum((total + 1) * bt["qlo"] - 1, 0); hi = (total + 1) * bt["qhi"] - 1
    lo = np.minimum(lo, total); hi = np.maximum(hi, total)
    conf = np.where(weak | (name == "category_fallback"), "LOW", np.where(nv >= 150, "HIGH", "MEDIUM"))
    ym = fut_dates[0].strftime("%Y-%m"); cutoff = (fut_dates[0] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return pd.DataFrame(dict(forecast_id="FC-" + pairs.store_id + "-" + pairs.sku_id + "-" + ym, store_id=pairs.store_id, sku_id=pairs.sku_id,
        forecast_month=ym, forecast_start_date=fut_dates[0].strftime("%Y-%m-%d"), forecast_end_date=fut_dates[-1].strftime("%Y-%m-%d"),
        data_cutoff_date=cutoff, model_name=name, history_valid_days=nv.astype(int), daily_forecast=np.round(daily, 4),
        demand_std_daily=np.round(sd, 4), total_forecast=np.round(daily * h, 3), lower_90=np.round(lo, 3), upper_90=np.round(hi, 3),
        confidence=conf, forecast_version=1))
