"""Score all buy signals with combined alpha+beta and create trade plans.

Virtual books: when N strategies select the same stock, create up to
MAX_POSITIONS_PER_STOCK independent sub-positions, each tracked by its
own strategy's SL/TP/MHD parameters.
"""

import json
import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.signal import TradingSignal
from api.models.bot_trading import BotTradePlan, BotPortfolio
from api.models.beta_factor import BetaReview

logger = logging.getLogger(__name__)

MAX_POSITIONS_PER_STOCK = 2  # Max concurrent sub-positions per stock (concentration limit)

WEIGHT_TABLE = {
    "cold": (0.80, 0.20),
    "warm": (0.60, 0.40),
    "mature": (0.50, 0.50),
}

# Gamma weight table: (alpha_weight, gamma_weight)
GAMMA_WEIGHT_TABLE = {
    "cold": (0.80, 0.20),     # < 30 completed trades with gamma
    "warm": (0.60, 0.40),     # 30-99
    "mature": (0.50, 0.50),   # >= 100
}


def _get_gamma_phase(db: Session) -> str:
    """Count completed trades that had gamma data at entry.

    Uses INNER JOIN to GammaSnapshot — only reviews where a
    snapshot existed on/before first_buy_date are counted.
    """
    from sqlalchemy import func, distinct, and_
    from api.models.bot_trading import BotTradeReview
    from api.models.gamma_factor import GammaSnapshot

    n = (
        db.query(func.count(distinct(BotTradeReview.id)))
        .join(GammaSnapshot, and_(
            GammaSnapshot.stock_code == BotTradeReview.stock_code,
            GammaSnapshot.snapshot_date <= BotTradeReview.first_buy_date,
        ))
        .scalar()
    ) or 0
    if n < 30:
        return "cold"
    elif n < 100:
        return "warm"
    return "mature"


def _get_phase(db: Session) -> str:
    n = db.query(BetaReview).filter(BetaReview.is_profitable.isnot(None)).count()
    if n < 30:
        return "cold"
    elif n < 100:
        return "warm"
    return "mature"


def _parse_strategy_names(reasons_json: str | None) -> list[str]:
    """Extract strategy names from reasons JSON (list of strings or dicts)."""
    try:
        reasons = json.loads(reasons_json or "[]")
    except Exception:
        return []
    names = []
    for r in reasons:
        if isinstance(r, dict):
            name = r.get("strategy") or r.get("name", "")
        elif isinstance(r, str):
            name = r
        else:
            name = ""
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return names


def _lookup_strategies(db: Session, names: list[str]) -> list:
    """Batch look up Strategy objects by name. Returns list ordered by backtest score desc."""
    from api.models.strategy import Strategy
    if not names:
        return []

    # Exact match first
    rows = db.query(Strategy).filter(Strategy.name.in_(names)).all()
    found_names = {s.name for s in rows}

    # Prefix match for any not found (names may be truncated)
    for name in names:
        if name not in found_names:
            s = db.query(Strategy).filter(Strategy.name.like(f"{name}%")).first()
            if s:
                rows.append(s)
                found_names.add(s.name)

    # Sort by backtest score descending (best strategy first)
    rows.sort(
        key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0,
        reverse=True,
    )
    return rows


def score_and_create_plans(db: Session, trade_date: str, plan_date: str) -> list[dict]:
    """Score all buy signals for trade_date and create BotTradePlans for plan_date.

    For each buy signal, up to MAX_POSITIONS_PER_STOCK independent sub-plans are
    created — one per triggering strategy.  Each sub-plan carries the strategy's
    own exit_config so the position will later be monitored with the correct
    SL/TP/MHD values.

    Returns list of plan summaries sorted by combined_score descending.
    """
    from api.services.beta_ml import predict_beta_score
    from api.services.bot_trading_engine import _get_prev_close

    buy_signals = (
        db.query(TradingSignal)
        .filter(TradingSignal.trade_date == trade_date, TradingSignal.market_regime == "buy")
        .all()
    )

    if not buy_signals:
        logger.info("Beta scorer: no buy signals for %s", trade_date)
        return []

    logger.info("Beta scorer: found %d buy signals for %s", len(buy_signals), trade_date)

    beta_phase = _get_phase(db)
    gamma_phase = _get_gamma_phase(db)
    alpha_w, gamma_w = GAMMA_WEIGHT_TABLE[gamma_phase]

    # Pre-load shared beta factor context (query once, reuse for all signals)
    shared_context = _load_shared_beta_context(db, trade_date)

    # Pre-load current counts per stock to enforce concentration limit
    holding_counts: dict[str, int] = dict(
        db.query(BotPortfolio.stock_code, func.count(BotPortfolio.id))
        .filter(BotPortfolio.quantity > 0)
        .group_by(BotPortfolio.stock_code)
        .all()
    )
    pending_counts: dict[str, int] = dict(
        db.query(BotTradePlan.stock_code, func.count(BotTradePlan.id))
        .filter(BotTradePlan.direction == "buy", BotTradePlan.status == "pending")
        .group_by(BotTradePlan.stock_code)
        .all()
    )

    # Pre-load already-occupied (stock_code, strategy_id) pairs
    held_pairs: set[tuple] = {
        (h.stock_code, h.strategy_id)
        for h in db.query(BotPortfolio).filter(BotPortfolio.quantity > 0).all()
    }
    pending_pairs: set[tuple] = {
        (p.stock_code, p.strategy_id)
        for p in db.query(BotTradePlan)
        .filter(BotTradePlan.direction == "buy", BotTradePlan.status == "pending")
        .all()
    }
    occupied_pairs = held_pairs | pending_pairs

    plans = []
    for signal in buy_signals:
        code = signal.stock_code

        # Concentration check: how many sub-positions does this stock already have?
        current_count = holding_counts.get(code, 0) + pending_counts.get(code, 0)
        if current_count >= MAX_POSITIONS_PER_STOCK:
            continue

        available_slots = MAX_POSITIONS_PER_STOCK - current_count

        # Extract all triggering strategy names from signal
        strategy_names = _parse_strategy_names(signal.reasons)
        if not strategy_names:
            # No named strategies — create one plan with no strategy binding
            strategy_names = [""]

        # Score the stock (same alpha/gamma/beta for all sub-positions)
        alpha = signal.final_score or 0.0
        gamma = signal.gamma_score  # May be None if chanlun-pro was unavailable

        # Gamma-first combined score
        if gamma is not None:
            combined = round(
                (alpha / 100.0) * alpha_w + (gamma / 100.0) * gamma_w, 4
            )
        else:
            combined = round(alpha / 100.0, 4)  # Degrade to pure Alpha

        # Beta reference (still computed for ML training, not for ranking)
        features = {
            "stock_code": code,
            "alpha_score": alpha,
            "day_of_week": datetime.now().weekday(),
            **shared_context,
            **_load_stock_beta_context(db, code),
        }

        # Add gamma features for ML
        if gamma is not None:
            from api.models.gamma_factor import GammaSnapshot as GS
            snap = db.query(GS).filter_by(
                stock_code=code, snapshot_date=trade_date
            ).first()
            if snap:
                features["gamma_score"] = snap.gamma_score
                features["daily_mmd_type"] = snap.daily_mmd_type
                features["daily_mmd_age"] = snap.daily_mmd_age
                features["weekly_resonance"] = snap.weekly_resonance

        beta = predict_beta_score(db, features)

        plan_price = _get_prev_close(db, code, trade_date) or 0.0
        if plan_price <= 0:
            continue

        quantity = int(100_000 / plan_price / 100) * 100
        if quantity <= 0:
            quantity = 100

        # Resolve stock name
        stock_name = ""
        try:
            from api.models.stock import Stock
            stock = db.query(Stock).filter(Stock.code == code).first()
            if stock:
                stock_name = stock.name
        except Exception:
            pass

        # Look up strategy objects, sorted by score desc
        strategies = _lookup_strategies(db, [n for n in strategy_names if n])

        # Build a name→strategy map for quick lookup
        strat_by_name: dict[str, object] = {s.name: s for s in strategies}

        created_this_stock = 0
        for strategy_name in strategy_names:
            if created_this_stock >= available_slots:
                break

            # Resolve strategy object
            strat = strat_by_name.get(strategy_name)
            if strat is None and strategy_name:
                # Try prefix match for truncated names
                strat = next(
                    (s for s in strategies if s.name.startswith(strategy_name[:40])),
                    None,
                )

            strategy_id = strat.id if strat else None

            # Skip if this (stock, strategy) pair is already occupied
            if (code, strategy_id) in occupied_pairs:
                continue

            # Confidence scoring (Logistic Regression)
            confidence = None
            try:
                from api.services.confidence_scorer import predict_confidence
                from api.models.market_regime import MarketRegimeLabel
                from datetime import date as _date
                regime = (
                    db.query(MarketRegimeLabel)
                    .filter(MarketRegimeLabel.week_end >= _date.fromisoformat(trade_date))
                    .order_by(MarketRegimeLabel.week_end.asc())
                    .first()
                )
                if regime:
                    confidence = predict_confidence(
                        db, alpha, gamma,
                        trend_strength=regime.trend_strength,
                        volatility=regime.volatility,
                        index_return_pct=regime.index_return_pct,
                    )
            except Exception as e:
                logger.warning("Confidence scoring failed (non-fatal): %s", e)

            plan = BotTradePlan(
                stock_code=code,
                stock_name=stock_name,
                direction="buy",
                plan_price=plan_price,
                quantity=quantity,
                sell_pct=0.0,
                plan_date=plan_date,
                status="pending",
                thinking=(
                    f"[C={confidence or '?'}] {strategy_name or 'signal'} "
                    f"alpha={alpha:.1f} gamma={gamma or 0:.1f} "
                    f"combined={combined:.4f}"
                ),
                source="beta",
                strategy_id=strategy_id,
                alpha_score=alpha,
                beta_score=beta,
                combined_score=combined,
                gamma_score=gamma,
                signal_grade=None,
                signal_win_rate=None,
                confidence=confidence,
            )
            db.add(plan)

            # Capture beta snapshot for XGBoost training
            try:
                from api.services.beta_engine import capture_signal_snapshot
                # Infer strategy family from strategy name (e.g. "RSI_47_67..." → "RSI")
                strat_family = None
                if strat and strat.name:
                    from api.services.beta_ml import FAMILY_MAP
                    for fam in FAMILY_MAP:
                        if fam != "unknown" and fam.lower() in strat.name.lower():
                            strat_family = fam
                            break
                capture_signal_snapshot(
                    db, code, stock_name, trade_date, features,
                    strategy_family=strat_family,
                )
            except Exception as e:
                logger.warning("Beta snapshot failed for %s (non-fatal): %s", code, e)

            # Update tracking state
            occupied_pairs.add((code, strategy_id))
            pending_counts[code] = pending_counts.get(code, 0) + 1
            created_this_stock += 1

            plans.append({
                "stock_code": code,
                "stock_name": stock_name,
                "strategy": strategy_name or "signal",
                "strategy_id": strategy_id,
                "alpha_score": alpha,  # Raw 0-100
                "gamma_score": gamma,
                "beta_score": beta,
                "combined_score": combined,
                "plan_price": plan_price,
                "quantity": quantity,
                "phase": gamma_phase,
            })

    if plans:
        plans.sort(key=lambda x: x["combined_score"], reverse=True)
        db.commit()
        logger.info(
            "Beta scorer: %d plans (%d stocks) for %s (gamma_phase=%s)",
            len(plans),
            len({p["stock_code"] for p in plans}),
            plan_date,
            gamma_phase,
        )

    return plans


def _load_shared_beta_context(db: Session, trade_date: str) -> dict:
    """Load market-wide beta factors (queried once per scoring run)."""
    context: dict = {}

    # Market regime
    try:
        from api.models.market_regime import MarketRegimeLabel
        from datetime import date as _date
        d = _date.fromisoformat(trade_date)
        regime = (
            db.query(MarketRegimeLabel)
            .filter(MarketRegimeLabel.week_end >= d)
            .order_by(MarketRegimeLabel.week_end.desc())
            .first()
        )
        if regime:
            context["regime_code"] = regime.regime
    except Exception:
        pass

    # Market sentiment
    try:
        from api.models.news_sentiment import NewsSentimentResult
        sent = (
            db.query(NewsSentimentResult)
            .order_by(NewsSentimentResult.analysis_time.desc())
            .first()
        )
        if sent:
            context["market_sentiment"] = sent.market_sentiment
    except Exception:
        pass

    return context


def _load_stock_beta_context(db: Session, stock_code: str) -> dict:
    """Load per-stock beta factors."""
    context: dict = {}

    # Sector heat — fuzzy match: exact → contains → keyword overlap
    try:
        from api.models.stock import Stock
        from api.models.news_agent import SectorHeat
        stock = db.query(Stock).filter(Stock.code == stock_code).first()
        if stock and stock.industry:
            ind = stock.industry
            # Try exact match first
            heat = (
                db.query(SectorHeat)
                .filter(SectorHeat.sector_name == ind)
                .order_by(SectorHeat.snapshot_time.desc())
                .first()
            )
            # Fallback: sector_name contains industry or vice versa
            if not heat:
                heat = (
                    db.query(SectorHeat)
                    .filter(SectorHeat.sector_name.contains(ind) | SectorHeat.sector_name.op("=")(ind))
                    .order_by(SectorHeat.snapshot_time.desc())
                    .first()
                )
            if not heat and len(ind) >= 2:
                # Try each 2-char keyword from industry name
                for i in range(len(ind) - 1):
                    kw = ind[i:i+2]
                    heat = (
                        db.query(SectorHeat)
                        .filter(SectorHeat.sector_name.contains(kw))
                        .order_by(SectorHeat.snapshot_time.desc())
                        .first()
                    )
                    if heat:
                        break
            if heat:
                context["sector_heat_score"] = heat.heat_score
    except Exception:
        pass

    # PE / turnover (from daily_basic via TuShare)
    try:
        from api.models.stock import DailyBasic
        basic = (
            db.query(DailyBasic)
            .filter(DailyBasic.stock_code == stock_code)
            .order_by(DailyBasic.trade_date.desc())
            .first()
        )
        if basic:
            if basic.pe is not None:
                context["pe"] = basic.pe
            if basic.turnover_rate is not None:
                context["turnover_rate"] = basic.turnover_rate
    except Exception:
        pass

    return context
