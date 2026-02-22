# Memory System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Zettelkasten-style atomic note memory system with Pinecone semantic retrieval, migrating from the current flat MEMORY.md.

**Architecture:** Markdown files with YAML frontmatter organized in `semantic/`, `episodic/`, `procedural/` directories under the Claude auto-memory path. Pinecone index `stockagent-memory` provides semantic search. A sync script bridges files to Pinecone. MEMORY.md becomes a lean navigation index.

**Tech Stack:** Markdown + YAML frontmatter, Pinecone (free tier, `multilingual-e5-large` embeddings), Python sync script, Claude Code MCP tools.

**Memory base path:** `/Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/`

---

### Task 1: Create Directory Structure

**Files:**
- Create: `memory/semantic/` directory
- Create: `memory/episodic/experiments/` directory
- Create: `memory/episodic/decisions/` directory
- Create: `memory/episodic/bugs/` directory
- Create: `memory/procedural/` directory
- Create: `memory/meta/` directory

**Step 1: Create all directories**

```bash
cd /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory
mkdir -p semantic episodic/experiments episodic/decisions episodic/bugs procedural meta
```

**Step 2: Verify structure**

```bash
find /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory -type d | sort
```

Expected:
```
memory/
memory/episodic
memory/episodic/bugs
memory/episodic/decisions
memory/episodic/experiments
memory/meta
memory/procedural
memory/semantic
```

---

### Task 2: Migrate Semantic Knowledge — architecture.md

**Files:**
- Create: `memory/semantic/architecture.md`
- Source: Current `MEMORY.md` sections "Architecture (v2)", "New Frontend", "New API Backend", "Key Patterns"

**Step 1: Create architecture.md**

Extract from MEMORY.md lines covering architecture, frontend, backend, and key patterns into:

```markdown
---
id: sem-architecture
type: semantic/architecture
tags: [architecture, nextjs, fastapi, sqlalchemy, frontend, backend]
created: 2026-02-08
relevance: high
related: [sem-api-patterns, sem-environment]
---

# System Architecture

## Stack
- **Frontend**: Next.js 16 + TradingView Lightweight Charts v5 + shadcn/ui (dark theme) at `web/`
- **Backend**: FastAPI + SQLAlchemy 2.0 + Pydantic v2 at `api/`
- **Legacy frontend**: Streamlit dashboard at `src/dashboard/` (superseded)
- **Data sources**: AkShare (primary, free), TuShare (fallback, token)
- **DB**: SQLite at `data/stockagent.db`
  - Legacy: `src/data_storage/database.py` (raw SQL)
  - New: `api/models/` (SQLAlchemy ORM, `_v2` suffix tables)
- **Signals**: `src/signals/rule_engine.py` — reused by both old and new backend
- **Backtest**: `src/backtest/engine.py` — reused by `api/services/backtest_engine.py`

## Frontend (`web/`)
- Entry: `npm run dev` in `web/` -> port 3050, proxies `/api/*` to backend :8050
- State: Zustand (`lib/store.ts`) + TanStack Query (`hooks/use-queries.ts`)
- Pages: `/` (dashboard), `/market` (3-panel K-line), `/signals`, `/backtest`, `/strategies`, `/ai`
- Charts: `components/charts/kline-chart.tsx`, `indicator-chart.tsx`
- Dark theme forced: `<html className="dark">`, system fonts

## Backend (`api/`)
- Entry: `api/main.py` -> `uvicorn api.main:app --port 8050`
- Config: `api/config.py` loads from `config/config.yaml` + env vars
- Models: `api/models/{stock,strategy,signal,backtest,ai_lab,ai_analyst,market_regime}.py`
- Routers: market, stocks, strategies, signals, backtest, ai_lab, ai_analyst, config
- Services: data_collector, indicator_engine, signal_engine, backtest_engine, ai_lab_engine, claude_runner
- Tables: `stocks`, `daily_prices`, `watchlist`, `strategies`, `trading_signals_v2`, `action_signals_v2`, `backtest_runs_v2`, `backtest_trades_v2`

## Key Patterns
- FastAPI `get_db()` dependency yields SQLAlchemy session per request
- SQLite WAL mode + `check_same_thread=False` for concurrency
- `api/utils/network.py` no_proxy() context manager for data API calls
- Backtest uses SSE for progress streaming
- `src/` business logic reused, not duplicated
- Indicator query format: `MA:5,10,20,60|MACD:12,26,9|RSI:14`
- AI Chat: fire-and-forget + polling (Next.js route handler + claude-worker.ts)
```

---

### Task 3: Migrate Semantic Knowledge — library-gotchas.md

**Files:**
- Create: `memory/semantic/library-gotchas.md`
- Source: MEMORY.md "Library API Notes" section

**Step 1: Create library-gotchas.md**

```markdown
---
id: sem-library-gotchas
type: semantic/library
tags: [lightweight-charts, react-resizable-panels, google-fonts, api-gotchas]
created: 2026-02-08
relevance: high
related: [sem-architecture]
---

# Third-Party Library Gotchas

## lightweight-charts v5
- Use `chart.addSeries(CandlestickSeries, opts)` not `chart.addCandlestickSeries()`
- Markers via `createSeriesMarkers(series, markers)` not `series.setMarkers()`
- Don't use `autoSize: true` inside flex/resizable panels — use manual `ResizeObserver` + `chart.resize(w, h)`
- `setVisibleRange()` after `setData()` may silently fail — use `requestAnimationFrame` to defer
- Always add `disposedRef` guard for async callbacks
- No `Range` type export — define inline: `type TimeRange = { from: Time; to: Time }`

## react-resizable-panels v4
- Use `orientation="horizontal"` not `direction="horizontal"`
- CRITICAL: numeric `defaultSize={15}` = 15px! Use string `defaultSize="15%"` for percentages
- Dynamic children must use `<Fragment key>` not `<div key>`

## indicator-meta color key matching
- Empty string key `""` matches ALL subKeys via `startsWith("")`
- Guard: only match `""` when subKey starts with a digit

## Google Fonts
- Blocked by proxy — use system fonts instead
```

---

### Task 4: Migrate Semantic Knowledge — strategy-knowledge.md

**Files:**
- Create: `memory/semantic/strategy-knowledge.md`
- Source: MEMORY.md "Signal/Strategy System" + experiment insights summary

**Step 1: Create strategy-knowledge.md**

```markdown
---
id: sem-strategy-knowledge
type: semantic/strategy
tags: [strategy, KDJ, MACD, PSAR, rule-engine, signals, indicators]
created: 2026-02-15
relevance: high
related: [sem-architecture, exp-r01-kdj, exp-r16-grid-search]
---

# Strategy Knowledge Base

## Rule Engine (`src/signals/rule_engine.py`)
- Condition+action rules with indicator params
- Column naming: `RSI_14`, `MACD_hist_12_26_9`, `KDJ_K_9_3_3`, `MA_5`, `ADX_plus_di_14`
- P4 upgrade complete: 6 new compare_type (lookback_min/max, lookback_value, consecutive, pct_diff, pct_change)
- `check_reachability()` detects contradictory conditions
- DeepSeek does NOT use new compare_type — needs few-shot templates

## Proven Strategy Families (from 306 experiments, 1473 strategies)
- **Best overall**: PSAR+MACD+KDJ — score 0.825, +90.5%, dd 12.4%
- **Best return**: PSAR趋势动量 — score 0.802, +99.6%, dd 12.2%
- **Lowest dd**: 全指标综合_保守版B — score 0.744, +26.4%, dd 3.2%
- **Golden take-profit**: TP14 is universally optimal
- **SL7 > SL5**: Wider stop-loss improves returns for 全指标综合

## What Does NOT Work
- Pure MA/EMA strategies: 0 profit across 4 rounds
- CMF indicator: almost always negative in A-shares
- 3+ indicator combinations: almost all fail
- DeepSeek generating new strategies: 87.5% invalid
- Same-type indicator stacking (STOCH+KDJ, ULTOSC+KDJ): dead end

## What Works
- KDJ is the most effective single indicator for A-shares
- KDJ+MACD is the best dual indicator combo
- PSAR+MACD+KDJ is the best triple combo (different types: trend+momentum+oversold)
- Grid search success rate >90%, all top strategies from grid search
- Short holding + fast turnover = key to all-regime profitability

## Key Numbers
- 306 valid experiments (ID up to 318), 1473 strategies
- done=1022, profitable=244 (23.9%), Standard A=118
- 21 rounds of exploration, parameter space fully exhausted
```

---

### Task 5: Migrate Semantic Knowledge — environment.md + design-docs.md

**Files:**
- Create: `memory/semantic/environment.md`
- Create: `memory/semantic/design-docs.md`

**Step 1: Create environment.md**

```markdown
---
id: sem-environment
type: semantic/environment
tags: [environment, python, proxy, venv]
created: 2026-02-08
relevance: high
related: [sem-architecture]
---

# Environment Configuration

- Python venv: `/Users/allenqiang/stockagent/venv/`
- Proxy: `http://127.0.0.1:7890` — use `NO_PROXY=localhost,127.0.0.1` for local API
- Frontend dev: `npm run dev` in `web/` -> port 3050
- Backend dev: `uvicorn api.main:app --port 8050`
- Claude CLI: `/opt/homebrew/bin/claude`
- SQLite DB: `data/stockagent.db`
- Config file: `config/config.yaml`
```

**Step 2: Create design-docs.md**

```markdown
---
id: sem-design-docs
type: semantic/design-docs
tags: [design, plans, documentation]
created: 2026-02-17
relevance: medium
related: [sem-architecture]
---

# Design Documents Index

| Date | Topic | File | Status |
|------|-------|------|--------|
| 2026-02-02 | Full system design | `docs/plans/2026-02-02-full-system-design.md` | Done |
| 2026-02-08 | Frontend upgrade | `docs/plans/2026-02-08-frontend-upgrade-design.md` | Done |
| 2026-02-08 | Market indicator system | `docs/plans/2026-02-08-market-indicator-system-design.md` | Done |
| 2026-02-10 | AI Lab | `docs/plans/2026-02-10-ai-lab-design.md` | Done |
| 2026-02-12 | Market regime integration | `docs/plans/2026-02-12-market-regime-integration-design.md` | Done |
| 2026-02-14 | News sentiment trading | `docs/plans/2026-02-14-news-sentiment-trading-design.md` | Done |
| 2026-02-15 | Combo strategy | `docs/plans/2026-02-15-combo-strategy-design.md` | Done |
| 2026-02-15 | Rule engine P4 upgrade | `docs/plans/2026-02-15-rule-engine-upgrade-design.md` | Done |
| 2026-02-17 | AI-driven signals | `docs/plans/2026-02-17-ai-driven-signals-design.md` | Planned |
| 2026-02-17 | Alpha scoring | `docs/plans/2026-02-17-alpha-scoring-design.md` | Planned |
| 2026-02-17 | Memory system | `docs/plans/2026-02-17-memory-system-design.md` | In Progress |
```

---

### Task 6: Migrate Episodic Knowledge — Experiment Notes (R01-R10)

**Files:**
- Create: `memory/episodic/experiments/R01-R04-kdj-exploration.md`
- Create: `memory/episodic/experiments/R05-R09-indicator-combos.md`
- Create: `memory/episodic/experiments/R10-new-indicators.md`
- Source: `docs/lab-experiment-analysis.md` insights 1-26

**Step 1: Create R01-R04 (KDJ exploration)**

```markdown
---
id: exp-r01-r04-kdj
type: episodic/experiment
tags: [KDJ, MACD, exploration, early-rounds, A-shares]
created: 2026-02-10
relevance: high
related: [sem-strategy-knowledge, exp-r05-r09-combos]
---

# R01-R04: KDJ Exploration & Early Combo Discovery

## Key Findings
1. KDJ is the most effective single technical indicator for A-shares — validated across 4 rounds
2. KDJ+MACD is the best dual indicator combo — 双金叉(+34.1%), 趋势跟踪(+29.3%), 底背离(+26.9%)
3. Short-period KDJ(6,3,3) > default(9,3,3) — 40% profit rate, best dd only 6.6%
4. All-regime profitable strategies share: short holding + fast turnover
5. Ranging market is the biggest profit killer — only 4% of strategies profit in ranging
6. 3+ indicator combos are counterproductive — 2 complementary indicators is the ceiling

## Experiment Stats
- Round 1-4 combined: 67 KDJ themes -> 26 profitable strategies
- Best return: +60.7% (KDJ variant)
- 5 strategies profitable across bull/bear/ranging

## Lessons
- 3-4 buy conditions is optimal (2 too loose, 5+ causes zero trades)
- Pure MA/EMA strategies are useless in A-shares (0 profit across 4 rounds)
- CMF is almost always negative in A-shares — unusable independently
```

**Step 2: Create R05-R09 (indicator combos)**

```markdown
---
id: exp-r05-r09-combos
type: episodic/experiment
tags: [indicator-combos, KDJ+RSI, KDJ+EMA, MACD+RSI, field-compare, BOLL]
created: 2026-02-12
relevance: medium
related: [exp-r01-r04-kdj, exp-r10-new-indicators]
---

# R05-R09: Non-KDJ Indicator Combos & Refinements

## Key Findings
- Non-KDJ combos largely fail: KDJ+RSI(0%), KDJ+EMA(0%), MACD+RSI(6.7%), EMA+ATR(0%)
- KDJ+MACD remains the ONLY effective dual-indicator combo
- RSI extreme oversold (<25) has high profit rate but too few signals
- Short-period KDJ+MACD(6,3,3)+(8,17,9) worse than defaults (+17.5% vs +34.1%)
- Volume confirmation adds zero value to KDJ
- MACD histogram crossover as primary signal is catastrophic (0/8 profit)
- DeepSeek cannot precisely reproduce existing strategies
- ADX/MA20 trend filters cannot defeat ranging markets
- BOLL_lower best return +59.0%

## Lessons
- field-to-field comparison works in rule engine (close < BOLL_lower)
- Trend filters (ADX>25, MA20) get fooled by ranging market noise
- DeepSeek "optimize" experiments produce worse results than originals
```

**Step 3: Create R10 (new indicators)**

```markdown
---
id: exp-r10-new-indicators
type: episodic/experiment
tags: [new-indicators, PSAR, ULCER, Keltner, UltimateOsc, Stochastic, BOLL-pctB]
created: 2026-02-13
relevance: medium
related: [exp-r05-r09-combos, exp-r11-r15-psar]
---

# R10: New Indicator Exploration (33 TA-Lib Indicators)

## Key Findings
- Added 33 TA-Lib indicators, 20+ experiments, 160+ strategies
- Overall: done=89, profitable=14 (15.7%), Standard A=3
- PSAR is the best new indicator after KDJ
- Keltner+ULCER low-volatility strategy has unique value (38% profit rate)
- BOLL%B+StochRSI is the best new discovery (+37.9%, score 0.66)
- UltimateOscillator is the biggest surprise (50% profit rate, score 0.72)
- Stochastic also valuable but similar to KDJ

## Effective New Indicators
| Indicator | Best Result | Notes |
|-----------|------------|-------|
| PSAR | +14.3%, dd 6.1% | Best as trend direction filter |
| BOLL%B+StochRSI | +37.9%, 233 trades | Standard A |
| UltimateOsc | +28.0%, dd 11.2% | Third effective oscillator after KDJ/MACD |
| ULCER | +19.5%, dd low | Only effective downside risk metric |

## Lessons
- Most new indicators are ineffective — only 6 out of 33 have any value
- PSAR shines as combination partner, not standalone
```

---

### Task 7: Migrate Episodic Knowledge — Experiment Notes (R11-R21)

**Files:**
- Create: `memory/episodic/experiments/R11-R15-psar-combos.md`
- Create: `memory/episodic/experiments/R16-R21-grid-search.md`
- Source: `docs/lab-experiment-analysis.md` insights 27-40

**Step 1: Create R11-R15 (PSAR combos)**

```markdown
---
id: exp-r11-r15-psar
type: episodic/experiment
tags: [PSAR, MACD, KDJ, BOLL, triple-combo, combo-strategy, timeout-protection]
created: 2026-02-14
relevance: high
related: [exp-r10-new-indicators, exp-r16-r21-grid-search, sem-strategy-knowledge]
---

# R11-R15: PSAR Triple Combos & Combo Strategy

## Key Findings
- PSAR+MACD+KDJ is the new strongest combo — S1277: score 0.77, +70.8%, dd 12.6%, all-regime profit
- PSAR+ULCER+KDJ has highest profit rate (71%) but low returns
- PSAR+BOLL+KDJ is second strongest triple — score 0.70, +27.5%, dd 8.2%
- Same-type indicator stacking fails: STOCH+KDJ, ULTOSC+KDJ, ULCER+STOCH all dead ends
- DeepSeek completely ignores field-comparison instructions for PSAR

## Combo Strategy (P3)
- Signal voting mechanism implemented: N member strategies vote, configurable threshold
- 5 diverse strategies with threshold=2/5: only 6 trades, +1.0%, dd 0.2%
- Diverse strategies are too conservative — use same-indicator variants instead

## Three-Layer Timeout Protection
- L1: Enhanced signal explosion detection (periodic re-check every 50 days)
- L2: Single strategy 5-minute timeout (threading.Timer + cancel_event)
- L3: Experiment 60-minute watchdog
- 323 strategy retries with zero hangs

## Key Insight
- Effective triple combos need DIFFERENT indicator types: trend(PSAR) + momentum(MACD) + oversold(KDJ)
- Same-type stacking only amplifies noise
```

**Step 2: Create R16-R21 (grid search)**

```markdown
---
id: exp-r16-r21-grid-search
type: episodic/experiment
tags: [grid-search, exit-config, SL, TP, MHD, parameter-optimization, breakthrough]
created: 2026-02-15
relevance: high
related: [exp-r11-r15-psar, sem-strategy-knowledge]
---

# R16-R21: Grid Search Breakthrough & Parameter Exhaustion

## Key Findings
- Grid search bypasses DeepSeek: clone S1277, modify exit_config, run 11 parameter combos
- Grid search success rate >90% (vs DeepSeek 12.5%)
- All top strategies come from grid search, not DeepSeek generation

## Best Results
| Strategy | Score | Return | DD | Notes |
|----------|-------|--------|-----|-------|
| 全指标综合_中性版C_SL7_TP14_MHD15 | 0.825 | +90.5% | 12.4% | Highest score |
| PSAR趋势动量_SL10_TP14 | 0.802 | +99.6% | 12.2% | Highest return |
| 全指标综合_保守版B_SL8_TP9 | 0.744 | +26.4% | 3.2% | Lowest dd |

## Parameter Insights
- TP14 is universal golden take-profit for both PSAR+MACD+KDJ and 全指标综合
- SL7 > SL5: wider stop-loss adds +15pp return for 全指标综合
- MHD has no effect on most strategies (only MACD+RSI sensitive to MHD)
- UltimateOsc: TP10 optimal, reduces dd by 40% vs TP18
- KDJ+MACD and BOLL%B+StochRSI: original parameters already optimal

## DeepSeek Status
- 87.5% invalid rate for new strategy generation
- Completely stopped using DeepSeek for new strategies
- Grid search is the only viable optimization method

## Lessons
- 6 consecutive precision search rounds (R16-R21): 71+ experiments, 100% Standard A hit rate
- Parameter space fully exhausted after 21 rounds
- Backtest must run serially (Semaphore=1) to protect SQLite
```

---

### Task 8: Migrate Episodic Knowledge — Bug & Decision Records

**Files:**
- Create: `memory/episodic/bugs/data-gap-2026-02-10.md`
- Create: `memory/episodic/decisions/001-fire-and-forget-chat.md`

**Step 1: Create data gap bug record**

```markdown
---
id: bug-data-gap-20260210
type: episodic/bug
tags: [data-integrity, daily-prices, TuShare, portfolio-backtest, critical]
created: 2026-02-10
relevance: high
related: [sem-architecture]
---

# Bug: Data Gap on 2026-02-10 (53 records instead of ~5175)

## Problem
- `daily_prices` table had only 53 records for 2026-02-10 (normal: ~5175)
- Portfolio backtest market value dropped to zero, max drawdown 90%+

## Root Cause
- Data collection interrupted, only partial day's data saved

## Solution
- Created `TradingCalendar` table caching SSE trading calendar (TuShare `trade_cal` API)
- `repair_daily_gaps()`: detects gaps by date (threshold = max_daily_count * 80%), repairs with TuShare `daily(trade_date=)` for whole market
- `get_daily_df()` improved: auto-extends 5 years when not local_only; internal gap detection
- Three trigger points: AI Lab (before backtest), backtest_engine (4 entry points), signal_scheduler (current day)
- Removed `last_close` carry-forward from portfolio_engine — data integrity guaranteed by repair
```

**Step 2: Create fire-and-forget chat decision**

```markdown
---
id: dec-001-fire-and-forget-chat
type: episodic/decision
tags: [AI-chat, architecture, fire-and-forget, polling, Next.js]
created: 2026-02-17
relevance: high
related: [sem-architecture]
---

# ADR-001: Fire-and-Forget + Polling for AI Chat

## Context
- AI chat used sync blocking: POST -> Next.js rewrite -> FastAPI -> subprocess.run(claude CLI) blocks 45-180s
- Next.js rewrite proxy has ~30s default timeout -> 500 errors

## Decision
Move Claude CLI execution into Next.js Node.js process. Fire-and-forget POST returns messageId instantly (<50ms), frontend polls every 2s for progress/result.

## Implementation
- `web/src/lib/claude-worker.ts`: globalThis-safe job/session stores, spawn() with stream-json
- `web/src/app/api/ai/chat/route.ts`: fire-and-forget POST
- `web/src/app/api/ai/chat/poll/route.ts`: polling GET endpoint
- Frontend: useAIChatSend() + useAIChatPoll() with conditional refetchInterval

## Consequences
- No more timeout errors
- Real-time progress feedback ("正在执行命令...", "正在搜索...")
- FastAPI /api/ai/reports and /api/ai/analyze endpoints unchanged (still via rewrite)
```

---

### Task 9: Create Procedural Knowledge

**Files:**
- Create: `memory/procedural/grid-search-workflow.md`
- Create: `memory/procedural/experiment-analysis.md`

**Step 1: Create grid search workflow**

```markdown
---
id: proc-grid-search
type: procedural/workflow
tags: [grid-search, clone, exit-config, backtest, workflow]
created: 2026-02-15
relevance: high
related: [exp-r16-r21-grid-search, sem-strategy-knowledge]
---

# Grid Search Workflow

## When to Use
When you have a profitable base strategy and want to find optimal exit parameters (stop_loss, take_profit, max_hold_days).

## Steps
1. Identify base strategy (e.g. S1277 PSAR+MACD+KDJ)
2. Clone strategy via AI Lab with modified exit_config
3. Run parameter grid: SL={5,7,8,10}% x TP={9,10,14,15}% x MHD={10,15,20,none}
4. Execute backtests serially (Semaphore=1 to protect SQLite)
5. Compare results: score, total_return_pct, max_drawdown_pct
6. Promote best variants to strategy list

## Key Constraints
- Never run >1 concurrent backtest (SQLite lock)
- Each backtest takes ~1-10 minutes depending on strategy complexity
- 5-member combo strategies can take 15+ minutes (may timeout)

## What NOT to Do
- Do NOT use DeepSeek to generate parameter variations (87.5% invalid rate)
- Do NOT try >3 indicators in a combo
- Do NOT stack same-type indicators (e.g. STOCH+KDJ)
```

**Step 2: Create experiment analysis workflow**

```markdown
---
id: proc-experiment-analysis
type: procedural/workflow
tags: [experiment, analysis, lab, workflow]
created: 2026-02-16
relevance: high
related: [sem-strategy-knowledge]
---

# Experiment Analysis Workflow

## After Each Experiment Round
1. Query experiment results: GET /api/lab/experiments/{id}
2. Classify strategies: done vs invalid vs error
3. Calculate profit rate: profitable / done
4. Identify Standard A strategies (score >= 0.65, return > 10%, dd < 25%)
5. Extract key findings (what worked, what failed, why)
6. Write episodic memory note: `memory/episodic/experiments/RNN-topic.md`
7. Update `memory/semantic/strategy-knowledge.md` if new insights
8. Update `docs/lab-experiment-analysis.md` with new round data
9. Sync to Pinecone: `python scripts/sync-memory.py --incremental`

## Standard A Criteria
- Score >= 0.65
- Total return > 10%
- Max drawdown < 25%
- Total trades >= 30
```

---

### Task 10: Create meta/index.json

**Files:**
- Create: `memory/meta/index.json`

**Step 1: Create initial index**

Create `index.json` with entries for all memory files created in Tasks 2-9. The index maps id -> file_path and includes tags for each note.

```json
{
  "version": 1,
  "updated": "2026-02-17",
  "notes": [
    {"id": "sem-architecture", "file": "semantic/architecture.md", "type": "semantic", "tags": ["architecture", "nextjs", "fastapi"], "relevance": "high"},
    {"id": "sem-library-gotchas", "file": "semantic/library-gotchas.md", "type": "semantic", "tags": ["lightweight-charts", "react-resizable-panels"], "relevance": "high"},
    {"id": "sem-strategy-knowledge", "file": "semantic/strategy-knowledge.md", "type": "semantic", "tags": ["strategy", "KDJ", "MACD", "PSAR"], "relevance": "high"},
    {"id": "sem-environment", "file": "semantic/environment.md", "type": "semantic", "tags": ["environment", "proxy", "venv"], "relevance": "high"},
    {"id": "sem-design-docs", "file": "semantic/design-docs.md", "type": "semantic", "tags": ["design", "plans"], "relevance": "medium"},
    {"id": "exp-r01-r04-kdj", "file": "episodic/experiments/R01-R04-kdj-exploration.md", "type": "episodic", "tags": ["KDJ", "MACD", "exploration"], "relevance": "high"},
    {"id": "exp-r05-r09-combos", "file": "episodic/experiments/R05-R09-indicator-combos.md", "type": "episodic", "tags": ["indicator-combos", "BOLL"], "relevance": "medium"},
    {"id": "exp-r10-new-indicators", "file": "episodic/experiments/R10-new-indicators.md", "type": "episodic", "tags": ["new-indicators", "PSAR", "ULCER"], "relevance": "medium"},
    {"id": "exp-r11-r15-psar", "file": "episodic/experiments/R11-R15-psar-combos.md", "type": "episodic", "tags": ["PSAR", "triple-combo"], "relevance": "high"},
    {"id": "exp-r16-r21-grid-search", "file": "episodic/experiments/R16-R21-grid-search.md", "type": "episodic", "tags": ["grid-search", "breakthrough"], "relevance": "high"},
    {"id": "bug-data-gap-20260210", "file": "episodic/bugs/data-gap-2026-02-10.md", "type": "episodic", "tags": ["data-integrity", "critical"], "relevance": "high"},
    {"id": "dec-001-fire-and-forget-chat", "file": "episodic/decisions/001-fire-and-forget-chat.md", "type": "episodic", "tags": ["AI-chat", "architecture"], "relevance": "high"},
    {"id": "proc-grid-search", "file": "procedural/grid-search-workflow.md", "type": "procedural", "tags": ["grid-search", "workflow"], "relevance": "high"},
    {"id": "proc-experiment-analysis", "file": "procedural/experiment-analysis.md", "type": "procedural", "tags": ["experiment", "analysis"], "relevance": "high"}
  ]
}
```

---

### Task 11: Create Pinecone Index + Sync Script

**Files:**
- Create: `scripts/sync-memory.py`

**Step 1: Create Pinecone index**

Use the Pinecone MCP tool `create-index-for-model`:
```
name: stockagent-memory
embed model: multilingual-e5-large
fieldMap.text: text
cloud: aws
region: us-east-1
```

**Step 2: Create sync script**

Create `scripts/sync-memory.py` that:
1. Walks `memory/` directory for all `.md` files (excluding MEMORY.md)
2. Parses YAML frontmatter (using `pyyaml` or simple regex)
3. Extracts id, type, tags, relevance, created, and body text
4. Upserts to Pinecone via the Pinecone Python client
5. Updates `meta/index.json`

```python
#!/usr/bin/env python3
"""Sync memory notes to Pinecone index.

Usage:
    python scripts/sync-memory.py --full     # full rebuild
    python scripts/sync-memory.py            # incremental (new/changed only)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

MEMORY_DIR = Path(os.environ.get(
    "MEMORY_DIR",
    os.path.expanduser("~/.claude/projects/-Users-allenqiang-stockagent/memory")
))
INDEX_FILE = MEMORY_DIR / "meta" / "index.json"
PINECONE_INDEX = "stockagent-memory"
PINECONE_NAMESPACE = "default"


def parse_note(filepath: Path) -> dict | None:
    """Parse a memory note file, extracting frontmatter and body."""
    text = filepath.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.+?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return None
    front = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    if not front or "id" not in front:
        return None
    rel_path = str(filepath.relative_to(MEMORY_DIR))
    tags = front.get("tags", [])
    return {
        "_id": front["id"],
        "text": body,
        "type": front.get("type", "").split("/")[0],
        "subtype": front.get("type", "").split("/")[-1],
        "tags": ",".join(tags) if isinstance(tags, list) else str(tags),
        "relevance": front.get("relevance", "medium"),
        "created": str(front.get("created", "")),
        "file_path": rel_path,
    }


def collect_notes() -> list[dict]:
    """Collect all memory notes from the memory directory."""
    notes = []
    for md in MEMORY_DIR.rglob("*.md"):
        if md.name == "MEMORY.md":
            continue
        note = parse_note(md)
        if note:
            notes.append(note)
    return notes


def update_index(notes: list[dict]):
    """Update meta/index.json from collected notes."""
    entries = []
    for n in notes:
        entries.append({
            "id": n["_id"],
            "file": n["file_path"],
            "type": n["type"],
            "tags": n["tags"].split(",") if n["tags"] else [],
            "relevance": n["relevance"],
        })
    index_data = {
        "version": 1,
        "updated": __import__("datetime").date.today().isoformat(),
        "notes": sorted(entries, key=lambda x: x["id"]),
    }
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(index_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {INDEX_FILE} with {len(entries)} notes")


def sync_pinecone(notes: list[dict]):
    """Upsert notes to Pinecone. Requires PINECONE_API_KEY env var."""
    api_key = os.environ.get("PINECONE_API_KEY")
    if not api_key:
        print("PINECONE_API_KEY not set, skipping Pinecone sync")
        print("Set it to enable semantic search: export PINECONE_API_KEY=...")
        return

    try:
        from pinecone import Pinecone
    except ImportError:
        print("pinecone package not installed. Run: pip install pinecone")
        return

    pc = Pinecone(api_key=api_key)
    idx = pc.Index(PINECONE_INDEX)

    # Upsert in batches of 20
    batch_size = 20
    for i in range(0, len(notes), batch_size):
        batch = notes[i:i + batch_size]
        records = []
        for n in batch:
            records.append({
                "_id": n["_id"],
                "text": n["text"][:8000],  # truncate for embedding
                "type": n["type"],
                "subtype": n["subtype"],
                "tags": n["tags"],
                "relevance": n["relevance"],
                "created": n["created"],
                "file_path": n["file_path"],
            })
        idx.upsert_records(PINECONE_NAMESPACE, records)
        print(f"Upserted {len(records)} records (batch {i // batch_size + 1})")

    print(f"Pinecone sync complete: {len(notes)} records in {PINECONE_INDEX}")


def main():
    parser = argparse.ArgumentParser(description="Sync memory notes to Pinecone")
    parser.add_argument("--full", action="store_true", help="Full rebuild (default: incremental)")
    args = parser.parse_args()

    notes = collect_notes()
    print(f"Found {len(notes)} memory notes")

    if not notes:
        print("No notes found. Check MEMORY_DIR path.")
        sys.exit(1)

    update_index(notes)
    sync_pinecone(notes)


if __name__ == "__main__":
    main()
```

**Step 3: Verify script runs**

```bash
cd /Users/allenqiang/stockagent
python scripts/sync-memory.py
```

Expected: "Found N memory notes", "Updated index.json with N notes", and either Pinecone upsert success or "PINECONE_API_KEY not set" message.

---

### Task 12: Rewrite MEMORY.md as Navigation Index

**Files:**
- Modify: `memory/MEMORY.md` (full rewrite)

**Step 1: Replace MEMORY.md with lean index**

```markdown
# StockAgent Memory Index

## Project
A股量化交易系统: Next.js 16 + FastAPI + SQLAlchemy + AkShare/TuShare
Memory base: This directory contains structured knowledge in semantic/episodic/procedural categories.

## How to Use This Memory
- **Architecture/API/Libraries**: Read files in `semantic/`
- **Experiments/Decisions/Bugs**: Read files in `episodic/`
- **Workflows/Procedures**: Read files in `procedural/`
- **Semantic search**: Use Pinecone MCP `search-records` (index: `stockagent-memory`, namespace: `default`)
- **Full index**: Read `meta/index.json` for all note IDs, tags, and file paths
- **When adding new knowledge**: Create a new .md file with YAML frontmatter (id, type, tags, created, relevance, related), then run `python scripts/sync-memory.py`

## Recent Highlights
- [high] PSAR+MACD+KDJ is the strongest combo (score 0.825, +90.5%, dd 12.4%)
- [high] Grid search success >90%, DeepSeek strategy generation failed (87.5% invalid)
- [high] TP14 is the universal golden take-profit point
- [high] Fire-and-forget + polling chat architecture deployed
- [high] 21 rounds, 306 experiments, parameter space fully exhausted

## Key Constraints
- DeepSeek does NOT use new compare_types — needs few-shot templates
- Backtest runs serially (Semaphore=1) — protect SQLite
- Google Fonts blocked by proxy — use system fonts
- Claude CLI path: `/opt/homebrew/bin/claude`
- Proxy: `http://127.0.0.1:7890`, use `NO_PROXY=localhost,127.0.0.1` for local API

## Memory Structure
```
semantic/           Facts: architecture, library-gotchas, strategy-knowledge, environment, design-docs
episodic/
  experiments/      R01-R04 KDJ, R05-R09 combos, R10 new indicators, R11-R15 PSAR, R16-R21 grid search
  decisions/        ADR-001 fire-and-forget chat
  bugs/             Data gap 2026-02-10
procedural/         Grid search workflow, experiment analysis workflow
meta/index.json     Full index of all notes with tags
```
```

---

### Task 13: Update ChatWidget System Prompt for Memory Retrieval

**Files:**
- Modify: `web/src/lib/claude-worker.ts:60-75` (SYSTEM_PROMPT constant)

**Step 1: Add memory retrieval instructions to SYSTEM_PROMPT**

Add the following block after the API endpoints list in the SYSTEM_PROMPT:

```typescript
const SYSTEM_PROMPT = `\
You are an expert A-share (China stock market) analyst assistant in the StockAgent system.
You can access local APIs at http://localhost:8050 to answer questions about stocks, signals, and strategies.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...

Available API endpoints:
- GET /api/signals/today — today's signals
- GET /api/signals/history?start_date=&end_date= — historical signals
- GET /api/strategies — active strategies
- GET /api/market/kline?code=&period=daily&start_date=&end_date= — K-line data
- GET /api/market/quote?code= — real-time quote
- GET /api/news/sentiment/latest — news sentiment
- GET /api/stocks/watchlist — watchlist
- GET /api/stocks/search?keyword= — search stocks

Knowledge Base:
You have access to a structured memory system with experiment results, strategy insights, and architectural decisions.
When answering questions about strategies, experiments, or historical decisions, consult the memory files at:
/Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/
- Read meta/index.json first to find relevant notes by tags
- Key knowledge: semantic/strategy-knowledge.md (what works/doesn't work)
- Experiment details: episodic/experiments/ (R01-R21 results)

Answer in Chinese. Be concise but thorough. Use data from the APIs to support your analysis.`;
```

**Step 2: Verify build**

```bash
cd /Users/allenqiang/stockagent/web && npx tsc --noEmit
```

Expected: No errors.

---

### Task 14: Pinecone Setup & Initial Sync

**Step 1: User registers for Pinecone free tier**

Go to https://app.pinecone.io and create a free account. Get API key.

**Step 2: Create index via MCP**

Use `create-index-for-model` MCP tool:
- name: `stockagent-memory`
- embed model: `multilingual-e5-large`
- fieldMap.text: `text`
- cloud: `aws`, region: `us-east-1`

**Step 3: Set API key and run full sync**

```bash
export PINECONE_API_KEY=your-key-here
cd /Users/allenqiang/stockagent
pip install pinecone
python scripts/sync-memory.py --full
```

**Step 4: Verify search works**

Use `search-records` MCP tool:
- index: `stockagent-memory`
- namespace: `default`
- query: "KDJ策略表现如何"
- topK: 3

Expected: Returns notes related to KDJ strategy performance.

---

### Task 15: Verification & Commit

**Step 1: Verify directory structure**

```bash
find /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory -type f | sort
```

Expected: ~15 files across semantic/, episodic/, procedural/, meta/.

**Step 2: Verify MEMORY.md is under 80 lines**

```bash
wc -l /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/MEMORY.md
```

Expected: < 80 lines.

**Step 3: Verify sync script**

```bash
python scripts/sync-memory.py
```

Expected: "Found 14 memory notes", index.json updated.

**Step 4: Verify ChatWidget build**

```bash
cd /Users/allenqiang/stockagent/web && npx tsc --noEmit
```

Expected: No errors.

**Step 5: Test ChatWidget with memory query**

Start dev server, go to /ai, ask "哪些策略组合最有效？". Verify the response references memory knowledge.

**Step 6: Commit**

```bash
cd /Users/allenqiang/stockagent
git add scripts/sync-memory.py web/src/lib/claude-worker.ts docs/plans/2026-02-17-memory-system-design.md docs/plans/2026-02-17-memory-system-plan.md
git commit -m "feat: add Zettelkasten memory system with Pinecone retrieval

- Structured memory: semantic/, episodic/, procedural/ directories
- Atomic notes with YAML frontmatter (id, type, tags, relevance)
- Pinecone sync script for semantic search
- ChatWidget system prompt enhanced with memory retrieval
- MEMORY.md rewritten as lean navigation index"
```
