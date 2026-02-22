# Trade Plan Mechanism Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace immediate trade execution with a plan-based system where AI creates limit-order plans targeting the next trading day, executed only if market price triggers.

**Architecture:** New `BotTradePlan` model sits between AI recommendations and `_execute_buy/_execute_sell`. Scheduler Step 0 checks pending plans against OHLCV before the existing signal+AI pipeline runs.

**Tech Stack:** SQLAlchemy ORM, FastAPI, React/Next.js, TanStack Query

**Design doc:** `docs/plans/2026-02-22-trade-plan-design.md`

---

### Task 1: BotTradePlan ORM Model

**Files:**
- Modify: `api/models/bot_trading.py`

**Step 1: Add BotTradePlan class**

Add after the existing `BotTradeReview` class (after line 68):

```python
class BotTradePlan(Base):
    """Pending trade plan — created from AI recommendations, executed on next trading day."""

    __tablename__ = "bot_trade_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    direction: Mapped[str] = mapped_column(String(4))  # "buy" | "sell"
    plan_price: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    sell_pct: Mapped[float] = mapped_column(Float, default=0.0)
    plan_date: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|executed|expired
    thinking: Mapped[str] = mapped_column(Text, default="")
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_trade_plan_code_dir_status", "stock_code", "direction", "status"),
        Index("ix_trade_plan_date_status", "plan_date", "status"),
    )
```

**Step 2: Verify import works**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.models.bot_trading import BotTradePlan; print('OK')"`

Expected: `OK`

**Step 3: Create the table**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.models.base import Base, engine; from api.models.bot_trading import BotTradePlan; Base.metadata.create_all(engine); print('Table created')"`

Expected: `Table created`

**Step 4: Commit**

```bash
git add api/models/bot_trading.py
git commit -m "feat(bot): add BotTradePlan ORM model"
```

---

### Task 2: Pydantic Schema for BotTradePlan

**Files:**
- Modify: `api/schemas/bot_trading.py`

**Step 1: Add BotTradePlanItem schema**

Add after the `BotTradeReviewItem` class (after line 55):

```python
class BotTradePlanItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    direction: str  # "buy" | "sell"
    plan_price: float = 0.0
    quantity: int = 0
    sell_pct: float = 0.0
    plan_date: str = ""
    status: str = "pending"
    thinking: str = ""
    report_id: Optional[int] = None
    created_at: str = ""
    executed_at: Optional[str] = None
    execution_price: Optional[float] = None

    model_config = {"from_attributes": True}
```

**Step 2: Verify import**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.schemas.bot_trading import BotTradePlanItem; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add api/schemas/bot_trading.py
git commit -m "feat(bot): add BotTradePlanItem pydantic schema"
```

---

### Task 3: Helper — get_next_trading_day

**Files:**
- Modify: `api/services/bot_trading_engine.py`

**Step 1: Add helper function**

Add after the `BUY_AMOUNT` constant (after line 13), before `execute_bot_trades`:

```python
from api.models.stock import DailyPrice


def _get_next_trading_day(db: Session, after_date: str) -> str | None:
    """Find the next trading day after the given date.

    Uses DataCollector.get_trading_dates to query the exchange calendar.
    Falls back to after_date + 1 weekday if API fails.
    """
    try:
        from api.services.data_collector import DataCollector
        from datetime import date, timedelta

        base = date.fromisoformat(after_date)
        end = base + timedelta(days=30)
        collector = DataCollector(db)
        dates = collector.get_trading_dates(after_date, end.isoformat())
        if dates:
            for d in sorted(dates):
                if d > after_date:
                    return d
    except Exception as e:
        logger.warning("get_next_trading_day failed: %s", e)

    # Fallback: skip weekends
    from datetime import date, timedelta
    d = date.fromisoformat(after_date) + timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d += timedelta(days=1)
    return d.isoformat()
```

**Step 2: Verify import**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.services.bot_trading_engine import _get_next_trading_day; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add api/services/bot_trading_engine.py
git commit -m "feat(bot): add _get_next_trading_day helper"
```

---

### Task 4: create_trade_plans function

**Files:**
- Modify: `api/services/bot_trading_engine.py`

**Step 1: Add create_trade_plans function**

Replace the existing `execute_bot_trades` function (lines 16-52) with `create_trade_plans`. Keep `execute_bot_trades` but rename it to `_legacy_execute_bot_trades` (keep for reference, will delete later).

Add the new function right after `_get_next_trading_day`:

```python
from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview, BotTradePlan


def create_trade_plans(db: Session, report_id: int, report_date: str, recommendations: list[dict]) -> list[dict]:
    """Create trade plans from AI recommendations for the next trading day.

    Instead of executing trades immediately, creates BotTradePlan records
    that will be checked against actual market prices on the plan_date.
    Returns list of created/updated plan summaries.
    """
    if not recommendations:
        return []

    next_td = _get_next_trading_day(db, report_date)
    if not next_td:
        logger.warning("Cannot find next trading day after %s, skipping plan creation", report_date)
        return []

    plans = []

    for rec in recommendations:
        action = rec.get("action", "")
        stock_code = rec.get("stock_code", "")
        stock_name = rec.get("stock_name", "")
        reason = rec.get("reason", "")

        if not stock_code or not action:
            continue

        if action == "buy":
            price = rec.get("entry_price") or rec.get("target_price")
            if not price or price <= 0:
                logger.warning("Plan skipped: no valid price for buy %s", stock_code)
                continue
            quantity = math.floor(BUY_AMOUNT / price / 100) * 100
            if quantity <= 0:
                quantity = 100
            result = _upsert_plan(db, stock_code, stock_name, "buy", price, quantity, 0.0,
                                  next_td, reason, report_id)
            plans.append(result)

        elif action in ("sell", "reduce"):
            price = rec.get("target_price") or rec.get("target")
            if not price or price <= 0:
                logger.warning("Plan skipped: no valid price for sell %s", stock_code)
                continue
            holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == stock_code).first()
            if not holding or holding.quantity <= 0:
                logger.info("Plan skipped: no holding for sell %s", stock_code)
                continue
            sell_pct = 100.0 if action == "sell" else rec.get("position_pct", 50.0)
            quantity = math.floor(holding.quantity * sell_pct / 100 / 100) * 100
            if quantity <= 0:
                quantity = min(100, holding.quantity)
            result = _upsert_plan(db, stock_code, stock_name, "sell", price, quantity, sell_pct,
                                  next_td, reason, report_id)
            plans.append(result)

        elif action == "hold":
            _execute_hold(db, stock_code, stock_name, rec.get("target_price"), reason, report_id, report_date)

    db.commit()
    logger.info("Created/updated %d trade plans for %s", len(plans), next_td)
    return plans


def _upsert_plan(db: Session, code: str, name: str, direction: str,
                 price: float, quantity: int, sell_pct: float,
                 plan_date: str, thinking: str, report_id: int) -> dict:
    """Insert or update a pending trade plan. One pending plan per stock+direction."""
    existing = (
        db.query(BotTradePlan)
        .filter(
            BotTradePlan.stock_code == code,
            BotTradePlan.direction == direction,
            BotTradePlan.status == "pending",
        )
        .first()
    )

    if existing:
        existing.plan_price = price
        existing.quantity = quantity
        existing.sell_pct = sell_pct
        existing.plan_date = plan_date
        existing.thinking = thinking
        existing.report_id = report_id
        existing.stock_name = name
        logger.info("Plan UPDATED: %s %s %s @ ¥%.2f for %s", direction.upper(), code, name, price, plan_date)
        return {"action": "plan_updated", "direction": direction, "stock_code": code,
                "plan_price": price, "quantity": quantity, "plan_date": plan_date}
    else:
        plan = BotTradePlan(
            stock_code=code, stock_name=name, direction=direction,
            plan_price=price, quantity=quantity, sell_pct=sell_pct,
            plan_date=plan_date, status="pending",
            thinking=thinking, report_id=report_id,
        )
        db.add(plan)
        logger.info("Plan CREATED: %s %s %s @ ¥%.2f for %s", direction.upper(), code, name, price, plan_date)
        return {"action": "plan_created", "direction": direction, "stock_code": code,
                "plan_price": price, "quantity": quantity, "plan_date": plan_date}
```

**Step 2: Verify import**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.services.bot_trading_engine import create_trade_plans; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add api/services/bot_trading_engine.py
git commit -m "feat(bot): add create_trade_plans with upsert logic"
```

---

### Task 5: execute_pending_plans function

**Files:**
- Modify: `api/services/bot_trading_engine.py`

**Step 1: Add execute_pending_plans**

Add after `_upsert_plan`:

```python
def execute_pending_plans(db: Session, trade_date: str) -> list[dict]:
    """Check pending trade plans for today and execute those triggered by market prices.

    Buy trigger:  daily low  <= plan_price
    Sell trigger: daily high >= plan_price
    Untriggered plans are marked expired.
    Plans with plan_date < trade_date (missed days) are also expired.
    """
    plans = (
        db.query(BotTradePlan)
        .filter(BotTradePlan.status == "pending", BotTradePlan.plan_date <= trade_date)
        .all()
    )

    if not plans:
        logger.info("No pending trade plans for %s", trade_date)
        return []

    executed = []

    for plan in plans:
        # Missed day cleanup
        if plan.plan_date < trade_date:
            plan.status = "expired"
            logger.info("Plan EXPIRED (missed): %s %s %s, plan_date=%s", plan.direction, plan.stock_code, plan.stock_name, plan.plan_date)
            continue

        # Get today's OHLCV
        ohlcv = (
            db.query(DailyPrice)
            .filter(DailyPrice.stock_code == plan.stock_code, DailyPrice.trade_date == trade_date)
            .first()
        )

        if not ohlcv:
            # Try to fetch data
            try:
                from api.services.data_collector import DataCollector
                collector = DataCollector(db)
                collector.get_daily_df(plan.stock_code, trade_date, trade_date, local_only=False)
                ohlcv = (
                    db.query(DailyPrice)
                    .filter(DailyPrice.stock_code == plan.stock_code, DailyPrice.trade_date == trade_date)
                    .first()
                )
            except Exception as e:
                logger.warning("Failed to fetch OHLCV for %s on %s: %s", plan.stock_code, trade_date, e)

        if not ohlcv:
            plan.status = "expired"
            logger.info("Plan EXPIRED (no data): %s %s %s", plan.direction, plan.stock_code, plan.stock_name)
            continue

        high = float(ohlcv.high)
        low = float(ohlcv.low)

        if plan.direction == "buy":
            triggered = low <= plan.plan_price
        else:  # sell
            triggered = high >= plan.plan_price

        if triggered:
            if plan.direction == "buy":
                result = _execute_buy(
                    db, plan.stock_code, plan.stock_name, plan.plan_price,
                    plan.thinking, plan.report_id, trade_date,
                )
            else:
                # Re-check holding quantity (may have changed since plan creation)
                holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == plan.stock_code).first()
                if not holding or holding.quantity <= 0:
                    plan.status = "expired"
                    logger.info("Plan EXPIRED (no holding): sell %s", plan.stock_code)
                    continue
                actual_sell_pct = plan.sell_pct
                if plan.quantity > holding.quantity:
                    actual_sell_pct = 100.0  # Sell whatever is left
                result = _execute_sell(
                    db, plan.stock_code, plan.stock_name, plan.plan_price,
                    actual_sell_pct, plan.thinking, plan.report_id, trade_date,
                )

            if result:
                plan.status = "executed"
                plan.executed_at = datetime.now()
                plan.execution_price = plan.plan_price
                executed.append(result)
                logger.info("Plan EXECUTED: %s %s %s @ ¥%.2f", plan.direction, plan.stock_code, plan.stock_name, plan.plan_price)
            else:
                plan.status = "expired"
                logger.info("Plan EXPIRED (exec failed): %s %s %s", plan.direction, plan.stock_code, plan.stock_name)
        else:
            plan.status = "expired"
            logger.info("Plan EXPIRED (not triggered): %s %s %s, price=¥%.2f, high=%.2f, low=%.2f",
                        plan.direction, plan.stock_code, plan.stock_name, plan.plan_price, high, low)

    db.commit()
    logger.info("Plan execution done for %s: %d executed, %d total", trade_date, len(executed), len(plans))
    return executed
```

**Step 2: Remove old execute_bot_trades**

Delete the original `execute_bot_trades` function (the one at lines 16-52). It is no longer called anywhere after Tasks 6 and 7.

**Step 3: Verify import**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.services.bot_trading_engine import execute_pending_plans, create_trade_plans; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/bot_trading_engine.py
git commit -m "feat(bot): add execute_pending_plans with OHLCV trigger logic"
```

---

### Task 6: Wire up scheduler

**Files:**
- Modify: `api/services/signal_scheduler.py`

**Step 1: Add Step 0 to _do_refresh**

In `_do_refresh` method, add plan execution **before** the trading day check (before line 106). Insert after `db = SessionLocal()` and `try:` (after line 104):

```python
                # Step 0: Execute pending trade plans (runs on all days)
                try:
                    from api.services.bot_trading_engine import execute_pending_plans
                    plan_results = execute_pending_plans(db, trade_date)
                    if plan_results:
                        logger.info("Executed %d trade plans for %s", len(plan_results), trade_date)
                except Exception as e:
                    logger.error("Trade plan execution failed (non-fatal): %s", e)
                    try:
                        db.rollback()
                    except Exception:
                        pass
```

**Step 2: Update _run_ai_analysis to create plans instead of executing trades**

In `_run_ai_analysis` (line 149), after saving the AI report to DB (after `db.commit()` on line 172), add plan creation:

```python
            # Create trade plans from recommendations
            recs = report.get("recommendations")
            if recs:
                try:
                    from api.services.bot_trading_engine import create_trade_plans
                    plan_results = create_trade_plans(db, ai_report.id, trade_date, recs)
                    logger.info("Created %d trade plans from AI analysis", len(plan_results))
                except Exception as e:
                    logger.warning("Trade plan creation failed (non-fatal): %s", e)
```

**Step 3: Verify no syntax errors**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.services.signal_scheduler import SignalScheduler; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/signal_scheduler.py
git commit -m "feat(bot): wire trade plans into scheduler — Step 0 execute, Step 3 create"
```

---

### Task 7: Update save_report endpoint

**Files:**
- Modify: `api/routers/ai_analyst.py`

**Step 1: Replace execute_bot_trades with create_trade_plans**

In `save_report` function (line 95), change lines 112-128:

Replace:
```python
    # Auto-execute bot trades from recommendations
    bot_trades_result = []
    if body.recommendations:
        from api.services.bot_trading_engine import execute_bot_trades
        try:
            bot_trades_result = execute_bot_trades(
                db, report.id, body.report_date, body.recommendations
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Bot trade execution failed: %s", e)

    return {
        "id": report.id,
        "report_date": report.report_date,
        "summary": report.summary,
        "bot_trades": bot_trades_result,
    }
```

With:
```python
    # Create trade plans from recommendations (plans execute on next trading day)
    trade_plans_result = []
    if body.recommendations:
        from api.services.bot_trading_engine import create_trade_plans
        try:
            trade_plans_result = create_trade_plans(
                db, report.id, body.report_date, body.recommendations
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Trade plan creation failed: %s", e)

    return {
        "id": report.id,
        "report_date": report.report_date,
        "summary": report.summary,
        "trade_plans": trade_plans_result,
    }
```

**Step 2: Verify**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.routers.ai_analyst import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add api/routers/ai_analyst.py
git commit -m "feat(bot): save_report creates trade plans instead of executing trades"
```

---

### Task 8: API endpoints for trade plans

**Files:**
- Modify: `api/routers/bot_trading.py`

**Step 1: Add plan endpoints**

Add imports at the top (line 7), alongside existing imports:

```python
from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview, BotTradePlan
from api.schemas.bot_trading import (
    BotPortfolioItem, BotTradeItem, BotTradeReviewItem,
    BotSummary, BotStockTimeline, BotTradePlanItem,
)
```

Add the following endpoints after `list_reviews` (after line 190), before `update_review`:

```python
@router.get("/plans", response_model=list[BotTradePlanItem])
def list_plans(
    status: str = Query("", description="Filter by status: pending|executed|expired"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List trade plans, optionally filtered by status."""
    q = db.query(BotTradePlan)
    if status:
        q = q.filter(BotTradePlan.status == status)
    rows = q.order_by(BotTradePlan.plan_date.desc(), BotTradePlan.id.desc()).limit(limit).all()
    return [
        BotTradePlanItem(
            id=p.id, stock_code=p.stock_code, stock_name=p.stock_name,
            direction=p.direction, plan_price=p.plan_price, quantity=p.quantity,
            sell_pct=p.sell_pct, plan_date=p.plan_date, status=p.status,
            thinking=p.thinking, report_id=p.report_id,
            created_at=p.created_at.isoformat() if p.created_at else "",
            executed_at=p.executed_at.isoformat() if p.executed_at else None,
            execution_price=p.execution_price,
        )
        for p in rows
    ]


@router.get("/plans/pending", response_model=list[BotTradePlanItem])
def list_pending_plans(db: Session = Depends(get_db)):
    """List only pending trade plans (shortcut)."""
    rows = (
        db.query(BotTradePlan)
        .filter(BotTradePlan.status == "pending")
        .order_by(BotTradePlan.plan_date, BotTradePlan.id)
        .all()
    )
    return [
        BotTradePlanItem(
            id=p.id, stock_code=p.stock_code, stock_name=p.stock_name,
            direction=p.direction, plan_price=p.plan_price, quantity=p.quantity,
            sell_pct=p.sell_pct, plan_date=p.plan_date, status=p.status,
            thinking=p.thinking, report_id=p.report_id,
            created_at=p.created_at.isoformat() if p.created_at else "",
            executed_at=None, execution_price=None,
        )
        for p in rows
    ]
```

**Step 2: Verify**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.routers.bot_trading import router; print([(r.path, r.methods) for r in router.routes])"`

Expected: Should list all routes including `/plans` and `/plans/pending`

**Step 3: Commit**

```bash
git add api/routers/bot_trading.py
git commit -m "feat(bot): add GET /api/bot/plans and /plans/pending endpoints"
```

---

### Task 9: Frontend types + API client

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/hooks/use-queries.ts`

**Step 1: Add TypeScript type**

In `web/src/types/index.ts`, after the `BotStockTimeline` interface (after line 639), add:

```typescript
export interface BotTradePlanItem {
  id: number;
  stock_code: string;
  stock_name: string;
  direction: "buy" | "sell";
  plan_price: number;
  quantity: number;
  sell_pct: number;
  plan_date: string;
  status: "pending" | "executed" | "expired";
  thinking: string;
  report_id: number | null;
  created_at: string;
  executed_at: string | null;
  execution_price: number | null;
}
```

**Step 2: Add API client method**

In `web/src/lib/api.ts`, find the `bot` object (around line 270) and add after `summary`:

```typescript
  plans: (status?: string) =>
    request<BotTradePlanItem[]>(
      `/bot/plans${status ? `?status=${status}` : ""}`
    ),
  pendingPlans: () => request<BotTradePlanItem[]>("/bot/plans/pending"),
```

Add `BotTradePlanItem` to the import from `@/types` at the top of the file.

**Step 3: Add React Query hook**

In `web/src/hooks/use-queries.ts`, after `useBotReviews` (after line 511), add:

```typescript
export function useBotPlans(status?: string) {
  return useQuery({
    queryKey: ["bot-plans", status],
    queryFn: () => bot.plans(status),
  });
}

export function useBotPendingPlans() {
  return useQuery({
    queryKey: ["bot-plans", "pending"],
    queryFn: () => bot.pendingPlans(),
  });
}
```

Add `bot` to the destructured import from `api` if not already present.

**Step 4: Verify build**

Run: `cd /Users/allenqiang/stockagent/web && npm run build 2>&1 | tail -5`

Expected: Build succeeds (or only existing warnings, no new errors)

**Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/hooks/use-queries.ts
git commit -m "feat(bot): add trade plan types, API client, and React Query hooks"
```

---

### Task 10: Frontend Plans Tab

**Files:**
- Modify: `web/src/app/ai/page.tsx`

**Step 1: Add Plans sub-tab to BotTradingPanel**

This task modifies the `BotTradingPanel` component in `web/src/app/ai/page.tsx`. The existing component has sub-tabs **Holdings | Closed**. Add a **Plans** tab between them: **Holdings | Plans | Closed**.

Key changes:
1. Import `useBotPendingPlans` and `useBotPlans` hooks
2. Add `"plans"` to the sub-tab state
3. Add a Plans panel that shows:
   - Pending plans with yellow/amber border (direction arrow, stock code, plan_price, plan_date, quantity)
   - Expandable thinking section
   - Recently executed/expired plans in collapsed grey section

The Plans panel should render each plan as a card:

```tsx
{/* Pending plan card */}
<div className="border border-amber-300 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-700 rounded-lg p-3">
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-2">
      <span className={plan.direction === "buy" ? "text-green-600" : "text-red-600"}>
        {plan.direction === "buy" ? "买入" : "卖出"}
      </span>
      <span className="font-mono font-bold">{plan.stock_code}</span>
      <span className="text-muted-foreground text-sm">{plan.stock_name}</span>
    </div>
    <span className="text-sm text-muted-foreground">{plan.plan_date}</span>
  </div>
  <div className="mt-2 flex gap-4 text-sm">
    <span>目标价: ¥{plan.plan_price.toFixed(2)}</span>
    <span>数量: {plan.quantity}</span>
    {plan.direction === "sell" && <span>比例: {plan.sell_pct}%</span>}
  </div>
</div>
```

For executed/expired plans, use a collapsible section with grey styling and a status badge.

**Step 2: Verify build**

Run: `cd /Users/allenqiang/stockagent/web && npm run build 2>&1 | tail -5`

Expected: Build succeeds

**Step 3: Commit**

```bash
git add web/src/app/ai/page.tsx
git commit -m "feat(bot): add Plans sub-tab to AI Trading panel"
```

---

### Task 11: Smoke test full flow

**Step 1: Start the API server**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && NO_PROXY=localhost,127.0.0.1 uvicorn api.main:app --port 8050 &`

**Step 2: Verify plan endpoints**

Run: `NO_PROXY=localhost,127.0.0.1 curl -s http://localhost:8050/api/bot/plans | python -m json.tool`

Expected: `[]` (empty list, no plans yet)

Run: `NO_PROXY=localhost,127.0.0.1 curl -s http://localhost:8050/api/bot/plans/pending | python -m json.tool`

Expected: `[]`

**Step 3: Verify table exists**

Run: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "
from api.models.base import engine
from sqlalchemy import inspect
insp = inspect(engine)
cols = [c['name'] for c in insp.get_columns('bot_trade_plans')]
print('Columns:', cols)
"`

Expected: Prints all column names from the BotTradePlan table

**Step 4: Stop the server**

Kill the backgrounded uvicorn process.

**Step 5: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(bot): smoke test fixes for trade plan flow"
```
