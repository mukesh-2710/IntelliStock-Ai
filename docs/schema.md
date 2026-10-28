# Schema, Relationships & Lifecycle
Full field-level dictionary: `data_dictionary.md` (generated from `src/schema.py`; tests assert exported CSV columns match it).

```
supplier ─< supplier_sku >─ sku ─< reorder_policy >─ store      (bridges give N:M; reorder_policy = SKU/store matrix)
store/sku ─< sales_history        store/sku ─< inventory_snapshot   (1:1 per live day)
supplier/sku/store ─< lead_time_observation
store+sku ─< forecast ─< purchase_recommendation >─ reorder_policy
purchase_recommendation ─< recommendation_event   (append-only)
```
Keys: PK per entity (`schema.pks()`), FKs declared in the dictionary (19 relationships; all validated and enforced in SQLite). SQLite also enforces required columns, enum domains, and row-level business checks. Event triggers prevent a timestamp before its recommendation's `order_date` and out-of-order inserts. Foreign-key enforcement is connection-local in SQLite; callers must issue `PRAGMA foreign_keys = ON`.
Optional relationships: `purchase_recommendation.supplier_id` (null when sourcing is blocked), `supplier_sku.effective_to`, `sku.discontinue_date`.
Effective dating: `supplier_sku` (pack/MOQ/cost; a terms change takes effect on the order date), `reorder_policy`.
The optional SQLite export contains the clean baseline records. Injected anomaly rows remain in the CSV export so invalid cases can be inspected without weakening database constraints.

## Lifecycle states
- **SKU:** PLANNED → ACTIVE → DISCONTINUED (no sales after `discontinue_date`; DISCONTINUED never recommended; PLANNED gets cold-start `category_fallback`).
- **Supplier / SupplierSKU:** ACTIVE | SUSPENDED | INACTIVE, ACTIVE | EXPIRED | SUSPENDED — only ACTIVE+ACTIVE and date-effective may be sourced.
- **Recommendation:** GENERATED → VALIDATED | BLOCKED | NO_ACTION; VALIDATED → PENDING_APPROVAL → APPROVED | REJECTED; APPROVED → ORDER_CREATED → PARTIALLY_RECEIVED* → COMPLETED. Invalid transitions and duplicate approvals raise (`replenishment.transition`).

## Derived values (never generated independently)
`closing = opening + received − sold`; `capacity_units = Σ max_stock`; `lead_time_days = received − order`; `total_forecast = daily × days`; `IP = on_hand + on_order`; `ROP`, `SS`, order-up-to, qty, cost, expected arrival — all computed from source rows and re-checked by `validation.py`.
