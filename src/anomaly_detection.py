"""Rule-based detectors for the 5 required exception paths + precision/recall vs ground_truth.csv.
Detectors only look at input tables (never ground truth)."""
import pandas as pd
ISSUES = ["STOCKOUT_MISTAKEN_AS_ZERO_DEMAND", "PACK_SIZE_OR_MOQ_VIOLATION", "DISCONTINUED_SKU_RECOMMENDED", "NEGATIVE_LEAD_TIME", "FORECAST_USES_FUTURE_SALES"]

def detect_stockout_as_zero(sales, inventory):
    """Find zero sales with no available stock and a cleared stockout flag."""
    daily = sales.merge(
        inventory[["store_id", "sku_id", "snapshot_date", "opening_on_hand", "received_units", "units_sold"]],
        left_on=["store_id", "sku_id", "sale_date"],
        right_on=["store_id", "sku_id", "snapshot_date"],
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=("_sales", "_inventory"),
    )
    if not daily["_merge"].eq("both").all():
        raise ValueError("sales and inventory inputs must contain the same store/SKU/date rows")
    if not daily["units_sold_sales"].eq(daily["units_sold_inventory"]).all():
        raise ValueError("sales and inventory units_sold values must agree")
    bad = (
        daily["units_sold_sales"].eq(0)
        & daily["opening_on_hand"].add(daily["received_units"]).eq(0)
        & daily["stockout_flag"].eq(0)
    )
    return daily.loc[bad, "sale_id"]

def detect_pack_violation(recs):
    b = recs[recs.recommended_qty > 0]
    bad = (b.recommended_qty % b.supplier_pack_size.astype(float) != 0) | (b.recommended_qty < b.supplier_moq.astype(float))
    return b.recommendation_id[bad]

def detect_discontinued_recommended(recs, skus):
    d = set(skus[skus.lifecycle_status == "DISCONTINUED"].sku_id); return recs.recommendation_id[(recs.recommended_qty > 0) & recs.sku_id.isin(d)]

def detect_negative_lead_time(lead): return lead.observation_id[(lead.lead_time_days <= 0) | (lead.received_date < lead.order_date)]

def detect_forecast_leakage(fc): return fc.forecast_id[fc.data_cutoff_date >= fc.forecast_start_date]

def detect_all(tables, daily_batches=()):
    stockout_ids = [detect_stockout_as_zero(sales, inventory) for sales, inventory in daily_batches]
    stockout = pd.concat(stockout_ids, ignore_index=True) if stockout_ids else pd.Series([], dtype=object)
    det = {"STOCKOUT_MISTAKEN_AS_ZERO_DEMAND": stockout,
           "PACK_SIZE_OR_MOQ_VIOLATION": detect_pack_violation(tables["purchase_recommendation"]),
           "DISCONTINUED_SKU_RECOMMENDED": detect_discontinued_recommended(tables["purchase_recommendation"], tables["sku"]),
           "NEGATIVE_LEAD_TIME": detect_negative_lead_time(tables["lead_time_observation"]),
           "FORECAST_USES_FUTURE_SALES": detect_forecast_leakage(tables["forecast"])}
    return pd.concat([pd.DataFrame(dict(record_id=v.values, issue_type=k)) for k, v in det.items()], ignore_index=True)

def evaluate_detection(detected, truth):
    rows = []
    for k in ISSUES:
        d = set(detected[detected.issue_type == k].record_id); g = set(truth[truth.issue_type == k].record_id)
        tp, fp, fn = len(d & g), len(d - g), len(g - d)
        rows.append(dict(issue_type=k, injected=len(g), detected=len(d), TP=tp, FP=fp, FN=fn,
                         precision=tp / (tp + fp) if tp + fp else float("nan"), recall=tp / (tp + fn) if tp + fn else float("nan")))
    r = pd.DataFrame(rows); TP, FP, FN = r.TP.sum(), r.FP.sum(), r.FN.sum()
    return r, dict(precision=float(TP / max(TP + FP, 1)), recall=float(TP / max(TP + FN, 1)), TP=int(TP), FP=int(FP), FN=int(FN))
