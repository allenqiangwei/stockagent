"""Unified indicator calculator for batch processing."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import pandas as pd

from .trend_indicators import MAIndicator, EMAIndicator, MACDIndicator, ADXIndicator
from .momentum_indicators import RSIIndicator, KDJIndicator
from .volume_indicators import OBVIndicator, ATRIndicator


@dataclass
class IndicatorConfig:
    """Configuration for indicator calculation.

    All period/param fields are lists to support multiple parameter sets.
    E.g., rsi_periods=[14, 7] will produce both RSI_14 and RSI_7 columns.
    """
    ma_periods: list[int] = field(default_factory=lambda: [5, 10, 20, 60])
    ema_periods: list[int] = field(default_factory=lambda: [12, 26])
    rsi_periods: list[int] = field(default_factory=lambda: [14])
    macd_params_list: list[tuple[int, int, int]] = field(
        default_factory=lambda: [(12, 26, 9)]
    )
    kdj_params_list: list[tuple[int, int, int]] = field(
        default_factory=lambda: [(9, 3, 3)]
    )
    adx_periods: list[int] = field(default_factory=lambda: [14])
    atr_periods: list[int] = field(default_factory=lambda: [14])
    calc_obv: bool = True
    # Extended indicators: group_name → list of param dicts
    extended: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    @staticmethod
    def from_collected_params(
        collected: Dict[str, List[Dict[str, Any]]]
    ) -> "IndicatorConfig":
        """Build config from rule_engine.collect_indicator_params() output.

        Args:
            collected: {"rsi": [{"period": 14}, ...], "macd": [...], ...}
        """
        config = IndicatorConfig(
            ma_periods=[],
            ema_periods=[],
            rsi_periods=[],
            macd_params_list=[],
            kdj_params_list=[],
            adx_periods=[],
            atr_periods=[],
            calc_obv=False,
        )

        for key, param_sets in collected.items():
            if key == "rsi":
                config.rsi_periods = sorted(set(
                    p.get("period", 14) for p in param_sets
                ))
            elif key == "macd":
                seen = set()
                for p in param_sets:
                    t = (p.get("fast", 12), p.get("slow", 26), p.get("signal", 9))
                    if t not in seen:
                        seen.add(t)
                        config.macd_params_list.append(t)
            elif key == "kdj":
                seen = set()
                for p in param_sets:
                    t = (p.get("fastk", 9), p.get("slowk", 3), p.get("slowd", 3))
                    if t not in seen:
                        seen.add(t)
                        config.kdj_params_list.append(t)
            elif key == "ma":
                config.ma_periods = sorted(set(
                    p.get("period", 20) for p in param_sets
                ))
            elif key == "ema":
                config.ema_periods = sorted(set(
                    p.get("period", 12) for p in param_sets
                ))
            elif key == "adx":
                config.adx_periods = sorted(set(
                    p.get("period", 14) for p in param_sets
                ))
            elif key == "atr":
                config.atr_periods = sorted(set(
                    p.get("period", 14) for p in param_sets
                ))
            elif key == "obv":
                config.calc_obv = True
            else:
                # Extended indicator (boll, cci, mfi, vwap, etc.)
                config.extended[key] = param_sets

        return config


class IndicatorCalculator:
    """Unified calculator for all technical indicators.

    Calculates indicators with parameterized column names:
      RSI_14, RSI_7, MACD_12_26_9, MACD_hist_12_26_9, MA_5, MA_20, etc.
    """

    AVAILABLE_INDICATORS = ["ma", "ema", "rsi", "macd", "kdj", "adx", "obv", "atr"]

    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.config = config or IndicatorConfig()

    def get_indicator_names(self) -> list[str]:
        return self.AVAILABLE_INDICATORS.copy()

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        # Compute built-in indicators
        result = self.calculate_subset(df, indicators=self.AVAILABLE_INDICATORS)
        # Compute any extended indicators collected from strategy rules
        for group_key, param_sets in self.config.extended.items():
            self._add_extended_with_params(df, result, group_key, param_sets)
        return result

    def calculate_subset(
        self,
        df: pd.DataFrame,
        indicators: list[str]
    ) -> pd.DataFrame:
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
            else:
                # Try extended indicator registry
                self._add_extended(df, result, indicator)

        return result

    def _add_extended(
        self, df: pd.DataFrame, result: pd.DataFrame, indicator: str,
    ) -> None:
        """Compute an extended indicator via the dynamic registry (default params)."""
        self._add_extended_with_params(df, result, indicator, [{}])

    def _add_extended_with_params(
        self, df: pd.DataFrame, result: pd.DataFrame,
        indicator: str, param_sets: List[Dict[str, Any]],
    ) -> None:
        """Compute an extended indicator for each param set via the dynamic registry."""
        try:
            from api.services.indicator_registry import (
                EXTENDED_INDICATORS, compute_extended_indicator,
            )
        except ImportError:
            return

        group = indicator.upper()
        if group not in EXTENDED_INDICATORS:
            return

        for params in param_sets:
            ext_df = compute_extended_indicator(df, group, params or None)
            for col in ext_df.columns:
                result[col] = ext_df[col]

    def _add_ma(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for period in self.config.ma_periods:
            ma = MAIndicator(period=period)
            ind_result = ma(df)
            result[ind_result.name] = ind_result.values  # MA_5, MA_10, etc.

    def _add_ema(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for period in self.config.ema_periods:
            ema = EMAIndicator(period=period)
            ind_result = ema(df)
            result[ind_result.name] = ind_result.values  # EMA_12, EMA_26, etc.

    def _add_rsi(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for period in self.config.rsi_periods:
            rsi = RSIIndicator(period=period)
            ind_result = rsi(df)
            result[f"RSI_{period}"] = ind_result.values

    def _add_macd(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for fast, slow, signal in self.config.macd_params_list:
            macd = MACDIndicator(
                fast_period=fast, slow_period=slow, signal_period=signal
            )
            ind_result = macd(df)
            suffix = f"_{fast}_{slow}_{signal}"
            result[f"MACD{suffix}"] = ind_result.params["macd"]
            result[f"MACD_signal{suffix}"] = ind_result.params["signal"]
            result[f"MACD_hist{suffix}"] = ind_result.params["histogram"]

    def _add_kdj(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for fastk, slowk, slowd in self.config.kdj_params_list:
            kdj = KDJIndicator(
                fastk_period=fastk, slowk_period=slowk, slowd_period=slowd
            )
            ind_result = kdj(df)
            suffix = f"_{fastk}_{slowk}_{slowd}"
            result[f"KDJ_K{suffix}"] = ind_result.params["k"]
            result[f"KDJ_D{suffix}"] = ind_result.params["d"]
            result[f"KDJ_J{suffix}"] = ind_result.params["j"]

    def _add_adx(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for period in self.config.adx_periods:
            adx = ADXIndicator(period=period)
            ind_result = adx(df)
            result[f"ADX_{period}"] = ind_result.values
            result[f"ADX_plus_di_{period}"] = ind_result.params["plus_di"]
            result[f"ADX_minus_di_{period}"] = ind_result.params["minus_di"]

    def _add_obv(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        if self.config.calc_obv:
            obv = OBVIndicator()
            ind_result = obv(df)
            result["OBV"] = ind_result.values

    def _add_atr(self, df: pd.DataFrame, result: pd.DataFrame) -> None:
        for period in self.config.atr_periods:
            atr = ATRIndicator(period=period)
            ind_result = atr(df)
            result[f"ATR_{period}"] = ind_result.values
