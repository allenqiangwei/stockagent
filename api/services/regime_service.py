"""Market regime computation service.

Computes weekly market regime labels from Shanghai Composite Index (000001)
using the existing MarketRegimeDetector. Results are cached in the
market_regimes DB table.
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from api.models.market_regime import MarketRegimeLabel
from api.services.data_collector import DataCollector
from src.signals.market_regime import MarketRegimeDetector

logger = logging.getLogger(__name__)

# Lookback window for regime detection (trading days before week end)
_LOOKBACK_DAYS = 60  # calendar days → ~40 trading days, detector needs >=30


def _fetch_index_daily(
    db: Session, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """Get Shanghai Composite Index daily OHLCV via DataCollector (DB-cached).

    Args:
        db: SQLAlchemy session
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    try:
        collector = DataCollector(db)
        return collector.get_index_daily_df("000001.SH", start_date, end_date)
    except Exception as e:
        logger.error("Failed to fetch Shanghai Index data: %s", e)
        return None


def _monday_of(d: date) -> date:
    """Return the Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


def _friday_of(d: date) -> date:
    """Return the Friday of the week containing date d."""
    return d + timedelta(days=4 - d.weekday())


def compute_weekly_regimes(
    db: Session,
    start_date: str,
    end_date: str,
) -> List[dict]:
    """Compute weekly market regime labels from Shanghai Index.

    Fetches index data (with lookback buffer), groups by natural week,
    and runs MarketRegimeDetector on each week's trailing window.

    Args:
        db: SQLAlchemy session
        start_date: YYYY-MM-DD — first week's Monday (or earlier)
        end_date: YYYY-MM-DD — last week's Friday (or later)

    Returns:
        List of dicts with keys: week_start, week_end, regime, confidence,
        trend_strength, volatility, breadth, index_return_pct
    """
    req_start = date.fromisoformat(start_date)
    req_end = date.fromisoformat(end_date)

    # Fetch extra lookback data before start_date for the detector
    fetch_start = (req_start - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    fetch_end = req_end.isoformat()

    df = _fetch_index_daily(db, fetch_start, fetch_end)
    if df is None or df.empty:
        logger.warning("No index data available for regime computation")
        return []

    # Parse dates
    df["_date"] = pd.to_datetime(df["date"])
    df = df.sort_values("_date").reset_index(drop=True)

    # Build week boundaries
    first_monday = _monday_of(req_start)
    last_friday = _friday_of(req_end)

    detector = MarketRegimeDetector()
    results = []

    current_monday = first_monday
    while current_monday <= last_friday:
        current_friday = current_monday + timedelta(days=4)

        # Get data up to this week's last trading day
        week_mask = df["_date"].dt.date <= current_friday
        available = df[week_mask]

        if len(available) < 30:
            current_monday += timedelta(days=7)
            continue

        # Use the last 30+ rows for detection
        window = available.tail(45)  # ~45 trading days for robust ADX/ATR

        # Detect regime (no breadth data for index, default 0.5)
        regime = detector.detect(index_df=window)

        # Compute weekly index return
        week_data = df[
            (df["_date"].dt.date >= current_monday) &
            (df["_date"].dt.date <= current_friday)
        ]
        if len(week_data) >= 1:
            week_open = float(week_data.iloc[0]["open"])
            week_close = float(week_data.iloc[-1]["close"])
            index_return = (week_close - week_open) / week_open * 100 if week_open > 0 else 0.0
        else:
            index_return = 0.0

        results.append({
            "week_start": current_monday,
            "week_end": current_friday,
            "regime": regime.regime,
            "confidence": round(regime.confidence, 4),
            "trend_strength": round(regime.trend_strength, 4),
            "volatility": round(regime.volatility, 4),
            "breadth": round(regime.breadth, 4),
            "index_return_pct": round(index_return, 4),
        })

        current_monday += timedelta(days=7)

    logger.info("Computed %d weekly regimes (%s ~ %s)", len(results), start_date, end_date)
    return results


def ensure_regimes(db: Session, start_date: str, end_date: str) -> int:
    """Ensure regime labels exist for the given date range. Only computes missing weeks.

    Args:
        db: SQLAlchemy session
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD

    Returns:
        Number of new weeks computed and stored
    """
    req_start = date.fromisoformat(start_date)
    req_end = date.fromisoformat(end_date)

    # Check what's already in DB
    existing = (
        db.query(MarketRegimeLabel.week_start)
        .filter(
            MarketRegimeLabel.week_start >= _monday_of(req_start),
            MarketRegimeLabel.week_start <= _friday_of(req_end),
        )
        .all()
    )
    existing_weeks = {row.week_start for row in existing}

    # Compute all weeks
    all_regimes = compute_weekly_regimes(db, start_date, end_date)

    # Insert only missing
    inserted = 0
    for r in all_regimes:
        ws = r["week_start"]
        if isinstance(ws, date) and ws in existing_weeks:
            continue
        db.add(MarketRegimeLabel(**r))
        inserted += 1

    if inserted > 0:
        db.commit()
        logger.info("Inserted %d new regime labels", inserted)

    return inserted


def get_regime_map(db: Session, start_date: str, end_date: str) -> Dict[str, str]:
    """Return {date_str: regime} mapping for every calendar day in the range.

    Each day maps to its containing week's regime label.

    Args:
        db: SQLAlchemy session
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD

    Returns:
        Dict mapping "YYYY-MM-DD" to regime string
    """
    req_start = date.fromisoformat(start_date)
    req_end = date.fromisoformat(end_date)

    rows = (
        db.query(MarketRegimeLabel)
        .filter(
            MarketRegimeLabel.week_start >= _monday_of(req_start) - timedelta(days=7),
            MarketRegimeLabel.week_end <= _friday_of(req_end) + timedelta(days=7),
        )
        .order_by(MarketRegimeLabel.week_start)
        .all()
    )

    regime_map: Dict[str, str] = {}
    for row in rows:
        ws = row.week_start if isinstance(row.week_start, date) else date.fromisoformat(str(row.week_start))
        we = row.week_end if isinstance(row.week_end, date) else date.fromisoformat(str(row.week_end))
        d = ws
        while d <= we:
            ds = d.isoformat()
            if start_date <= ds <= end_date:
                regime_map[ds] = row.regime
            d += timedelta(days=1)

    return regime_map


def get_regime_summary(db: Session, start_date: str, end_date: str) -> dict:
    """Return regime distribution and total index return for the period.

    Returns:
        {
            "regimes": {regime: {"weeks": N, "index_return_pct": X}},
            "total_weeks": N,
            "total_index_return_pct": X,
        }
    """
    req_start = date.fromisoformat(start_date)
    req_end = date.fromisoformat(end_date)

    rows = (
        db.query(MarketRegimeLabel)
        .filter(
            MarketRegimeLabel.week_start >= _monday_of(req_start),
            MarketRegimeLabel.week_end <= _friday_of(req_end),
        )
        .order_by(MarketRegimeLabel.week_start)
        .all()
    )

    regimes: Dict[str, dict] = {}
    total_return = 0.0
    for row in rows:
        r = row.regime
        if r not in regimes:
            regimes[r] = {"weeks": 0, "index_return_pct": 0.0}
        regimes[r]["weeks"] += 1
        regimes[r]["index_return_pct"] += row.index_return_pct
        total_return += row.index_return_pct

    # Round values
    for v in regimes.values():
        v["index_return_pct"] = round(v["index_return_pct"], 2)

    return {
        "regimes": regimes,
        "total_weeks": len(rows),
        "total_index_return_pct": round(total_return, 2),
    }
