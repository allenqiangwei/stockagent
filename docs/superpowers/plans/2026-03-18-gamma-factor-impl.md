# Gamma Factor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate 缠论 (Chan Theory) buy/sell point signals as a Gamma scoring factor alongside Alpha, with chanlun-pro HTTP API as data source.

**Architecture:** New `gamma_service.py` fetches 缠论 data from localhost:9900 and computes a 0-100 Gamma score across 3 dimensions (daily strength, weekly resonance, structure health). The score flows through the existing signal pipeline: scheduler → signal model → beta_scorer (renamed combined formula) → trade plans → frontend.

**Tech Stack:** Python 3.11, SQLAlchemy ORM, PostgreSQL, requests (HTTP client), Next.js/React (frontend)

**Spec:** `docs/superpowers/specs/2026-03-18-gamma-factor-design.md`

---

## Chunk 1: Data Model & Gamma Service

### Task 1: Create GammaSnapshot ORM Model

**Files:**
- Create: `api/models/gamma_factor.py`

- [ ] **Step 1: Create the GammaSnapshot model file**

```python
"""Gamma Factor ORM model — 缠论 snapshot per stock per day."""

from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GammaSnapshot(Base):
    __tablename__ = "gamma_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    snapshot_date: Mapped[str] = mapped_column(String(10))

    # Gamma scoring dimensions
    gamma_score: Mapped[float] = mapped_column(Float, default=0.0)
    daily_strength: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_resonance: Mapped[float] = mapped_column(Float, default=0.0)
    structure_health: Mapped[float] = mapped_column(Float, default=0.0)

    # Raw 缠论 signal data (for ML features)
    daily_mmd_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    daily_mmd_level: Mapped[str | None] = mapped_column(String(5), nullable=True)
    daily_mmd_age: Mapped[int] = mapped_column(Integer, default=0)
    weekly_mmd_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    weekly_mmd_level: Mapped[str | None] = mapped_column(String(5), nullable=True)
    daily_bc_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_bi_zs_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_last_bi_dir: Mapped[str | None] = mapped_column(String(5), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_gamma_snap_code_date", "stock_code", "snapshot_date", unique=True),
    )
```

- [ ] **Step 2: Register the model in the models package**

`api/models/__init__.py` is currently empty. Add the import so `Base.metadata` includes the new table:
```python
from .gamma_factor import GammaSnapshot  # noqa: F401
```

- [ ] **Step 3: Add gamma_score to TradingSignal**

Insert a new line after `api/models/signal.py:17` (after `final_score`):
```python
    gamma_score: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 4: Add gamma_score to BotTradePlan**

Insert a new line after `api/models/bot_trading.py:103` (after `combined_score`, before `__table_args__`):
```python
    gamma_score: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 5: Apply DB migration**

Run Alembic or auto-create tables:
```bash
cd /Users/allenqiang/stockagent
python3 -c "
from api.models.base import engine, Base
from api.models.gamma_factor import GammaSnapshot
from api.models.signal import TradingSignal
from api.models.bot_trading import BotTradePlan
Base.metadata.create_all(engine)
print('Tables created/updated')
"
```

Then add missing columns to existing tables:
```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from sqlalchemy import text
from api.models.base import engine

with engine.connect() as conn:
    # Add gamma_score to trading_signals_v2
    try:
        conn.execute(text('ALTER TABLE trading_signals_v2 ADD COLUMN gamma_score FLOAT'))
        conn.commit()
        print('Added gamma_score to trading_signals_v2')
    except Exception as e:
        print(f'trading_signals_v2: {e}')
        conn.rollback()

    # Add gamma_score to bot_trade_plans
    try:
        conn.execute(text('ALTER TABLE bot_trade_plans ADD COLUMN gamma_score FLOAT'))
        conn.commit()
        print('Added gamma_score to bot_trade_plans')
    except Exception as e:
        print(f'bot_trade_plans: {e}')
        conn.rollback()
"
```

- [ ] **Step 6: Verify tables exist**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from sqlalchemy import inspect
from api.models.base import engine
insp = inspect(engine)
print('gamma_snapshots:', 'gamma_snapshots' in insp.get_table_names())
cols = {c['name'] for c in insp.get_columns('trading_signals_v2')}
print('gamma_score in signals:', 'gamma_score' in cols)
cols2 = {c['name'] for c in insp.get_columns('bot_trade_plans')}
print('gamma_score in plans:', 'gamma_score' in cols2)
"
```
Expected: all three `True`.

- [ ] **Step 7: Commit**

```bash
git add api/models/gamma_factor.py api/models/signal.py api/models/bot_trading.py
git commit -m "feat(gamma): add GammaSnapshot model and gamma_score columns"
```

---

### Task 2: Create Gamma Service — HTTP Client

**Files:**
- Create: `api/services/gamma_service.py`

- [ ] **Step 1: Create gamma_service.py with HTTP client and code mapping**

```python
"""Gamma Factor service — fetch 缠论 data from chanlun-pro and compute scores.

chanlun-pro runs on localhost:9900 and provides TradingView-compatible
chart data including 缠论 analysis: MMD (买卖点), BC (背驰), BI (笔),
XD (段), ZS (中枢).
"""

import logging
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# ── Module-level session (lazy login) ──────────────────────────

_session = requests.Session()
_logged_in = False
_CHANLUN_BASE = "http://127.0.0.1:9900"
_TIMEOUT = 5  # seconds
_consecutive_failures = 0
_CIRCUIT_BREAKER_THRESHOLD = 10


def _ensure_login() -> bool:
    """Login to chanlun-pro (empty password auto-login). Returns success."""
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
    """Fetch TradingView history data from chanlun-pro.

    Args:
        symbol: chanlun format e.g. "a:SH.600519"
        resolution: "1D" for daily, "1W" for weekly
        from_ts: Unix timestamp start
        to_ts: Unix timestamp end

    Returns:
        JSON response dict or None on failure.
    """
    global _consecutive_failures, _logged_in

    if _consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        return None

    if not _logged_in:
        if not _ensure_login():
            _consecutive_failures += 1
            return None

    import urllib.parse
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
            # Try re-login once
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
    """Convert stockagent code to chanlun-pro symbol.

    600519 → a:SH.600519, 002495 → a:SZ.002495, 830799 → a:BJ.830799
    """
    if code.startswith(("6", "9")):
        prefix = "SH"
    elif code.startswith(("4", "8")):
        prefix = "BJ"
    else:
        prefix = "SZ"
    return f"a:{prefix}.{code}"


def reset_circuit_breaker():
    """Reset the circuit breaker counter (call at start of each daily run)."""
    global _consecutive_failures
    _consecutive_failures = 0
```

- [ ] **Step 2: Commit HTTP client**

```bash
git add api/services/gamma_service.py
git commit -m "feat(gamma): add HTTP client for chanlun-pro API"
```

---

### Task 3: Gamma Scoring Algorithm

**Files:**
- Modify: `api/services/gamma_service.py`

- [ ] **Step 1: Add scoring constants and helper**

Append to `gamma_service.py`:

```python
# ── Scoring tables ─────────────────────────────────────────────

# Daily MMD type → base score (dimension 1, max 45)
_DAILY_MMD_SCORES: dict[str, dict[str, int]] = {
    "1B":  {"笔": 45, "段": 42},
    "2B":  {"笔": 35, "段": 33},
    "L2B": {"笔": 30, "段": 28},
    "3B":  {"笔": 25, "段": 23},
    "L3B": {"笔": 20, "段": 18},
}


def _parse_mmds(mmds: list[dict]) -> list[tuple[str, str, int, float]]:
    """Parse MMD list into (mmd_type, level, timestamp, price) tuples.

    Input format: {"points": {"price": float, "time": int}, "text": "笔:1B"}
    A single text can contain multiple types: "笔:2S,1S"
    """
    results = []
    for m in mmds:
        text = m.get("text", "")
        pts = m.get("points", {})
        ts = int(pts.get("time", 0))  # Defensive cast — API may return str
        price = float(pts.get("price", 0.0))
        if ":" not in text:
            continue
        level, types_str = text.split(":", 1)
        for t in types_str.split(","):
            t = t.strip()
            if t:
                results.append((t, level, ts, price))
    return results


def _compute_daily_strength(mmds: list[dict], now_ts: int) -> tuple[float, str | None, str | None, int]:
    """Compute daily strength score (0-45).

    Returns: (score, mmd_type, mmd_level, mmd_age_days)
    """
    parsed = _parse_mmds(mmds)
    # Filter buy points only
    buy_mmds = [(t, lvl, ts, p) for t, lvl, ts, p in parsed if t.endswith("B")]
    if not buy_mmds:
        return 0.0, None, None, 0

    # Most recent buy point
    buy_mmds.sort(key=lambda x: x[2], reverse=True)
    mmd_type, mmd_level, mmd_ts, _ = buy_mmds[0]

    base_score = _DAILY_MMD_SCORES.get(mmd_type, {}).get(mmd_level, 0)
    if base_score == 0:
        return 0.0, mmd_type, mmd_level, 0

    # Time decay (trading days approximation: natural days * 5/7)
    age_days = max(0, (now_ts - mmd_ts) // 86400)
    trading_days = int(age_days * 5 / 7)

    if trading_days <= 5:
        decay = 1.0
    elif trading_days <= 10:
        decay = 0.5
    else:
        decay = 0.25

    return round(base_score * decay, 1), mmd_type, mmd_level, trading_days


def _compute_weekly_resonance(mmds: list[dict], bis: list, bar_times: list[int]) -> tuple[float, str | None, str | None]:
    """Compute weekly resonance score (0-30).

    Priority evaluation order:
    1. Buy point in last 4 bars → 30
    2. Sell point in last 4 bars → 0
    3. Last bi direction = up → 20
    4. Default (in consolidation) → 10

    Returns: (score, weekly_mmd_type, weekly_mmd_level)
    """
    # Determine time boundary for "last 4 bars"
    if len(bar_times) >= 4:
        cutoff_ts = bar_times[-4]
    elif bar_times:
        cutoff_ts = bar_times[0]
    else:
        return 10.0, None, None  # No data, default

    parsed = _parse_mmds(mmds)
    recent = [(t, lvl, ts, p) for t, lvl, ts, p in parsed if ts >= cutoff_ts]

    recent_buys = [(t, lvl) for t, lvl, _, _ in recent if t.endswith("B")]
    recent_sells = [(t, lvl) for t, lvl, _, _ in recent if t.endswith("S")]

    # Priority 1: buy point
    if recent_buys:
        return 30.0, recent_buys[0][0], recent_buys[0][1]

    # Priority 2: sell point
    if recent_sells:
        return 0.0, recent_sells[0][0], recent_sells[0][1]

    # Priority 3: last bi direction = up
    if bis and len(bis) > 0:
        last_bi = bis[-1]
        if len(last_bi) >= 2:
            start_price = last_bi[0].get("price", 0) if isinstance(last_bi[0], dict) else 0
            end_price = last_bi[1].get("price", 0) if isinstance(last_bi[1], dict) else 0
            if end_price > start_price:
                return 20.0, None, None

    # Priority 4: default
    return 10.0, None, None


def _compute_structure_health(mmds: list[dict], bcs: list[dict], bi_zss: list, bar_times: list[int], current_price: float) -> float:
    """Compute structure health score (0-25).

    - 背驰确认 (bcs): 0-10
    - 中枢距离: 0-8
    - 买点密度: 0-7
    """
    score = 0.0

    # 1. 背驰确认 (0-10): last BC within 10 bars
    if bcs and bar_times and len(bar_times) >= 10:
        cutoff_10 = bar_times[-10]
        for bc in reversed(bcs):
            bc_ts = bc.get("points", {}).get("time", 0)
            if bc_ts >= cutoff_10:
                score += 10.0
                break

    # 2. 中枢距离 (0-8)
    if bi_zss and current_price > 0:
        last_zs = bi_zss[-1]
        if isinstance(last_zs, list) and len(last_zs) >= 2:
            zs_prices = [p.get("price", 0) for p in last_zs if isinstance(p, dict)]
            if zs_prices:
                zs_low = min(zs_prices)
                zs_high = max(zs_prices)
                if current_price < zs_low:
                    score += 8.0  # Below pivot zone — strong support
                elif zs_low <= current_price <= zs_high:
                    score += 4.0  # Inside pivot zone
                # Above pivot = 0

    # 3. 买点密度 (0-7): buy points in last 30 bars
    if bar_times and len(bar_times) >= 30:
        cutoff_30 = bar_times[-30]
    elif bar_times:
        cutoff_30 = bar_times[0]
    else:
        cutoff_30 = 0

    parsed = _parse_mmds(mmds)
    buy_count = sum(1 for t, _, ts, _ in parsed if t.endswith("B") and ts >= cutoff_30)
    if buy_count >= 3:
        score += 7.0
    elif buy_count == 2:
        score += 5.0
    elif buy_count == 1:
        score += 3.0

    return round(score, 1)
```

- [ ] **Step 2: Add the main compute_gamma function**

Append to `gamma_service.py`:

```python
def compute_gamma(stock_code: str, trade_date: str) -> dict | None:
    """Compute Gamma score for a single stock.

    Calls chanlun-pro for daily + weekly data, computes 3-dimension score.

    Returns:
        Dict with all gamma fields, or None if chanlun-pro unavailable.
    """
    if _consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        logger.debug("Circuit breaker open, skipping %s", stock_code)
        return None

    symbol = stockagent_code_to_chanlun(stock_code)

    # Time range: ~2 years of data for sufficient context
    to_ts = int(datetime.strptime(trade_date, "%Y-%m-%d").timestamp()) + 86400
    from_ts = to_ts - 2 * 365 * 86400

    # Fetch daily data
    daily = _fetch_history(symbol, "1D", from_ts, to_ts)
    if not daily or daily.get("s") == "no_data":
        return None

    # Fetch weekly data
    weekly = _fetch_history(symbol, "1W", from_ts, to_ts)

    # Extract fields
    daily_mmds = daily.get("mmds", [])
    daily_bcs = daily.get("bcs", [])
    daily_bi_zss = daily.get("bi_zss", [])
    daily_bis = daily.get("bis", [])
    daily_bar_times = [int(t) for t in daily.get("t", [])]

    # Current price = last close
    closes = daily.get("c", [])
    current_price = closes[-1] if closes else 0.0

    now_ts = to_ts

    # Dimension 1: Daily strength (0-45)
    daily_score, mmd_type, mmd_level, mmd_age = _compute_daily_strength(daily_mmds, now_ts)

    # Dimension 2: Weekly resonance (0-30)
    weekly_mmds = weekly.get("mmds", []) if weekly else []
    weekly_bis = weekly.get("bis", []) if weekly else []
    weekly_bar_times = [int(t) for t in weekly.get("t", [])] if weekly else []
    weekly_score, w_mmd_type, w_mmd_level = _compute_weekly_resonance(
        weekly_mmds, weekly_bis, weekly_bar_times
    )

    # Dimension 3: Structure health (0-25)
    health_score = _compute_structure_health(
        daily_mmds, daily_bcs, daily_bi_zss, daily_bar_times, current_price
    )

    total = round(daily_score + weekly_score + health_score, 1)

    # Last bi direction
    last_bi_dir = None
    if daily_bis:
        last_bi = daily_bis[-1]
        if len(last_bi) >= 2:
            s = last_bi[0].get("price", 0) if isinstance(last_bi[0], dict) else 0
            e = last_bi[1].get("price", 0) if isinstance(last_bi[1], dict) else 0
            last_bi_dir = "up" if e > s else "down"

    return {
        "stock_code": stock_code,
        "snapshot_date": trade_date,
        "gamma_score": total,
        "daily_strength": daily_score,
        "weekly_resonance": weekly_score,
        "structure_health": health_score,
        "daily_mmd_type": mmd_type,
        "daily_mmd_level": mmd_level,
        "daily_mmd_age": mmd_age,
        "weekly_mmd_type": w_mmd_type,
        "weekly_mmd_level": w_mmd_level,
        "daily_bc_count": len(daily_bcs),
        "daily_bi_zs_count": len(daily_bi_zss),
        "daily_last_bi_dir": last_bi_dir,
    }
```

- [ ] **Step 3: Verify the service can connect and compute**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.services.gamma_service import compute_gamma
result = compute_gamma('600519', '2026-03-18')
if result:
    print(f'Gamma score: {result[\"gamma_score\"]}')
    print(f'  Daily strength: {result[\"daily_strength\"]}')
    print(f'  Weekly resonance: {result[\"weekly_resonance\"]}')
    print(f'  Structure health: {result[\"structure_health\"]}')
    print(f'  MMD: {result[\"daily_mmd_level\"]}:{result[\"daily_mmd_type\"]}')
else:
    print('No data returned (chanlun-pro may not be running)')
"
```

- [ ] **Step 4: Commit**

```bash
git add api/services/gamma_service.py
git commit -m "feat(gamma): implement scoring algorithm (daily+weekly+health)"
```

---

## Chunk 2: Pipeline Integration

### Task 4: Integrate Gamma into Signal Scheduler

**Files:**
- Modify: `api/services/signal_scheduler.py:312-314`

- [ ] **Step 1: Add Step 5c2 after the Step 5c try/except block**

Insert the following block **after the entire Step 5c `try/except` block closes** (after the `except` clause ending at line ~312, same indentation level as the `try`), before the `# Step 5d` comment at line 314:

```python
        # Step 5c2: Gamma scoring (缠论 buy/sell points)
        jm.update_progress(job_id, 90, "Gamma评分")
        try:
            from api.services.gamma_service import compute_gamma, reset_circuit_breaker
            from api.models.gamma_factor import GammaSnapshot
            from api.models.signal import TradingSignal  # Not imported at top level in this file

            reset_circuit_breaker()
            buy_signals = (
                db.query(TradingSignal)
                .filter(TradingSignal.trade_date == trade_date, TradingSignal.market_regime == "buy")
                .all()
            )
            gamma_count = 0
            for sig in buy_signals:
                result = compute_gamma(sig.stock_code, trade_date)
                if result is None:
                    continue
                # Update TradingSignal
                sig.gamma_score = result["gamma_score"]
                # Upsert GammaSnapshot
                snap = (
                    db.query(GammaSnapshot)
                    .filter_by(stock_code=sig.stock_code, snapshot_date=trade_date)
                    .first()
                )
                if snap:
                    for k, v in result.items():
                        setattr(snap, k, v)
                else:
                    db.add(GammaSnapshot(**result))
                gamma_count += 1
            db.commit()
            logger.info("Gamma scorer: %d/%d stocks scored", gamma_count, len(buy_signals))
        except Exception as e:
            logger.warning("Gamma scoring failed (non-fatal): %s", e)
```

- [ ] **Step 2: Verify the scheduler flow compiles**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.signal_scheduler import SignalScheduler
print('signal_scheduler imports ok')
"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/signal_scheduler.py
git commit -m "feat(gamma): integrate Gamma scoring into daily scheduler (Step 5c2)"
```

---

### Task 5: Refactor Beta Scorer — New Combined Formula

**Files:**
- Modify: `api/services/beta_scorer.py:22-26` (WEIGHT_TABLE)
- Modify: `api/services/beta_scorer.py:109-110` (phase/weight lookup)
- Modify: `api/services/beta_scorer.py:159-169` (alpha/beta/combined calculation)
- Modify: `api/services/beta_scorer.py:215-233` (plan creation)

- [ ] **Step 1: Add Gamma weight table and phase function**

At `beta_scorer.py`, replace the existing `WEIGHT_TABLE` (lines 22-26) and `_get_phase` (line 29):

Replace:
```python
WEIGHT_TABLE = {
    "cold": (0.80, 0.20),
    "warm": (0.60, 0.40),
    "mature": (0.50, 0.50),
}


def _get_phase(db: Session) -> str:
    n = db.query(BetaReview).filter(BetaReview.is_profitable.isnot(None)).count()
```

With:
```python
# Gamma weight table: (alpha_weight, gamma_weight)
GAMMA_WEIGHT_TABLE = {
    "cold": (0.80, 0.20),     # < 30 completed trades with gamma
    "warm": (0.60, 0.40),     # 30-99
    "mature": (0.50, 0.50),   # >= 100
}

# Legacy beta weight (still used for beta reference score)
WEIGHT_TABLE = {
    "cold": (0.80, 0.20),
    "warm": (0.60, 0.40),
    "mature": (0.50, 0.50),
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
```

- [ ] **Step 2: Refactor the scoring loop**

In `score_and_create_plans()`, change lines 109-110 from:
```python
    phase = _get_phase(db)
    alpha_w, beta_w = WEIGHT_TABLE[phase]
```
To:
```python
    beta_phase = _get_phase(db)
    gamma_phase = _get_gamma_phase(db)
    alpha_w, gamma_w = GAMMA_WEIGHT_TABLE[gamma_phase]
```

- [ ] **Step 3: Change the combined score calculation**

Replace lines 159-169:
```python
        # Score the stock (same alpha/beta for all sub-positions on this stock)
        alpha = signal.final_score or 0.5
        features = {
            "stock_code": code,
            "alpha_score": alpha,
            "day_of_week": datetime.now().weekday(),
            **shared_context,
            **_load_stock_beta_context(db, code),
        }
        beta = predict_beta_score(db, features)
        combined = round(alpha * alpha_w + beta * beta_w, 4)
```
With:
```python
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
```

- [ ] **Step 4: Update plan creation to include gamma_score**

In the `BotTradePlan(...)` constructor (~line 215-233), update the `thinking` field and add `gamma_score`:

Replace:
```python
                thinking=(
                    f"[Beta] {strategy_name or 'signal'} "
                    f"alpha={alpha:.3f} beta={beta:.3f} combined={combined:.4f} phase={phase}"
                ),
                source="beta",
```
With:
```python
                thinking=(
                    f"[Gamma] {strategy_name or 'signal'} "
                    f"alpha={alpha:.1f} gamma={gamma or 0:.1f} "
                    f"combined={combined:.4f} phase={gamma_phase}"
                ),
                source="beta",
```

And update the score fields:
Replace:
```python
                alpha_score=alpha,
                beta_score=beta,
                combined_score=combined,
```
With:
```python
                alpha_score=alpha,  # Keep raw 0-100 (existing convention)
                beta_score=beta,
                combined_score=combined,
                gamma_score=gamma,
```

- [ ] **Step 5: Update the plan summary dict**

Replace the `plans.append({` block (~line 259-270):
```python
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
```

- [ ] **Step 6: Update log message**

Replace the log at ~line 275-280:
```python
        logger.info(
            "Beta scorer: %d plans (%d stocks) for %s (gamma_phase=%s)",
            len(plans),
            len({p["stock_code"] for p in plans}),
            plan_date,
            gamma_phase,
        )
```

- [ ] **Step 7: Verify import works**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.beta_scorer import score_and_create_plans, _get_gamma_phase, GAMMA_WEIGHT_TABLE
print('beta_scorer imports ok')
print('GAMMA_WEIGHT_TABLE:', GAMMA_WEIGHT_TABLE)
"
```

- [ ] **Step 8: Commit**

```bash
git add api/services/beta_scorer.py
git commit -m "feat(gamma): refactor combined score formula (alpha+gamma, beta as reference)"
```

---

### Task 6: Expand ML Features

**Files:**
- Modify: `api/services/beta_ml.py:21-29` (FEATURE_NAMES)
- Modify: `api/services/beta_ml.py:102-117` (_features_to_array)

- [ ] **Step 1: Add Gamma features to FEATURE_NAMES**

At `beta_ml.py:21-29`, add 4 new features after `"strategy_family_encoded"`:

```python
FEATURE_NAMES = [
    # Entry snapshot features (from BetaSnapshot)
    "alpha_score", "final_score", "entry_price", "day_of_week",
    "stock_return_5d", "stock_volatility_20d", "volume_ratio_5d",
    "index_return_5d", "index_return_20d",
    "sector_heat_score", "regime_encoded",
    # Static context
    "strategy_family_encoded",
    # Gamma features (from GammaSnapshot)
    "gamma_score",
    "daily_mmd_type_encoded",
    "daily_mmd_age",
    "weekly_resonance",
]

# Label encoding for MMD types (shared between training and prediction)
MMD_TYPE_ENCODING = {
    "1B": 6, "2B": 5, "L2B": 4, "3B": 3, "L3B": 2,
    "1S": 1, "2S": 1, "3S": 1, "L2S": 1, "L3S": 1,
}
```

- [ ] **Step 2: Update _features_to_array**

At `beta_ml.py:102-117`, add 4 new lines at the end of the return list:

```python
def _features_to_array(features: dict) -> list[float]:
    """Convert feature dict to ordered array matching FEATURE_NAMES."""
    return [
        features.get("alpha_score", 0.5),
        features.get("final_score", 0.5),
        features.get("entry_price", 0.0),
        features.get("day_of_week", 0),
        features.get("stock_return_5d", 0.0),
        features.get("stock_volatility_20d", 0.0),
        features.get("volume_ratio_5d", 1.0),
        features.get("index_return_5d", 0.0),
        features.get("index_return_20d", 0.0),
        features.get("sector_heat_score", 0.5),
        _encode_regime(features.get("regime_code")),
        _encode_family(features.get("strategy_family")),
        # Gamma features
        features.get("gamma_score", 0.0),
        MMD_TYPE_ENCODING.get(features.get("daily_mmd_type"), 0),
        features.get("daily_mmd_age", 0),
        features.get("weekly_resonance", 0.0),
    ]
```

- [ ] **Step 3: Update _build_training_data to populate gamma features**

In `beta_ml.py`, find `_build_training_data()` (~line 200). After the `features = { ... }` dict is built from `BetaSnapshot` (~line 229-242), add a GammaSnapshot join to populate gamma features with `np.nan` for pre-deployment rows:

After line 242 (`"strategy_family": snapshot.strategy_family,`), before `X_rows.append(...)`, insert:

```python
        # Populate gamma features (np.nan for pre-deployment data)
        from api.models.gamma_factor import GammaSnapshot
        gamma_snap = (
            db.query(GammaSnapshot)
            .filter_by(stock_code=snapshot.stock_code, snapshot_date=snapshot.trade_date)
            .first()
        )
        if gamma_snap:
            features["gamma_score"] = gamma_snap.gamma_score
            features["daily_mmd_type"] = gamma_snap.daily_mmd_type
            features["daily_mmd_age"] = gamma_snap.daily_mmd_age
            features["weekly_resonance"] = gamma_snap.weekly_resonance
        else:
            features["gamma_score"] = float("nan")
            features["daily_mmd_type"] = None  # → 0 via MMD_TYPE_ENCODING
            features["daily_mmd_age"] = float("nan")
            features["weekly_resonance"] = float("nan")
```

Also update `_features_to_array` defaults for gamma features from `0.0` to `float("nan")`:
```python
        features.get("gamma_score", float("nan")),
        MMD_TYPE_ENCODING.get(features.get("daily_mmd_type"), 0),
        features.get("daily_mmd_age", float("nan")),
        features.get("weekly_resonance", float("nan")),
```

This ensures XGBoost treats pre-deployment rows as missing data (native `nan` handling) rather than zero-valued, avoiding bias against stocks without gamma data.

- [ ] **Step 4: Verify feature count matches**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
import math
from api.services.beta_ml import FEATURE_NAMES, _features_to_array
arr = _features_to_array({})
assert len(arr) == len(FEATURE_NAMES), f'{len(arr)} != {len(FEATURE_NAMES)}'
# Verify gamma defaults are nan (not 0)
assert math.isnan(arr[-4]), f'gamma_score default should be nan, got {arr[-4]}'
print(f'Feature count: {len(FEATURE_NAMES)} (matches array, gamma defaults=nan)')
"
```

- [ ] **Step 5: Commit**

```bash
git add api/services/beta_ml.py
git commit -m "feat(gamma): expand ML features with 4 gamma dimensions"
```

---

## Chunk 3: API & Frontend

### Task 7: Update Signal Engine Query & Dict

**Files:**
- Modify: `api/services/signal_engine.py:639-648` (get_signals_by_date)
- Modify: `api/services/signal_engine.py:716-741` (_signal_to_dict)

- [ ] **Step 1: Add GammaSnapshot import**

At the top of `signal_engine.py`, add to the imports section:

```python
from api.models.gamma_factor import GammaSnapshot
```

Also ensure `and_` is imported from sqlalchemy (check existing imports).

- [ ] **Step 2: Update get_signals_by_date to join GammaSnapshot**

Replace lines 639-648:
```python
    def get_signals_by_date(self, trade_date: str) -> list[dict]:
        """Fetch signals for a given date, with stock names."""
        rows = (
            self.db.query(TradingSignal, Stock.name)
            .outerjoin(Stock, TradingSignal.stock_code == Stock.code)
            .filter(TradingSignal.trade_date == trade_date)
            .order_by(TradingSignal.final_score.desc())
            .all()
        )
        return [self._signal_to_dict(sig, name or "") for sig, name in rows]
```
With:
```python
    def get_signals_by_date(self, trade_date: str) -> list[dict]:
        """Fetch signals for a given date, with stock names and gamma data."""
        from sqlalchemy import and_
        rows = (
            self.db.query(TradingSignal, Stock.name, GammaSnapshot)
            .outerjoin(Stock, TradingSignal.stock_code == Stock.code)
            .outerjoin(GammaSnapshot, and_(
                GammaSnapshot.stock_code == TradingSignal.stock_code,
                GammaSnapshot.snapshot_date == TradingSignal.trade_date,
            ))
            .filter(TradingSignal.trade_date == trade_date)
            .order_by(TradingSignal.final_score.desc())
            .all()
        )
        return [self._signal_to_dict(sig, name or "", snap) for sig, name, snap in rows]
```

- [ ] **Step 3: Update _signal_to_dict signature and add gamma fields**

Replace the entire `_signal_to_dict` method (lines 716-741):

```python
    @staticmethod
    def _signal_to_dict(row: TradingSignal, stock_name: str = "", snapshot: GammaSnapshot | None = None) -> dict:
        reasons = row.reasons or "[]"
        try:
            reasons_list = json.loads(reasons)
        except (json.JSONDecodeError, TypeError):
            reasons_list = []

        alpha_score = row.final_score or 0.0
        count_score = row.swing_score or 0.0
        quality_score = row.trend_score or 0.0
        diversity_score = round(max(0.0, alpha_score - count_score - quality_score), 1)

        # Gamma fields (default to 0/null when no snapshot)
        gamma_score = row.gamma_score or 0.0

        # Combined score for display purposes.
        # Uses cold-start weights (80/20) as a static approximation.
        # The actual decision-time combined_score lives in BotTradePlan
        # and uses dynamic phase-based weights from _get_gamma_phase().
        if row.gamma_score is not None:
            combined = round((alpha_score / 100.0) * 0.8 + (row.gamma_score / 100.0) * 0.2, 4)
        else:
            combined = round(alpha_score / 100.0, 4)

        return {
            "stock_code": row.stock_code,
            "stock_name": stock_name,
            "trade_date": row.trade_date,
            "final_score": alpha_score,
            "alpha_score": alpha_score,
            "count_score": count_score,
            "quality_score": quality_score,
            "diversity_score": diversity_score,
            "signal_level": row.signal_level,
            "signal_level_name": row.signal_level_name,
            "action": row.market_regime or "hold",
            "reasons": reasons_list,
            # Gamma fields
            "gamma_score": gamma_score,
            "gamma_daily_strength": snapshot.daily_strength if snapshot else 0.0,
            "gamma_weekly_resonance": snapshot.weekly_resonance if snapshot else 0.0,
            "gamma_structure_health": snapshot.structure_health if snapshot else 0.0,
            "gamma_daily_mmd": (
                f"{snapshot.daily_mmd_level}:{snapshot.daily_mmd_type}"
                if snapshot and snapshot.daily_mmd_type else None
            ),
            "gamma_weekly_mmd": (
                f"{snapshot.weekly_mmd_level}:{snapshot.weekly_mmd_type}"
                if snapshot and snapshot.weekly_mmd_type else None
            ),
            "combined_score": combined,
            "beta_score": 0.0,
        }
```

- [ ] **Step 4: Verify signal engine compiles**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.signal_engine import SignalEngine
print('signal_engine imports ok')
"
```

- [ ] **Step 5: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "feat(gamma): add gamma fields to signal API response"
```

---

### Task 8: Update Frontend Types

**Files:**
- Modify: `web/src/types/index.ts:175-188`

- [ ] **Step 1: Extend SignalItem interface**

At `web/src/types/index.ts:175-188`, add gamma fields:

```typescript
export interface SignalItem {
  stock_code: string;
  stock_name: string;
  trade_date: string;
  final_score: number;
  alpha_score: number;
  count_score: number;
  quality_score: number;
  diversity_score: number;
  signal_level: number;
  signal_level_name: string;
  action: "buy" | "sell" | "hold";
  reasons: string[];
  // Gamma factor
  gamma_score: number;
  gamma_daily_strength: number;
  gamma_weekly_resonance: number;
  gamma_structure_health: number;
  gamma_daily_mmd: string | null;
  gamma_weekly_mmd: string | null;
  combined_score: number;
  beta_score: number;
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/types/index.ts
git commit -m "feat(gamma): add gamma fields to SignalItem TypeScript interface"
```

---

### Task 9: Update Alpha Top Cards Component

**Files:**
- Modify: `web/src/components/signal/alpha-top-cards.tsx`

- [ ] **Step 1: Add GammaScoreBar helper component**

At the top of `alpha-top-cards.tsx`, after the existing `ScoreBar` component (lines 6-28), add:

```tsx
function GammaScoreBar({ daily, weekly, health, total }: {
  daily: number;
  weekly: number;
  health: number;
  total: number;
}) {
  if (total <= 0) return null;
  const pctD = (daily / 100) * 100;
  const pctW = (weekly / 100) * 100;
  const pctH = (health / 100) * 100;

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden flex">
        <div className="h-full bg-emerald-500" style={{ width: `${pctD}%` }} title={`日线 ${daily}`} />
        <div className="h-full bg-cyan-500" style={{ width: `${pctW}%` }} title={`周线 ${weekly}`} />
        <div className="h-full bg-yellow-500" style={{ width: `${pctH}%` }} title={`结构 ${health}`} />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums w-7 text-right">{total}</span>
    </div>
  );
}
```

- [ ] **Step 2: Update legend to show both Alpha and Gamma**

In the `AlphaTopCards` component, replace the legend section (lines 50-54):

```tsx
        <div className="flex items-center gap-3 ml-auto text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-blue-500" />数量</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-violet-500" />质量</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-orange-500" />多样性</span>
          <span className="mx-1 text-border">|</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-emerald-500" />日线</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-cyan-500" />周线</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-yellow-500" />结构</span>
        </div>
```

- [ ] **Step 3: Add Gamma bar and MMD label to each card**

After the `<ScoreBar ... />` in each card (line 71-76), add:

```tsx
            <GammaScoreBar
              daily={s.gamma_daily_strength}
              weekly={s.gamma_weekly_resonance}
              health={s.gamma_structure_health}
              total={s.gamma_score}
            />

            {s.gamma_daily_mmd && (
              <div className="mt-1 flex items-center gap-1.5">
                <Badge className="px-1 py-0 text-[10px] leading-4 bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-500/20">
                  {s.gamma_daily_mmd}
                </Badge>
                {s.gamma_weekly_mmd && (
                  <Badge className="px-1 py-0 text-[10px] leading-4 bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 hover:bg-cyan-500/20">
                    周{s.gamma_weekly_mmd.split(":")[1]}
                  </Badge>
                )}
                <span className="text-[10px] text-muted-foreground ml-auto">
                  综合 {(s.combined_score * 100).toFixed(0)}
                </span>
              </div>
            )}
```

- [ ] **Step 4: Verify frontend builds**

```bash
cd /Users/allenqiang/stockagent/web && npm run build 2>&1 | tail -5
```
Expected: Build succeeds with no type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/components/signal/alpha-top-cards.tsx
git commit -m "feat(gamma): add dual ScoreBar and 缠论 labels to Alpha Top Cards"
```

---

## Chunk 4: Migration & Verification

### Task 10: Invalidate Existing ML Models

**Files:** None (SQL command)

- [ ] **Step 1: Deactivate existing beta models**

Since FEATURE_NAMES changed from 12 → 16 features, existing trained models are incompatible.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from sqlalchemy import text
from api.models.base import engine
with engine.connect() as conn:
    result = conn.execute(text('UPDATE beta_model_states SET is_active = false WHERE is_active = true'))
    conn.commit()
    print(f'Deactivated {result.rowcount} model(s)')
"
```

- [ ] **Step 2: Verify no active models remain**

**IMPORTANT: This must pass BEFORE restarting the server in Task 11.** If an old 12-feature model is still active when the server starts with 16-feature code, predictions will error.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.services.beta_ml import get_active_model
from api.models.base import SessionLocal
db = SessionLocal()
m = get_active_model(db)
assert m is None, f'DANGER: Active model still exists! Deactivation failed.'
print('✅ No active models — safe to restart server with new feature set')
db.close()
"
```
Expected: `✅ No active models — safe to restart server with new feature set`

- [ ] **Step 3: No code commit needed**

This is a data migration only (SQL UPDATE on beta_model_states).

---

### Task 11: End-to-End Smoke Test

- [ ] **Step 1: Restart the backend server**

```bash
# Find and restart uvicorn
kill $(lsof -ti:8050) 2>/dev/null
cd /Users/allenqiang/stockagent
nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/stockagent.log 2>&1 &
sleep 3
curl -s http://127.0.0.1:8050/api/health | python3 -m json.tool
```

- [ ] **Step 2: Test Gamma computation for a single stock**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.services.gamma_service import compute_gamma
result = compute_gamma('600519', '2026-03-17')
if result:
    print('✅ Gamma computed successfully')
    for k, v in result.items():
        print(f'  {k}: {v}')
else:
    print('⚠️ No result (chanlun-pro may need to be started on port 9900)')
"
```

- [ ] **Step 3: Test signal API returns gamma fields**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/signals?trade_date=2026-03-17" | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('items', [])
if items:
    s = items[0]
    print(f'Stock: {s[\"stock_code\"]} {s[\"stock_name\"]}')
    print(f'Alpha: {s[\"alpha_score\"]}')
    print(f'Gamma: {s.get(\"gamma_score\", \"MISSING\")}')
    print(f'Combined: {s.get(\"combined_score\", \"MISSING\")}')
    print(f'Gamma MMD: {s.get(\"gamma_daily_mmd\", \"MISSING\")}')
else:
    print('No signals found for this date')
"
```

- [ ] **Step 4: Test frontend builds and renders**

```bash
cd /Users/allenqiang/stockagent/web && npm run build 2>&1 | tail -3
```

- [ ] **Step 5: Commit any fixes needed**

If any adjustments were required during smoke testing, commit them:
```bash
git add -u
git commit -m "fix(gamma): smoke test fixes"
```
