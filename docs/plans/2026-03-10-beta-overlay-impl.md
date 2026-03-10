# Beta Overlay System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an ML-driven second-layer scoring system that captures beta factors at signal time, tracks daily during holding, trains XGBoost after exit, and scores all new signals with combined alpha+beta score to create trade plans.

**Architecture:** Extends existing beta_engine.py (4-stage pipeline) with 3 new capabilities: daily holding tracking (BetaDailyTrack), XGBoost model training pipeline (replaces simple scorecard at 30+ samples), and automated signal-to-plan creation flow. The system is integrated into signal_scheduler.py's daily workflow.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (mapped_column pattern), PostgreSQL, XGBoost (already in requirements.txt), scikit-learn, numpy/pandas.

---

## Key Codebase Context

| Item | Detail |
|------|--------|
| Holding table | `bot_portfolio` (class `BotPortfolio`), NOT `bot_holdings` |
| Date format | String `"YYYY-MM-DD"` everywhere (not Date objects) |
| Session | `autoflush=False` -- explicit `db.flush()` required before queries |
| Migration | No Alembic -- `Base.metadata.create_all(engine)` in `api/main.py`. New tables auto-create; new columns on existing tables need manual `ALTER TABLE` |
| Mapped column | Uses `Mapped[type] = mapped_column(...)` pattern (SQLAlchemy 2.x) |
| Beta engine | `api/services/beta_engine.py` -- 4 stages: capture (L24), review (L130), aggregate (L209), scorecard (L273) |
| Bot engine | `api/services/bot_trading_engine.py` -- execute_pending_plans (L303), _create_review (L584) |
| Scheduler | `api/services/signal_scheduler.py` -- _do_refresh (L143), runs Steps 0-5 daily |
| Signal model | `api/models/signal.py` -- TradingSignal (final_score), ActionSignal (stock_code, action, strategy_name) |
| Tests | `tests/` dir exists but no beta/bot trading tests. Tests use pytest. |
| Model serialization | XGBoost models stored via pickle in `beta_model_state.model_blob` (internal-only, no untrusted data) |

---

### Task 1: Add New DB Models (BetaDailyTrack + BetaModelState)

**Files:**
- Modify: `api/models/beta_factor.py:107` (append new classes)
- Modify: `api/main.py:19` (imports already pull Base -- new models auto-discovered via same module)

**Step 1: Add BetaDailyTrack and BetaModelState models**

Append to `api/models/beta_factor.py` after the BetaInsight class:

```python
class BetaDailyTrack(Base):
    """Daily tracking record for each active bot holding."""
    __tablename__ = "beta_daily_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(Integer, index=True)  # bot_portfolio.id
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    track_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD

    # Daily snapshot
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cumulative_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Context
    regime_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sector_heat_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    index_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    news_event_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_beta_track_holding_date", "holding_id", "track_date", unique=True),
    )


class BetaModelState(Base):
    """Persisted XGBoost/scorecard model state with versioning."""
    __tablename__ = "beta_model_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    model_type: Mapped[str] = mapped_column(String(20), default="scorecard")  # scorecard|xgboost
    model_blob: Mapped[Optional[bytes]] = mapped_column(nullable=True)  # XGBoost native save format
    feature_names: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    feature_importance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    training_samples: Mapped[int] = mapped_column(Integer, default=0)
    auc_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    training_window_start: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    training_window_end: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    hyperparams: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**Step 2: Verify models auto-create on server start**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY=localhost,127.0.0.1 python3 -c "from api.models.beta_factor import BetaDailyTrack, BetaModelState; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add api/models/beta_factor.py
git commit -m "feat(beta): add BetaDailyTrack and BetaModelState models"
```

---

### Task 2: Add New Columns to Existing Beta Tables

**Files:**
- Modify: `api/models/beta_factor.py` -- add columns to BetaSnapshot (after line 49) and BetaReview (after line 81)

**Step 1: Add new columns to BetaSnapshot**

After the `ai_reasoning` field (line 49), add:

```python
    # ML features (added for Beta Overlay)
    strategy_family: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    final_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Alpha score from signal
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0=Mon..4=Fri
    stock_return_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_volatility_20d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    index_return_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    index_return_20d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
```

**Step 2: Add new columns to BetaReview**

After the `entry_snapshot_id` field (line 81), add:

```python
    # Trajectory aggregates (filled after position close)
    max_unrealized_gain: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_unrealized_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    regime_changed: Mapped[Optional[bool]] = mapped_column(nullable=True)
    volume_trend_slope: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_path_volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sector_heat_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    news_events_during_hold: Mapped[int] = mapped_column(Integer, default=0)
    index_return_during_hold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_profitable: Mapped[Optional[bool]] = mapped_column(nullable=True)
```

**Step 3: Add new columns to BotTradePlan**

In `api/models/bot_trading.py`, after the `execution_price` field (line 98), add:

```python
    # Beta overlay scores
    alpha_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    combined_score: Mapped[float | None] = mapped_column(Float, nullable=True)
```

**Step 4: Create migration script for existing tables**

Create `scripts/migrate_beta_overlay.py`:

```python
#!/usr/bin/env python3
"""Add new columns to existing beta/bot tables for Beta Overlay System."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from api.models.base import engine, Base

# Create new tables (BetaDailyTrack, BetaModelState)
from api.models.beta_factor import BetaDailyTrack, BetaModelState
Base.metadata.create_all(engine, tables=[BetaDailyTrack.__table__, BetaModelState.__table__])
print("Created new tables: beta_daily_tracks, beta_model_state")

# ALTER TABLE for new columns on existing tables
ALTER_STATEMENTS = [
    # beta_snapshots new columns
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS strategy_family VARCHAR(50)",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS final_score FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS entry_price FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS day_of_week INTEGER",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS stock_return_5d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS stock_volatility_20d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS volume_ratio_5d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS index_return_5d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS index_return_20d FLOAT",
    # beta_reviews new columns
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS max_unrealized_gain FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS max_unrealized_loss FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS regime_changed BOOLEAN",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS volume_trend_slope FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS price_path_volatility FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS sector_heat_delta FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS news_events_during_hold INTEGER DEFAULT 0",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS index_return_during_hold FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS is_profitable BOOLEAN",
    # bot_trade_plans new columns
    "ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS alpha_score FLOAT",
    "ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS beta_score FLOAT",
    "ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS combined_score FLOAT",
]

with engine.connect() as conn:
    for stmt in ALTER_STATEMENTS:
        try:
            conn.execute(text(stmt))
            col_name = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split(" ")[0]
            print(f"  OK: {col_name}")
        except Exception as e:
            print(f"  SKIP: {stmt[:60]}... ({e})")
    conn.commit()

print("Migration complete.")
```

**Step 5: Run migration**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY=localhost,127.0.0.1 python3 scripts/migrate_beta_overlay.py`
Expected: All columns added successfully.

**Step 6: Commit**

```bash
git add api/models/beta_factor.py api/models/bot_trading.py scripts/migrate_beta_overlay.py
git commit -m "feat(beta): add ML feature columns to beta_snapshots, beta_reviews, bot_trade_plans"
```

---

### Task 3: Daily Holding Tracker Service

**Files:**
- Create: `api/services/beta_tracker.py`

**Step 1: Create the daily tracking service**

```python
"""Beta daily tracking -- records daily snapshots for all active bot holdings."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from api.models.bot_trading import BotPortfolio
from api.models.beta_factor import BetaDailyTrack

logger = logging.getLogger(__name__)


def track_daily_holdings(db: Session, trade_date: str) -> int:
    """Create daily tracking records for all active bot holdings.

    Called after market close (Step 2 in the daily flow).
    Returns count of tracks created.
    """
    holdings = db.query(BotPortfolio).filter(BotPortfolio.quantity > 0).all()
    if not holdings:
        return 0

    from src.data_storage.database import DailyPrice, IndexDaily, Stock

    # Batch-load today's prices for all held stocks
    codes = [h.stock_code for h in holdings]
    prices = {
        p.stock_code: p
        for p in db.query(DailyPrice)
        .filter(DailyPrice.stock_code.in_(codes), DailyPrice.trade_date == trade_date)
        .all()
    }

    # Market index close
    index_row = (
        db.query(IndexDaily)
        .filter(IndexDaily.index_code == "000001", IndexDaily.trade_date == trade_date)
        .first()
    )
    index_close = index_row.close if index_row else None

    # Current regime
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

        # Skip if already tracked today
        existing = (
            db.query(BetaDailyTrack)
            .filter(BetaDailyTrack.holding_id == holding.id, BetaDailyTrack.track_date == trade_date)
            .first()
        )
        if existing:
            continue

        # Compute features
        entry_price = holding.buy_price or holding.avg_cost
        cum_pnl = ((price.close - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

        # Volume ratio vs 5-day average and daily return
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

        # Sector heat
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

        # News event count today
        news_count = 0
        try:
            from src.data_storage.database import NewsEvent
            news_count = (
                db.query(NewsEvent)
                .filter(NewsEvent.event_date == trade_date)
                .count()
            )
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
```

**Step 2: Commit**

```bash
git add api/services/beta_tracker.py
git commit -m "feat(beta): add daily holding tracker service"
```

---

### Task 4: Trajectory Aggregation on Position Close

**Files:**
- Create: `api/services/beta_trajectory.py`
- Modify: `api/services/bot_trading_engine.py:553,584` (pass holding_id, call trajectory)

**Step 1: Create trajectory aggregation service**

```python
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
        logger.warning("No BetaReview found for review_id=%d, skipping trajectory", review_id)
        return False

    tracks = (
        db.query(BetaDailyTrack)
        .filter(BetaDailyTrack.holding_id == holding_id)
        .order_by(BetaDailyTrack.track_date.asc())
        .all()
    )

    # Always set target variable
    beta_review.is_profitable = beta_review.pnl_pct > 0

    if not tracks:
        db.commit()
        return True

    # Compute trajectory features
    cum_pnls = [t.cumulative_pnl_pct for t in tracks if t.cumulative_pnl_pct is not None]
    daily_rets = [t.daily_return_pct for t in tracks if t.daily_return_pct is not None]
    volumes = [t.volume for t in tracks if t.volume is not None]

    beta_review.max_unrealized_gain = max(cum_pnls) if cum_pnls else None
    beta_review.max_unrealized_loss = min(cum_pnls) if cum_pnls else None
    beta_review.price_path_volatility = float(np.std(daily_rets)) if len(daily_rets) >= 2 else None

    # Volume trend slope (linear regression)
    if len(volumes) >= 3:
        x = np.arange(len(volumes), dtype=float)
        slope = float(np.polyfit(x, volumes, 1)[0])
        beta_review.volume_trend_slope = slope

    # Regime changed?
    regimes = [t.regime_code for t in tracks if t.regime_code]
    beta_review.regime_changed = (regimes[0] != regimes[-1]) if len(regimes) >= 2 else False

    # Sector heat delta (last - first)
    heats = [t.sector_heat_score for t in tracks if t.sector_heat_score is not None]
    if len(heats) >= 2:
        beta_review.sector_heat_delta = heats[-1] - heats[0]

    # News events during hold
    beta_review.news_events_during_hold = sum(t.news_event_count for t in tracks)

    # Index return during hold
    index_closes = [t.index_close for t in tracks if t.index_close is not None]
    if len(index_closes) >= 2:
        beta_review.index_return_during_hold = (
            (index_closes[-1] - index_closes[0]) / index_closes[0] * 100
        )

    db.commit()
    logger.info(
        "Trajectory aggregated for review_id=%d: gain=%.2f%%, loss=%.2f%%, profitable=%s",
        review_id,
        beta_review.max_unrealized_gain or 0,
        beta_review.max_unrealized_loss or 0,
        beta_review.is_profitable,
    )
    return True
```

**Step 2: Modify _execute_sell to pass holding_id**

In `api/services/bot_trading_engine.py`, around line 553 change:

```python
# Before:
_create_review(db, code, name, trade_date)
# After:
_create_review(db, code, name, trade_date, holding.id)
```

**Step 3: Modify _create_review signature and add trajectory call**

At line 584, change signature:
```python
def _create_review(db: Session, code: str, name: str, last_sell_date: str, holding_id: int = 0):
```

After line 648 (the existing `create_beta_review` call), add:
```python
    # Aggregate trajectory features from daily tracks
    try:
        from api.services.beta_trajectory import aggregate_trajectory
        aggregate_trajectory(db, review.id, holding_id, code)
    except Exception as e:
        logger.warning("Trajectory aggregation failed for %s: %s", code, e)
```

**Step 4: Commit**

```bash
git add api/services/beta_trajectory.py api/services/bot_trading_engine.py
git commit -m "feat(beta): add trajectory aggregation on position close"
```

---

### Task 5: Enhanced Beta Snapshot Capture

**Files:**
- Modify: `api/services/beta_engine.py:24-90` (capture_beta_snapshots function)

**Step 1: Add helper functions before capture_beta_snapshots**

Insert before `capture_beta_snapshots` (around line 22):

```python
def _compute_price_features(db: Session, stock_code: str, trade_date: str) -> dict:
    """Compute stock price/volume features from daily_prices."""
    from src.data_storage.database import DailyPrice
    import numpy as np

    prices = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code == stock_code, DailyPrice.trade_date <= trade_date)
        .order_by(DailyPrice.trade_date.desc())
        .limit(25)
        .all()
    )
    if len(prices) < 2:
        return {}

    closes = [p.close for p in reversed(prices)]
    volumes = [p.volume for p in reversed(prices)]
    returns_list = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]

    result = {}
    if len(closes) >= 6:
        result["stock_return_5d"] = round((closes[-1] - closes[-6]) / closes[-6] * 100, 4)
    if len(returns_list) >= 20:
        result["stock_volatility_20d"] = round(float(np.std(returns_list[-20:])) * 100, 4)
    if len(volumes) >= 6:
        avg_vol = sum(volumes[-6:-1]) / 5
        result["volume_ratio_5d"] = round(volumes[-1] / avg_vol, 4) if avg_vol > 0 else None
    return result


def _compute_index_returns(db: Session, trade_date: str) -> dict:
    """Compute index return features (5d and 20d)."""
    from src.data_storage.database import IndexDaily

    rows = (
        db.query(IndexDaily)
        .filter(IndexDaily.index_code == "000001", IndexDaily.trade_date <= trade_date)
        .order_by(IndexDaily.trade_date.desc())
        .limit(25)
        .all()
    )
    if len(rows) < 2:
        return {}

    closes = [r.close for r in reversed(rows)]
    result = {}
    if len(closes) >= 6:
        result["index_return_5d"] = round((closes[-1] - closes[-6]) / closes[-6] * 100, 4)
    if len(closes) >= 21:
        result["index_return_20d"] = round((closes[-1] - closes[-21]) / closes[-21] * 100, 4)
    return result
```

**Step 2: Update the BetaSnapshot creation in capture_beta_snapshots**

In the snapshot creation block (around line 58-80), add the new ML feature fields to the BetaSnapshot constructor after the existing fields:

```python
            # Compute ML features
            price_feats = _compute_price_features(db, code, report_date)
            index_feats = _compute_index_returns(db, report_date)
            from datetime import date as date_cls
            try:
                dow = date_cls.fromisoformat(report_date).weekday()
            except ValueError:
                dow = None

            snap = BetaSnapshot(
                # ... all existing fields stay the same ...
                # Add new ML features:
                strategy_family=rec.get("strategy_family"),
                final_score=rec.get("final_score") or rec.get("alpha_score"),
                entry_price=rec.get("entry_price"),
                day_of_week=dow,
                stock_return_5d=price_feats.get("stock_return_5d"),
                stock_volatility_20d=price_feats.get("stock_volatility_20d"),
                volume_ratio_5d=price_feats.get("volume_ratio_5d"),
                index_return_5d=index_feats.get("index_return_5d"),
                index_return_20d=index_feats.get("index_return_20d"),
            )
```

**Step 3: Commit**

```bash
git add api/services/beta_engine.py
git commit -m "feat(beta): enhance snapshot capture with ML feature columns"
```

---

### Task 6: XGBoost Training Pipeline

**Files:**
- Create: `api/services/beta_ml.py`

**Step 1: Create the ML training and prediction service**

```python
"""Beta ML pipeline -- XGBoost training, prediction, and model management.

Note: Uses pickle for XGBoost model serialization. This is safe because
model_blob only contains internally-trained models, never untrusted data.
XGBoost's native save/load requires file I/O; pickle enables direct DB storage.
"""

import io
import logging
import pickle
from datetime import datetime

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, accuracy_score
from sqlalchemy.orm import Session

from api.models.beta_factor import BetaSnapshot, BetaReview, BetaModelState

logger = logging.getLogger(__name__)

# Feature columns (order matters -- must match training and prediction)
ENTRY_FEATURES = [
    "market_regime_confidence", "sector_heat_score",
    "stock_return_5d", "stock_volatility_20d", "volume_ratio_5d",
    "alpha_score", "day_of_week", "pe", "pb", "turnover_rate",
    "index_return_5d", "index_return_20d", "market_sentiment",
]

TRAJECTORY_FEATURES = [
    "max_unrealized_gain", "max_unrealized_loss", "holding_days",
    "regime_changed", "volume_trend_slope", "price_path_volatility",
    "sector_heat_delta", "news_events_during_hold", "index_return_during_hold",
]

CATEGORICAL_COLS = ["regime_code", "industry", "strategy_family"]

COLD_START_THRESHOLD = 30
MATURE_THRESHOLD = 100


def get_active_model(db: Session) -> tuple:
    """Load the currently active model. Returns (model, model_type, feature_names)."""
    state = (
        db.query(BetaModelState)
        .filter(BetaModelState.is_active == True)
        .order_by(BetaModelState.version.desc())
        .first()
    )
    if not state or not state.model_blob:
        return None, "scorecard", []

    model = pickle.loads(state.model_blob)  # noqa: S301 - internal model only
    return model, state.model_type, state.feature_names or []


def predict_beta_score(db: Session, features: dict) -> float:
    """Predict P(profitable) for a single signal. Returns 0.0-1.0."""
    model, model_type, feature_names = get_active_model(db)

    if model is None or model_type == "scorecard":
        return _scorecard_predict(db, features)

    row = {col: features.get(col, np.nan) for col in feature_names}
    df = pd.DataFrame([row])
    try:
        dmat = xgb.DMatrix(df)
        prob = float(model.predict(dmat)[0])
        return round(prob, 4)
    except Exception as e:
        logger.warning("XGBoost prediction failed, falling back to scorecard: %s", e)
        return _scorecard_predict(db, features)


def _scorecard_predict(db: Session, features: dict) -> float:
    """Simple weighted scorecard fallback for cold-start phase."""
    from api.services.beta_engine import compute_beta_scorecard
    code = features.get("stock_code", "")
    if not code:
        return 0.5
    result = compute_beta_scorecard(db, [code])
    scorecard = result.get(code, {})
    return round(scorecard.get("beta_score", 50) / 100, 4)


def train_model(db: Session) -> dict:
    """Train XGBoost model on completed trades with trajectory data."""
    reviews = (
        db.query(BetaReview)
        .filter(BetaReview.is_profitable.isnot(None))
        .order_by(BetaReview.created_at.asc())
        .all()
    )

    n_samples = len(reviews)
    if n_samples < COLD_START_THRESHOLD:
        logger.info("Beta ML: %d samples < %d, staying in scorecard mode", n_samples, COLD_START_THRESHOLD)
        return {"model_type": "scorecard", "samples": n_samples, "reason": "insufficient_data"}

    # Build feature matrix
    rows = []
    for rev in reviews:
        snap = None
        if rev.entry_snapshot_id:
            snap = db.query(BetaSnapshot).filter(BetaSnapshot.id == rev.entry_snapshot_id).first()
        if not snap:
            snap = (
                db.query(BetaSnapshot)
                .filter(BetaSnapshot.stock_code == rev.stock_code)
                .order_by(BetaSnapshot.created_at.desc())
                .first()
            )

        row = {}
        if snap:
            for col in ENTRY_FEATURES:
                row[col] = getattr(snap, col, None)
            for col in CATEGORICAL_COLS:
                row[col] = getattr(snap, col, None)
        else:
            for col in ENTRY_FEATURES + CATEGORICAL_COLS:
                row[col] = None

        for col in TRAJECTORY_FEATURES:
            val = getattr(rev, col, None)
            if isinstance(val, bool):
                val = int(val)
            row[col] = val

        row["target"] = int(rev.is_profitable)
        rows.append(row)

    df = pd.DataFrame(rows)

    # Encode categoricals as numeric codes
    for col in CATEGORICAL_COLS:
        if col in df.columns:
            df[col] = df[col].astype("category").cat.codes.replace(-1, np.nan)

    if "regime_changed" in df.columns:
        df["regime_changed"] = df["regime_changed"].map({True: 1, False: 0, None: np.nan})

    feature_cols = [c for c in df.columns if c != "target"]
    X = df[feature_cols]
    y = df["target"]

    max_depth = 3 if n_samples < MATURE_THRESHOLD else 5
    params = {
        "objective": "binary:logistic", "eval_metric": "auc",
        "max_depth": max_depth, "learning_rate": 0.1,
        "subsample": 0.8, "colsample_bytree": 0.8,
        "min_child_weight": 3, "reg_alpha": 0.1, "reg_lambda": 1.0,
        "verbosity": 0,
    }

    # Time-series CV
    n_splits = min(5, max(2, n_samples // 10))
    tscv = TimeSeriesSplit(n_splits=n_splits)
    auc_scores = []

    for train_idx, val_idx in tscv.split(X):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dval = xgb.DMatrix(X_val, label=y_val)
        model = xgb.train(
            params, dtrain, num_boost_round=100,
            evals=[(dval, "val")], early_stopping_rounds=10, verbose_eval=False,
        )
        preds = model.predict(dval)
        if len(set(y_val)) > 1:
            auc_scores.append(roc_auc_score(y_val, preds))

    avg_auc = float(np.mean(auc_scores)) if auc_scores else 0.5

    # Final model on all data
    dtrain_full = xgb.DMatrix(X, label=y)
    final_model = xgb.train(params, dtrain_full, num_boost_round=100, verbose_eval=False)

    # Feature importance
    importance = final_model.get_score(importance_type="gain")
    feat_importance = {}
    for feat_key, score in importance.items():
        idx = int(feat_key.replace("f", ""))
        if idx < len(feature_cols):
            feat_importance[feature_cols[idx]] = round(score, 4)

    # Rollback check
    prev_state = (
        db.query(BetaModelState)
        .filter(BetaModelState.is_active == True)
        .order_by(BetaModelState.version.desc())
        .first()
    )
    if prev_state and prev_state.auc_score and avg_auc < prev_state.auc_score * 0.95:
        logger.warning("Beta ML: AUC %.4f is >5%% worse than prev %.4f, keeping old model", avg_auc, prev_state.auc_score)
        return {"model_type": "xgboost", "samples": n_samples, "auc": avg_auc, "action": "rollback"}

    # Save new model
    if prev_state:
        prev_state.is_active = False

    new_version = (prev_state.version + 1) if prev_state else 1
    preds_full = final_model.predict(dtrain_full)
    acc = float(accuracy_score(y, (preds_full > 0.5).astype(int)))

    state = BetaModelState(
        version=new_version, model_type="xgboost",
        model_blob=pickle.dumps(final_model),  # noqa: S301
        feature_names=feature_cols, feature_importance=feat_importance,
        training_samples=n_samples, auc_score=round(avg_auc, 4), accuracy=round(acc, 4),
        training_window_start=reviews[0].created_at.strftime("%Y-%m-%d"),
        training_window_end=reviews[-1].created_at.strftime("%Y-%m-%d"),
        hyperparams=params, is_active=True,
    )
    db.add(state)
    db.commit()

    logger.info("Beta ML: Trained v%d (depth=%d, n=%d, AUC=%.4f, Acc=%.4f)", new_version, max_depth, n_samples, avg_auc, acc)
    return {
        "model_type": "xgboost", "version": new_version, "samples": n_samples,
        "auc": avg_auc, "accuracy": acc,
        "top_features": sorted(feat_importance.items(), key=lambda x: x[1], reverse=True)[:5],
    }
```

**Step 2: Commit**

```bash
git add api/services/beta_ml.py
git commit -m "feat(beta): add XGBoost training pipeline with cold-start fallback"
```

---

### Task 7: Signal Scoring and Automated Plan Creation

**Files:**
- Create: `api/services/beta_scorer.py`

**Step 1: Create the signal scoring + plan creation service**

```python
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
    """Determine current model phase based on completed trade count."""
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

    # Skip stocks already held
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

        # Skip if pending buy plan already exists
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

        # Resolve stock name
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
        logger.info("Beta scorer: %d plans created for %s (phase=%s)", len(plans), plan_date, phase)

    return plans
```

**Step 2: Commit**

```bash
git add api/services/beta_scorer.py
git commit -m "feat(beta): add signal scoring and automated plan creation"
```

---

### Task 8: Integrate into Daily Scheduler

**Files:**
- Modify: `api/services/signal_scheduler.py:247` (add tracking, training, scoring steps)

**Step 1: Add new steps after existing Step 5 (Beta aggregation)**

After the beta aggregation block (line 247), insert:

```python
                    # Step 5b: Daily holding tracking
                    try:
                        from api.services.beta_tracker import track_daily_holdings
                        tracked = track_daily_holdings(db, trade_date)
                        if tracked:
                            logger.info("Beta tracking: %d holdings for %s", tracked, trade_date)
                    except Exception as e:
                        logger.warning("Beta tracking failed (non-fatal): %s", e)

                    # Step 5c: Retrain beta ML model
                    try:
                        from api.services.beta_ml import train_model
                        train_result = train_model(db)
                        if train_result.get("version"):
                            logger.info("Beta ML: v%d AUC=%.4f", train_result["version"], train_result.get("auc", 0))
                    except Exception as e:
                        logger.warning("Beta ML training failed (non-fatal): %s", e)

                    # Step 5d: Score buy signals and create plans
                    try:
                        from api.services.beta_scorer import score_and_create_plans
                        from api.services.bot_trading_engine import _get_next_trading_day
                        plan_date = _get_next_trading_day(trade_date)
                        scored_plans = score_and_create_plans(db, trade_date, plan_date)
                        if scored_plans:
                            logger.info("Beta scorer: %d plans for %s", len(scored_plans), plan_date)
                    except Exception as e:
                        logger.warning("Beta scoring failed (non-fatal): %s", e)
```

**Step 2: Commit**

```bash
git add api/services/signal_scheduler.py
git commit -m "feat(beta): integrate tracking, training, scoring into daily scheduler"
```

---

### Task 9: API Endpoints for Beta ML

**Files:**
- Modify: `api/routers/beta.py` (append new endpoints)

**Step 1: Add ML-related endpoints**

Append to `api/routers/beta.py`:

```python
@router.get("/model/status")
def get_model_status(db: Session = Depends(get_db)):
    """Current beta ML model status."""
    from api.models.beta_factor import BetaModelState, BetaReview
    state = (
        db.query(BetaModelState)
        .filter(BetaModelState.is_active == True)
        .order_by(BetaModelState.version.desc())
        .first()
    )
    n_reviews = db.query(BetaReview).filter(BetaReview.is_profitable.isnot(None)).count()
    phase = "cold" if n_reviews < 30 else "warm" if n_reviews < 100 else "mature"

    if not state:
        return {"phase": phase, "model_type": "scorecard", "completed_trades": n_reviews, "version": 0}

    return {
        "phase": phase, "model_type": state.model_type, "version": state.version,
        "completed_trades": n_reviews, "training_samples": state.training_samples,
        "auc_score": state.auc_score, "accuracy": state.accuracy,
        "feature_importance": state.feature_importance,
        "training_window": f"{state.training_window_start} to {state.training_window_end}",
        "created_at": state.created_at.isoformat() if state.created_at else None,
    }


@router.post("/model/train")
def trigger_training(db: Session = Depends(get_db)):
    """Manually trigger beta ML model retraining."""
    from api.services.beta_ml import train_model
    return train_model(db)


@router.get("/tracks/{stock_code}")
def get_daily_tracks(stock_code: str, db: Session = Depends(get_db)):
    """Daily tracking records for a stock's current or recent holding."""
    from api.models.beta_factor import BetaDailyTrack
    tracks = (
        db.query(BetaDailyTrack)
        .filter(BetaDailyTrack.stock_code == stock_code)
        .order_by(BetaDailyTrack.track_date.desc())
        .limit(60)
        .all()
    )
    return [
        {
            "track_date": t.track_date, "close_price": t.close_price,
            "cumulative_pnl_pct": t.cumulative_pnl_pct, "daily_return_pct": t.daily_return_pct,
            "volume_ratio": t.volume_ratio, "regime_code": t.regime_code,
            "sector_heat_score": t.sector_heat_score,
        }
        for t in tracks
    ]
```

**Step 2: Commit**

```bash
git add api/routers/beta.py
git commit -m "feat(beta): add model status, training, and tracking API endpoints"
```

---

### Task 10: Frontend -- Beta Score Display in Plans

**Files:**
- Modify: `web/src/types/index.ts` (add beta score fields to TradePlan type)
- Modify: `web/src/lib/api.ts` (add beta model status API call)

**Step 1: Add beta fields to TradePlan type**

Find the TradePlan interface in `web/src/types/index.ts` and add:

```typescript
  alpha_score?: number;
  beta_score?: number;
  combined_score?: number;
```

**Step 2: Add beta model status API**

In `web/src/lib/api.ts`, add:

```typescript
export async function getBetaModelStatus(): Promise<any> {
  const res = await fetch(`${API_BASE}/beta/model/status`);
  return res.json();
}
```

**Step 3: Commit**

```bash
git add web/src/lib/api.ts web/src/types/index.ts
git commit -m "feat(web): add beta score types and API integration"
```

---

### Task 11: End-to-End Verification

**Step 1: Run migration**

```bash
cd /Users/allenqiang/stockagent
NO_PROXY=localhost,127.0.0.1 python3 scripts/migrate_beta_overlay.py
```

**Step 2: Verify all imports**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.beta_factor import BetaDailyTrack, BetaModelState
from api.services.beta_tracker import track_daily_holdings
from api.services.beta_trajectory import aggregate_trajectory
from api.services.beta_ml import train_model, predict_beta_score
from api.services.beta_scorer import score_and_create_plans
print('All imports OK')
"
```

**Step 3: Verify API endpoint**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/beta/model/status | python3 -m json.tool
```

Expected: `{"phase": "cold", "model_type": "scorecard", ...}`

**Step 4: Test scorecard prediction**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import SessionLocal
from api.services.beta_ml import predict_beta_score
db = SessionLocal()
score = predict_beta_score(db, {'stock_code': '000001'})
print(f'Beta score for 000001: {score}')
db.close()
"
```

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat(beta): complete Beta Overlay System -- ML-driven signal scoring"
```

---

## Dependency Graph

```
Task 1 (new models) ---+
Task 2 (new columns) --+
                        +---> Task 3 (daily tracker) ---> Task 8 (scheduler)
                        +---> Task 4 (trajectory)
Task 5 (snapshot) ------+
                        +---> Task 6 (XGBoost ML) ---> Task 7 (scorer) ---> Task 8
                        +---> Task 9 (API endpoints)
Task 10 (frontend) --- independent
Task 11 (verification) --- after all
```

Tasks 1-2 must be done first (DB foundation). Tasks 3-7 can be partially parallelized. Task 8 integrates everything. Tasks 9-10 are independent. Task 11 is final verification.
