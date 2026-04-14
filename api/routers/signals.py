"""Signals router — today signals, history, generate, SSE stream."""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/meta")
def get_signal_meta(db: Session = Depends(get_db)):
    """Return metadata about the latest signal generation + schedule info."""
    from api.services.signal_scheduler import get_signal_scheduler

    engine = SignalEngine(db)
    meta = engine.get_signal_meta()

    scheduler = get_signal_scheduler()
    meta["next_run_time"] = scheduler.get_next_run_time()
    meta["refresh_hour"] = scheduler.refresh_hour
    meta["refresh_minute"] = scheduler.refresh_minute

    return meta


@router.get("/today")
def get_today_signals(
    date: str = Query("", description="YYYY-MM-DD, default today"),
    db: Session = Depends(get_db),
):
    """Get signals for today (or a given date).

    If no date is specified and today has no signals yet,
    automatically falls back to the last date that has signals.
    """
    engine = SignalEngine(db)
    explicit_date = bool(date)

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    signals = engine.get_signals_by_date(date)

    # Auto-fallback: if caller didn't specify a date and today is empty,
    # show the most recent date that has signals.
    if not signals and not explicit_date:
        meta = engine.get_signal_meta()
        last_date = meta.get("last_trade_date")
        if last_date and last_date != date:
            date = last_date
            signals = engine.get_signals_by_date(date)

    # Alpha Top 5: buy signals sorted by alpha_score descending
    alpha_top = sorted(
        [s for s in signals if s.get("action") == "buy" and s.get("alpha_score", 0) > 0],
        key=lambda x: x.get("alpha_score", 0),
        reverse=True,
    )[:5]

    return {
        "trade_date": date,
        "total": len(signals),
        "items": signals,
        "alpha_top": alpha_top,
    }


@router.get("/history")
def get_signal_history(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    action: str = Query("", description="Filter by action: buy/sell"),
    date: str = Query("", description="Filter by trade_date YYYY-MM-DD"),
    strategy: str = Query("", description="Filter by strategy name"),
    db: Session = Depends(get_db),
):
    """Get paginated signal history with optional filters."""
    engine = SignalEngine(db)
    items, total = engine.get_signal_history(
        page, size,
        action=action or None,
        trade_date=date or None,
        strategy=strategy or None,
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": items,
    }


@router.post("/generate")
def generate_signals(
    body: dict = None,
    date: str = Query("", description="YYYY-MM-DD, default today"),
    strategy_ids: str = Query("", description="Comma-separated strategy IDs, e.g. 1,3,5"),
    db: Session = Depends(get_db),
):
    """Trigger signal generation for given stocks.

    Accepts optional JSON body with stock_codes list.
    Use strategy_ids query param to limit which strategies are used.
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    stock_codes = None
    if body and isinstance(body, dict):
        stock_codes = body.get("stock_codes")
    elif body and isinstance(body, list):
        stock_codes = body

    sid_list = None
    if strategy_ids:
        sid_list = [int(x.strip()) for x in strategy_ids.split(",") if x.strip().isdigit()]

    engine = SignalEngine(db)
    signals = engine.generate_signals(date, stock_codes, strategy_ids=sid_list)

    # Auto-create trade plans from all buy signals
    plans_created = _create_plans_from_signals(db, date)

    return {
        "trade_date": date,
        "generated": len(signals),
        "plans_created": plans_created,
        "items": signals,
    }


@router.post("/generate-stream")
def generate_signals_stream(
    date: str = Query("", description="YYYY-MM-DD, default today"),
    db: Session = Depends(get_db),
):
    """Trigger signal generation with SSE progress streaming.

    After all signals are generated, automatically creates trade plans
    from buy signals via beta_scorer.
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    engine = SignalEngine(db)

    def _stream_then_create_plans():
        for event_str in engine.generate_signals_stream(date):
            yield event_str
        # After stream completes, create trade plans from signals
        plans_created = _create_plans_from_signals(db, date)
        yield f"data: {json.dumps({'type': 'plans_created', 'count': plans_created})}\n\n"

    return StreamingResponse(
        _stream_then_create_plans(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _create_sell_plans_from_signals(db: Session, trade_date: str, plan_date: str) -> int:
    """Create sell trade plans from sell signals for the given trade_date → plan_date.

    Called by both the route handler and the daily scheduler.
    Returns the number of new sell plans created.
    """
    from datetime import date as _date
    from api.models.signal import TradingSignal
    from api.models.bot_trading import BotPortfolio, BotTradePlan
    from api.models.stock import DailyPrice

    sell_signals = db.query(TradingSignal).filter(
        TradingSignal.trade_date == trade_date,
        TradingSignal.market_regime == "sell",
    ).all()
    sell_codes = {s.stock_code for s in sell_signals}
    sig_reasons_raw: dict[str, str] = {s.stock_code: (s.reasons or "[]") for s in sell_signals}

    if not sell_codes:
        return 0

    price_map = {r.stock_code: float(r.close * (r.adj_factor or 1.0)) for r in db.query(DailyPrice).filter(
        DailyPrice.trade_date == _date.fromisoformat(trade_date),
        DailyPrice.stock_code.in_(sell_codes),
    ).all()}

    holdings = db.query(BotPortfolio).filter(
        BotPortfolio.stock_code.in_(sell_codes)
    ).all()

    sell_created = 0
    for h in holdings:
        price = price_map.get(h.stock_code, h.avg_cost)
        if not price or price <= 0:
            continue
        q = db.query(BotTradePlan).filter(
            BotTradePlan.stock_code == h.stock_code,
            BotTradePlan.direction == "sell",
            BotTradePlan.status == "pending",
        )
        if h.strategy_id:
            q = q.filter(BotTradePlan.strategy_id == h.strategy_id)
        if not q.first():
            reasons_list = json.loads(sig_reasons_raw.get(h.stock_code, "[]")) if sig_reasons_raw else []
            if reasons_list:
                count_part = reasons_list[0] if reasons_list else ""
                cond_parts = "、".join(reasons_list[1:]) if len(reasons_list) > 1 else ""
                thinking = (
                    f"[卖出信号] {count_part} | 触发条件: {cond_parts} | trade_date={trade_date}"
                    if cond_parts else
                    f"[卖出信号] {count_part} | trade_date={trade_date}"
                )
            else:
                thinking = f"[卖出信号] 策略卖出条件触发 | trade_date={trade_date}"
            db.add(BotTradePlan(
                stock_code=h.stock_code,
                stock_name=h.stock_name,
                direction="sell",
                plan_price=price,
                quantity=h.quantity,
                sell_pct=100.0,
                plan_date=plan_date,
                status="pending",
                thinking=thinking,
                source="sell_condition",
                strategy_id=h.strategy_id,
            ))
            sell_created += 1
    db.commit()
    logger.info("Auto-created %d sell plans for %s from sell signals on %s", sell_created, plan_date, trade_date)
    return sell_created


def _create_plans_from_signals(db: Session, trade_date: str) -> int:
    """Create buy + sell trade plans from signals.

    Buy plans: via beta scorer (scored/ranked).
    Sell plans: one per portfolio position whose sell condition triggered.
    """
    from datetime import date as _date
    plan_date_dt = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=1)
    d = _date.fromisoformat(plan_date_dt.strftime("%Y-%m-%d"))
    while d.weekday() >= 5:
        d += timedelta(days=1)
    plan_date = d.isoformat()

    total = 0

    # ── Buy plans via beta scorer ──
    try:
        from api.services.beta_scorer import score_and_create_plans
        plans = score_and_create_plans(db, trade_date, plan_date)
        total += len(plans)
        logger.info("Auto-created %d buy plans for %s from signals on %s", len(plans), plan_date, trade_date)
    except Exception as e:
        logger.error("Buy plan creation failed: %s", e)

    # ── Sell plans from sell signals ──
    try:
        sell_count = _create_sell_plans_from_signals(db, trade_date, plan_date)
        total += sell_count
    except Exception as e:
        logger.error("Sell plan creation failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass

    return total
