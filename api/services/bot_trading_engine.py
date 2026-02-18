"""Bot Trading Engine — executes simulated trades from AI report recommendations."""

import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview

logger = logging.getLogger(__name__)

BUY_AMOUNT = 100_000  # ¥100,000 per buy


def execute_bot_trades(db: Session, report_id: int, report_date: str, recommendations: list[dict]) -> list[dict]:
    """Execute simulated trades based on AI report recommendations.

    Returns list of executed trade summaries.
    """
    if not recommendations:
        return []

    executed = []

    for rec in recommendations:
        action = rec.get("action", "")
        stock_code = rec.get("stock_code", "")
        stock_name = rec.get("stock_name", "")
        target_price = rec.get("target_price")
        position_pct = rec.get("position_pct", 0)
        reason = rec.get("reason", "")

        if not stock_code or not action:
            continue

        if action == "buy":
            result = _execute_buy(db, stock_code, stock_name, target_price, reason, report_id, report_date)
        elif action == "sell":
            result = _execute_sell(db, stock_code, stock_name, target_price, 100.0, reason, report_id, report_date)
        elif action == "reduce":
            result = _execute_sell(db, stock_code, stock_name, target_price, position_pct, reason, report_id, report_date)
        elif action == "hold":
            result = _execute_hold(db, stock_code, stock_name, target_price, reason, report_id, report_date)
        else:
            continue

        if result:
            executed.append(result)

    db.commit()
    return executed


def _execute_buy(db: Session, code: str, name: str, price: float | None, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Buy ~¥100,000 worth of stock."""
    if not price or price <= 0:
        logger.warning("Bot buy skipped: no valid target_price for %s", code)
        return None

    quantity = math.floor(BUY_AMOUNT / price / 100) * 100  # Round to lots of 100
    if quantity <= 0:
        quantity = 100  # Minimum 1 lot

    amount = quantity * price

    # Update or create portfolio entry
    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == code).first()
    if holding:
        # Average up: recalculate avg_cost
        total_cost = holding.avg_cost * holding.quantity + amount
        holding.quantity += quantity
        holding.avg_cost = total_cost / holding.quantity
        holding.total_invested += amount
    else:
        holding = BotPortfolio(
            stock_code=code,
            stock_name=name,
            quantity=quantity,
            avg_cost=price,
            total_invested=amount,
            first_buy_date=trade_date,
        )
        db.add(holding)

    # Record trade
    trade = BotTrade(
        stock_code=code,
        stock_name=name,
        action="buy",
        quantity=quantity,
        price=price,
        amount=amount,
        thinking=reason,
        report_id=report_id,
        trade_date=trade_date,
    )
    db.add(trade)

    logger.info("Bot BUY: %s %s × %d @ ¥%.2f = ¥%.0f", code, name, quantity, price, amount)
    return {"action": "buy", "stock_code": code, "quantity": quantity, "price": price, "amount": amount}


def _execute_sell(db: Session, code: str, name: str, price: float | None, sell_pct: float, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Sell a percentage of holdings. sell_pct=100 means full exit."""
    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == code).first()
    if not holding or holding.quantity <= 0:
        logger.warning("Bot sell skipped: no holding for %s", code)
        return None

    if not price or price <= 0:
        price = holding.avg_cost  # Fallback to cost if no target_price

    sell_qty = math.floor(holding.quantity * sell_pct / 100 / 100) * 100  # Round to lots
    if sell_qty <= 0:
        sell_qty = min(100, holding.quantity)
    if sell_qty > holding.quantity:
        sell_qty = holding.quantity

    amount = sell_qty * price
    action = "sell" if sell_qty >= holding.quantity else "reduce"

    # Record trade
    trade = BotTrade(
        stock_code=code,
        stock_name=name,
        action=action,
        quantity=sell_qty,
        price=price,
        amount=amount,
        thinking=reason,
        report_id=report_id,
        trade_date=trade_date,
    )
    db.add(trade)

    # Update holding
    holding.quantity -= sell_qty
    fully_exited = holding.quantity <= 0

    logger.info("Bot %s: %s %s × %d @ ¥%.2f = ¥%.0f", action.upper(), code, name, sell_qty, price, amount)

    if fully_exited:
        # Trigger review (sync for now, async later)
        _create_review(db, code, name, trade_date)
        db.delete(holding)

    return {"action": action, "stock_code": code, "quantity": sell_qty, "price": price, "amount": amount, "fully_exited": fully_exited}


def _execute_hold(db: Session, code: str, name: str, price: float | None, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Record a hold decision with thinking."""
    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == code).first()
    if not holding:
        return None

    trade = BotTrade(
        stock_code=code,
        stock_name=name,
        action="hold",
        quantity=0,
        price=price or 0,
        amount=0,
        thinking=reason,
        report_id=report_id,
        trade_date=trade_date,
    )
    db.add(trade)

    logger.info("Bot HOLD: %s %s", code, name)
    return {"action": "hold", "stock_code": code}


def _create_review(db: Session, code: str, name: str, last_sell_date: str):
    """Create a trade review record after fully exiting a position."""
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.stock_code == code)
        .order_by(BotTrade.trade_date, BotTrade.id)
        .all()
    )
    if not trades:
        return

    buy_amount = sum(t.amount for t in trades if t.action == "buy")
    sell_amount = sum(t.amount for t in trades if t.action in ("sell", "reduce"))
    pnl = sell_amount - buy_amount
    pnl_pct = (pnl / buy_amount * 100) if buy_amount > 0 else 0.0

    first_buy = next((t for t in trades if t.action == "buy"), None)
    first_buy_date = first_buy.trade_date if first_buy else ""

    holding_days = 0
    if first_buy_date and last_sell_date:
        try:
            from datetime import date
            d1 = date.fromisoformat(first_buy_date)
            d2 = date.fromisoformat(last_sell_date)
            holding_days = (d2 - d1).days
        except ValueError:
            pass

    trades_snapshot = [
        {
            "id": t.id,
            "action": t.action,
            "quantity": t.quantity,
            "price": t.price,
            "amount": t.amount,
            "thinking": t.thinking,
            "trade_date": t.trade_date,
        }
        for t in trades
    ]

    review = BotTradeReview(
        stock_code=code,
        stock_name=name,
        total_buy_amount=buy_amount,
        total_sell_amount=sell_amount,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        first_buy_date=first_buy_date,
        last_sell_date=last_sell_date,
        holding_days=holding_days,
        review_thinking="",  # Will be filled by Claude review job
        memory_synced=False,
        trades=trades_snapshot,
    )
    db.add(review)
    logger.info("Bot review created: %s %s, PnL=¥%.2f (%.1f%%)", code, name, pnl, pnl_pct)
