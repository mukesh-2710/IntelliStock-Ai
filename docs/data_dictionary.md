# Data Dictionary

_Generated from `src/schema.py` (single source of truth)._

## sku

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| sku_id | string | Y | SKU-NNNNNN | PK | ^SKU-\d{6}$, immutable |
| sku_name | string | Y | text | - | non-empty |
| category | string | Y | {Electronics\|Groceries\|Clothing\|Household\|PersonalCare} | - | enum |
| list_price | float | Y | currency units | - | > 0 |
| lifecycle_status | string | Y | {PLANNED\|ACTIVE\|DISCONTINUED} | - | PLANNED->ACTIVE->DISCONTINUED only |
| launch_date | date | Y | ISO-8601 | - | PLANNED => after as-of date |
| discontinue_date | date | N | ISO-8601 | - | required iff DISCONTINUED; >= launch_date; no sales after |

## store

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| store_id | string | Y | STORE-NNNNNN | PK | ^STORE-\d{6}$, immutable |
| store_name | string | Y | text | - | non-empty |
| region | string | Y | {North\|South\|East\|West\|Central} | - | enum |
| open_date | date | Y | ISO-8601 | - | no sales before open_date |
| status | string | Y | {ACTIVE\|TEMP_CLOSED\|CLOSED} | - | non-ACTIVE blocks replenishment |
| capacity_units | int | Y | units | - | derived = sum(reorder_policy.max_stock_units) for store |

## supplier

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| supplier_id | string | Y | SUP-NNNNNN | PK | ^SUP-\d{6}$ |
| supplier_name | string | Y | text | - | non-empty |
| status | string | Y | {ACTIVE\|SUSPENDED\|INACTIVE} | - | only ACTIVE can be sourced from |
| contract_lead_days | int | Y | days | - | 1..60 |

## supplier_sku

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| supplier_sku_id | string | Y | SSK-NNNNNN | PK | bridge table N:M supplier<->sku |
| supplier_id | string | Y | SUP-NNNNNN | FK supplier.supplier_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| pack_size | int | Y | units/pack | - | >= 1 |
| moq_units | int | Y | units | - | >= 1 |
| unit_cost | float | Y | currency/unit | - | > 0 |
| effective_from | date | Y | ISO-8601 | - | <= effective_to |
| effective_to | date | N | ISO-8601 | - | null = open ended; no overlap per supplier+sku |
| status | string | Y | {ACTIVE\|EXPIRED\|SUSPENDED} | - | enum |
| is_primary | int | Y | {0\|1} | - | one primary per sku per date |

## lead_time_observation

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| observation_id | string | Y | LTO-NNNNNN | PK | unique |
| supplier_id | string | Y | SUP-NNNNNN | FK supplier.supplier_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| store_id | string | Y | STORE-NNNNNN | FK store.store_id | must exist |
| order_date | date | Y | ISO-8601 | - | <= received_date |
| received_date | date | Y | ISO-8601 | - | >= order_date |
| lead_time_days | int | Y | days | - | = received_date - order_date, must be >= 1 |
| ordered_qty | int | Y | units | - | > 0 |
| received_qty | int | Y | units | - | = ordered_qty (full receipt in baseline) |

## reorder_policy

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| policy_id | string | Y | POL-NNNNNN | PK | unique; one ACTIVE per store+sku+date (the SKU/store matrix) |
| store_id | string | Y | STORE-NNNNNN | FK store.store_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| service_level | float | Y | 0..1 | - | 0.90, 0.95 or 0.98 |
| z_score | float | Y | std-normal quantile | - | = NormalDist.inv_cdf(service_level) |
| review_days | int | Y | days | - | >= 1 |
| max_stock_units | int | Y | units | - | >= 1 shelf/storage capacity for the pair |
| effective_from | date | Y | ISO-8601 | - | <= effective_to |
| effective_to | date | N | ISO-8601 | - | null = open ended |
| status | string | Y | {ACTIVE\|RETIRED} | - | enum |

## sales_history

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| sale_id | string | Y | SALE-<store-id>-<sku>-<date> | PK | unique (store,sku,date) |
| store_id | string | Y | STORE-NNNNNN | FK store.store_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| sale_date | date | Y | ISO-8601 | - | within live window; no sale after discontinue_date |
| units_sold | int | Y | units | - | >= 0 and <= available stock (observed, censored by availability) |
| promo_flag | int | Y | {0\|1} | - | 1 = promotion active |
| stockout_flag | int | Y | {0\|1} | - | 1 = unavailable/short that day -> sale is censored, NOT zero demand |

## inventory_snapshot

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| snapshot_id | string | Y | INV-<store-id>-<sku>-<date> | PK | unique |
| store_id | string | Y | STORE-NNNNNN | FK store.store_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| snapshot_date | date | Y | ISO-8601 | - | end-of-day snapshot |
| opening_on_hand | int | Y | units | - | >= 0 (= previous closing) |
| received_units | int | Y | units | - | >= 0; equals lead_time_observation arrivals |
| units_sold | int | Y | units | - | equals sales_history.units_sold |
| closing_on_hand | int | Y | units | - | = opening + received - sold |
| on_order_units | int | Y | units | - | >= 0 open PO quantity at day end |

## forecast

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| forecast_id | string | Y | FC-<store-id>-<sku>-2026-01 | PK | unique per store+sku+month+version |
| store_id | string | Y | STORE-NNNNNN | FK store.store_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| forecast_month | string | Y | YYYY-MM | - | = forecast_start_date month |
| forecast_start_date | date | Y | ISO-8601 | - | first target day |
| forecast_end_date | date | Y | ISO-8601 | - | >= start |
| data_cutoff_date | date | Y | ISO-8601 | - | MUST be < forecast_start_date (no future sales) |
| model_name | string | Y | {moving_avg\|exp_smooth\|croston_sba\|seasonal_naive\|category_fallback} | - | enum |
| history_valid_days | int | Y | days | - | uncensored days used |
| daily_forecast | float | Y | units/day | - | >= 0 |
| demand_std_daily | float | Y | units/day | - | >= 0 |
| total_forecast | float | Y | units | - | = daily_forecast x horizon days |
| lower_90 | float | Y | units | - | >= 0, <= total_forecast |
| upper_90 | float | Y | units | - | >= total_forecast |
| confidence | string | Y | {HIGH\|MEDIUM\|LOW} | - | LOW for fallback/short history |
| forecast_version | int | Y | counter | - | >= 1 |

## purchase_recommendation

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| recommendation_id | string | Y | PO-2026-NNNNNN | PK | unique |
| forecast_id | string | Y | FC-... | FK forecast.forecast_id | lineage; must exist |
| policy_id | string | Y | POL-NNNNNN | FK reorder_policy.policy_id | lineage; must exist |
| store_id | string | Y | STORE-NNNNNN | FK store.store_id | must exist |
| sku_id | string | Y | SKU-NNNNNN | FK sku.sku_id | must exist |
| supplier_id | string | N | SUP-NNNNNN | FK supplier.supplier_id | null when no eligible supplier |
| as_of_date | date | Y | ISO-8601 | - | inventory state date |
| order_date | date | Y | ISO-8601 | - | = as_of_date + 1 |
| decision | string | Y | {REORDER\|REORDER_CAPPED_BY_CAPACITY\|NO_ORDER\|BLOCKED_DISCONTINUED\|BLOCKED_STORE_CLOSED\|BLOCKED_NO_SUPPLIER\|BLOCKED_SUPPLIER_SUSPENDED\|INFEASIBLE_CAPACITY} | - | enum |
| daily_demand_forecast | float | Y | units/day | - | from forecast |
| demand_std_daily | float | Y | units/day | - | from forecast |
| lead_time_mean_days | float | Y | days | - | valid observations only |
| lead_time_std_days | float | Y | days | - | >= 0 |
| safety_stock_units | float | Y | units | - | = z*sqrt(L*sd_d^2 + mu^2*sd_L^2) |
| reorder_point_units | float | Y | units | - | = mu*L + SS |
| on_hand_units | int | Y | units | - | >= 0 |
| on_order_units | int | Y | units | - | >= 0 |
| inventory_position | int | Y | units | - | = on_hand + on_order |
| order_up_to_units | float | Y | units | - | = mu*(L+R) + SS |
| required_qty | float | Y | units | - | = max(order_up_to - IP,0) if IP <= ROP else 0 |
| supplier_pack_size | int | N | units/pack | - | from supplier_sku effective at order_date |
| supplier_moq | int | N | units | - | from supplier_sku effective at order_date |
| max_stock_units | int | Y | units | - | from reorder_policy |
| recommended_qty | int | Y | units | - | 0 or multiple of pack, >= MOQ, IP+qty <= max_stock |
| unit_cost | float | N | currency/unit | - | from supplier_sku |
| total_cost | float | Y | currency | - | = recommended_qty x unit_cost |
| expected_arrival_date | date | N | ISO-8601 | - | order_date + ceil(L) |
| stockout_risk | string | Y | {LOW\|MEDIUM\|HIGH} | - | HIGH if on_hand < mu*L |
| forecast_confidence | string | Y | {HIGH\|MEDIUM\|LOW} | - | copied from forecast |
| status | string | Y | {GENERATED\|VALIDATED\|BLOCKED\|NO_ACTION\|PENDING_APPROVAL\|APPROVED\|REJECTED\|ORDER_CREATED\|PARTIALLY_RECEIVED\|COMPLETED} | - | see TRANSITIONS |
| explanation | string | Y | text | - | human-readable calculation trace |

## recommendation_event

| field | type | req | allowed values / units | key | validation rule |
|---|---|---|---|---|---|
| event_id | string | Y | EVT-2026-NNNNNN | PK | immutable append-only |
| recommendation_id | string | Y | PO-2026-NNNNNN | FK purchase_recommendation.recommendation_id | must exist |
| previous_status | string | N | status enum | - | null for first event |
| new_status | string | Y | status enum | - | valid transition from previous_status |
| actor | string | Y | text | - | system / role |
| reason | string | Y | text | - | non-empty |
| event_ts | string | Y | ISO-8601 UTC | - | monotone per recommendation |

## Relationships

| Relationship | Cardinality | Optional? | Notes |
|---|---|---|---|
| supplier - supplier_sku - sku | N:M via `supplier_sku` (bridge) | sku may have no valid supplier (exception path) | effective-dated terms (pack/MOQ/cost) |
| store - reorder_policy - sku | N:M via `reorder_policy` (the SKU/store matrix) | - | one ACTIVE policy per pair per date |
| store / sku - sales_history | 1:N each | - | PK = store+sku+date |
| store / sku - inventory_snapshot | 1:N each | - | 1:1 with sales_history per live day |
| supplier / sku / store - lead_time_observation | 1:N each | - | one row per received PO |
| store+sku - forecast | 1:N (month, version) | - | FC-<store>-<sku>-YYYY-MM |
| forecast - purchase_recommendation | 1:N | - | mandatory lineage (forecast_id, policy_id) |
| purchase_recommendation - recommendation_event | 1:N | - | append-only status history |
