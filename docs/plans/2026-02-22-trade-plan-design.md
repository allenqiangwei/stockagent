# Trade Plan Mechanism Design

**Date**: 2026-02-22
**Status**: Approved
**Approach**: A — Two-stage scheduler (execute plans first, then generate new ones)

## Problem

The current bot trading engine executes trades immediately when AI produces recommendations (T day evening), using target prices as if they were filled instantly. This is unrealistic — in real trading, a decision made after market close can only be executed on the next trading day, and only if the market price reaches the target.

## Solution Overview

Introduce a `BotTradePlan` layer between AI recommendations and trade execution:

```
T日 19:00: AI分析 → 创建交易计划(plan_date = T+1)
T+1日 19:00: 检查计划 → 当日high/low是否触发 → 执行或过期
```

## Data Model

### BotTradePlan

| Field | Type | Description |
|-------|------|-------------|
| id | int PK | |
| stock_code | str(6), indexed | |
| stock_name | str(50) | |
| direction | str(4) | "buy" or "sell" |
| plan_price | float | AI recommended price (limit order) |
| quantity | int | Pre-calculated: buy=floor(100k/price/100)*100, sell=holding*pct |
| sell_pct | float | Sell percentage (only for sell, 100=full exit) |
| plan_date | str(10) | Target execution date (next trading day) |
| status | str(10) | "pending" / "executed" / "expired" |
| thinking | text | AI reasoning from recommendation |
| report_id | int, nullable | Associated AI report |
| created_at | datetime | |
| executed_at | datetime, nullable | When actually executed |
| execution_price | float, nullable | Actual fill price (= plan_price) |

**Uniqueness**: Per stock_code + direction, only one `pending` plan allowed. New recommendations upsert (update) existing pending plans.

## Scheduler Flow

```
19:00 _do_refresh(trade_date = today)

  Step 0: execute_pending_plans(db, today)
    - Query: plan_date <= today AND status = "pending"
    - plan_date < today → expired (missed day cleanup)
    - plan_date = today:
        Fetch today's OHLCV (high, low)
        Buy trigger:  low <= plan_price
        Sell trigger: high >= plan_price
        Triggered → _execute_buy/_execute_sell, mark "executed"
        Not triggered → mark "expired"

  Step 1: Trading day check + data sync + signal generation (unchanged)

  Step 2: AI analysis → save AIReport (unchanged)

  Step 3: create_trade_plans(db, report_id, report_date, recommendations)
    - next_td = get_next_trading_day(report_date)
    - buy → upsert BotTradePlan(direction="buy", plan_price=entry_price, plan_date=next_td)
    - sell/reduce → upsert BotTradePlan(direction="sell", plan_price=target, plan_date=next_td)
    - hold → record BotTrade as before, no plan created
```

## Function Changes

### bot_trading_engine.py

| Function | Change |
|----------|--------|
| `execute_bot_trades` | **Removed** — replaced by `create_trade_plans` |
| `create_trade_plans(db, report_id, report_date, recs)` | **New** — creates/updates BotTradePlan records |
| `execute_pending_plans(db, trade_date)` | **New** — checks plans against OHLCV, executes or expires |
| `_execute_buy` | **Unchanged** — called by `execute_pending_plans` |
| `_execute_sell` | **Unchanged** — called by `execute_pending_plans` |
| `_execute_hold` | **Unchanged** — called directly by `create_trade_plans` |
| `_create_review` | **Unchanged** |

### signal_scheduler.py

| Location | Change |
|----------|--------|
| `_do_refresh` Step 0 | **New** — call `execute_pending_plans(db, trade_date)` before anything else |
| `_run_ai_analysis` | **Changed** — call `create_trade_plans` instead of `execute_bot_trades` |

### ai_analyst.py

| Endpoint | Change |
|----------|--------|
| `POST /api/ai/reports/save` | Call `create_trade_plans` instead of `execute_bot_trades`. Return `trade_plans` instead of `bot_trades`. |

## API Endpoints

### New

```
GET /api/bot/plans           — List plans (optional ?status=pending|executed|expired)
GET /api/bot/plans/pending   — Shortcut for pending plans only
```

### Modified

```
POST /api/ai/reports/save    — Returns trade_plans instead of bot_trades
```

## Frontend Changes

AI Trading tab sub-tabs: **Holdings | Plans (new) | Closed**

Plans tab shows:
- Pending plans (yellow border): stock, direction, plan_price, plan_date, quantity
- Recent executed/expired plans (grey, collapsed)

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Stock suspended / no OHLCV | Plan expired |
| Holding reduced before sell plan executes | Sell min(plan_qty, actual_holding); if 0 → expired |
| Buy plan for stock already held | Normal — _execute_buy handles averaging up |
| Scheduler missed a day | plan_date < today → expired in next run |
| AI gives no price | Skip, don't create plan |
| No next trading day within 30 days | Return empty, log warning |
| Buy + sell plans for same stock | Allowed — independent slots |

## Trigger Rules

- **Buy**: `daily_low <= plan_price` (price dipped to target → filled)
- **Sell**: `daily_high >= plan_price` (price rose to target → filled)
- **Execution price**: Always `plan_price` (limit order semantics)
- **Plan TTL**: T+1 only. Not triggered on plan_date → expired.
