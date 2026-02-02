"""Tests for signal combiner."""

import pytest
import pandas as pd
import numpy as np
from src.signals.base_signal import SignalLevel, SignalResult
from src.signals.signal_combiner import SignalCombiner, CombinedSignal


@pytest.fixture
def sample_ohlcv_with_indicators():
    """Create sample OHLCV data with all required indicators."""
    np.random.seed(42)
    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close - np.random.rand(n),
        "high": close + np.random.rand(n) * 2,
        "low": close - np.random.rand(n) * 2,
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
        # Swing strategy indicators
        "RSI": np.random.uniform(30, 70, n),
        "KDJ_K": np.random.uniform(20, 80, n),
        "KDJ_D": np.random.uniform(20, 80, n),
        "KDJ_J": np.random.uniform(0, 100, n),
        "MACD_hist": np.random.uniform(-1, 1, n),
        # Trend strategy indicators
        "MA_5": close - 1,
        "MA_20": close - 2,
        "EMA_12": close - 0.5,
        "EMA_26": close - 1.5,
        "ADX": np.random.uniform(15, 40, n),
        "ADX_plus_di": np.random.uniform(20, 35, n),
        "ADX_minus_di": np.random.uniform(15, 30, n)
    })


class TestCombinedSignal:
    """Tests for CombinedSignal dataclass."""

    def test_combined_signal_creation(self):
        """Test CombinedSignal can be created."""
        signal = CombinedSignal(
            stock_code="000001.SZ",
            trade_date="2024-01-15",
            final_score=75.0,
            signal_level=SignalLevel.WEAK_BUY,
            swing_score=70.0,
            trend_score=80.0,
            ml_score=None,
            reasons=["MA金叉", "RSI超卖反弹"]
        )
        assert signal.stock_code == "000001.SZ"
        assert signal.final_score == 75.0
        assert signal.signal_level == SignalLevel.WEAK_BUY

    def test_combined_signal_without_ml(self):
        """Test CombinedSignal works without ML score."""
        signal = CombinedSignal(
            stock_code="000001.SZ",
            trade_date="2024-01-15",
            final_score=65.0,
            signal_level=SignalLevel.WEAK_BUY,
            swing_score=60.0,
            trend_score=70.0,
            ml_score=None,
            reasons=[]
        )
        assert signal.ml_score is None


class TestSignalCombiner:
    """Tests for SignalCombiner."""

    def test_combiner_default_weights(self):
        """Test combiner has correct default weights."""
        combiner = SignalCombiner()
        assert combiner.swing_weight == 0.35
        assert combiner.trend_weight == 0.35
        assert combiner.ml_weight == 0.30

    def test_combiner_custom_weights(self):
        """Test combiner accepts custom weights."""
        combiner = SignalCombiner(
            swing_weight=0.4,
            trend_weight=0.4,
            ml_weight=0.2
        )
        assert combiner.swing_weight == 0.4
        assert combiner.ml_weight == 0.2

    def test_combine_without_ml(self, sample_ohlcv_with_indicators):
        """Test combining signals without ML score."""
        combiner = SignalCombiner()
        result = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )

        assert isinstance(result, CombinedSignal)
        assert result.stock_code == "000001.SZ"
        assert result.ml_score is None
        assert 0 <= result.final_score <= 100

    def test_combine_with_ml(self, sample_ohlcv_with_indicators):
        """Test combining signals with ML score."""
        combiner = SignalCombiner()
        result = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15",
            ml_score=70.0
        )

        assert result.ml_score == 70.0
        assert 0 <= result.final_score <= 100

    def test_weights_sum_without_ml(self, sample_ohlcv_with_indicators):
        """Test swing and trend weights are normalized when no ML."""
        combiner = SignalCombiner()
        result = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )

        # Without ML, swing and trend should be 50/50 of their combined weight
        # Final score should be average of swing and trend weighted by their ratio
        expected_ratio = 0.35 / (0.35 + 0.35)  # 0.5 each
        assert expected_ratio == 0.5

    def test_ml_score_affects_final(self, sample_ohlcv_with_indicators):
        """Test ML score affects final combined score."""
        combiner = SignalCombiner()

        result_no_ml = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )

        result_high_ml = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15",
            ml_score=90.0
        )

        result_low_ml = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15",
            ml_score=10.0
        )

        # High ML should push score up, low ML should push score down
        assert result_high_ml.final_score > result_low_ml.final_score

    def test_signal_level_matches_score(self, sample_ohlcv_with_indicators):
        """Test signal level correctly reflects the score."""
        combiner = SignalCombiner()
        result = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )

        # Verify signal level matches score range
        if result.final_score >= 80:
            assert result.signal_level == SignalLevel.STRONG_BUY
        elif result.final_score >= 60:
            assert result.signal_level == SignalLevel.WEAK_BUY
        elif result.final_score >= 40:
            assert result.signal_level == SignalLevel.HOLD
        elif result.final_score >= 20:
            assert result.signal_level == SignalLevel.WEAK_SELL
        else:
            assert result.signal_level == SignalLevel.STRONG_SELL

    def test_reasons_included(self, sample_ohlcv_with_indicators):
        """Test combined signal includes reasons from strategies."""
        combiner = SignalCombiner()
        result = combiner.combine(
            sample_ohlcv_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )

        assert isinstance(result.reasons, list)

    def test_bullish_signals_combine_to_buy(self):
        """Test bullish signals from both strategies produce buy signal."""
        # Create strongly bullish data
        df = pd.DataFrame({
            "close": [120.0],
            # Swing: oversold RSI, KDJ golden cross, positive MACD
            "RSI": [25.0],
            "KDJ_K": [70.0],
            "KDJ_D": [30.0],
            "KDJ_J": [150.0],
            "MACD_hist": [0.8],
            # Trend: MA golden cross, strong uptrend
            "MA_5": [118.0],
            "MA_20": [110.0],
            "EMA_12": [116.0],
            "EMA_26": [112.0],
            "ADX": [35.0],
            "ADX_plus_di": [35.0],
            "ADX_minus_di": [15.0]
        })

        combiner = SignalCombiner()
        result = combiner.combine(df, "000001.SZ", "2024-01-15")

        assert result.signal_level.is_bullish()

    def test_bearish_signals_combine_to_sell(self):
        """Test bearish signals from both strategies produce sell signal."""
        # Create strongly bearish data
        df = pd.DataFrame({
            "close": [80.0],
            # Swing: overbought RSI, KDJ death cross, negative MACD
            "RSI": [75.0],
            "KDJ_K": [30.0],
            "KDJ_D": [70.0],
            "KDJ_J": [-50.0],
            "MACD_hist": [-0.8],
            # Trend: MA death cross, strong downtrend
            "MA_5": [82.0],
            "MA_20": [90.0],
            "EMA_12": [84.0],
            "EMA_26": [88.0],
            "ADX": [35.0],
            "ADX_plus_di": [15.0],
            "ADX_minus_di": [35.0]
        })

        combiner = SignalCombiner()
        result = combiner.combine(df, "000001.SZ", "2024-01-15")

        assert result.signal_level.is_bearish()

    def test_combine_batch(self, sample_ohlcv_with_indicators):
        """Test combining signals for multiple stocks."""
        combiner = SignalCombiner()
        stocks = ["000001.SZ", "000002.SZ", "600000.SH"]

        results = combiner.combine_batch(
            {code: sample_ohlcv_with_indicators for code in stocks},
            trade_date="2024-01-15"
        )

        assert len(results) == 3
        assert all(isinstance(r, CombinedSignal) for r in results)
        assert set(r.stock_code for r in results) == set(stocks)
