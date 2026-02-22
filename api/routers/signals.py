"""Signals router — today signals, history, generate, SSE stream."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.services.signal_engine import SignalEngine

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
    return {
        "trade_date": date,
        "generated": len(signals),
        "items": signals,
    }


@router.post("/generate-stream")
def generate_signals_stream(
    date: str = Query("", description="YYYY-MM-DD, default today"),
    db: Session = Depends(get_db),
):
    """Trigger signal generation with SSE progress streaming."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    engine = SignalEngine(db)
    return StreamingResponse(
        engine.generate_signals_stream(date),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
