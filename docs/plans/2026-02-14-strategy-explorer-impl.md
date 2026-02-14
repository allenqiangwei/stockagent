# Strategy Explorer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create the `/explore-strategies` skill that implements an iterative experiment-insight-plan-reexperiment loop for discovering profitable trading strategies across market regimes.

**Architecture:** A Claude Code skill (`.claude/skills/explore-strategies.md`) drives the entire flow via existing APIs. One minor backend change adds custom label support to the promote endpoint. The `docs/lab-experiment-analysis.md` file is restructured to serve as persistent memory with an exploration status table.

**Tech Stack:** Claude Code skill (markdown prompt), FastAPI (one-line endpoint change), existing AI Lab APIs.

---

### Task 1: Add custom label support to promote endpoint

**Files:**
- Modify: `api/routers/ai_lab.py:276-311` (promote_strategy function)

**Step 1: Modify the promote endpoint to accept an optional label query param**

Change the `promote_strategy` function signature and the `Strategy` name line:

```python
@router.post("/strategies/{strategy_id}/promote")
def promote_strategy(
    strategy_id: int,
    label: str = Query("[AI]", description="Name prefix label, e.g. [AI], [AI-牛市]"),
    db: Session = Depends(get_db),
):
    """Copy an experiment strategy to the formal strategy library."""
    from api.models.strategy import Strategy

    exp_strat = db.query(ExperimentStrategy).get(strategy_id)
    if not exp_strat:
        raise HTTPException(404, "Experiment strategy not found")

    if exp_strat.promoted and exp_strat.promoted_strategy_id:
        existing = db.query(Strategy).filter(
            Strategy.id == exp_strat.promoted_strategy_id
        ).first()
        if existing:
            return {"message": "Already promoted", "strategy_id": exp_strat.promoted_strategy_id}

    formal = Strategy(
        name=f"{label} {exp_strat.name}",
        description=exp_strat.description,
        rules=[],
        buy_conditions=exp_strat.buy_conditions,
        sell_conditions=exp_strat.sell_conditions,
        exit_config=exp_strat.exit_config,
        weight=0.5,
        enabled=False,
    )
    db.add(formal)
    db.flush()

    exp_strat.promoted = True
    exp_strat.promoted_strategy_id = formal.id
    db.commit()

    return {"message": "Promoted", "strategy_id": formal.id}
```

Note: `Query` is already imported at the top of the file (used by other endpoints).

**Step 2: Verify the change works**

Run: `NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/docs | grep -c promote`
Expected: The OpenAPI docs include the updated promote endpoint (nonzero count confirms server is running with the change).

**Step 3: Commit**

```bash
git add api/routers/ai_lab.py
git commit -m "feat(lab): add optional label param to promote endpoint"
```

---

### Task 2: Restructure lab-experiment-analysis.md

**Files:**
- Modify: `docs/lab-experiment-analysis.md` (full rewrite to new structure)

The current file is 455 lines. Restructure it to the design's target format while preserving all valuable data. The new structure puts the most actionable sections first.

**Step 1: Rewrite the file with new structure**

The new file must have these sections in order:

```markdown
# AI 策略实验室 — 实验结果分析

> 更新时间: 2026-02-14 | 总实验: 82 | 总策略: 656 | 盈利: 63 (10.8%)

## 核心洞察

[Keep existing 8 core insights as-is — they are current and valuable]

## 探索状态

| 优先级 | 方向 | 子主题 | 状态 | 实验数 | 盈利率 | 最佳收益 | 备注 |
|--------|------|--------|------|--------|--------|----------|------|
| P1 | 震荡市 | KDJ短周期+震荡专属参数 | 待探索 | 0 | — | — | KDJ(6,3,3)震荡市最佳 |
| P1 | 震荡市 | VWAP均值回归 | 待探索 | 0 | — | — | VWAP盈利率30% |
| P1 | 震荡市 | BOLL收窄+KDJ | 待探索 | 0 | — | — | 布林带收窄=低波动 |
| P1 | 震荡市 | CMF资金流反转 | 待探索 | 0 | — | — | CMF 21%盈利率 |
| P2 | 指标组合 | VWAP+KDJ | 待探索 | 0 | — | — | 两个最有效指标 |
| P2 | 指标组合 | BOLL_lower+MACD | 待探索 | 0 | — | — | BOLL_lower最佳+59% |
| P2 | 指标组合 | CMF+KDJ金叉 | 待探索 | 0 | — | — | 资金流确认 |
| P2 | 指标组合 | EMA+ATR止损 | 待探索 | 0 | — | — | KDJ+EMA 43%盈利率 |
| P3 | 策略组合 | 信号投票/加权 | 待解锁 | 0 | — | — | 需后端新功能 |

## Auto-Promote 记录

| 日期 | 策略名 | 标签 | 评分 | 收益 | 回撤 | Promote标准 |
|------|--------|------|------|------|------|------------|
| (暂无) | | | | | | |

## 最佳策略排行 (Top 15)

[Keep existing Top 15 table]

## 全阶段盈利策略

[Keep existing 5 all-regime-profitable strategies table]

## 各市场阶段最优

[Keep existing bull/bear/sideways best tables — compressed to top 3 each]

## 历史实验摘要

### 第一轮~第三轮 (综合实验)
- 第一轮: 4模板32策略, 盈利2(8.7%), 最佳+11.1%
- 第二轮: 15实验120策略, 盈利9(19.6%), 数据缺陷导致回撤虚高
- 第三轮: 15实验120策略, 盈利6(11.8%), 数据修复验证成功, KDJ最佳+37.1%

### 第四轮: KDJ深挖 (67实验536策略)
- 盈利26/258(10.1%), 最佳+60.7%, >30%收益2个
- KDJ+EMA最佳组合(43%盈利率), 短周期(6,3,3)优于默认
- 5个策略全阶段盈利

### P0修复: 扩展指标收集Bug
- 292零交易策略重跑, 273修复成功(93.5%), 新增31盈利策略
- 最佳: 全指标综合_中性版C(+58.5%, score 0.78)
- VWAP盈利率最高(30%), DPO完全无效(0%)

## 各扩展指标表现

[Keep existing extended indicator performance table — it's compact and valuable]

## 已知问题

- P0~P6: 全部已修复 (详见 git history)
- P4 零交易(~50%): 持续优化中
- P3 策略组合: 待实现
```

**Step 2: Write the restructured file**

Combine existing valuable data into the new structure. Remove:
- Detailed per-round comparison tables (replaced by summary lines)
- Long "发现" section (absorbed into 核心洞察)
- Verbose P0-P6 issue descriptions (compressed to one-line summaries)
- Duplicate "历史对比" section

Keep:
- Core insights (8 items)
- Top 15 + all-regime tables
- Per-market-stage best (top 3 each)
- Extended indicator performance table
- New exploration status table

**Step 3: Verify line count**

Run: `wc -l docs/lab-experiment-analysis.md`
Expected: < 300 lines (target is < 500, but the restructure should compress significantly)

**Step 4: Commit**

```bash
git add docs/lab-experiment-analysis.md
git commit -m "refactor: restructure lab analysis as explorer memory with exploration status"
```

---

### Task 3: Create the explore-strategies skill

**Files:**
- Create: `.claude/skills/explore-strategies.md`

**Step 1: Write the skill file**

The skill file is a markdown prompt that instructs Claude how to execute the exploration loop. It must include:

1. **Metadata header** — skill name, description, trigger
2. **Memory loading instructions** — read `docs/lab-experiment-analysis.md`
3. **Data querying instructions** — which API calls to make via `curl`
4. **Analysis framework** — how to identify unexplored directions, evaluate results
5. **Experiment creation format** — exact JSON body for `POST /api/lab/experiments`
6. **Auto-promote rules** — Standard A and Standard B with exact thresholds
7. **Memory update instructions** — how to edit the analysis file
8. **Mode handling** — semi-auto (default) vs auto (with `auto` argument)

Key content for the skill:

```markdown
---
name: explore-strategies
description: Iterative strategy discovery — analyze experiments, plan new ones, auto-promote winners
---

# Strategy Explorer

You are a quantitative strategy researcher for the Chinese A-share market.
Your job is to systematically discover profitable strategies through iterative experimentation.

## Mode

- Default (no args): Semi-auto — present plan, wait for approval, then execute
- `auto` argument: Full-auto — execute without approval, loop until done (max 5 rounds)

## Step 1: Load Memory

Read `docs/lab-experiment-analysis.md`. Extract:
- **核心洞察**: What we already know works/doesn't work
- **探索状态**: Which directions have been explored, their results
- **最佳策略**: Current best strategies and their characteristics

## Step 2: Query Latest Data

Use Bash with curl to query the running backend (port 8050):

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/lab/experiments?page=1&size=5
```

Check if there are recent experiments not yet analyzed.

Also query current market regime:
```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/regimes?start_date=2023-02-14&end_date=2026-02-14"
```

## Step 3: Analyze & Plan

Look at the 探索状态 table. Pick 1-3 topics from the highest-priority unexplored direction.

Priority rules:
1. P1 (震荡市) before P2 (指标组合) before P3 (策略组合)
2. Within same priority, pick highest expected profitability
3. If a direction had < 5% profitability for 2 consecutive rounds, skip it
4. If all directions explored, revisit directions with > 15% profitability for parameter tuning

For each topic, prepare:
- `theme`: Descriptive name (e.g. "VWAP均值回归+KDJ确认")
- `source_text`: Detailed description for DeepSeek, focusing on the specific hypothesis

## Step 4: Present Plan (semi-auto) or Execute (auto)

**Semi-auto**: Show the plan as a table and ask for approval:

"本轮探索计划："
| # | 主题 | 方向 | 假设 |
...
"确认执行？可以调整主题或跳过某个。"

**Auto**: Skip to Step 5.

## Step 5: Execute Experiments

For each approved topic, create an experiment:

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/lab/experiments \
  -H "Content-Type: application/json" \
  -d '{"theme":"...","source_type":"custom","source_text":"...","initial_capital":100000,"max_positions":10,"max_position_pct":30}'
```

This returns an SSE stream. The experiment runs in the background.
Poll for completion:

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/lab/experiments/{id}
```

Wait until `status` is `done` or `failed`. Check every 30 seconds.
Each experiment takes 3-10 minutes depending on strategy count.

## Step 6: Analyze Results

For each completed experiment, read the strategies:

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/lab/experiments/{id}
```

Calculate:
- Profitability rate: profitable / (total - zero_trade)
- Best strategy: highest score
- Per-regime performance: parse regime_stats from each strategy
- Compare with historical best

Generate insights:
- New findings vs existing core insights
- Whether this direction is worth further exploration
- Specific parameter combinations that worked

## Step 7: Auto-Promote

Check each strategy against promote criteria:

**Standard A (高评分)**:
- score >= 0.65 AND total_return_pct > 10 AND max_drawdown_pct < 30 AND total_trades >= 50

**Standard B (市场阶段冠军)**:
- Has highest profit in bull/bear/sideways among this round's strategies
- That regime's profit > 0
- total_return_pct > 0

For qualifying strategies, promote:

Standard A:
```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/lab/strategies/{id}/promote?label=%5BAI%5D"
```

Standard B (example for bull market champion):
```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/lab/strategies/{id}/promote?label=%5BAI-%E7%89%9B%E5%B8%82%5D"
```

## Step 8: Update Memory

Edit `docs/lab-experiment-analysis.md`:

1. Update the header line (experiment count, strategy count, profitability)
2. Update 探索状态 table: change status to "已探索" or "探索中", fill in metrics
3. Add new insights to 核心洞察 if discovered
4. Add promote records to Auto-Promote 记录 table
5. If 核心洞察 exceeds 10 items, merge or remove the least impactful ones

Cleanup:
- Keep file under 500 lines
- Compress old experiment details into summary lines
- Remove directions with 0% profitability after 2+ rounds from detailed sections

## Step 9: Output Summary

Present results:

"## 本轮探索结果

**实验**: N 个主题, M 个策略生成, K 个盈利
**最佳策略**: [name] (收益 +X%, 评分 Y)
**新洞察**: [bullet points]
**Auto-Promote**: N 个策略已添加到策略库
**下一步建议**: [what to explore next]"

**Auto mode**: Return to Step 2 unless:
- All directions explored with no new unexplored topics
- 2 consecutive rounds with 0 profitable strategies
- Reached 5-round limit for this session
```

**Step 2: Verify the skill file is valid**

Run: `ls -la .claude/skills/explore-strategies.md`
Expected: File exists with non-zero size

**Step 3: Commit**

```bash
git add .claude/skills/explore-strategies.md
git commit -m "feat: create /explore-strategies skill for iterative strategy discovery"
```

---

### Task 4: End-to-end verification

**Step 1: Verify backend is running with the promote change**

Restart the backend if needed:
```bash
kill $(lsof -ti:8050) 2>/dev/null; sleep 1
source venv/bin/activate
NO_PROXY=localhost,127.0.0.1 uvicorn api.main:app --host 0.0.0.0 --port 8050 &
sleep 5
```

**Step 2: Verify the promote endpoint accepts the label param**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/openapi.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
params=spec['paths']['/api/lab/strategies/{strategy_id}/promote']['post'].get('parameters',[])
labels=[p['name'] for p in params if p['name']=='label']
print('label param found' if labels else 'MISSING label param')
"
```
Expected: `label param found`

**Step 3: Verify the skill is discoverable**

The skill should appear in `/help` or be invocable via `/explore-strategies` in Claude Code.

**Step 4: Verify lab-experiment-analysis.md has the new structure**

```bash
grep -c "## 探索状态" docs/lab-experiment-analysis.md
grep -c "## Auto-Promote 记录" docs/lab-experiment-analysis.md
```
Expected: Both return `1`

**Step 5: Final commit with all changes**

If any uncommitted changes remain:
```bash
git add -A
git commit -m "chore: strategy explorer implementation complete"
```
