"""Vectorized signal pre-computation for backtest acceleration.

Replaces per-row evaluate_conditions() calls with one-shot boolean array
computation using pandas vectorized ops. Reduces O(n²) to O(n).
"""

import logging
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd

from src.signals.rule_engine import resolve_column_name

logger = logging.getLogger(__name__)


def vectorize_conditions(
    conditions: List[Dict[str, Any]],
    df: pd.DataFrame,
    mode: str = "AND",
) -> np.ndarray:
    """Pre-compute buy/sell signals as boolean array for entire DataFrame.

    Args:
        conditions: List of condition dicts (same format as rule_engine)
        df: Full DataFrame with OHLCV + indicator columns
        mode: "AND" = all conditions must be true; "OR" = any condition

    Returns:
        np.ndarray[bool] of shape (len(df),) — True where signal fires
    """
    if not conditions or df.empty:
        return np.zeros(len(df), dtype=bool)

    n = len(df)
    masks: List[np.ndarray] = []

    for cond in conditions:
        mask = _vectorize_single_condition(cond, df)
        if mask is None:
            if mode == "AND":
                return np.zeros(n, dtype=bool)
            continue
        masks.append(mask)

    if not masks:
        return np.zeros(n, dtype=bool)

    if mode == "AND":
        result = masks[0].copy()
        for m in masks[1:]:
            result &= m
    else:  # OR
        result = masks[0].copy()
        for m in masks[1:]:
            result |= m

    # Row 0 is always False (need at least 1 prior day for lookback safety)
    result[0] = False
    return result


def _vectorize_single_condition(
    cond: Dict[str, Any],
    df: pd.DataFrame,
) -> Optional[np.ndarray]:
    """Vectorize a single condition into a boolean mask.

    Returns None if the condition references a missing column.
    """
    compare_type = cond.get("compare_type", "value")
    field = cond.get("field", "")
    operator = cond.get("operator", ">")
    params = cond.get("params")

    col_name = resolve_column_name(field, params)

    if compare_type == "consecutive":
        return _vec_consecutive(cond, col_name, df)
    elif compare_type == "pct_diff":
        return _vec_pct_diff(cond, col_name, df, operator)
    elif compare_type == "pct_change":
        return _vec_pct_change(cond, col_name, df, operator)

    # Get left-side values
    if col_name not in df.columns:
        logger.debug("Vectorize: column '%s' not found (field='%s')", col_name, field)
        return None
    left = df[col_name].values.astype(np.float64)

    # Get right-side values based on compare_type
    if compare_type == "field":
        compare_field = cond.get("compare_field", "")
        compare_params = cond.get("compare_params")
        compare_col = resolve_column_name(compare_field, compare_params)
        if compare_col not in df.columns:
            logger.debug("Vectorize: compare column '%s' not found", compare_col)
            return None
        right = df[compare_col].values.astype(np.float64)
    elif compare_type == "lookback_min":
        right = _vec_lookback_extreme(cond, col_name, df, "min")
        if right is None:
            return None
    elif compare_type == "lookback_max":
        right = _vec_lookback_extreme(cond, col_name, df, "max")
        if right is None:
            return None
    elif compare_type == "lookback_value":
        right = _vec_lookback_value(cond, df)
        if right is None:
            return None
    else:
        # compare_type == "value" (default)
        right = np.full(len(df), float(cond.get("compare_value", 0)))

    # Handle NaN: where either side is NaN, the condition is False
    left_nan = np.isnan(left)
    right_nan = np.isnan(right)
    either_nan = left_nan | right_nan

    mask = _vec_compare(left, operator, right)
    mask[either_nan] = False
    return mask


def _vec_compare(left: np.ndarray, operator: str, right: np.ndarray) -> np.ndarray:
    """Vectorized comparison."""
    if operator == ">":
        return left > right
    elif operator == "<":
        return left < right
    elif operator == ">=":
        return left >= right
    elif operator == "<=":
        return left <= right
    return np.zeros(len(left), dtype=bool)


def _vec_lookback_extreme(
    cond: Dict[str, Any],
    col_name: str,
    df: pd.DataFrame,
    mode: str,
) -> Optional[np.ndarray]:
    """Vectorized lookback_min / lookback_max.

    Returns rolling min/max of the last N values (excluding current row).
    """
    n = cond.get("lookback_n", 5)
    lookback_field = cond.get("lookback_field", cond.get("field", ""))
    lookback_params = cond.get("lookback_params", cond.get("params"))
    lookback_col = resolve_column_name(lookback_field, lookback_params)

    if lookback_col not in df.columns:
        return None

    series = df[lookback_col].astype(np.float64)
    # shift(1) excludes current row, then rolling(n) covers the previous N rows
    shifted = series.shift(1)
    if mode == "min":
        result = shifted.rolling(window=n, min_periods=n).min()
    else:
        result = shifted.rolling(window=n, min_periods=n).max()
    return result.values


def _vec_lookback_value(
    cond: Dict[str, Any],
    df: pd.DataFrame,
) -> Optional[np.ndarray]:
    """Vectorized lookback_value: get value from N days ago."""
    n = cond.get("lookback_n", 1)
    lookback_field = cond.get("lookback_field", cond.get("field", ""))
    lookback_params = cond.get("lookback_params", cond.get("params"))
    lookback_col = resolve_column_name(lookback_field, lookback_params)

    if lookback_col not in df.columns:
        return None

    return df[lookback_col].shift(n).values.astype(np.float64)


def _vec_consecutive(
    cond: Dict[str, Any],
    col_name: str,
    df: pd.DataFrame,
) -> Optional[np.ndarray]:
    """Vectorized consecutive rising/falling check.

    For "rising": checks that diff > 0 for N consecutive days.
    For "falling": checks that diff < 0 for N consecutive days.
    """
    n = cond.get("lookback_n", 3)
    consecutive_type = cond.get("consecutive_type", "rising")

    if col_name not in df.columns:
        return None

    series = df[col_name].astype(np.float64)
    diff = series.diff()

    if consecutive_type == "rising":
        step_ok = (diff > 0).astype(np.float64)
    else:  # falling
        step_ok = (diff < 0).astype(np.float64)

    # rolling sum of N consecutive steps all being True
    consecutive_sum = step_ok.rolling(window=n, min_periods=n).sum()
    mask = (consecutive_sum >= n).values

    # Handle NaN in original series: if any value in the window is NaN, result is False
    nan_mask = series.isna().rolling(window=n + 1, min_periods=1).sum() > 0
    mask[nan_mask.values] = False

    return mask


def _vec_pct_diff(
    cond: Dict[str, Any],
    col_name: str,
    df: pd.DataFrame,
    operator: str,
) -> Optional[np.ndarray]:
    """Vectorized pct_diff: (field - compare_field) / compare_field * 100."""
    if col_name not in df.columns:
        return None

    compare_field = cond.get("compare_field", "")
    compare_params = cond.get("compare_params")
    compare_col = resolve_column_name(compare_field, compare_params)
    if compare_col not in df.columns:
        return None

    left = df[col_name].values.astype(np.float64)
    base = df[compare_col].values.astype(np.float64)

    # Avoid division by zero
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(base != 0, (left - base) / base * 100, np.nan)

    threshold = float(cond.get("compare_value", 0))
    right = np.full(len(df), threshold)

    mask = _vec_compare(pct, operator, right)
    mask[np.isnan(pct)] = False
    return mask


def _vec_pct_change(
    cond: Dict[str, Any],
    col_name: str,
    df: pd.DataFrame,
    operator: str,
) -> Optional[np.ndarray]:
    """Vectorized pct_change: (today - N_days_ago) / N_days_ago * 100."""
    n = cond.get("lookback_n", 1)

    if col_name not in df.columns:
        return None

    current = df[col_name].values.astype(np.float64)
    past = df[col_name].shift(n).values.astype(np.float64)

    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(past != 0, (current - past) / past * 100, np.nan)

    threshold = float(cond.get("compare_value", 0))
    right = np.full(len(df), threshold)

    mask = _vec_compare(pct, operator, right)
    mask[np.isnan(pct)] = False
    return mask
