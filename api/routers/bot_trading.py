"""Bot Trading router — simulated portfolio, trades, and reviews."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview
from api.models.stock import DailyPrice
from api.schemas.bot_trading import (
    BotPortfolioItem, BotTradeItem, BotTradeReviewItem,
    BotSummary, BotStockTimeline,
)

router = APIRouter(prefix="/api/bot", tags=["bot-trading"])


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
        result.append(BotPortfolioItem(
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

    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == stock_code).first()
    review = (
        db.query(BotTradeReview)
        .filter(BotTradeReview.stock_code == stock_code)
        .order_by(BotTradeReview.created_at.desc())
        .first()
    )

    buy_amount = sum(t.amount for t in trades if t.action == "buy")
    sell_amount = sum(t.amount for t in trades if t.action in ("sell", "reduce"))

    status = "holding" if holding and holding.quantity > 0 else "closed"
    pnl = sell_amount - buy_amount if status == "closed" else 0.0
    pnl_pct = (pnl / buy_amount * 100) if buy_amount > 0 and status == "closed" else 0.0

    first_buy = next((t for t in trades if t.action == "buy"), None)
    last_trade = trades[-1] if trades else None

    close, _ = _latest_close(db, stock_code) if holding else (None, None)

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
        current_quantity=holding.quantity if holding else 0,
        current_price=close,
        current_market_value=round(close * holding.quantity, 2) if close and holding else None,
        trades=[
            BotTradeItem(
                id=t.id, stock_code=t.stock_code, stock_name=t.stock_name,
                action=t.action, quantity=t.quantity, price=t.price,
                amount=t.amount, thinking=t.thinking, report_id=t.report_id,
                trade_date=t.trade_date,
                created_at=t.created_at.isoformat() if t.created_at else "",
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
    )
