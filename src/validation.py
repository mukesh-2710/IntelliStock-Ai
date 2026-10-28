"""Step 8: schema-driven validation (PK, FK, enums, required, ID formats, dates, reconciliation, lifecycle, duplicates)."""
import re
import numpy as np, pandas as pd
from src import schema
from src.generator import daily_frames, block_size

def _r(report, check, table, bad, detail=""):
    report.append(dict(check=check, table=table, status="PASS" if bad == 0 else "FAIL", violations=int(bad), detail=detail))

def validate_small(tables):
    rep = []; E = schema.enums(); pk = schema.pks()
    for t, df in tables.items():
        if list(df.columns) != schema.columns(t): _r(rep, "columns_match_dictionary", t, 1, str(list(df.columns))); continue
        req = [r["field"] for r in schema.SPEC[t] if r["required"] == "Y"]
        _r(rep, "required_not_null", t, int(df[req].isna().sum().sum()))
        _r(rep, "pk_unique", t, int(df[pk[t]].duplicated().sum()))
        for c, pat in schema.ID_PATTERNS.items():
            if c in df.columns: _r(rep, f"id_format:{c}", t, int((~df[c].dropna().astype(str).str.match(pat)).sum()))
        for (et, f), vals in E.items():
            if et == t: _r(rep, f"enum:{f}", t, int((~df[f].dropna().astype(str).isin(vals)).sum()))
    for t, f, pt, pf in schema.fks():
        if t in tables and pt in tables:
            _r(rep, f"fk:{f}->{pt}.{pf}", t, int((~tables[t][f].dropna().isin(set(tables[pt][pf]))).sum()))
    T = tables
    lt = T["lead_time_observation"]; _r(rep, "date_order:received>=order", "lead_time_observation", int((lt.received_date < lt.order_date).sum()))
    _r(rep, "lead_time_positive_and_consistent", "lead_time_observation", int(((lt.lead_time_days < 1) | (lt.lead_time_days != (pd.to_datetime(lt.received_date) - pd.to_datetime(lt.order_date)).dt.days)).sum()))
    s = T["sku"]; _r(rep, "lifecycle:discontinue_date_iff_DISCONTINUED", "sku", int((s.discontinue_date.notna() != (s.lifecycle_status == "DISCONTINUED")).sum()))
    _r(rep, "date_order:launch<=discontinue", "sku", int((s.discontinue_date.notna() & (s.discontinue_date < s.launch_date)).sum()))
    ss = T["supplier_sku"]; _r(rep, "date_order:effective_from<=to", "supplier_sku", int((ss.effective_to.notna() & (ss.effective_to < ss.effective_from)).sum()))
    ov = 0
    for _, g in ss.sort_values("effective_from").groupby(["supplier_id", "sku_id"]):
        e = g.effective_to.fillna("9999-12-31").values; f = g.effective_from.values; ov += int((f[1:] <= e[:-1]).sum())
    _r(rep, "no_overlapping_effective_dates", "supplier_sku", ov)
    _r(rep, "pack_moq_positive", "supplier_sku", int(((ss.pack_size < 1) | (ss.moq_units < 1)).sum()))
    p = T["reorder_policy"]; _r(rep, "single_active_policy_per_pair", "reorder_policy", int(p[p.status == "ACTIVE"].duplicated(["store_id", "sku_id"]).sum()))
    cap = p.groupby("store_id").max_stock_units.sum(); st = T["store"].set_index("store_id").capacity_units
    _r(rep, "derived:store_capacity=sum(policy)", "store", int((cap.reindex(st.index).fillna(0) != st).sum()))
    if "forecast" in T:
        f = T["forecast"]; _r(rep, "no_future_sales_in_forecast", "forecast", int((f.data_cutoff_date >= f.forecast_start_date).sum()))
        _r(rep, "forecast_arithmetic", "forecast", int(((f.total_forecast - f.daily_forecast * (pd.to_datetime(f.forecast_end_date) - pd.to_datetime(f.forecast_start_date)).dt.days.add(1)).abs() > .01).sum()))
        _r(rep, "forecast_interval_order", "forecast", int(((f.lower_90 > f.total_forecast + 1e-9) | (f.upper_90 < f.total_forecast - 1e-9)).sum()))
        _r(rep, "forecast_nonnegative", "forecast", int((f.daily_forecast < 0).sum()))
        _r(rep, "forecast_unique_store_sku_month_version", "forecast", int(f.duplicated(["store_id", "sku_id", "forecast_month", "forecast_version"]).sum()))
        _r(rep, "forecast_pair_in_sku_store_matrix", "forecast", int((~(f.store_id + f.sku_id).isin(set(p.store_id + p.sku_id))).sum()))
    if "purchase_recommendation" in T:
        r = T["purchase_recommendation"]; buy = r[r.recommended_qty > 0]
        _r(rep, "qty_multiple_of_pack_and_>=MOQ", "purchase_recommendation", int(((buy.recommended_qty % buy.supplier_pack_size.astype(float) != 0) | (buy.recommended_qty < buy.supplier_moq.astype(float))).sum()))
        _r(rep, "qty_within_capacity", "purchase_recommendation", int((buy.inventory_position + buy.recommended_qty > buy.max_stock_units).sum()))
        _r(rep, "no_discontinued_sku_recommended", "purchase_recommendation", int(buy.sku_id.isin(set(s[s.lifecycle_status == "DISCONTINUED"].sku_id)).sum()))
        _r(rep, "cost_reconciliation", "purchase_recommendation", int(((r.total_cost - r.recommended_qty * r.unit_cost.fillna(0)).abs() > .011).sum()))
        _r(rep, "inventory_position=on_hand+on_order", "purchase_recommendation", int((r.inventory_position != r.on_hand_units + r.on_order_units).sum()))
        # tolerance is relative: stored inputs are rounded to 3-4 decimals
        _r(rep, "reorder_point=mu*L+SS", "purchase_recommendation", int(((r.reorder_point_units - (r.daily_demand_forecast * r.lead_time_mean_days + r.safety_stock_units)).abs() > .01 + 1e-3 * r.reorder_point_units).sum()))
        _r(rep, "forecast_lineage", "purchase_recommendation", int((~r.forecast_id.isin(set(T["forecast"].forecast_id))).sum()) if "forecast" in T else 0)
    if "recommendation_event" in T and "purchase_recommendation" in T:
        from src.replenishment import TRANSITIONS
        ev = T["recommendation_event"]; bad = sum(1 for a, b in zip(ev.previous_status, ev.new_status) if pd.notna(a) and b not in TRANSITIONS.get(a, set()))
        _r(rep, "lifecycle_transitions_valid", "recommendation_event", bad)
        _r(rep, "final_event_status=recommendation_status", "recommendation_event", int((ev.groupby("recommendation_id").new_status.last().reindex(T["purchase_recommendation"].set_index("recommendation_id").index) != T["purchase_recommendation"].set_index("recommendation_id").status).sum()))
        order_dates = T["purchase_recommendation"].set_index("recommendation_id").order_date
        event_orders = ev.merge(order_dates.rename("order_date"), left_on="recommendation_id", right_index=True, how="left")
        event_ts = pd.to_datetime(event_orders.event_ts, utc=True, errors="coerce")
        event_date = event_ts.dt.strftime("%Y-%m-%d")
        before_order = event_ts.isna() | (event_date < event_orders.order_date)
        _r(rep, "event_not_before_order_date", "recommendation_event", int(before_order.sum()))
        out_of_order = sum(not group.event_ts.is_monotonic_increasing for _, group in ev.groupby("recommendation_id", sort=False))
        _r(rep, "events_chronological_per_recommendation", "recommendation_event", out_of_order)
    return rep

def validate_daily(sim, tables, flag=None):
    """Chunked validation of SalesHistory / InventorySnapshot (3.65M+ rows at full scale)."""
    rep = []; bs = block_size(sim); sk = set(tables["sku"].sku_id); st = set(tables["store"].store_id)
    disc = tables["sku"].set_index("sku_id").discontinue_date.dropna().to_dict(); launch = tables["sku"].set_index("sku_id").launch_date.to_dict()
    opend = tables["store"].set_index("store_id").open_date.to_dict(); acc = dict.fromkeys(["rows", "dup_sale", "dup_inv", "fk", "recon", "neg", "oversold", "late", "early", "enum", "id", "mismatch"], 0)
    for p0 in range(0, len(sim.pairs), bs):
        s, i = daily_frames(sim, p0, p0 + bs, flag); acc["rows"] += len(s)
        acc["dup_sale"] += int(s.sale_id.duplicated().sum()); acc["dup_inv"] += int(i.snapshot_id.duplicated().sum())
        acc["fk"] += int((~s.sku_id.isin(sk)).sum() + (~s.store_id.isin(st)).sum() + (~i.sku_id.isin(sk)).sum() + (~i.store_id.isin(st)).sum())
        acc["recon"] += int((i.closing_on_hand != i.opening_on_hand + i.received_units - i.units_sold).sum())
        acc["neg"] += int(((i.closing_on_hand < 0) | (s.units_sold < 0) | (i.opening_on_hand < 0)).sum())
        acc["oversold"] += int((s.units_sold > i.opening_on_hand + i.received_units).sum())
        d = s.sku_id.map(disc); acc["late"] += int(((d.notna()) & (s.sale_date > d) & (s.units_sold > 0)).sum())
        acc["early"] += int((s.sale_date < s.sku_id.map(launch)).sum() + (s.sale_date < s.store_id.map(opend)).sum())
        acc["enum"] += int((~s.stockout_flag.isin([0, 1])).sum() + (~s.promo_flag.isin([0, 1])).sum())
        acc["id"] += int((~s.sale_id.str.match(schema.ID_PATTERNS["sale_id"])).sum() + (~i.snapshot_id.str.match(schema.ID_PATTERNS["snapshot_id"])).sum())
        acc["mismatch"] += int((s.units_sold != i.units_sold).sum())
    for k, c, t in [("dup_sale", "pk_unique", "sales_history"), ("dup_inv", "pk_unique", "inventory_snapshot"), ("fk", "fk_store_sku", "sales_history+inventory_snapshot"),
                    ("recon", "closing=opening+received-sold", "inventory_snapshot"), ("neg", "no_negative_inventory_or_sales", "inventory_snapshot"),
                    ("oversold", "sales<=available_stock", "sales_history"), ("late", "no_sales_after_discontinuation", "sales_history"),
                    ("early", "no_sales_before_launch_or_store_open", "sales_history"), ("enum", "enum:flags", "sales_history"),
                    ("id", "id_format", "sales_history+inventory_snapshot"), ("mismatch", "sales_units=inventory_units", "sales_history")]:
        _r(rep, c, t, acc[k])
    rec_inv = int(sim.received.sum()); rec_obs = int(tables["lead_time_observation"].received_qty.sum())
    _r(rep, "inventory_receipts=lead_time_observation_qty", "inventory_snapshot", int(rec_inv != rec_obs), f"{rec_inv} vs {rec_obs}")
    pk = sim.pairs.store_id + sim.pairs.sku_id; _r(rep, "sku_store_matrix_unique", "reorder_policy", int(pk.duplicated().sum()))
    return rep, acc["rows"]

def summarize(rep):
    return dict(total_checks=len(rep), passed=sum(r["status"] == "PASS" for r in rep), failed=[r for r in rep if r["status"] == "FAIL"], checks=rep)
