"""Step 5/7: inject LABELLED edge cases into a COPY of the validated baseline; return ground_truth rows.
Only the targeted rows change; every change is recorded with original and injected value."""
import math
import numpy as np, pandas as pd

def inject(sim, tables, n, seed):
    rng = np.random.default_rng(seed + 1); T = {k: v.copy() for k, v in tables.items()}; flag = sim.stock.copy(); gt = []
    def add(entity, rid, issue, sev, rule, o, i): gt.append(dict(entity=entity, record_id=rid, issue_type=issue, severity=sev, rule_violated=rule, original_value=o, injected_value=i))
    # EC-001 stockout hidden -> looks like zero demand (flag cleared on censored zero-sale days)
    cand = np.argwhere(sim.stock & (sim.sold == 0) & (sim.demand > 0)); 
    if len(cand) < n: cand = np.argwhere(sim.stock & (sim.sold == 0))
    for p, t in cand[np.sort(rng.choice(len(cand), min(n, len(cand)), replace=False))]:
        flag[p, t] = False; add("sales_history", f"SALE-{sim.pair_key[p]}-{sim.iso[t]}", "STOCKOUT_MISTAKEN_AS_ZERO_DEMAND", "HIGH", "stockout_flag must be 1 when no stock available", "stockout_flag=1", f"stockout_flag=0; true_demand={int(sim.demand[p, t])}")
    r = T["purchase_recommendation"]
    # EC-002 quantity ignores pack size
    pool = r.index[(r.recommended_qty > 0) & (r.supplier_pack_size.astype(float) >= 2)].values
    for i in np.sort(rng.choice(pool, min(n, len(pool)), replace=False)) if len(pool) else []:
        o = int(r.at[i, "recommended_qty"]); r.at[i, "recommended_qty"] = o + 1; r.at[i, "total_cost"] = round((o + 1) * float(r.at[i, "unit_cost"]), 2)
        add("purchase_recommendation", r.at[i, "recommendation_id"], "PACK_SIZE_OR_MOQ_VIOLATION", "HIGH", "qty must be multiple of pack_size and >= MOQ", f"qty={o}", f"qty={o + 1}; pack={r.at[i, 'supplier_pack_size']}")
    # EC-003 discontinued SKU recommended
    pool = r.index[(r.decision == "BLOCKED_DISCONTINUED") & r.supplier_pack_size.notna()].values
    for i in np.sort(rng.choice(pool, min(n, len(pool)), replace=False)) if len(pool) else []:
        q = int(math.ceil(r.at[i, "supplier_moq"] / r.at[i, "supplier_pack_size"]) * r.at[i, "supplier_pack_size"])
        r.loc[i, ["decision", "status", "recommended_qty"]] = ["REORDER", "VALIDATED", q]; r.at[i, "total_cost"] = round(q * float(r.at[i, "unit_cost"]), 2)
        add("purchase_recommendation", r.at[i, "recommendation_id"], "DISCONTINUED_SKU_RECOMMENDED", "CRITICAL", "DISCONTINUED SKU must never be recommended", "decision=BLOCKED_DISCONTINUED,qty=0", f"decision=REORDER,qty={q}")
    # EC-004 negative lead time
    lt = T["lead_time_observation"]; ix = np.sort(rng.choice(len(lt), min(n, len(lt)), replace=False))
    for i in ix:
        k = int(rng.integers(1, 6)); o = lt.at[i, "lead_time_days"]; od = pd.Timestamp(lt.at[i, "order_date"])
        lt.at[i, "received_date"] = (od - pd.Timedelta(days=k)).strftime("%Y-%m-%d"); lt.at[i, "lead_time_days"] = -k
        add("lead_time_observation", lt.at[i, "observation_id"], "NEGATIVE_LEAD_TIME", "MEDIUM", "received_date >= order_date; lead_time_days >= 1", f"lead_time_days={o}", f"lead_time_days={-k}")
    # EC-005 forecast trained on future sales (cutoff after forecast start)
    f = T["forecast"]; ix = np.sort(rng.choice(len(f), min(n, len(f)), replace=False))
    for i in ix:
        o = f.at[i, "data_cutoff_date"]; f.at[i, "data_cutoff_date"] = (pd.Timestamp(f.at[i, "forecast_start_date"]) + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
        add("forecast", f.at[i, "forecast_id"], "FORECAST_USES_FUTURE_SALES", "CRITICAL", "data_cutoff_date < forecast_start_date", f"cutoff={o}", f"cutoff={f.at[i, 'data_cutoff_date']}")
    truth = pd.DataFrame(gt); truth.insert(0, "issue_id", [f"GT-{i:06d}" for i in range(1, len(truth) + 1)])
    return T, flag, truth
