"""Tests for unified indicator calculator."""

import pytest
import pandas as pd
import numpy as np
from src.indicators.indicator_calculator import IndicatorCalculator, IndicatorConfig


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


class TestIndicatorConfig:
    """Tests for indicator configuration."""

    def test_default_config(self):
        """Test default configuration has all indicators enabled."""
        config = IndicatorConfig()
        assert config.ma_periods == [5, 10, 20, 60]
        assert config.ema_periods == [12, 26]
        assert config.rsi_period == 14
        assert config.macd_params == (12, 26, 9)
        assert config.kdj_params == (9, 3, 3)
        assert config.adx_period == 14
        assert config.atr_period == 14

    def test_custom_config(self):
        """Test custom configuration override."""
        config = IndicatorConfig(
            ma_periods=[10, 20],
            rsi_period=7
        )
        assert config.ma_periods == [10, 20]
        assert config.rsi_period == 7
        # Others should be default
        assert config.adx_period == 14


class TestIndicatorCalculator:
    """Tests for IndicatorCalculator."""

    def test_calculator_initialization(self):
        """Test calculator initializes with config."""
        calc = IndicatorCalculator()
        assert calc.config is not None

    def test_calculator_custom_config(self):
        """Test calculator accepts custom config."""
        config = IndicatorConfig(ma_periods=[5, 10])
        calc = IndicatorCalculator(config=config)
        assert calc.config.ma_periods == [5, 10]

    def test_calculate_all_returns_dataframe(self, sample_ohlcv):
        """Test calculate_all returns DataFrame with all indicators."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(sample_ohlcv)

    def test_calculate_all_includes_ma(self, sample_ohlcv):
        """Test result includes MA indicators."""
        config = IndicatorConfig(ma_periods=[5, 10])
        calc = IndicatorCalculator(config=config)
        result = calc.calculate_all(sample_ohlcv)

        assert "MA_5" in result.columns
        assert "MA_10" in result.columns

    def test_calculate_all_includes_ema(self, sample_ohlcv):
        """Test result includes EMA indicators."""
        config = IndicatorConfig(ema_periods=[12, 26])
        calc = IndicatorCalculator(config=config)
        result = calc.calculate_all(sample_ohlcv)

        assert "EMA_12" in result.columns
        assert "EMA_26" in result.columns

    def test_calculate_all_includes_rsi(self, sample_ohlcv):
        """Test result includes RSI indicator."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert "RSI" in result.columns

    def test_calculate_all_includes_macd(self, sample_ohlcv):
        """Test result includes MACD components."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert "MACD" in result.columns
        assert "MACD_signal" in result.columns
        assert "MACD_hist" in result.columns

    def test_calculate_all_includes_kdj(self, sample_ohlcv):
        """Test result includes KDJ components."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert "KDJ_K" in result.columns
        assert "KDJ_D" in result.columns
        assert "KDJ_J" in result.columns

    def test_calculate_all_includes_adx(self, sample_ohlcv):
        """Test result includes ADX and DI lines."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert "ADX" in result.columns
        assert "ADX_plus_di" in result.columns
        assert "ADX_minus_di" in result.columns

    def test_calculate_all_includes_obv(self, sample_ohlcv):
        """Test result includes OBV indicator."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert "OBV" in result.columns

    def test_calculate_all_includes_atr(self, sample_ohlcv):
        """Test result includes ATR indicator."""
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        assert "ATR" in result.columns

    def test_calculate_all_preserves_index(self, sample_ohlcv):
        """Test result preserves original DataFrame index."""
        sample_ohlcv.index = pd.date_range("2024-01-01", periods=len(sample_ohlcv))
        calc = IndicatorCalculator()
        result = calc.calculate_all(sample_ohlcv)

        pd.testing.assert_index_equal(result.index, sample_ohlcv.index)

    def test_calculate_subset(self, sample_ohlcv):
        """Test calculating only specific indicators."""
        calc = IndicatorCalculator()
        result = calc.calculate_subset(
            sample_ohlcv,
            indicators=["ma", "rsi"]
        )

        # Should have MA and RSI
        assert any("MA_" in col for col in result.columns)
        assert "RSI" in result.columns
        # Should NOT have MACD, KDJ etc
        assert "MACD" not in result.columns
        assert "KDJ_K" not in result.columns

    def test_get_indicator_names(self):
        """Test getting list of available indicator names."""
        calc = IndicatorCalculator()
        names = calc.get_indicator_names()

        assert "ma" in names
        assert "ema" in names
        assert "rsi" in names
        assert "macd" in names
        assert "kdj" in names
        assert "adx" in names
        assert "obv" in names
        assert "atr" in names
