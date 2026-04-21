# 前复权因子重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change `daily_prices` from storing pre-adjusted (前复权) OHLCV to storing raw (不复权) OHLCV + adj_factor, with real-time forward adjustment at read time.

**Architecture:** TDX collector gets a new `fetch_daily_raw()` that returns unadjusted prices + adj_factor. `data_collector.get_daily_df()` multiplies OHLCV by adj_factor before returning (transparent to callers). All 7 files that directly query `DailyPrice.close` via ORM are updated to multiply by `adj_factor`. A rebuild script re-downloads all data. Daily/weekly adj_factor refresh keeps data current.

**Tech Stack:** pytdx, pandas, SQLAlchemy, PostgreSQL

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/models/stock.py` | Modify | Add `adj_factor` column to DailyPrice |
| `api/services/tdx_collector.py` | Modify | New `fetch_daily_raw()` returning raw OHLCV + adj_factor |
| `api/services/data_collector.py` | Modify | Write adj_factor; read with real-time adjustment |
| `api/services/bot_trading_engine.py` | Modify | `_get_prev_close()` uses adj_factor |
| `api/routers/bot_trading.py` | Modify | `_latest_close()`, `_get_today_prices()` use adj_factor |
| `api/routers/signals.py` | Modify | price_map uses adj_factor |
| `api/routers/stocks.py` | Modify | watchlist/portfolio prices use adj_factor |
| `api/services/beta_engine.py` | Modify | ML features use adj_factor |
| `api/services/beta_tracker.py` | Modify | daily tracking uses adj_factor |
| `api/services/news_stock_matcher.py` | Modify | SQL uses adj_factor |
| `api/services/signal_scheduler.py` | Modify | Daily/weekly adj_factor refresh |
| `scripts/rebuild_daily_prices.py` | Create | Full rebuild script |

---

### Task 1: TDX — fetch_daily_raw()

**Files:**
- Modify: `api/services/tdx_collector.py`

- [ ] **Step 1: Add `fetch_daily_raw()` method**

Add a new method to `TdxCollector` class (after `fetch_daily`) that returns raw (unadjusted) OHLCV plus an `adj_factor` column. The method should:

1. Fetch K-line bars the same way as `fetch_daily()` (paginated `get_security_bars`)
2. Fetch xdxr info via `get_xdxr_info()`
3. Instead of calling `_apply_qfq()` to modify OHLCV, call a new `_compute_adj_factor()` that returns only the factor column
4. Return DataFrame with columns: `date, open, high, low, close, volume, adj_factor`

The `_compute_adj_factor()` static method should:
1. Filter xdxr to category=1 (除权除息) only
2. For each xdxr record, compute `ratio = preclose / close_prev` using the same formula as `_apply_qfq`
3. Build cumulative product from the end (latest day adj=1.0, going backward each ratio multiplies)
4. Return a Series aligned to the K-line dates

Keep the existing `fetch_daily()` method unchanged (backward compatibility for TDX API router).

- [ ] **Step 2: Test manually**

```bash
cd /Users/allenqiang/stockagent && NO_PROXY='*' python3 -c "
from api.services.tdx_collector import TdxCollector
tdx = TdxCollector()
df = tdx.fetch_daily_raw('000001', '2026-04-01', '2026-04-11')
print(df[['date','open','high','low','close','adj_factor']].tail(5))
print(f'adj_factor range: {df.adj_factor.min():.6f} ~ {df.adj_factor.max():.6f}')
# Verify: raw_close * adj_factor should ≈ forward-adjusted close
df_qfq = tdx.fetch_daily('000001', '2026-04-01', '2026-04-11')
print(f'\nRaw close × adj: {(df.close.iloc[-1] * df.adj_factor.iloc[-1]):.2f}')
print(f'QFQ close:        {df_qfq.close.iloc[-1]:.2f}')
"
```

Expected: latest adj_factor = 1.0 (or very close), and `raw × adj ≈ qfq`.

- [ ] **Step 3: Commit**

```
git commit -m "feat(adj): add fetch_daily_raw() to TDX collector"
```

---

### Task 2: ORM + DB Schema

**Files:**
- Modify: `api/models/stock.py`

- [ ] **Step 1: Add adj_factor column to DailyPrice model**

In `api/models/stock.py`, add after the `amount` field:

```python
    adj_factor: Mapped[float] = mapped_column(Float, default=1.0)
```

- [ ] **Step 2: Add column to DB**

```bash
cd /Users/allenqiang/stockagent && NO_PROXY='*' python3 -c "
from sqlalchemy import create_engine, text
from api.config import get_settings
engine = create_engine(get_settings().database.url)
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS adj_factor FLOAT DEFAULT 1.0'))
    conn.commit()
print('Done')
"
```

- [ ] **Step 3: Commit**

```
git commit -m "feat(adj): add adj_factor column to DailyPrice model + DB"
```

---

### Task 3: data_collector — Write + Read with adj_factor

**Files:**
- Modify: `api/services/data_collector.py`

This is the central change. Two parts:

**Part A — Write path:** `_cache_daily()` and `_cache_daily_batch()` now store adj_factor.

**Part B — Read path:** `get_daily_df()` multiplies OHLCV by adj_factor before returning.

- [ ] **Step 1: Update `_cache_daily()`**

Add `adj_factor` to both the insert and update paths. If the DataFrame has an `adj_factor` column, use it; otherwise default to 1.0.

```python
adj = float(row.get("adj_factor", 1.0))
```

Add to the existing DailyPrice constructor and update block.

- [ ] **Step 2: Update `_cache_daily_batch()`**

Same pattern — read `adj_factor` from the DataFrame row if present, otherwise 1.0. Add to both the update dict and the DailyPrice constructor.

- [ ] **Step 3: Update `_fetch_daily_tdx()` to use `fetch_daily_raw()`**

Change from:
```python
return self._get_tdx_collector().fetch_daily(stock_code, start_date, end_date)
```
To:
```python
return self._get_tdx_collector().fetch_daily_raw(stock_code, start_date, end_date)
```

This makes all TDX-sourced data flow through the raw+adj_factor path.

- [ ] **Step 4: Update `get_daily_df()` read path**

After building the DataFrame from DB rows (around line 331), apply adj_factor before returning:

```python
if rows:
    df = pd.DataFrame([{
        "date": r.trade_date.isoformat() if isinstance(r.trade_date, date) else str(r.trade_date),
        "open": r.open * (r.adj_factor or 1.0),
        "high": r.high * (r.adj_factor or 1.0),
        "low": r.low * (r.adj_factor or 1.0),
        "close": r.close * (r.adj_factor or 1.0),
        "volume": r.volume,
    } for r in rows])
    return df
```

This makes `get_daily_df()` transparent — callers still get forward-adjusted prices.

- [ ] **Step 5: Commit**

```
git commit -m "feat(adj): data_collector reads/writes adj_factor"
```

---

### Task 4: Update all 7 ORM consumer files

**Files:** 7 files that directly read `DailyPrice.close` (or open/high/low) via ORM without going through `get_daily_df()`.

The pattern for each: wherever code reads `row.close`, change to `row.close * (row.adj_factor or 1.0)`. Same for open/high/low.

- [ ] **Step 1: `api/services/bot_trading_engine.py`**

Function `_get_prev_close()` (~line 60):
```python
return round(row.close * (row.adj_factor or 1.0), 2) if row and row.close else None
```

Also in `monitor_exit_conditions()`, anywhere it reads price from DailyPrice — search for all `.close`, `.open`, `.high`, `.low` references on DailyPrice query results and multiply by adj_factor.

- [ ] **Step 2: `api/routers/bot_trading.py`**

Function `_latest_close()` (~line 33-48): multiply close by adj_factor.

Function `_get_today_prices()` (~line 261): in the returned dict, multiply close/open/high/low by adj_factor.

- [ ] **Step 3: `api/routers/signals.py`**

`_create_sell_plans_from_signals()` price_map (~line 195):
```python
price_map = {r.stock_code: float(r.close * (r.adj_factor or 1.0)) for r in ...}
```

- [ ] **Step 4: `api/routers/stocks.py`**

`get_watchlist()` and `get_portfolio()` — multiply latest.close and prev_close by adj_factor.

- [ ] **Step 5: `api/services/beta_engine.py`**

`_compute_ml_features()` — all `prices[i].close` references multiply by adj_factor. Same for index prices if they use DailyPrice (check if IndexDaily has adj_factor — it doesn't need one since indices don't have dividends).

- [ ] **Step 6: `api/services/beta_tracker.py`**

`track_daily_holdings()` — `price.close * (price.adj_factor or 1.0)` for close_price, prev_close, cum_pnl calculations.

- [ ] **Step 7: `api/services/news_stock_matcher.py`**

`align_news_prices()` SQL query — change `SELECT trade_date, close FROM daily_prices` to `SELECT trade_date, close * COALESCE(adj_factor, 1.0) as close FROM daily_prices`.

- [ ] **Step 8: Commit**

```
git commit -m "feat(adj): update 7 ORM consumers to use adj_factor"
```

---

### Task 5: Scheduler — daily + weekly adj_factor refresh

**Files:**
- Modify: `api/services/signal_scheduler.py`
- Modify: `api/services/data_collector.py` (add recompute method)

- [ ] **Step 1: Add `recompute_adj_factors()` to data_collector**

New method on `DataCollector`:

```python
def recompute_adj_factors(self, stock_codes: list[str] | None = None) -> int:
```

For each stock (all if stock_codes is None):
1. Fetch xdxr from TDX
2. Compute adj_factor series
3. Update `daily_prices SET adj_factor = X WHERE stock_code = Y AND trade_date = Z`

Return count of updated rows.

- [ ] **Step 2: Add daily check in do_refresh**

In `signal_scheduler.py`, after Step 0b (data integrity check), add:

```python
# Step 0c: Update adj_factors for stocks with recent xdxr events
try:
    from api.services.data_collector import DataCollector
    collector = DataCollector(db)
    updated = collector.recompute_adj_factors_today(trade_date)
    if updated:
        logger.info("Adj factor updated: %d stocks", updated)
except Exception as e:
    logger.warning("Adj factor update failed (non-fatal): %s", e)
```

The `recompute_adj_factors_today()` method checks TDX for xdxr events on `trade_date` and only recomputes those stocks.

- [ ] **Step 3: Add weekly full recompute**

In `_run_loop`, alongside the daily_basic backfill check (20:00), add a Sunday check:

```python
# Sunday: full adj_factor recompute
if now.weekday() == 6 and now.hour == 3 and now.minute < 1:
    self._recompute_all_adj_factors()
```

The `_recompute_all_adj_factors()` method creates a DataCollector and calls `recompute_adj_factors(None)`.

- [ ] **Step 4: Commit**

```
git commit -m "feat(adj): daily + weekly adj_factor refresh in scheduler"
```

---

### Task 6: Full rebuild script

**Files:**
- Create: `scripts/rebuild_daily_prices.py`

- [ ] **Step 1: Create the rebuild script**

Script that:
1. Reads all stock codes from `stocks` table
2. Truncates `daily_prices`
3. For each stock, calls `tdx.fetch_daily_raw(code, "2015-01-01", today)`
4. Batch inserts into DB (1000 rows per commit for speed)
5. Prints progress every 100 stocks
6. At the end: runs `VACUUM ANALYZE daily_prices`

Key parameters:
- `START_DATE = "2015-01-01"` (configurable)
- `BATCH_COMMIT_SIZE = 1000`
- Uses TdxCollector directly (not DataCollector, to avoid overhead)
- Handles TDX connection failures with retry (3 attempts per stock)

Usage:
```bash
# 1. Stop uvicorn first
# 2. Run:
cd /Users/allenqiang/stockagent && NO_PROXY='*' python3 scripts/rebuild_daily_prices.py
# 3. Start uvicorn
```

- [ ] **Step 2: Test with a small subset**

```bash
cd /Users/allenqiang/stockagent && NO_PROXY='*' python3 scripts/rebuild_daily_prices.py --limit 5 --dry-run
```

- [ ] **Step 3: Commit**

```
git commit -m "feat(adj): add full rebuild script for daily_prices"
```

---

### Task 7: Execute rebuild

This is the actual data migration — run during a maintenance window.

- [ ] **Step 1: Stop uvicorn**

```bash
kill $(ps aux | grep "uvicorn.*8050" | grep -v grep | awk '{print $2}')
```

- [ ] **Step 2: Run rebuild**

```bash
cd /Users/allenqiang/stockagent && NO_PROXY='*' python3 scripts/rebuild_daily_prices.py
```

Expected: 2-4 hours, ~5400 stocks.

- [ ] **Step 3: Verify data**

```bash
NO_PROXY='*' python3 -c "
from sqlalchemy import create_engine, text
from api.config import get_settings
engine = create_engine(get_settings().database.url)
with engine.connect() as conn:
    r = conn.execute(text('SELECT COUNT(*), COUNT(adj_factor), AVG(adj_factor) FROM daily_prices'))
    row = r.fetchone()
    print(f'Total: {row[0]:,}, has adj: {row[1]:,}, avg adj: {row[2]:.4f}')
    # Spot check: latest adj_factor should be 1.0 for most stocks
    r = conn.execute(text('''
        SELECT stock_code, trade_date, close, adj_factor, close * adj_factor as qfq_close
        FROM daily_prices WHERE trade_date = (SELECT MAX(trade_date) FROM daily_prices)
        LIMIT 5
    '''))
    for row in r:
        print(f'  {row[0]} {row[1]}: raw={row[2]:.2f} adj={row[3]:.6f} qfq={row[4]:.2f}')
"
```

- [ ] **Step 4: Start uvicorn and verify end-to-end**

```bash
nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/uvicorn.log 2>&1 &
sleep 8
# Verify API returns correct prices
curl -s --noproxy '*' "http://127.0.0.1:8050/api/market/quote/000001"
curl -s --noproxy '*' "http://127.0.0.1:8050/api/bot/plans/pending" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} plans')"
```

- [ ] **Step 5: Commit verification notes**

```
git commit --allow-empty -m "feat(adj): data rebuild complete — all daily_prices now raw+adj_factor"
```

---

## Summary

| Task | What | Files | Risk |
|------|------|-------|------|
| 1 | TDX fetch_daily_raw() | tdx_collector.py | Low — new method, old one unchanged |
| 2 | ORM + DB column | stock.py + ALTER TABLE | Low — additive column |
| 3 | data_collector read/write | data_collector.py | Medium — central data path |
| 4 | 7 ORM consumers | 7 files | Medium — many touch points |
| 5 | Scheduler refresh | scheduler + collector | Low — new logic only |
| 6 | Rebuild script | new file | Low — standalone |
| 7 | Execute rebuild | runtime | High — 2-4hr downtime, irreversible truncate |

**Critical path:** Tasks 1→2→3 must be in order. Task 4 can be parallel with 5-6. Task 7 must be last.
