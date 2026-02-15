"""Tests for condition reachability pre-check."""
import pytest
from src.signals.rule_engine import check_reachability


class TestRangeContradiction:
    """Same field with contradictory upper/lower bounds."""

    def test_rsi_contradiction(self):
        """RSI > 70 AND RSI < 25 is impossible."""
        conditions = [
            {"field": "RSI", "operator": ">", "compare_type": "value", "compare_value": 70, "params": {"period": 14}},
            {"field": "RSI", "operator": "<", "compare_type": "value", "compare_value": 25, "params": {"period": 14}},
        ]
        reachable, reason = check_reachability(conditions)
        assert not reachable
        assert "矛盾" in reason or "不可达" in reason

    def test_kdj_valid_range(self):
        """KDJ_K > 80 AND KDJ_K < 90 is valid (80 < 90)."""
        conditions = [
            {"field": "KDJ_K", "operator": ">", "compare_type": "value", "compare_value": 80, "params": {"fastk": 9, "slowk": 3, "slowd": 3}},
            {"field": "KDJ_K", "operator": "<", "compare_type": "value", "compare_value": 90, "params": {"fastk": 9, "slowk": 3, "slowd": 3}},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable
        assert reason is None

    def test_gt_eq_contradiction(self):
        """RSI >= 80 AND RSI <= 20 is impossible."""
        conditions = [
            {"field": "RSI", "operator": ">=", "compare_type": "value", "compare_value": 80, "params": {"period": 14}},
            {"field": "RSI", "operator": "<=", "compare_type": "value", "compare_value": 20, "params": {"period": 14}},
        ]
        reachable, reason = check_reachability(conditions)
        assert not reachable

    def test_single_point_range_valid(self):
        """RSI >= 70 AND RSI <= 70 is valid (exactly 70)."""
        conditions = [
            {"field": "RSI", "operator": ">=", "compare_type": "value", "compare_value": 70, "params": {"period": 14}},
            {"field": "RSI", "operator": "<=", "compare_type": "value", "compare_value": 70, "params": {"period": 14}},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable

    def test_different_fields_ok(self):
        """RSI > 70 AND KDJ_K < 25 are different fields — always reachable."""
        conditions = [
            {"field": "RSI", "operator": ">", "compare_type": "value", "compare_value": 70, "params": {"period": 14}},
            {"field": "KDJ_K", "operator": "<", "compare_type": "value", "compare_value": 25, "params": {"fastk": 9, "slowk": 3, "slowd": 3}},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable

    def test_same_field_different_params_ok(self):
        """RSI_14 > 70 AND RSI_7 < 25 are different columns — reachable."""
        conditions = [
            {"field": "RSI", "operator": ">", "compare_type": "value", "compare_value": 70, "params": {"period": 14}},
            {"field": "RSI", "operator": "<", "compare_type": "value", "compare_value": 25, "params": {"period": 7}},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable


class TestFieldRangeValidation:
    """Out-of-range value detection for bounded indicators."""

    def test_rsi_over_100(self):
        """RSI > 120 is impossible (RSI range 0-100)."""
        conditions = [
            {"field": "RSI", "operator": ">", "compare_type": "value", "compare_value": 120, "params": {"period": 14}},
        ]
        reachable, reason = check_reachability(conditions)
        assert not reachable

    def test_rsi_under_0(self):
        """RSI < -5 is impossible."""
        conditions = [
            {"field": "RSI", "operator": "<", "compare_type": "value", "compare_value": -5, "params": {"period": 14}},
        ]
        reachable, reason = check_reachability(conditions)
        assert not reachable

    def test_boll_pband_over_1(self):
        """BOLL_pband > 1.5 is impossible (%B range 0-1)."""
        conditions = [
            {"field": "BOLL_pband", "operator": ">", "compare_type": "value", "compare_value": 1.5, "params": {"length": 20, "std": 2.0}},
        ]
        reachable, reason = check_reachability(conditions)
        assert not reachable

    def test_unbounded_field_any_value_ok(self):
        """close > 99999 is technically reachable (price is unbounded)."""
        conditions = [
            {"field": "close", "operator": ">", "compare_type": "value", "compare_value": 99999},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable


class TestFieldCompareSkipped:
    """compare_type='field' conditions should be skipped by reachability check."""

    def test_field_compare_always_reachable(self):
        """close < BOLL_lower is a field comparison — skip reachability."""
        conditions = [
            {"field": "close", "operator": "<", "compare_type": "field",
             "compare_field": "BOLL_lower", "compare_params": {"length": 20, "std": 2.0}},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable


class TestEmptyConditions:
    """Edge cases."""

    def test_empty_list(self):
        reachable, reason = check_reachability([])
        assert reachable
        assert reason is None

    def test_single_condition(self):
        conditions = [
            {"field": "RSI", "operator": "<", "compare_type": "value", "compare_value": 30, "params": {"period": 14}},
        ]
        reachable, reason = check_reachability(conditions)
        assert reachable
