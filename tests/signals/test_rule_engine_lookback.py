"""Tests for N-day lookback condition types."""
import pandas as pd
import numpy as np
import pytest
from src.signals.rule_engine import evaluate_conditions


def _make_df(close_values: list[float], extra_cols: dict = None) -> pd.DataFrame:
    """Helper to build a DataFrame with date index and close column."""
    n = len(close_values)
    df = pd.DataFrame({
        "close": close_values,
        "open": [v * 0.99 for v in close_values],
        "high": [v * 1.01 for v in close_values],
        "low": [v * 0.98 for v in close_values],
        "volume": [1000000] * n,
    })
    if extra_cols:
        for k, v in extra_cols.items():
            df[k] = v
    return df


class TestLookbackMin:
    """compare_type='lookback_min' — field <= MIN(lookback_field, N days)."""

    def test_close_at_5day_low(self):
        """close=8 is new 5-day low (previous 5 days: 10,11,12,9,10)."""
        df = _make_df([10, 11, 12, 9, 10, 8])
        conditions = [{
            "field": "close", "operator": "<=",
            "compare_type": "lookback_min",
            "lookback_field": "close", "lookback_n": 5,
            "label": "5日新低",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered
        assert "5日新低" in labels

    def test_close_not_at_5day_low(self):
        """close=11 is NOT 5-day low (previous 5 days: 10,11,12,9,10)."""
        df = _make_df([10, 11, 12, 9, 10, 11])
        conditions = [{
            "field": "close", "operator": "<=",
            "compare_type": "lookback_min",
            "lookback_field": "close", "lookback_n": 5,
            "label": "5日新低",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered

    def test_insufficient_data(self):
        """Only 2 rows of data, lookback_n=5 — should not trigger."""
        df = _make_df([10, 8])
        conditions = [{
            "field": "close", "operator": "<=",
            "compare_type": "lookback_min",
            "lookback_field": "close", "lookback_n": 5,
            "label": "5日新低",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered


class TestLookbackMax:
    """compare_type='lookback_max' — field >= MAX(lookback_field, N days)."""

    def test_close_at_5day_high(self):
        """close=15 is new 5-day high (previous: 10,11,12,13,14)."""
        df = _make_df([10, 11, 12, 13, 14, 15])
        conditions = [{
            "field": "close", "operator": ">=",
            "compare_type": "lookback_max",
            "lookback_field": "close", "lookback_n": 5,
            "label": "5日新高",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered


class TestLookbackValue:
    """compare_type='lookback_value' — field vs lookback_field[N days ago]."""

    def test_close_higher_than_yesterday(self):
        """close=12 > close[1 day ago]=10."""
        df = _make_df([8, 9, 10, 12])
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "lookback_value",
            "lookback_field": "close", "lookback_n": 1,
            "label": "今涨",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_close_lower_than_3_days_ago(self):
        """close=7 < close[3 days ago]=10."""
        df = _make_df([10, 11, 12, 7])
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "lookback_value",
            "lookback_field": "close", "lookback_n": 3,
            "label": "3日回落",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered


class TestConsecutive:
    """compare_type='consecutive' — consecutive N days rising/falling."""

    def test_3_consecutive_rising(self):
        """Last 3 days: 10->11->12->13 (3 consecutive rises)."""
        df = _make_df([8, 9, 10, 11, 12, 13])
        conditions = [{
            "field": "close",
            "compare_type": "consecutive",
            "lookback_n": 3,
            "consecutive_type": "rising",
            "label": "连涨3日",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_not_consecutive_rising(self):
        """Last 3 days: 10->12->11->13 (not consecutive — 12->11 is a dip)."""
        df = _make_df([8, 10, 12, 11, 13])
        conditions = [{
            "field": "close",
            "compare_type": "consecutive",
            "lookback_n": 3,
            "consecutive_type": "rising",
            "label": "连涨3日",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered

    def test_consecutive_falling(self):
        """Last 3 days: 13->12->11->10 (3 consecutive falls)."""
        df = _make_df([15, 13, 12, 11, 10])
        conditions = [{
            "field": "close",
            "compare_type": "consecutive",
            "lookback_n": 3,
            "consecutive_type": "falling",
            "label": "连跌3日",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered


class TestBackwardCompatibility:
    """Existing value/field conditions still work with new code."""

    def test_value_compare(self):
        df = _make_df([10, 11, 12, 13, 14, 15])
        df["RSI_14"] = [30, 35, 40, 25, 20, 18]
        conditions = [{
            "field": "RSI", "operator": "<",
            "compare_type": "value", "compare_value": 30,
            "params": {"period": 14},
            "label": "RSI超卖",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_field_compare(self):
        df = _make_df([10, 11, 12, 13, 14, 15])
        df["KDJ_K_9_3_3"] = [20, 25, 30, 35, 40, 45]
        df["KDJ_D_9_3_3"] = [30, 30, 30, 30, 30, 30]
        conditions = [{
            "field": "KDJ_K", "operator": ">",
            "compare_type": "field",
            "compare_field": "KDJ_D",
            "params": {"fastk": 9, "slowk": 3, "slowd": 3},
            "compare_params": {"fastk": 9, "slowk": 3, "slowd": 3},
            "label": "K上穿D",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered
