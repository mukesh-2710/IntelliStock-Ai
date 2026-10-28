"""Deterministic, vectorised synthetic retail generator (Steps 1-6).
Order: master data -> SKU/store matrix -> true demand -> inventory/replenishment simulation (sales are
CENSORED by availability) -> derived tables. True demand is kept only for ground truth/evaluation."""
from __future__ import annotations
from dataclasses import dataclass
from statistics import NormalDist
import numpy as np, pandas as pd
from config.settings import SEED, START_DATE, DAYS
from src import schema

# category: (rate multiplier, price range, pack options, seasonal peak day-of-year, service level)
CATS = {"Electronics": (0.5, (40, 600), [1, 2, 4], 335, .95), "Groceries": (2.5, (1, 12), [6, 12, 24], 355, .98),
        "Clothing": (1.0, (8, 90), [2, 4, 6], 170, .90), "Household": (1.2, (5, 80), [2, 4, 12], 120, .95),
        "PersonalCare": (1.6, (2, 30), [6, 12, 24], 200, .90)}
PROFILES = ["stable", "intermittent", "seasonal", "trending"]
REGIONS = ["North", "South", "East", "West", "Central"]
DOW_F = np.array([.85, .85, .9, .95, 1.15, 1.35, 1.2])   # Mon..Sun weekday effect
PROMO_UPLIFT = 1.6
BIG = 10**6

@dataclass
class Sim:
    tables: dict            # small tables (DataFrames)
    pairs: pd.DataFrame     # SKU/store matrix: store_id, sku_id, category, profile
    dates: pd.DatetimeIndex
    iso: np.ndarray
    pair_key: np.ndarray
    demand: np.ndarray      # TRUE demand (ground truth only)
    sold: np.ndarray; opening: np.ndarray; received: np.ndarray; closing: np.ndarray; on_order: np.ndarray
    stock: np.ndarray; promo: np.ndarray; live: np.ndarray
    params: dict            # hidden generation parameters (ground truth)

def _iso(x): return pd.to_datetime(x).strftime("%Y-%m-%d")

def generate(n_skus=60, n_stores=8, assortment=0.5, seed=SEED, days=DAYS) -> Sim:
    rng = np.random.default_rng(seed); T = days
    dates = pd.date_range(START_DATE, periods=T); d0 = dates[0]; t = np.arange(T)
    day = lambda i: _iso(d0 + pd.to_timedelta(np.asarray(i), "D"))
    # ---------------- SKU master ----------------
    cn = list(CATS); ci = rng.choice(5, n_skus, p=[.15, .30, .25, .20, .10])
    prof = rng.choice(PROFILES, n_skus, p=[.35, .30, .20, .15])
    mult = np.array([CATS[c][0] for c in cn])[ci]
    base = np.where(prof == "intermittent", rng.uniform(.08, .5, n_skus), rng.lognormal(np.log(1.5), .6, n_skus) * mult)
    u = rng.random(n_skus)
    life = np.where(u < .04, "DISCONTINUED", np.where(u < .06, "PLANNED", "ACTIVE"))
    launch_idx = np.where(rng.random(n_skus) < .12, rng.integers(20, 300, n_skus), 0)   # staggered product launches
    launch_idx = np.where(life == "PLANNED", T + rng.integers(4, 25, n_skus), np.where(life == "DISCONTINUED", 0, launch_idx))
    pre = rng.integers(30, 400, n_skus)
    disc_idx = np.where(life == "DISCONTINUED", rng.integers(150, max(151, T - 20), n_skus), BIG)
    lo = np.array([CATS[c][1][0] for c in cn])[ci]; hi = np.array([CATS[c][1][1] for c in cn])[ci]
    sku_ids = [f"SKU-{i:06d}" for i in range(1, n_skus + 1)]
    sku = pd.DataFrame(dict(sku_id=sku_ids, sku_name=[f"{cn[c]} item {i:04d}" for i, c in enumerate(ci, 1)],
        category=[cn[c] for c in ci], list_price=np.round(rng.uniform(lo, hi), 2), lifecycle_status=life,
        launch_date=day(np.where(launch_idx > 0, launch_idx, -pre)),
        discontinue_date=[day(d) if d < BIG else None for d in disc_idx]))
    # ---------------- Store master ----------------
    store_ids = [f"STORE-{i:06d}" for i in range(1, n_stores + 1)]
    open_idx = np.where(rng.random(n_stores) < .05, rng.integers(30, 200, n_stores), 0)
    store = pd.DataFrame(dict(store_id=store_ids, store_name=[f"Store {i:03d}" for i in range(1, n_stores + 1)],
        region=rng.choice(REGIONS, n_stores), open_date=day(np.where(open_idx > 0, open_idx, -rng.integers(100, 2000, n_stores))),
        status=rng.choice(["ACTIVE", "TEMP_CLOSED"], n_stores, p=[.97, .03])))
    store_eff = rng.lognormal(0, .3, n_stores)
    # ---------------- Supplier + lead-time distributions ----------------
    n_sup = max(5, n_skus // 40)
    sstat = rng.choice(["ACTIVE", "SUSPENDED", "INACTIVE"], n_sup, p=[.9, .06, .04]); sstat[0] = "ACTIVE"
    lt_mean = rng.integers(3, 15, n_sup); lt_sd = np.round(lt_mean * rng.uniform(.1, .3, n_sup), 2); delay_p = rng.uniform(.05, .25, n_sup)
    sup_ids = [f"SUP-{i:06d}" for i in range(1, n_sup + 1)]
    supplier = pd.DataFrame(dict(supplier_id=sup_ids, supplier_name=[f"Supplier {i:03d}" for i in range(1, n_sup + 1)],
        status=sstat, contract_lead_days=lt_mean))
    # ---------------- SupplierSKU (bridge, effective-dated pack/MOQ) ----------------
    rows = []; sup1 = rng.integers(0, n_sup, n_skus); pack1 = np.zeros(n_skus, int); moq1 = np.zeros(n_skus, int)
    exp_end = T - 32; ord_end = np.full(n_skus, BIG); next_start = day(T)   # day after last history day
    for i in range(n_skus):
        packs = CATS[cn[ci[i]]][2]; p = int(rng.choice(packs)); m = p * int(rng.choice([1, 2, 3, 4, 6]))
        c = round(float(sku.list_price[i]) * float(rng.uniform(.5, .7)), 2); r = rng.random(); pack1[i], moq1[i] = p, m
        end = None; st = "ACTIVE"
        if r < .02: end, st, ord_end[i] = day(exp_end), "EXPIRED", exp_end      # expired contract
        elif r < .10: end = day(T - 1)                                          # terms change on next_start
        rows.append((sup_ids[sup1[i]], sku_ids[i], p, m, c, "2024-01-01", end, st, 1))
        if .02 <= r < .10: rows.append((sup_ids[sup1[i]], sku_ids[i], p * 2, m * 2, round(c * 1.04, 2), next_start, None, "ACTIVE", 1))
        if r >= .02 and rng.random() < .25:                                      # secondary supplier
            s2 = (sup1[i] + 1 + int(rng.integers(0, n_sup - 1))) % n_sup; p2 = int(rng.choice(packs))
            rows.append((sup_ids[s2], sku_ids[i], p2, p2 * int(rng.choice([1, 2, 4])), round(c * 1.05, 2), "2024-01-01", None, "ACTIVE", 0))
    ssku = pd.DataFrame(rows, columns=["supplier_id", "sku_id", "pack_size", "moq_units", "unit_cost", "effective_from", "effective_to", "status", "is_primary"])
    ssku.insert(0, "supplier_sku_id", [f"SSK-{i:06d}" for i in range(1, len(ssku) + 1)])
    ord_end = np.minimum(ord_end, disc_idx)
    # ---------------- SKU/store matrix ----------------
    mask = rng.random((n_stores, n_skus)) < assortment
    mask[rng.integers(0, n_stores, n_skus), np.arange(n_skus)] = True
    si, ki = np.nonzero(mask); P = len(si)
    lam_pair = base[ki] * store_eff[si] * rng.lognormal(0, .25, P)
    live_from = np.maximum(open_idx[si], launch_idx[ki]); live = t[None, :] >= live_from[:, None]
    # ---------------- True demand: base x season x trend x promo x store x weekday x holiday ----------------
    doy = dates.dayofyear.values; dow = dates.dayofweek.values
    peak = np.array([CATS[c][3] for c in cn])[ci]; amp = np.where(prof == "seasonal", .5, .08)
    season = 1 + amp[:, None] * np.cos(2 * np.pi * (doy[None, :] - peak[:, None]) / 365)
    slope = np.where(prof == "trending", rng.uniform(-.4, .8, n_skus), 0.)
    trend = np.clip(1 + slope[:, None] * t[None, :] / T, .2, None)
    promo_s = np.zeros((n_skus, T), bool)
    for i, nw in enumerate(rng.integers(0, 4, n_skus)):
        for _ in range(nw): s = int(rng.integers(0, T - 14)); promo_s[i, s:s + int(rng.integers(7, 15))] = True
    hol = np.where(doy >= 329, 1.25, 1.0)                                       # late Nov-Dec holiday surge
    lam = lam_pair[:, None] * (season * trend * np.where(promo_s, PROMO_UPLIFT, 1.0))[ki] * (DOW_F[dow] * hol)[None, :]
    demand = rng.poisson(lam).astype(np.int32)
    demand = np.where(rng.random((P, T)) < .0005, demand * 4 + 2, demand).astype(np.int32)   # sudden spikes
    demand[~live] = 0; demand[t[None, :] >= disc_idx[ki][:, None]] = 0
    promo = promo_s[ki] & live
    # ---------------- Policy parameters + inventory simulation ----------------
    moq_p, pack_p = moq1[ki], pack1[ki]
    maxstock = np.maximum(np.rint(lam_pair * rng.uniform(25, 60, P)), np.ceil(1.6 * moq_p)).astype(int)
    tight = rng.random(P) < .03; maxstock = np.where(tight, np.maximum(1, (.8 * moq_p).astype(int)), maxstock)  # natural MOQ>capacity cases
    svc = np.array([CATS[cn[c]][4] for c in ci])[ki]; z_p = np.array([NormalDist().inv_cdf(s) for s in svc])
    sp = sup1[ki]; Lm, Lsd, dp = lt_mean[sp], lt_sd[sp], delay_p[sp]; can = ord_end[ki]
    init = np.minimum(np.rint(lam_pair * rng.uniform(10, 30, P)).astype(int), maxstock)
    on_hand = np.zeros(P, int); on_ord = np.zeros(P, int); rate = lam_pair.copy(); arr = np.zeros((P, T + 60), np.int32)
    opening, received, sold, closing, onord = (np.zeros((P, T), np.int32) for _ in range(5)); stock = np.zeros((P, T), bool); log = []
    for d in range(T):
        on_hand = np.where(live_from == d, init, on_hand); lv = live[:, d]
        opening[:, d] = np.where(lv, on_hand, 0)
        rec = np.where(lv, arr[:, d], 0); avail = on_hand + rec; dm = demand[:, d]; s = np.minimum(dm, avail)
        stock[:, d] = lv & ((avail == 0) | (dm > avail))                         # unavailability recorded separately from zero demand
        on_hand = avail - s; on_ord = on_ord - rec; rate = np.where(lv, rate + .05 * (s - rate), rate)  # operator sees censored sales
        ip = on_hand + on_ord; L = Lm + 1; ss = z_p * np.sqrt(np.maximum(rate, .05) * 1.5 * L); rop = rate * L + ss
        q = np.ceil(np.maximum(rop + rate * 7 - ip, moq_p) / pack_p) * pack_p; room = maxstock - ip
        q = np.where(q > room, np.floor(np.maximum(room, 0) / pack_p) * pack_p, q)
        q = np.where(lv & (ip <= rop) & (d < can) & (q >= moq_p), q, 0).astype(int); idx = np.nonzero(q)[0]
        if idx.size:
            lt = np.maximum(1, np.rint(rng.normal(Lm[idx], Lsd[idx]))).astype(int) + (rng.random(idx.size) < dp[idx]) * (1 + rng.poisson(2, idx.size))
            lt = np.minimum(lt, 55); arr[idx, d + lt] += q[idx]; on_ord[idx] += q[idx]; log.append((np.full(idx.size, d), idx, q[idx], lt))
        sold[:, d] = s; received[:, d] = rec; closing[:, d] = np.where(lv, on_hand, 0); onord[:, d] = np.where(lv, on_ord, 0)
    od, op, oq, ol = (np.concatenate(x) for x in zip(*log)) if log else (np.array([], int),) * 4
    keep = od + ol < T; od, op, oq, ol = od[keep], op[keep], oq[keep], ol[keep]
    ordr = np.lexsort((op, od)); od, op, oq, ol = od[ordr], op[ordr], oq[ordr], ol[ordr]
    lead = pd.DataFrame(dict(observation_id=[f"LTO-{i:06d}" for i in range(1, len(od) + 1)], supplier_id=np.array(sup_ids)[sp[op]],
        sku_id=np.array(sku_ids)[ki[op]], store_id=np.array(store_ids)[si[op]], order_date=day(od), received_date=day(od + ol),
        lead_time_days=ol, ordered_qty=oq, received_qty=oq))
    z_all = [NormalDist().inv_cdf(s) for s in svc]
    pol = pd.DataFrame(dict(policy_id=[f"POL-{i:06d}" for i in range(1, P + 1)], store_id=np.array(store_ids)[si], sku_id=np.array(sku_ids)[ki],
        service_level=svc, z_score=np.round(z_all, 6), review_days=7, max_stock_units=maxstock, effective_from=START_DATE, effective_to=None, status="ACTIVE"))
    store["capacity_units"] = np.bincount(si, weights=maxstock, minlength=n_stores).astype(int)       # derived from source rows
    pairs = pd.DataFrame(dict(store_id=np.array(store_ids)[si], sku_id=np.array(sku_ids)[ki], category=np.array([cn[c] for c in ci])[ki], profile=prof[ki]))
    tables = dict(sku=sku, store=store, supplier=supplier, supplier_sku=ssku, lead_time_observation=lead, reorder_policy=pol)
    tables = {k: v[schema.columns(k)] for k, v in tables.items()}
    params = dict(sku_demand_profile=dict(zip(sku_ids, prof.tolist())), promo_uplift=PROMO_UPLIFT,
        supplier_lead_time={s: dict(mean=int(m), sd=float(sd), delay_prob=round(float(p), 4)) for s, m, sd, p in zip(sup_ids, lt_mean, lt_sd, delay_p)})
    iso = np.array(_iso(dates), dtype=object); pk = (pairs.store_id + "-" + pairs.sku_id).values.astype(object)
    return Sim(tables, pairs, dates, iso, pk, demand, sold, opening, received, closing, onord, stock, promo, live, params)

def daily_frames(sim: Sim, p0: int, p1: int, flag=None):
    """SalesHistory + InventorySnapshot rows for pairs [p0,p1) (live days only), derived from the simulation arrays."""
    flag = sim.stock if flag is None else flag
    pi, ti = np.nonzero(sim.live[p0:p1]); gp = pi + p0
    key, ds = sim.pair_key[gp], sim.iso[ti]; st = sim.pairs.store_id.values[gp]; sk = sim.pairs.sku_id.values[gp]
    sales = pd.DataFrame(dict(sale_id=("SALE-" + key + "-" + ds), store_id=st, sku_id=sk, sale_date=ds, units_sold=sim.sold[gp, ti],
        promo_flag=sim.promo[gp, ti].astype(int), stockout_flag=flag[gp, ti].astype(int)))
    inv = pd.DataFrame(dict(snapshot_id=("INV-" + key + "-" + ds), store_id=st, sku_id=sk, snapshot_date=ds, opening_on_hand=sim.opening[gp, ti],
        received_units=sim.received[gp, ti], units_sold=sim.sold[gp, ti], closing_on_hand=sim.closing[gp, ti], on_order_units=sim.on_order[gp, ti]))
    return sales, inv

def block_size(sim, rows=400_000):
    return max(1, int(rows / max(1, sim.live.shape[1])))
