"""Volume and volatility indicators using TA-Lib."""

import pandas as pd
import numpy as np
import talib

from .base_indicator import BaseIndicator, IndicatorResult


class OBVIndicator(BaseIndicator):
    """On-Balance Volume indicator.

    OBV measures buying and selling pressure as a cumulative indicator:
    - Price up: Add volume to OBV
    - Price down: Subtract volume from OBV
    - Price unchanged: OBV unchanged

    Used to confirm price trends and detect divergences.
    Rising OBV with flat price suggests accumulation.
    Falling OBV with flat price suggests distribution.
    """

    @property
    def name(self) -> str:
        return "OBV"

    @property
    def required_columns(self) -> list[str]:
        return ["close", "volume"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate On-Balance Volume.

        Args:
            df: DataFrame with 'close' and 'volume' columns

        Returns:
            IndicatorResult with cumulative OBV values
        """
        values = talib.OBV(df["close"].values, df["volume"].values)
        return IndicatorResult(
            name=self.name,
            values=pd.Series(values, index=df.index),
            params={}
        )


class ATRIndicator(BaseIndicator):
    """Average True Range indicator.

    ATR measures market volatility by calculating the average of true ranges:
    - True Range = max(high-low, |high-prev_close|, |low-prev_close|)

    Used for:
    - Position sizing (higher ATR = smaller position)
    - Stop-loss placement (e.g., 2x ATR trailing stop)
    - Volatility breakout strategies

    ATR doesn't indicate direction, only volatility magnitude.
    """

    def __init__(self, period: int = 14):
        """Initialize ATR indicator.

        Args:
            period: Number of periods for averaging (default: 14)
        """
        self.period = period

    @property
    def name(self) -> str:
        return f"ATR_{self.period}"

    @property
    def required_columns(self) -> list[str]:
        return ["high", "low", "close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate Average True Range.

        Args:
            df: DataFrame with 'high', 'low', 'close' columns

        Returns:
            IndicatorResult with ATR values and true_range in params
        """
        period = kwargs.get("period", self.period)

        # Calculate True Range
        true_range = talib.TRANGE(
            df["high"].values,
            df["low"].values,
            df["close"].values
        )

        # Calculate ATR (average of true range)
        atr = talib.ATR(
            df["high"].values,
            df["low"].values,
            df["close"].values,
            timeperiod=period
        )

        return IndicatorResult(
            name=self.name,
            values=pd.Series(atr, index=df.index),
            params={
                "period": period,
                "true_range": pd.Series(true_range, index=df.index)
            }
        )
