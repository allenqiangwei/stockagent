"""Logistic Regression confidence scorer for trade win probability.

Predicts a 0-100 confidence score using alpha, gamma, and market regime
features. Model params are stored as JSON (no binary serialization).
Replaces signal_grader for plan ranking.
"""

import logging
import math
import threading
from typing import Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.models.confidence import ConfidenceModel

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "alpha_score",
    "gamma_daily_strength",
    "gamma_weekly_resonance",
    "gamma_structure_health",
    "gamma_mmd_age",
    "gamma_bc_confirmed",
    "has_gamma",
    "trend_strength",
    "volatility",
    "index_return_pct",
    "sector_heat_score",
    "regime_encoded",
    "day_of_week",
    "stock_return_5d",
    "volume_ratio_5d",
]

REGIME_MAP = {"trending_bull": 1, "ranging": 0, "trending_bear": -1, "volatile": -0.5}

# Thread-safe cache for active model params
_cache_lock = threading.Lock()
_cached_params: Optional[dict] = None
_cached_feature_names: Optional[list] = None
_cached_version: Optional[int] = None


def _sigmoid(z: float) -> float:
    """Numerically stable sigmoid function."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    else:
        ez = math.exp(z)
        return ez / (1.0 + ez)


def _predict_from_params(params: dict, features: list[float]) -> float:
    """Pure-math prediction from stored model params. No sklearn needed.

    Steps:
      1. StandardScaler transform: (f - mean) / scale
      2. Dot product with coefficients + intercept
      3. Sigmoid * 100

    Returns confidence score 0-100.
    """
    coef = params["coef"]
    intercept = params["intercept"]
    scaler_mean = params["scaler_mean"]
    scaler_scale = params["scaler_scale"]

    # StandardScaler transform
    scaled = [
        (f - m) / s if s > 0 else 0.0
        for f, m, s in zip(features, scaler_mean, scaler_scale)
    ]

    # Dot product + intercept
    z = sum(c * x for c, x in zip(coef, scaled)) + intercept

    return _sigmoid(z) * 100.0


def _train_lr(X: np.ndarray, y: np.ndarray, feature_names: list[str]) -> dict:
    """Train LogisticRegression(C=1.0) + StandardScaler on (X, y).

    Returns dict with all JSON-safe values:
      {status, model_params, auc, brier, samples, positive_rate, coefficients}
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    lr = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
    lr.fit(X_scaled, y)

    proba = lr.predict_proba(X_scaled)[:, 1]
    auc = float(roc_auc_score(y, proba))
    brier = float(brier_score_loss(y, proba))
    positive_rate = float(y.mean())

    # Calibration curve: bin predictions, compare to actual positive rate
    cal_bins = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    calibration = []
    for lo, hi in zip(cal_bins[:-1], cal_bins[1:]):
        mask = (proba >= lo) & (proba < hi)
        if mask.sum() >= 5:
            calibration.append({
                "bin": f"{lo:.1f}-{hi:.1f}",
                "count": int(mask.sum()),
                "predicted": round(float(proba[mask].mean()), 4),
                "actual": round(float(y[mask].mean()), 4),
            })

    model_params = {
        "coef": [float(c) for c in lr.coef_[0]],
        "intercept": float(lr.intercept_[0]),
        "scaler_mean": [float(m) for m in scaler.mean_],
        "scaler_scale": [float(s) for s in scaler.scale_],
    }

    coefficients = {
        name: float(c) for name, c in zip(feature_names, lr.coef_[0])
    }

    return {
        "status": "trained",
        "model_params": model_params,
        "auc": auc,
        "brier": brier,
        "samples": int(len(y)),
        "positive_rate": positive_rate,
        "calibration": calibration,
        "coefficients": coefficients,
    }


def _build_training_data(db: Session) -> tuple[np.ndarray, np.ndarray]:
    """Build training data from executed buy plans joined with trade reviews, market regimes,
    gamma_snapshots, and beta_snapshots.

    Returns (X, y) where X has columns matching FEATURE_NAMES and
    y is binary (1 = profitable, 0 = loss).
    """
    sql = text("""
        SELECT p.alpha_score, p.gamma_score,
               mr.trend_strength, mr.volatility, mr.index_return_pct,
               r.pnl_pct,
               gs.daily_strength, gs.weekly_resonance,
               gs.structure_health, gs.daily_mmd_age,
               bs.sector_heat_score, bs.market_regime,
               bs.day_of_week, bs.stock_return_5d, bs.volume_ratio_5d
        FROM bot_trade_plans p
        JOIN bot_trade_reviews r
            ON r.stock_code = p.stock_code
            AND r.strategy_id = p.strategy_id
            AND r.first_buy_date = p.plan_date
        JOIN market_regimes mr
            ON r.first_buy_date BETWEEN mr.week_start::text AND mr.week_end::text
        LEFT JOIN gamma_snapshots gs
            ON gs.stock_code = p.stock_code
            AND gs.snapshot_date = p.plan_date
        LEFT JOIN beta_snapshots bs
            ON bs.stock_code = p.stock_code
            AND bs.snapshot_date = p.plan_date
        WHERE p.status = 'executed'
            AND p.direction = 'buy'
            AND p.alpha_score IS NOT NULL
    """)

    rows = db.execute(sql).fetchall()
    if not rows:
        return np.empty((0, len(FEATURE_NAMES))), np.empty(0)

    X_list = []
    y_list = []
    for row in rows:
        alpha_score = float(row[0]) if row[0] is not None else 0.0
        has_gamma = 1.0 if row[1] is not None else 0.0
        trend_strength = float(row[2]) if row[2] is not None else 0.0
        volatility = float(row[3]) if row[3] is not None else 0.0
        index_return_pct = float(row[4]) if row[4] is not None else 0.0
        pnl_pct = float(row[5]) if row[5] is not None else 0.0

        # Gamma raw dimensions (from gamma_snapshots LEFT JOIN)
        gamma_daily_strength = float(row[6]) if row[6] is not None else 0.0
        gamma_weekly_resonance = float(row[7]) if row[7] is not None else 0.0
        gamma_structure_health = float(row[8]) if row[8] is not None else 0.0
        gamma_mmd_age = float(row[9]) if row[9] is not None else 0.0
        gamma_bc_confirmed = 1.0 if gamma_structure_health >= 10 else 0.0

        # Beta features (from beta_snapshots LEFT JOIN)
        sector_heat_score = float(row[10]) if row[10] is not None else 0.0
        regime_str = row[11] if row[11] is not None else "ranging"
        regime_encoded = REGIME_MAP.get(regime_str, 0.0)
        day_of_week = float(row[12]) if row[12] is not None else 0.0
        stock_return_5d = float(row[13]) if row[13] is not None else 0.0
        volume_ratio_5d = float(row[14]) if row[14] is not None else 0.0

        X_list.append([
            alpha_score,
            gamma_daily_strength,
            gamma_weekly_resonance,
            gamma_structure_health,
            gamma_mmd_age,
            gamma_bc_confirmed,
            has_gamma,
            trend_strength,
            volatility,
            index_return_pct,
            sector_heat_score,
            regime_encoded,
            day_of_week,
            stock_return_5d,
            volume_ratio_5d,
        ])
        y_list.append(1 if pnl_pct > 0 else 0)

    return np.array(X_list), np.array(y_list)


def train_confidence_model(db: Session) -> dict:
    """Build training data, train LR model, and persist to confidence_models table.

    AUC guard: if AUC < 0.55, the model is not deployed (not marked as active).
    Returns training result dict.
    """
    global _cached_params, _cached_feature_names, _cached_version

    X, y = _build_training_data(db)
    if len(y) < 30:
        return {
            "status": "insufficient_data",
            "samples": int(len(y)),
            "message": f"Need at least 30 samples, have {len(y)}.",
        }

    # Check class balance
    pos_rate = float(y.mean())
    if pos_rate == 0.0 or pos_rate == 1.0:
        return {
            "status": "no_class_variance",
            "samples": int(len(y)),
            "positive_rate": pos_rate,
            "message": "All labels are the same — cannot train.",
        }

    result = _train_lr(X, y, FEATURE_NAMES)

    # AUC guard
    if result["auc"] < 0.55:
        logger.warning(
            "Confidence model AUC %.4f < 0.55 — not deploying (samples=%d)",
            result["auc"], result["samples"],
        )
        return {
            "status": "auc_too_low",
            "auc": result["auc"],
            "brier": result["brier"],
            "samples": result["samples"],
            "positive_rate": result["positive_rate"],
            "message": f"AUC {result['auc']:.4f} < 0.55 threshold — model not deployed.",
        }

    # Deactivate previous models
    db.query(ConfidenceModel).filter(ConfidenceModel.is_active == True).update(
        {"is_active": False}
    )

    # Get next version number
    max_ver = db.query(ConfidenceModel.version).order_by(
        ConfidenceModel.version.desc()
    ).first()
    next_version = (max_ver[0] + 1) if max_ver else 1

    # Persist
    model = ConfidenceModel(
        version=next_version,
        model_params=result["model_params"],
        feature_names=FEATURE_NAMES,
        auc_score=result["auc"],
        brier_score=result["brier"],
        training_samples=result["samples"],
        positive_rate=result["positive_rate"],
        calibration_data=result.get("calibration"),
        is_active=True,
    )
    db.add(model)
    db.commit()

    # Update cache
    with _cache_lock:
        _cached_params = result["model_params"]
        _cached_feature_names = FEATURE_NAMES[:]
        _cached_version = next_version

    logger.info(
        "Confidence model v%d deployed: AUC=%.4f, Brier=%.4f, samples=%d",
        next_version, result["auc"], result["brier"], result["samples"],
    )

    return {
        "status": "deployed",
        "version": next_version,
        "auc": result["auc"],
        "brier": result["brier"],
        "samples": result["samples"],
        "positive_rate": result["positive_rate"],
        "coefficients": result["coefficients"],
    }


def _load_active_model(db: Session) -> Optional[dict]:
    """Load active model params from DB into cache. Returns params or None."""
    global _cached_params, _cached_feature_names, _cached_version

    model = (
        db.query(ConfidenceModel)
        .filter(ConfidenceModel.is_active == True)
        .order_by(ConfidenceModel.version.desc())
        .first()
    )
    if not model:
        return None

    with _cache_lock:
        _cached_params = model.model_params
        _cached_feature_names = model.feature_names
        _cached_version = model.version

    return model.model_params


def predict_confidence(
    db: Session,
    alpha: float,
    gamma_snapshot: dict | None = None,
    trend_strength: float = 0.0,
    volatility: float = 0.0,
    index_return_pct: float = 0.0,
    sector_heat_score: float = 0.0,
    regime: str = "ranging",
    day_of_week: int = 0,
    stock_return_5d: float = 0.0,
    volume_ratio_5d: float = 0.0,
) -> float | None:
    """Predict trade confidence score (0-100) using the active model.

    Returns None if no active model is available.
    Thread-safe: uses cached model params, loads from DB on cache miss.

    gamma_snapshot: dict with keys {daily_strength, weekly_resonance,
                    structure_health, daily_mmd_age} or None.
    """
    global _cached_params

    params = None
    with _cache_lock:
        params = _cached_params

    if params is None:
        params = _load_active_model(db)
        if params is None:
            return None

    # Build gamma features from snapshot dict
    if gamma_snapshot is not None:
        gamma_daily_strength = float(gamma_snapshot.get("daily_strength", 0.0))
        gamma_weekly_resonance = float(gamma_snapshot.get("weekly_resonance", 0.0))
        gamma_structure_health = float(gamma_snapshot.get("structure_health", 0.0))
        gamma_mmd_age = float(gamma_snapshot.get("daily_mmd_age", 0.0))
        gamma_bc_confirmed = 1.0 if gamma_structure_health >= 10 else 0.0
        has_gamma = 1.0
    else:
        gamma_daily_strength = 0.0
        gamma_weekly_resonance = 0.0
        gamma_structure_health = 0.0
        gamma_mmd_age = 0.0
        gamma_bc_confirmed = 0.0
        has_gamma = 0.0

    regime_encoded = float(REGIME_MAP.get(regime, 0.0))

    features = [
        float(alpha),
        gamma_daily_strength,
        gamma_weekly_resonance,
        gamma_structure_health,
        gamma_mmd_age,
        gamma_bc_confirmed,
        has_gamma,
        float(trend_strength),
        float(volatility),
        float(index_return_pct),
        float(sector_heat_score),
        regime_encoded,
        float(day_of_week),
        float(stock_return_5d),
        float(volume_ratio_5d),
    ]

    # Backward compatibility: if model was trained with fewer features,
    # truncate to match stored coefficient count
    coef_len = len(params.get("coef", []))
    if coef_len > 0 and coef_len != len(features):
        logger.info(
            "Feature count mismatch: model has %d coefs, input has %d features — truncating",
            coef_len, len(features),
        )
        features = features[:coef_len]

    try:
        score = _predict_from_params(params, features)
        return round(score, 1)
    except Exception as e:
        logger.warning("Confidence prediction failed: %s", e)
        return None


def get_model_report(db: Session) -> dict:
    """Return a report dict for the active confidence model."""
    model = (
        db.query(ConfidenceModel)
        .filter(ConfidenceModel.is_active == True)
        .order_by(ConfidenceModel.version.desc())
        .first()
    )
    if not model:
        return {"status": "no_active_model"}

    coefficients = {}
    if model.model_params and model.feature_names:
        coef = model.model_params.get("coef", [])
        for name, c in zip(model.feature_names, coef):
            coefficients[name] = round(c, 6)

    report = {
        "status": "active",
        "version": model.version,
        "auc_score": model.auc_score,
        "brier_score": model.brier_score,
        "training_samples": model.training_samples,
        "positive_rate": round(model.positive_rate, 4),
        "feature_names": model.feature_names,
        "coefficients": coefficients,
        "created_at": model.created_at.isoformat() if model.created_at else None,
    }
    if model.calibration_data:
        report["calibration"] = model.calibration_data
    return report
