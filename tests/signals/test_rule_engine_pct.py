"""Tests for percentage deviation condition types."""
import pandas as pd
import pytest
from src.signals.rule_engine import evaluate_conditions


def _make_df(close_values: list[float], extra_cols: dict = None) -> pd.DataFrame:
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


class TestPctDiff:
    """compare_type='pct_diff' -- percentage difference between two fields."""

    def test_close_below_vwap_by_3pct(self):
        """close=97, VWAP_14=100 -> pct_diff = -3% < -2% -> triggered."""
        df = _make_df([100, 100, 100, 97], extra_cols={"VWAP_14": [100, 100, 100, 100]})
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": -2.0,
            "label": "偏离VWAP超2%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_close_near_vwap(self):
        """close=99, VWAP_14=100 -> pct_diff = -1% > -2% -> NOT triggered."""
        df = _make_df([100, 100, 100, 99], extra_cols={"VWAP_14": [100, 100, 100, 100]})
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": -2.0,
            "label": "偏离VWAP超2%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered

    def test_close_above_vwap(self):
        """close=105, VWAP_14=100 -> pct_diff = +5% > 3% -> triggered."""
        df = _make_df([100, 100, 100, 105], extra_cols={"VWAP_14": [100, 100, 100, 100]})
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": 3.0,
            "label": "高于VWAP 3%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_zero_base_returns_false(self):
        """VWAP_14=0 would cause division by zero -- should return False."""
        df = _make_df([100, 100, 100, 97], extra_cols={"VWAP_14": [0, 0, 0, 0]})
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": -2.0,
            "label": "偏离VWAP",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered


class TestPctChange:
    """compare_type='pct_change' -- N-day percentage change of a field."""

    def test_5day_rise_over_5pct(self):
        """close went from 100 to 106 in 5 days -> +6% > 5% -> triggered."""
        df = _make_df([95, 100, 101, 102, 103, 106])
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_change",
            "lookback_n": 5, "compare_value": 5.0,
            "label": "5日涨超5%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_5day_rise_under_5pct(self):
        """close went from 100 to 103 in 5 days -> +3% < 5% -> NOT triggered."""
        df = _make_df([100, 101, 102, 103, 103, 103])
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_change",
            "lookback_n": 5, "compare_value": 5.0,
            "label": "5日涨超5%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered

    def test_1day_drop(self):
        """close dropped from 100 to 95 -> -5% < -3% -> triggered."""
        df = _make_df([90, 100, 95])
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_change",
            "lookback_n": 1, "compare_value": -3.0,
            "label": "日跌超3%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_insufficient_data(self):
        """Only 2 rows, lookback_n=5 -- should not trigger."""
        df = _make_df([100, 106])
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_change",
            "lookback_n": 5, "compare_value": 5.0,
            "label": "5日涨超5%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered
