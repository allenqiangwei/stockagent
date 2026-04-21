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
    "sell_condition": "信号",
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
    from api.models.stock import DailyPrice
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
    from api.models.stock import DailyPrice

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
        sells_signal=sells_by_reason.get("sell_condition", 0),
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
        return "信号卖出: 卖出信号触发"
