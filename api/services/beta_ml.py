"""XGBoost training pipeline and prediction for Beta Overlay System.

Model persistence: Uses Python's pickle via XGBoost's native save/load for
internal model serialization to PostgreSQL. This is safe because:
- Models are trained and consumed entirely within this system
- No external/untrusted model files are ever loaded
- The LargeBinary column is never exposed via API
"""

import logging
import io
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from api.models.beta_factor import BetaReview, BetaSnapshot, BetaModelState

logger = logging.getLogger(__name__)

# Features used by the model — order matters for consistency
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

# Strategy family encoding (extend as needed)
FAMILY_MAP = {
    "KDJ": 0, "MACD": 1, "RSI": 2, "PSAR": 3, "BOLL": 4,
    "KAMA": 5, "CCI": 6, "ULTOSC": 7, "KELTNER": 8, "ADX": 9,
    "STOCHRSI": 10, "ULCER": 11, "STOCH": 12, "ATR": 13,
    "unknown": 99,
}

REGIME_MAP = {
    "bull": 0, "bear": 1, "ranging": 2, "volatile": 3,
}


def _encode_regime(regime_str: str | None) -> int:
    if not regime_str:
        return 2  # default to ranging
    for key, val in REGIME_MAP.items():
        if key in regime_str.lower():
            return val
    return 2


def _encode_family(family_str: str | None) -> int:
    if not family_str:
        return FAMILY_MAP["unknown"]
    for key, val in FAMILY_MAP.items():
        if key.lower() in family_str.lower():
            return val
    return FAMILY_MAP["unknown"]


def get_active_model(db: Session) -> BetaModelState | None:
    """Get the currently active model from DB."""
    return (
        db.query(BetaModelState)
        .filter(BetaModelState.is_active.is_(True))
        .order_by(BetaModelState.created_at.desc())
        .first()
    )


def predict_beta_score(db: Session, features: dict) -> float:
    """Predict probability of profitable trade.

    features dict should contain: stock_code, alpha_score, day_of_week, and
    optionally other snapshot fields. Missing fields get defaults.

    Returns float in [0, 1].
    """
    model_state = get_active_model(db)

    # Cold start: use scorecard
    if not model_state:
        return _scorecard_predict(db, features)

    try:
        import xgboost as xgb

        buffer = io.BytesIO(model_state.model_blob)
        booster = xgb.Booster()
        booster.load_model(bytearray(buffer.read()))

        x = _features_to_array(features)
        dmat = xgb.DMatrix(np.array([x]), feature_names=FEATURE_NAMES)
        pred = booster.predict(dmat)[0]
        return float(np.clip(pred, 0.0, 1.0))
    except Exception as e:
        logger.warning("XGBoost predict failed, falling back to scorecard: %s", e)
        return _scorecard_predict(db, features)


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
        features.get("gamma_score", float("nan")),
        MMD_TYPE_ENCODING.get(features.get("daily_mmd_type"), 0),
        features.get("daily_mmd_age", float("nan")),
        features.get("weekly_resonance", float("nan")),
    ]


def _scorecard_predict(db: Session, features: dict) -> float:
    """Heuristic scoring combining alpha with beta factors.

    Uses available non-technical factors: market regime, market sentiment,
    sector heat, news sentiment, plus basic market signals.
    """
    score = 0.5  # neutral base — pure beta factors adjust from here

    # ── Market regime (from market_regimes table) ──
    regime = features.get("regime_code", "")
    if regime:
        if "bull" in regime:
            score += 0.10
        elif "bear" in regime:
            score -= 0.10
        # ranging/volatile → no adjustment

    # ── Market sentiment (from news_sentiment_results, scale: -100 to +100) ──
    market_sent = features.get("market_sentiment")
    if market_sent is not None:
        if market_sent > 30:
            score += 0.08
        elif market_sent > 0:
            score += 0.03
        elif market_sent < -30:
            score -= 0.08
        elif market_sent < 0:
            score -= 0.03

    # ── Sector heat (from sector_heat table, scale: 0-100) ──
    sector_heat = features.get("sector_heat_score")
    if sector_heat is not None:
        if sector_heat >= 70:
            score += 0.08  # hot sector
        elif sector_heat >= 50:
            score += 0.03  # warm sector
        elif sector_heat <= 30:
            score -= 0.05  # cold sector

    # ── Per-stock news sentiment (from Proposal C, scale: -1 to +1) ──
    news_sent = features.get("news_sentiment_3d")
    if news_sent is not None:
        if news_sent > 0.3:
            score += 0.06  # positive news cluster
        elif news_sent < -0.3:
            score -= 0.06  # negative news cluster

    # ── PE valuation (from daily_basic via TuShare) ──
    pe = features.get("pe")
    if pe is not None and pe > 0:
        if pe < 20:
            score += 0.05  # undervalued
        elif pe > 80:
            score -= 0.05  # overvalued

    # ── Turnover rate ──
    turnover = features.get("turnover_rate")
    if turnover is not None:
        if 2 < turnover < 8:
            score += 0.03  # healthy activity
        elif turnover > 15:
            score -= 0.03  # potentially speculative

    # ── Legacy factors (index return, volatility, day-of-week) ──
    index_ret = features.get("index_return_5d", 0)
    if index_ret and index_ret > 0:
        score += 0.05
    elif index_ret and index_ret < -2:
        score -= 0.05

    vol = features.get("stock_volatility_20d", 0)
    if vol and 0 < vol < 3:
        score += 0.03

    dow = features.get("day_of_week", 2)
    if dow in (0, 4):
        score -= 0.02

    return float(np.clip(score, 0.0, 1.0))


def _build_training_data(db: Session, window_days: int = 365) -> tuple[np.ndarray, np.ndarray]:
    """Build X, y arrays from completed BetaReviews with snapshots.

    Returns (X: ndarray shape [n, features], y: ndarray shape [n]).
    """
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")

    reviews = (
        db.query(BetaReview)
        .filter(
            BetaReview.is_profitable.isnot(None),
            BetaReview.entry_snapshot_id.isnot(None),
        )
        .all()
    )

    X_rows = []
    y_rows = []

    for review in reviews:
        snapshot = (
            db.query(BetaSnapshot)
            .filter(BetaSnapshot.id == review.entry_snapshot_id)
            .first()
        )
        if not snapshot:
            continue

        features = {
            "alpha_score": snapshot.final_score or snapshot.alpha_score or 0.5,
            "final_score": snapshot.final_score or 0.5,
            "entry_price": snapshot.entry_price or 0.0,
            "day_of_week": snapshot.day_of_week or 0,
            "stock_return_5d": snapshot.stock_return_5d or 0.0,
            "stock_volatility_20d": snapshot.stock_volatility_20d or 0.0,
            "volume_ratio_5d": snapshot.volume_ratio_5d or 0.0,
            "index_return_5d": snapshot.index_return_5d or 0.0,
            "index_return_20d": snapshot.index_return_20d or 0.0,
            "sector_heat_score": snapshot.sector_heat_score or 0.5,
            "regime_code": snapshot.market_regime,
            "strategy_family": snapshot.strategy_family,
        }

        # Populate gamma features (np.nan for pre-deployment data)
        from api.models.gamma_factor import GammaSnapshot
        gamma_snap = (
            db.query(GammaSnapshot)
            .filter_by(stock_code=snapshot.stock_code, snapshot_date=snapshot.snapshot_date)
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

        X_rows.append(_features_to_array(features))
        y_rows.append(1.0 if review.is_profitable else 0.0)

    return np.array(X_rows, dtype=np.float32), np.array(y_rows, dtype=np.float32)


def train_model(db: Session, force: bool = False) -> dict:
    """Train or retrain XGBoost model on completed trade reviews.

    Returns dict with training metrics.
    """
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score, accuracy_score

    X, y = _build_training_data(db)
    n_samples = len(y)

    if n_samples < 30 and not force:
        return {
            "status": "skipped",
            "reason": f"Only {n_samples} samples, need >= 30",
            "phase": "cold",
        }

    # Determine model complexity by data size
    if n_samples < 100:
        params = {
            "max_depth": 3, "eta": 0.1, "objective": "binary:logistic",
            "eval_metric": "auc", "nthread": 2, "seed": 42,
            "min_child_weight": 3, "subsample": 0.8,
        }
        phase = "warm"
    else:
        params = {
            "max_depth": 5, "eta": 0.05, "objective": "binary:logistic",
            "eval_metric": "auc", "nthread": 2, "seed": 42,
            "min_child_weight": 5, "subsample": 0.8, "colsample_bytree": 0.8,
        }
        phase = "mature"

    # Time-series cross-validation: train on first 80%, validate on last 20%
    split_idx = int(n_samples * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_NAMES)

    num_rounds = 200 if phase == "mature" else 100
    booster = xgb.train(
        params, dtrain, num_boost_round=num_rounds,
        evals=[(dval, "val")], verbose_eval=False,
        early_stopping_rounds=20,
    )

    # Evaluate
    val_pred = booster.predict(dval)
    try:
        auc = float(roc_auc_score(y_val, val_pred))
    except ValueError:
        auc = 0.5  # single class in validation
    acc = float(accuracy_score(y_val, (val_pred > 0.5).astype(int)))

    # AUC rollback protection: don't deploy if worse than current
    current = get_active_model(db)
    if current and current.auc_score and auc < current.auc_score - 0.02:
        return {
            "status": "rollback_prevented",
            "reason": f"New AUC {auc:.4f} < current {current.auc_score:.4f} - 0.02",
            "auc": auc, "accuracy": acc, "phase": phase,
        }

    # Serialize model
    buffer = io.BytesIO()
    booster.save_model(buffer)
    model_bytes = buffer.getvalue()

    # Feature importance
    importance = booster.get_score(importance_type="gain")

    # Deactivate old models
    db.query(BetaModelState).filter(BetaModelState.is_active.is_(True)).update(
        {"is_active": False}
    )

    # Save new model
    version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    new_model = BetaModelState(
        version=version,
        model_type="xgboost",
        model_blob=model_bytes,
        feature_names=FEATURE_NAMES,
        feature_importance=importance,
        training_samples=n_samples,
        auc_score=auc,
        accuracy=acc,
        training_window_start=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
        training_window_end=datetime.now().strftime("%Y-%m-%d"),
        hyperparams=params,
        is_active=True,
    )
    db.add(new_model)
    db.commit()

    logger.info(
        "Beta model trained: %s, samples=%d, AUC=%.4f, accuracy=%.4f, phase=%s",
        version, n_samples, auc, acc, phase,
    )

    return {
        "status": "trained",
        "version": version,
        "samples": n_samples,
        "auc": auc,
        "accuracy": acc,
        "phase": phase,
        "feature_importance": importance,
    }
