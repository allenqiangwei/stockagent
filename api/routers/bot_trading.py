"""Bot Trading router — simulated portfolio, trades, and reviews."""

import json as _json

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview, BotTradePlan
from api.models.stock import DailyPrice
from api.schemas.bot_trading import (
    BotPortfolioItem, BotTradeItem, BotTradeReviewItem,
    BotSummary, BotStockTimeline, BotTradePlanItem,
)

router = APIRouter(prefix="/api/bot", tags=["bot-trading"])


def _parse_exit_config(val) -> dict | None:
    """Safely parse exit_config which may be dict, JSON string, or None."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return _json.loads(val)
        except (_json.JSONDecodeError, ValueError):
            return None
    return None


def _latest_close(db: Session, code: str) -> tuple[float | None, float | None]:
    """Get latest close price and change_pct for a stock."""
    rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code == code)
        .order_by(DailyPrice.trade_date.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return None, None
    close = float(rows[0].close)
    change_pct = None
    if len(rows) >= 2:
        prev = float(rows[1].close)
        if prev > 0:
            change_pct = round((close - prev) / prev * 100, 2)
    return close, change_pct


@router.get("/portfolio", response_model=list[BotPortfolioItem])
def get_bot_portfolio(db: Session = Depends(get_db)):
    """List all bot portfolio holdings with current price and P&L."""
    holdings = db.query(BotPortfolio).order_by(BotPortfolio.first_buy_date.desc()).all()
    from datetime import date as _date

    result = []
    for h in holdings:
        close, change_pct = _latest_close(db, h.stock_code)
        pnl = None
        pnl_pct = None
        market_value = None
        if close is not None and h.quantity > 0:
            market_value = round(close * h.quantity, 2)
            pnl = round((close - h.avg_cost) * h.quantity, 2)
            if h.avg_cost > 0:
                pnl_pct = round((close - h.avg_cost) / h.avg_cost * 100, 2)

        # Compute exit monitoring derived fields
        hold_days = None
        sl_price = None
        tp_price = None
        days_remaining = None
        ec = _parse_exit_config(h.exit_config)
        if ec and h.buy_price:
            sl_pct = ec.get("stop_loss_pct", 0)
            tp_pct = ec.get("take_profit_pct", 0)
            mhd = ec.get("max_hold_days", 0)
            if sl_pct:
                sl_price = round(h.buy_price * (1 + sl_pct / 100), 2)
            if tp_pct:
                tp_price = round(h.buy_price * (1 + tp_pct / 100), 2)
            if h.buy_date:
                try:
                    hd = (_date.today() - _date.fromisoformat(h.buy_date)).days
                    hold_days = hd
                    if mhd:
                        days_remaining = max(0, mhd - hd)
                except ValueError:
                    pass

        result.append(BotPortfolioItem(
            id=h.id,
            stock_code=h.stock_code,
            stock_name=h.stock_name,
            quantity=h.quantity,
            avg_cost=h.avg_cost,
            total_invested=h.total_invested,
            first_buy_date=h.first_buy_date,
            close=close,
            change_pct=change_pct,
            pnl=pnl,
            pnl_pct=pnl_pct,
            market_value=market_value,
            strategy_id=h.strategy_id,
            strategy_name=h.strategy_name,
            exit_config=h.exit_config,
            buy_price=h.buy_price,
            buy_date=h.buy_date,
            hold_days=hold_days,
            sl_price=sl_price,
            tp_price=tp_price,
            days_remaining=days_remaining,
        ))
    return result


@router.get("/trades", response_model=list[BotTradeItem])
def list_trades(
    stock_code: str = Query("", description="Filter by stock code"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List bot trades, optionally filtered by stock."""
    q = db.query(BotTrade)
    if stock_code:
        q = q.filter(BotTrade.stock_code == stock_code)
    rows = q.order_by(BotTrade.trade_date.desc(), BotTrade.id.desc()).limit(limit).all()
    return [
        BotTradeItem(
            id=t.id,
            stock_code=t.stock_code,
            stock_name=t.stock_name,
            action=t.action,
            quantity=t.quantity,
            price=t.price,
            amount=t.amount,
            thinking=t.thinking,
            report_id=t.report_id,
            trade_date=t.trade_date,
            created_at=t.created_at.isoformat() if t.created_at else "",
            sell_reason=t.sell_reason,
        )
        for t in rows
    ]


@router.get("/trades/{stock_code}/timeline", response_model=BotStockTimeline)
def get_stock_timeline(stock_code: str, db: Session = Depends(get_db)):
    """Get full trade timeline for a single stock (all trades + review if exists)."""
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.stock_code == stock_code)
        .order_by(BotTrade.trade_date, BotTrade.id)
        .all()
    )
    if not trades:
        raise HTTPException(404, f"No trades found for {stock_code}")

    # Sum all sub-positions for this stock (virtual books may have multiple rows)
    holdings = db.query(BotPortfolio).filter(BotPortfolio.stock_code == stock_code).all()
    total_quantity = sum(h.quantity for h in holdings)
    review = (
        db.query(BotTradeReview)
        .filter(BotTradeReview.stock_code == stock_code)
        .order_by(BotTradeReview.created_at.desc())
        .first()
    )

    buy_amount = sum(t.amount for t in trades if t.action == "buy")
    sell_amount = sum(t.amount for t in trades if t.action in ("sell", "reduce"))

    status = "holding" if total_quantity > 0 else "closed"
    pnl = sell_amount - buy_amount if status == "closed" else 0.0
    pnl_pct = (pnl / buy_amount * 100) if buy_amount > 0 and status == "closed" else 0.0

    first_buy = next((t for t in trades if t.action == "buy"), None)
    last_trade = trades[-1] if trades else None

    close, _ = _latest_close(db, stock_code) if total_quantity > 0 else (None, None)

    return BotStockTimeline(
        stock_code=stock_code,
        stock_name=trades[0].stock_name if trades else "",
        status=status,
        total_buy_amount=buy_amount,
        total_sell_amount=sell_amount,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        first_buy_date=first_buy.trade_date if first_buy else "",
        last_trade_date=last_trade.trade_date if last_trade else "",
        holding_days=0,
        current_quantity=total_quantity,
        current_price=close,
        current_market_value=round(close * total_quantity, 2) if close and total_quantity else None,
        trades=[
            BotTradeItem(
                id=t.id, stock_code=t.stock_code, stock_name=t.stock_name,
                action=t.action, quantity=t.quantity, price=t.price,
                amount=t.amount, thinking=t.thinking, report_id=t.report_id,
                trade_date=t.trade_date,
                created_at=t.created_at.isoformat() if t.created_at else "",
                sell_reason=t.sell_reason,
            )
            for t in trades
        ],
        review=BotTradeReviewItem(
            id=review.id, stock_code=review.stock_code, stock_name=review.stock_name,
            total_buy_amount=review.total_buy_amount, total_sell_amount=review.total_sell_amount,
            pnl=review.pnl, pnl_pct=review.pnl_pct,
            first_buy_date=review.first_buy_date, last_sell_date=review.last_sell_date,
            holding_days=review.holding_days, review_thinking=review.review_thinking,
            memory_synced=review.memory_synced, memory_note_id=review.memory_note_id,
            trades=review.trades,
            created_at=review.created_at.isoformat() if review.created_at else "",
        ) if review else None,
    )


@router.get("/reviews", response_model=list[BotTradeReviewItem])
def list_reviews(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List trade reviews (post-mortems)."""
    rows = (
        db.query(BotTradeReview)
        .order_by(BotTradeReview.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        BotTradeReviewItem(
            id=r.id, stock_code=r.stock_code, stock_name=r.stock_name,
            total_buy_amount=r.total_buy_amount, total_sell_amount=r.total_sell_amount,
            pnl=r.pnl, pnl_pct=r.pnl_pct,
            first_buy_date=r.first_buy_date, last_sell_date=r.last_sell_date,
            holding_days=r.holding_days, review_thinking=r.review_thinking,
            memory_synced=r.memory_synced, memory_note_id=r.memory_note_id,
            trades=r.trades,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


def _get_today_prices(db: Session, stock_codes: list[str]) -> dict:
    """Fetch latest OHLCV for a list of stocks. Tries today first, falls back to most recent."""
    if not stock_codes:
        return {}
    from datetime import date as _date
    from sqlalchemy import func
    from api.models.stock import DailyPrice

    today = _date.today()
    # Try today's data first
    rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code.in_(stock_codes), DailyPrice.trade_date == today)
        .all()
    )
    result = {}
    found_codes = set()
    for row in rows:
        if row.close:
            change_pct = ((row.close - row.open) / row.open * 100) if row.open else 0.0
            result[row.stock_code] = {
                "close": round(row.close, 2),
                "change_pct": round(change_pct, 2),
                "high": round(row.high, 2) if row.high else None,
                "low": round(row.low, 2) if row.low else None,
                "is_today": True,
            }
            found_codes.add(row.stock_code)

    # Fallback: fetch most recent close for stocks missing today's data
    missing = [c for c in stock_codes if c not in found_codes]
    if missing:
        # Get the latest trade_date per stock
        latest_sub = (
            db.query(DailyPrice.stock_code, func.max(DailyPrice.trade_date).label("max_date"))
            .filter(DailyPrice.stock_code.in_(missing))
            .group_by(DailyPrice.stock_code)
            .subquery()
        )
        fallback_rows = (
            db.query(DailyPrice)
            .join(latest_sub, (DailyPrice.stock_code == latest_sub.c.stock_code) & (DailyPrice.trade_date == latest_sub.c.max_date))
            .all()
        )
        for row in fallback_rows:
            if row.close:
                change_pct = ((row.close - row.open) / row.open * 100) if row.open else 0.0
                result[row.stock_code] = {
                    "close": round(row.close, 2),
                    "change_pct": round(change_pct, 2),
                    "high": round(row.high, 2) if row.high else None,
                    "low": round(row.low, 2) if row.low else None,
                    "is_today": False,
                    "price_date": row.trade_date.isoformat() if hasattr(row.trade_date, 'isoformat') else str(row.trade_date),
                }

    return result


def _plan_to_item(p, prices: dict, strategy_cache: dict | None = None) -> BotTradePlanItem:
    """Convert ORM plan + price lookup to response item, enriched with strategy details."""
    px = prices.get(p.stock_code, {})

    # Extract phase from thinking field: "[Beta] [AI] strategy alpha=... phase=cold"
    phase = None
    strategy_name = None
    thinking = p.thinking or ""
    if "phase=" in thinking:
        try:
            phase = thinking.split("phase=")[1].split()[0].strip()
        except (IndexError, ValueError):
            pass
    # Extract strategy name: everything between "[Beta] " and " alpha="
    if thinking.startswith("[Beta] ") and " alpha=" in thinking:
        name_part = thinking[7:].split(" alpha=")[0].strip()
        strategy_name = name_part

    # Look up strategy details from cache
    stop_loss_pct = None
    take_profit_pct = None
    max_hold_days = None
    buy_conditions = None
    sell_conditions = None

    if strategy_cache and strategy_name:
        strat = strategy_cache.get(strategy_name)
        if strat:
            ec = strat.exit_config or {}
            stop_loss_pct = ec.get("stop_loss_pct")
            take_profit_pct = ec.get("take_profit_pct")
            max_hold_days = ec.get("max_hold_days")
            buy_conditions = strat.buy_conditions
            sell_conditions = strat.sell_conditions
            if not strategy_name:
                strategy_name = strat.name

    return BotTradePlanItem(
        id=p.id, stock_code=p.stock_code, stock_name=p.stock_name,
        direction=p.direction, plan_price=p.plan_price, quantity=p.quantity,
        sell_pct=p.sell_pct, plan_date=p.plan_date, status=p.status,
        thinking=p.thinking, report_id=p.report_id,
        source=getattr(p, "source", "ai") or "ai",
        strategy_id=getattr(p, "strategy_id", None),
        created_at=p.created_at.isoformat() if p.created_at else "",
        executed_at=p.executed_at.isoformat() if p.executed_at else None,
        execution_price=p.execution_price,
        alpha_score=getattr(p, "alpha_score", None),
        beta_score=getattr(p, "beta_score", None),
        combined_score=getattr(p, "combined_score", None),
        phase=phase,
        strategy_name=strategy_name,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_hold_days=max_hold_days,
        buy_conditions=buy_conditions,
        sell_conditions=sell_conditions,
        today_close=px.get("close"),
        today_change_pct=px.get("change_pct"),
        today_high=px.get("high"),
        today_low=px.get("low"),
    )


def _build_strategy_cache(db: Session, plans: list) -> dict:
    """Build a name→Strategy lookup for all strategies referenced in plans' thinking fields.

    Strategy names in thinking may be truncated, so we use prefix (LIKE) matching.
    """
    from api.models.strategy import Strategy
    names = set()
    for p in plans:
        thinking = p.thinking or ""
        if thinking.startswith("[Beta] ") and " alpha=" in thinking:
            name_part = thinking[7:].split(" alpha=")[0].strip()
            if name_part:
                names.add(name_part)
    if not names:
        return {}
    # Try exact match first, fall back to prefix match for truncated names
    strategies = db.query(Strategy).filter(Strategy.name.in_(names)).all()
    cache = {s.name: s for s in strategies}
    # For names not found via exact match, try prefix match
    missing = names - set(cache.keys())
    for name in missing:
        strat = db.query(Strategy).filter(Strategy.name.like(f"{name}%")).first()
        if strat:
            cache[name] = strat
    return cache


@router.get("/plans", response_model=list[BotTradePlanItem])
def list_plans(
    status: str = Query("", description="Filter by status: pending|executed|expired"),
    plan_date: str = Query("", description="Filter by plan_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List trade plans, optionally filtered by status and plan_date."""
    q = db.query(BotTradePlan)
    if status:
        q = q.filter(BotTradePlan.status == status)
    if plan_date:
        q = q.filter(BotTradePlan.plan_date == plan_date)
    rows = q.order_by(BotTradePlan.plan_date.desc(), BotTradePlan.id.desc()).limit(limit).all()
    prices = _get_today_prices(db, list({p.stock_code for p in rows}))
    strat_cache = _build_strategy_cache(db, rows)
    return [_plan_to_item(p, prices, strat_cache) for p in rows]


@router.get("/plans/pending", response_model=list[BotTradePlanItem])
def list_pending_plans(db: Session = Depends(get_db)):
    """List only pending trade plans, sorted by combined_score descending."""
    rows = (
        db.query(BotTradePlan)
        .filter(BotTradePlan.status == "pending")
        .order_by(BotTradePlan.alpha_score.desc().nullslast(), BotTradePlan.id)
        .all()
    )
    prices = _get_today_prices(db, list({p.stock_code for p in rows}))
    strat_cache = _build_strategy_cache(db, rows)
    return [_plan_to_item(p, prices, strat_cache) for p in rows]


@router.put("/reviews/{review_id}/update")
def update_review(review_id: int, body: dict, db: Session = Depends(get_db)):
    """Update a review record (called by Claude review job)."""
    review = db.query(BotTradeReview).filter(BotTradeReview.id == review_id).first()
    if not review:
        raise HTTPException(404, f"Review {review_id} not found")

    if "review_thinking" in body:
        review.review_thinking = body["review_thinking"]
    if "memory_synced" in body:
        review.memory_synced = body["memory_synced"]
    if "memory_note_id" in body:
        review.memory_note_id = body["memory_note_id"]

    db.commit()
    return {"ok": True}


@router.get("/summary", response_model=BotSummary)
def get_bot_summary(db: Session = Depends(get_db)):
    """Get aggregate bot trading statistics."""
    holdings = db.query(BotPortfolio).all()
    reviews = db.query(BotTradeReview).all()

    total_invested = 0.0
    current_mv = 0.0
    for h in holdings:
        total_invested += h.total_invested
        close, _ = _latest_close(db, h.stock_code)
        if close:
            current_mv += close * h.quantity

    # P&L from closed positions
    closed_pnl = sum(r.pnl for r in reviews)
    # Unrealized P&L from open positions
    open_pnl = current_mv - sum(h.avg_cost * h.quantity for h in holdings)
    total_pnl = closed_pnl + open_pnl
    all_invested = total_invested + sum(r.total_buy_amount for r in reviews)
    total_pnl_pct = (total_pnl / all_invested * 100) if all_invested > 0 else 0.0

    # Count exit reasons from trades
    from sqlalchemy import func
    exit_counts = dict(
        db.query(BotTrade.sell_reason, func.count())
        .filter(BotTrade.sell_reason.isnot(None))
        .group_by(BotTrade.sell_reason)
        .all()
    )

    return BotSummary(
        total_invested=round(all_invested, 2),
        current_market_value=round(current_mv, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
        active_positions=len(holdings),
        completed_trades=len(reviews),
        reviews_count=len(reviews),
        win_count=sum(1 for r in reviews if r.pnl > 0),
        loss_count=sum(1 for r in reviews if r.pnl <= 0),
        sl_count=exit_counts.get("stop_loss", 0),
        tp_count=exit_counts.get("take_profit", 0),
        mhd_count=exit_counts.get("max_hold", 0),
        ai_sell_count=exit_counts.get("ai_recommend", 0),
    )
