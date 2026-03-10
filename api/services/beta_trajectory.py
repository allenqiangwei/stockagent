"""Aggregate holding trajectory features from daily tracks after position close."""

import logging
import numpy as np
from sqlalchemy.orm import Session

from api.models.beta_factor import BetaDailyTrack, BetaReview

logger = logging.getLogger(__name__)


def aggregate_trajectory(db: Session, review_id: int, holding_id: int, stock_code: str) -> bool:
    """Compute trajectory features from daily tracks and update the beta review.

    Called after _create_review() in bot_trading_engine.py.
    Returns True if trajectory was successfully aggregated.
    """
    beta_review = db.query(BetaReview).filter(BetaReview.review_id == review_id).first()
    if not beta_review:
        logger.warning("No BetaReview for review_id=%d, skipping trajectory", review_id)
        return False

    tracks = (
        db.query(BetaDailyTrack)
        .filter(BetaDailyTrack.holding_id == holding_id)
        .order_by(BetaDailyTrack.track_date.asc())
        .all()
    )

    beta_review.is_profitable = beta_review.pnl_pct > 0

    if not tracks:
        db.commit()
        return True

    cum_pnls = [t.cumulative_pnl_pct for t in tracks if t.cumulative_pnl_pct is not None]
    daily_rets = [t.daily_return_pct for t in tracks if t.daily_return_pct is not None]
    volumes = [t.volume for t in tracks if t.volume is not None]

    beta_review.max_unrealized_gain = max(cum_pnls) if cum_pnls else None
    beta_review.max_unrealized_loss = min(cum_pnls) if cum_pnls else None
    beta_review.price_path_volatility = float(np.std(daily_rets)) if len(daily_rets) >= 2 else None

    if len(volumes) >= 3:
        x = np.arange(len(volumes), dtype=float)
        beta_review.volume_trend_slope = float(np.polyfit(x, volumes, 1)[0])

    regimes = [t.regime_code for t in tracks if t.regime_code]
    beta_review.regime_changed = (regimes[0] != regimes[-1]) if len(regimes) >= 2 else False

    heats = [t.sector_heat_score for t in tracks if t.sector_heat_score is not None]
    if len(heats) >= 2:
        beta_review.sector_heat_delta = heats[-1] - heats[0]

    beta_review.news_events_during_hold = sum(t.news_event_count for t in tracks)

    index_closes = [t.index_close for t in tracks if t.index_close is not None]
    if len(index_closes) >= 2:
        beta_review.index_return_during_hold = (
            (index_closes[-1] - index_closes[0]) / index_closes[0] * 100
        )

    db.commit()
    logger.info(
        "Trajectory aggregated for review_id=%d: gain=%.2f%%, loss=%.2f%%, profitable=%s",
        review_id, beta_review.max_unrealized_gain or 0,
        beta_review.max_unrealized_loss or 0, beta_review.is_profitable,
    )
    return True
