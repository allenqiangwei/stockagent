"""Tests for trend following strategy."""

import pytest
import pandas as pd
import numpy as np
from src.signals.base_signal import SignalLevel, SignalResult
from src.signals.trend_strategy import TrendStrategy


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data with indicators."""
    np.random.seed(42)
    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "close": close,
        # Pre-calculated indicators for testing
        "MA_5": close - 1,  # Short MA
        "MA_20": close - 2,  # Long MA
        "EMA_12": close - 0.5,
        "EMA_26": close - 1.5,
        "ADX": np.random.uniform(15, 40, n),
        "ADX_plus_di": np.random.uniform(20, 35, n),
        "ADX_minus_di": np.random.uniform(15, 30, n)
    })


class TestTrendStrategy:
    """Tests for TrendStrategy."""

    def test_strategy_name(self):
        """Test strategy name."""
        strategy = TrendStrategy()
        assert strategy.name == "TREND"

    def test_generate_signals_returns_result(self, sample_ohlcv):
        """Test generate_signals returns SignalResult."""
        strategy = TrendStrategy()
        result = strategy.generate_signals(
            sample_ohlcv,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )
        assert isinstance(result, SignalResult)
        assert result.strategy_name == "TREND"

    def test_score_in_valid_range(self, sample_ohlcv):
        """Test score is between 0 and 100."""
        strategy = TrendStrategy()
        result = strategy(sample_ohlcv, "000001.SZ", "2024-01-15")
        assert 0 <= result.score <= 100

    def test_ma_golden_cross_bullish(self):
        """Test short MA above long MA is bullish."""
        df = pd.DataFrame({
            "close": [110.0],
            "MA_5": [108.0],  # Short MA above long MA
            "MA_20": [100.0],
            "EMA_12": [105.0],
            "EMA_26": [105.0],
            "ADX": [25.0],
            "ADX_plus_di": [25.0],
            "ADX_minus_di": [25.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score > 50

    def test_ma_death_cross_bearish(self):
        """Test short MA below long MA is bearish."""
        df = pd.DataFrame({
            "close": [90.0],
            "MA_5": [92.0],  # Short MA below long MA
            "MA_20": [100.0],
            "EMA_12": [95.0],
            "EMA_26": [95.0],
            "ADX": [25.0],
            "ADX_plus_di": [25.0],
            "ADX_minus_di": [25.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score < 50

    def test_strong_adx_amplifies_signal(self):
        """Test strong ADX (>25) amplifies trend signal."""
        # Bullish setup with strong trend
        df_strong = pd.DataFrame({
            "close": [110.0],
            "MA_5": [108.0],
            "MA_20": [100.0],
            "EMA_12": [106.0],
            "EMA_26": [104.0],
            "ADX": [40.0],  # Strong trend
            "ADX_plus_di": [30.0],
            "ADX_minus_di": [15.0]
        })

        # Same setup with weak trend
        df_weak = pd.DataFrame({
            "close": [110.0],
            "MA_5": [108.0],
            "MA_20": [100.0],
            "EMA_12": [106.0],
            "EMA_26": [104.0],
            "ADX": [15.0],  # Weak trend
            "ADX_plus_di": [25.0],
            "ADX_minus_di": [20.0]
        })

        strategy = TrendStrategy()
        result_strong = strategy(df_strong, "000001.SZ", "2024-01-15")
        result_weak = strategy(df_weak, "000001.SZ", "2024-01-15")

        # Strong trend should have more extreme score
        assert abs(result_strong.score - 50) > abs(result_weak.score - 50)

    def test_plus_di_above_minus_di_bullish(self):
        """Test +DI above -DI contributes to bullish signal."""
        df = pd.DataFrame({
            "close": [100.0],
            "MA_5": [100.0],
            "MA_20": [100.0],
            "EMA_12": [100.0],
            "EMA_26": [100.0],
            "ADX": [30.0],
            "ADX_plus_di": [35.0],  # +DI > -DI
            "ADX_minus_di": [15.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score > 50

    def test_minus_di_above_plus_di_bearish(self):
        """Test -DI above +DI contributes to bearish signal."""
        df = pd.DataFrame({
            "close": [100.0],
            "MA_5": [100.0],
            "MA_20": [100.0],
            "EMA_12": [100.0],
            "EMA_26": [100.0],
            "ADX": [30.0],
            "ADX_plus_di": [15.0],  # +DI < -DI
            "ADX_minus_di": [35.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score < 50

    def test_price_above_emas_bullish(self):
        """Test price above both EMAs is bullish."""
        df = pd.DataFrame({
            "close": [110.0],  # Price above both EMAs
            "MA_5": [105.0],
            "MA_20": [105.0],
            "EMA_12": [105.0],
            "EMA_26": [100.0],
            "ADX": [25.0],
            "ADX_plus_di": [25.0],
            "ADX_minus_di": [25.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score > 50

    def test_price_below_emas_bearish(self):
        """Test price below both EMAs is bearish."""
        df = pd.DataFrame({
            "close": [90.0],  # Price below both EMAs
            "MA_5": [95.0],
            "MA_20": [95.0],
            "EMA_12": [95.0],
            "EMA_26": [100.0],
            "ADX": [25.0],
            "ADX_plus_di": [25.0],
            "ADX_minus_di": [25.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score < 50

    def test_combined_bullish_trend(self):
        """Test combined bullish signals produce strong buy."""
        df = pd.DataFrame({
            "close": [120.0],  # Price well above MAs
            "MA_5": [115.0],  # Short MA above long MA
            "MA_20": [105.0],
            "EMA_12": [112.0],  # EMA12 above EMA26
            "EMA_26": [108.0],
            "ADX": [35.0],  # Strong trend
            "ADX_plus_di": [35.0],  # +DI > -DI
            "ADX_minus_di": [15.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.signal_level in [SignalLevel.STRONG_BUY, SignalLevel.WEAK_BUY]

    def test_combined_bearish_trend(self):
        """Test combined bearish signals produce strong sell."""
        df = pd.DataFrame({
            "close": [80.0],  # Price well below MAs
            "MA_5": [85.0],  # Short MA below long MA
            "MA_20": [95.0],
            "EMA_12": [88.0],  # EMA12 below EMA26
            "EMA_26": [92.0],
            "ADX": [35.0],  # Strong trend
            "ADX_plus_di": [15.0],  # +DI < -DI
            "ADX_minus_di": [35.0]
        })
        strategy = TrendStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.signal_level in [SignalLevel.STRONG_SELL, SignalLevel.WEAK_SELL]

    def test_result_includes_reason(self, sample_ohlcv):
        """Test result includes reason explaining the signal."""
        strategy = TrendStrategy()
        result = strategy(sample_ohlcv, "000001.SZ", "2024-01-15")
        assert result.reason is not None

    def test_custom_parameters(self):
        """Test strategy accepts custom parameters."""
        strategy = TrendStrategy(
            ma_weight=0.4,
            adx_weight=0.3,
            ema_weight=0.3,
            adx_threshold=30.0
        )
        assert strategy.ma_weight == 0.4
        assert strategy.adx_threshold == 30.0
