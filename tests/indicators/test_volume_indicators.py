"""Tests for volume/volatility indicators (OBV, ATR)."""

import pytest
import pandas as pd
import numpy as np
from src.indicators.base_indicator import IndicatorResult
from src.indicators.volume_indicators import OBVIndicator, ATRIndicator


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
        "volume": np.random.randint(1000, 10000, n).astype(float)
    })


class TestOBVIndicator:
    """Tests for On-Balance Volume indicator."""

    def test_obv_name(self):
        """Test OBV indicator name."""
        obv = OBVIndicator()
        assert obv.name == "OBV"

    def test_obv_required_columns(self):
        """Test OBV requires close and volume columns."""
        obv = OBVIndicator()
        assert "close" in obv.required_columns
        assert "volume" in obv.required_columns

    def test_obv_calculation(self, sample_ohlcv):
        """Test OBV calculation produces valid values."""
        obv = OBVIndicator()
        result = obv(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert len(result.values) == len(sample_ohlcv)
        # OBV should have no NaN values
        assert not result.values.isna().any()

    def test_obv_cumulative_nature(self):
        """Test OBV accumulates volume based on price direction."""
        df = pd.DataFrame({
            "close": [10.0, 11.0, 10.5, 12.0, 11.5],  # up, down, up, down
            "volume": [100.0, 200.0, 150.0, 300.0, 250.0]
        })
        obv = OBVIndicator()
        result = obv(df)

        # First OBV = 0 (or first volume)
        # Day 2: price up -> +200 -> OBV = 200
        # Day 3: price down -> -150 -> OBV = 50
        # Day 4: price up -> +300 -> OBV = 350
        # Day 5: price down -> -250 -> OBV = 100
        expected = pd.Series([100.0, 300.0, 150.0, 450.0, 200.0])
        pd.testing.assert_series_equal(
            result.values.reset_index(drop=True),
            expected,
            check_names=False
        )

    def test_obv_unchanged_price(self):
        """Test OBV unchanged when price doesn't change."""
        df = pd.DataFrame({
            "close": [10.0, 10.0, 10.0],
            "volume": [100.0, 200.0, 150.0]
        })
        obv = OBVIndicator()
        result = obv(df)

        # When price unchanged, OBV stays the same
        assert result.values.iloc[1] == result.values.iloc[0]
        assert result.values.iloc[2] == result.values.iloc[1]


class TestATRIndicator:
    """Tests for Average True Range indicator."""

    def test_atr_name(self):
        """Test ATR indicator name includes period."""
        atr = ATRIndicator(period=14)
        assert atr.name == "ATR_14"

    def test_atr_required_columns(self):
        """Test ATR requires high, low, close columns."""
        atr = ATRIndicator()
        assert "high" in atr.required_columns
        assert "low" in atr.required_columns
        assert "close" in atr.required_columns

    def test_atr_calculation(self, sample_ohlcv):
        """Test ATR calculation produces valid values."""
        atr = ATRIndicator(period=14)
        result = atr(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert len(result.values) == len(sample_ohlcv)

    def test_atr_always_positive(self, sample_ohlcv):
        """Test ATR values are always positive."""
        atr = ATRIndicator(period=14)
        result = atr(sample_ohlcv)

        valid_values = result.values.dropna()
        assert (valid_values >= 0).all()

    def test_atr_reflects_volatility(self):
        """Test ATR is higher during volatile periods."""
        # Low volatility data
        low_vol = pd.DataFrame({
            "high": [10.1, 10.2, 10.1, 10.2, 10.1] * 10,
            "low": [9.9, 9.8, 9.9, 9.8, 9.9] * 10,
            "close": [10.0, 10.0, 10.0, 10.0, 10.0] * 10
        })

        # High volatility data
        high_vol = pd.DataFrame({
            "high": [12.0, 12.0, 12.0, 12.0, 12.0] * 10,
            "low": [8.0, 8.0, 8.0, 8.0, 8.0] * 10,
            "close": [10.0, 10.0, 10.0, 10.0, 10.0] * 10
        })

        atr = ATRIndicator(period=5)
        low_vol_result = atr(low_vol)
        high_vol_result = atr(high_vol)

        # High volatility ATR should be greater
        assert high_vol_result.values.iloc[-1] > low_vol_result.values.iloc[-1]

    def test_atr_includes_true_range(self, sample_ohlcv):
        """Test ATR result includes true range values."""
        atr = ATRIndicator(period=14)
        result = atr(sample_ohlcv)

        assert "true_range" in result.params
        tr = result.params["true_range"]
        assert len(tr) == len(sample_ohlcv)
        # True range should always be positive
        assert (tr.dropna() >= 0).all()
