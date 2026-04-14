"""Stock-news matching and price alignment service.

Proposal A: Link individual news articles to specific stocks, then
compute forward returns for each (news, stock) pair.

Matching strategies (in priority order):
  1. code_mention — 6-digit stock code appears in title/content
  2. name_mention — stock name appears in title/content
  3. event_affected — NewsAgent already identified affected_codes
  4. concept_match — article keywords overlap with stock concepts
"""

import re
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy import text, func
from sqlalchemy.orm import Session

from api.models.news_stock import NewsStockLink, NewsPriceAligned
from api.models.news_agent import NewsEvent
from api.models.stock import Stock, DailyPrice

logger = logging.getLogger(__name__)

# Match 6-digit A-share stock codes (000xxx, 002xxx, 300xxx, 600xxx, 601xxx, 603xxx, 688xxx)
CODE_PATTERN = re.compile(r"(?<!\d)(00[0-3]\d{3}|002\d{3}|300\d{3}|30[1-9]\d{3}|60[0-3]\d{3}|688\d{3})(?!\d)")


def match_news_to_stocks(db: Session, lookback_hours: float = 48.0, limit: int = 5000) -> dict:
    """Scan recent news_archive articles and link them to stocks.

    Args:
        db: SQLAlchemy session
        lookback_hours: How far back to scan
        limit: Max articles to process per run

    Returns:
        Stats dict with match counts per type.
    """
    cutoff = datetime.now() - timedelta(hours=lookback_hours)

    # Fetch unlinked articles (not yet in news_stock_links)
    rows = db.execute(text("""
        SELECT na.id, na.title, na.content, na.keywords, na.publish_time
        FROM news_archive na
        WHERE na.created_at >= :cutoff
        AND na.id NOT IN (SELECT DISTINCT news_id FROM news_stock_links)
        ORDER BY na.created_at DESC
        LIMIT :lim
    """), {"cutoff": cutoff, "lim": limit}).fetchall()

    if not rows:
        logger.info("NewsStockMatcher: no new articles to process")
        return {"total": 0, "linked": 0}

    # Load stock name→code mapping
    stocks = db.query(Stock.code, Stock.name).all()
    name_to_code = {}
    for code, name in stocks:
        if name and len(name) >= 2:
            # Use shortest unambiguous name (at least 2 chars)
            clean = name.replace("*ST", "").replace("ST", "").strip()
            if len(clean) >= 2:
                name_to_code[clean] = code
            name_to_code[name] = code

    stats = {"total": len(rows), "linked": 0, "code_mention": 0, "name_mention": 0}
    batch = []

    for row in rows:
        news_id = row[0]
        title = row[1] or ""
        content = row[2] or ""
        text_combined = title + " " + content[:500]  # limit content scan length

        matched_codes = set()

        # Strategy 1: Code mention
        codes_found = CODE_PATTERN.findall(text_combined)
        for code in codes_found:
            # Verify it's a real stock
            exists = db.query(Stock.code).filter(Stock.code == code).first()
            if exists and code not in matched_codes:
                batch.append(NewsStockLink(
                    news_id=news_id, stock_code=code,
                    match_type="code_mention", relevance_score=1.0,
                ))
                matched_codes.add(code)
                stats["code_mention"] += 1

        # Strategy 2: Name mention (search title first, then content[:300])
        for name, code in name_to_code.items():
            if code in matched_codes:
                continue
            if name in title:
                batch.append(NewsStockLink(
                    news_id=news_id, stock_code=code,
                    match_type="name_mention", relevance_score=0.9,
                ))
                matched_codes.add(code)
                stats["name_mention"] += 1
            elif name in content[:300]:
                batch.append(NewsStockLink(
                    news_id=news_id, stock_code=code,
                    match_type="name_mention", relevance_score=0.7,
                ))
                matched_codes.add(code)
                stats["name_mention"] += 1

        if matched_codes:
            stats["linked"] += 1

        # Batch commit every 500 articles
        if len(batch) >= 500:
            db.bulk_save_objects(batch)
            db.commit()
            batch = []

    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    logger.info(
        "NewsStockMatcher: %d articles → %d linked (code=%d, name=%d)",
        stats["total"], stats["linked"], stats["code_mention"], stats["name_mention"],
    )
    return stats


def link_from_events(db: Session, lookback_hours: float = 48.0) -> int:
    """Strategy 3: Link stocks from NewsAgent events' affected_codes."""
    cutoff = datetime.now() - timedelta(hours=lookback_hours)
    events = (
        db.query(NewsEvent)
        .filter(NewsEvent.created_at >= cutoff)
        .filter(NewsEvent.affected_codes.isnot(None))
        .all()
    )

    added = 0
    for evt in events:
        codes = evt.affected_codes or []
        if not codes or not evt.news_id:
            continue
        for code in codes:
            if not isinstance(code, str) or len(code) != 6:
                continue
            exists = (
                db.query(NewsStockLink)
                .filter_by(news_id=evt.news_id, stock_code=code)
                .first()
            )
            if not exists:
                db.add(NewsStockLink(
                    news_id=evt.news_id, stock_code=code,
                    match_type="event_affected", relevance_score=0.85,
                ))
                added += 1

    if added:
        db.commit()
    logger.info("NewsStockMatcher: %d event-based links added", added)
    return added


def align_news_prices(db: Session, trade_date: str) -> int:
    """Align linked news to trading day and compute forward returns.

    For each (news_id, stock_code) in news_stock_links that hasn't been
    aligned yet, find the nearest trading day and compute T+0/1/3/5 returns.

    Args:
        trade_date: Current trading date (YYYY-MM-DD)

    Returns:
        Number of alignments created.
    """
    # Get unaligned links (include sentiment_score for sentiment labeling)
    unaligned = db.execute(text("""
        SELECT nsl.news_id, nsl.stock_code, na.publish_time, na.sentiment_score
        FROM news_stock_links nsl
        JOIN news_archive na ON nsl.news_id = na.id
        WHERE (nsl.news_id, nsl.stock_code) NOT IN (
            SELECT news_id, stock_code FROM news_price_aligned
        )
        LIMIT 10000
    """)).fetchall()

    if not unaligned:
        return 0

    # Get all trading dates for lookups
    dates_rows = db.execute(text(
        "SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date"
    )).fetchall()
    all_dates = [str(r[0]) for r in dates_rows]
    date_idx = {d: i for i, d in enumerate(all_dates)}

    aligned = 0
    batch = []

    # Pre-load news_events impact_direction by news_id (more accurate sentiment)
    event_sentiment: dict[int, str] = {}
    news_ids = [r[0] for r in unaligned]
    if news_ids:
        evt_rows = db.execute(text("""
            SELECT news_id, impact_direction FROM news_events
            WHERE news_id IN :ids AND impact_direction IS NOT NULL
        """), {"ids": tuple(news_ids[:5000])}).fetchall()
        for eid, direction in evt_rows:
            event_sentiment[eid] = direction  # positive/negative/neutral

    for news_id, stock_code, publish_time, article_sentiment_score in unaligned:
        # Determine which trading day this news maps to
        pub_date = _extract_date(publish_time)
        if not pub_date:
            pub_date = trade_date  # fallback to current date

        td = _find_nearest_trade_date(pub_date, date_idx)
        if not td:
            continue

        i = date_idx[td]

        # Get closes for this stock around the trade date
        price_rows = db.execute(text("""
            SELECT trade_date, close * COALESCE(adj_factor, 1.0) as close FROM daily_prices
            WHERE stock_code = :code
            AND trade_date >= :start AND trade_date <= :end
            ORDER BY trade_date
        """), {
            "code": stock_code,
            "start": all_dates[max(0, i - 1)],
            "end": all_dates[min(len(all_dates) - 1, i + 5)],
        }).fetchall()

        closes = {str(r[0]): float(r[1]) for r in price_rows}
        if td not in closes:
            continue

        # Compute returns
        prev_d = all_dates[i - 1] if i > 0 else None
        ret_t0 = _pct(closes.get(prev_d), closes.get(td)) if prev_d else None

        def _fwd_ret(offset):
            j = i + offset
            if 0 <= j < len(all_dates) and all_dates[j] in closes:
                return _pct(closes.get(td), closes.get(all_dates[j]))
            return None

        # Derive sentiment label: prefer news_events (AI-classified), fallback to article score
        sentiment = event_sentiment.get(news_id)
        if not sentiment and article_sentiment_score is not None:
            if article_sentiment_score > 55:
                sentiment = "positive"
            elif article_sentiment_score < 45:
                sentiment = "negative"
            else:
                sentiment = "neutral"

        batch.append(NewsPriceAligned(
            news_id=news_id,
            stock_code=stock_code,
            trade_date=td,
            publish_time=publish_time,
            sentiment=sentiment,
            ret_t0=ret_t0,
            ret_t1=_fwd_ret(1),
            ret_t3=_fwd_ret(3),
            ret_t5=_fwd_ret(5),
        ))
        aligned += 1

        if len(batch) >= 500:
            db.bulk_save_objects(batch)
            db.commit()
            batch = []

    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    logger.info("NewsPriceAlignment: %d alignments created", aligned)
    return aligned


def compute_stock_news_sentiment(db: Session, stock_code: str, window_days: int = 3) -> Optional[float]:
    """Compute rolling news sentiment score for a stock.

    Returns a score in [-1.0, +1.0]:
      +1.0 = all news positive
      -1.0 = all news negative
       0.0 = balanced or no news

    Used by Proposal C as strategy indicator (NEWS_SENTIMENT_3D, etc.)
    """
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")

    # Count positive/negative/neutral aligned news
    rows = db.execute(text("""
        SELECT npa.sentiment, COUNT(*) as cnt
        FROM news_price_aligned npa
        WHERE npa.stock_code = :code AND npa.trade_date >= :cutoff
        AND npa.sentiment IS NOT NULL
        GROUP BY npa.sentiment
    """), {"code": stock_code, "cutoff": cutoff}).fetchall()

    if not rows:
        return None

    counts = {r[0]: r[1] for r in rows}
    pos = counts.get("positive", 0)
    neg = counts.get("negative", 0)
    total = sum(counts.values())
    if total == 0:
        return None

    return round((pos - neg) / total, 4)


def _extract_date(publish_time: Optional[str]) -> Optional[str]:
    """Extract YYYY-MM-DD from publish_time string."""
    if not publish_time:
        return None
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        pass
    # Try YYYY-MM-DD prefix
    if len(publish_time) >= 10 and publish_time[4] == "-":
        return publish_time[:10]
    return None


def _find_nearest_trade_date(d: str, date_idx: dict) -> Optional[str]:
    """Find the nearest trading date on or after d."""
    if d in date_idx:
        return d
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return None
    for _ in range(7):
        ds = dt.isoformat()
        if ds in date_idx:
            return ds
        dt += timedelta(days=1)
    return None


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or a == 0:
        return None
    return round((b - a) / a, 6)
