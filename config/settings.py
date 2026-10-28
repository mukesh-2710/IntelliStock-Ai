"""Central configuration. One generator, parameterised scale (Step 4)."""
SEED = 20261022
START_DATE = "2025-01-01"
DAYS = 365
HOLDOUT_DAYS = 28            # temporal holdout = last 28 days of history
MIN_VALID_DAYS = 28          # fewer uncensored days -> category fallback (cold start)
# assortment = share of the SKU x store matrix that is actually stocked.
# full: 2000 x 100 x 5% = 10k pairs -> ~3.65M rows per daily table (use 1.0 for the literal 73M matrix).
SCALES = {
    "starter": dict(n_skus=60,   n_stores=8,   assortment=0.50, n_inject=10),
    "medium":  dict(n_skus=400,  n_stores=30,  assortment=0.10, n_inject=50),
    "full":    dict(n_skus=2000, n_stores=100, assortment=0.05, n_inject=200),
}
