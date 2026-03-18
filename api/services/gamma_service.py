"""Gamma Factor service — fetch 缠论 data from chanlun-pro and compute scores.

chanlun-pro runs on localhost:9900 and provides TradingView-compatible
chart data including 缠论 analysis: MMD (买卖点), BC (背驰), BI (笔),
XD (段), ZS (中枢).
"""

import logging
import time
import urllib.parse
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_session = requests.Session()
_logged_in = False
_CHANLUN_BASE = "http://127.0.0.1:9900"
_TIMEOUT = 5
_consecutive_failures = 0
_CIRCUIT_BREAKER_THRESHOLD = 10


# ---------------------------------------------------------------------------
# HTTP client helpers
# ---------------------------------------------------------------------------

def _ensure_login() -> bool:
    global _logged_in
    try:
        resp = _session.get(
            f"{_CHANLUN_BASE}/login",
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        _logged_in = resp.status_code == 200
        if _logged_in:
            logger.debug("chanlun-pro login ok")
        return _logged_in
    except Exception as e:
        logger.warning("chanlun-pro login failed: %s", e)
        _logged_in = False
        return False


def _fetch_history(symbol: str, resolution: str, from_ts: int, to_ts: int) -> dict | None:
    global _consecutive_failures, _logged_in

    if _consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        return None

    if not _logged_in:
        if not _ensure_login():
            _consecutive_failures += 1
            return None

    encoded_symbol = urllib.parse.quote(symbol, safe="")

    url = (
        f"{_CHANLUN_BASE}/tv/history"
        f"?symbol={encoded_symbol}"
        f"&resolution={resolution}"
        f"&from={from_ts}&to={to_ts}"
        f"&firstDataRequest=true"
    )

    try:
        resp = _session.get(url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            _logged_in = False
            if not _ensure_login():
                _consecutive_failures += 1
                return None
            resp = _session.get(url, timeout=_TIMEOUT)
            if resp.status_code != 200:
                _consecutive_failures += 1
                return None

        _consecutive_failures = 0
        return resp.json()
    except Exception as e:
        _consecutive_failures += 1
        logger.warning("chanlun-pro fetch failed (%s %s): %s", symbol, resolution, e)
        return None


def stockagent_code_to_chanlun(code: str) -> str:
    """Convert a 6-digit A-share code to chanlun-pro symbol format."""
    if code.startswith(("6", "9")):
        prefix = "SH"
    elif code.startswith(("4", "8")):
        prefix = "BJ"
    else:
        prefix = "SZ"
    return f"a:{prefix}.{code}"


def reset_circuit_breaker():
    """Reset the consecutive failure counter (e.g. after service recovery)."""
    global _consecutive_failures
    _consecutive_failures = 0


# ---------------------------------------------------------------------------
# Scoring tables
# ---------------------------------------------------------------------------

_DAILY_MMD_SCORES: dict[str, dict[str, int]] = {
    "1B":  {"笔": 45, "段": 42},
    "2B":  {"笔": 35, "段": 33},
    "L2B": {"笔": 30, "段": 28},
    "3B":  {"笔": 25, "段": 23},
    "L3B": {"笔": 20, "段": 18},
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_mmds(mmds: list) -> list[tuple[str, str, int, float]]:
    """Parse MMD list into (mmd_type, level, timestamp, price) tuples.

    Each MMD entry from chanlun-pro looks like:
        {"points": {"price": 12.5, "time": 1710000000}, "text": "笔:1B"}
    The 'text' field may contain multiple types separated by commas,
    each prefixed with level + colon.

    Returns a flat list of (mmd_type, level, timestamp, price).
    """
    results = []
    if not mmds:
        return results

    for item in mmds:
        try:
            ts = int(item.get("points", {}).get("time", 0))
            price = float(item.get("points", {}).get("price", 0.0))
            text = str(item.get("text", ""))

            if not text:
                continue

            # Handle "笔:2B,1B" or "段:1S" or "笔:2S,1S"
            if ":" in text:
                parts = text.split(":")
                level = parts[0]  # "笔" or "段"
                types_str = parts[1] if len(parts) > 1 else ""
                for mmd_type in types_str.split(","):
                    mmd_type = mmd_type.strip()
                    if mmd_type:
                        results.append((mmd_type, level, ts, price))
            else:
                # Bare type without level prefix
                results.append((text.strip(), "笔", ts, price))
        except (ValueError, TypeError, AttributeError):
            continue

    return results


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def _compute_daily_strength(
    mmds: list[tuple[str, str, int, float]],
    now_ts: int,
) -> tuple[float, str | None, str | None, int]:
    """Compute daily strength score from buy-point MMDs.

    Returns (score, mmd_type, mmd_level, mmd_age_days).
    - Filter buy points only (ending with 'B')
    - Take most recent buy point
    - Apply time decay: <=5 trading days = 100%, 6-10 = 50%, >10 = 25%
    - Trading days approximation: natural_days * 5/7
    """
    buy_mmds = [(t, lvl, ts, p) for t, lvl, ts, p in mmds if t.endswith("B")]
    if not buy_mmds:
        return 0.0, None, None, 0

    # Sort by timestamp descending, take most recent
    buy_mmds.sort(key=lambda x: x[2], reverse=True)
    mmd_type, level, ts, _price = buy_mmds[0]

    # Calculate age in trading days
    natural_days = max(0, (now_ts - ts) / 86400)
    trading_days = int(natural_days * 5 / 7)

    # Base score from lookup table
    base_score = _DAILY_MMD_SCORES.get(mmd_type, {}).get(level, 0)

    # Time decay
    if trading_days <= 5:
        decay = 1.0
    elif trading_days <= 10:
        decay = 0.5
    else:
        decay = 0.25

    score = base_score * decay
    return score, mmd_type, level, trading_days


def _compute_weekly_resonance(
    mmds: list[tuple[str, str, int, float]],
    bis: list,
    bar_times: list[int],
) -> tuple[float, str | None, str | None]:
    """Compute weekly resonance score.

    Priority evaluation (first match returns):
    1. Buy point in last 4 bars -> 30
    2. Sell point in last 4 bars -> 0
    3. Last bi direction = up -> 20
    4. Default -> 10

    Returns (score, weekly_mmd_type, weekly_mmd_level).
    """
    # Empty bar_times — no data to evaluate
    if not bar_times:
        return 10.0, None, None

    # Determine the cutoff timestamp for "last 4 bars"
    if len(bar_times) >= 4:
        cutoff_ts = bar_times[-4]
    else:
        cutoff_ts = bar_times[0]

    # Check for recent buy/sell points
    recent_buys = [(t, lvl, ts, p) for t, lvl, ts, p in mmds if t.endswith("B") and ts >= cutoff_ts]
    recent_sells = [(t, lvl, ts, p) for t, lvl, ts, p in mmds if t.endswith("S") and ts >= cutoff_ts]

    if recent_buys:
        # Take the most recent buy
        recent_buys.sort(key=lambda x: x[2], reverse=True)
        mmd_type, level, _, _ = recent_buys[0]
        return 30.0, mmd_type, level

    if recent_sells:
        recent_sells.sort(key=lambda x: x[2], reverse=True)
        mmd_type, level, _, _ = recent_sells[0]
        return 0.0, mmd_type, level

    # Check last bi direction — bis is a list of coordinate pairs
    if bis and len(bis) > 0:
        last_bi = bis[-1]
        if isinstance(last_bi, list) and len(last_bi) >= 2:
            start_price = last_bi[0].get("price", 0) if isinstance(last_bi[0], dict) else 0
            end_price = last_bi[1].get("price", 0) if isinstance(last_bi[1], dict) else 0
            if end_price > start_price:
                return 20.0, None, None

    return 10.0, None, None


def _compute_structure_health(
    mmds: list[tuple[str, str, int, float]],
    bcs: list,
    bi_zss: list,
    bar_times: list[int],
    current_price: float,
) -> float:
    """Compute structure health score (0-25).

    - 背驰确认: last BC within 10 bars = 10 pts
    - 中枢距离: below pivot = 8, inside = 4, above = 0
    - 买点密度: buy points in last 30 bars, >=3 = 7, 2 = 5, 1 = 3
    """
    score = 0.0

    # Empty bar_times — skip BC and buy-density calculations
    if not bar_times:
        # Only evaluate ZS distance if possible
        if bi_zss and current_price > 0:
            last_zs = bi_zss[-1]
            if isinstance(last_zs, list) and len(last_zs) >= 2:
                zs_prices = [p.get("price", 0) for p in last_zs if isinstance(p, dict)]
                if zs_prices:
                    zs_low = min(zs_prices)
                    zs_high = max(zs_prices)
                    if current_price < zs_low:
                        score += 8.0
                    elif zs_low <= current_price <= zs_high:
                        score += 4.0
        return min(score, 25.0)

    # Cutoff timestamps
    cutoff_10 = bar_times[-10] if len(bar_times) >= 10 else bar_times[0]
    cutoff_30 = bar_times[-30] if len(bar_times) >= 30 else bar_times[0]

    # 1. 背驰确认 (BC within last 10 bars)
    if bcs:
        for bc in reversed(bcs):
            try:
                bc_ts = int(bc.get("points", {}).get("time", 0))
                if bc_ts >= cutoff_10:
                    score += 10.0
                    break
            except (ValueError, TypeError, AttributeError):
                continue

    # 2. 中枢距离 (ZS pivot distance)
    if bi_zss and current_price > 0:
        last_zs = bi_zss[-1]
        if isinstance(last_zs, list) and len(last_zs) >= 2:
            zs_prices = [p.get("price", 0) for p in last_zs if isinstance(p, dict)]
            if zs_prices:
                zs_low = min(zs_prices)
                zs_high = max(zs_prices)
                if current_price < zs_low:
                    score += 8.0  # Below pivot zone
                elif zs_low <= current_price <= zs_high:
                    score += 4.0  # Inside pivot zone
                # Above = 0

    # 3. 买点密度 (buy point density in last 30 bars)
    buy_count = sum(1 for t, _, ts, _ in mmds if t.endswith("B") and ts >= cutoff_30)
    if buy_count >= 3:
        score += 7.0
    elif buy_count == 2:
        score += 5.0
    elif buy_count == 1:
        score += 3.0

    return min(score, 25.0)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_gamma(stock_code: str, trade_date: str) -> dict | None:
    """Compute gamma score for a stock on a given date.

    Args:
        stock_code: 6-digit A-share code (e.g. '600519')
        trade_date: date string YYYY-MM-DD

    Returns:
        dict with all fields matching GammaSnapshot model, or None on failure.
    """
    symbol = stockagent_code_to_chanlun(stock_code)

    # Time range: ~1 year lookback for enough bars
    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError:
        logger.warning("Invalid trade_date format: %s", trade_date)
        return None

    to_ts = int(dt.timestamp()) + 86400  # end of day
    from_ts = to_ts - 365 * 86400  # 1 year back

    # Fetch daily and weekly data
    daily_data = _fetch_history(symbol, "D", from_ts, to_ts)
    weekly_data = _fetch_history(symbol, "W", from_ts, to_ts)

    if not daily_data or daily_data.get("s") == "no_data":
        logger.info("No daily data for %s on %s", stock_code, trade_date)
        return None

    # Extract components — defensive int() casts on timestamps
    daily_bar_times = [int(t) for t in daily_data.get("t", [])]
    daily_mmds_raw = daily_data.get("mmds", [])
    daily_bcs = daily_data.get("bcs", [])
    daily_bis = daily_data.get("bis", [])
    daily_bi_zss = daily_data.get("bi_zss", [])

    # Current price from last close
    closes = daily_data.get("c", [])
    current_price = float(closes[-1]) if closes else 0.0

    now_ts = int(dt.timestamp())

    # Parse daily MMDs
    daily_mmds = _parse_mmds(daily_mmds_raw)

    # Compute daily strength
    daily_score, d_mmd_type, d_mmd_level, d_mmd_age = _compute_daily_strength(
        daily_mmds, now_ts
    )

    # Weekly resonance
    weekly_score = 10.0
    w_mmd_type = None
    w_mmd_level = None
    if weekly_data and weekly_data.get("s") != "no_data":
        weekly_bar_times = [int(t) for t in weekly_data.get("t", [])]
        weekly_mmds_raw = weekly_data.get("mmds", [])
        weekly_bis = weekly_data.get("bis", [])
        weekly_mmds = _parse_mmds(weekly_mmds_raw)
        weekly_score, w_mmd_type, w_mmd_level = _compute_weekly_resonance(
            weekly_mmds, weekly_bis, weekly_bar_times
        )

    # Structure health
    health_score = _compute_structure_health(
        daily_mmds, daily_bcs, daily_bi_zss, daily_bar_times, current_price
    )

    # Total gamma score
    gamma_score = daily_score + weekly_score + health_score

    # Count stats for raw data fields
    daily_bc_count = len(daily_bcs) if daily_bcs else 0
    daily_bi_zs_count = len(daily_bi_zss) if daily_bi_zss else 0

    # Last bi direction — bis is a list of coordinate pairs
    last_bi_dir = None
    if daily_bis:
        last_bi = daily_bis[-1]
        if isinstance(last_bi, list) and len(last_bi) >= 2:
            s = last_bi[0].get("price", 0) if isinstance(last_bi[0], dict) else 0
            e = last_bi[1].get("price", 0) if isinstance(last_bi[1], dict) else 0
            last_bi_dir = "up" if e > s else "down"
    daily_last_bi_dir = last_bi_dir

    return {
        "stock_code": stock_code,
        "snapshot_date": trade_date,
        "gamma_score": round(gamma_score, 2),
        "daily_strength": round(daily_score, 2),
        "weekly_resonance": round(weekly_score, 2),
        "structure_health": round(health_score, 2),
        "daily_mmd_type": d_mmd_type,
        "daily_mmd_level": d_mmd_level,
        "daily_mmd_age": d_mmd_age,
        "weekly_mmd_type": w_mmd_type,
        "weekly_mmd_level": w_mmd_level,
        "daily_bc_count": daily_bc_count,
        "daily_bi_zs_count": daily_bi_zs_count,
        "daily_last_bi_dir": daily_last_bi_dir,
    }
