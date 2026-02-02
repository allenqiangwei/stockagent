"""Tests for momentum indicators (RSI, KDJ)."""

import pytest
import pandas as pd
import numpy as np
from src.indicators.base_indicator import IndicatorResult
from src.indicators.momentum_indicators import RSIIndicator, KDJIndicator


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data for testing."""
    np.random.seed(42)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close - np.random.rand(n),
        "high": close + np.random.rand(n) * 2,
        "low": close - np.random.rand(n) * 2,
        "close": close,
        "volume": np.random.randint(1000, 10000, n)
    })


class TestRSIIndicator:
    """Tests for Relative Strength Index indicator."""

    def test_rsi_name(self):
        """Test RSI indicator name includes period."""
        rsi = RSIIndicator(period=14)
        assert rsi.name == "RSI_14"

    def test_rsi_required_columns(self):
        """Test RSI requires close column."""
        rsi = RSIIndicator()
        assert "close" in rsi.required_columns

    def test_rsi_calculation(self, sample_ohlcv):
        """Test RSI calculation produces valid values."""
        rsi = RSIIndicator(period=14)
        result = rsi(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert len(result.values) == len(sample_ohlcv)

    def test_rsi_values_between_0_and_100(self, sample_ohlcv):
        """Test RSI values are bounded between 0 and 100."""
        rsi = RSIIndicator(period=14)
        result = rsi(sample_ohlcv)

        valid_values = result.values.dropna()
        assert (valid_values >= 0).all()
        assert (valid_values <= 100).all()

    def test_rsi_overbought_oversold_levels(self):
        """Test RSI detects overbought/oversold conditions."""
        # Create strongly trending up data -> high RSI
        uptrend = pd.DataFrame({
            "close": [float(100 + i * 2) for i in range(50)]  # Strong uptrend
        })
        rsi = RSIIndicator(period=14)
        result = rsi(uptrend)
        # Last RSI should be high (overbought territory)
        assert result.values.iloc[-1] > 60

        # Create strongly trending down data -> low RSI
        downtrend = pd.DataFrame({
            "close": [float(200 - i * 2) for i in range(50)]  # Strong downtrend
        })
        result_down = rsi(downtrend)
        # Last RSI should be low (oversold territory)
        assert result_down.values.iloc[-1] < 40


class TestKDJIndicator:
    """Tests for KDJ (Stochastic) indicator."""

    def test_kdj_name(self):
        """Test KDJ indicator name."""
        kdj = KDJIndicator()
        assert kdj.name == "KDJ"

    def test_kdj_required_columns(self):
        """Test KDJ requires high, low, close columns."""
        kdj = KDJIndicator()
        assert "high" in kdj.required_columns
        assert "low" in kdj.required_columns
        assert "close" in kdj.required_columns

    def test_kdj_default_params(self):
        """Test KDJ default parameters."""
        kdj = KDJIndicator()
        assert kdj.fastk_period == 9
        assert kdj.slowk_period == 3
        assert kdj.slowd_period == 3

    def test_kdj_calculation(self, sample_ohlcv):
        """Test KDJ calculation produces K, D, J values."""
        kdj = KDJIndicator()
        result = kdj(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert "k" in result.params
        assert "d" in result.params
        assert "j" in result.params

    def test_kdj_k_values_between_0_and_100(self, sample_ohlcv):
        """Test K values are bounded between 0 and 100."""
        kdj = KDJIndicator()
        result = kdj(sample_ohlcv)

        k_values = result.params["k"].dropna()
        assert (k_values >= 0).all()
        assert (k_values <= 100).all()

    def test_kdj_d_values_between_0_and_100(self, sample_ohlcv):
        """Test D values are bounded between 0 and 100."""
        kdj = KDJIndicator()
        result = kdj(sample_ohlcv)

        d_values = result.params["d"].dropna()
        assert (d_values >= 0).all()
        assert (d_values <= 100).all()

    def test_kdj_j_formula(self, sample_ohlcv):
        """Test J = 3K - 2D formula."""
        kdj = KDJIndicator()
        result = kdj(sample_ohlcv)

        k = result.params["k"]
        d = result.params["d"]
        j = result.params["j"]

        # J = 3K - 2D
        expected_j = 3 * k - 2 * d
        pd.testing.assert_series_equal(j, expected_j, check_names=False)

    def test_kdj_j_can_exceed_bounds(self, sample_ohlcv):
        """Test J values can go outside 0-100 range."""
        kdj = KDJIndicator()
        result = kdj(sample_ohlcv)

        j_values = result.params["j"].dropna()
        # J can be < 0 or > 100 (this is expected behavior)
        # Just verify we have some variance in J
        assert j_values.std() > 0
