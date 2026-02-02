"""Technical indicator calculation module.

Provides technical analysis indicators for stock trading strategies:
- Trend indicators: MA, EMA, MACD, ADX
- Momentum indicators: RSI, KDJ
- Volume/volatility indicators: OBV, ATR
- Unified calculator for batch processing
"""

from .base_indicator import BaseIndicator, IndicatorResult
from .trend_indicators import MAIndicator, EMAIndicator, MACDIndicator, ADXIndicator
from .momentum_indicators import RSIIndicator, KDJIndicator
from .volume_indicators import OBVIndicator, ATRIndicator
from .indicator_calculator import IndicatorCalculator, IndicatorConfig

__all__ = [
    # Base
    "BaseIndicator",
    "IndicatorResult",
    # Trend
    "MAIndicator",
    "EMAIndicator",
    "MACDIndicator",
    "ADXIndicator",
    # Momentum
    "RSIIndicator",
    "KDJIndicator",
    # Volume/Volatility
    "OBVIndicator",
    "ATRIndicator",
    # Calculator
    "IndicatorCalculator",
    "IndicatorConfig",
]
