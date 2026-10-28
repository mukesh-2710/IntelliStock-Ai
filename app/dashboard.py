"""Streamlit dashboard.  Run: streamlit run app/dashboard.py   (reads ./output from `python -m src.pipeline`)"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd, plotly.express as px, streamlit as st
from src.replenishment import safety_stock, order_qty

OUT = st.sidebar.text_input("Output folder", os.environ.get("INTELLISTOCK_OUT", "output"))
@st.cache_data
def load(folder, name): return pd.read_csv(Path(folder) / f"{name}.csv")

output_dir = Path(OUT).expanduser()
required_files = (
    "reports/validation_summary.json",
    "purchase_recommendation.csv",
    "forecast.csv",
    "reports/exceptions_detected.csv",
)
missing = [str(output_dir / name) for name in required_files if not (output_dir / name).is_file()]
if missing:
    st.error("Dashboard data is missing from the selected output folder.")
    st.write("Generate the pipeline output first, or choose an existing output folder in the sidebar.")
    st.code("python -m src.pipeline --scale starter --out output", language="powershell")
    st.caption("Missing files: " + ", ".join(missing))
    st.stop()

with (output_dir / "reports" / "validation_summary.json").open(encoding="utf-8") as summary_file:
    summ = json.load(summary_file)
rec, fc = load(str(output_dir), "purchase_recommendation"), load(str(output_dir), "forecast")
store = st.sidebar.selectbox("Store", ["All"] + sorted(rec.store_id.unique())); sku = st.sidebar.selectbox("SKU", ["All"] + sorted(rec.sku_id.unique()))
flt = lambda d: d[((d.store_id == store) | (store == "All")) & ((d.sku_id == sku) | (sku == "All"))]
t1, t2, t3, t4, t5 = st.tabs(["Overview", "Forecasting", "Replenishment", "Exceptions", "What-if"])
with t1:
    r = flt(rec); c = st.columns(4); c[0].metric("Pairs", len(r)); c[1].metric("Reorders", int(r.decision.str.startswith("REORDER").sum()))
    c[2].metric("Units to buy", int(r.recommended_qty.sum())); c[3].metric("Purchase value", f"{r.total_cost.sum():,.0f}")
    st.plotly_chart(px.pie(r, names="decision", title="Decisions"), use_container_width=True)
    b = summ["baseline_validation"]; st.success(f"Baseline validation: {b['passed']}/{b['total_checks']} checks PASS")
with t2:
    st.dataframe(pd.DataFrame(summ["forecast"]["metrics"]).set_index("model")); st.caption(f"90% interval coverage on temporal holdout: {summ['forecast']['interval_90_coverage_on_holdout']:.1%}")
    f = flt(fc); st.plotly_chart(px.histogram(f, x="model_name", color="confidence", title="Model used / confidence"), use_container_width=True); st.dataframe(f.head(500))
with t3:
    r = flt(rec); st.dataframe(r[r.recommended_qty > 0].head(500))
    pick = st.selectbox("Explain recommendation", r.recommendation_id.head(500))
    if pick: st.info(r.set_index("recommendation_id").loc[pick, "explanation"])
with t4:
    d = summ["detection"]; st.metric("Precision", f"{d['overall']['precision']:.1%}"); st.metric("Recall", f"{d['overall']['recall']:.1%}")
    st.dataframe(pd.DataFrame(d["per_issue"])); st.dataframe(load(str(output_dir / "reports"), "exceptions_detected").head(500))
with t5:
    a, b_, c_ = st.columns(3); mu = a.number_input("Daily demand", 0.0, 1e4, 20.0); L = b_.number_input("Lead time (d)", 0.1, 90.0, 5.0); ssx = c_.number_input("Safety stock override (0=formula)", 0.0, 1e5, 30.0)
    sd = a.number_input("Demand std", 0.0, 1e3, 5.0); sl = b_.number_input("Lead-time std", 0.0, 30.0, 1.0); ip = c_.number_input("Inventory position", 0, 100000, 40)
    pack = a.number_input("Pack", 1, 1000, 12); moq = b_.number_input("MOQ", 1, 10000, 48); room = c_.number_input("Capacity room", 0, 10**6, 500)
    ss = ssx or float(safety_stock(1.645, mu, sd, L, sl)); rop = mu * L + ss; need = max(mu * (L + 7) + ss - ip, 0) if ip <= rop else 0; q, s = order_qty(need, moq, pack, room)
    st.write(f"ROP = {mu}x{L} + {ss:.1f} = **{rop:.1f}**; IP={ip} -> {'REORDER' if ip <= rop else 'NO ORDER'}; qty **{q}** ({s})")
    L2 = L * 2; st.write(f"Supplier delay x2: ROP {rop:.1f} -> {mu * L2 + ss:.1f} (+{mu * (L2 - L):.1f})")
