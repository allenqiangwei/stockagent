# Rule Engine Upgrade (P4) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the rule engine with condition reachability pre-checks, N-day lookback conditions, and percentage deviation conditions — reducing 31% invalid strategy rate and unlocking new strategy types.

**Architecture:** Extend `_evaluate_single_rule()` with new `compare_type` options (`lookback_min/max/value`, `consecutive`, `pct_diff`, `pct_change`). Add `check_reachability()` for pre-backtest validation. Update DeepSeek prompt to generate new condition types. All changes are backward-compatible with existing 1199 strategies.

**Tech Stack:** Python, pandas, existing rule_engine.py + ai_lab_engine.py + deepseek_client.py

**Design Doc:** `docs/plans/2026-02-15-rule-engine-upgrade-design.md`

---

### Task 1: Reachability Pre-Check — Tests

**Files:**
- Create: `tests/signals/test_rule_engine_reachability.py`

**Step 1: Write failing tests for `check_reachability()`**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -m pytest tests/signals/test_rule_engine_reachability.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_reachability'`

**Step 3: Commit test file**

```bash
git add tests/signals/test_rule_engine_reachability.py
git commit -m "test: add reachability pre-check tests (red phase)"
```

---

### Task 2: Reachability Pre-Check — Implementation

**Files:**
- Modify: `src/signals/rule_engine.py` (add after line 412, before `validate_rule`)

**Step 1: Add FIELD_RANGES constant and check_reachability() function**

Add these after the `evaluate_conditions` function (after line 412) and before `validate_rule` (line 416):

```python
# ── 已知指标取值范围 ─────────────────────────────────────
FIELD_RANGES: Dict[str, Tuple[float, float]] = {
    "RSI": (0, 100),
    "KDJ_K": (0, 100),
    "KDJ_D": (0, 100),
    "KDJ_J": (-20, 120),
    "STOCHRSI_K": (0, 100),
    "STOCHRSI_D": (0, 100),
    "BOLL_pband": (0, 1),
    "ADX": (0, 100),
    "ADX_plus_di": (0, 100),
    "ADX_minus_di": (0, 100),
    "MFI": (0, 100),
    "WR": (-100, 0),
    "CCI": (-500, 500),
    "ULTOSC": (0, 100),
    "STOCH_K": (0, 100),
    "STOCH_D": (0, 100),
}


def _get_field_range(field: str) -> Optional[Tuple[float, float]]:
    """Get known value range for a field, checking base name if parametrized."""
    if field in FIELD_RANGES:
        return FIELD_RANGES[field]
    # Check base field name (strip trailing _N params): RSI_14 -> RSI
    base = field.split("_")[0]
    if base in FIELD_RANGES:
        return FIELD_RANGES[base]
    return None


def check_reachability(
    conditions: List[Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    """Check if a set of AND-combined conditions can ever be simultaneously true.

    Returns (True, None) if reachable, (False, reason_string) if contradictory.
    Only checks compare_type="value" conditions — field comparisons are skipped.
    """
    if not conditions:
        return True, None

    # Collect per-column bounds: col_name -> {"lower": float, "upper": float}
    bounds: Dict[str, Dict[str, float]] = {}

    for cond in conditions:
        compare_type = cond.get("compare_type", "value")
        if compare_type != "value":
            continue  # Skip field/lookback/pct comparisons

        field = cond.get("field", "")
        params = cond.get("params")
        col_name = resolve_column_name(field, params)
        operator = cond.get("operator", ">")

        try:
            val = float(cond.get("compare_value", 0))
        except (ValueError, TypeError):
            continue

        if col_name not in bounds:
            bounds[col_name] = {"lower": float("-inf"), "upper": float("inf")}

        b = bounds[col_name]
        if operator in (">", ">="):
            b["lower"] = max(b["lower"], val)
        elif operator in ("<", "<="):
            b["upper"] = min(b["upper"], val)

    # Check 1: Range contradiction — lower >= upper means impossible
    for col_name, b in bounds.items():
        if b["lower"] >= b["upper"]:
            return False, f"条件矛盾: {col_name} 要求同时 >{b['lower']} 且 <{b['upper']}"

    # Check 2: Out-of-range for bounded indicators
    for col_name, b in bounds.items():
        field_range = _get_field_range(col_name)
        if not field_range:
            continue
        range_min, range_max = field_range

        # Lower bound exceeds indicator max → impossible
        if b["lower"] != float("-inf") and b["lower"] >= range_max:
            return False, f"不可达: {col_name} >{b['lower']} 超出取值范围上限{range_max}"
        # Upper bound below indicator min → impossible
        if b["upper"] != float("inf") and b["upper"] <= range_min:
            return False, f"不可达: {col_name} <{b['upper']} 低于取值范围下限{range_min}"

    return True, None
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -m pytest tests/signals/test_rule_engine_reachability.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/signals/rule_engine.py
git commit -m "feat: add check_reachability() for condition contradiction detection"
```

---

### Task 3: Integrate Reachability Check into AI Lab Engine

**Files:**
- Modify: `api/services/ai_lab_engine.py:461-469` (the strategy loop before backtest)

**Step 1: Add reachability check before backtest**

In the strategy loop (line 461), after the `strat.status == "failed"` skip check (line 462-469), add a reachability check before the backtest call. Insert after line 469 (`continue`) and before line 471 (`progress.push`):

```python
            # ── Reachability pre-check ──
            buy_conds = strat.buy_conditions or []
            if buy_conds:
                from src.signals.rule_engine import check_reachability
                reachable, reason = check_reachability(buy_conds)
                if not reachable:
                    strat.status = "invalid"
                    strat.error_message = f"条件不可达: {reason}"
                    strat.score = 0.0
                    self.db.commit()
                    progress.push({
                        "type": "backtest_skip",
                        "index": idx, "total": total,
                        "name": strat.name,
                        "reason": strat.error_message,
                    })
                    continue
```

**Step 2: Verify manually**

The reachability check has no separate integration test — it will be validated in Task 7 (end-to-end).

**Step 3: Commit**

```bash
git add api/services/ai_lab_engine.py
git commit -m "feat: integrate reachability pre-check before backtest in AI Lab"
```

---

### Task 4: N-Day Lookback Conditions — Tests

**Files:**
- Create: `tests/signals/test_rule_engine_lookback.py`

**Step 1: Write failing tests**

```python
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
        """Last 3 days: 10→11→12→13 (3 consecutive rises)."""
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
        """Last 3 days: 10→12→11→13 (not consecutive — 12→11 is a dip)."""
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
        """Last 3 days: 13→12→11→10 (3 consecutive falls)."""
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -m pytest tests/signals/test_rule_engine_lookback.py -v`
Expected: FAIL (lookback types not handled)

**Step 3: Commit test file**

```bash
git add tests/signals/test_rule_engine_lookback.py
git commit -m "test: add N-day lookback condition tests (red phase)"
```

---

### Task 5: N-Day Lookback Conditions — Implementation

**Files:**
- Modify: `src/signals/rule_engine.py:316` (`_evaluate_single_rule`), `287` (`evaluate_rules`), `368` (`evaluate_conditions`)

**Step 1: Update `_evaluate_single_rule` signature and add lookback logic**

Replace the existing `_evaluate_single_rule` function (lines 316-363) with:

```python
def _evaluate_single_rule(
    rule: Dict[str, Any], row: pd.Series, df_slice: Optional[pd.DataFrame] = None
) -> bool:
    """评估单条规则是否被触发

    Args:
        rule: 规则字典
        row: 当前行（最新数据点）
        df_slice: 截止到当前行的完整 DataFrame（lookback 类型条件需要）
    """
    field = rule.get("field", "")
    operator = rule.get("operator", ">")
    compare_type = rule.get("compare_type", "value")
    params = rule.get("params")

    # 将 field+params 映射到实际列名
    col_name = resolve_column_name(field, params)

    # ── consecutive 类型：不需要 left_val，直接看序列 ──
    if compare_type == "consecutive":
        return _evaluate_consecutive(rule, col_name, df_slice)

    # 获取左值
    if col_name not in row.index:
        logger.debug("Column '%s' not found for field='%s' params=%s", col_name, field, params)
        return False
    left_val = row[col_name]
    if pd.isna(left_val):
        return False

    # 获取右值
    if compare_type == "field":
        compare_field = rule.get("compare_field", "")
        compare_params = rule.get("compare_params")
        compare_col = resolve_column_name(compare_field, compare_params)
        if compare_col not in row.index:
            logger.debug("Compare column '%s' not found", compare_col, compare_field, compare_params)
            return False
        right_val = row[compare_col]
        if pd.isna(right_val):
            return False
    elif compare_type in ("lookback_min", "lookback_max"):
        right_val = _get_lookback_extreme(rule, col_name, df_slice, compare_type)
        if right_val is None:
            return False
    elif compare_type == "lookback_value":
        right_val = _get_lookback_value(rule, df_slice)
        if right_val is None:
            return False
    elif compare_type == "pct_diff":
        return _evaluate_pct_diff(rule, row, left_val, operator)
    elif compare_type == "pct_change":
        return _evaluate_pct_change(rule, col_name, df_slice, left_val, operator)
    else:
        right_val = rule.get("compare_value", 0)

    try:
        left_val = float(left_val)
        right_val = float(right_val)
    except (ValueError, TypeError):
        return False

    return _compare(left_val, operator, right_val)


def _compare(left: float, operator: str, right: float) -> bool:
    """Apply comparison operator."""
    if operator == ">":
        return left > right
    elif operator == "<":
        return left < right
    elif operator == ">=":
        return left >= right
    elif operator == "<=":
        return left <= right
    return False


def _get_lookback_extreme(
    rule: Dict[str, Any], col_name: str, df_slice: Optional[pd.DataFrame], mode: str
) -> Optional[float]:
    """Get MIN or MAX of a field over the last N days (excluding today)."""
    if df_slice is None:
        return None
    n = rule.get("lookback_n", 5)
    lookback_field = rule.get("lookback_field", rule.get("field", ""))
    lookback_params = rule.get("lookback_params", rule.get("params"))
    lookback_col = resolve_column_name(lookback_field, lookback_params)
    if lookback_col not in df_slice.columns:
        return None
    # Need at least n+1 rows (n previous + today)
    if len(df_slice) < n + 1:
        return None
    window = df_slice[lookback_col].iloc[-(n + 1):-1]  # last N rows excluding today
    if window.isna().all():
        return None
    if mode == "lookback_min":
        return float(window.min())
    else:
        return float(window.max())


def _get_lookback_value(
    rule: Dict[str, Any], df_slice: Optional[pd.DataFrame]
) -> Optional[float]:
    """Get value of lookback_field from N days ago."""
    if df_slice is None:
        return None
    n = rule.get("lookback_n", 1)
    lookback_field = rule.get("lookback_field", rule.get("field", ""))
    lookback_params = rule.get("lookback_params", rule.get("params"))
    lookback_col = resolve_column_name(lookback_field, lookback_params)
    if lookback_col not in df_slice.columns:
        return None
    if len(df_slice) < n + 1:
        return None
    val = df_slice[lookback_col].iloc[-(n + 1)]
    if pd.isna(val):
        return None
    return float(val)


def _evaluate_consecutive(
    rule: Dict[str, Any], col_name: str, df_slice: Optional[pd.DataFrame]
) -> bool:
    """Check if field has been consecutively rising/falling for N days."""
    if df_slice is None:
        return False
    n = rule.get("lookback_n", 3)
    consecutive_type = rule.get("consecutive_type", "rising")
    if col_name not in df_slice.columns:
        return False
    if len(df_slice) < n + 1:
        return False
    # Get last n+1 values (need n+1 to check n transitions)
    values = df_slice[col_name].iloc[-(n + 1):].values
    if any(pd.isna(v) for v in values):
        return False
    for i in range(1, len(values)):
        if consecutive_type == "rising" and values[i] <= values[i - 1]:
            return False
        elif consecutive_type == "falling" and values[i] >= values[i - 1]:
            return False
    return True
```

**Step 2: Update `evaluate_rules` to pass df_slice**

In `evaluate_rules()` (line 287), change the `_evaluate_single_rule` call at line 305 from:
```python
triggered = _evaluate_single_rule(rule, latest)
```
to:
```python
triggered = _evaluate_single_rule(rule, latest, df_slice=indicator_df)
```

**Step 3: Update `evaluate_conditions` to pass df_slice**

In `evaluate_conditions()` (line 368), change both `_evaluate_single_rule` calls (lines 395 and 405) from:
```python
if _evaluate_single_rule(cond, latest):
```
to:
```python
if _evaluate_single_rule(cond, latest, df_slice=indicator_df):
```

**Step 4: Run tests**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -m pytest tests/signals/test_rule_engine_lookback.py tests/signals/test_rule_engine_reachability.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/signals/rule_engine.py
git commit -m "feat: add lookback_min/max/value and consecutive condition types"
```

---

### Task 6: Percentage Deviation Conditions — Tests & Implementation

**Files:**
- Create: `tests/signals/test_rule_engine_pct.py`
- Modify: `src/signals/rule_engine.py` (add helper functions referenced in Task 5's `_evaluate_single_rule`)

**Step 1: Write tests**

```python
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
    """compare_type='pct_diff' — percentage difference between two fields."""

    def test_close_below_vwap_by_3pct(self):
        """close=97, VWAP=100 → pct_diff = -3% < -2% → triggered."""
        df = _make_df([100, 100, 100, 97], extra_cols={"VWAP": [100, 100, 100, 100]})
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": -2.0,
            "label": "偏离VWAP超2%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_close_near_vwap(self):
        """close=99, VWAP=100 → pct_diff = -1% > -2% → NOT triggered."""
        df = _make_df([100, 100, 100, 99], extra_cols={"VWAP": [100, 100, 100, 100]})
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": -2.0,
            "label": "偏离VWAP超2%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered

    def test_close_above_vwap(self):
        """close=105, VWAP=100 → pct_diff = +5% > 3% → triggered."""
        df = _make_df([100, 100, 100, 105], extra_cols={"VWAP": [100, 100, 100, 100]})
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": 3.0,
            "label": "高于VWAP 3%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert triggered

    def test_zero_base_returns_false(self):
        """VWAP=0 would cause division by zero — should return False."""
        df = _make_df([100, 100, 100, 97], extra_cols={"VWAP": [0, 0, 0, 0]})
        conditions = [{
            "field": "close", "operator": "<",
            "compare_type": "pct_diff",
            "compare_field": "VWAP", "compare_value": -2.0,
            "label": "偏离VWAP",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered


class TestPctChange:
    """compare_type='pct_change' — N-day percentage change of a field."""

    def test_5day_rise_over_5pct(self):
        """close went from 100 to 106 in 5 days → +6% > 5% → triggered."""
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
        """close went from 100 to 103 in 5 days → +3% < 5% → NOT triggered."""
        df = _make_df([95, 100, 101, 102, 103, 103])
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_change",
            "lookback_n": 5, "compare_value": 5.0,
            "label": "5日涨超5%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered

    def test_1day_drop(self):
        """close dropped from 100 to 95 → -5% < -3% → triggered."""
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
        """Only 2 rows, lookback_n=5 — should not trigger."""
        df = _make_df([100, 106])
        conditions = [{
            "field": "close", "operator": ">",
            "compare_type": "pct_change",
            "lookback_n": 5, "compare_value": 5.0,
            "label": "5日涨超5%",
        }]
        triggered, labels = evaluate_conditions(conditions, df)
        assert not triggered
```

**Step 2: Add pct_diff and pct_change helper functions**

Add these to `src/signals/rule_engine.py`, right after `_evaluate_consecutive()` (before the `evaluate_conditions` section):

```python
def _evaluate_pct_diff(
    rule: Dict[str, Any], row: pd.Series, left_val: float, operator: str
) -> bool:
    """Evaluate percentage difference: (field - compare_field) / compare_field * 100."""
    compare_field = rule.get("compare_field", "")
    compare_params = rule.get("compare_params")
    compare_col = resolve_column_name(compare_field, compare_params)
    if compare_col not in row.index:
        return False
    base_val = row[compare_col]
    if pd.isna(base_val):
        return False
    try:
        base_val = float(base_val)
        left_val = float(left_val)
    except (ValueError, TypeError):
        return False
    if base_val == 0:
        return False
    pct = (left_val - base_val) / base_val * 100
    threshold = float(rule.get("compare_value", 0))
    return _compare(pct, operator, threshold)


def _evaluate_pct_change(
    rule: Dict[str, Any],
    col_name: str,
    df_slice: Optional[pd.DataFrame],
    left_val: float,
    operator: str,
) -> bool:
    """Evaluate N-day percentage change: (today - N_days_ago) / N_days_ago * 100."""
    if df_slice is None:
        return False
    n = rule.get("lookback_n", 1)
    if len(df_slice) < n + 1:
        return False
    if col_name not in df_slice.columns:
        return False
    past_val = df_slice[col_name].iloc[-(n + 1)]
    if pd.isna(past_val):
        return False
    try:
        past_val = float(past_val)
        left_val = float(left_val)
    except (ValueError, TypeError):
        return False
    if past_val == 0:
        return False
    pct = (left_val - past_val) / past_val * 100
    threshold = float(rule.get("compare_value", 0))
    return _compare(pct, operator, threshold)
```

**Step 3: Run all tests**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -m pytest tests/signals/test_rule_engine_pct.py tests/signals/test_rule_engine_lookback.py tests/signals/test_rule_engine_reachability.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/signals/test_rule_engine_pct.py src/signals/rule_engine.py
git commit -m "feat: add pct_diff and pct_change condition types"
```

---

### Task 7: validate_rule() & collect_indicator_params() Enhancement

**Files:**
- Modify: `src/signals/rule_engine.py:416` (`validate_rule`), `src/signals/rule_engine.py:211` (`collect_indicator_params`)

**Step 1: Update validate_rule() to accept new compare_types**

Replace the compare_type validation block in `validate_rule()` (around lines 429-440):

```python
    VALID_COMPARE_TYPES = {
        "value", "field",
        "lookback_min", "lookback_max", "lookback_value", "consecutive",
        "pct_diff", "pct_change",
    }

    compare_type = rule.get("compare_type", "value")
    if compare_type not in VALID_COMPARE_TYPES:
        return f"未知比较类型: {compare_type}"

    if compare_type == "field":
        cf = rule.get("compare_field", "")
        if not get_field_group(cf) and not get_extended_field_group(cf):
            return f"未知比较字段: {cf}"
    elif compare_type == "value":
        try:
            float(rule.get("compare_value", 0))
        except (ValueError, TypeError):
            return "比较值必须是数字"
    elif compare_type in ("lookback_min", "lookback_max", "lookback_value", "consecutive"):
        n = rule.get("lookback_n")
        if not isinstance(n, int) or n < 1 or n > 60:
            return f"lookback_n 必须是 1-60 的整数（当前: {n}）"
        if compare_type == "consecutive":
            ct = rule.get("consecutive_type", "")
            if ct not in ("rising", "falling"):
                return f"consecutive_type 必须是 rising 或 falling（当前: {ct}）"
    elif compare_type in ("pct_diff", "pct_change"):
        try:
            float(rule.get("compare_value", 0))
        except (ValueError, TypeError):
            return "比较值必须是数字"
        if compare_type == "pct_diff":
            cf = rule.get("compare_field", "")
            if not cf:
                return "pct_diff 类型必须指定 compare_field"
        if compare_type == "pct_change":
            n = rule.get("lookback_n")
            if not isinstance(n, int) or n < 1 or n > 60:
                return f"lookback_n 必须是 1-60 的整数（当前: {n}）"
```

**Step 2: Update collect_indicator_params() to collect lookback_field**

In `collect_indicator_params()`, add after line 270 (the `compare_field` collection block):

```python
        # 收集 lookback 字段
        if rule.get("lookback_field"):
            _add_to_result(
                rule.get("lookback_field", ""),
                rule.get("lookback_params", rule.get("params"))
            )
```

**Step 3: Run all rule engine tests**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -m pytest tests/signals/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/signals/rule_engine.py
git commit -m "feat: enhance validate_rule and collect_indicator_params for new types"
```

---

### Task 8: DeepSeek Prompt Update

**Files:**
- Modify: `api/services/deepseek_client.py:14-100` (the `_SYSTEM_PROMPT_TEMPLATE`)

**Step 1: Update the condition format section**

In `_SYSTEM_PROMPT_TEMPLATE`, replace lines 22-32 (the condition format JSON block) with:

```python
## 条件格式

每个条件是一个 JSON 对象。支持以下 compare_type:

### 基础类型 (value/field)
{{
  "field": "指标字段名",
  "params": {{"参数名": 值}},
  "operator": "> 或 < 或 >= 或 <=",
  "compare_type": "value",
  "compare_value": 数字,
  "label": "条件描述"
}}

### N日回溯类型 (lookback_min/lookback_max/lookback_value)
{{
  "field": "close", "operator": "<=",
  "compare_type": "lookback_min",
  "lookback_field": "close", "lookback_n": 5,
  "label": "收盘价创5日新低"
}}
说明: lookback_min=过去N日最小值, lookback_max=过去N日最大值, lookback_value=N日前的值
lookback_n 范围 1-20, 不要用太长的回溯周期

### 连续型 (consecutive)
{{
  "field": "close",
  "compare_type": "consecutive",
  "lookback_n": 3, "consecutive_type": "rising",
  "label": "连续3日上涨"
}}
说明: consecutive_type 可选 "rising"(连涨) 或 "falling"(连跌)

### 百分比偏差型 (pct_diff)
{{
  "field": "close", "operator": "<",
  "compare_type": "pct_diff",
  "compare_field": "VWAP", "compare_value": -2.0,
  "label": "收盘价低于VWAP超过2%"
}}
说明: 计算 (field - compare_field) / compare_field * 100, 与 compare_value 比较
适用于 VWAP/BOLL 等价格类指标的偏离度判断

### N日涨跌幅型 (pct_change)
{{
  "field": "close", "operator": ">",
  "compare_type": "pct_change",
  "lookback_n": 5, "compare_value": 5.0,
  "label": "5日涨幅超过5%"
}}
说明: 计算 (today - N日前) / N日前 * 100, 与 compare_value 比较
适用于涨跌幅、量能变化等
```

**Step 2: Add rule 14 to the important rules section**

After rule 13 (line ~100), add:
```
14. **新条件类型使用建议**:
    - VWAP偏离: 用 pct_diff (close vs VWAP), 阈值 ±1%~±3%
    - N日突破: 用 lookback_max (close >= 20日最高), 配合 volume pct_change
    - 连涨连跌: 用 consecutive, lookback_n 建议 2-5 日
    - 涨跌幅: 用 pct_change, 典型阈值 ±3%~±10%
    - 新类型条件建议每策略最多用 1-2 个, 其余用 value/field 基础类型
```

**Step 3: Commit**

```bash
git add api/services/deepseek_client.py
git commit -m "feat: update DeepSeek prompt with new condition types"
```

---

### Task 9: End-to-End Verification

**Step 1: Start the backend**

```bash
cd /Users/allenqiang/stockagent
lsof -ti:8050 | xargs kill -9 2>/dev/null
nohup venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/stockagent-api.log 2>&1 &
sleep 5
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/health
```

**Step 2: Run a test experiment with new condition types**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s --max-time 120 -X POST http://127.0.0.1:8050/api/lab/experiments \
  -H "Content-Type: application/json" \
  -d '{
    "theme": "P4规则引擎验证_回溯+偏差",
    "source_type": "custom",
    "source_text": "测试新条件类型。用以下策略方向：\n1. VWAP均值回归：close偏离VWAP超过-2%时买入(pct_diff)，收盘价高于VWAP时卖出\n2. 连续下跌反弹：连续3日下跌后(consecutive falling)，且RSI<30买入\n3. N日突破：close创20日新高(lookback_max)买入\n4. 5日涨幅：5日涨幅超过8%(pct_change)时卖出止盈\n每个方向生成2个变体(激进+保守)。使用新的compare_type: pct_diff, consecutive, lookback_max, pct_change。",
    "initial_capital": 100000,
    "max_positions": 10,
    "max_position_pct": 30
  }' &
PID=$!
sleep 3
kill $PID 2>/dev/null; wait $PID 2>/dev/null
```

**Step 3: Monitor and verify**

Poll experiment status. Verify that:
1. DeepSeek generates strategies with new condition types
2. Reachability check catches contradictory conditions (if any)
3. Backtest runs successfully with lookback/pct conditions
4. Results are meaningful (non-zero trades)

```bash
# Get latest experiment ID and check status
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments?page=1&size=1" | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items', [])
if items:
    e = items[0]
    print(f'ID: {e[\"id\"]}, Status: {e[\"status\"]}, Theme: {e[\"theme\"]}')
"
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: rule engine P4 upgrade complete — reachability, lookback, pct conditions"
```

---

### Task 10: Update Lab Memory

**Files:**
- Modify: `docs/lab-experiment-analysis.md` (已知问题 section)

**Step 1: Update known issues**

Mark rule engine upgrade as complete in the 已知问题 table. Update the 探索状态 to show P4 is done.

**Step 2: Commit**

```bash
git add docs/lab-experiment-analysis.md
git commit -m "docs: update lab memory with P4 rule engine upgrade status"
```
