# AI Strategy Selection Design

**Date**: 2026-02-22
**Status**: Approved

## Problem

The system has 1029 enabled strategies (22 families × parameter variants). All strategies run against all stocks every day, but:
1. Most strategies don't trigger for most stocks — wasted computation
2. Alpha consensus score is diluted: 2 triggers / 1029 total × 40 ≈ 0
3. AI can't differentiate which strategies are appropriate for current market conditions
4. AI report narratively "selects strategies" but doesn't actually control which ones run

## Solution Overview

Add an AI strategy selection step before signal generation. Claude assesses market conditions and picks 3-5 strategy families. Only the best variant from each selected family runs signal generation.

```
Step 0: Check trading day
Step 1: Sync daily prices
Step 2: Execute pending trade plans (needs OHLCV)
Step 3: AI strategy selection (NEW)
  3a: Build 22-row family summary table
  3b: Claude selects 3-5 families
  3c: Map to best variant IDs per family
Step 4: Generate signals (selected strategies only)
Step 5: AI analysis (existing, unchanged)
```

## Strategy Family Summary

Dynamic computation (no new table). Groups 1029 strategies into ~22 families by stripping parameter suffixes (_SL, _TP, _MHD, _调参, etc.). Each family represented by its highest-score variant.

### Functions

```python
# New file or in bot_trading_engine.py

def build_family_summary(db) -> list[dict]:
    """Build family-level summary for AI selection."""
    # Returns ~22 rows:
    # {family, best_id, variants_count, score,
    #  total_return_pct, max_drawdown_pct,
    #  bull_avg_pnl, bear_avg_pnl, range_avg_pnl}

def select_strategies_by_families(db, family_names: list[str]) -> list[int]:
    """Map AI-selected family names to best strategy IDs (one per family)."""
```

### AI Input Example (~500 tokens)

```
族名                    | score | 收益    | 回撤  | 牛市  | 熊市  | 震荡  | 变体
全指标综合_中性版C       | 0.825 | +90.5% | 12.4% | 2.44 | 1.18 | 0.41 | 223
PSAR趋势动量_保守版A    | 0.818 | +133%  | 8.5%  | 1.79 | 0.52 | 0.40 | 228
UltimateOsc_中性版C     | 0.786 | +47.0% | 3.3%  | 2.24 | 0.25 | 0.94 | 148
...
```

## Claude Strategy Selection Call

### System Prompt

```
你是 StockAgent 的策略选择引擎。根据当前市场环境，从策略族中选择最适合的 3-5 个。

可用 API：
- GET /api/news/sentiment/latest — 市场情绪
- GET /api/market/quote?code=000001 — 上证指数实时行情
- GET /api/bot/portfolio — 当前持仓

以下是策略族摘要表（regime 列: 牛市/熊市/震荡下的平均每笔盈亏%）：
{family_table}

选择规则：
1. 判断当前市场环境（牛市/熊市/震荡/转换期）
2. 优先选 regime 表现匹配当前环境的族
3. 如有持仓，确保至少 1 个族对持仓股的卖出信号覆盖好
4. 选 3-5 个族，平衡进攻性和防御性

返回 JSON：
{
  "market_assessment": "bull|bear|ranging|transition",
  "selected_families": ["族名1", "族名2", ...],
  "reasoning": "选择理由（1-2句）"
}
```

### Parameters

- Model: opus (same as analysis)
- No max_turns or max_budget limits
- Permission mode: bypassPermissions

### Fallback

If Claude call fails, times out, or returns unparseable result → fallback to top 5 families by score. Never blocks the pipeline.

## Signal Generation Changes

### signal_engine.py

`generate_signals_stream` gains `strategy_ids` parameter:

```python
def generate_signals_stream(
    self,
    trade_date: str,
    stock_codes: Optional[list[str]] = None,
    strategy_ids: Optional[list[int]] = None,
) -> Generator[str, None, None]:
    query = self.db.query(Strategy).filter(Strategy.enabled.is_(True))
    if strategy_ids:
        query = query.filter(Strategy.id.in_(strategy_ids))
    strategies = query.all()
```

### Alpha Consensus Fix

With 5 strategies instead of 1029, consensus naturally becomes meaningful:
- 2/5 × 40 = 16 points (useful signal)
- vs 2/1029 × 40 ≈ 0.08 (noise)

No formula change needed — just fewer total strategies.

## AI Analysis Prompt Update

Add context to the analysis system prompt:

```
注意：今日信号是基于 AI 策略选择引擎筛选的策略生成的，不是全部策略。
```

Also require `alpha_score` pass-through from signal data (already done).

## Edge Cases

| Scenario | Handling |
|----------|----------|
| AI selects non-existent family name | Ignore, use only matched; if all invalid → fallback |
| AI returns 0 families | Fallback to score top 5 |
| AI returns > 5 families | Allow (no truncation) |
| No backtest_summary data | Skip selection, run all strategies (backward compat) |
| AI call timeout | Fallback to score top 5, continue |
| Non-trading day | Skip Steps 1-4, only run Step 5 (AI analysis) |

## Unchanged

- Frontend: no changes
- Strategy management page: no changes
- Manual signal generation (`POST /api/signals/generate`): runs all strategies
- Manual AI analysis (`POST /api/ai/analyze`): goes through strategy selection
- New APIs: none needed
