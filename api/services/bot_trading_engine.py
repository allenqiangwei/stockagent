"""Bot Trading Engine — executes simulated trades from AI report recommendations.

Includes mechanical exit monitoring (SL/TP/MHD) consistent with the backtest engine.
"""

import json as _json
import logging
import math
from datetime import datetime, date as _date

from sqlalchemy.orm import Session

from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview, BotTradePlan
from api.models.stock import DailyPrice
from src.backtest.engine import calc_limit_prices

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
    return round(row.close * (row.adj_factor or 1.0), 2) if row and row.close else None


def monitor_exit_conditions(db: Session, trade_date: str) -> list[dict]:  # noqa: C901
    """Check all holdings for SL/TP/MHD exit conditions, matching backtest engine logic.

    Execution order: SL > TP > MHD (same as backtest).
    SL/TP: same-day execution (simulates stop/limit orders).
    MHD: creates pending sell plan for next trading day.
    """
    holdings = db.query(BotPortfolio).all()
    results = []

    for h in holdings:
        if not h.exit_config or h.quantity <= 0:
            continue

        ec = h.exit_config
        if isinstance(ec, str):
            try:
                ec = _json.loads(ec)
            except (_json.JSONDecodeError, ValueError):
                continue
        sl_pct = ec.get("stop_loss_pct", 0)
        tp_pct = ec.get("take_profit_pct", 0)
        mhd = ec.get("max_hold_days", 0)
        ref_price = h.buy_price or h.avg_cost

        # Get today's OHLCV
        ohlcv = db.query(DailyPrice).filter(
            DailyPrice.stock_code == h.stock_code,
            DailyPrice.trade_date == trade_date,
        ).first()
        if not ohlcv:
            continue

        _adj = float(ohlcv.adj_factor or 1.0)
        open_p = float(ohlcv.open) * _adj
        high = float(ohlcv.high) * _adj
        low = float(ohlcv.low) * _adj

        # Previous close for limit prices
        prev_row = (
            db.query(DailyPrice)
            .filter(DailyPrice.stock_code == h.stock_code, DailyPrice.trade_date < trade_date)
            .order_by(DailyPrice.trade_date.desc())
            .first()
        )
        if not prev_row:
            continue
        limit_up, limit_down = calc_limit_prices(h.stock_code, float(prev_row.close) * float(prev_row.adj_factor or 1.0))

        # T+1: cannot sell stocks bought today
        bought_today = db.query(BotTrade).filter(
            BotTrade.stock_code == h.stock_code,
            BotTrade.action == "buy",
            BotTrade.trade_date == trade_date,
        ).first()
        if bought_today:
            continue

        strat_id = h.strategy_id  # may be None for AI-recommended positions

        # ── SL check ──
        if sl_pct and sl_pct < 0:
            sl_threshold = round(ref_price * (1 + sl_pct / 100), 2)
            if open_p <= sl_threshold:
                sell_price = max(open_p, limit_down)
                if sell_price > limit_down or open_p > limit_down:
                    result = _execute_sell(
                        db, h.stock_code, h.stock_name, sell_price, 100.0,
                        f"止损触发(跳空): 阈值¥{sl_threshold}, 开盘¥{open_p}",
                        None, trade_date, sell_reason="stop_loss",
                        strategy_id=strat_id,
                    )
                    if result:
                        results.append(result)
                    continue
            elif low <= sl_threshold:
                sell_price = max(sl_threshold, limit_down)
                result = _execute_sell(
                    db, h.stock_code, h.stock_name, sell_price, 100.0,
                    f"止损触发: 阈值¥{sl_threshold}, 日低¥{low}",
                    None, trade_date, sell_reason="stop_loss",
                    strategy_id=strat_id,
                )
                if result:
                    results.append(result)
                continue

        # ── TP check ──
        if tp_pct and tp_pct > 0:
            tp_threshold = round(ref_price * (1 + tp_pct / 100), 2)
            if open_p >= tp_threshold:
                sell_price = min(open_p, limit_up)
                result = _execute_sell(
                    db, h.stock_code, h.stock_name, sell_price, 100.0,
                    f"止盈触发(跳空): 阈值¥{tp_threshold}, 开盘¥{open_p}",
                    None, trade_date, sell_reason="take_profit",
                    strategy_id=strat_id,
                )
                if result:
                    results.append(result)
                continue
            elif high >= tp_threshold:
                sell_price = min(tp_threshold, limit_up)
                result = _execute_sell(
                    db, h.stock_code, h.stock_name, sell_price, 100.0,
                    f"止盈触发: 阈值¥{tp_threshold}, 日高¥{high}",
                    None, trade_date, sell_reason="take_profit",
                    strategy_id=strat_id,
                )
                if result:
                    results.append(result)
                continue

        # ── MHD check ──
        if mhd and mhd > 0 and h.buy_date:
            try:
                buy_d = _date.fromisoformat(h.buy_date)
                today_d = _date.fromisoformat(trade_date)
                hold_days = (today_d - buy_d).days
            except ValueError:
                continue
            if hold_days >= mhd:
                next_td = _get_next_trading_day(db, trade_date)
                if next_td:
                    _upsert_plan(
                        db, h.stock_code, h.stock_name, "sell",
                        float(ohlcv.close) * _adj, h.quantity, 100.0, next_td,
                        f"最长持有{mhd}天到期(已持有{hold_days}天)",
                        None, source="max_hold", strategy_id=strat_id,
                    )
                    results.append({
                        "action": "max_hold_plan", "stock_code": h.stock_code,
                        "hold_days": hold_days, "plan_date": next_td,
                    })

    if results:
        db.commit()
        logger.info("Exit monitor: %d actions for %s", len(results), trade_date)
    return results


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
                 plan_date: str, thinking: str, report_id: int | None,
                 *, source: str = "ai", strategy_id: int | None = None) -> dict:
    """Insert or update a pending trade plan.

    Uniqueness scope:
    - strategy_id set: one pending plan per (stock, direction, strategy_id)
    - strategy_id None: one pending plan per (stock, direction) for AI plans
    """
    q = db.query(BotTradePlan).filter(
        BotTradePlan.stock_code == code,
        BotTradePlan.direction == direction,
        BotTradePlan.status == "pending",
    )
    if strategy_id is not None:
        q = q.filter(BotTradePlan.strategy_id == strategy_id)
    else:
        q = q.filter(BotTradePlan.strategy_id.is_(None))
    existing = q.first()

    if existing:
        existing.plan_price = price
        existing.quantity = quantity
        existing.sell_pct = sell_pct
        existing.plan_date = plan_date
        existing.thinking = thinking
        existing.report_id = report_id
        existing.stock_name = name
        existing.source = source
        if strategy_id is not None:
            existing.strategy_id = strategy_id
        logger.info("Plan UPDATED: %s %s %s @ ¥%.2f for %s [%s]", direction.upper(), code, name, price, plan_date, source)
        return {"action": "plan_updated", "direction": direction, "stock_code": code,
                "plan_price": price, "quantity": quantity, "plan_date": plan_date}
    else:
        plan = BotTradePlan(
            stock_code=code, stock_name=name, direction=direction,
            plan_price=price, quantity=quantity, sell_pct=sell_pct,
            plan_date=plan_date, status="pending",
            thinking=thinking, report_id=report_id,
            source=source, strategy_id=strategy_id,
        )
        db.add(plan)
        logger.info("Plan CREATED: %s %s %s @ ¥%.2f for %s [%s]", direction.upper(), code, name, price, plan_date, source)
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

        _adj = float(ohlcv.adj_factor or 1.0)
        high = float(ohlcv.high) * _adj
        low = float(ohlcv.low) * _adj
        open_price = float(ohlcv.open) * _adj

        if plan.direction == "buy":
            triggered = low <= plan.plan_price
        else:  # sell
            triggered = high >= plan.plan_price

        if triggered:
            # Limit-order fill price: buy fills at min(limit, open), sell at max(limit, open)
            if plan.direction == "buy":
                exec_price = min(plan.plan_price, open_price)
            else:
                exec_price = max(plan.plan_price, open_price)

            if plan.direction == "buy":
                # Resolve exit_config from strategy if available
                buy_exit_config = None
                if plan.strategy_id:
                    from api.models.strategy import Strategy
                    strat = db.query(Strategy).filter(Strategy.id == plan.strategy_id).first()
                    if strat and strat.exit_config:
                        buy_exit_config = strat.exit_config
                result = _execute_buy(
                    db, plan.stock_code, plan.stock_name, exec_price,
                    plan.thinking, plan.report_id, trade_date,
                    strategy_id=plan.strategy_id, exit_config=buy_exit_config,
                )
            else:
                # Re-check holding quantity (may have changed since plan creation)
                # For strategy-bound positions, match by (stock_code, strategy_id)
                holding_q = db.query(BotPortfolio).filter(
                    BotPortfolio.stock_code == plan.stock_code
                )
                if plan.strategy_id:
                    holding_q = holding_q.filter(BotPortfolio.strategy_id == plan.strategy_id)
                holding = holding_q.first()
                if not holding or holding.quantity <= 0:
                    plan.status = "expired"
                    logger.info("Plan EXPIRED (no holding): sell %s", plan.stock_code)
                    continue
                actual_sell_pct = plan.sell_pct
                if plan.quantity > holding.quantity:
                    actual_sell_pct = 100.0  # Sell whatever is left
                sell_reason = plan.source if plan.source != "ai" else "ai_recommend"
                result = _execute_sell(
                    db, plan.stock_code, plan.stock_name, exec_price,
                    actual_sell_pct, plan.thinking, plan.report_id, trade_date,
                    sell_reason=sell_reason, strategy_id=plan.strategy_id,
                )

            if result:
                plan.status = "executed"
                plan.executed_at = datetime.now()
                plan.execution_price = exec_price
                executed.append(result)
                logger.info("Plan EXECUTED: %s %s %s @ ¥%.2f (plan=%.2f, open=%.2f)", plan.direction, plan.stock_code, plan.stock_name, exec_price, plan.plan_price, open_price)
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


def _execute_buy(db: Session, code: str, name: str, price: float | None, reason: str,
                 report_id: int | None, trade_date: str,
                 *, strategy_id: int | None = None, exit_config: dict | None = None) -> dict | None:
    """Buy ~¥100,000 worth of stock."""
    if not price or price <= 0:
        logger.warning("Bot buy skipped: no valid target_price for %s", code)
        return None

    # Rule 1: same (stock, strategy) can only be bought once per day
    already_bought_q = db.query(BotTrade).filter(
        BotTrade.stock_code == code, BotTrade.action == "buy", BotTrade.trade_date == trade_date,
    )
    if strategy_id:
        already_bought_q = already_bought_q.filter(BotTrade.strategy_id == strategy_id)
    else:
        already_bought_q = already_bought_q.filter(BotTrade.strategy_id.is_(None))
    if already_bought_q.first():
        logger.info("Bot buy skipped: %s (strategy_id=%s) already bought on %s", code, strategy_id, trade_date)
        return None

    # Rule 2: same indicator family cannot hold the same stock twice.
    # Two strategies from the same family (e.g. two MACD+RSI variants) produce
    # essentially the same signal — double-buying wastes capital and doubles risk.
    # Check BOTH portfolio (committed holdings) AND today's trades (uncommitted in same tx).
    if strategy_id:
        from api.models.strategy import Strategy
        from api.services.strategy_pool import extract_indicator_family
        strat_obj = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if strat_obj:
            family = strat_obj.indicator_family or extract_indicator_family(strat_obj.buy_conditions)

            # Check 1: existing portfolio holdings (covers committed data)
            existing_holdings = (
                db.query(BotPortfolio)
                .filter(BotPortfolio.stock_code == code, BotPortfolio.quantity > 0)
                .all()
            )
            for h in existing_holdings:
                if h.strategy_id and h.strategy_id != strategy_id:
                    other_strat = db.query(Strategy).filter(Strategy.id == h.strategy_id).first()
                    if other_strat:
                        other_family = other_strat.indicator_family or extract_indicator_family(other_strat.buy_conditions)
                        if other_family == family:
                            logger.info("Bot buy skipped: %s already held by same family '%s' (strategy %d vs %d)",
                                        code, family, h.strategy_id, strategy_id)
                            return None

            # Check 2: today's buy trades in same transaction (covers unflushed adds)
            today_buys = (
                db.query(BotTrade)
                .filter(BotTrade.stock_code == code, BotTrade.action == "buy",
                        BotTrade.trade_date == trade_date)
                .all()
            )
            for tb in today_buys:
                if tb.strategy_id and tb.strategy_id != strategy_id:
                    other_strat = db.query(Strategy).filter(Strategy.id == tb.strategy_id).first()
                    if other_strat:
                        other_family = other_strat.indicator_family or extract_indicator_family(other_strat.buy_conditions)
                        if other_family == family:
                            logger.info("Bot buy skipped: %s already bought today by same family '%s' (strategy %d vs %d)",
                                        code, family, tb.strategy_id, strategy_id)
                            return None

    quantity = math.floor(BUY_AMOUNT / price / 100) * 100  # Round to lots of 100
    if quantity <= 0:
        quantity = 100  # Minimum 1 lot

    amount = quantity * price

    # Resolve strategy name if strategy_id provided
    strat_name = None
    if strategy_id:
        from api.models.strategy import Strategy
        strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if strat:
            strat_name = strat.name[:500] if strat.name else None
            if not exit_config and strat.exit_config:
                exit_config = strat.exit_config

    # Default exit_config if none provided
    if not exit_config:
        exit_config = {"stop_loss_pct": -10, "take_profit_pct": 15, "max_hold_days": 15}

    # Update or create portfolio entry.
    # Strategy-bound positions (strategy_id set): always create a new independent row.
    # AI/manual positions (strategy_id=None): avg-up if a row for the same stock exists.
    if strategy_id:
        holding = (
            db.query(BotPortfolio)
            .filter(BotPortfolio.stock_code == code, BotPortfolio.strategy_id == strategy_id)
            .first()
        )
    else:
        holding = (
            db.query(BotPortfolio)
            .filter(BotPortfolio.stock_code == code, BotPortfolio.strategy_id.is_(None))
            .first()
        )

    if holding:
        # Average up for same (stock, strategy) — shouldn't happen for virtual books
        # since beta_scorer already prevents duplicates, but handle defensively
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
            strategy_id=strategy_id,
            strategy_name=strat_name,
            exit_config=exit_config,
            buy_price=price,
            buy_date=trade_date,
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
        strategy_id=strategy_id,
    )
    db.add(trade)
    db.flush()  # Make holding + trade visible to subsequent Rule 2 checks in same tx

    logger.info("Bot BUY: %s %s × %d @ ¥%.2f = ¥%.0f (strategy=%s)", code, name, quantity, price, amount, strat_name or "none")
    return {"action": "buy", "stock_code": code, "quantity": quantity, "price": price, "amount": amount}


def _execute_sell(db: Session, code: str, name: str, price: float | None, sell_pct: float,
                  reason: str, report_id: int | None, trade_date: str,
                  *, sell_reason: str | None = None,
                  strategy_id: int | None = None) -> dict | None:
    """Sell a percentage of holdings. sell_pct=100 means full exit.

    strategy_id: when set, only affects the sub-position bound to that strategy.
    """
    if strategy_id:
        holding = (
            db.query(BotPortfolio)
            .filter(BotPortfolio.stock_code == code, BotPortfolio.strategy_id == strategy_id)
            .first()
        )
    else:
        holding = (
            db.query(BotPortfolio)
            .filter(BotPortfolio.stock_code == code, BotPortfolio.strategy_id.is_(None))
            .first()
        )
    if not holding or holding.quantity <= 0:
        logger.warning("Bot sell skipped: no holding for %s (strategy_id=%s)", code, strategy_id)
        return None

    # Rule: T+1 — cannot sell a position that was opened today
    if holding.buy_date == trade_date:
        logger.info("Bot sell skipped: %s (strategy_id=%s) was bought today (T+1 rule)", code, strategy_id)
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
        sell_reason=sell_reason or "ai_recommend",
        strategy_id=strategy_id,
    )
    db.add(trade)

    # Update holding
    holding.quantity -= sell_qty
    fully_exited = holding.quantity <= 0

    logger.info("Bot %s: %s %s × %d @ ¥%.2f = ¥%.0f [%s]", action.upper(), code, name, sell_qty, price, amount, sell_reason or "ai")

    if fully_exited:
        db.flush()  # Ensure the sell trade is visible to _create_review's query
        _create_review(
            db, code, name, trade_date,
            holding_id=holding.id,
            strategy_id=strategy_id,
            first_buy_date=holding.first_buy_date,
            exit_reason=sell_reason,
        )
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


def _create_review(db: Session, code: str, name: str, last_sell_date: str,
                   *, holding_id: int | None = None, strategy_id: int | None = None,
                   first_buy_date: str | None = None, exit_reason: str | None = None):
    """Create a trade review for ONE complete trade cycle (buy→sell).

    Only includes trades from this holding period (first_buy_date onwards),
    filtered by strategy_id. Each review = one independent position lifecycle.
    """
    trades_q = db.query(BotTrade).filter(BotTrade.stock_code == code)
    if strategy_id:
        trades_q = trades_q.filter(BotTrade.strategy_id == strategy_id)
    else:
        trades_q = trades_q.filter(BotTrade.strategy_id.is_(None))

    # Only include trades from this holding cycle — not historical ones
    if first_buy_date:
        trades_q = trades_q.filter(BotTrade.trade_date >= first_buy_date)

    trades = trades_q.order_by(BotTrade.trade_date, BotTrade.id).all()
    if not trades:
        return

    buy_amount = sum(t.amount for t in trades if t.action == "buy")
    sell_amount = sum(t.amount for t in trades if t.action in ("sell", "reduce"))
    pnl = sell_amount - buy_amount
    pnl_pct = (pnl / buy_amount * 100) if buy_amount > 0 else 0.0

    actual_first_buy = next((t for t in trades if t.action == "buy"), None)
    actual_first_buy_date = actual_first_buy.trade_date if actual_first_buy else (first_buy_date or "")

    holding_days = 0
    if actual_first_buy_date and last_sell_date:
        try:
            from datetime import date
            d1 = date.fromisoformat(actual_first_buy_date)
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
            "strategy_id": t.strategy_id,
            "sell_reason": t.sell_reason,
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
        first_buy_date=actual_first_buy_date,
        last_sell_date=last_sell_date,
        holding_days=holding_days,
        review_thinking="",
        memory_synced=False,
        trades=trades_snapshot,
        strategy_id=strategy_id,
        exit_reason=exit_reason,
    )
    db.add(review)
    db.flush()
    logger.info("Bot review created: %s %s, PnL=¥%.2f (%.1f%%)", code, name, pnl, pnl_pct)

    # Aggregate trajectory features from daily tracks (for Beta ML training)
    if holding_id:
        try:
            from api.services.beta_trajectory import aggregate_trajectory
            aggregate_trajectory(db, review.id, holding_id, code)
        except Exception as e:
            logger.warning("Beta trajectory aggregation failed for %s: %s", code, e)

    # Create beta review (links snapshot → outcome for XGBoost training)
    try:
        from api.services.beta_engine import create_beta_review
        create_beta_review(db, review)
    except Exception as e:
        logger.warning("Beta review creation failed for %s: %s", code, e)

    # Update decay probation state (if strategy is on probation)
    if strategy_id:
        try:
            from api.services.strategy_pool import StrategyPoolManager
            from api.models.strategy import Strategy
            strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
            if strat and StrategyPoolManager.is_on_probation(strat):
                is_win = (pnl_pct or 0) > 0
                cleared = StrategyPoolManager.update_decay_probation(strat, is_win)
                if cleared:
                    logger.info("Probation cleared for S%d after trade on %s", strategy_id, code)
        except Exception as e:
            logger.warning("Decay probation update failed for S%d: %s", strategy_id, e)
