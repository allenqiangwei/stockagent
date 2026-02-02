"""Tests for signal base class and signal levels."""

import pytest
import pandas as pd
import numpy as np
from src.signals.base_signal import (
    SignalLevel,
    SignalResult,
    BaseStrategy,
    score_to_signal_level
)


class TestSignalLevel:
    """Tests for SignalLevel enum."""

    def test_signal_level_values(self):
        """Test signal level integer values."""
        assert SignalLevel.STRONG_SELL == 1
        assert SignalLevel.WEAK_SELL == 2
        assert SignalLevel.HOLD == 3
        assert SignalLevel.WEAK_BUY == 4
        assert SignalLevel.STRONG_BUY == 5

    def test_signal_level_ordering(self):
        """Test signal levels can be compared."""
        assert SignalLevel.STRONG_BUY > SignalLevel.WEAK_BUY
        assert SignalLevel.WEAK_BUY > SignalLevel.HOLD
        assert SignalLevel.HOLD > SignalLevel.WEAK_SELL
        assert SignalLevel.WEAK_SELL > SignalLevel.STRONG_SELL

    def test_signal_level_is_bullish(self):
        """Test bullish signal detection."""
        assert SignalLevel.STRONG_BUY.is_bullish()
        assert SignalLevel.WEAK_BUY.is_bullish()
        assert not SignalLevel.HOLD.is_bullish()
        assert not SignalLevel.WEAK_SELL.is_bullish()
        assert not SignalLevel.STRONG_SELL.is_bullish()

    def test_signal_level_is_bearish(self):
        """Test bearish signal detection."""
        assert SignalLevel.STRONG_SELL.is_bearish()
        assert SignalLevel.WEAK_SELL.is_bearish()
        assert not SignalLevel.HOLD.is_bearish()
        assert not SignalLevel.WEAK_BUY.is_bearish()
        assert not SignalLevel.STRONG_BUY.is_bearish()


class TestScoreToSignalLevel:
    """Tests for score_to_signal_level function."""

    def test_strong_buy_range(self):
        """Test scores 80-100 map to STRONG_BUY."""
        assert score_to_signal_level(80) == SignalLevel.STRONG_BUY
        assert score_to_signal_level(90) == SignalLevel.STRONG_BUY
        assert score_to_signal_level(100) == SignalLevel.STRONG_BUY

    def test_weak_buy_range(self):
        """Test scores 60-80 map to WEAK_BUY."""
        assert score_to_signal_level(60) == SignalLevel.WEAK_BUY
        assert score_to_signal_level(70) == SignalLevel.WEAK_BUY
        assert score_to_signal_level(79) == SignalLevel.WEAK_BUY

    def test_hold_range(self):
        """Test scores 40-60 map to HOLD."""
        assert score_to_signal_level(40) == SignalLevel.HOLD
        assert score_to_signal_level(50) == SignalLevel.HOLD
        assert score_to_signal_level(59) == SignalLevel.HOLD

    def test_weak_sell_range(self):
        """Test scores 20-40 map to WEAK_SELL."""
        assert score_to_signal_level(20) == SignalLevel.WEAK_SELL
        assert score_to_signal_level(30) == SignalLevel.WEAK_SELL
        assert score_to_signal_level(39) == SignalLevel.WEAK_SELL

    def test_strong_sell_range(self):
        """Test scores 0-20 map to STRONG_SELL."""
        assert score_to_signal_level(0) == SignalLevel.STRONG_SELL
        assert score_to_signal_level(10) == SignalLevel.STRONG_SELL
        assert score_to_signal_level(19) == SignalLevel.STRONG_SELL

    def test_score_clamping(self):
        """Test scores outside 0-100 are clamped."""
        assert score_to_signal_level(-10) == SignalLevel.STRONG_SELL
        assert score_to_signal_level(110) == SignalLevel.STRONG_BUY


class TestSignalResult:
    """Tests for SignalResult dataclass."""

    def test_signal_result_creation(self):
        """Test SignalResult can be created with required fields."""
        result = SignalResult(
            strategy_name="TEST",
            stock_code="000001.SZ",
            signal_level=SignalLevel.WEAK_BUY,
            score=65.0,
            trade_date="2024-01-15"
        )
        assert result.strategy_name == "TEST"
        assert result.stock_code == "000001.SZ"
        assert result.signal_level == SignalLevel.WEAK_BUY
        assert result.score == 65.0

    def test_signal_result_optional_fields(self):
        """Test SignalResult optional fields default correctly."""
        result = SignalResult(
            strategy_name="TEST",
            stock_code="000001.SZ",
            signal_level=SignalLevel.HOLD,
            score=50.0,
            trade_date="2024-01-15"
        )
        assert result.reason is None
        assert result.metadata == {}

    def test_signal_result_with_reason(self):
        """Test SignalResult with reason field."""
        result = SignalResult(
            strategy_name="TEST",
            stock_code="000001.SZ",
            signal_level=SignalLevel.STRONG_BUY,
            score=85.0,
            trade_date="2024-01-15",
            reason="MACD golden cross + RSI oversold rebound"
        )
        assert "MACD" in result.reason


class ConcreteStrategy(BaseStrategy):
    """Concrete implementation for testing abstract base class."""

    @property
    def name(self) -> str:
        return "CONCRETE"

    def generate_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str
    ) -> SignalResult:
        score = 50.0  # Neutral
        return SignalResult(
            strategy_name=self.name,
            stock_code=stock_code,
            signal_level=score_to_signal_level(score),
            score=score,
            trade_date=trade_date
        )


class TestBaseStrategy:
    """Tests for BaseStrategy abstract base class."""

    @pytest.fixture
    def sample_df(self):
        """Create sample OHLCV dataframe for testing."""
        np.random.seed(42)
        n = 50
        close = 100 + np.cumsum(np.random.randn(n) * 2)
        return pd.DataFrame({
            "open": close - np.random.rand(n),
            "high": close + np.random.rand(n) * 2,
            "low": close - np.random.rand(n) * 2,
            "close": close,
            "volume": np.random.randint(1000, 10000, n).astype(float)
        })

    @pytest.fixture
    def strategy(self):
        """Create concrete strategy instance."""
        return ConcreteStrategy()

    def test_abstract_class_cannot_be_instantiated(self):
        """Test that BaseStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_strategy_has_name(self, strategy):
        """Test strategy has name property."""
        assert strategy.name == "CONCRETE"

    def test_generate_signals_returns_result(self, strategy, sample_df):
        """Test generate_signals returns SignalResult."""
        result = strategy.generate_signals(
            sample_df,
            stock_code="000001.SZ",
            trade_date="2024-01-15"
        )
        assert isinstance(result, SignalResult)
        assert result.strategy_name == "CONCRETE"
        assert result.stock_code == "000001.SZ"

    def test_call_generates_signals(self, strategy, sample_df):
        """Test __call__ invokes generate_signals."""
        result = strategy(sample_df, "000001.SZ", "2024-01-15")
        assert isinstance(result, SignalResult)
