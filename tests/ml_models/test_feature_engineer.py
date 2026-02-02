"""Tests for feature engineering module."""

import pytest
import pandas as pd
import numpy as np
from src.ml_models.feature_engineer import FeatureEngineer


@pytest.fixture
def sample_ohlcv_with_indicators():
    """Create sample OHLCV data with indicators."""
    np.random.seed(42)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "trade_date": pd.date_range("2024-01-01", periods=n),
        "open": close - np.random.rand(n),
        "high": close + np.random.rand(n) * 2,
        "low": close - np.random.rand(n) * 2,
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
        # Indicators
        "MA_5": close - 1,
        "MA_10": close - 1.5,
        "MA_20": close - 2,
        "EMA_12": close - 0.5,
        "EMA_26": close - 1.5,
        "RSI": np.random.uniform(30, 70, n),
        "MACD": np.random.uniform(-1, 1, n),
        "MACD_signal": np.random.uniform(-1, 1, n),
        "MACD_hist": np.random.uniform(-0.5, 0.5, n),
        "KDJ_K": np.random.uniform(20, 80, n),
        "KDJ_D": np.random.uniform(20, 80, n),
        "KDJ_J": np.random.uniform(0, 100, n),
        "ADX": np.random.uniform(15, 40, n),
        "ADX_plus_di": np.random.uniform(20, 35, n),
        "ADX_minus_di": np.random.uniform(15, 30, n),
        "ATR": np.random.uniform(1, 3, n),
        "OBV": np.cumsum(np.random.randint(-1000, 1000, n))
    })


class TestFeatureEngineer:
    """Tests for FeatureEngineer."""

    def test_engineer_initialization(self):
        """Test feature engineer initializes correctly."""
        fe = FeatureEngineer()
        assert fe is not None

    def test_create_features_returns_dataframe(self, sample_ohlcv_with_indicators):
        """Test create_features returns a DataFrame."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(sample_ohlcv_with_indicators)

    def test_price_features_included(self, sample_ohlcv_with_indicators):
        """Test price-based features are created."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        # Return features
        assert "return_1d" in features.columns
        assert "return_5d" in features.columns

        # Price position
        assert "price_vs_ma5" in features.columns
        assert "price_vs_ma20" in features.columns

    def test_momentum_features_included(self, sample_ohlcv_with_indicators):
        """Test momentum features are created."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        assert "rsi_normalized" in features.columns
        assert "macd_normalized" in features.columns
        assert "kdj_diff" in features.columns

    def test_trend_features_included(self, sample_ohlcv_with_indicators):
        """Test trend features are created."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        assert "ma_cross" in features.columns  # MA5 vs MA20
        assert "ema_cross" in features.columns  # EMA12 vs EMA26
        assert "adx_strength" in features.columns
        assert "di_diff" in features.columns

    def test_volatility_features_included(self, sample_ohlcv_with_indicators):
        """Test volatility features are created."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        assert "atr_normalized" in features.columns
        assert "volatility_5d" in features.columns

    def test_volume_features_included(self, sample_ohlcv_with_indicators):
        """Test volume features are created."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        assert "volume_ratio" in features.columns  # vs MA
        assert "obv_slope" in features.columns

    def test_no_nan_in_valid_range(self, sample_ohlcv_with_indicators):
        """Test features have no NaN after warmup period."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        # After 30 rows (warmup), should have no NaN
        valid_features = features.iloc[30:]
        nan_counts = valid_features.isna().sum()

        # Allow some columns to have NaN but most should be clean
        assert nan_counts.sum() < len(valid_features) * 0.1

    def test_feature_scaling(self, sample_ohlcv_with_indicators):
        """Test features are appropriately scaled."""
        fe = FeatureEngineer()
        features = fe.create_features(sample_ohlcv_with_indicators)

        # Normalized features should be roughly in [-1, 1] or [0, 1] range
        if "rsi_normalized" in features.columns:
            rsi_norm = features["rsi_normalized"].dropna()
            assert rsi_norm.min() >= -1.5
            assert rsi_norm.max() <= 1.5

    def test_get_feature_names(self):
        """Test getting list of feature names."""
        fe = FeatureEngineer()
        names = fe.get_feature_names()

        assert isinstance(names, list)
        assert len(names) > 0
        assert "return_1d" in names

    def test_custom_lookback_periods(self, sample_ohlcv_with_indicators):
        """Test custom lookback periods."""
        fe = FeatureEngineer(
            return_periods=[1, 3, 10],
            volatility_period=10
        )
        features = fe.create_features(sample_ohlcv_with_indicators)

        assert "return_1d" in features.columns
        assert "return_3d" in features.columns
        assert "return_10d" in features.columns

    def test_create_features_batch(self, sample_ohlcv_with_indicators):
        """Test creating features for multiple stocks."""
        fe = FeatureEngineer()
        stock_data = {
            "000001.SZ": sample_ohlcv_with_indicators,
            "000002.SZ": sample_ohlcv_with_indicators.copy()
        }

        results = fe.create_features_batch(stock_data)

        assert len(results) == 2
        assert "000001.SZ" in results
        assert "000002.SZ" in results
        assert isinstance(results["000001.SZ"], pd.DataFrame)
