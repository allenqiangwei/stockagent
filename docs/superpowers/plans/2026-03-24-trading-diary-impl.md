# Trading Diary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real-time "日记" tab to the /ai page showing do_refresh pipeline progress, trade execution details with reasons, and next-day plans with rationale.

**Architecture:** New `GET /api/bot/diary/{date}` endpoint aggregates data from Job, BotTrade, BotTradePlan, BotPortfolio, TradingSignal, GammaSnapshot tables. Frontend adds "日记" tab with 5-second polling during refresh. No new DB tables.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js + @tanstack/react-query + Tailwind (frontend)

**Spec:** `docs/superpowers/specs/2026-03-24-trading-diary-design.md`

---

### Task 1: Backend Schemas

**Files:**
- Modify: `api/schemas/bot_trading.py` (after line 148)

- [ ] **Step 1: Add diary Pydantic schemas**

Add after the existing `BotStockTimeline` class (line 148):

```python
# ── Trading Diary schemas ──

class DiaryRefreshStep(BaseModel):
    name: str
    status: str  # done|running|pending|failed|skipped
    duration_sec: Optional[float] = None
    detail: str = ""
    progress: Optional[str] = None  # e.g. "2476/5187"
    error: Optional[str] = None

class DiaryRefresh(BaseModel):
    job_id: Optional[int] = None
    status: str  # succeeded|running|failed|not_started
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_sec: Optional[float] = None
    steps: list[DiaryRefreshStep] = []
    error: Optional[str] = None

class DiaryExecutionBuy(BaseModel):
    code: str
    name: str
    price: float
    quantity: int
    amount: float
    plan_price: float = 0
    day_low: Optional[float] = None
    trigger: str = ""
    strategy_name: Optional[str] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    gamma: Optional[float] = None
    combined: Optional[float] = None

class DiaryExecutionSell(BaseModel):
    code: str
    name: str
    price: float
    quantity: int
    amount: float
    reason: str  # take_profit|stop_loss|max_hold|ai_recommend
    reason_label: str  # 止盈|止损|超期|AI
    buy_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_days: Optional[int] = None
    trigger: str = ""

class DiaryExecutionExpired(BaseModel):
    code: str
    name: str
    direction: str
    plan_price: float
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    reason: str
    source: Optional[str] = None

class DiaryExecutionSummary(BaseModel):
    plans_total: int = 0
    executed: int = 0
    expired: int = 0
    buys: int = 0
    sells_tp: int = 0
    sells_sl: int = 0
    sells_mhd: int = 0
    sells_ai: int = 0

class DiaryExecution(BaseModel):
    summary: DiaryExecutionSummary
    buy_list: list[DiaryExecutionBuy] = []
    sell_list: list[DiaryExecutionSell] = []
    expired_list: list[DiaryExecutionExpired] = []

class DiaryPlanBuy(BaseModel):
    code: str
    name: str
    plan_price: Optional[float] = None
    quantity: Optional[int] = None
    strategy_name: Optional[str] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    gamma: Optional[float] = None
    combined: Optional[float] = None
    gamma_daily_mmd: Optional[str] = None
    gamma_weekly_mmd: Optional[str] = None
    source: str = "beta"
    reason: str = ""

class DiaryPlanSell(BaseModel):
    code: str
    name: str
    plan_price: Optional[float] = None
    source: str  # take_profit|stop_loss|max_hold|signal
    source_label: str  # 止盈|止损|超期|信号
    reason: str = ""
    hold_days: Optional[int] = None
    strategy_name: Optional[str] = None

class DiaryPlansSummary(BaseModel):
    buy: int = 0
    sell_tp: int = 0
    sell_sl: int = 0
    sell_mhd: int = 0
    sell_signal: int = 0

class DiaryPlansCreated(BaseModel):
    for_date: str = ""
    summary: DiaryPlansSummary = DiaryPlansSummary()
    buy_list: list[DiaryPlanBuy] = []
    sell_list: list[DiaryPlanSell] = []

class DiarySignals(BaseModel):
    generated: int = 0
    buy_signals: int = 0
    sell_signals: int = 0

class DiaryPortfolioSnapshot(BaseModel):
    total_holdings: int = 0
    total_invested: float = 0
    total_market_value: Optional[float] = None
    daily_pnl: Optional[float] = None
    daily_pnl_pct: Optional[float] = None

class TradingDiary(BaseModel):
    date: str
    is_trading_day: bool = True
    refresh: DiaryRefresh
    execution: DiaryExecution
    portfolio_snapshot: Optional[DiaryPortfolioSnapshot] = None
    signals: DiarySignals
    plans_created: DiaryPlansCreated
```

- [ ] **Step 2: Commit**

```bash
git add api/schemas/bot_trading.py
git commit -m "feat(diary): add Trading Diary Pydantic schemas"
```

---

### Task 2: Diary Service — Core Aggregation

**Files:**
- Create: `api/services/diary_service.py`

- [ ] **Step 1: Create diary service with all builder functions**

```python
"""Trading Diary service — aggregates daily do_refresh and trading data."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from api.models.bot_trading import BotTrade, BotTradePlan, BotPortfolio
from api.models.job import Job
from api.schemas.bot_trading import (
    TradingDiary, DiaryRefresh, DiaryRefreshStep,
    DiaryExecution, DiaryExecutionSummary, DiaryExecutionBuy, DiaryExecutionSell, DiaryExecutionExpired,
    DiarySignals, DiaryPortfolioSnapshot,
    DiaryPlansCreated, DiaryPlansSummary, DiaryPlanBuy, DiaryPlanSell,
)

logger = logging.getLogger(__name__)

# do_refresh progress_pct → step name mapping
_REFRESH_STEPS = [
    (10, "数据完整性检查"),
    (25, "同步日线数据"),
    (50, "执行交易计划"),
    (70, "监控退出条件"),
    (75, "策略池健康检查"),
    (80, "生成交易信号"),
    (85, "Beta每日追踪"),
    (88, "Beta ML训练"),
    (90, "Gamma评分"),
    (92, "Beta评分+计划"),
    (96, "生成卖出计划"),
]

_SELL_REASON_LABELS = {
    "take_profit": "止盈",
    "stop_loss": "止损",
    "max_hold": "超期",
    "ai_recommend": "AI",
    "signal": "信号",
}


def build_diary(db: Session, diary_date: str) -> TradingDiary:
    """Build complete trading diary for a given date."""
    return TradingDiary(
        date=diary_date,
        is_trading_day=_is_trading_day(db, diary_date),
        refresh=_build_refresh(db, diary_date),
        execution=_build_execution(db, diary_date),
        portfolio_snapshot=_build_portfolio_snapshot(db, diary_date),
        signals=_build_signals(db, diary_date),
        plans_created=_build_plans_created(db, diary_date),
    )


def _is_trading_day(db: Session, date_str: str) -> bool:
    """Check if date has any price data (proxy for trading day)."""
    from api.models.daily_price import DailyPrice
    return db.query(DailyPrice.id).filter(DailyPrice.trade_date == date_str).first() is not None


# ── Refresh Pipeline ──

def _build_refresh(db: Session, diary_date: str) -> DiaryRefresh:
    """Reconstruct do_refresh pipeline status from Job table + live scheduler."""
    # Find the data_sync job for this date
    job = (
        db.query(Job)
        .filter(Job.job_type == "data_sync", Job.title.contains(diary_date))
        .order_by(Job.id.desc())
        .first()
    )

    if not job:
        # Check if refresh is currently running for today
        from api.services.signal_scheduler import get_signal_scheduler
        sched = get_signal_scheduler()
        status = sched.get_status()
        if status.get("is_refreshing") and diary_date == datetime.now().strftime("%Y-%m-%d"):
            return _build_refresh_from_live(status)
        return DiaryRefresh(status="not_started")

    # Reconstruct steps from job progress
    steps = _reconstruct_steps(job)

    started = job.started_at.isoformat() if job.started_at else None
    finished = job.finished_at.isoformat() if job.finished_at else None
    duration = None
    if job.started_at and job.finished_at:
        duration = (job.finished_at - job.started_at).total_seconds()

    status = "succeeded" if job.status == "succeeded" else (
        "failed" if job.status == "failed" else (
            "running" if job.status == "running" else "not_started"
        )
    )

    return DiaryRefresh(
        job_id=job.id,
        status=status,
        started_at=started,
        finished_at=finished,
        duration_sec=duration,
        steps=steps,
        error=job.error_message,
    )


def _build_refresh_from_live(status: dict) -> DiaryRefresh:
    """Build refresh info from live scheduler status (currently running)."""
    current_step = status.get("sync_step", "")
    current_done = status.get("sync_done", 0)
    current_total = status.get("sync_total", 0)

    steps = []
    found_current = False
    for _, step_name in _REFRESH_STEPS:
        if not found_current and step_name in current_step:
            progress = f"{current_done}/{current_total}" if current_total > 0 else None
            steps.append(DiaryRefreshStep(
                name=step_name, status="running", detail=current_step,
                progress=progress,
            ))
            found_current = True
        elif found_current:
            steps.append(DiaryRefreshStep(name=step_name, status="pending"))
        else:
            steps.append(DiaryRefreshStep(name=step_name, status="done"))

    # If no step matched, all steps pending (just started)
    if not found_current:
        steps = [DiaryRefreshStep(name=name, status="pending") for _, name in _REFRESH_STEPS]

    return DiaryRefresh(job_id=None, status="running", steps=steps)


def _reconstruct_steps(job: Job) -> list[DiaryRefreshStep]:
    """Reconstruct step list from completed job's progress_pct."""
    steps = []
    job_pct = job.progress_pct or 0
    job_msg = job.progress_message or ""
    is_done = job.status in ("succeeded", "failed")

    for threshold, step_name in _REFRESH_STEPS:
        if is_done:
            # All steps done (or failed at some point)
            steps.append(DiaryRefreshStep(name=step_name, status="done"))
        elif job_pct >= threshold:
            steps.append(DiaryRefreshStep(name=step_name, status="done"))
        elif job_pct > 0 and job_pct < threshold:
            # This is the current step if it's the first one above job_pct
            if not any(s.status == "running" for s in steps):
                progress = None
                if step_name in job_msg:
                    # Extract progress from message like "生成交易信号 2476/5187"
                    parts = job_msg.split()
                    for p in parts:
                        if "/" in p and p.replace("/", "").isdigit():
                            progress = p
                            break
                steps.append(DiaryRefreshStep(
                    name=step_name, status="running", detail=job_msg, progress=progress,
                ))
            else:
                steps.append(DiaryRefreshStep(name=step_name, status="pending"))
        else:
            steps.append(DiaryRefreshStep(name=step_name, status="pending"))

    if job.status == "failed" and steps:
        # Mark last done step as failed
        for i in range(len(steps) - 1, -1, -1):
            if steps[i].status == "done":
                steps[i].status = "failed"
                steps[i].error = job.error_message
                break

    return steps


# ── Trade Execution ──

def _build_execution(db: Session, diary_date: str) -> DiaryExecution:
    """Build trade execution summary and lists for the diary date."""
    from api.models.daily_price import DailyPrice

    # All trades on this date
    trades = db.query(BotTrade).filter(BotTrade.trade_date == diary_date).all()

    # All plans for this date (executed + expired)
    plans = db.query(BotTradePlan).filter(BotTradePlan.plan_date == diary_date).all()

    # Price data for trigger info
    stock_codes = list({t.stock_code for t in trades} | {p.stock_code for p in plans})
    prices = {}
    if stock_codes:
        for dp in db.query(DailyPrice).filter(
            DailyPrice.stock_code.in_(stock_codes), DailyPrice.trade_date == diary_date
        ).all():
            prices[dp.stock_code] = dp

    # Build plan lookup: (stock_code, strategy_id) → plan
    executed_plans = {(p.stock_code, p.strategy_id): p for p in plans if p.status == "executed"}

    # Build buy list
    buy_list = []
    for t in trades:
        if t.action != "buy":
            continue
        plan = executed_plans.get((t.stock_code, t.strategy_id))
        dp = prices.get(t.stock_code)
        trigger = ""
        plan_price = 0
        if plan and dp:
            plan_price = plan.plan_price or 0
            trigger = f"日低{dp.low}≤计划价{plan_price}" if dp else ""

        # Get strategy name from plan thinking
        strategy_name = None
        if plan and plan.thinking:
            thinking = plan.thinking
            for prefix in ["[Gamma] ", "[Beta] "]:
                if thinking.startswith(prefix):
                    name_part = thinking[len(prefix):].split(" alpha=")[0].strip()
                    while name_part.startswith("[") and "] " in name_part:
                        name_part = name_part.split("] ", 1)[1]
                    strategy_name = name_part[:60]
                    break

        buy_list.append(DiaryExecutionBuy(
            code=t.stock_code, name=t.stock_name or "", price=t.price, quantity=t.quantity,
            amount=t.amount or t.price * t.quantity, plan_price=plan_price,
            day_low=float(dp.low) if dp else None,
            trigger=trigger, strategy_name=strategy_name,
            alpha=plan.alpha_score if plan else None,
            beta=plan.beta_score if plan else None,
            gamma=plan.gamma_score if plan else None,
            combined=plan.combined_score if plan else None,
        ))

    # Build sell list
    sell_list = []
    for t in trades:
        if t.action not in ("sell", "reduce"):
            continue
        reason = t.sell_reason or "ai_recommend"
        # Try to find buy price from portfolio or plan
        buy_price = None
        pnl = None
        pnl_pct = None
        hold_days = None
        plan = executed_plans.get((t.stock_code, t.strategy_id))
        dp = prices.get(t.stock_code)
        trigger = ""

        if plan:
            trigger = f"日高{dp.high}≥目标{plan.plan_price}" if dp and plan.plan_price else ""

        sell_list.append(DiaryExecutionSell(
            code=t.stock_code, name=t.stock_name or "", price=t.price, quantity=t.quantity,
            amount=t.amount or t.price * t.quantity,
            reason=reason, reason_label=_SELL_REASON_LABELS.get(reason, reason),
            buy_price=buy_price, pnl=pnl, pnl_pct=pnl_pct, hold_days=hold_days,
            trigger=trigger,
        ))

    # Build expired list
    expired_list = []
    for p in plans:
        if p.status != "expired":
            continue
        dp = prices.get(p.stock_code)
        reason = ""
        if dp:
            if p.direction == "buy":
                reason = f"日低{dp.low}>计划价{p.plan_price}, 未触及"
            else:
                if dp.high and p.plan_price:
                    gap = round((p.plan_price - float(dp.high)) / p.plan_price * 100, 1)
                    reason = f"日高{dp.high}<目标{p.plan_price}, 差{gap}%"
        else:
            reason = "无当日行情数据"

        expired_list.append(DiaryExecutionExpired(
            code=p.stock_code, name=p.stock_name or "", direction=p.direction,
            plan_price=p.plan_price or 0,
            day_high=float(dp.high) if dp else None,
            day_low=float(dp.low) if dp else None,
            reason=reason, source=getattr(p, "source", None),
        ))

    # Summary counts
    sells_by_reason = defaultdict(int)
    for s in sell_list:
        sells_by_reason[s.reason] += 1

    summary = DiaryExecutionSummary(
        plans_total=len(plans),
        executed=len([p for p in plans if p.status == "executed"]),
        expired=len([p for p in plans if p.status == "expired"]),
        buys=len(buy_list),
        sells_tp=sells_by_reason.get("take_profit", 0),
        sells_sl=sells_by_reason.get("stop_loss", 0),
        sells_mhd=sells_by_reason.get("max_hold", 0),
        sells_ai=sells_by_reason.get("ai_recommend", 0),
    )

    return DiaryExecution(
        summary=summary,
        buy_list=sorted(buy_list, key=lambda x: -(x.combined or 0)),
        sell_list=sell_list,
        expired_list=expired_list,
    )


# ── Signals ──

def _build_signals(db: Session, diary_date: str) -> DiarySignals:
    """Count trading signals generated on this date."""
    try:
        from api.models.signal import TradingSignal
        total = db.query(TradingSignal).filter(TradingSignal.trade_date == diary_date).count()
        buys = db.query(TradingSignal).filter(
            TradingSignal.trade_date == diary_date, TradingSignal.market_regime == "buy"
        ).count()
        return DiarySignals(generated=total, buy_signals=buys, sell_signals=total - buys)
    except Exception:
        return DiarySignals()


# ── Portfolio Snapshot ──

def _build_portfolio_snapshot(db: Session, diary_date: str) -> DiaryPortfolioSnapshot | None:
    """Build portfolio snapshot — only for today (BotPortfolio is mutable)."""
    today = datetime.now().strftime("%Y-%m-%d")
    if diary_date != today:
        return None  # Historical portfolio not available without snapshot table

    holdings = db.query(BotPortfolio).filter(BotPortfolio.quantity > 0).all()
    total_invested = sum(h.total_invested or 0 for h in holdings)

    return DiaryPortfolioSnapshot(
        total_holdings=len(holdings),
        total_invested=total_invested,
    )


# ── Plans Created (for next day) ──

def _build_plans_created(db: Session, diary_date: str) -> DiaryPlansCreated:
    """Build next-day plans that were created during this diary date's refresh."""
    from api.services.bot_trading_engine import _get_next_trading_day

    next_date = _get_next_trading_day(db, diary_date)
    if not next_date:
        return DiaryPlansCreated()

    plans = db.query(BotTradePlan).filter(BotTradePlan.plan_date == next_date).all()

    # Build gamma cache for buy plan reasons
    gamma_cache = {}
    try:
        from api.models.gamma_factor import GammaSnapshot
        buy_codes = [p.stock_code for p in plans if p.direction == "buy"]
        if buy_codes:
            snaps = db.query(GammaSnapshot).filter(
                GammaSnapshot.stock_code.in_(buy_codes),
                GammaSnapshot.snapshot_date == diary_date,
            ).all()
            for s in snaps:
                gamma_cache[s.stock_code] = {
                    "daily_mmd": f"{s.daily_mmd_type}:{s.daily_mmd_level}" if s.daily_mmd_type else None,
                    "weekly_mmd": f"{s.weekly_mmd_type}:{s.weekly_mmd_level}" if s.weekly_mmd_type else None,
                    "daily_strength": s.daily_strength,
                }
    except Exception:
        pass

    # Strategy cache for buy conditions
    strategy_cache = {}
    try:
        from api.models.strategy import Strategy
        strategy_ids = [p.strategy_id for p in plans if p.strategy_id]
        if strategy_ids:
            for s in db.query(Strategy).filter(Strategy.id.in_(strategy_ids)).all():
                strategy_cache[s.id] = s
    except Exception:
        pass

    buy_list = []
    sell_tp = sell_sl = sell_mhd = sell_signal = 0
    sell_list = []

    for p in plans:
        if p.direction == "buy":
            reason = _generate_buy_reason(p, gamma_cache, strategy_cache)
            # Extract strategy name from thinking
            strategy_name = None
            if p.thinking:
                for prefix in ["[Gamma] ", "[Beta] "]:
                    if p.thinking.startswith(prefix):
                        name_part = p.thinking[len(prefix):].split(" alpha=")[0].strip()
                        while name_part.startswith("[") and "] " in name_part:
                            name_part = name_part.split("] ", 1)[1]
                        strategy_name = name_part[:60]
                        break

            gamma = gamma_cache.get(p.stock_code, {})
            buy_list.append(DiaryPlanBuy(
                code=p.stock_code, name=p.stock_name or "",
                plan_price=p.plan_price, quantity=p.quantity,
                strategy_name=strategy_name,
                alpha=p.alpha_score, beta=p.beta_score,
                gamma=p.gamma_score, combined=p.combined_score,
                gamma_daily_mmd=gamma.get("daily_mmd"),
                gamma_weekly_mmd=gamma.get("weekly_mmd"),
                source=getattr(p, "source", "beta") or "beta",
                reason=reason,
            ))
        else:
            source = getattr(p, "source", "signal") or "signal"
            label = _SELL_REASON_LABELS.get(source, source)
            reason = _generate_sell_reason(p, source)

            if source == "take_profit": sell_tp += 1
            elif source == "stop_loss": sell_sl += 1
            elif source == "max_hold": sell_mhd += 1
            else: sell_signal += 1

            sell_list.append(DiaryPlanSell(
                code=p.stock_code, name=p.stock_name or "",
                plan_price=p.plan_price, source=source, source_label=label,
                reason=reason, strategy_name=None,
            ))

    return DiaryPlansCreated(
        for_date=next_date,
        summary=DiaryPlansSummary(
            buy=len(buy_list), sell_tp=sell_tp, sell_sl=sell_sl,
            sell_mhd=sell_mhd, sell_signal=sell_signal,
        ),
        buy_list=sorted(buy_list, key=lambda x: -(x.combined or 0)),
        sell_list=sell_list,
    )


def _generate_buy_reason(plan, gamma_cache: dict, strategy_cache: dict) -> str:
    """Generate human-readable buy reason from gamma + strategy conditions."""
    parts = []
    gamma = gamma_cache.get(plan.stock_code, {})

    # Gamma info
    if gamma.get("daily_mmd"):
        parts.append(f"日线{gamma['daily_mmd']}买点")
    if gamma.get("weekly_mmd"):
        parts.append(f"周线{gamma['weekly_mmd']}共振")

    # Strategy conditions summary
    strat = strategy_cache.get(plan.strategy_id) if plan.strategy_id else None
    if strat and strat.buy_conditions:
        for c in strat.buy_conditions:
            field = c.get("field", "")
            ct = c.get("compare_type", "")
            if "RSI" in field and ct == "value":
                op = c.get("operator", "")
                val = c.get("compare_value")
                if op == ">" and val is not None:
                    parts.append(f"RSI>{val}")
                elif op == "<" and val is not None:
                    parts.append(f"RSI<{val}")
            elif "ATR" in field and c.get("operator") == "<" and ct == "value":
                parts.append(f"ATR<{c.get('compare_value')}")

    # Alpha score
    if plan.alpha_score and plan.alpha_score >= 90:
        parts.append(f"Alpha {plan.alpha_score}")

    return ", ".join(parts[:5]) if parts else "Beta评分推荐"


def _generate_sell_reason(plan, source: str) -> str:
    """Generate human-readable sell reason."""
    if source == "take_profit":
        return f"止盈挂单: 目标价¥{plan.plan_price}"
    elif source == "stop_loss":
        return f"止损挂单: 防亏价¥{plan.plan_price}"
    elif source == "max_hold":
        return "到期卖出: 持有已达MHD上限"
    else:
        return f"信号卖出: 卖出信号触发"
```

- [ ] **Step 2: Commit**

```bash
git add api/services/diary_service.py
git commit -m "feat(diary): add diary aggregation service"
```

---

### Task 3: Backend Endpoint

**Files:**
- Modify: `api/routers/bot_trading.py` (after line 565)

- [ ] **Step 1: Add diary endpoint**

Add after the last endpoint (`/summary`):

```python
@router.get("/diary/{diary_date}")
def get_diary(diary_date: str, db: Session = Depends(get_db)):
    """Get complete trading diary for a specific date."""
    from api.services.diary_service import build_diary
    return build_diary(db, diary_date)
```

- [ ] **Step 2: Verify endpoint works**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s 'http://127.0.0.1:8050/api/bot/diary/2026-03-24' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'date={d[\"date\"]} refresh={d[\"refresh\"][\"status\"]}')
print(f'execution: {d[\"execution\"][\"summary\"]}')
print(f'signals: {d[\"signals\"]}')
print(f'plans: {d[\"plans_created\"][\"summary\"]}')
"
```

- [ ] **Step 3: Commit**

```bash
git add api/routers/bot_trading.py
git commit -m "feat(diary): add GET /api/bot/diary/{date} endpoint"
```

---

### Task 4: Frontend Types + API

**Files:**
- Modify: `web/src/types/index.ts` (after line 757)
- Modify: `web/src/lib/api.ts` (add to bot object)
- Modify: `web/src/hooks/use-queries.ts` (add useDiary hook)

- [ ] **Step 1: Add TypeScript interfaces**

Add after `BotTradePlanItem` (line 757) in `web/src/types/index.ts`:

```typescript
// ── Trading Diary ──
export interface DiaryRefreshStep {
  name: string;
  status: "done" | "running" | "pending" | "failed" | "skipped";
  duration_sec: number | null;
  detail: string;
  progress: string | null;
  error: string | null;
}

export interface DiaryRefresh {
  job_id: number | null;
  status: "succeeded" | "running" | "failed" | "not_started";
  started_at: string | null;
  finished_at: string | null;
  duration_sec: number | null;
  steps: DiaryRefreshStep[];
  error: string | null;
}

export interface DiaryExecutionBuy {
  code: string;
  name: string;
  price: number;
  quantity: number;
  amount: number;
  plan_price: number;
  day_low: number | null;
  trigger: string;
  strategy_name: string | null;
  alpha: number | null;
  beta: number | null;
  gamma: number | null;
  combined: number | null;
}

export interface DiaryExecutionSell {
  code: string;
  name: string;
  price: number;
  quantity: number;
  amount: number;
  reason: string;
  reason_label: string;
  buy_price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  hold_days: number | null;
  trigger: string;
}

export interface DiaryExecutionExpired {
  code: string;
  name: string;
  direction: string;
  plan_price: number;
  day_high: number | null;
  day_low: number | null;
  reason: string;
  source: string | null;
}

export interface DiaryExecution {
  summary: {
    plans_total: number;
    executed: number;
    expired: number;
    buys: number;
    sells_tp: number;
    sells_sl: number;
    sells_mhd: number;
    sells_ai: number;
  };
  buy_list: DiaryExecutionBuy[];
  sell_list: DiaryExecutionSell[];
  expired_list: DiaryExecutionExpired[];
}

export interface DiaryPlanBuy {
  code: string;
  name: string;
  plan_price: number | null;
  quantity: number | null;
  strategy_name: string | null;
  alpha: number | null;
  beta: number | null;
  gamma: number | null;
  combined: number | null;
  gamma_daily_mmd: string | null;
  gamma_weekly_mmd: string | null;
  source: string;
  reason: string;
}

export interface DiaryPlanSell {
  code: string;
  name: string;
  plan_price: number | null;
  source: string;
  source_label: string;
  reason: string;
  hold_days: number | null;
  strategy_name: string | null;
}

export interface DiaryPlansCreated {
  for_date: string;
  summary: {
    buy: number;
    sell_tp: number;
    sell_sl: number;
    sell_mhd: number;
    sell_signal: number;
  };
  buy_list: DiaryPlanBuy[];
  sell_list: DiaryPlanSell[];
}

export interface DiarySignals {
  generated: number;
  buy_signals: number;
  sell_signals: number;
}

export interface DiaryPortfolioSnapshot {
  total_holdings: number;
  total_invested: number;
  total_market_value: number | null;
  daily_pnl: number | null;
  daily_pnl_pct: number | null;
}

export interface TradingDiary {
  date: string;
  is_trading_day: boolean;
  refresh: DiaryRefresh;
  execution: DiaryExecution;
  portfolio_snapshot: DiaryPortfolioSnapshot | null;
  signals: DiarySignals;
  plans_created: DiaryPlansCreated;
}
```

- [ ] **Step 2: Add API method to bot object**

In `web/src/lib/api.ts`, add to the `bot` object (after `pendingPlans`):

```typescript
    diary: (date: string) => request<TradingDiary>(`/bot/diary/${date}`),
```

Add `TradingDiary` to the imports from `@/types`.

- [ ] **Step 3: Add useDiary hook**

In `web/src/hooks/use-queries.ts`, add after the bot trading hooks:

```typescript
export function useDiary(date: string) {
  return useQuery({
    queryKey: ["diary", date],
    queryFn: () => bot.diary(date),
    enabled: !!date,
    refetchInterval: (query) => {
      const status = query.state.data?.refresh?.status;
      return status === "running" ? 5000 : false;
    },
  });
}
```

Add `bot` to imports if not already imported, and add `TradingDiary` to type imports.

- [ ] **Step 4: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/hooks/use-queries.ts
git commit -m "feat(diary): add frontend types, API method, and useDiary hook"
```

---

### Task 5: Frontend — 日记 Tab UI

**Files:**
- Modify: `web/src/app/ai/page.tsx`

- [ ] **Step 1: Add "diary" to subTab type and tab bar**

Change the subTab state type (line 597):
```typescript
const [subTab, setSubTab] = useState<"holding" | "plans" | "closed" | "diary">("holding");
```

Change the tab array (line 693) to include "diary":
```typescript
{(["holding", "plans", "closed", "diary"] as const).map(tab => (
```

Add the label for "diary" in the tab button text:
```typescript
tab === "diary" ? "日记" :
```

- [ ] **Step 2: Add diary date state and data hook**

Add near the other state variables (around line 600):
```typescript
const [diaryDate, setDiaryDate] = useState(() => new Date().toISOString().slice(0, 10));
const { data: diary } = useDiary(subTab === "diary" ? diaryDate : "");
```

Add import for `useDiary` from `@/hooks/use-queries`.

- [ ] **Step 3: Add diary tab content**

Add after the `{subTab === "closed" && (...)}` block (around line 1160):

```tsx
{subTab === "diary" && (
  <div className="space-y-4">
    {/* Date picker */}
    <div className="flex items-center gap-2">
      <button onClick={() => {
        const d = new Date(diaryDate);
        d.setDate(d.getDate() - 1);
        setDiaryDate(d.toISOString().slice(0, 10));
      }} className="px-2 py-1 rounded hover:bg-muted">&lt;</button>
      <input type="date" value={diaryDate} onChange={e => setDiaryDate(e.target.value)}
        className="bg-background border border-border rounded px-2 py-1 text-sm" />
      <button onClick={() => {
        const d = new Date(diaryDate);
        d.setDate(d.getDate() + 1);
        setDiaryDate(d.toISOString().slice(0, 10));
      }} className="px-2 py-1 rounded hover:bg-muted">&gt;</button>
      <button onClick={() => setDiaryDate(new Date().toISOString().slice(0, 10))}
        className="text-xs text-muted-foreground hover:text-foreground">今天</button>
    </div>

    {!diary ? (
      <div className="text-center text-muted-foreground py-8">加载中...</div>
    ) : (
      <>
        {/* Refresh pipeline */}
        <div className="border border-border rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Do-Refresh 流程</span>
            <span className={`text-xs px-2 py-0.5 rounded ${
              diary.refresh.status === "succeeded" ? "bg-green-500/10 text-green-500" :
              diary.refresh.status === "running" ? "bg-blue-500/10 text-blue-500" :
              diary.refresh.status === "failed" ? "bg-red-500/10 text-red-500" :
              "bg-muted text-muted-foreground"
            }`}>
              {diary.refresh.status === "succeeded" ? "已完成" :
               diary.refresh.status === "running" ? "进行中" :
               diary.refresh.status === "failed" ? "失败" : "未开始"}
            </span>
          </div>
          {diary.refresh.duration_sec != null && (
            <div className="text-[10px] text-muted-foreground mb-2">
              耗时: {Math.round(diary.refresh.duration_sec / 60)}分钟
            </div>
          )}
          <div className="space-y-1">
            {diary.refresh.steps.map((step, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="w-4 text-center">
                  {step.status === "done" ? "✅" :
                   step.status === "running" ? "🔄" :
                   step.status === "failed" ? "❌" : "⏳"}
                </span>
                <span className={`flex-1 ${step.status === "pending" ? "text-muted-foreground" : ""}`}>
                  {step.name}
                </span>
                {step.progress && (
                  <span className="text-muted-foreground font-mono">{step.progress}</span>
                )}
                {step.detail && step.status === "done" && (
                  <span className="text-muted-foreground">{step.detail}</span>
                )}
                {step.error && (
                  <span className="text-red-500 truncate max-w-[200px]" title={step.error}>{step.error}</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Execution summary */}
        <div className="border border-border rounded-lg p-3">
          <div className="text-sm font-medium mb-2">今日交易执行</div>
          <div className="flex gap-3 text-xs mb-3">
            <span className="px-2 py-1 rounded bg-emerald-500/10 text-emerald-500">买入 {diary.execution.summary.buys}</span>
            <span className="px-2 py-1 rounded bg-green-500/10 text-green-500">止盈 {diary.execution.summary.sells_tp}</span>
            <span className="px-2 py-1 rounded bg-red-500/10 text-red-500">止损 {diary.execution.summary.sells_sl}</span>
            <span className="px-2 py-1 rounded bg-muted text-muted-foreground">过期 {diary.execution.summary.expired}</span>
          </div>

          {/* Buy list */}
          {diary.execution.buy_list.length > 0 && (
            <details open={diary.execution.buy_list.length <= 20}>
              <summary className="text-xs text-muted-foreground cursor-pointer mb-1">
                买入明细 ({diary.execution.buy_list.length})
              </summary>
              <div className="space-y-1.5 mt-1">
                {diary.execution.buy_list.map((b, i) => (
                  <div key={i} className="text-xs border-l-2 border-emerald-500 pl-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold">{b.code}</span>
                      <span>{b.name}</span>
                      <span className="text-muted-foreground">¥{b.price}×{b.quantity}</span>
                      {b.combined != null && <span className="text-emerald-500 font-medium">{b.combined.toFixed(2)}</span>}
                    </div>
                    <div className="text-muted-foreground text-[10px]">
                      {b.strategy_name && <span>{b.strategy_name.split("_").slice(0, 3).join("_")} </span>}
                      {b.trigger && <span>| {b.trigger} </span>}
                      {b.alpha != null && <span>α{b.alpha.toFixed(0)} </span>}
                      {b.gamma != null && <span>γ{b.gamma.toFixed(1)}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Sell list */}
          {diary.execution.sell_list.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-muted-foreground cursor-pointer mb-1">
                卖出明细 ({diary.execution.sell_list.length})
              </summary>
              <div className="space-y-1.5 mt-1">
                {diary.execution.sell_list.map((s, i) => (
                  <div key={i} className="text-xs border-l-2 border-red-500 pl-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold">{s.code}</span>
                      <span>{s.name}</span>
                      <span className="text-muted-foreground">¥{s.price}×{s.quantity}</span>
                      <span className={`px-1 py-0.5 rounded text-[10px] ${
                        s.reason === "take_profit" ? "bg-green-500/10 text-green-500" :
                        s.reason === "stop_loss" ? "bg-red-500/10 text-red-500" :
                        "bg-muted text-muted-foreground"
                      }`}>{s.reason_label}</span>
                    </div>
                    {s.trigger && <div className="text-[10px] text-muted-foreground">{s.trigger}</div>}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Expired list */}
          {diary.execution.expired_list.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-muted-foreground cursor-pointer mb-1">
                过期未触发 ({diary.execution.expired_list.length})
              </summary>
              <div className="space-y-1 mt-1">
                {diary.execution.expired_list.slice(0, 50).map((e, i) => (
                  <div key={i} className="text-[10px] text-muted-foreground flex gap-2">
                    <span className="font-mono">{e.code}</span>
                    <span>{e.name}</span>
                    <span>{e.reason}</span>
                  </div>
                ))}
                {diary.execution.expired_list.length > 50 && (
                  <div className="text-[10px] text-muted-foreground">...还有{diary.execution.expired_list.length - 50}条</div>
                )}
              </div>
            </details>
          )}
        </div>

        {/* Signals + Plans */}
        <div className="border border-border rounded-lg p-3">
          <div className="text-sm font-medium mb-2">
            信号 & 明日计划 ({diary.plans_created.for_date})
          </div>
          <div className="flex gap-3 text-xs mb-3">
            <span>信号: {diary.signals.generated} (买{diary.signals.buy_signals} 卖{diary.signals.sell_signals})</span>
            <span>|</span>
            <span>明日: {diary.plans_created.summary.buy}买 + {diary.plans_created.summary.sell_tp + diary.plans_created.summary.sell_sl + diary.plans_created.summary.sell_mhd + diary.plans_created.summary.sell_signal}卖</span>
          </div>

          {/* Buy plans */}
          {diary.plans_created.buy_list.length > 0 && (
            <details open>
              <summary className="text-xs text-muted-foreground cursor-pointer mb-1">
                买入计划 ({diary.plans_created.buy_list.length})
              </summary>
              <div className="space-y-1.5 mt-1">
                {diary.plans_created.buy_list.map((p, i) => (
                  <div key={i} className="text-xs border-l-2 border-emerald-500 pl-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold">{p.code}</span>
                      <span>{p.name}</span>
                      {p.plan_price && <span className="text-muted-foreground">@¥{p.plan_price.toFixed(2)}</span>}
                      {p.combined != null && <span className="text-emerald-500 font-medium">{p.combined.toFixed(2)}</span>}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {p.reason}
                    </div>
                    <div className="text-[10px] flex gap-2">
                      {p.alpha != null && <span>α{p.alpha.toFixed(0)}</span>}
                      {p.gamma != null && <span>γ{p.gamma.toFixed(1)}</span>}
                      {p.gamma_daily_mmd && (
                        <span className="px-1 py-0.5 rounded bg-violet-500/10 text-violet-500">
                          日{p.gamma_daily_mmd}
                        </span>
                      )}
                      {p.gamma_weekly_mmd && (
                        <span className="px-1 py-0.5 rounded bg-blue-500/10 text-blue-500">
                          周{p.gamma_weekly_mmd}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Sell plans */}
          {(diary.plans_created.summary.sell_tp + diary.plans_created.summary.sell_sl + diary.plans_created.summary.sell_mhd + diary.plans_created.summary.sell_signal) > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-muted-foreground cursor-pointer mb-1">
                卖出计划 ({diary.plans_created.sell_list.length})
              </summary>
              <div className="space-y-1 mt-1">
                {diary.plans_created.sell_list.slice(0, 50).map((s, i) => (
                  <div key={i} className="text-[10px] text-muted-foreground flex gap-2">
                    <span className="font-mono">{s.code}</span>
                    <span>{s.name}</span>
                    <span className={`px-1 py-0.5 rounded ${
                      s.source === "take_profit" ? "bg-green-500/10 text-green-500" :
                      s.source === "stop_loss" ? "bg-red-500/10 text-red-500" :
                      s.source === "max_hold" ? "bg-amber-500/10 text-amber-500" :
                      "bg-muted"
                    }`}>{s.source_label}</span>
                    <span>{s.reason}</span>
                  </div>
                ))}
                {diary.plans_created.sell_list.length > 50 && (
                  <div className="text-[10px] text-muted-foreground">...还有{diary.plans_created.sell_list.length - 50}条</div>
                )}
              </div>
            </details>
          )}
        </div>

        {/* Portfolio snapshot */}
        {diary.portfolio_snapshot && (
          <div className="border border-border rounded-lg p-3">
            <div className="text-sm font-medium mb-1">持仓快照</div>
            <div className="flex gap-4 text-xs text-muted-foreground">
              <span>持仓 <span className="text-foreground font-medium">{diary.portfolio_snapshot.total_holdings}</span> 只</span>
              <span>投入 <span className="text-foreground font-medium">¥{(diary.portfolio_snapshot.total_invested / 10000).toFixed(0)}万</span></span>
            </div>
          </div>
        )}
      </>
    )}
  </div>
)}
```

- [ ] **Step 4: Commit**

```bash
git add web/src/app/ai/page.tsx
git commit -m "feat(diary): add 日记 tab with full diary UI"
```

---

### Task 6: Restart & Verify

- [ ] **Step 1: Restart backend**

```bash
kill $(lsof -t -i :8050) 2>/dev/null; sleep 2
cd /Users/allenqiang/stockagent && NO_PROXY=localhost,127.0.0.1 SKIP_ORPHAN_RECOVERY=1 PYTHONUNBUFFERED=1 nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/uvicorn_fresh.log 2>&1 &
sleep 15
```

- [ ] **Step 2: Test diary API**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s 'http://127.0.0.1:8050/api/bot/diary/2026-03-24' | python3 -m json.tool | head -30
```

- [ ] **Step 3: Restart frontend**

```bash
kill $(lsof -t -i :3050) 2>/dev/null; sleep 2
cd /Users/allenqiang/stockagent/web && NO_PROXY=localhost,127.0.0.1 nohup npm run dev -- -H 0.0.0.0 -p 3050 > /tmp/stockagent_web.log 2>&1 &
sleep 12
```

- [ ] **Step 4: Verify in browser**

Open http://192.168.7.125:3050/ai, click "日记" tab. Verify:
- Date picker works (prev/next/today)
- Refresh pipeline shows steps with status icons
- Execution lists show buy/sell/expired details
- Plans section shows next-day plans with reasons

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(diary): complete trading diary feature (backend + frontend)"
```
