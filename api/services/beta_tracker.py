"""Beta daily tracking — records daily snapshots for all active bot holdings."""

import logging
from sqlalchemy.orm import Session

from api.models.bot_trading import BotPortfolio
from api.models.beta_factor import BetaDailyTrack

logger = logging.getLogger(__name__)


def track_daily_holdings(db: Session, trade_date: str) -> int:
    """Create daily tracking records for all active bot holdings.

    Called after market close. Returns count of tracks created.
    """
    holdings = db.query(BotPortfolio).filter(BotPortfolio.quantity > 0).all()
    if not holdings:
        return 0

    from src.data_storage.database import DailyPrice, IndexDaily, Stock

    codes = [h.stock_code for h in holdings]
    prices = {
        p.stock_code: p
        for p in db.query(DailyPrice)
        .filter(DailyPrice.stock_code.in_(codes), DailyPrice.trade_date == trade_date)
        .all()
    }

    index_row = (
        db.query(IndexDaily)
        .filter(IndexDaily.index_code == "000001", IndexDaily.trade_date == trade_date)
        .first()
    )
    index_close = index_row.close if index_row else None

    regime_code = None
    try:
        from api.services.beta_engine import _get_current_regime
        regime = _get_current_regime(db, trade_date)
        regime_code = regime.regime if regime else None
    except Exception:
        pass

    created = 0
    for holding in holdings:
        code = holding.stock_code
        price = prices.get(code)
        if not price:
            continue

        existing = (
            db.query(BetaDailyTrack)
            .filter(BetaDailyTrack.holding_id == holding.id, BetaDailyTrack.track_date == trade_date)
            .first()
        )
        if existing:
            continue

        entry_price = holding.buy_price or holding.avg_cost
        cum_pnl = ((price.close - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

        recent_prices = (
            db.query(DailyPrice)
            .filter(DailyPrice.stock_code == code, DailyPrice.trade_date <= trade_date)
            .order_by(DailyPrice.trade_date.desc())
            .limit(6)
            .all()
        )
        daily_ret = 0.0
        if len(recent_prices) >= 2:
            prev_close = recent_prices[1].close
            daily_ret = ((price.close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        vol_ratio = None
        if len(recent_prices) >= 6:
            avg_vol = sum(p.volume for p in recent_prices[1:6]) / 5
            vol_ratio = (price.volume / avg_vol) if avg_vol > 0 else None

        sector_heat_score = None
        try:
            stock = db.query(Stock).filter(Stock.code == code).first()
            if stock and stock.industry:
                from api.services.beta_engine import _get_sector_heat, _get_stock_concepts
                concepts = _get_stock_concepts(db, code)
                sh = _get_sector_heat(db, stock.industry, concepts)
                sector_heat_score = sh.heat_score if sh else None
        except Exception:
            pass

        news_count = 0
        try:
            from src.data_storage.database import NewsEvent
            news_count = db.query(NewsEvent).filter(NewsEvent.event_date == trade_date).count()
        except Exception:
            pass

        track = BetaDailyTrack(
            holding_id=holding.id,
            stock_code=code,
            track_date=trade_date,
            close_price=price.close,
            daily_return_pct=round(daily_ret, 4),
            cumulative_pnl_pct=round(cum_pnl, 4),
            volume=price.volume,
            volume_ratio=round(vol_ratio, 4) if vol_ratio else None,
            regime_code=regime_code,
            sector_heat_score=sector_heat_score,
            index_close=index_close,
            news_event_count=news_count,
        )
        db.add(track)
        created += 1

    if created:
        db.commit()
        logger.info("Beta daily tracking: %d holdings tracked for %s", created, trade_date)
    return created
