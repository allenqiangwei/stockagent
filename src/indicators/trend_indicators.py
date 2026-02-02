"""Trend-following technical indicators using TA-Lib."""

import pandas as pd
import numpy as np
import talib

from .base_indicator import BaseIndicator, IndicatorResult


class MAIndicator(BaseIndicator):
    """Simple Moving Average indicator.

    SMA smooths price data by calculating the average over a fixed window.
    Used for trend identification and support/resistance levels.
    """

    def __init__(self, period: int = 20):
        """Initialize MA indicator.

        Args:
            period: Number of periods for calculation (default: 20)
        """
        self.period = period

    @property
    def name(self) -> str:
        return f"MA_{self.period}"

    @property
    def required_columns(self) -> list[str]:
        return ["close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate Simple Moving Average.

        Args:
            df: DataFrame with 'close' column

        Returns:
            IndicatorResult with MA values
        """
        period = kwargs.get("period", self.period)
        values = talib.SMA(df["close"].values, timeperiod=period)
        return IndicatorResult(
            name=self.name,
            values=pd.Series(values, index=df.index),
            params={"period": period}
        )


class EMAIndicator(BaseIndicator):
    """Exponential Moving Average indicator.

    EMA gives more weight to recent prices, making it more responsive
    to new information than SMA.
    """

    def __init__(self, period: int = 20):
        """Initialize EMA indicator.

        Args:
            period: Number of periods for calculation (default: 20)
        """
        self.period = period

    @property
    def name(self) -> str:
        return f"EMA_{self.period}"

    @property
    def required_columns(self) -> list[str]:
        return ["close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate Exponential Moving Average.

        Args:
            df: DataFrame with 'close' column

        Returns:
            IndicatorResult with EMA values
        """
        period = kwargs.get("period", self.period)
        values = talib.EMA(df["close"].values, timeperiod=period)
        return IndicatorResult(
            name=self.name,
            values=pd.Series(values, index=df.index),
            params={"period": period}
        )


class MACDIndicator(BaseIndicator):
    """Moving Average Convergence Divergence indicator.

    MACD shows the relationship between two EMAs and includes:
    - MACD line: Difference between fast and slow EMAs
    - Signal line: EMA of MACD line
    - Histogram: Difference between MACD and signal

    Used for trend direction, momentum, and divergence signals.
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ):
        """Initialize MACD indicator.

        Args:
            fast_period: Fast EMA period (default: 12)
            slow_period: Slow EMA period (default: 26)
            signal_period: Signal line EMA period (default: 9)
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    @property
    def name(self) -> str:
        return "MACD"

    @property
    def required_columns(self) -> list[str]:
        return ["close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate MACD, signal line, and histogram.

        Args:
            df: DataFrame with 'close' column

        Returns:
            IndicatorResult with MACD line as values and
            signal/histogram in params
        """
        fast = kwargs.get("fast_period", self.fast_period)
        slow = kwargs.get("slow_period", self.slow_period)
        signal = kwargs.get("signal_period", self.signal_period)

        macd, macd_signal, macd_hist = talib.MACD(
            df["close"].values,
            fastperiod=fast,
            slowperiod=slow,
            signalperiod=signal
        )

        return IndicatorResult(
            name=self.name,
            values=pd.Series(macd, index=df.index),
            params={
                "fast_period": fast,
                "slow_period": slow,
                "signal_period": signal,
                "macd": pd.Series(macd, index=df.index),
                "signal": pd.Series(macd_signal, index=df.index),
                "histogram": pd.Series(macd_hist, index=df.index)
            }
        )


class ADXIndicator(BaseIndicator):
    """Average Directional Index indicator.

    ADX measures trend strength (not direction):
    - ADX < 20: Weak trend / ranging market
    - ADX 20-40: Moderate trend
    - ADX > 40: Strong trend

    Also includes +DI (bullish) and -DI (bearish) directional indicators.
    """

    def __init__(self, period: int = 14):
        """Initialize ADX indicator.

        Args:
            period: Number of periods for calculation (default: 14)
        """
        self.period = period

    @property
    def name(self) -> str:
        return f"ADX_{self.period}"

    @property
    def required_columns(self) -> list[str]:
        return ["high", "low", "close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate ADX, +DI, and -DI.

        Args:
            df: DataFrame with 'high', 'low', 'close' columns

        Returns:
            IndicatorResult with ADX values and DI lines in params
        """
        period = kwargs.get("period", self.period)

        adx = talib.ADX(
            df["high"].values,
            df["low"].values,
            df["close"].values,
            timeperiod=period
        )

        plus_di = talib.PLUS_DI(
            df["high"].values,
            df["low"].values,
            df["close"].values,
            timeperiod=period
        )

        minus_di = talib.MINUS_DI(
            df["high"].values,
            df["low"].values,
            df["close"].values,
            timeperiod=period
        )

        return IndicatorResult(
            name=self.name,
            values=pd.Series(adx, index=df.index),
            params={
                "period": period,
                "plus_di": pd.Series(plus_di, index=df.index),
                "minus_di": pd.Series(minus_di, index=df.index)
            }
        )
