"""Base classes and types for trading signal generation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Any

import pandas as pd


class SignalLevel(IntEnum):
    """Trading signal strength levels.

    5-class classification for signal strength:
    - STRONG_BUY (5): Score 80-100, high confidence buy signal
    - WEAK_BUY (4): Score 60-80, moderate buy signal
    - HOLD (3): Score 40-60, neutral, maintain current position
    - WEAK_SELL (2): Score 20-40, moderate sell signal
    - STRONG_SELL (1): Score 0-20, high confidence sell signal
    """
    STRONG_SELL = 1
    WEAK_SELL = 2
    HOLD = 3
    WEAK_BUY = 4
    STRONG_BUY = 5

    def is_bullish(self) -> bool:
        """Check if signal indicates bullish sentiment."""
        return self.value >= 4

    def is_bearish(self) -> bool:
        """Check if signal indicates bearish sentiment."""
        return self.value <= 2


def score_to_signal_level(score: float) -> SignalLevel:
    """Convert numeric score (0-100) to SignalLevel.

    Score ranges:
    - 80-100: STRONG_BUY
    - 60-80: WEAK_BUY
    - 40-60: HOLD
    - 20-40: WEAK_SELL
    - 0-20: STRONG_SELL

    Args:
        score: Numeric score, clamped to 0-100

    Returns:
        Corresponding SignalLevel
    """
    # Clamp score to valid range
    score = max(0, min(100, score))

    if score >= 80:
        return SignalLevel.STRONG_BUY
    elif score >= 60:
        return SignalLevel.WEAK_BUY
    elif score >= 40:
        return SignalLevel.HOLD
    elif score >= 20:
        return SignalLevel.WEAK_SELL
    else:
        return SignalLevel.STRONG_SELL


@dataclass
class SignalResult:
    """Container for strategy signal output.

    Attributes:
        strategy_name: Name of the strategy that generated this signal
        stock_code: Stock identifier (e.g., "000001.SZ")
        signal_level: Signal strength classification
        score: Raw numeric score (0-100)
        trade_date: Date the signal applies to
        reason: Human-readable explanation of the signal
        metadata: Additional strategy-specific data
    """
    strategy_name: str
    stock_code: str
    signal_level: SignalLevel
    score: float
    trade_date: str
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Subclasses must implement:
        - name: Property returning strategy identifier
        - generate_signals: Method that analyzes data and produces signals

    Usage:
        strategy = ConcreteStrategy()
        result = strategy(df, stock_code, trade_date)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return strategy identifier."""
        pass

    @abstractmethod
    def generate_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str
    ) -> SignalResult:
        """Generate trading signal for a stock.

        Args:
            df: OHLCV DataFrame with indicator columns
            stock_code: Stock identifier
            trade_date: Date for the signal

        Returns:
            SignalResult with signal level and score
        """
        pass

    def __call__(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str
    ) -> SignalResult:
        """Generate signals (callable interface).

        Args:
            df: OHLCV DataFrame with indicator columns
            stock_code: Stock identifier
            trade_date: Date for the signal

        Returns:
            SignalResult with signal level and score
        """
        return self.generate_signals(df, stock_code, trade_date)
