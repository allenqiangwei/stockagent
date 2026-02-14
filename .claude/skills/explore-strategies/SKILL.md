---
name: explore-strategies
description: Iterative strategy discovery — analyze experiments, plan new ones, auto-promote winners. Use /explore-strategies for semi-auto, /explore-strategies auto for full-auto.
---

# Strategy Explorer

You are a quantitative strategy researcher for the Chinese A-share market. Your job is to systematically discover profitable strategies through iterative experimentation using the AI Lab system.

## Mode

- **Default** (no args): Semi-auto — present plan, wait for user approval, then execute
- **`auto`** argument: Full-auto — execute without approval, loop until done (max 5 rounds per session)

## Step 1: Load Memory

Read `docs/lab-experiment-analysis.md`. Extract:
- **核心洞察**: What works and doesn't work in A-share markets
- **探索状态**: Which directions have been explored, their results, what's next
- **最佳策略**: Current top strategies and their characteristics
- **Auto-Promote 记录**: What has already been promoted

## Step 2: Query Latest Data

Query the running backend (port 8050) for the latest state:

```bash
# Recent experiments
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments?page=1&size=10"

# Current market regime (last 3 years)
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/regimes?start_date=2023-02-14&end_date=2026-02-14"
```

Check if there are recent experiments whose results haven't been analyzed yet. If so, analyze them first before planning new ones.

## Step 3: Analyze & Plan

Look at the **探索状态** table. Pick 1-3 topics from the highest-priority unexplored direction.

**Priority rules:**
1. P1 (震荡市) before P2 (指标组合) before P3 (策略组合)
2. Within same priority, pick highest expected profitability based on existing data
3. If a direction had < 5% profitability for 2 consecutive rounds, mark it "已弃" and skip
4. If all P1 explored, move to P2. If all done, revisit directions with > 15% profitability for parameter tuning
5. You may propose NEW sub-topics not in the table if your analysis suggests a promising direction

For each topic, prepare:
- `theme`: Descriptive Chinese name (e.g. "VWAP均值回归+KDJ确认震荡市策略")
- `source_text`: Detailed strategy description for DeepSeek. Be specific about:
  - Which indicators to use and their parameters
  - The market hypothesis being tested
  - Target market regime (震荡/牛市/熊市)
  - Desired holding period and risk tolerance
  - Key: keep to 2 indicators max, 3-4 buy conditions

## Step 4: Present Plan (semi-auto only)

Show the plan in a clear table:

```
本轮探索计划：

| # | 主题 | 方向 | 假设 |
|---|------|------|------|
| 1 | ... | 震荡市 P1 | ... |
| 2 | ... | 指标组合 P2 | ... |

确认执行？你可以调整主题、增减数量、或跳过某个。
```

In **auto mode**, skip this step and proceed directly.

## Step 5: Execute Experiments

For each approved topic, create an experiment via API:

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/lab/experiments \
  -H "Content-Type: application/json" \
  -d '{"theme":"主题名","source_type":"custom","source_text":"详细描述...","initial_capital":100000,"max_positions":10,"max_position_pct":30}'
```

This returns an SSE stream. The experiment runs in the background (3-10 minutes each).

Poll for completion every 30 seconds:
```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments/{id}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])"
```

Wait until status is `done` or `failed`.

## Step 6: Analyze Results

For each completed experiment, fetch full strategy data:
```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments/{id}"
```

Calculate and report:
- **Profitability rate**: profitable / (total - zero_trade - failed)
- **Best strategy**: name, score, return%, drawdown%
- **Per-regime performance**: parse `regime_stats` from each strategy with status=done
- **Comparison**: How does this compare with existing best strategies?

Generate insights — specifically look for:
- New findings that contradict or extend existing core insights
- Parameter combinations that work well in specific market regimes
- Whether this direction is worth further exploration or should be marked "已弃"

## Step 7: Auto-Promote

Check each strategy with `status=done` against promote criteria:

**Standard A (高评分)** — ALL conditions must be met:
- `score >= 0.65`
- `total_return_pct > 10`
- `max_drawdown_pct < 30` (absolute value)
- `total_trades >= 50`

**Standard B (市场阶段冠军)** — ALL conditions must be met:
- Has highest profit in a specific regime (bull/bear/sideways) among this round's strategies
- That regime's profit > 0 (from `regime_stats`)
- `total_return_pct > 0`

Promote qualifying strategies:

```bash
# Standard A — default [AI] label
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/lab/strategies/{id}/promote?label=%5BAI%5D"

# Standard B — market regime label
# Bull: [AI-牛市]
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/lab/strategies/{id}/promote?label=%5BAI-%E7%89%9B%E5%B8%82%5D"
# Bear: [AI-熊市]
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/lab/strategies/{id}/promote?label=%5BAI-%E7%86%8A%E5%B8%82%5D"
# Sideways: [AI-震荡]
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/lab/strategies/{id}/promote?label=%5BAI-%E9%9C%87%E8%8D%A1%5D"
```

A strategy can be promoted under multiple standards (e.g. both Standard A and Standard B for bull market).

## Step 8: Update Memory

Edit `docs/lab-experiment-analysis.md`:

1. **Header**: Update experiment count, strategy count, profitability numbers
2. **探索状态**: Change topic status from "待探索" to "已探索", fill in 盈利率 and 最佳收益
3. **核心洞察**: Add new insights if discovered (keep total <= 12, merge or remove least impactful)
4. **Auto-Promote 记录**: Add promoted strategies with date, label, metrics, standard
5. **最佳策略 Top 15**: Update if any new strategy ranks higher
6. **全阶段盈利策略**: Add if a new strategy profits in all regimes
7. **各市场阶段最优**: Update top 3 per regime if improved

**Cleanup rules:**
- File must stay under 500 lines
- Don't add detailed per-strategy listings for non-profitable strategies
- If a direction is marked "已弃", keep only the summary line in 探索状态

## Step 9: Output Summary

Present a concise summary:

```
## 本轮探索结果

**实验**: N 个主题, M 个策略生成, K 个盈利 (X%)
**最佳策略**: [name] — 收益 +X%, 评分 Y, 回撤 Z%
**新洞察**:
- [bullet points of new findings]
**Auto-Promote**: N 个策略已添加到策略库
  - [list promoted strategies with labels]
**下一步建议**: [what to explore next based on updated 探索状态]
```

## Auto Mode Loop

In auto mode, after Step 9:
- **Continue** if: there are unexplored directions AND last round had >= 1 profitable strategy
- **Stop** if:
  - All directions explored (no more "待探索" in 探索状态)
  - 2 consecutive rounds with 0 profitable strategies
  - Reached 5-round limit
  - Any experiment failed (investigate before continuing)

When stopping, output a final session summary with total experiments run, strategies found, and promote actions taken.
