"""Constraint-aware replenishment: ROP / safety stock / order-up-to, then MOQ -> pack size -> capacity.
Returns explicit decisions (incl. blocked/infeasible) with a human-readable calculation trace."""
import math
import numpy as np, pandas as pd
from src import schema

TRANSITIONS = {"GENERATED": {"VALIDATED", "BLOCKED", "NO_ACTION"}, "VALIDATED": {"PENDING_APPROVAL"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED"}, "APPROVED": {"ORDER_CREATED"},
    "ORDER_CREATED": {"PARTIALLY_RECEIVED", "COMPLETED"}, "PARTIALLY_RECEIVED": {"PARTIALLY_RECEIVED", "COMPLETED"},
    "BLOCKED": set(), "NO_ACTION": set(), "REJECTED": set(), "COMPLETED": set()}

def transition(rec_id, prev, new, actor, reason, ts, events=()):
    """Validate a lifecycle transition and return an immutable event dict (rejects invalid + duplicate approvals)."""
    if new not in TRANSITIONS.get(prev, set()): raise ValueError(f"invalid transition {prev}->{new}")
    if new == "APPROVED" and any(e["recommendation_id"] == rec_id and e["new_status"] == "APPROVED" for e in events):
        raise ValueError("duplicate approval")
    return dict(event_id=f"EVT-2026-{len(events) + 1:06d}", recommendation_id=rec_id, previous_status=prev, new_status=new, actor=actor, reason=reason, event_ts=ts)

def safety_stock(z, mu, sd_d, L, sd_L): return z * np.sqrt(L * sd_d ** 2 + mu ** 2 * sd_L ** 2)

def order_qty(need, moq, pack, room):
    """Q = pack * ceil(max(need, MOQ)/pack); if it exceeds capacity room, round room DOWN to a pack multiple;
    if that is below MOQ -> infeasible (qty 0, never silently violate a hard constraint)."""
    need, moq, pack, room = (np.asarray(v, float) for v in (need, moq, pack, room))
    full = np.ceil(np.maximum(need, moq) / pack) * pack; capped = np.floor(np.maximum(room, 0) / pack) * pack
    ok = full <= room; cap_ok = ~ok & (capped >= moq) & (capped > 0)
    qty = np.where(need <= 0, 0, np.where(ok, full, np.where(cap_ok, capped, 0))).astype(int)
    st = np.where(need <= 0, "NONE", np.where(ok, "OK", np.where(cap_ok, "CAPPED", "INFEASIBLE")))
    return (int(qty) if qty.ndim == 0 else qty), (str(st) if st.ndim == 0 else st)

def make_events(recs):
    if recs.recommendation_id.duplicated().any():
        raise ValueError("recommendation IDs must be unique when creating events")
    rows = []; n = 0
    for rid, st, order_date in zip(recs.recommendation_id, recs.status, recs.order_date):
        order_ts = pd.Timestamp(order_date)
        if pd.isna(order_ts):
            raise ValueError(f"invalid order date for recommendation {rid}")
        order_ts = order_ts.normalize().tz_localize("UTC")
        events = ((None, "GENERATED", "recommendation computed from forecast + inventory + policy"),
                  ("GENERATED", st, "constraints validated" if st == "VALIDATED" else "no purchase action: " + st))
        for event_offset, (prev, new, reason) in enumerate(events):
            n += 1
            event_ts = order_ts + pd.Timedelta(seconds=event_offset)
            rows.append(dict(event_id=f"EVT-2026-{n:06d}", recommendation_id=rid, previous_status=prev, new_status=new, actor="system", reason=reason, event_ts=event_ts.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return pd.DataFrame(rows, columns=schema.columns("recommendation_event"))

def recommend(tables, forecast, state, as_of):
    od = (pd.Timestamp(as_of) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    sku, store, sup, ss, lead, pol = (tables[k] for k in ("sku", "store", "supplier", "supplier_sku", "lead_time_observation", "reorder_policy"))
    df = (forecast.merge(state, on=["store_id", "sku_id"], how="left")
          .merge(pol[["store_id", "sku_id", "policy_id", "z_score", "review_days", "max_stock_units"]], on=["store_id", "sku_id"])
          .merge(sku[["sku_id", "lifecycle_status"]], on="sku_id").merge(store[["store_id", "status"]].rename(columns={"status": "store_status"}), on="store_id"))
    s2 = ss.merge(sup[["supplier_id", "status"]].rename(columns={"status": "sup_status"}), on="supplier_id")
    dv = s2[(s2.effective_from <= od) & (s2.effective_to.isna() | (s2.effective_to >= od))]          # terms effective at ORDER date
    el = dv[(dv.status == "ACTIVE") & (dv.sup_status == "ACTIVE")].sort_values(["sku_id", "is_primary", "unit_cost"], ascending=[True, False, True]).drop_duplicates("sku_id")
    susp = set(dv[(dv.status == "ACTIVE") & (dv.sup_status != "ACTIVE")].sku_id)
    df = df.merge(el[["sku_id", "supplier_id", "pack_size", "moq_units", "unit_cost"]], on="sku_id", how="left")
    v = lead[(lead.lead_time_days > 0) & (lead.received_date >= lead.order_date)]                       # reject invalid lead times
    bysk = v.groupby(["supplier_id", "sku_id"]).lead_time_days.agg(["mean", "std", "count"]).reset_index().rename(columns={"mean": "k_m", "std": "k_s", "count": "k_n"})
    bys = v.groupby("supplier_id").lead_time_days.agg(["mean", "std"]).reset_index().rename(columns={"mean": "s_m", "std": "s_s"})
    df = df.merge(bysk, on=["supplier_id", "sku_id"], how="left").merge(bys, on="supplier_id", how="left")
    use = df.k_n.fillna(0) >= 5
    df["L"] = np.where(use, df.k_m, df.s_m).astype(float); df["sdL"] = np.where(use, df.k_s, df.s_s).astype(float)
    df["L"] = df.L.fillna(7.0); df["sdL"] = df.sdL.fillna(2.0)                                           # documented fallback
    for c in ("on_hand", "on_order"): df[c] = df[c].fillna(0).astype(int)
    mu, sd, z, L, R = df.daily_forecast.values, df.demand_std_daily.values, df.z_score.values, df.L.values, df.review_days.values
    ss_ = safety_stock(z, mu, sd, L, df.sdL.values); rop = mu * L + ss_; ip = (df.on_hand + df.on_order).values; S = mu * (L + R) + ss_
    below = ip <= rop                                                                                   # boundary rule: IP == ROP -> reorder
    need = np.where(below, np.maximum(S - ip, 0), 0.0); room = df.max_stock_units.values - ip
    has = df.supplier_id.notna().values; pack = df.pack_size.fillna(1).values; moq = df.moq_units.fillna(1).values
    qty, qst = order_qty(need, moq, pack, room); qty = np.where(has, qty, 0)
    dec = np.select([df.lifecycle_status.eq("DISCONTINUED"), df.store_status.ne("ACTIVE"), ~has & df.sku_id.isin(susp), ~has, mu <= 0.01, ~below, qst == "INFEASIBLE", qst == "CAPPED"],
                    ["BLOCKED_DISCONTINUED", "BLOCKED_STORE_CLOSED", "BLOCKED_SUPPLIER_SUSPENDED", "BLOCKED_NO_SUPPLIER", "NO_ORDER", "NO_ORDER", "INFEASIBLE_CAPACITY", "REORDER_CAPPED_BY_CAPACITY"], "REORDER")
    qty = np.where(np.isin(dec, ["REORDER", "REORDER_CAPPED_BY_CAPACITY"]), qty, 0)
    status = np.where(np.isin(dec, ["REORDER", "REORDER_CAPPED_BY_CAPACITY"]), "VALIDATED", np.where(dec == "NO_ORDER", "NO_ACTION", "BLOCKED"))
    risk = np.where(np.isin(dec, ["NO_ORDER"]) & (df.on_hand.values >= mu * L), "LOW", np.where(df.on_hand.values < mu * L, "HIGH", np.where(below, "MEDIUM", "LOW")))
    arr = [(pd.Timestamp(od) + pd.Timedelta(days=int(math.ceil(l)))).strftime("%Y-%m-%d") if q > 0 else None for q, l in zip(qty, L)]
    def why(i):
        b = (f"IP={ip[i]} (on_hand {df.on_hand.values[i]} + on_order {df.on_order.values[i]}); ROP={rop[i]:.1f} = {mu[i]:.2f}/day x {L[i]:.1f}d + SS {ss_[i]:.1f} (z={z[i]:.2f}, sd_d={sd[i]:.2f}, sd_L={df.sdL.values[i]:.2f}). ")
        d = dec[i]
        if d.startswith("BLOCKED"): return b + "Blocked: " + d.replace("BLOCKED_", "").lower().replace("_", " ") + "; no order created."
        if d == "NO_ORDER": return b + ("Forecast demand ~0; no order." if mu[i] <= .01 else "IP above reorder point; no order.")
        if d == "INFEASIBLE_CAPACITY": return b + f"Need {need[i]:.1f} (up-to {S[i]:.1f}); MOQ {moq[i]:.0f}/pack {pack[i]:.0f} but capacity room {room[i]:.0f} cannot fit a valid order -> INFEASIBLE, qty 0."
        return b + f"IP<=ROP. Order-up-to {S[i]:.1f}, need {need[i]:.1f} -> MOQ {moq[i]:.0f}, pack {pack[i]:.0f} -> {qty[i]} units" + (f" (capped by capacity room {room[i]:.0f})." if d.endswith("CAPACITY") else f"; capacity room {room[i]:.0f} OK.")
    out = pd.DataFrame(dict(recommendation_id=[f"PO-2026-{i:06d}" for i in range(1, len(df) + 1)], forecast_id=df.forecast_id, policy_id=df.policy_id,
        store_id=df.store_id, sku_id=df.sku_id, supplier_id=df.supplier_id, as_of_date=as_of, order_date=od, decision=dec,
        daily_demand_forecast=df.daily_forecast.round(4), demand_std_daily=df.demand_std_daily, lead_time_mean_days=df.L.round(3), lead_time_std_days=df.sdL.round(3),
        safety_stock_units=np.round(ss_, 3), reorder_point_units=np.round(rop, 3), on_hand_units=df.on_hand, on_order_units=df.on_order, inventory_position=ip,
        order_up_to_units=np.round(S, 3), required_qty=np.round(need, 3), supplier_pack_size=df.pack_size.astype("Int64"), supplier_moq=df.moq_units.astype("Int64"),
        max_stock_units=df.max_stock_units, recommended_qty=qty.astype(int), unit_cost=df.unit_cost, total_cost=np.round(qty * df.unit_cost.fillna(0).values, 2),
        expected_arrival_date=arr, stockout_risk=risk, forecast_confidence=df.confidence, status=status))
    out["explanation"] = [why(i) for i in range(len(out))]
    return out[schema.columns("purchase_recommendation")].reset_index(drop=True)
