"""Multi-timeframe indicator computation.

Resamples daily OHLCV to weekly (W) or monthly (M), computes indicators
on the lower-frequency data, then forward-fills back to the daily index.

Columns are prefixed: W_RSI_14, W_EMA_20, M_RSI_14, etc.
Strategies can mix daily and weekly/monthly conditions freely.

Design choice: uses **completed periods** (not rolling windows).
- Weekly: last trading day of each week marks the period end.
  Monday–Thursday inherit the previous week's values.
  Friday (or last trading day) updates to the current week.
- Monthly: same logic at month boundaries.

This is ideal for T+1 systems where signals fire after market close.
"""

import logging
from typing import Dict, Optional

import pandas as pd

from src.indicators.indicator_calculator import IndicatorCalculator, IndicatorConfig

logger = logging.getLogger(__name__)


def resample_ohlcv(daily_df: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """Resample daily OHLCV to weekly or monthly.

    Args:
        daily_df: DataFrame with 'date', 'open', 'high', 'low', 'close', 'volume'
        freq: "W" for weekly, "M" for monthly

    Returns:
        Resampled OHLCV DataFrame with 'date' column (period end dates).
    """
    df = daily_df.copy()
    df["_dt"] = pd.to_datetime(df["date"])
    df = df.set_index("_dt").sort_index()

    # W-FRI = week ending Friday (aligns with A-share trading week)
    rule = "W-FRI" if freq == "W" else "ME"

    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    resampled = df.resample(rule).agg(agg).dropna(subset=["close"])
    resampled = resampled.reset_index().rename(columns={"_dt": "date"})
    resampled["date"] = resampled["date"].dt.strftime("%Y-%m-%d")

    return resampled


def compute_mtf_indicators(
    daily_df: pd.DataFrame,
    indicator_config: IndicatorConfig,
    prefix: str,
) -> Optional[pd.DataFrame]:
    """Compute indicators on resampled data, forward-fill to daily index.

    Args:
        daily_df: Original daily OHLCV (must have 'date' column)
        indicator_config: IndicatorConfig for the lower timeframe
        prefix: "W" or "M"

    Returns:
        DataFrame aligned with daily_df rows. Columns prefixed with W_ or M_.
        Returns None if resampled data is too short.
    """
    freq = "W" if prefix == "W" else "M"
    resampled = resample_ohlcv(daily_df, freq)

    if resampled.empty or len(resampled) < 3:
        logger.debug("MTF %s: too few periods (%d), skipping", prefix, len(resampled))
        return None

    # Compute indicators on resampled OHLCV
    calculator = IndicatorCalculator(indicator_config)
    indicators = calculator.calculate_all(resampled)

    resampled_full = pd.concat(
        [resampled.reset_index(drop=True), indicators.reset_index(drop=True)],
        axis=1,
    )

    # Forward-fill to daily index via merge_asof
    daily_dates = pd.to_datetime(daily_df["date"]).reset_index(drop=True).to_frame("date")
    resampled_full["date"] = pd.to_datetime(resampled_full["date"])

    merged = pd.merge_asof(
        daily_dates.sort_values("date"),
        resampled_full.sort_values("date"),
        on="date",
        direction="backward",
    )

    # Build result: prefix all columns (including OHLCV → W_close, W_high, etc.)
    result = pd.DataFrame(index=range(len(daily_df)))
    for col in merged.columns:
        if col == "date":
            continue
        result[f"{prefix}_{col}"] = merged[col].values

    return result


def separate_mtf_params(
    collected: Dict[str, list],
) -> tuple[dict, dict, dict]:
    """Separate collected indicator params by timeframe.

    Args:
        collected: Output of collect_indicator_params(), may contain
                   keys like "w_rsi", "m_ema" alongside "rsi", "ema".

    Returns:
        (daily_params, weekly_params, monthly_params)
        Weekly/monthly params have the prefix stripped (w_rsi → rsi).
    """
    daily = {}
    weekly = {}
    monthly = {}

    for key, param_sets in collected.items():
        if key.startswith("w_"):
            weekly[key[2:]] = param_sets
        elif key.startswith("m_"):
            monthly[key[2:]] = param_sets
        else:
            daily[key] = param_sets

    return daily, weekly, monthly
