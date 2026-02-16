# 已知问题批量修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 unresolved AI Lab issues (P14/P18/P4/P21/P22) to improve backtest performance and strategy generation quality.

**Architecture:** Module-level threading semaphore for P14; indicator cache merging for P18; quick signal pre-scan for P4; few-shot examples + keyword triggers for P21; auto-correction in validation pipeline for P22.

**Tech Stack:** Python 3, FastAPI, threading, SQLAlchemy, pandas

---

### Task 1: P14 — Backtest Concurrency Control (Semaphore)

**Files:**
- Modify: `api/services/ai_lab_engine.py:8-12` (imports), `:992-993` (timeout constants), `:995-1010` (method entry)
- Modify: `api/routers/ai_lab.py:455-514` (clone-backtest thread)

**Step 1: Add module-level semaphore in ai_lab_engine.py**

In `api/services/ai_lab_engine.py`, add after the imports (around line 12):

```python
import threading

# Limit concurrent backtests to avoid SQLite contention
_BACKTEST_SEMAPHORE = threading.Semaphore(3)
```

Note: `threading` is already imported at line 10, so just add the semaphore line after the existing imports block (after line 30, before the class definition).

**Step 2: Wrap `_run_single_backtest()` with semaphore acquire/release**

In `api/services/ai_lab_engine.py`, modify `_run_single_backtest()` (line 995). Wrap the entire method body with semaphore:

```python
def _run_single_backtest(
    self,
    strat: ExperimentStrategy,
    stock_data: dict,
    start_date: str,
    end_date: str,
    exp: Experiment = None,
    regime_map: dict | None = None,
    index_return_pct: float = 0.0,
):
    """Run portfolio backtest for a single experiment strategy."""
    _BACKTEST_SEMAPHORE.acquire()
    try:
        self._run_single_backtest_inner(
            strat, stock_data, start_date, end_date,
            exp, regime_map, index_return_pct,
        )
    finally:
        _BACKTEST_SEMAPHORE.release()
```

Actually, a cleaner approach — just add acquire/release at the top of the existing method without splitting:

At the very start of `_run_single_backtest()` body (line 1010, before `strat.status = "backtesting"`):

```python
_BACKTEST_SEMAPHORE.acquire()
```

And wrap everything from line 1010 through the end of the method in a try/finally that calls `_BACKTEST_SEMAPHORE.release()` in finally.

**Step 3: Increase single-strategy timeout from 300s to 600s**

In `api/services/ai_lab_engine.py` line 992, change:

```python
BACKTEST_TIMEOUT_SECONDS = 600  # was 300, increased for queue wait time
```

**Step 4: Add semaphore to clone-backtest in ai_lab.py**

In `api/routers/ai_lab.py`, the `_run_backtest()` inner function (line 455) also calls `engine._run_single_backtest()` which will now acquire the semaphore automatically. No extra change needed here since P14 is handled at the engine level.

However, add a log message at the start of `_run_backtest()` (after line 460):

```python
logger.info("Clone-backtest queued for strategy %s (semaphore)", clone_id)
```

Add the logger import at the top of the file if not already present.

**Step 5: Verify the change compiles**

Run:
```bash
cd /Users/allenqiang/stockagent && /Users/allenqiang/stockagent/venv/bin/python -c "from api.services.ai_lab_engine import AILabEngine; print('OK')"
```
Expected: `OK`

**Step 6: Commit**

```bash
git add api/services/ai_lab_engine.py api/routers/ai_lab.py
git commit -m "feat(lab): add backtest concurrency semaphore (P14)

Limit concurrent backtests to 3 via threading.Semaphore to avoid
SQLite contention when multiple clone-backtests run simultaneously.
Increase single-strategy timeout from 300s to 600s for queue wait."
```

---

### Task 2: P18 — Combo Strategy Short-Circuit Evaluation

**Files:**
- Modify: `src/backtest/portfolio_engine.py:375-393` (combo buy voting), `:313-325` (combo sell voting)

**Step 1: Add short-circuit to combo buy voting**

In `src/backtest/portfolio_engine.py`, the combo buy voting loop at lines 375-390. Add an early break when vote threshold is met:

Replace the loop body (lines 376-390) with:

```python
                    if is_combo and member_strategies:
                        # Combo buy: vote across member strategies
                        buy_votes = 0
                        weighted_score = 0.0
                        for m in member_strategies:
                            m_buy = m.get("buy_conditions", [])
                            if m_buy:
                                triggered, _ = evaluate_conditions(m_buy, df_slice, mode="AND")
                                if triggered:
                                    buy_votes += 1
                                    weighted_score += m.get("weight", 1.0)
                            # Short-circuit: stop evaluating once threshold met
                            if combo_weight_mode == "equal" and buy_votes >= combo_vote_threshold:
                                break
                            if combo_weight_mode != "equal" and weighted_score >= combo_score_threshold:
                                break

                        if combo_weight_mode == "equal":
                            buy_signal = buy_votes >= combo_vote_threshold
                        else:  # score_weighted
                            buy_signal = weighted_score >= combo_score_threshold
```

**Step 2: Add short-circuit to combo sell voting**

In `src/backtest/portfolio_engine.py`, the combo sell voting loop at lines 313-325. Add early break:

Replace lines 314-325 with:

```python
                    if is_combo and member_strategies:
                        # Combo sell: evaluate each member's sell conditions
                        sell_votes = 0
                        for m in member_strategies:
                            m_sell = m.get("sell_conditions", [])
                            if m_sell:
                                triggered, _ = evaluate_conditions(m_sell, df_slice, mode="OR")
                                if triggered:
                                    sell_votes += 1
                            # Short-circuit for "any" mode: one vote is enough
                            if combo_sell_mode == "any" and sell_votes > 0:
                                break
                            # Short-circuit for "majority": enough votes already
                            if combo_sell_mode == "majority" and sell_votes > len(member_strategies) / 2:
                                break
                        if combo_sell_mode == "any" and sell_votes > 0:
                            sell_reason = "strategy_exit"
                        elif combo_sell_mode == "majority" and sell_votes > len(member_strategies) / 2:
                            sell_reason = "strategy_exit"
```

**Step 3: Verify the change compiles**

Run:
```bash
cd /Users/allenqiang/stockagent && /Users/allenqiang/stockagent/venv/bin/python -c "from src.backtest.portfolio_engine import PortfolioBacktestEngine; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add src/backtest/portfolio_engine.py
git commit -m "perf(backtest): short-circuit combo voting evaluation (P18)

Break out of member evaluation loop once vote threshold is met.
For buy: stop when buy_votes >= threshold or weighted_score >= threshold.
For sell: stop on first vote in 'any' mode, or majority reached."
```

---

### Task 3: P4 — Quick Signal Pre-Scan (Zero-Trade Detection)

**Files:**
- Modify: `api/services/ai_lab_engine.py` — add `_quick_signal_check()` method and call it from `_run_single_backtest()`

**Step 1: Add `_quick_signal_check()` method**

In `api/services/ai_lab_engine.py`, add a new method to the `AILabEngine` class, just before the `_run_single_backtest()` method (around line 989):

```python
    # ── Quick signal pre-scan ─────────────────────────────
    _PRESCAN_SAMPLE_SIZE = 100
    _PRESCAN_DAYS = 60

    def _quick_signal_check(
        self, strat: ExperimentStrategy, stock_data: dict,
    ) -> bool:
        """Quick pre-scan: sample stocks and check if any buy signal fires.

        Returns True if at least one signal found (strategy is viable).
        Returns False if zero signals across all samples (likely zero-trade).
        """
        import random
        import pandas as pd
        from src.signals.rule_engine import (
            collect_indicator_params,
            evaluate_conditions,
        )
        from src.indicators.indicator_calculator import (
            IndicatorCalculator,
            IndicatorConfig,
        )

        buy_conditions = strat.buy_conditions or []
        if not buy_conditions:
            return False

        # Sample up to N stocks
        codes = list(stock_data.keys())
        if len(codes) > self._PRESCAN_SAMPLE_SIZE:
            codes = random.sample(codes, self._PRESCAN_SAMPLE_SIZE)

        # Build indicator config from buy conditions only
        all_rules = buy_conditions + (strat.sell_conditions or [])
        collected = collect_indicator_params(all_rules)
        config = IndicatorConfig.from_collected_params(collected)
        calculator = IndicatorCalculator(config)

        for code in codes:
            df = stock_data.get(code)
            if df is None or df.empty:
                continue

            # Take only last N days
            df_tail = df.tail(self._PRESCAN_DAYS).copy()
            if len(df_tail) < 10:
                continue

            try:
                indicators = calculator.calculate_all(df_tail)
                df_full = pd.concat(
                    [df_tail.reset_index(drop=True), indicators.reset_index(drop=True)],
                    axis=1,
                )
                # Check last 30 rows for any buy signal
                for i in range(max(0, len(df_full) - 30), len(df_full)):
                    df_slice = df_full.iloc[: i + 1]
                    triggered, _ = evaluate_conditions(buy_conditions, df_slice, mode="AND")
                    if triggered:
                        return True
            except Exception:
                continue  # Skip stocks with calculation errors

        return False
```

**Step 2: Call pre-scan from `_run_single_backtest()`**

In `_run_single_backtest()`, after the semaphore acquire and before the main backtest logic, add the pre-scan check. Insert after `strat.status = "backtesting"` / `self.db.commit()` (around line 1011):

```python
        # ── Quick signal pre-scan (skip combo strategies) ──
        combo_config = ...  # this is computed later, so we need to check early
```

Actually, looking at the code flow more carefully — the combo_config detection is at line 1023. The pre-scan should only apply to non-combo strategies. Add the check right after `combo_config = self._extract_combo_config(strat)` (line 1023):

```python
        if not combo_config and stock_data:
            if not self._quick_signal_check(strat, stock_data):
                strat.status = "invalid"
                strat.error_message = "预扫描: 100只股票×60天无任何买入信号"
                strat.score = 0.0
                self.db.commit()
                logger.info("Pre-scan: zero signals for %s, marking invalid", strat.name)
                return
```

**Step 3: Verify the change compiles**

Run:
```bash
cd /Users/allenqiang/stockagent && /Users/allenqiang/stockagent/venv/bin/python -c "from api.services.ai_lab_engine import AILabEngine; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/ai_lab_engine.py
git commit -m "feat(lab): add zero-trade pre-scan before full backtest (P4)

Sample 100 stocks × 60 days and check for any buy signal before
running the full 5000-stock backtest. Strategies with zero signals
are marked invalid immediately, saving ~5 minutes per strategy."
```

---

### Task 4: P21 — DeepSeek Few-Shot Examples for New Condition Types

**Files:**
- Modify: `api/services/deepseek_client.py:14-145` (system prompt template)

**Step 1: Add Example Strategy D using new condition types**

In `api/services/deepseek_client.py`, the `_SYSTEM_PROMPT_TEMPLATE` string. Find the section after the condition format docs (around line 72, before `## 输出格式`). Add a complete example strategy using new types:

```python
### 完整示例 — 使用新条件类型

示例策略D — N日新低反弹（使用 lookback_min + pct_change）:
```json
{{
  "name": "N日新低反弹_保守版D",
  "description": "20日新低后3日反弹超2%，KDJ超卖确认",
  "buy_conditions": [
    {{"field": "close", "compare_type": "lookback_min", "lookback_field": "close", "lookback_n": 20, "operator": "<=", "label": "创20日新低"}},
    {{"field": "close", "compare_type": "pct_change", "lookback_n": 3, "operator": ">", "compare_value": 2.0, "label": "3日涨幅>2%"}},
    {{"field": "KDJ_K", "compare_type": "value", "compare_value": 25, "operator": "<", "params": {{"fastk": 9, "slowk": 3, "slowd": 3}}, "label": "KDJ超卖"}}
  ],
  "sell_conditions": [
    {{"field": "close", "compare_type": "lookback_max", "lookback_field": "close", "lookback_n": 10, "operator": ">=", "label": "创10日新高止盈"}}
  ],
  "exit_config": {{"stop_loss_pct": -8.0, "take_profit_pct": 15.0, "max_hold_days": 20}}
}}
```
```

Note: All `{` and `}` in JSON examples must be doubled (`{{` and `}}`) because the template uses Python `.format()`.

**Step 2: Add keyword-triggered mandatory instruction for new types**

In `api/services/deepseek_client.py`, find the `generate_strategies()` method. Before building the user prompt, add keyword detection:

Find where `source_text` is used to build the user prompt. Add this logic:

```python
# Keyword detection for new condition types
new_type_keywords = ["N日新低", "N日新高", "连续涨", "连续跌", "连涨", "连跌",
                     "偏离度", "偏离", "涨跌幅", "涨幅", "跌幅", "突破"]
force_new_types = any(kw in source_text for kw in new_type_keywords)

if force_new_types:
    source_text += "\n\n【强制要求】此主题涉及新条件类型，至少2个策略必须使用 lookback_min/lookback_max/pct_change/consecutive 中的至少一种，而非仅使用 value/field 基础类型。参考示例策略D的格式。"
```

**Step 3: Verify the change compiles**

Run:
```bash
cd /Users/allenqiang/stockagent && /Users/allenqiang/stockagent/venv/bin/python -c "from api.services.deepseek_client import DeepSeekClient; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/deepseek_client.py
git commit -m "feat(deepseek): add few-shot example for new condition types (P21)

Add Example Strategy D using lookback_min + pct_change in the system
prompt. Add keyword detection to force new type usage when source_text
mentions patterns like N日新低, 连续涨跌, 偏离度, 涨跌幅."
```

---

### Task 5: P22 — Field Comparison Auto-Correction in Validation

**Files:**
- Modify: `api/services/ai_lab_engine.py:909-923` (field comparison validation in `_validate_conditions()`)

**Step 1: Add auto-correction logic for reversed field comparisons**

In `api/services/ai_lab_engine.py`, in the `_validate_conditions()` method, find the `elif ctype == "field":` block (line 909). Replace lines 909-920 with enhanced logic:

```python
            elif ctype == "field":
                cf = cond.get("compare_field", "")
                field_val = cond.get("field", "")

                # ── Auto-swap: if field is an indicator and compare_field is "close", swap them ──
                price_fields = {"close", "open", "high", "low", "volume"}
                if field_val not in price_fields and cf in price_fields:
                    # DeepSeek often reverses: e.g. {"field": "MA", "compare_field": "close"}
                    # Should be: {"field": "close", "compare_field": "MA"}
                    cond["field"], cond["compare_field"] = cf, field_val
                    # Also swap params
                    old_params = cond.get("params")
                    old_cp = cond.get("compare_params")
                    if old_params:
                        cond["compare_params"] = old_params
                    if old_cp:
                        cond["params"] = old_cp
                    else:
                        cond.pop("params", None)
                    # Flip operator direction
                    op = cond.get("operator", ">")
                    flip = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
                    cond["operator"] = flip.get(op, op)
                    errors.append(f"自动修正: {field_val} vs {cf} → 交换为 {cf} vs {field_val}")
                    field_val, cf = cf, field_val

                if not get_field_group(cf) and not is_extended_indicator(cf):
                    errors.append(f"不支持的比较指标: {cf}")
                    continue

                # ── Auto-fill default params if compare_field needs them ──
                if not cond.get("compare_params"):
                    from api.services.indicator_registry import get_extended_field_group, EXTENDED_INDICATORS
                    ext_group = get_extended_field_group(cf)
                    if ext_group:
                        meta = EXTENDED_INDICATORS[ext_group]
                        if meta["params"]:
                            defaults = {k: v["default"] for k, v in meta["params"].items()}
                            cond["compare_params"] = defaults
                            errors.append(f"自动填充 {cf} 默认参数: {defaults}")
                    else:
                        # Built-in indicators: check if field group needs params
                        group = get_field_group(cf)
                        if group and group not in price_fields:
                            # Common defaults for built-in indicators
                            builtin_defaults = {
                                "MA": {"period": 20},
                                "EMA": {"period": 20},
                                "PSAR": {"step": 0.02, "max_step": 0.2},
                                "BOLL_upper": {"length": 20, "std": 2.0},
                                "BOLL_middle": {"length": 20, "std": 2.0},
                                "BOLL_lower": {"length": 20, "std": 2.0},
                            }
                            if cf in builtin_defaults and not cond.get("compare_params"):
                                cond["compare_params"] = builtin_defaults[cf]
                                errors.append(f"自动填充 {cf} 默认参数: {builtin_defaults[cf]}")

                # ── Same-field comparison detection ──
                cp = cond.get("compare_params") or {}
                p = cond.get("params") or {}
                if cf == field_val and self._params_equal(p, cp):
                    errors.append(f"移除无效条件: {field_val} 与自身比较")
                    continue
```

**Step 2: Add field comparison templates to the prompt**

In `api/services/deepseek_client.py`, in the `_SYSTEM_PROMPT_TEMPLATE`, find rule #13 about field comparison (around line 139). Replace it with clearer templates:

```python
13. **field 比较固定模板** — 使用 compare_type="field" 时，必须严格遵循以下模板:
    - close > PSAR: {{"field":"close", "compare_type":"field", "operator":">", "compare_field":"PSAR", "compare_params":{{"step":0.02,"max_step":0.2}}, "label":"站上SAR"}}
    - close > MA_20: {{"field":"close", "compare_type":"field", "operator":">", "compare_field":"MA", "compare_params":{{"period":20}}, "label":"站上MA20"}}
    - close < BOLL_lower: {{"field":"close", "compare_type":"field", "operator":"<", "compare_field":"BOLL_lower", "compare_params":{{"length":20,"std":2.0}}, "label":"跌破布林下轨"}}
    注意: field 字段必须是 close/open/high/low 等价格字段，compare_field 是指标字段。不要反过来写。
```

**Step 3: Verify the change compiles**

Run:
```bash
cd /Users/allenqiang/stockagent && /Users/allenqiang/stockagent/venv/bin/python -c "from api.services.ai_lab_engine import AILabEngine; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/ai_lab_engine.py api/services/deepseek_client.py
git commit -m "feat(lab): auto-correct reversed field comparisons (P22)

Add 3-layer fix for DeepSeek field comparison errors:
1. Auto-swap when field is indicator and compare_field is price
2. Auto-fill default params when compare_params is empty
3. Add fixed templates in prompt to prevent reversed operands"
```

---

### Task 6: Update Known Issues Status

**Files:**
- Modify: `docs/lab-experiment-analysis.md` — update P4/P14/P18/P21/P22 status to 已修复

**Step 1: Update the known issues table**

Change the status of P4, P14, P18, P21, P22 from their current status to `已修复`.

**Step 2: Commit**

```bash
git add docs/lab-experiment-analysis.md
git commit -m "docs: mark P4/P14/P18/P21/P22 as resolved in lab analysis"
```
