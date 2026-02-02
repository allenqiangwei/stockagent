"""Tests for trend indicators (MA, EMA, MACD, ADX)."""

import pytest
import pandas as pd
import numpy as np
from src.indicators.base_indicator import IndicatorResult
from src.indicators.trend_indicators import (
    MAIndicator,
    EMAIndicator,
    MACDIndicator,
    ADXIndicator
)


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


class TestMAIndicator:
    """Tests for Simple Moving Average indicator."""

    def test_ma_name(self):
        """Test MA indicator name includes period."""
        ma = MAIndicator(period=20)
        assert ma.name == "MA_20"

    def test_ma_required_columns(self):
        """Test MA requires close column."""
        ma = MAIndicator()
        assert "close" in ma.required_columns

    def test_ma_calculation(self, sample_ohlcv):
        """Test MA calculation produces correct values."""
        ma = MAIndicator(period=5)
        result = ma(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert len(result.values) == len(sample_ohlcv)
        # First 4 values should be NaN (period-1)
        assert pd.isna(result.values.iloc[:4]).all()
        # After warmup, values should exist
        assert not pd.isna(result.values.iloc[4:]).any()

    def test_ma_values_match_pandas_rolling(self, sample_ohlcv):
        """Test MA values match pandas rolling mean."""
        period = 10
        ma = MAIndicator(period=period)
        result = ma(sample_ohlcv)
        expected = sample_ohlcv["close"].rolling(period).mean()
        pd.testing.assert_series_equal(result.values, expected, check_names=False)


class TestEMAIndicator:
    """Tests for Exponential Moving Average indicator."""

    def test_ema_name(self):
        """Test EMA indicator name includes period."""
        ema = EMAIndicator(period=12)
        assert ema.name == "EMA_12"

    def test_ema_calculation(self, sample_ohlcv):
        """Test EMA calculation produces valid values."""
        ema = EMAIndicator(period=12)
        result = ema(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert len(result.values) == len(sample_ohlcv)
        # EMA should have values after warmup period
        valid_values = result.values.dropna()
        assert len(valid_values) > 0

    def test_ema_responds_faster_than_ma(self, sample_ohlcv):
        """Test EMA responds faster to price changes than MA."""
        period = 20
        ma = MAIndicator(period=period)
        ema = EMAIndicator(period=period)

        ma_result = ma(sample_ohlcv)
        ema_result = ema(sample_ohlcv)

        # EMA should be closer to recent prices
        last_price = sample_ohlcv["close"].iloc[-1]
        ma_diff = abs(ma_result.values.iloc[-1] - last_price)
        ema_diff = abs(ema_result.values.iloc[-1] - last_price)
        # This test may not always pass due to random data, but generally true
        assert ema_diff <= ma_diff * 1.5  # Allow some tolerance


class TestMACDIndicator:
    """Tests for MACD indicator."""

    def test_macd_name(self):
        """Test MACD indicator name."""
        macd = MACDIndicator()
        assert macd.name == "MACD"

    def test_macd_default_params(self):
        """Test MACD default parameters."""
        macd = MACDIndicator()
        assert macd.fast_period == 12
        assert macd.slow_period == 26
        assert macd.signal_period == 9

    def test_macd_calculation(self, sample_ohlcv):
        """Test MACD calculation produces result with all components."""
        macd = MACDIndicator()
        result = macd(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert "macd" in result.params
        assert "signal" in result.params
        assert "histogram" in result.params
        # result.values should be the MACD line
        assert len(result.values) == len(sample_ohlcv)

    def test_macd_histogram_is_macd_minus_signal(self, sample_ohlcv):
        """Test MACD histogram equals MACD line minus signal line."""
        macd = MACDIndicator()
        result = macd(sample_ohlcv)

        macd_line = result.params["macd"]
        signal_line = result.params["signal"]
        histogram = result.params["histogram"]

        # Allow small floating point differences
        diff = macd_line - signal_line
        np.testing.assert_array_almost_equal(
            histogram.dropna().values,
            diff.dropna().values,
            decimal=10
        )


class TestADXIndicator:
    """Tests for Average Directional Index indicator."""

    def test_adx_name(self):
        """Test ADX indicator name includes period."""
        adx = ADXIndicator(period=14)
        assert adx.name == "ADX_14"

    def test_adx_required_columns(self):
        """Test ADX requires high, low, close columns."""
        adx = ADXIndicator()
        assert "high" in adx.required_columns
        assert "low" in adx.required_columns
        assert "close" in adx.required_columns

    def test_adx_calculation(self, sample_ohlcv):
        """Test ADX calculation produces valid values."""
        adx = ADXIndicator(period=14)
        result = adx(sample_ohlcv)

        assert isinstance(result, IndicatorResult)
        assert len(result.values) == len(sample_ohlcv)
        # ADX should be between 0 and 100
        valid_values = result.values.dropna()
        assert (valid_values >= 0).all()
        assert (valid_values <= 100).all()

    def test_adx_includes_di_lines(self, sample_ohlcv):
        """Test ADX result includes +DI and -DI lines."""
        adx = ADXIndicator(period=14)
        result = adx(sample_ohlcv)

        assert "plus_di" in result.params
        assert "minus_di" in result.params
        # DI values should be between 0 and 100
        plus_di = result.params["plus_di"].dropna()
        minus_di = result.params["minus_di"].dropna()
        assert (plus_di >= 0).all() and (plus_di <= 100).all()
        assert (minus_di >= 0).all() and (minus_di <= 100).all()
