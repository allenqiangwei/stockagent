"""Score all buy signals with combined alpha+beta and create trade plans."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from api.models.signal import ActionSignal
from api.models.bot_trading import BotTradePlan, BotPortfolio
from api.models.beta_factor import BetaReview

logger = logging.getLogger(__name__)

WEIGHT_TABLE = {
    "cold": (0.80, 0.20),
    "warm": (0.60, 0.40),
    "mature": (0.50, 0.50),
}


def _get_phase(db: Session) -> str:
    n = db.query(BetaReview).filter(BetaReview.is_profitable.isnot(None)).count()
    if n < 30:
        return "cold"
    elif n < 100:
        return "warm"
    return "mature"


def score_and_create_plans(db: Session, trade_date: str, plan_date: str) -> list[dict]:
    """Score all buy signals for trade_date and create BotTradePlans for plan_date.

    Returns list of plan summaries sorted by combined_score descending.
    """
    from api.services.beta_ml import predict_beta_score
    from api.services.bot_trading_engine import _get_prev_close

    buy_signals = (
        db.query(ActionSignal)
        .filter(ActionSignal.trade_date == trade_date, ActionSignal.action == "BUY")
        .all()
    )

    if not buy_signals:
        logger.info("Beta scorer: no BUY signals for %s", trade_date)
        return []

    held_codes = {
        h.stock_code for h in db.query(BotPortfolio).filter(BotPortfolio.quantity > 0).all()
    }

    phase = _get_phase(db)
    alpha_w, beta_w = WEIGHT_TABLE[phase]

    plans = []
    for signal in buy_signals:
        code = signal.stock_code
        if code in held_codes:
            continue

        existing = (
            db.query(BotTradePlan)
            .filter(
                BotTradePlan.stock_code == code,
                BotTradePlan.direction == "buy",
                BotTradePlan.status == "pending",
            )
            .first()
        )
        if existing:
            continue

        alpha = signal.confidence_score or 0.5
        features = {
            "stock_code": code,
            "alpha_score": alpha,
            "day_of_week": datetime.now().weekday(),
        }
        beta = predict_beta_score(db, features)
        combined = round(alpha * alpha_w + beta * beta_w, 4)

        plan_price = _get_prev_close(db, code, trade_date) or 0.0
        if plan_price <= 0:
            continue

        quantity = int(100_000 / plan_price / 100) * 100
        if quantity <= 0:
            quantity = 100

        strategy_name = signal.strategy_name or "unknown"

        stock_name = ""
        try:
            from src.data_storage.database import Stock
            stock = db.query(Stock).filter(Stock.code == code).first()
            if stock:
                stock_name = stock.name
        except Exception:
            pass

        plan = BotTradePlan(
            stock_code=code, stock_name=stock_name, direction="buy",
            plan_price=plan_price, quantity=quantity, sell_pct=0.0,
            plan_date=plan_date, status="pending",
            thinking=f"[Beta] {strategy_name} alpha={alpha:.3f} beta={beta:.3f} combined={combined:.4f} phase={phase}",
            source="beta", strategy_id=None,
            alpha_score=alpha, beta_score=beta, combined_score=combined,
        )
        db.add(plan)
        plans.append({
            "stock_code": code, "stock_name": stock_name,
            "strategy": strategy_name,
            "alpha_score": alpha, "beta_score": beta, "combined_score": combined,
            "plan_price": plan_price, "quantity": quantity, "phase": phase,
        })

    if plans:
        db.commit()
        plans.sort(key=lambda x: x["combined_score"], reverse=True)
        logger.info("Beta scorer: %d plans for %s (phase=%s)", len(plans), plan_date, phase)

    return plans
