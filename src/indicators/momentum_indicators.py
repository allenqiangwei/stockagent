"""Momentum-based technical indicators using TA-Lib."""

import pandas as pd
import numpy as np
import talib

from .base_indicator import BaseIndicator, IndicatorResult


class RSIIndicator(BaseIndicator):
    """Relative Strength Index indicator.

    RSI measures the speed and magnitude of price changes:
    - RSI > 70: Overbought (potential reversal down)
    - RSI < 30: Oversold (potential reversal up)
    - RSI 30-70: Neutral zone

    Uses average gains vs average losses over the period.
    """

    def __init__(self, period: int = 14):
        """Initialize RSI indicator.

        Args:
            period: Number of periods for calculation (default: 14)
        """
        self.period = period

    @property
    def name(self) -> str:
        return f"RSI_{self.period}"

    @property
    def required_columns(self) -> list[str]:
        return ["close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate RSI.

        Args:
            df: DataFrame with 'close' column

        Returns:
            IndicatorResult with RSI values (0-100)
        """
        period = kwargs.get("period", self.period)
        values = talib.RSI(df["close"].values, timeperiod=period)
        return IndicatorResult(
            name=self.name,
            values=pd.Series(values, index=df.index),
            params={"period": period}
        )


class KDJIndicator(BaseIndicator):
    """KDJ Stochastic indicator (Chinese market variant).

    KDJ is based on Stochastic Oscillator with additional J line:
    - K: Fast stochastic (%K smoothed)
    - D: Slow stochastic (smoothed K)
    - J: 3K - 2D (more sensitive, can exceed 0-100)

    Signals:
    - K crossing above D: Bullish
    - K crossing below D: Bearish
    - J < 0: Oversold extreme
    - J > 100: Overbought extreme
    """

    def __init__(
        self,
        fastk_period: int = 9,
        slowk_period: int = 3,
        slowd_period: int = 3
    ):
        """Initialize KDJ indicator.

        Args:
            fastk_period: Fast %K period (default: 9)
            slowk_period: Slow %K smoothing period (default: 3)
            slowd_period: %D smoothing period (default: 3)
        """
        self.fastk_period = fastk_period
        self.slowk_period = slowk_period
        self.slowd_period = slowd_period

    @property
    def name(self) -> str:
        return "KDJ"

    @property
    def required_columns(self) -> list[str]:
        return ["high", "low", "close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate K, D, J values.

        Args:
            df: DataFrame with 'high', 'low', 'close' columns

        Returns:
            IndicatorResult with K as values, D and J in params
        """
        fastk = kwargs.get("fastk_period", self.fastk_period)
        slowk = kwargs.get("slowk_period", self.slowk_period)
        slowd = kwargs.get("slowd_period", self.slowd_period)

        # Calculate Stochastic (K and D)
        k, d = talib.STOCH(
            df["high"].values,
            df["low"].values,
            df["close"].values,
            fastk_period=fastk,
            slowk_period=slowk,
            slowk_matype=0,  # SMA
            slowd_period=slowd,
            slowd_matype=0   # SMA
        )

        # Calculate J = 3K - 2D
        k_series = pd.Series(k, index=df.index)
        d_series = pd.Series(d, index=df.index)
        j_series = 3 * k_series - 2 * d_series

        return IndicatorResult(
            name=self.name,
            values=k_series,  # K as primary value
            params={
                "fastk_period": fastk,
                "slowk_period": slowk,
                "slowd_period": slowd,
                "k": k_series,
                "d": d_series,
                "j": j_series
            }
        )
