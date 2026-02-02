"""Unified indicator calculator for batch processing."""

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .trend_indicators import MAIndicator, EMAIndicator, MACDIndicator, ADXIndicator
from .momentum_indicators import RSIIndicator, KDJIndicator
from .volume_indicators import OBVIndicator, ATRIndicator


@dataclass
class IndicatorConfig:
    """Configuration for indicator calculation.

    Attributes:
        ma_periods: List of periods for Simple Moving Average
        ema_periods: List of periods for Exponential Moving Average
        rsi_period: Period for RSI calculation
        macd_params: Tuple of (fast, slow, signal) periods for MACD
        kdj_params: Tuple of (fastk, slowk, slowd) periods for KDJ
        adx_period: Period for ADX calculation
        atr_period: Period for ATR calculation
    """
    ma_periods: list[int] = field(default_factory=lambda: [5, 10, 20, 60])
    ema_periods: list[int] = field(default_factory=lambda: [12, 26])
    rsi_period: int = 14
    macd_params: tuple[int, int, int] = (12, 26, 9)
    kdj_params: tuple[int, int, int] = (9, 3, 3)
    adx_period: int = 14
    atr_period: int = 14


class IndicatorCalculator:
    """Unified calculator for all technical indicators.

    Provides a single interface to calculate multiple indicators at once,
    returning a DataFrame with all indicator values as columns.

    Usage:
        calc = IndicatorCalculator()
        indicators_df = calc.calculate_all(ohlcv_df)

        # Or calculate specific indicators only
        subset_df = calc.calculate_subset(ohlcv_df, indicators=["ma", "rsi"])
    """

    AVAILABLE_INDICATORS = ["ma", "ema", "rsi", "macd", "kdj", "adx", "obv", "atr"]

    def __init__(self, config: Optional[IndicatorConfig] = None):
        """Initialize calculator with optional custom config.

        Args:
            config: Custom indicator configuration (default: IndicatorConfig())
        """
        self.config = config or IndicatorConfig()

    def get_indicator_names(self) -> list[str]:
        """Get list of available indicator names.

        Returns:
            List of indicator identifiers that can be used with calculate_subset
        """
        return self.AVAILABLE_INDICATORS.copy()

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all configured indicators.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume

        Returns:
            DataFrame with all indicator values as columns
        """
        return self.calculate_subset(df, indicators=self.AVAILABLE_INDICATORS)

    def calculate_subset(
        self,
        df: pd.DataFrame,
        indicators: list[str]
    ) -> pd.DataFrame:
        """Calculate only specified indicators.

        Args:
            df: OHLCV DataFrame
            indicators: List of indicator names to calculate

        Returns:
            DataFrame with specified indicator values
        """
        result = pd.DataFrame(index=df.index)

        for indicator in indicators:
            if indicator == "ma":
                self._add_ma(df, result)
            elif indicator == "ema":
                self._add_ema(df, result)
            elif indicator == "rsi":
                self._add_rsi(df, result)
            elif indicator == "macd":
                self._add_macd(df, result)
            elif indicator == "kdj":
                self._add_kdj(df, result)
            elif indicator == "adx":
                self._add_adx(df, result)
            elif indicator == "obv":
                self._add_obv(df, result)
            elif indicator == "atr":
                self._add_atr(df, result)

        return result

    def _add_ma(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add MA indicators to result DataFrame."""
        for period in self.config.ma_periods:
            ma = MAIndicator(period=period)
            ind_result = ma(df)
            result[ind_result.name] = ind_result.values

    def _add_ema(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add EMA indicators to result DataFrame."""
        for period in self.config.ema_periods:
            ema = EMAIndicator(period=period)
            ind_result = ema(df)
            result[ind_result.name] = ind_result.values

    def _add_rsi(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add RSI indicator to result DataFrame."""
        rsi = RSIIndicator(period=self.config.rsi_period)
        ind_result = rsi(df)
        result["RSI"] = ind_result.values

    def _add_macd(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add MACD indicators to result DataFrame."""
        fast, slow, signal = self.config.macd_params
        macd = MACDIndicator(
            fast_period=fast,
            slow_period=slow,
            signal_period=signal
        )
        ind_result = macd(df)
        result["MACD"] = ind_result.params["macd"]
        result["MACD_signal"] = ind_result.params["signal"]
        result["MACD_hist"] = ind_result.params["histogram"]

    def _add_kdj(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add KDJ indicators to result DataFrame."""
        fastk, slowk, slowd = self.config.kdj_params
        kdj = KDJIndicator(
            fastk_period=fastk,
            slowk_period=slowk,
            slowd_period=slowd
        )
        ind_result = kdj(df)
        result["KDJ_K"] = ind_result.params["k"]
        result["KDJ_D"] = ind_result.params["d"]
        result["KDJ_J"] = ind_result.params["j"]

    def _add_adx(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add ADX indicators to result DataFrame."""
        adx = ADXIndicator(period=self.config.adx_period)
        ind_result = adx(df)
        result["ADX"] = ind_result.values
        result["ADX_plus_di"] = ind_result.params["plus_di"]
        result["ADX_minus_di"] = ind_result.params["minus_di"]

    def _add_obv(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add OBV indicator to result DataFrame."""
        obv = OBVIndicator()
        ind_result = obv(df)
        result["OBV"] = ind_result.values

    def _add_atr(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        """Add ATR indicator to result DataFrame."""
        atr = ATRIndicator(period=self.config.atr_period)
        ind_result = atr(df)
        result["ATR"] = ind_result.values
