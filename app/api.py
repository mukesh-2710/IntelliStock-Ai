"""FastAPI service.  Run: uvicorn app.api:app --reload   (needs `python -m src.pipeline` output in ./output)"""
import json, os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from fastapi import FastAPI, HTTPException
from src.replenishment import safety_stock, order_qty

OUT = os.environ.get("INTELLISTOCK_OUT", "output"); app = FastAPI(title="IntelliStock AI")
def _csv(n): 
    p = f"{OUT}/{n}.csv"
    if not os.path.exists(p): raise HTTPException(503, f"{p} missing - run `python -m src.pipeline --out {OUT}`")
    return pd.read_csv(p)

@app.get("/health")
def health(): return {"status": "ok", "output_dir": OUT}

@app.get("/recommendations")
def recommendations(store_id: str | None = None, sku_id: str | None = None, decision: str | None = None, limit: int = 50):
    r = _csv("purchase_recommendation")
    for c, v in (("store_id", store_id), ("sku_id", sku_id), ("decision", decision)):
        if v: r = r[r[c] == v]
    return r.head(min(limit, 500)).where(r.notna(), None).to_dict("records")

@app.get("/exceptions")
def exceptions(): return json.load(open(f"{OUT}/reports/validation_summary.json"))["detection"]

@app.get("/whatif")
def whatif(daily_demand: float, lead_time_days: float, demand_std: float = 0, lead_time_std: float = 0, z: float = 1.645,
           inventory_position: float = 0, pack: int = 1, moq: int = 1, room: float = 1e9, review_days: int = 7):
    ss = float(safety_stock(z, daily_demand, demand_std, lead_time_days, lead_time_std)); rop = daily_demand * lead_time_days + ss
    need = max(daily_demand * (lead_time_days + review_days) + ss - inventory_position, 0) if inventory_position <= rop else 0
    q, st = order_qty(need, moq, pack, room)
    return dict(safety_stock=ss, reorder_point=rop, reorder=inventory_position <= rop, required_qty=need, recommended_qty=q, status=st)
