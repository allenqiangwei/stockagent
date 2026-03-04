---
name: explore-strategies
description: Iterative strategy discovery — analyze experiments, plan new ones, auto-promote winners, then resolve ALL identified problems and implement follow-up actions. Use /explore-strategies for semi-auto, /explore-strategies auto for full-auto (default 50), /explore-strategies auto N for N experiments, /explore-strategies time Xh for time-limited continuous exploration (300 strategies per batch).
---

# Strategy Explorer

You are a quantitative strategy researcher for the Chinese A-share market. Your job is to systematically discover profitable strategies through iterative experimentation using the AI Lab system.

## Mode

- **Default** (no args): Semi-auto — present plan, wait for user approval, then execute
- **`auto`** argument: Full-auto with default 50 experiments per round
- **`auto N`** argument: Full-auto with N experiments per round (e.g. `auto 30` = 30 experiments)
- **`time Xh`** or **`time Xm`** argument: Time-limited continuous exploration — runs in batches of ~300 strategies per round until the specified duration expires. Examples: `time 2h` = 2 hours, `time 90m` = 90 minutes, `time 0.5h` = 30 minutes.

The number N controls the total experiment count for the round. Direction allocation is decided dynamically by the AI based on memory analysis (Step 3).

### Time Mode Details

In `time` mode, the skill operates like `auto` mode but with these differences:
1. **Batch size**: Each round targets ~300 strategies (not N experiments). Since each experiment typically generates ~4-6 strategies, this means ~50-75 experiments per round. The AI dynamically adjusts experiment count to hit the ~300 strategy target.
2. **No user prompts**: Rounds transition automatically without asking the user. No `AskUserQuestion` between rounds.
3. **Time-based exit**: The skill records the start time and checks remaining time before each new round. If remaining time < 30 minutes (estimated minimum for a useful round), it stops and proceeds to Step 10.
4. **Background auto-finish**: If a round's backtests are still running when time is about to expire, the skill creates a background `auto_finish` script for the remaining backtests and exits gracefully.
5. **Clock display**: At the start of each round, display elapsed time and remaining time:
   ```
   ⏱️ 已用时: 1h 23m / 总计: 3h | 剩余: 1h 37m
   ```

## Step 1: Load Memory & Verify Promote/Enable State

### 1a: Load Memory

Read `docs/lab-experiment-analysis.md`. Extract:
- **核心洞察**: What works and doesn't work in A-share markets
- **探索状态**: Which directions have been explored, their results, what's next
- **最佳策略**: Current top strategies and their characteristics
- **Auto-Promote 记录**: What has already been promoted
- **已知问题**: Known rule engine limitations and workarounds

### 1b: Verify Previous Experiments are Correctly Promoted

Scan ALL completed experiments and ensure every qualifying strategy has been promoted. This catches cases where a previous session's Step 7 (Auto-Promote) was skipped or interrupted.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json, urllib.parse

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def promote(sid, label):
    encoded_label = urllib.parse.quote(label)
    cat_map = {'[AI]':'全能','[AI-牛市]':'牛市','[AI-熊市]':'熊市','[AI-震荡]':'震荡'}
    cat = urllib.parse.quote(cat_map.get(label, ''))
    r = subprocess.run(['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label={encoded_label}&category={cat}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# Scan all experiments
all_exps = api('lab/experiments?page=1&size=200').get('items', [])
missing = 0
promoted = 0
for exp_summary in all_exps:
    eid = exp_summary['id']
    exp = api(f'lab/experiments/{eid}')
    for s in exp.get('strategies', []):
        if s.get('status') != 'done': continue
        if s.get('promoted'): continue  # already promoted
        score = s.get('score',0) or 0
        ret = s.get('total_return_pct',0) or 0
        dd = abs(s.get('max_drawdown_pct',100) or 100)
        trades = s.get('total_trades',0) or 0
        wr = s.get('win_rate',0) or 0
        if score >= 0.75 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
            result = promote(s['id'], '[AI]')
            msg = result.get('message','')
            if msg != 'Already promoted':
                missing += 1
                print(f'  PROMOTED: S{s[\"id\"]} {s.get(\"name\",\"?\")[:50]} (score={score:.3f}, ret={ret:.1f}%, wr={wr:.1f}%) -> {msg}')
            promoted += 1

print(f'Promote检查完成: {promoted}个StdA策略, 其中{missing}个补漏promote')
"
```

If any strategies were missing from the promote list, output:
```
Promote补漏: N个策略未被promote, 已修复
```

### 1c: Enable ALL Promoted Strategies in Strategy Management

All promoted strategies should be enabled so they can be used for signal generation and combo strategies. Query the strategy library and enable any that are currently disabled.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api_get(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def api_put(path, data):
    r = subprocess.run(['curl','-s','-X','PUT',f'http://127.0.0.1:8050/api/{path}',
                        '-H','Content-Type: application/json','-d',json.dumps(data)],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# Get all strategies in strategy management
strategies = api_get('strategies')
disabled = [s for s in strategies if not s.get('enabled', False)]
enabled_count = 0

for s in disabled:
    api_put(f'strategies/{s[\"id\"]}', {'enabled': True})
    enabled_count += 1
    print(f'  ENABLED: S{s[\"id\"]} {s.get(\"name\",\"?\")[:60]}')

print(f'策略启用完成: {len(strategies)}个策略总计, {enabled_count}个已启用, {len(strategies)-len(disabled)}个原已启用')
"
```

Output summary:
```
策略管理状态:
- Promote补漏: X个 (已修复)
- 策略启用: Y个disabled→enabled
- 当前策略库: Z个策略全部enabled
```

### 1d: Sync Completed Background Rounds

Background auto_finish scripts may complete between sessions. Check for exploration rounds where `memory_synced=false` and sync their results into memory.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

rounds = api('lab/exploration-rounds')
items = rounds.get('items', rounds) if isinstance(rounds, dict) else rounds
unsynced = [r for r in items if not r.get('memory_synced', False)]
if not unsynced:
    print('所有探索轮次已同步，无需补同步')
else:
    for r in unsynced:
        print(f'⚠️ R{r[\"round_number\"]} (id={r[\"id\"]}) 未同步! best={r.get(\"best_strategy_name\",\"?\")} score={r.get(\"best_strategy_score\",0)} ret={r.get(\"best_strategy_return\",0)}%')
    print(f'发现 {len(unsynced)} 个未同步轮次，需要执行 Step 8 (Update Memory) 补同步')
"
```

If unsynced rounds are found:
1. Read `/tmp/r{N}_summary.json` (if exists) for the full analysis data
2. Execute Step 8 (Update Memory) for each unsynced round — update `docs/lab-experiment-analysis.md`, `memory/semantic/strategy-knowledge.md`, `memory/episodic/experiments/`, `memory/MEMORY.md`
3. Run `python3 scripts/sync-memory.py` to push to Pinecone
4. Update the exploration round via `PUT /api/lab/exploration-rounds/{id}` with `memory_synced=true, pinecone_synced=true`
5. Run StdA+ cleanup: `POST /api/strategies/cleanup` to remove any strategies promoted by the background script that don't meet current StdA+ criteria

**This step is BLOCKING**: Do NOT proceed until all unsynced rounds are fully synced.

## Step 1.5: Resolve Outstanding Issues (BLOCKING GATE)

**Before ANY new exploration, all outstanding issues from previous sessions must be resolved.**

Scan the **已知问题** table for items whose status is NOT "已修复" / "已验证" / "已完成" / "已实现" / "完成" / "已弃". Also check for:
- Experiments stuck in `backtesting` or `pending` status (zombie experiments)
- Strategies that were reset to `pending` but never re-run
- Any TODO items or "下一步" notes left from previous sessions

For each outstanding issue:

1. **Classify**: 🔧 Fixable now / 🏗️ Needs new feature / ⏳ Blocked externally
2. **Execute fixes** for all 🔧 and 🏗️ items — read relevant code, implement the fix, test it, commit
3. **Re-run** any experiments or backtests that were blocked by the now-fixed issues
4. **Update** `docs/lab-experiment-analysis.md` 已知问题 table with new status
5. **Document** any ⏳ items clearly (what's needed, why blocked, expected impact)

**This step is a BLOCKING GATE**: Do NOT proceed to Step 2 until all fixable issues are resolved. If a fix requires server restart, do it. If a fix requires code changes, implement them. The goal is to start each exploration round with a clean slate.

**Output a summary** of what was resolved before proceeding:
```
遗留问题处理:
- ✅ [issue]: [what was done]
- ✅ [issue]: [what was done]
- ⏳ [issue]: [why blocked]
无遗留问题 / 全部已处理，继续探索。
```

## Step 2: Query Latest Data

Query the running backend (port 8050) for the latest state:

```bash
# Recent experiments
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments?page=1&size=10"

# Current market regime (last 3 years)
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/regimes?start_date=2023-02-14&end_date=2026-02-14"
```

Check if there are recent experiments whose results haven't been analyzed yet. If so, analyze them first before planning new ones.

## Step 3: Analyze & Batch Plan (N experiments)

Based on the accumulated insights from **核心洞察**, **探索状态**, **最佳策略** and the **下一步建议** from previous sessions, generate a batch of **N experiment plans** (N = user-specified count, default 50).

**In `time` mode**: Target ~300 strategies per round. Since each experiment produces ~4-6 strategies, plan ~50-75 experiments per round. The exact count should be dynamically adjusted based on the experiment types being used (grid search produces more strategies per experiment than DeepSeek).

### 3a: Decision Framework — Dynamic Allocation

Synthesize all available evidence to decide the next exploration directions **and how many experiments to allocate to each**. There is NO fixed ratio — the AI decides allocation based on what memory says is most promising.

1. **Review what worked**: Which indicator combinations, parameter ranges, and market hypotheses produced profitable strategies? Allocate more experiments to proven high-yield directions.
2. **Review what failed**: Which directions are "已弃"? Do NOT retry them unless a code fix (from Step 1.5) has removed the original blocker. Allocate ZERO to dead ends.
3. **Check 下一步建议**: Previous sessions' recommendations are high-priority inputs — convert each actionable suggestion into 1-3 experiment plans.
4. **Identify gaps**: Are there promising indicator combinations not yet tested? Are there parameter ranges for top strategies not yet grid-searched?
5. **Assess method effectiveness**: Check historical success rates of each experiment type (DeepSeek generation, grid search, variant testing, etc.) and allocate proportionally. For example, if DeepSeek has >50% invalid rate, allocate few or zero to it; if grid search has >90% success rate, allocate heavily.
6. **🆕 NEW INDICATOR EXPLORATION (MANDATORY)**: Every round MUST allocate **at least 5 experiments** (or 5% of N, whichever is larger) to testing a new or under-explored indicator. See the **Indicator Exploration Tracker** below.
7. **Decide allocation**: Present a brief allocation rationale before listing experiments:

```
本轮分配 (共N个实验):
- Grid search (clone-backtest): X个 — 理由: [why]
- Variant testing: Y个 — 理由: [why]
- 🆕 New indicator exploration: Z个 — 目标指标: [indicator name] — 理由: [why this indicator]
- Other new direction: W个 — 理由: [why]
(X + Y + Z + W = N)
```

Available experiment categories (use any subset, allocate any amount including 0):

| Category | Description |
|----------|-------------|
| **Grid search (clone-backtest)** | Parameter optimization of proven strategies (SL/TP/hold days) |
| **Variant testing** | Modify top strategies with small changes (add/remove 1 condition, adjust thresholds) |
| **DeepSeek exploration** | New indicator/strategy ideas via DeepSeek generation |
| **🆕 New indicator exploration** | **MANDATORY every round.** Test indicators from the tracker below that are 未探索 or 浅探索 |
| **New direction** | Untested hypotheses or newly enabled features (e.g. new condition types) |

### 3a-extra: Indicator Exploration Tracker

**Every round MUST pick at least one indicator from the 未探索/浅探索 list below and run 5+ experiments with it.** The goal is to systematically test every available indicator over time, preventing stagnation in the same proven families.

**How to use this tracker:**
1. Read the tracker below to find indicators with status 未探索 or 浅探索
2. Pick the highest-priority one (prefer 未探索 > 浅探索, prefer higher priority indicators)
3. Design 5+ experiments: combine it with KDJ (proven base), try solo, try with PSAR/MACD
4. After running experiments, update the tracker status in `docs/lab-experiment-analysis.md`
5. If ALL indicators are 已探索/已弃, try **new combinations** of explored indicators that haven't been paired before

**Experiment design for new indicators:**
- Pair with KDJ (the strongest base indicator) as primary approach
- Try 2-3 standalone strategies (conservative/moderate/aggressive thresholds)
- Try 1-2 combos with PSAR or MACD (proven secondary indicators)
- Use clone-backtest where possible: if a working strategy exists with similar logic, clone and add the new indicator as a filter condition
- If clone-backtest isn't possible, use DeepSeek with explicit few-shot examples showing the correct indicator column names

#### Available Indicators & Exploration Status

**Built-in indicators (8):**

| Indicator | Status | Notes |
|-----------|--------|-------|
| KDJ | ✅ 深度探索 | 最有效单指标, 所有组合的核心 |
| MACD | ✅ 深度探索 | KDJ+MACD最佳双指标组合 |
| RSI | ✅ 已探索 | 极端超卖(<25)有效但信号少, RSI+KDJ组合有效 |
| ADX | ✅ 已探索 | 趋势过滤无法对抗震荡市, PSAR+ADX+CCI有效 |
| MA | ✅ 已弃 | 纯均线策略在A股无效 |
| EMA | ✅ 已弃 | EMA+ATR灾难性(-50%~-98%) |
| OBV | ⚠️ 避免 | 规则引擎建议避免 |
| ATR | ✅ 已探索 | EMA+ATR失败, 但ATR作为波动过滤可能有用 |

**Extended indicators (33) — exploration priority:**

| Priority | Indicator | Status | Columns | Notes |
|----------|-----------|--------|---------|-------|
| 🔴高 | **KAMA** | ✅ 深度探索 | KAMA_{length} | R31-R32探索, KAMA突破88个T+1存活, KAMA终极震荡全军覆没(0/65, 前视偏差), 保守版F/G各14个存活 |
| 🔴高 | **NVI** | ✅ 浅探索 | NVI | R32探索, 仅1/11达StdA+(score 0.760, T+1存活), 机构追踪理论合理但效果有限 |
| 🔴高 | **VPT** | ✅ 已弃 | VPT | R32探索, 0/21 StdA+, OBV改进版在A股同样失效 |
| 🟡中 | BOLL | ✅ 深度探索 | BOLL_upper/middle/lower/pctb | BOLL+KDJ有效, BOLL%B+StochRSI达StdA |
| 🟡中 | PSAR | ✅ 深度探索 | PSAR_{af}_{max_af} | 最强趋势指标, T+1 top=0.816, 91.3%存活(313/343) |
| 🟡中 | ULTOSC | ✅ 深度探索 | ULTOSC_{s}_{m}_{l} | T+1仅14.9%存活(26/175), 低TP策略受T+1冲击大 |
| 🟡中 | ULCER | ✅ 已探索 | ULCER_{length} | ULCER<5+KDJ有效, PSAR+ULCER+KDJ三重过滤71%盈利 |
| 🟡中 | CCI | ✅ 已探索 | CCI_{length} | PSAR+ADX+CCI有效但TP1-2死 |
| 🟡中 | STOCH | ✅ 已探索 | STOCH_K/D_{k}_{d}_{smooth} | 类似KDJ, 50%盈利率, 同类叠加失败 |
| 🟡中 | STOCHRSI | ✅ 已探索 | STOCHRSI_k/d_{length}_{rsi}_{k}_{d} | BOLL%B+StochRSI达StdA |
| 🟡中 | STC | ✅ 已弃 | STC_{length}_{fast}_{slow} | R154: STC+KDJ 4/4inv, best wr=46%, 0 StdA+. 确认无效 |
| 🟡中 | MFI | ✅ 已弃 | MFI_{length} | R154: MFI+KDJ wr=41%, MFI+PSAR wr=36%, 0 StdA+. 确认无效 |
| 🟡中 | WR | ✅ 已弃 | WR_{length} | R154: WR+PSAR wr=38%, WR+KDJ 6/8inv, 0 StdA+. 确认无效 |
| 🟡中 | ROC | ✅ 已弃 | ROC_{length} | R154: ROC+KDJ wr=44%, ROC+PSAR wr=45%, 0 StdA+. 确认无效 |
| 🟡中 | KELTNER | ✅ 已探索 | KELTNER_upper/middle/lower_{length}_{atr} | Keltner+ULCER有效(37.5%) |
| 🟢低 | DONCHIAN | ✅ 已弃 | DONCHIAN_upper/lower/mid_{length} | 海龟交易法全亏 |
| 🟢低 | AROON | ✅ 已弃 | AROON_up/down/osc_{length} | 信号爆炸+0盈利 |
| 🟢低 | ICHIMOKU | ✅ 已弃 | ICHIMOKU_a/b/base/conv/... | 信号爆炸风险高 |
| 🟢低 | KST | ✅ 已弃 | KST/KST_signal | 全invalid, A股无效 |
| 🟢低 | MASS | ✅ 已弃 | MASS_{fast}_{slow} | 0盈利 |
| 🟢低 | TSI | ✅ 已弃 | TSI_{slow}_{fast} | 信号爆炸(>0.02几乎always true) |
| 🟢低 | VORTEX | ✅ 已弃 | VORTEX_pos/neg_{length} | DeepSeek无法生成 |
| 🟢低 | WMA | ✅ 已弃 | WMA_{length} | 全invalid |
| 🟢低 | TRIX | ✅ 已弃 | TRIX_{length} | 6.2%盈利率, 很低 |
| 🟢低 | DPO | ✅ 已弃 | DPO_{length} | 0%盈利 |
| 🟢低 | PPO | ✅ 已弃 | PPO_{fast}_{slow}_{signal}/PPO_hist/PPO_signal | 全亏 |
| 🟢低 | PVO | ✅ 已弃 | PVO_{fast}_{slow}_{signal}/PVO_hist | 全亏 |
| 🟢低 | AO | ✅ 已弃 | AO_{fast}_{slow} | 0盈利 |
| 🟢低 | FI | ✅ 已弃 | FI_{length} | 全亏 |
| 🟢低 | EMV | ✅ 已弃 | EMV_{length}/EMV_ma_{length} | 全亏 |
| 🟢低 | ADI | ✅ 已弃 | ADI | PVO+ADI全亏 |
| 🟢低 | CMF | ✅ 已弃 | CMF_{length} | A股几乎永远为负 |
| 🟢低 | VWAP | ⚠️ 受限 | VWAP | 需field比较, DeepSeek不支持 |

**When all 未探索 indicators are exhausted:**
- Revisit 浅探索 indicators (STC, MFI, WR, ROC) with new combinations
- Try **cross-family pairings** not yet tested (e.g., ULTOSC+PSAR, KELTNER+MACD)
- Try **new parameter configurations** for explored indicators (non-default periods)
- Try **re-testing 已弃 indicators** with clone-backtest approach (bypasses DeepSeek failures that may have caused original failures)

### 3b: Plan Generation Rules

**Generate exactly N plans per round** (N from `auto N` argument, default 50; in `time` mode, target ~50-75 experiments to produce ~300 strategies). If you cannot generate N, explain why (e.g. all directions exhausted) and generate as many as feasible.

For **DeepSeek experiments**, prepare:
- `theme`: Descriptive Chinese name (e.g. "KDJ+RSI双确认趋势策略")
- `source_text`: Detailed strategy description for DeepSeek. Be specific about:
  - Which indicators to use and their parameters
  - The market hypothesis being tested
  - Target market regime (震荡/牛市/熊市)
  - Desired holding period and risk tolerance
  - Key: keep to 2 indicators max, 3-4 buy conditions
  - **CRITICAL**: Only describe conditions as indicator vs numeric threshold comparisons

For **Grid search experiments**, prepare:
- `source_strategy_id`: The ID of the strategy to clone
- `parameter_grid`: List of (stop_loss, take_profit, max_hold_days) combinations to test
- One clone-backtest call per parameter combination

For **Variant testing**, prepare:
- `source_strategy_id`: The strategy to modify
- `modification`: What to change (add condition, remove condition, adjust threshold)

### 3c: Rule Engine Constraints (apply to ALL plan types)

- ✅ Supported: Single indicator vs numeric value (e.g. `KDJ_K < 20`, `RSI_14 > 70`, `MACD_hist > 0`)
- ✅ Supported: Crossover conditions (K上穿D = `KDJ_K > KDJ_D` with same-indicator params)
- ✅ Supported: Price vs MA/EMA (e.g. `close > MA_5`), field-to-field with `compare_type: "field"`
- ✅ Supported: Volume conditions (e.g. `volume > volume_ma_5`)
- ✅ Supported: New P4 types: `lookback_min/max`, `consecutive`, `pct_change`, `pct_diff`
- ❌ AVOID: CMF indicator (persistently negative in A-shares), OBV, VWAP standalone
- ⚠️ DANGER: Overly permissive conditions cause "signal explosion". Keep thresholds tight.
- In source_text, explicitly tell DeepSeek: "禁止使用OBV指标" and "所有条件必须是指标与数值的比较"

## Step 4: Present Plan (semi-auto only)

Show the full plan in a table:

```
本轮探索计划 (N个实验):

| # | 类型 | 主题 | 方向 | 假设 |
|---|------|------|------|------|
| 1 | DeepSeek | ... | 指标组合 | ... |
| 2 | DeepSeek | ... | 震荡市 | ... |
| 3 | Grid | S1277 SL{5,8,10}×TP{10,15,20} | 参数优化 | 宽止损更优 |
| 4 | Variant | S1334 去掉ADX条件 | 变体测试 | ADX可能过滤掉好信号 |
| ... | ... | ... | ... | ... |
| 10+ | ... | ... | ... | ... |

确认执行？你可以调整主题、增减数量、或跳过某个。
```

In **auto mode** or **time mode**, skip this step and proceed directly.

## Step 5: Execute Experiments

**IMPORTANT: Serial Execution Constraint**
The backend enforces **single-backtest execution** (Semaphore=1). Only one strategy can be backtesting at a time. This protects the database from concurrent write conflicts and keeps CPU load manageable. When multiple experiments are submitted, strategies will queue and execute one by one. Expect ~3-5 min per strategy backtest, so 10 experiments × 4 strategies = ~40 strategies × 4 min ≈ 2.5 hours total.

For each approved topic, create an experiment via API. The POST endpoint returns an SSE stream — the experiment is created synchronously but the stream blocks. Use background curl pattern:

```bash
# Launch experiment — use & to background the curl, sleep to let DB commit
NO_PROXY=localhost,127.0.0.1 curl -s --max-time 120 -X POST http://127.0.0.1:8050/api/lab/experiments \
  -H "Content-Type: application/json" \
  -d '{"theme":"主题名","source_type":"custom","source_text":"详细描述...","initial_capital":100000,"max_positions":10,"max_position_pct":30}' &
PID=$!
sleep 3
kill $PID 2>/dev/null; wait $PID 2>/dev/null
```

After creating all experiments, verify they exist:
```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments?page=1&size=5"
```

Poll for completion every 60 seconds using a background loop:
```bash
for i in $(seq 1 30); do
  sleep 60
  # Check each experiment status
  for id in ID1 ID2 ID3; do
    NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments/$id" | \
      python3 -c "import json,sys; d=json.load(sys.stdin); s=d.get('strategies',[]); done=sum(1 for x in s if x.get('status') in ('done','invalid','failed')); print(f'ID{d[\"id\"]}:{d[\"status\"]}({done}/{len(s)})')"
  done
  # Break when all done/failed
done
```

Wait until all experiments have status `done` or `failed`.

## Step 6: Analyze Results

For each completed experiment, fetch full strategy data:
```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/lab/experiments/{id}"
```

Calculate and report:
- **Profitability rate**: profitable / (total - zero_trade - failed - invalid)
- **Best strategy**: name, score, return%, drawdown%
- **Per-regime performance**: parse `regime_stats` from each strategy with status=done
- **Comparison**: How does this compare with existing best strategies?
- **Invalid count**: How many strategies were `invalid` (rule engine rejection)

Generate insights — specifically look for:
- New findings that contradict or extend existing core insights
- Parameter combinations that work well in specific market regimes
- Whether this direction is worth further exploration or should be marked "已弃"
- **New indicator results**: How did the mandatory new indicator experiments perform? Update the Indicator Exploration Tracker status (未探索→浅探索 or 已探索 or 已弃)

### Problem Detection & Self-Healing

After analyzing results, check for these problems and **fix them before continuing**:

**Problem: High invalid rate (>50% strategies invalid)**
→ The source_text likely used conditions the rule engine can't express.
→ Fix: Redesign the experiment with simpler, numeric-threshold-only conditions and resubmit.
→ Do NOT ask the user — just fix it and retry once.

**Problem: All strategies zero-trade**
→ Buy conditions are too restrictive or contradictory.
→ Fix: Loosen thresholds (e.g. RSI<35 → RSI<45, reduce condition count to 3).
→ Resubmit as a new experiment with "(宽松版)" appended to theme.

**Problem: Experiment stuck in `generating` for >5 min**
→ DeepSeek API may have timed out.
→ Fix: Check experiment status. If still generating after 5 min, the experiment may need manual intervention — note it and move to the next experiment.

**Problem: Experiment status `failed`**
→ Read the error message from the experiment detail.
→ Fix: If it's a data issue, try again. If it's a systematic issue, note it in 已知问题 and skip.

Only after all fixable problems are resolved, proceed to Step 7.

## Step 7: Auto-Promote

**IMPORTANT**: Promote applies to ALL experiments, not just the current round. Every run of this skill must scan the entire experiment history for qualifying strategies that haven't been promoted yet.

### 7a: Scan ALL experiments for Standard A

Query all experiments and check every `status=done` strategy against Standard A criteria. The promote API is idempotent — if already promoted it returns `{"message": "Already promoted"}`, so it's safe to call on all qualifying strategies.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

LABEL_TO_CATEGORY = {'[AI]':'全能','[AI-牛市]':'牛市','[AI-熊市]':'熊市','[AI-震荡]':'震荡'}

def promote(sid, label):
    import urllib.parse
    encoded_label = urllib.parse.quote(label)
    cat = urllib.parse.quote(LABEL_TO_CATEGORY.get(label, ''))
    r = subprocess.run(['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label={encoded_label}&category={cat}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# Get all experiment IDs
exp_ids = [e['id'] for e in api('lab/experiments?page=1&size=100').get('items', [])]

# Standard A: score >= 0.75, ret > 60%, dd < 18%, trades >= 50, win_rate > 60%
promoted_a = []
for eid in exp_ids:
    for s in api(f'lab/experiments/{eid}').get('strategies', []):
        if s.get('status') != 'done': continue
        score = s.get('score',0) or 0
        ret = s.get('total_return_pct',0) or 0
        dd = abs(s.get('max_drawdown_pct',100) or 100)
        trades = s.get('total_trades',0) or 0
        wr = s.get('win_rate',0) or 0
        if score >= 0.75 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
            result = promote(s['id'], '[AI]')
            promoted_a.append((s['id'], s['name'], result.get('message','')))

# Standard B: regime champions with total_return > 0 and regime pnl > 100
bull_best = bear_best = side_best = None
for eid in exp_ids:
    for s in api(f'lab/experiments/{eid}').get('strategies', []):
        if s.get('status') != 'done': continue
        ret = s.get('total_return_pct',0) or 0
        if ret <= 0: continue
        regime = s.get('regime_stats', {})
        for rname, rdata in (regime or {}).items():
            pnl = rdata.get('total_pnl',0) or 0
            if pnl <= 100: continue
            if 'bull' in rname and (not bull_best or pnl > bull_best[1]):
                bull_best = (s, pnl)
            if 'bear' in rname and (not bear_best or pnl > bear_best[1]):
                bear_best = (s, pnl)
            if 'rang' in rname.lower() and (not side_best or pnl > side_best[1]):
                side_best = (s, pnl)

promoted_b = []
for champ, label in [(bull_best,'[AI-牛市]'),(bear_best,'[AI-熊市]'),(side_best,'[AI-震荡]')]:
    if champ:
        result = promote(champ[0]['id'], label)
        promoted_b.append((champ[0]['id'], champ[0]['name'], label, result.get('message','')))

print(f'Standard A: {len(promoted_a)} strategies')
for sid, name, msg in promoted_a:
    print(f'  ID{sid}: {name} -> {msg}')
print(f'Standard B: {len(promoted_b)} regime champions')
for sid, name, label, msg in promoted_b:
    print(f'  ID{sid}: {name} {label} -> {msg}')
"
```

**Standard A (高评分)** — ALL conditions must be met:
- `score >= 0.75`
- `total_return_pct > 60`
- `max_drawdown_pct < 18` (absolute value)
- `total_trades >= 50`
- `win_rate > 60`

**Standard B (市场阶段冠军)** — ALL conditions must be met:
- Has highest profit in a specific regime (bull/bear/sideways) across ALL experiments
- That regime's profit > 0 (from `regime_stats`)
- `total_return_pct > 0`
- That regime's `total_pnl > 100` (skip negligible profits like 26元 on 10万)

## Step 8: Update Memory

### 8a: Update experiment analysis doc

Edit `docs/lab-experiment-analysis.md`:

1. **Header**: Update experiment count, strategy count, profitability numbers
2. **探索状态**: Change topic status from "待探索" to "已探索", fill in 盈利率 and 最佳收益
3. **核心洞察**: Add new insights if discovered (keep total <= 20, merge or remove least impactful)
4. **Auto-Promote 记录**: Add promoted strategies with date, label, metrics, standard
5. **最佳策略 Top 15**: Update if any new strategy ranks higher
6. **全阶段盈利策略**: Add if a new strategy profits in all regimes
7. **各市场阶段最优**: Update top 3 per regime if improved

**Cleanup rules:**
- File must stay under 500 lines
- Don't add detailed per-strategy listings for non-profitable strategies
- If a direction is marked "已弃", keep only the summary line in 探索状态

### 8b: Sync to structured memory + Pinecone

After updating the experiment analysis doc, sync key findings into the memory system so they're searchable via Pinecone semantic search.

**1. Update `memory/semantic/strategy-knowledge.md`** — Rewrite this file with the latest condensed knowledge from `docs/lab-experiment-analysis.md`:
- Proven strategy families (top 5 with scores)
- What works / what doesn't work (key bullet points)
- Key numbers (experiments, strategies, profitability)
- Keep the YAML frontmatter intact, update `created` date

**2. Update the relevant episodic experiment note** — If this round falls into an existing note range (e.g. R16-R21), update it. If it's a new range, create a new file in `memory/episodic/experiments/` with proper YAML frontmatter:
```yaml
---
id: exp-rXX-rYY-topic
type: episodic/experiment
tags: [relevant, tags]
created: YYYY-MM-DD
relevance: high
related: [sem-strategy-knowledge]
---
```

**3. Run sync script** to push changes to Pinecone:
```bash
cd /Users/allenqiang/stockagent && python scripts/sync-memory.py
```

This ensures all experiment results are searchable by AI analysis, chat, and other semantic search consumers.

## Step 9: Output Summary

Present a concise summary:

```
## 本轮探索结果

**实验**: N 个主题, M 个策略生成, K 个盈利 (X%)
**最佳策略**: [name] — 收益 +X%, 评分 Y, 回撤 Z%
**🆕 新指标探索**: [indicator name] — [result summary: X/Y profitable, best score, verdict (有潜力/已弃/需深入)]
**新洞察**:
- [bullet points of new findings]
**Auto-Promote**: N 个策略已添加到策略库
  - [list promoted strategies with labels]
**问题修复**: [any problems detected and fixed during this round]
**下一步建议**: [what to explore next based on updated 探索状态]
```

## Step 9b: Save Exploration Round to API

After outputting the summary, call the API to save this round's record for the 探索历史 tab:

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/lab/exploration-rounds \
  -H "Content-Type: application/json" \
  -d '{
    "round_number": <本轮轮次>,
    "mode": "<auto|semi-auto>",
    "started_at": "<ISO datetime when this round started>",
    "finished_at": "<ISO datetime now>",
    "experiment_ids": [<关联实验ID列表>],
    "total_experiments": <实验数>,
    "total_strategies": <策略总数>,
    "profitable_count": <盈利策略数>,
    "profitability_pct": <盈利比例>,
    "std_a_count": <StdA数量>,
    "best_strategy_name": "<最佳策略名>",
    "best_strategy_score": <最高分>,
    "best_strategy_return": <最高收益>,
    "best_strategy_dd": <最高分策略回撤>,
    "insights": ["<洞察1>", "<洞察2>"],
    "promoted": [{"id": <id>, "name": "<名>", "label": "<标签>", "score": <分>}],
    "issues_resolved": ["<修复1>"],
    "next_suggestions": ["<建议1>"],
    "summary": "<Step 9 的完整 Markdown 摘要, JSON转义换行为\\n>",
    "memory_synced": <true|false from Step 8b>,
    "pinecone_synced": <true|false from Step 8b sync-memory.py>
  }'
```

Field notes:
- `memory_synced`: Whether Step 8b strategy-knowledge.md update + sync-memory.py succeeded
- `pinecone_synced`: Whether Step 8b sync-memory.py Pinecone upsert succeeded
- `summary`: The full Markdown summary from Step 9, with newlines escaped as `\n` for JSON
- If the API call fails, log the error but continue — don't block the exploration loop

### 9c: Background Auto-Finish Script Requirements

When creating a background auto_finish script (for long-running batch experiments that outlive the Claude session), the script **MUST** update the exploration round API record when it completes. This ensures Step 1d can detect and sync results in the next session.

**Required in every auto_finish script's `main()` function:**

```python
def api_put(path, data):
    """PUT request to update existing records."""
    import subprocess, json
    r = subprocess.run(
        ['curl', '-s', '-X', 'PUT', f'http://127.0.0.1:8050/api/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)

# After analysis and promotion, update the exploration round record
# (round_id should be saved when the round is first created in Step 9b)
api_put(f'lab/exploration-rounds/{round_id}', {
    "round_number": N,
    "mode": "auto",
    "started_at": started_at_iso,
    "finished_at": datetime.now().isoformat(),
    "total_experiments": total,
    "total_strategies": valid,
    "profitable_count": stda_count,
    "profitability_pct": stda_count / valid * 100,
    "std_a_count": stda_count,
    "best_strategy_name": best_name,
    "best_strategy_score": best_score,
    "best_strategy_return": best_return,
    "best_strategy_dd": best_dd,
    "insights": [...],
    "promoted": [...],
    "issues_resolved": [],
    "next_suggestions": [],
    "summary": summary_text,
    "memory_synced": False,  # Memory sync happens in next Claude session (Step 1d)
    "pinecone_synced": False,
})
```

**Key principle**: The script updates the API record with `memory_synced=False`. This signals to Step 1d in the next Claude session that memory files need to be synced. The Claude session then handles the actual memory file updates (which require file system access the background script doesn't have structured templates for).

## Auto Mode Loop

In auto mode, after Step 9b, check continuation conditions:

- **Should continue** if: there are unexplored directions AND last round had >= 1 profitable strategy (after retries)
- **Should stop** when:
  - All directions explored (no more "待探索" in 探索状态)
  - 2 consecutive rounds with 0 profitable strategies (even after self-healing retries)
  - Unrecoverable error (note it and stop gracefully)

### Round Transition Prompt (auto mode only)

If conditions say **should continue**, ask the user with `AskUserQuestion`:

```
question: "第N轮已完成 (M个StdA新策略)。继续下一轮探索？10秒无操作将自动继续。"
options:
  - "继续下一轮 (Recommended)" — proceed to next round
  - "停止探索" — skip to Step 10
```

**Auto-continue rule**: If the user selects "继续下一轮" OR does not respond within ~10 seconds, proceed to the next round (go back to Step 2). Use this pattern to implement the timeout:

1. Ask the question via `AskUserQuestion`
2. If user answers "继续下一轮" → go to Step 2
3. If user answers "停止探索" → go to Step 10
4. If user provides custom input → interpret intent and act accordingly

**Note**: The 10-second auto-continue is a UX goal. In practice, `AskUserQuestion` blocks until the user responds. The "10秒无操作自动继续" text signals to the user that they should respond quickly if they want to stop — otherwise the default action is to continue.

If conditions say **should stop**, skip the prompt and go directly to Step 10.

**IMPORTANT**: When exploration stops (either by user choice or stop conditions), do NOT end the session yet. Proceed to Step 10.

## Time Mode Loop

In `time` mode, the loop behaves differently from `auto` mode:

### Time Tracking

At the very start of the skill execution, record the start time and parse the duration:
```python
import time
start_time = time.time()
# Parse "2h" → 7200, "90m" → 5400, "0.5h" → 1800
duration_str = "2h"  # from argument
if duration_str.endswith('h'):
    total_seconds = float(duration_str[:-1]) * 3600
elif duration_str.endswith('m'):
    total_seconds = float(duration_str[:-1]) * 60
else:
    total_seconds = float(duration_str) * 3600  # default to hours
```

### Time Check (before each round)

Before starting a new round, check remaining time:
```
elapsed = time.time() - start_time
remaining = total_seconds - elapsed
remaining_min = remaining / 60
```

Display the clock:
```
⏱️ 已用时: {elapsed_h}h {elapsed_m}m / 总计: {total_h}h | 剩余: {remaining_h}h {remaining_m}m
```

**Exit condition**: If `remaining_min < 30`, stop and proceed to Step 10. This ensures there's enough time to complete at least a partial round with memory sync.

### Round Transition (time mode)

In `time` mode, do NOT use `AskUserQuestion` between rounds. Instead:
1. Check remaining time
2. If remaining >= 30 min → immediately start next round (go to Step 2)
3. If remaining < 30 min → proceed to Step 10

The standard `auto` mode stop conditions also apply (2 consecutive 0-profit rounds, all directions exhausted, unrecoverable error).

### Graceful Timeout Handling

If a round's backtests are still running when time is about to expire (remaining < 15 min during Step 5 polling):
1. Stop polling — do NOT wait for all backtests to finish
2. Create a background `auto_finish` script (per Step 9c) to handle the remaining backtests
3. Run Steps 6-9 on whatever results are already available
4. Proceed to Step 10 for the final session summary
5. The unfinished backtests will be picked up by Step 1d in the next session

### Time Mode in Step 9b

When saving the exploration round to API, set `mode` to `"time"` and include the duration:
```json
{
    "mode": "time",
    "summary": "... (time mode: 2h, 实际用时: 1h 47m) ..."
}
```

## Step 10: Resolve Problems & Execute Follow-Up Actions

Before the session can end, ALL identified problems and follow-up suggestions must be addressed. This is the most important step — exploration produces insights, but this step produces actual improvements.

### 10a: Triage Issues

Collect all items from:
1. **已知问题** table in `docs/lab-experiment-analysis.md` — any with status not "已修复"
2. **下一步建议** from the Step 9 summary
3. **Problems detected** during this session (zombie experiments, DeepSeek limitations, etc.)

For each item, classify it:
- **🔧 Fixable now**: Can be resolved with code changes, API calls, or configuration. DO IT.
- **🏗️ Needs new feature**: Requires implementing new backend/frontend code. IMPLEMENT IT or create a concrete design plan.
- **⏳ Blocked externally**: Requires external dependency (e.g., third-party API, data source). Document clearly and skip.

### 10b: Execute Fixes

Work through all 🔧 and 🏗️ items. Examples of what to do:

**Zombie experiments (stuck in backtesting for days)**
→ Fix: Investigate why they're stuck. Check if the backtest engine has a timeout. If not, add one. Mark the experiments as failed via API or direct DB update if API doesn't support it.

**Manual stop-loss/take-profit optimization (bypassing DeepSeek)**
→ Fix: Don't just suggest it — actually implement it. Read the top strategy's rules, clone it with modified stop-loss/take-profit params via the strategies API, and run a backtest. This bypasses DeepSeek's imprecision problem.

**P3 combo strategy (needs backend feature)**
→ Fix: Design and implement the backend feature. Create the API endpoint, the portfolio/signal combination logic, and any necessary DB models. Then test it with existing top strategies.

**Rule engine limitations (field-to-field comparison)**
→ Fix: If this would unlock high-value experiment directions (VWAP, BOLL bandwidth), implement the feature in `src/signals/rule_engine.py`. Then run the experiments that were previously blocked.

**DeepSeek can't precisely replicate strategies**
→ Fix: Implement a "clone + modify" API endpoint that copies an existing strategy's rules and only changes specific parameters (stop-loss %, take-profit %, position size). This enables parameter optimization without DeepSeek regeneration.

### 10c: Verify & Iterate

After executing fixes:
1. Re-run any experiments that were blocked by now-fixed issues
2. Re-check promote criteria — new fixes may produce promotable strategies
3. Update `docs/lab-experiment-analysis.md` with results from fixes
4. If a fix unlocked new experiment directions, go back to Step 3 and explore them

### 10d: Document Remaining Items

For any items classified as ⏳ or that couldn't be completed:
- Create a detailed TODO in `docs/lab-experiment-analysis.md` 已知问题 section
- Include: what's needed, why it's blocked, what would unblock it, expected impact

## Step 11: Round Summary & Loop Back

Only after Step 10 is complete, output a round summary:

```
## 本轮完整报告 (Round N)

**探索阶段**:
- 实验: M 个, 策略: K 个
- 盈利策略: X (Y%)
- Auto-Promote: Z 个新策略

**问题解决阶段**:
- 已修复: [list of fixed issues]
- 已实现新功能: [list of new features built]
- 剩余阻塞: [list of items that couldn't be resolved, with reasons]

**系统改进**:
- [concrete improvements made to the platform]
```

### Loop Back Decision

After outputting the summary, **loop back to Step 1** to start the next cycle. The full loop is:

```
Step 1 (Load Memory) → Step 1.5 (Resolve Issues) → Steps 2-9 (Explore) → Step 10 (Fix Problems) → Step 11 (Summary) → Step 1 (Loop Back)
```

This creates a continuous improvement cycle: each round's problem resolution (Step 10) may unlock new exploration directions or fix issues that improve the next round's results.

**The loop continues indefinitely** in auto mode. The only exit points are:
1. User explicitly says "停止" when prompted at the Round Transition (between Step 9 and Step 10)
2. Stop conditions are met (all directions explored, 2 consecutive 0-profit rounds, unrecoverable error)

**In `time` mode**, the loop continues until the time limit is reached (remaining < 30 min). No user prompt is shown between rounds. The loop exits automatically when time runs out.

When the loop does exit (user stops, stop conditions met, or time expired), output a **final session summary** instead:

```
## 全自动会话最终报告

**模式**: auto / time Xh
**总轮数**: N
**总用时**: Xh Ym (time mode only)
**累计实验**: M, 累计策略: K
**累计盈利策略**: X (Y%)
**累计Auto-Promote**: Z 个新策略
**累计问题修复**: [count of issues resolved across all rounds]
**下一次运行建议**: [what the NEXT session should focus on]
```
