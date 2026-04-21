# Trading Diary Feature Design Spec

## Goal

Add a real-time "日记" (Diary) tab to the `/ai` page that shows the complete daily do_refresh pipeline progress, trade execution results with reasons, and next-day plan details with creation rationale. The diary updates live during do_refresh execution and serves as a historical audit trail.

## Architecture

- **Backend**: New `GET /api/bot/diary/{date}` endpoint in `api/routers/bot_trading.py` that aggregates data from Job, BotTrade, BotTradePlan, BotPortfolio, TradingSignal, and GammaSnapshot tables into a single response.
- **Frontend**: New "日记" tab in `/ai` page (`web/src/app/ai/page.tsx`), with 5-second polling when do_refresh is running.
- **No new DB tables**: All data already exists, this is pure aggregation + presentation.

## Backend: `GET /api/bot/diary/{date}`

### Request
```
GET /api/bot/diary/2026-03-24
```

### Response Schema

```python
class DiaryRefreshStep(BaseModel):
    name: str                    # "数据同步", "执行交易计划", etc.
    status: str                  # "done"|"running"|"pending"|"failed"|"skipped"
    started_at: str | None       # ISO timestamp
    duration_sec: float | None   # seconds taken
    detail: str                  # human-readable result, e.g. "5187 records"
    progress: str | None         # e.g. "2476/5187" (only for running step)
    error: str | None            # error message if failed

class DiaryRefresh(BaseModel):
    job_id: int | None
    status: str                  # "succeeded"|"running"|"failed"|"not_started"
    started_at: str | None
    finished_at: str | None
    duration_sec: float | None
    steps: list[DiaryRefreshStep]
    error: str | None

class DiaryExecutionBuy(BaseModel):
    code: str
    name: str
    price: float                 # execution price
    quantity: int
    amount: float
    plan_price: float            # original plan price
    day_low: float | None
    trigger: str                 # "日低1.82≤计划价1.85"
    strategy_name: str | None
    alpha: float | None
    beta: float | None
    gamma: float | None
    combined: float | None

class DiaryExecutionSell(BaseModel):
    code: str
    name: str
    price: float
    quantity: int
    amount: float
    reason: str                  # "take_profit"|"stop_loss"|"max_hold"|"ai_recommend"
    reason_label: str            # "止盈"|"止损"|"超期"|"AI"
    buy_price: float | None
    pnl: float | None
    pnl_pct: float | None
    hold_days: int | None
    trigger: str                 # "日高9.40≥止盈价9.40"

class DiaryExecutionExpired(BaseModel):
    code: str
    name: str
    direction: str               # "buy"|"sell"
    plan_price: float
    day_high: float | None
    day_low: float | None
    reason: str                  # "日高3.81<止盈价3.83, 差0.5%"
    source: str | None           # "take_profit"|"stop_loss"|"beta"|etc.

class DiaryExecutionSummary(BaseModel):
    plans_total: int
    executed: int
    expired: int
    buys: int
    sells_tp: int
    sells_sl: int
    sells_mhd: int
    sells_ai: int
    family_skipped: int          # same-family dedup skips

class DiaryExecution(BaseModel):
    summary: DiaryExecutionSummary
    buy_list: list[DiaryExecutionBuy]
    sell_list: list[DiaryExecutionSell]
    expired_list: list[DiaryExecutionExpired]

class DiaryPlanBuy(BaseModel):
    code: str
    name: str
    plan_price: float | None
    quantity: int | None
    strategy_name: str | None
    alpha: float | None
    beta: float | None
    gamma: float | None
    combined: float | None
    gamma_daily_mmd: str | None   # "3B:笔"
    gamma_weekly_mmd: str | None
    source: str                   # "beta"
    reason: str                   # human-readable, auto-generated from conditions

class DiaryPlanSell(BaseModel):
    code: str
    name: str
    plan_price: float | None
    source: str                   # "take_profit"|"stop_loss"|"max_hold"|"signal"
    source_label: str             # "止盈"|"止损"|"超期"|"信号"
    reason: str                   # "持有已达MHD(15天), 自动平仓"
    hold_days: int | None
    strategy_name: str | None

class DiaryPlansSummary(BaseModel):
    buy: int
    sell_tp: int
    sell_sl: int
    sell_mhd: int
    sell_signal: int

class DiaryPlansCreated(BaseModel):
    for_date: str                 # "2026-03-25"
    summary: DiaryPlansSummary
    buy_list: list[DiaryPlanBuy]
    sell_list: list[DiaryPlanSell]

class DiarySignals(BaseModel):
    generated: int
    buy_signals: int
    sell_signals: int

class DiaryPortfolioSnapshot(BaseModel):
    total_holdings: int
    total_invested: float
    total_market_value: float | None
    daily_pnl: float | None
    daily_pnl_pct: float | None

class TradingDiary(BaseModel):
    date: str
    is_trading_day: bool
    refresh: DiaryRefresh
    execution: DiaryExecution
    portfolio_snapshot: DiaryPortfolioSnapshot
    signals: DiarySignals
    plans_created: DiaryPlansCreated
```

### Implementation: `_build_diary(db, date) -> TradingDiary`

**Step-by-step data collection:**

1. **refresh** — Query `Job` where `job_type="data_sync"` and title contains the date. Parse `JobEvent` records to reconstruct step timeline. If no job found and date is today, check `scheduler-status` for live progress.

2. **execution** — Query `BotTrade` where `trade_date=date`, join with `BotTradePlan` to get plan_price and trigger info. For expired plans, query `BotTradePlan` where `plan_date=date AND status="expired"`, join with `DailyPrice` to get actual high/low for reason generation.

3. **portfolio_snapshot** — Query current `BotPortfolio` aggregate stats. For historical dates, approximate from `BetaDailyTrack` counts.

4. **signals** — Query `TradingSignal` where `trade_date=date`, count by `market_regime`.

5. **plans_created** — Query `BotTradePlan` where `plan_date=date+1` (next trading day) AND `created_at` falls on the diary date. Join with GammaSnapshot for gamma details. Auto-generate `reason` from:
   - Buy plans: strategy buy_conditions + gamma_daily_mmd + alpha/gamma scores
   - Sell plans: source field → human-readable label + hold_days if max_hold

### Reason Generation Logic

**Buy plan reason** (auto-generated):
```python
def _generate_buy_reason(plan, gamma_cache, strategy_cache):
    parts = []
    # Gamma info
    gamma = gamma_cache.get(plan.stock_code, {})
    if gamma.get("daily_mmd"):
        mmd_type, level = gamma["daily_mmd"].split(":")
        parts.append(f"日线{mmd_type}买点({level}级)")
    if gamma.get("weekly_mmd"):
        parts.append(f"周线{gamma['weekly_mmd']}共振")
    # Strategy conditions summary
    strat = strategy_cache.get(plan.strategy_id)
    if strat and strat.buy_conditions:
        for c in strat.buy_conditions:
            field = c.get("field", "")
            if "RSI" in field:
                lo = [x for x in strat.buy_conditions if x.get("field") == field and x.get("operator") == ">"]
                hi = [x for x in strat.buy_conditions if x.get("field") == field and x.get("operator") == "<"]
                if lo and hi:
                    parts.append(f"RSI {lo[0].get('compare_value')}-{hi[0].get('compare_value')}")
            elif "ATR" in field and c.get("operator") == "<" and c.get("compare_type") == "value":
                parts.append(f"ATR<{c.get('compare_value')}")
    # Alpha score context
    if plan.alpha_score and plan.alpha_score >= 90:
        parts.append(f"Alpha {plan.alpha_score}(top策略)")
    return ", ".join(parts) if parts else "Beta评分系统推荐"
```

**Sell plan reason**:
```python
source_reasons = {
    "take_profit": "止盈挂单: 价格达到TP{tp}%目标",
    "stop_loss": "止损挂单: 防止亏损超过SL{sl}%",
    "max_hold": "到期卖出: 持有已达{mhd}天上限",
    "signal": "信号卖出: 卖出信号触发",
}
```

**Expired plan reason**:
```python
def _generate_expired_reason(plan, ohlcv):
    if plan.direction == "buy":
        return f"日低{ohlcv.low}>{plan.plan_price}, 未触及买入价"
    else:
        gap = round((plan.plan_price - ohlcv.high) / plan.plan_price * 100, 1)
        return f"日高{ohlcv.high}<目标{plan.plan_price}, 差{gap}%"
```

## Frontend: 日记 Tab

### Location
- New tab "日记" added to the existing tab bar in `/ai` page
- Tab value: `"diary"`
- Position: after "已完结"

### Component Structure

```
DiaryTab
├── DiaryDatePicker          // [< 2026-03-24 >] with prev/next arrows
├── DiaryRefreshPanel        // do_refresh pipeline steps
│   └── DiaryStepRow × N    // individual step with status icon + detail
├── DiaryExecutionPanel      // today's trade execution
│   ├── ExecutionSummaryBar  // 买145 | 止盈14 | 止损2 | 过期174
│   ├── ExecutionBuyList     // collapsible list of buys
│   ├── ExecutionSellList    // collapsible list of sells (grouped by reason)
│   └── ExecutionExpiredList // collapsible list of expired plans
├── DiarySignalsPanel        // signal generation summary
├── DiaryPlansPanel          // next-day plans created
│   ├── PlanBuyList          // buy plans with reason
│   └── PlanSellList         // sell plans grouped by source
└── DiaryPortfolioPanel      // portfolio snapshot
```

### Polling Logic
```typescript
// Poll every 5 seconds when refresh is running
const isRefreshing = diary?.refresh?.status === "running";
useSWR(`/api/bot/diary/${selectedDate}`, fetcher, {
  refreshInterval: isRefreshing ? 5000 : 0,
});
```

### Step Status Icons
- ✅ `done` — green check
- 🔄 `running` — spinning loader + progress bar if available
- ⏳ `pending` — gray clock
- ❌ `failed` — red X with error tooltip
- ⏭️ `skipped` — gray skip icon

### Collapsible Lists
Each list section (buys, sells, expired, buy plans, sell plans) uses `<details>` with default:
- **Buys**: expanded if ≤20 items, collapsed if >20
- **Sells**: grouped by reason (TP/SL/MHD/AI), each group collapsible
- **Expired**: collapsed by default (usually large)
- **Buy plans**: expanded (usually small, high interest)
- **Sell plans**: grouped by source, collapsed by default

## Files to Create/Modify

### Create
- `api/schemas/diary.py` — All Pydantic models above
- `api/services/diary_service.py` — `build_diary(db, date)` aggregation logic

### Modify
- `api/routers/bot_trading.py` — Add `GET /diary/{date}` endpoint
- `web/src/app/ai/page.tsx` — Add "日记" tab + DiaryTab component
- `web/src/lib/api.ts` — Add `fetchDiary(date)` function
- `web/src/types/index.ts` — Add TypeScript interfaces for diary response

## Review Fixes Applied

### Fix 1: Polling library → @tanstack/react-query (not SWR)
The frontend uses `@tanstack/react-query` throughout. Polling pattern:
```typescript
// In web/src/hooks/use-queries.ts
export function useDiary(date: string) {
  return useQuery({
    queryKey: ["diary", date],
    queryFn: () => bot.fetchDiary(date),
    enabled: !!date,
    refetchInterval: (query) =>
      query.state.data?.refresh?.status === "running" ? 5000 : false,
  });
}
```

### Fix 2: Job step reconstruction from progress_pct ladder (not JobEvent)
`_do_refresh` uses `jm.update_progress(job_id, pct, message)` but never calls `emit_event()`. Steps must be reconstructed from the Job's `progress_pct` and `progress_message` against this static ladder:

| pct | Step Name |
|-----|-----------|
| 10 | 数据完整性检查 |
| 25 | 批量同步日线数据 |
| 50 | 执行交易计划 |
| 70 | 监控退出条件 |
| 75 | 策略池检查 |
| 80 | 生成交易信号 |
| 85 | Beta每日追踪 |
| 88 | Beta ML训练 |
| 90 | Gamma评分 |
| 92 | Beta评分+计划 |
| 96 | 生成卖出计划 |
| 100 | 完成 |

For live-running state, read `get_signal_scheduler().get_status()` directly in the service layer (returns `_sync_step`, `_sync_done`, `_sync_total`, `_is_refreshing`).

### Fix 3: BotTrade ↔ BotTradePlan join via (stock_code, strategy_id)
No FK exists between the two tables. Reconstruct the relationship:
- Fetch all `BotTradePlan` where `plan_date = diary_date AND status = "executed"`
- Build lookup keyed on `(stock_code, strategy_id)`
- Match each `BotTrade` to its plan by these two fields
- Assumption: at most one plan per `(stock_code, strategy_id, direction)` executes per day (enforced by the existing dedup logic)

### Fix 4: Remove `family_skipped` from DiaryExecutionSummary
The family-dedup skip in `_execute_buy()` returns `None` silently with no persistent record. Remove this field from the spec until a `JobEvent` emission is added to the engine.

### Fix 5: Use `_get_next_trading_day()` for plan lookup
`plan_date = date + 1` is wrong for Fridays and holidays. Use:
```python
from api.services.bot_trading_engine import _get_next_trading_day
next_date = _get_next_trading_day(db, diary_date) or diary_date
plans = db.query(BotTradePlan).filter(BotTradePlan.plan_date == next_date).all()
```

### Fix 6: RSI extraction guard for compare_type
Add `compare_type == "value"` guard:
```python
lo = [x for x in strat.buy_conditions
      if x.get("field") == field and x.get("operator") == ">"
      and x.get("compare_type") == "value"]
```

### Fix 7: Portfolio snapshot = null for historical dates
`BotPortfolio` is mutable (rows deleted on exit). For non-today dates, `portfolio_snapshot` is set to `null`. Only today's date gets a live portfolio snapshot. A future enhancement could add a daily snapshot table.

### Minor fixes
- M2: `DiaryPlanBuy.source` → `str` (not hardcoded "beta"), can be "ai" or "beta"
- M3: Document that `sell_reason = "max_hold"` appears on the day the plan EXECUTES (day after MHD detected)
- M4: TypeScript interfaces are ADDED to existing `web/src/types/index.ts`, not replaced

## Non-Goals (out of scope)
- Historical portfolio value tracking (would need daily snapshots table)
- Trade P&L attribution by strategy family
- Push notifications (飞书/Slack) for diary events
- PDF/Markdown export of diary
