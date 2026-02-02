"""Tests for label builder and XGBoost model trainer."""

import pytest
import pandas as pd
import numpy as np
from src.ml_models.model_trainer import (
    LabelBuilder,
    XGBoostTrainer,
    SignalLabel
)


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data."""
    np.random.seed(42)
    n = 200
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "trade_date": pd.date_range("2024-01-01", periods=n),
        "close": close,
        "high": close + np.random.rand(n) * 2,
        "low": close - np.random.rand(n) * 2,
        "volume": np.random.randint(1000, 10000, n).astype(float)
    })


@pytest.fixture
def sample_features():
    """Create sample feature data."""
    np.random.seed(42)
    n = 200
    return pd.DataFrame({
        "return_1d": np.random.randn(n) * 2,
        "return_5d": np.random.randn(n) * 4,
        "price_vs_ma5": np.random.randn(n) * 3,
        "price_vs_ma20": np.random.randn(n) * 5,
        "rsi_normalized": np.random.uniform(-1, 1, n),
        "macd_normalized": np.random.randn(n) * 0.5,
        "kdj_diff": np.random.uniform(-0.5, 0.5, n),
        "ma_cross": np.random.randn(n) * 2,
        "adx_strength": np.random.uniform(0, 0.5, n),
        "di_diff": np.random.uniform(-0.3, 0.3, n),
        "atr_normalized": np.random.uniform(0.5, 3, n),
        "volume_ratio": np.random.uniform(0.5, 2, n)
    })


class TestSignalLabel:
    """Tests for SignalLabel enum."""

    def test_label_values(self):
        """Test label integer values."""
        assert SignalLabel.STRONG_SELL == 0
        assert SignalLabel.WEAK_SELL == 1
        assert SignalLabel.HOLD == 2
        assert SignalLabel.WEAK_BUY == 3
        assert SignalLabel.STRONG_BUY == 4


class TestLabelBuilder:
    """Tests for LabelBuilder."""

    def test_default_thresholds(self):
        """Test default return thresholds."""
        builder = LabelBuilder()
        assert builder.strong_buy_threshold == 5.0
        assert builder.weak_buy_threshold == 2.0
        assert builder.weak_sell_threshold == -2.0
        assert builder.strong_sell_threshold == -5.0

    def test_custom_thresholds(self):
        """Test custom thresholds."""
        builder = LabelBuilder(
            strong_buy_threshold=10.0,
            weak_buy_threshold=5.0
        )
        assert builder.strong_buy_threshold == 10.0
        assert builder.weak_buy_threshold == 5.0

    def test_create_labels_returns_series(self, sample_ohlcv):
        """Test create_labels returns a Series."""
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        assert isinstance(labels, pd.Series)
        assert len(labels) == len(sample_ohlcv)

    def test_label_values_are_valid(self, sample_ohlcv):
        """Test all labels are valid SignalLabel values."""
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        valid_labels = labels.dropna()
        assert all(label in [0, 1, 2, 3, 4] for label in valid_labels)

    def test_forward_return_calculation(self, sample_ohlcv):
        """Test forward returns are calculated correctly."""
        builder = LabelBuilder()
        returns = builder.calculate_forward_returns(sample_ohlcv, forward_days=5)

        # Forward returns should be NaN for last 5 rows
        assert returns.iloc[-5:].isna().all()
        # Should have values before that
        assert not returns.iloc[:-5].isna().all()

    def test_strong_buy_label_for_high_return(self):
        """Test high forward return gets STRONG_BUY label."""
        df = pd.DataFrame({
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]  # 10% return
        })
        builder = LabelBuilder(strong_buy_threshold=5.0)
        labels = builder.create_labels(df, forward_days=5)

        assert labels.iloc[0] == SignalLabel.STRONG_BUY

    def test_strong_sell_label_for_low_return(self):
        """Test low forward return gets STRONG_SELL label."""
        df = pd.DataFrame({
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 90.0]  # -10% return
        })
        builder = LabelBuilder(strong_sell_threshold=-5.0)
        labels = builder.create_labels(df, forward_days=5)

        assert labels.iloc[0] == SignalLabel.STRONG_SELL

    def test_hold_label_for_small_return(self):
        """Test small forward return gets HOLD label."""
        df = pd.DataFrame({
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.5]  # 0.5% return
        })
        builder = LabelBuilder()
        labels = builder.create_labels(df, forward_days=5)

        assert labels.iloc[0] == SignalLabel.HOLD


class TestXGBoostTrainer:
    """Tests for XGBoostTrainer."""

    def test_trainer_initialization(self):
        """Test trainer initializes correctly."""
        trainer = XGBoostTrainer()
        assert trainer.model is None

    def test_train_creates_model(self, sample_features, sample_ohlcv):
        """Test training creates a model."""
        # Create labels
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        # Align features and labels, drop NaN
        valid_idx = ~labels.isna()
        X = sample_features[valid_idx].iloc[:-5]  # Exclude last 5 (no labels)
        y = labels[valid_idx].iloc[:-5]

        # Drop any remaining NaN in features
        valid_rows = ~X.isna().any(axis=1)
        X = X[valid_rows]
        y = y[valid_rows]

        trainer = XGBoostTrainer()
        trainer.train(X, y)

        assert trainer.model is not None

    def test_predict_returns_scores(self, sample_features, sample_ohlcv):
        """Test predict returns score array."""
        # Setup
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        valid_idx = ~labels.isna()
        X = sample_features[valid_idx].iloc[:-5]
        y = labels[valid_idx].iloc[:-5]

        valid_rows = ~X.isna().any(axis=1)
        X = X[valid_rows]
        y = y[valid_rows]

        trainer = XGBoostTrainer()
        trainer.train(X, y)

        # Predict
        predictions = trainer.predict(X.iloc[:10])

        assert len(predictions) == 10
        assert all(0 <= p <= 100 for p in predictions)

    def test_predict_proba_returns_probabilities(self, sample_features, sample_ohlcv):
        """Test predict_proba returns class probabilities."""
        # Setup
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        valid_idx = ~labels.isna()
        X = sample_features[valid_idx].iloc[:-5]
        y = labels[valid_idx].iloc[:-5]

        valid_rows = ~X.isna().any(axis=1)
        X = X[valid_rows]
        y = y[valid_rows]

        trainer = XGBoostTrainer()
        trainer.train(X, y)

        # Predict probabilities
        probas = trainer.predict_proba(X.iloc[:10])

        assert probas.shape == (10, 5)  # 5 classes
        # Probabilities should sum to 1
        assert np.allclose(probas.sum(axis=1), 1.0)

    def test_save_and_load_model(self, sample_features, sample_ohlcv, tmp_path):
        """Test model can be saved and loaded."""
        # Setup and train
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        valid_idx = ~labels.isna()
        X = sample_features[valid_idx].iloc[:-5]
        y = labels[valid_idx].iloc[:-5]

        valid_rows = ~X.isna().any(axis=1)
        X = X[valid_rows]
        y = y[valid_rows]

        trainer = XGBoostTrainer()
        trainer.train(X, y)

        # Save
        model_path = tmp_path / "model.json"
        trainer.save(str(model_path))

        assert model_path.exists()

        # Load into new trainer
        new_trainer = XGBoostTrainer()
        new_trainer.load(str(model_path))

        assert new_trainer.model is not None

        # Predictions should match
        pred1 = trainer.predict(X.iloc[:5])
        pred2 = new_trainer.predict(X.iloc[:5])

        np.testing.assert_array_almost_equal(pred1, pred2)

    def test_feature_importance(self, sample_features, sample_ohlcv):
        """Test getting feature importance."""
        # Setup and train
        builder = LabelBuilder()
        labels = builder.create_labels(sample_ohlcv, forward_days=5)

        valid_idx = ~labels.isna()
        X = sample_features[valid_idx].iloc[:-5]
        y = labels[valid_idx].iloc[:-5]

        valid_rows = ~X.isna().any(axis=1)
        X = X[valid_rows]
        y = y[valid_rows]

        trainer = XGBoostTrainer()
        trainer.train(X, y)

        importance = trainer.get_feature_importance()

        assert isinstance(importance, dict)
        assert len(importance) > 0
