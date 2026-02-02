"""Tests for swing trading strategy."""

import pytest
import pandas as pd
import numpy as np
from src.signals.base_signal import SignalLevel, SignalResult
from src.signals.swing_strategy import SwingStrategy


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data with indicators."""
    np.random.seed(42)
    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close - np.random.rand(n),
        "high": close + np.random.rand(n) * 2,
        "low": close - np.random.rand(n) * 2,
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
        # Pre-calculated indicators for testing
        "RSI": np.random.uniform(30, 70, n),
        "KDJ_K": np.random.uniform(20, 80, n),
        "KDJ_D": np.random.uniform(20, 80, n),
        "KDJ_J": np.random.uniform(0, 100, n),
        "MACD_hist": np.random.uniform(-1, 1, n)
    })


class TestSwingStrategy:
    """Tests for SwingStrategy."""

    def test_strategy_name(self):
        """Test strategy name."""
        strategy = SwingStrategy()
        assert strategy.name == "SWING"

    def test_generate_signals_returns_result(self, sample_ohlcv):
        """Test generate_signals returns SignalResult."""
        strategy = SwingStrategy()
        result = strategy.generate_signals(
            sample_ohlcv,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )
        assert isinstance(result, SignalResult)
        assert result.strategy_name == "SWING"
        assert result.stock_code == "000001.SZ"

    def test_score_in_valid_range(self, sample_ohlcv):
        """Test score is between 0 and 100."""
        strategy = SwingStrategy()
        result = strategy(sample_ohlcv, "000001.SZ", "2024-01-15")
        assert 0 <= result.score <= 100

    def test_oversold_rsi_bullish(self):
        """Test oversold RSI contributes to bullish signal."""
        df = pd.DataFrame({
            "RSI": [25.0],  # Oversold
            "KDJ_K": [50.0],
            "KDJ_D": [50.0],
            "KDJ_J": [50.0],
            "MACD_hist": [0.0]
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        # Oversold RSI should push score above neutral
        assert result.score > 50

    def test_overbought_rsi_bearish(self):
        """Test overbought RSI contributes to bearish signal."""
        df = pd.DataFrame({
            "RSI": [75.0],  # Overbought
            "KDJ_K": [50.0],
            "KDJ_D": [50.0],
            "KDJ_J": [50.0],
            "MACD_hist": [0.0]
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        # Overbought RSI should push score below neutral
        assert result.score < 50

    def test_kdj_golden_cross_bullish(self):
        """Test KDJ K crossing above D is bullish."""
        # K > D indicates bullish crossover
        df = pd.DataFrame({
            "RSI": [50.0],
            "KDJ_K": [60.0],  # K above D
            "KDJ_D": [40.0],
            "KDJ_J": [100.0],  # J = 3K - 2D = 180 - 80 = 100
            "MACD_hist": [0.0]
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score > 50

    def test_kdj_death_cross_bearish(self):
        """Test KDJ K crossing below D is bearish."""
        # K < D indicates bearish crossover
        df = pd.DataFrame({
            "RSI": [50.0],
            "KDJ_K": [40.0],  # K below D
            "KDJ_D": [60.0],
            "KDJ_J": [0.0],  # J = 3K - 2D = 120 - 120 = 0
            "MACD_hist": [0.0]
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score < 50

    def test_macd_histogram_positive_bullish(self):
        """Test positive MACD histogram contributes to bullish signal."""
        df = pd.DataFrame({
            "RSI": [50.0],
            "KDJ_K": [50.0],
            "KDJ_D": [50.0],
            "KDJ_J": [50.0],
            "MACD_hist": [0.5]  # Positive histogram
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score > 50

    def test_macd_histogram_negative_bearish(self):
        """Test negative MACD histogram contributes to bearish signal."""
        df = pd.DataFrame({
            "RSI": [50.0],
            "KDJ_K": [50.0],
            "KDJ_D": [50.0],
            "KDJ_J": [50.0],
            "MACD_hist": [-0.5]  # Negative histogram
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.score < 50

    def test_combined_bullish_signals(self):
        """Test combined bullish signals produce strong buy."""
        df = pd.DataFrame({
            "RSI": [25.0],  # Oversold
            "KDJ_K": [70.0],  # K > D (bullish)
            "KDJ_D": [30.0],
            "KDJ_J": [150.0],
            "MACD_hist": [0.8]  # Strong positive
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.signal_level in [SignalLevel.STRONG_BUY, SignalLevel.WEAK_BUY]

    def test_combined_bearish_signals(self):
        """Test combined bearish signals produce strong sell."""
        df = pd.DataFrame({
            "RSI": [75.0],  # Overbought
            "KDJ_K": [30.0],  # K < D (bearish)
            "KDJ_D": [70.0],
            "KDJ_J": [-50.0],
            "MACD_hist": [-0.8]  # Strong negative
        })
        strategy = SwingStrategy()
        result = strategy(df, "000001.SZ", "2024-01-15")
        assert result.signal_level in [SignalLevel.STRONG_SELL, SignalLevel.WEAK_SELL]

    def test_result_includes_reason(self, sample_ohlcv):
        """Test result includes reason explaining the signal."""
        strategy = SwingStrategy()
        result = strategy(sample_ohlcv, "000001.SZ", "2024-01-15")
        assert result.reason is not None
        assert len(result.reason) > 0

    def test_custom_weights(self):
        """Test strategy accepts custom indicator weights."""
        strategy = SwingStrategy(
            rsi_weight=0.5,
            kdj_weight=0.3,
            macd_weight=0.2
        )
        assert strategy.rsi_weight == 0.5
        assert strategy.kdj_weight == 0.3
        assert strategy.macd_weight == 0.2
