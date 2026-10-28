"""Single source of truth for the data dictionary. Validation, docs and tests all read SPEC.
Line format: field|type|required|domain-or-unit|key|rule   (key: PK | FK table.field | -)"""
_RAW = {
"sku": """sku_id|string|Y|SKU-NNNNNN|PK|^SKU-\\d{6}$, immutable
sku_name|string|Y|text|-|non-empty
category|string|Y|{Electronics|Groceries|Clothing|Household|PersonalCare}|-|enum
list_price|float|Y|currency units|-|> 0
lifecycle_status|string|Y|{PLANNED|ACTIVE|DISCONTINUED}|-|PLANNED->ACTIVE->DISCONTINUED only
launch_date|date|Y|ISO-8601|-|PLANNED => after as-of date
discontinue_date|date|N|ISO-8601|-|required iff DISCONTINUED; >= launch_date; no sales after""",
"store": """store_id|string|Y|STORE-NNNNNN|PK|^STORE-\\d{6}$, immutable
store_name|string|Y|text|-|non-empty
region|string|Y|{North|South|East|West|Central}|-|enum
open_date|date|Y|ISO-8601|-|no sales before open_date
status|string|Y|{ACTIVE|TEMP_CLOSED|CLOSED}|-|non-ACTIVE blocks replenishment
capacity_units|int|Y|units|-|derived = sum(reorder_policy.max_stock_units) for store""",
"supplier": """supplier_id|string|Y|SUP-NNNNNN|PK|^SUP-\\d{6}$
supplier_name|string|Y|text|-|non-empty
status|string|Y|{ACTIVE|SUSPENDED|INACTIVE}|-|only ACTIVE can be sourced from
contract_lead_days|int|Y|days|-|1..60""",
"supplier_sku": """supplier_sku_id|string|Y|SSK-NNNNNN|PK|bridge table N:M supplier<->sku
supplier_id|string|Y|SUP-NNNNNN|FK supplier.supplier_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
pack_size|int|Y|units/pack|-|>= 1
moq_units|int|Y|units|-|>= 1
unit_cost|float|Y|currency/unit|-|> 0
effective_from|date|Y|ISO-8601|-|<= effective_to
effective_to|date|N|ISO-8601|-|null = open ended; no overlap per supplier+sku
status|string|Y|{ACTIVE|EXPIRED|SUSPENDED}|-|enum
is_primary|int|Y|{0|1}|-|one primary per sku per date""",
"lead_time_observation": """observation_id|string|Y|LTO-NNNNNN|PK|unique
supplier_id|string|Y|SUP-NNNNNN|FK supplier.supplier_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
store_id|string|Y|STORE-NNNNNN|FK store.store_id|must exist
order_date|date|Y|ISO-8601|-|<= received_date
received_date|date|Y|ISO-8601|-|>= order_date
lead_time_days|int|Y|days|-|= received_date - order_date, must be >= 1
ordered_qty|int|Y|units|-|> 0
received_qty|int|Y|units|-|= ordered_qty (full receipt in baseline)""",
"reorder_policy": """policy_id|string|Y|POL-NNNNNN|PK|unique; one ACTIVE per store+sku+date (the SKU/store matrix)
store_id|string|Y|STORE-NNNNNN|FK store.store_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
service_level|float|Y|0..1|-|0.90, 0.95 or 0.98
z_score|float|Y|std-normal quantile|-|= NormalDist.inv_cdf(service_level)
review_days|int|Y|days|-|>= 1
max_stock_units|int|Y|units|-|>= 1 shelf/storage capacity for the pair
effective_from|date|Y|ISO-8601|-|<= effective_to
effective_to|date|N|ISO-8601|-|null = open ended
status|string|Y|{ACTIVE|RETIRED}|-|enum""",
"sales_history": """sale_id|string|Y|SALE-<store-id>-<sku>-<date>|PK|unique (store,sku,date)
store_id|string|Y|STORE-NNNNNN|FK store.store_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
sale_date|date|Y|ISO-8601|-|within live window; no sale after discontinue_date
units_sold|int|Y|units|-|>= 0 and <= available stock (observed, censored by availability)
promo_flag|int|Y|{0|1}|-|1 = promotion active
stockout_flag|int|Y|{0|1}|-|1 = unavailable/short that day -> sale is censored, NOT zero demand""",
"inventory_snapshot": """snapshot_id|string|Y|INV-<store-id>-<sku>-<date>|PK|unique
store_id|string|Y|STORE-NNNNNN|FK store.store_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
snapshot_date|date|Y|ISO-8601|-|end-of-day snapshot
opening_on_hand|int|Y|units|-|>= 0 (= previous closing)
received_units|int|Y|units|-|>= 0; equals lead_time_observation arrivals
units_sold|int|Y|units|-|equals sales_history.units_sold
closing_on_hand|int|Y|units|-|= opening + received - sold
on_order_units|int|Y|units|-|>= 0 open PO quantity at day end""",
"forecast": """forecast_id|string|Y|FC-<store-id>-<sku>-2026-01|PK|unique per store+sku+month+version
store_id|string|Y|STORE-NNNNNN|FK store.store_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
forecast_month|string|Y|YYYY-MM|-|= forecast_start_date month
forecast_start_date|date|Y|ISO-8601|-|first target day
forecast_end_date|date|Y|ISO-8601|-|>= start
data_cutoff_date|date|Y|ISO-8601|-|MUST be < forecast_start_date (no future sales)
model_name|string|Y|{moving_avg|exp_smooth|croston_sba|seasonal_naive|category_fallback}|-|enum
history_valid_days|int|Y|days|-|uncensored days used
daily_forecast|float|Y|units/day|-|>= 0
demand_std_daily|float|Y|units/day|-|>= 0
total_forecast|float|Y|units|-|= daily_forecast x horizon days
lower_90|float|Y|units|-|>= 0, <= total_forecast
upper_90|float|Y|units|-|>= total_forecast
confidence|string|Y|{HIGH|MEDIUM|LOW}|-|LOW for fallback/short history
forecast_version|int|Y|counter|-|>= 1""",
"purchase_recommendation": """recommendation_id|string|Y|PO-2026-NNNNNN|PK|unique
forecast_id|string|Y|FC-...|FK forecast.forecast_id|lineage; must exist
policy_id|string|Y|POL-NNNNNN|FK reorder_policy.policy_id|lineage; must exist
store_id|string|Y|STORE-NNNNNN|FK store.store_id|must exist
sku_id|string|Y|SKU-NNNNNN|FK sku.sku_id|must exist
supplier_id|string|N|SUP-NNNNNN|FK supplier.supplier_id|null when no eligible supplier
as_of_date|date|Y|ISO-8601|-|inventory state date
order_date|date|Y|ISO-8601|-|= as_of_date + 1
decision|string|Y|{REORDER|REORDER_CAPPED_BY_CAPACITY|NO_ORDER|BLOCKED_DISCONTINUED|BLOCKED_STORE_CLOSED|BLOCKED_NO_SUPPLIER|BLOCKED_SUPPLIER_SUSPENDED|INFEASIBLE_CAPACITY}|-|enum
daily_demand_forecast|float|Y|units/day|-|from forecast
demand_std_daily|float|Y|units/day|-|from forecast
lead_time_mean_days|float|Y|days|-|valid observations only
lead_time_std_days|float|Y|days|-|>= 0
safety_stock_units|float|Y|units|-|= z*sqrt(L*sd_d^2 + mu^2*sd_L^2)
reorder_point_units|float|Y|units|-|= mu*L + SS
on_hand_units|int|Y|units|-|>= 0
on_order_units|int|Y|units|-|>= 0
inventory_position|int|Y|units|-|= on_hand + on_order
order_up_to_units|float|Y|units|-|= mu*(L+R) + SS
required_qty|float|Y|units|-|= max(order_up_to - IP,0) if IP <= ROP else 0
supplier_pack_size|int|N|units/pack|-|from supplier_sku effective at order_date
supplier_moq|int|N|units|-|from supplier_sku effective at order_date
max_stock_units|int|Y|units|-|from reorder_policy
recommended_qty|int|Y|units|-|0 or multiple of pack, >= MOQ, IP+qty <= max_stock
unit_cost|float|N|currency/unit|-|from supplier_sku
total_cost|float|Y|currency|-|= recommended_qty x unit_cost
expected_arrival_date|date|N|ISO-8601|-|order_date + ceil(L)
stockout_risk|string|Y|{LOW|MEDIUM|HIGH}|-|HIGH if on_hand < mu*L
forecast_confidence|string|Y|{HIGH|MEDIUM|LOW}|-|copied from forecast
status|string|Y|{GENERATED|VALIDATED|BLOCKED|NO_ACTION|PENDING_APPROVAL|APPROVED|REJECTED|ORDER_CREATED|PARTIALLY_RECEIVED|COMPLETED}|-|see TRANSITIONS
explanation|string|Y|text|-|human-readable calculation trace""",
"recommendation_event": """event_id|string|Y|EVT-2026-NNNNNN|PK|immutable append-only
recommendation_id|string|Y|PO-2026-NNNNNN|FK purchase_recommendation.recommendation_id|must exist
previous_status|string|N|status enum|-|null for first event
new_status|string|Y|status enum|-|valid transition from previous_status
actor|string|Y|text|-|system / role
reason|string|Y|text|-|non-empty
event_ts|string|Y|ISO-8601 UTC|-|monotone per recommendation""",
}
def _split(ln):
    if ln.split("|")[3].startswith("{"):  # enum domains contain '|' inside {...}
        a, rest = ln.split("{", 1); dom, tail = rest.split("}", 1)
        f, ty, rq, _ = a.split("|"); key, rule = tail.lstrip("|").split("|", 1)
        return f, ty, rq, "{" + dom + "}", key, rule
    return ln.split("|", 5)
SPEC = {t: [dict(zip(("field", "type", "required", "domain", "key", "rule"), _split(ln))) for ln in raw.split("\n")]
        for t, raw in _RAW.items()}
def columns(t): return [r["field"] for r in SPEC[t]]
def enums(): return {(t, r["field"]): set(r["domain"][1:-1].split("|")) for t, rows in SPEC.items() for r in rows if r["domain"].startswith("{")}
def fks(): return [(t, r["field"], *r["key"][3:].split(".")) for t, rows in SPEC.items() for r in rows if r["key"].startswith("FK")]
def pks(): return {t: next(r["field"] for r in rows if r["key"] == "PK") for t, rows in SPEC.items()}

def sqlite_checks(table):
    """Return SQLite CHECK expressions for the business rules expressible per row."""
    q = lambda field: f'"{field}"'
    checks = [
        f"{q(field)} IN ({', '.join(repr(value) for value in sorted(values))})"
        for (t, field), values in enums().items() if t == table
    ]
    rules = {
        "sku": [
            '"list_price" > 0',
            '(("lifecycle_status" = \'DISCONTINUED\' AND "discontinue_date" IS NOT NULL) OR ("lifecycle_status" != \'DISCONTINUED\' AND "discontinue_date" IS NULL))',
            '("discontinue_date" IS NULL OR "discontinue_date" >= "launch_date")',
        ],
        "store": ['"capacity_units" > 0'],
        "supplier": ['"contract_lead_days" BETWEEN 1 AND 60'],
        "supplier_sku": [
            '"pack_size" >= 1', '"moq_units" >= 1', '"unit_cost" > 0',
            '("effective_to" IS NULL OR "effective_to" >= "effective_from")',
            '"is_primary" IN (0, 1)',
        ],
        "lead_time_observation": [
            '"received_date" >= "order_date"',
            '"lead_time_days" >= 1',
            'ABS("lead_time_days" - (julianday("received_date") - julianday("order_date"))) < 0.001',
            '"ordered_qty" > 0', '"received_qty" = "ordered_qty"',
        ],
        "reorder_policy": [
            '"service_level" BETWEEN 0 AND 1', '"review_days" >= 1', '"max_stock_units" >= 1',
            '("effective_to" IS NULL OR "effective_to" >= "effective_from")',
        ],
        "sales_history": [
            '"units_sold" >= 0', '"promo_flag" IN (0, 1)', '"stockout_flag" IN (0, 1)',
        ],
        "inventory_snapshot": [
            '"opening_on_hand" >= 0', '"received_units" >= 0', '"units_sold" >= 0',
            '"closing_on_hand" >= 0', '"on_order_units" >= 0',
            '"closing_on_hand" = "opening_on_hand" + "received_units" - "units_sold"',
        ],
        "forecast": [
            '"forecast_end_date" >= "forecast_start_date"',
            '"data_cutoff_date" < "forecast_start_date"',
            '"forecast_month" = substr("forecast_start_date", 1, 7)',
            '"history_valid_days" >= 0', '"daily_forecast" >= 0', '"demand_std_daily" >= 0',
            '"lower_90" >= 0 AND "lower_90" <= "total_forecast"',
            '"upper_90" >= "total_forecast"', '"forecast_version" >= 1',
        ],
        "purchase_recommendation": [
            '"order_date" = date("as_of_date", \'+1 day\')',
            '"daily_demand_forecast" >= 0', '"demand_std_daily" >= 0',
            '"lead_time_mean_days" > 0', '"lead_time_std_days" >= 0',
            '"on_hand_units" >= 0', '"on_order_units" >= 0',
            '"inventory_position" = "on_hand_units" + "on_order_units"',
            '"recommended_qty" >= 0', '"max_stock_units" >= 1', '"total_cost" >= 0',
            '("recommended_qty" = 0 OR ("supplier_id" IS NOT NULL AND "supplier_pack_size" IS NOT NULL AND "supplier_moq" IS NOT NULL AND "supplier_pack_size" > 0 AND "supplier_moq" > 0 AND "recommended_qty" >= "supplier_moq" AND "recommended_qty" % "supplier_pack_size" = 0 AND "inventory_position" + "recommended_qty" <= "max_stock_units"))',
            '("unit_cost" IS NULL OR ABS("total_cost" - round("recommended_qty" * "unit_cost", 2)) <= 0.011)',
        ],
        "recommendation_event": [
            '"new_status" IN (\'GENERATED\', \'VALIDATED\', \'BLOCKED\', \'NO_ACTION\', \'PENDING_APPROVAL\', \'APPROVED\', \'REJECTED\', \'ORDER_CREATED\', \'PARTIALLY_RECEIVED\', \'COMPLETED\')',
            '("previous_status" IS NULL OR "previous_status" IN (\'GENERATED\', \'VALIDATED\', \'BLOCKED\', \'NO_ACTION\', \'PENDING_APPROVAL\', \'APPROVED\', \'REJECTED\', \'ORDER_CREATED\', \'PARTIALLY_RECEIVED\', \'COMPLETED\'))',
            '(("previous_status" IS NULL AND "new_status" = \'GENERATED\') OR ("previous_status" = \'GENERATED\' AND "new_status" IN (\'VALIDATED\', \'BLOCKED\', \'NO_ACTION\')) OR ("previous_status" = \'VALIDATED\' AND "new_status" = \'PENDING_APPROVAL\') OR ("previous_status" = \'PENDING_APPROVAL\' AND "new_status" IN (\'APPROVED\', \'REJECTED\')) OR ("previous_status" = \'APPROVED\' AND "new_status" = \'ORDER_CREATED\') OR ("previous_status" = \'ORDER_CREATED\' AND "new_status" IN (\'PARTIALLY_RECEIVED\', \'COMPLETED\')) OR ("previous_status" = \'PARTIALLY_RECEIVED\' AND "new_status" IN (\'PARTIALLY_RECEIVED\', \'COMPLETED\')))',
            'length("event_ts") = 20 AND strftime(\'%Y-%m-%dT%H:%M:%SZ\', "event_ts") IS NOT NULL',
        ],
    }
    return checks + rules.get(table, [])

ID_PATTERNS = {"sku_id": r"^SKU-\d{6}$", "store_id": r"^STORE-\d{6}$", "supplier_id": r"^SUP-\d{6}$",
    "recommendation_id": r"^PO-2026-\d{6}$", "event_id": r"^EVT-2026-\d{6}$", "policy_id": r"^POL-\d{6}$",
    "observation_id": r"^LTO-\d{6}$", "supplier_sku_id": r"^SSK-\d{6}$",
    "forecast_id": r"^FC-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}$",
    "sale_id": r"^SALE-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}-\d{2}$", "snapshot_id": r"^INV-STORE-\d{6}-SKU-\d{6}-\d{4}-\d{2}-\d{2}$"}
RELATIONSHIPS = """| Relationship | Cardinality | Optional? | Notes |
|---|---|---|---|
| supplier - supplier_sku - sku | N:M via `supplier_sku` (bridge) | sku may have no valid supplier (exception path) | effective-dated terms (pack/MOQ/cost) |
| store - reorder_policy - sku | N:M via `reorder_policy` (the SKU/store matrix) | - | one ACTIVE policy per pair per date |
| store / sku - sales_history | 1:N each | - | PK = store+sku+date |
| store / sku - inventory_snapshot | 1:N each | - | 1:1 with sales_history per live day |
| supplier / sku / store - lead_time_observation | 1:N each | - | one row per received PO |
| store+sku - forecast | 1:N (month, version) | - | FC-<store>-<sku>-YYYY-MM |
| forecast - purchase_recommendation | 1:N | - | mandatory lineage (forecast_id, policy_id) |
| purchase_recommendation - recommendation_event | 1:N | - | append-only status history |"""
def render_dictionary(path):
    out = ["# Data Dictionary\n", "_Generated from `src/schema.py` (single source of truth)._"]
    for t, rows in SPEC.items():
        out.append(f"\n## {t}\n\n| field | type | req | allowed values / units | key | validation rule |\n|---|---|---|---|---|---|")
        out += ["| " + " | ".join(str(r[k]).replace("|", "\\|") for k in ("field","type","required","domain","key","rule")) + " |" for r in rows]
    out.append("\n## Relationships\n\n" + RELATIONSHIPS)
    open(path, "w").write("\n".join(out) + "\n")
if __name__ == "__main__":
    render_dictionary("docs/data_dictionary.md"); print("written docs/data_dictionary.md")
