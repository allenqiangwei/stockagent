"""Indicator calculation service — wraps the existing indicator calculator.

Computes technical indicators (MA, RSI, MACD, KDJ, ADX, etc.) on price DataFrames
and returns the results as column-appended DataFrames or structured dicts.
"""

import logging
from typing import Optional

import pandas as pd

from src.indicators.indicator_calculator import IndicatorCalculator, IndicatorConfig

logger = logging.getLogger(__name__)


class IndicatorEngine:
    """Compute technical indicators on OHLCV DataFrames."""

    SUPPORTED = ["ma", "ema", "rsi", "macd", "kdj", "adx", "obv", "atr"]

    def compute(
        self,
        df: pd.DataFrame,
        indicators: Optional[list[str]] = None,
        config: Optional[IndicatorConfig] = None,
    ) -> pd.DataFrame:
        """Compute indicators and merge with the original df.

        Args:
            df: Must have columns: date, open, high, low, close, volume
            indicators: List of indicator names to compute (default: all)
            config: Custom IndicatorConfig (default: standard params)

        Returns:
            DataFrame with original + indicator columns
        """
        if df is None or df.empty:
            return df

        calc = IndicatorCalculator(config or IndicatorConfig())

        target = indicators if indicators else self.SUPPORTED
        target = [i.lower() for i in target if i.lower() in self.SUPPORTED]

        ind_df = calc.calculate_subset(df, target)
        result = pd.concat(
            [df.reset_index(drop=True), ind_df.reset_index(drop=True)],
            axis=1,
        )
        return result

    def compute_for_api(
        self,
        df: pd.DataFrame,
        indicators: list[str],
        config: Optional[IndicatorConfig] = None,
    ) -> list[dict]:
        """Compute indicators and return as list of {date, values: {name: val}}.

        Suitable for JSON serialization in API responses.
        """
        full_df = self.compute(df, indicators, config)
        if full_df is None or full_df.empty:
            return []

        # Identify indicator columns (everything not in the original price cols)
        price_cols = {"date", "open", "high", "low", "close", "volume", "amount"}
        ind_cols = [c for c in full_df.columns if c not in price_cols]

        result = []
        for _, row in full_df.iterrows():
            d = row.get("date", "")
            values = {}
            for col in ind_cols:
                v = row.get(col)
                values[col] = round(float(v), 4) if pd.notna(v) else None
            result.append({"date": str(d), "values": values})

        return result
