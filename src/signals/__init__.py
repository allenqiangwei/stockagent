"""Trading signal generation module.

Provides strategies for generating buy/sell signals:
- SwingStrategy: Mean-reversion using RSI, KDJ, MACD
- TrendStrategy: Trend-following using MA, ADX, EMA
"""

from .base_signal import (
    SignalLevel,
    SignalResult,
    BaseStrategy,
    score_to_signal_level
)
from .swing_strategy import SwingStrategy
from .trend_strategy import TrendStrategy
from .signal_combiner import SignalCombiner, CombinedSignal
from .daily_signal_generator import DailySignalGenerator, DailySignalReport

__all__ = [
    # Base types
    "SignalLevel",
    "SignalResult",
    "BaseStrategy",
    "score_to_signal_level",
    # Strategies
    "SwingStrategy",
    "TrendStrategy",
    # Combiner
    "SignalCombiner",
    "CombinedSignal",
    # Generator
    "DailySignalGenerator",
    "DailySignalReport",
]
