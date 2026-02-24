"""Bot Trading Engine — executes simulated trades from AI report recommendations."""

import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview, BotTradePlan
from api.models.stock import DailyPrice

logger = logging.getLogger(__name__)

BUY_AMOUNT = 100_000  # ¥100,000 per buy


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
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _get_prev_close(db: Session, stock_code: str, report_date: str) -> float | None:
    """Get the previous close price for a stock as of report_date."""
    from datetime import date as _date
    row = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code == stock_code, DailyPrice.trade_date <= _date.fromisoformat(report_date))
        .order_by(DailyPrice.trade_date.desc())
        .first()
    )
    return round(row.close, 2) if row and row.close else None


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
            price = _get_prev_close(db, stock_code, report_date)
            if not price or price <= 0:
                logger.warning("Plan skipped: no close price for buy %s", stock_code)
                continue
            quantity = math.floor(BUY_AMOUNT / price / 100) * 100
            if quantity <= 0:
                quantity = 100
            result = _upsert_plan(db, stock_code, stock_name, "buy", price, quantity, 0.0,
                                  next_td, reason, report_id)
            plans.append(result)

        elif action in ("sell", "reduce"):
            price = _get_prev_close(db, stock_code, report_date)
            if not price or price <= 0:
                logger.warning("Plan skipped: no close price for sell %s", stock_code)
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


def _execute_buy(db: Session, code: str, name: str, price: float | None, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Buy ~¥100,000 worth of stock."""
    if not price or price <= 0:
        logger.warning("Bot buy skipped: no valid target_price for %s", code)
        return None

    # Rule: same stock can only be bought once per day
    already_bought = (
        db.query(BotTrade)
        .filter(BotTrade.stock_code == code, BotTrade.action == "buy", BotTrade.trade_date == trade_date)
        .first()
    )
    if already_bought:
        logger.info("Bot buy skipped: %s already bought on %s", code, trade_date)
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

    # Rule: T+1 — cannot sell stock bought on the same day
    bought_today = (
        db.query(BotTrade)
        .filter(BotTrade.stock_code == code, BotTrade.action == "buy", BotTrade.trade_date == trade_date)
        .first()
    )
    if bought_today:
        logger.info("Bot sell skipped: %s was bought today (T+1 rule), date=%s", code, trade_date)
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
