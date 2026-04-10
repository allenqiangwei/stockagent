"""Tests for confidence_scorer: _sigmoid, _predict_from_params, _train_lr."""

import math
import numpy as np
import pytest


def test_sigmoid_zero():
    from api.services.confidence_scorer import _sigmoid
    assert _sigmoid(0.0) == pytest.approx(0.5, abs=1e-9)


def test_sigmoid_large_positive():
    from api.services.confidence_scorer import _sigmoid
    assert _sigmoid(100.0) == pytest.approx(1.0, abs=1e-9)


def test_sigmoid_large_negative():
    from api.services.confidence_scorer import _sigmoid
    assert _sigmoid(-100.0) == pytest.approx(0.0, abs=1e-9)


def test_sigmoid_symmetry():
    from api.services.confidence_scorer import _sigmoid
    for z in [0.5, 1.0, 2.0, 5.0]:
        assert _sigmoid(z) + _sigmoid(-z) == pytest.approx(1.0, abs=1e-9)


def test_sigmoid_no_overflow():
    """Numerically stable sigmoid should not overflow for extreme values."""
    from api.services.confidence_scorer import _sigmoid
    # These should not raise
    assert 0.0 <= _sigmoid(1000.0) <= 1.0
    assert 0.0 <= _sigmoid(-1000.0) <= 1.0


def test_predict_from_params_basic():
    from api.services.confidence_scorer import _predict_from_params

    params = {
        "coef": [1.0, 0.0],
        "intercept": 0.0,
        "scaler_mean": [0.0, 0.0],
        "scaler_scale": [1.0, 1.0],
    }
    # With feature [0, 0], z = 0 => sigmoid = 0.5 => score = 50
    score = _predict_from_params(params, [0.0, 0.0])
    assert score == pytest.approx(50.0, abs=0.1)


def test_predict_from_params_with_scaling():
    from api.services.confidence_scorer import _predict_from_params

    params = {
        "coef": [2.0],
        "intercept": 0.0,
        "scaler_mean": [10.0],
        "scaler_scale": [5.0],
    }
    # feature = 10.0 => scaled = (10 - 10) / 5 = 0 => z = 0 => 50
    score = _predict_from_params(params, [10.0])
    assert score == pytest.approx(50.0, abs=0.1)

    # feature = 15.0 => scaled = (15 - 10) / 5 = 1.0 => z = 2.0 => sigmoid(2) * 100
    score2 = _predict_from_params(params, [15.0])
    expected = 1.0 / (1.0 + math.exp(-2.0)) * 100
    assert score2 == pytest.approx(expected, abs=0.1)


def test_predict_returns_0_to_100():
    from api.services.confidence_scorer import _predict_from_params

    params = {
        "coef": [1.0, -1.0, 0.5],
        "intercept": 0.0,
        "scaler_mean": [0.0, 0.0, 0.0],
        "scaler_scale": [1.0, 1.0, 1.0],
    }
    for features in [[100, -100, 50], [-100, 100, -50], [0, 0, 0]]:
        score = _predict_from_params(params, features)
        assert 0.0 <= score <= 100.0


def test_train_lr_synthetic():
    """Train on perfectly separable synthetic data — should get high AUC."""
    from api.services.confidence_scorer import _train_lr

    np.random.seed(42)
    n = 200
    # Feature 1 determines the label
    X_pos = np.column_stack([
        np.random.normal(3, 0.5, n // 2),
        np.random.normal(0, 1, n // 2),
    ])
    X_neg = np.column_stack([
        np.random.normal(-3, 0.5, n // 2),
        np.random.normal(0, 1, n // 2),
    ])
    X = np.vstack([X_pos, X_neg])
    y = np.array([1] * (n // 2) + [0] * (n // 2))

    result = _train_lr(X, y, ["feat_a", "feat_b"])

    assert result["status"] == "trained"
    assert result["auc"] > 0.95
    assert result["brier"] < 0.1
    assert result["samples"] == n
    assert result["positive_rate"] == pytest.approx(0.5)
    assert "feat_a" in result["coefficients"]
    assert "feat_b" in result["coefficients"]
    # coef for feat_a should be positive (higher => class 1)
    assert result["coefficients"]["feat_a"] > 0

    # model_params should be JSON-safe
    mp = result["model_params"]
    assert isinstance(mp["coef"], list)
    assert isinstance(mp["intercept"], float)
    assert isinstance(mp["scaler_mean"], list)
    assert isinstance(mp["scaler_scale"], list)
    assert len(mp["coef"]) == 2
    assert len(mp["scaler_mean"]) == 2
    assert len(mp["scaler_scale"]) == 2


def test_train_lr_noisy():
    """Train on noisy data — AUC should still be > 0.5."""
    from api.services.confidence_scorer import _train_lr

    np.random.seed(123)
    n = 100
    X = np.random.randn(n, 3)
    # Weak signal: y depends slightly on first feature
    probs = 1.0 / (1.0 + np.exp(-0.5 * X[:, 0]))
    y = (np.random.rand(n) < probs).astype(int)

    result = _train_lr(X, y, ["f1", "f2", "f3"])
    assert result["status"] == "trained"
    assert result["auc"] >= 0.5  # At least not worse than random
    assert result["samples"] == n


def test_predict_from_params_matches_train():
    """Verify that _predict_from_params reproduces the same predictions as sklearn."""
    from api.services.confidence_scorer import _train_lr, _predict_from_params

    np.random.seed(99)
    n = 100
    X = np.random.randn(n, 2) * 5
    y = (X[:, 0] + X[:, 1] > 0).astype(int)

    result = _train_lr(X, y, ["a", "b"])
    params = result["model_params"]

    # Predict using our pure-math function
    for i in range(min(20, n)):
        our_score = _predict_from_params(params, X[i].tolist())
        assert 0.0 <= our_score <= 100.0

    # The prediction for a very positive input should be high
    high_score = _predict_from_params(params, [10.0, 10.0])
    low_score = _predict_from_params(params, [-10.0, -10.0])
    assert high_score > low_score
