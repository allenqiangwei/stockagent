---
name: explore-strategies
description: Iterative strategy discovery — analyze experiments, plan new ones, auto-promote winners, then resolve ALL identified problems and implement follow-up actions. Use /explore-strategies for semi-auto, /explore-strategies auto for full-auto (default 50), /explore-strategies auto N for N experiments, /explore-strategies time Xh for time-limited continuous exploration (300 strategies per batch).
---

# Strategy Explorer

You are a quantitative strategy researcher for the Chinese A-share market. Your job is to systematically discover profitable strategies through iterative experimentation using the AI Lab system.

## Automated Engine (Alternative)

An automated Exploration Workflow Engine is available at `POST /api/exploration-workflow/`. It implements the same 11-step pipeline as this skill but runs autonomously with LLM planning (Qwen/DeepSeek).

```bash
# Start automated exploration (no Claude session needed)
curl -X POST "localhost:8050/api/exploration-workflow/start?rounds=3&experiments_per_round=50"

# Monitor status
curl "localhost:8050/api/exploration-workflow/status"

# Stop gracefully
curl -X POST "localhost:8050/api/exploration-workflow/stop"
```

Engine code: `api/services/exploration_engine.py`. Factor registry: `src/factors/registry.py` (37 factors auto-discovered via `@register_factor`).

**When to use this skill vs the engine:**
- This skill: complex analysis, memory updates, code fixes, new feature implementation, manual direction control
- Engine API: routine exploration rounds, unattended batch runs, overnight execution

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
- **下一步建议**: Previous session's prioritized suggestions for what to explore next (HIGH PRIORITY — these are the most informed recommendations from the prior session's analysis)

Also query the latest exploration round's `next_suggestions` from the API to cross-check:

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

rounds = api('lab/exploration-rounds')
items = rounds.get('items', rounds) if isinstance(rounds, dict) else rounds
if items:
    latest = max(items, key=lambda r: r.get('round_number', 0))
    print(f'最新轮次: R{latest[\"round_number\"]}')
    suggestions = latest.get('next_suggestions', [])
    if suggestions:
        print('上轮建议:')
        for i, s in enumerate(suggestions, 1):
            print(f'  {i}. {s}')
    else:
        print('上轮无建议')
else:
    print('无历史轮次')
"
```

**Use both sources** (the `## 下一步建议` section in the doc AND the API `next_suggestions`) to inform Step 3's direction allocation. The doc section is the canonical source; the API field is a backup.

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
        if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
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

### 1e: Indicator Family Status Check (3-Tier Taxonomy)

**在规划新实验之前，查询当前指标家族（Level 1）的填充状态，确定资源分配方向。**

指标家族（Indicator Family）= 买入条件中使用的核心指标集合（如 `ATR+RSI`、`KDJ+PSAR+VPT`）。
每个家族根据其所有冠军策略的平均得分获得动态配额（quota）：
- avg_score >= 0.87 -> quota = 200
- avg_score >= 0.85 -> quota = 150
- avg_score >= 0.83 -> quota = 100
- avg_score >= 0.81 -> quota = 50
- avg_score < 0.81 -> quota = 20

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

status = api('strategies/pool/status')
families = status.get('family_summary', [])

unfull_families = [f for f in families if f.get('gap', 0) > 0]
full_families = [f for f in families if f.get('gap', 0) == 0]

print(f'=== 指标家族状态 (Level 1) ===')
print(f'总家族数: {len(families)}  (未满: {len(unfull_families)}, 已满: {len(full_families)})')
print()

print('未满家族 (gap>0，补充填充，30%资源):')
for f in sorted(unfull_families, key=lambda x: -x.get('gap', 0))[:10]:
    print(f'  {f[\"family\"]:30s} | {f[\"active_count\"]}/{f[\"quota\"]} (gap={f[\"gap\"]}) avg={f[\"avg_score\"]:.4f} fp={f[\"fingerprint_count\"]}')

print()
print('已满家族 (gap=0，优胜劣汰，10%资源):')
for f in sorted(full_families, key=lambda x: x.get('avg_score', 0))[:5]:
    print(f'  {f[\"family\"]:30s} | {f[\"active_count\"]}/{f[\"quota\"]} avg={f[\"avg_score\"]:.4f}')
"
```

**结果解读（将三类骨架列表带入 Step 3a）：**

- 🟡 **未满骨架** (`current < quota`)：骨架已有冠军但数量未达配额。继续探索这一骨架的参数变体、不同指标组合，可提升覆盖度。
- 🔴 **已满骨架** (`current >= quota`)：骨架配额已满，只有超越当前最弱冠军分数的新策略才能进入。优先探索改良方向，淘汰弱者。

> **⚠️ 注意**: Step 1e 只检查已有骨架的填充状态。**新骨架候选**由下方 Step 1f 生成，不在此步骤中出现。如果 Step 1e 显示"新骨架=0"，这是正常的——新骨架方向来自 Step 1f。

### 1f: New Skeleton Candidate Generator (MANDATORY)

**这是每轮探索最重要的步骤。** Step 1e 只检查池里已有的骨架，而本步骤主动枚举**池中不存在、但值得尝试的全新指标组合**。60%资源分配的"新骨架"来源于此步骤的输出，而非 Step 1e。

**核心原则**: 探索必须持续扩展信号空间的多样性，不能退化为纯参数优化。

#### 候选生成方法

**方法1: 指标组合矩阵**

从 Indicator Exploration Tracker（Step 3a-extra）中选取所有有效指标（非"已弃"），生成**两两组合 + 三元组合**的候选矩阵，然后排除已在池中存在的组合。

有效指标池（从 Tracker 中非"已弃"的指标）:
- 震荡类: KDJ, RSI, STOCH, STOCHRSI, ULTOSC, MFI(弱)
- 趋势类: MACD, PSAR, EMA, KAMA, ADX
- 波动类: ATR, BOLL, KELTNER, ULCER
- 量价类: VPT
- 多时间框架: W_RSI, W_EMA, W_ATR, W_KDJ (全部未探索!)

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json, re, itertools
from collections import defaultdict

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# Step 1: Get existing pool skeleton indicator sets
status = api('strategies/pool/status')
families = status.get('families_summary', [])

existing_indicator_sets = set()
for f in families:
    name = f.get('representative_name', '')
    if f.get('active_count', 0) == 0: continue
    # Extract indicator names from strategy name
    indicators = set()
    for ind in ['KDJ','MACD','RSI','PSAR','BOLL','VPT','ATR','EMA','KAMA','ULTOSC','ULCER','KELTNER','STOCH','STOCHRSI','ADX','CCI','MFI','ROC','NVI','W_']:
        if ind in name.upper() or ind in name:
            indicators.add(ind)
    if indicators:
        existing_indicator_sets.add(frozenset(indicators))

print(f'现有池中指标组合数: {len(existing_indicator_sets)}')
for s in sorted(existing_indicator_sets, key=lambda x: len(x)):
    print(f'  {sorted(s)}')

# Step 2: Generate candidate new combinations
# Effective indicators (non-abandoned)
effective = ['KDJ', 'RSI', 'MACD', 'PSAR', 'BOLL', 'ATR', 'EMA', 'KAMA', 'ULTOSC', 'ULCER', 'KELTNER', 'STOCH', 'STOCHRSI', 'VPT', 'ADX']
weekly = ['W_RSI', 'W_EMA', 'W_ATR', 'W_KDJ']

# Generate 2-indicator combos
candidates_2 = []
for a, b in itertools.combinations(effective, 2):
    combo = frozenset([a, b])
    if combo not in existing_indicator_sets:
        candidates_2.append(sorted([a, b]))

# Generate weekly + daily combos (always new since W_ never tested)
candidates_w = []
for w in weekly:
    for d in effective[:8]:  # top 8 daily indicators
        candidates_w.append([w, d])

# Generate 3-indicator combos (only with proven base indicators)
proven_base = ['KDJ', 'PSAR', 'MACD', 'RSI']
candidates_3 = []
for base in proven_base:
    for a, b in itertools.combinations(effective, 2):
        if base in (a, b): continue
        combo = frozenset([base, a, b])
        if combo not in existing_indicator_sets:
            candidates_3.append(sorted([base, a, b]))

print(f'\\n=== 新骨架候选 ===')
print(f'两指标组合 (池中不存在): {len(candidates_2)}')
for c in candidates_2[:10]:
    print(f'  {c}')
if len(candidates_2) > 10: print(f'  ... 共{len(candidates_2)}个')

print(f'\\n周线+日线组合 (全部未探索): {len(candidates_w)}')
for c in candidates_w[:8]:
    print(f'  {c}')

print(f'\\n三指标组合 (池中不存在): {len(candidates_3)}')
for c in candidates_3[:8]:
    print(f'  ... 共{len(candidates_3)}个')

total_candidates = len(candidates_2) + len(candidates_w) + len(candidates_3)
print(f'\\n🆕 总候选新骨架数: {total_candidates}')
print(f'   (两指标: {len(candidates_2)}, 周线: {len(candidates_w)}, 三指标: {len(candidates_3)})')
"
```

**方法2: 条件结构变异**

即使使用相同指标，不同的条件逻辑结构也可以创造新骨架：
- **交叉条件**: `KDJ_K > KDJ_D`（金叉）vs `KDJ_K < 20`（绝对阈值）— 不同逻辑
- **多时间框架过滤**: 日线 KDJ + `W_RSI_14 < 70`（周线超买过滤）
- **复合条件**: `ATR pct_change` + `volume consecutive` — 波动率+量能双确认
- **反向条件**: 做空信号作为卖出条件（如 `RSI > 80` 作为平仓触发）

**方法3: 从实验历史中发现遗漏**

查询所有已完成实验中产出过 StdA+ 策略、但从未被 promote 到池中的指标组合：

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
# Check if there are StdA+ experiment strategies with indicator combos not in the pool
# This finds 'proven but unrepresented' skeletons
import subprocess, json

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    try: return json.loads(r.stdout)
    except: return {}

# Sample recent experiments for high-scoring strategies not yet in pool patterns
# (This is a heuristic — full scan would be too slow)
print('Checking recent experiments for underrepresented skeletons...')
found = {}
for page in range(1, 5):
    exps = api(f'lab/experiments?page={page}&size=50')
    for exp in exps.get('items', []):
        theme = exp.get('theme', '')
        if exp.get('best_score', 0) and exp['best_score'] >= 0.80:
            # Extract indicator combo from theme
            key = theme.split('×')[0].strip()[:40] if '×' in theme else theme[:40]
            if key not in found or exp['best_score'] > found[key]:
                found[key] = exp['best_score']

for k, v in sorted(found.items(), key=lambda x: -x[1])[:10]:
    print(f'  {k} → best score {v:.4f}')
"
```

#### 输出格式

Step 1f 必须输出**至少10个具体的新骨架候选方向**，按优先级排序：

```
🆕 新骨架候选 (Step 1f):
优先级1: [W_RSI + KDJ] — 周线超买过滤+日线超卖信号，多时间框架完全未探索
优先级2: [KELTNER + KDJ] — Keltner通道+KDJ，Keltner已验证37.5%盈利率但未进池
优先级3: [ULCER + PSAR] — 低波动+趋势反转，三重过滤曾71%盈利率
优先级4: [STOCHRSI + PSAR] — 灵敏震荡+趋势，StochRSI已达StdA
优先级5: [W_EMA + RSI + ATR] — 周线趋势+日线动量+波动过滤
...
```

**硬性约束**: 如果 Step 1f 输出候选数 < 5，说明指标空间已接近穷尽，应切换到"条件结构变异"或"多时间框架"方向，而非放弃新骨架探索。

#### 失败记录与候选淘汰

Step 1f 必须读取 `docs/lab-experiment-analysis.md` 中的 **新骨架探索记录** 表，排除已标记"已弃"的组合。每轮 Step 8（Update Memory）必须更新此表。

**表格格式**（在 `docs/lab-experiment-analysis.md` 中维护）:

```markdown
## 新骨架探索记录

| 指标组合 | 首次尝试轮次 | 实验数 | 最佳score | 最佳StdA+数 | 状态 |
|---------|------------|--------|----------|------------|------|
| KELTNER+KDJ | R1190 | 5 | 0.72 | 0 | 浅探索 |
| W_RSI+KDJ | R1190 | 8 | 0.85 | 3 | ✅已进池 |
| ULCER+PSAR | R1190 | 5 | 0.65 | 0 | 已弃(2轮0 StdA+) |
```

**状态流转规则**:
- **未探索** → 首次出现在 Step 1f 候选列表中
- **浅探索** → 已测试 < 10 个实验，结果不确定（有盈利但未达StdA+），下轮可再测
- **✅已进池** → 产出 ≥ 1 个 StdA+ 且已 promote 到策略池，Step 1f 不再推荐（池中已有）
- **已弃** → 累计 ≥ 2 轮探索、≥ 10 个实验、0 个 StdA+。Step 1f 永久排除此组合

**Step 1f 生成候选时必须**:
1. 读取此表，排除状态为"已弃"和"✅已进池"的组合
2. 优先推荐状态为"浅探索"的组合（已有初步数据，值得深入）
3. 其次推荐"未探索"的全新组合

**Step 8 更新此表时必须**:
1. 本轮新尝试的组合 → 新增行或更新实验数/最佳score
2. 累计 ≥ 2 轮 + ≥ 10 实验 + 0 StdA+ → 标记"已弃"
3. 产出 StdA+ 并 promote → 标记"✅已进池"

这样候选池会随着探索**自然收缩**（失败的被淘汰、成功的进入池），同时通过三指标组合和多时间框架**持续补充新候选**，确保探索不会停滞也不会原地打转。

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

### 3a: Decision Framework — Skeleton-Driven Three-Tier Allocation

根据 **Step 1f 的新骨架候选** + **Step 1e 的骨架填充状态**，使用**固定三层比例**分配本轮实验资源：

```
本轮分配 (共N个实验):
┌───────────────────────────────────────────────────────────────────────────┐
│ 🆕 新骨架探索    60% (N×0.6 个) — 来自 Step 1f 的候选新指标组合          │
│ 🟡 未满骨架填充  30% (N×0.3 个) — Step 1e 中 current < quota 的骨架      │
│ 🔴 已满骨架优化  10% (N×0.1 个) — 针对最弱 champion 的定向改良           │
└───────────────────────────────────────────────────────────────────────────┘
⚠️ 60%是硬约束：即使 Step 1f 候选全部失败也不得挪用给填充/优化层。
⚠️ 新骨架来源是 Step 1f（候选生成器），NOT Step 1e（已有池检查）。
```

**三层目标说明：**

**🆕 新骨架探索 (60%)**
目标：从 **Step 1f 的候选列表**中选取方向，创造策略池中不存在的全新信号结构。
- **来源**: Step 1f 输出的候选新骨架列表（NOT Step 1e 的 current=0 列表）
- 按 Step 1f 的优先级排序，每个候选方向分配 3-8 个实验（不同参数配置 + 不同卖出条件）
- 对每个候选方向：先用 **batch-clone-backtest + buy_conditions override** 构造条件（绕过 DeepSeek），只有无法构造时才用 DeepSeek
- 多时间框架（W_ 前缀）候选享有最高优先级，因为这是完全未探索的新维度
- 成功标准：实验产生至少一个通过 StdA+ 的策略，即视为新骨架探索成功
- **硬性约束**: 即使所有 Step 1f 候选的实验都失败（0 StdA+），也不得将此60%资源挪给未满骨架填充。宁可在失败的候选上做二次变体测试（更宽阈值、不同参数），也要保持60%的新骨架探索比例

**🟡 未满骨架填充 (30%)**
目标：在已验证有效的骨架结构中，补充覆盖缺失的参数空间。
- 从 Step 1e 的 `unfull_skeletons` 中选取 `gap` 最大的骨架优先填充
- 分析该骨架已有冠军的参数范围（SL/TP/MHD），找出尚未覆盖的参数区间
- 使用 `batch-clone-backtest` 针对已有冠军 ES_ID 进行参数网格搜索
- 若骨架有多个 fingerprint 家族，重点对分数靠前但参数覆盖不全的家族做变体

**🔴 已满骨架优化 (10%)**
目标：在配额已满的骨架中，针对最弱 champion 进行定向改良，实现优胜劣汰。
- 从 Step 1e 的 `full_skeletons` 中选取 `avg_score` 最低的骨架
- 查询该骨架最弱 champion 的具体参数和失分原因（drawdown/win_rate/return 哪项最弱）
- 设计针对性改良：若 win_rate 低 → 调整 TP 阈值；若 drawdown 大 → 收紧 SL；若 return 低 → 增大 MHD
- 新策略必须超过该骨架当前最弱 champion 分数才能进入 pool（见 promote 竞争门槛）

**约束规则：**
- 已弃方向（"已弃"标记）：分配 ZERO，除非 Step 1.5 修复了原始阻断问题
- 下一步建议：上轮遗留的高优先级建议转化为实验，优先归入对应骨架层
- **60%硬约束**: 新骨架探索的60%比例不可挪用。如果 Step 1f 候选不足，必须通过"条件结构变异"或"多时间框架"方向补足，而非将资源分给填充/优化层
- **禁止退化为纯参数优化**: 如果本轮全部实验都是对已有骨架的 SL/TP/MHD 网格搜索，视为违反 skill 设计意图。至少60%实验必须包含**不同的 buy_conditions 指标组合**
- **新骨架 ≠ 池中 current=0**: "新骨架"定义为 Step 1f 生成的**策略池中不存在该指标组合**的候选，不是 Step 1e 的 current=0 分类

**分配汇总输出（在列出实验前必须展示）：**

```
本轮三层分配 (共N个实验):
- 🆕 新骨架探索: X个 (目标骨架: [骨架名称/新指标组合]) — [简要理由]
- 🟡 未满骨架填充: Y个 (目标骨架: [骨架名称], gap=[N]) — [简要理由]
- 🔴 已满骨架优化: Z个 (目标骨架: [骨架名称], 最弱score=[N]) — [简要理由]
(X + Y + Z = N)
```

Available experiment methods (可用于任意层):

| Method | Description | 适合层 |
|--------|-------------|--------|
| **DeepSeek exploration** | 生成新骨架策略（指定新指标组合） | 🆕 新骨架 |
| **批量克隆回测 (clone-backtest)** | 对现有 ES_ID 做参数网格搜索 | 🟡 未满/🔴 已满 |
| **Variant testing** | 对冠军策略做条件微调（加/减一个条件） | 🟡 未满/🔴 已满 |
| **New direction** | 尚未测试的市场假设或新条件类型 | 🆕 新骨架 |

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
| 🔴高 | **NVI** | ✅ 已弃 | NVI | R32+R383探索, 79%invalid(19/24), 0 StdA+, best=0.6972. NVI不适合A股短线策略 |
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

**Alpha Factors (8 groups, 26+ sub-fields) — updated from R1208-R1221 exploration:**

| Priority | Factor | Status | Sub-fields | Exploration Results |
|----------|--------|--------|------------|---------------------|
| 🔴高 | **PPOS** | ⚠️ 部分有效 | PPOS_close_pos, PPOS_high_dist, PPOS_low_dist, PPOS_drawdown, PPOS_consec_dir | close_pos ❌已弃(wr<45%), consec_dir ❌已弃. **high_dist ✅有效**(0.8676), **drawdown ✅有效**(0.8196). low_dist ❌无效 |
| 🔴高 | **KBAR** | ✅ 深度探索 | KBAR_upper_shadow, KBAR_lower_shadow, KBAR_body_ratio, KBAR_amplitude, KBAR_overnight_ret, KBAR_intraday_ret | **amplitude ✅最强**(0.8790, 40-50% StdA+率). body_ratio ✅有效(0.8635). lower_shadow ✅有效. upper_shadow/overnight/intraday ❌无效(wr<60%) |
| 🔴高 | **REALVOL** | ✅ 深度探索 | REALVOL, REALVOL_skew, REALVOL_kurt, REALVOL_downside | **REALVOL ✅**(50%率, 0.8775). **kurt ✅**(36%, 0.8784). **downside ✅**(20%, 0.8778). skew ✅(10%, 0.8552). Ultra-low TP解决wr: REALVOL 15/15=100% |
| 🔴高 | **MOM** | ✅ 已探索 | MOM | MOM>0 ✅有效(20%, 0.8401). 与KBAR/RSTR combo有效 |
| 🟡中 | **PVOL** | ✅ 已探索 | PVOL_corr, PVOL_amount_conc, PVOL_vwap_bias | **corr ✅有效**(0.8665). **amount_conc ✅有效**(50%, 0.8781). vwap_bias ❌已弃 |
| 🟡中 | **LIQ** | ⚠️ 部分有效 | LIQ_amihud, LIQ_turnover_vol, LIQ_log_amount | amihud ❌已弃(太restrictive). turnover_vol ✅有效. log_amount ✅新增(未充分测试) |
| 🟡中 | **RSTR** | ✅ 已探索 | RSTR, RSTR_weighted | **weighted ✅有效**(61.5%, 0.8737). RSTR ✅有效 |
| 🟡中 | **AMPVOL** | ✅ 深度探索 | AMPVOL_std, AMPVOL_parkinson | **std ✅最强之一**(58.6%, 0.8730). parkinson ❌已弃(太restrictive, 8 trades) |
| 🟢新 | **NEWS_SENTIMENT** | ❌ 未探索 | NEWS_SENTIMENT_3D, NEWS_SENTIMENT_7D | 新闻情绪因子, 3日/7日聚合. 可与任何骨架组合. **高优先级新方向** |

**因子系统已重构**: 所有因子通过 `@register_factor` 装饰器注册在 `src/factors/` 目录下。新增因子自动出现在探索引擎中（`api/services/exploration_engine.py` 从 registry 动态构建因子列表）。

**当前可用因子**: 37 个（从 registry 自动构建），包含 W_ 周线变体。查看完整列表:
```bash
python3 -c "from api.services.exploration_engine import VALID_BUY_FACTORS; print(len(VALID_BUY_FACTORS), 'factors'); [print(f'  {k}') for k in sorted(VALID_BUY_FACTORS)]"
```

**Factor condition format (P36: MUST use compare_value!):**
```json
{"field": "PPOS_high_dist", "operator": "<", "compare_type": "value", "compare_value": -5, "params": {"period": 20}}
{"field": "KBAR_amplitude", "operator": "<", "compare_type": "value", "compare_value": 0.03}
{"field": "REALVOL", "operator": "<", "compare_type": "value", "compare_value": 25, "params": {"period": 20}}
{"field": "NEWS_SENTIMENT_3D", "operator": ">", "compare_type": "value", "compare_value": 0.3}
{"field": "AMPVOL_std", "operator": "<", "compare_type": "value", "compare_value": 0.02, "params": {"period": 5}}
```

**Multi-Timeframe indicators (W_ / M_ prefix):**

Any indicator above can be prefixed with `W_` (weekly) or `M_` (monthly). Weekly data is resampled from daily, forward-filled. **R1208-R1217验证: 6/8 W_指标产出StdA+(75%成功率)**

| Prefix | Timeframe | 已验证有效 |
|--------|-----------|-----------|
| W_ | 周线 | W_REALVOL✅, W_KBAR✅, W_AMPVOL_std✅, W_RSTR_weighted✅, W_ATR✅, W_PVOL_corr✅, W_ADX✅, W_MOM✅ |
| M_ | 月线 | M_REALVOL✅ |

**Proven effective combinations (from R1208-R1221):**
- **单因子最强**: KBAR_amplitude(0.8790), REALVOL_kurt(0.8784), AMPVOL_std(0.8730)
- **双因子最强**: KBAR_amp+W_REALVOL(42%), AMPVOL_std+KBAR_amp(50%), RSTR_w+KBAR(57%)
- **5因子combo**: ATR+RSI+RVkurt+KBAR+W_REALVOL = 0.8791(session最高)
- **Ultra-low TP通用修复**: 任何高score低wr因子用TP=0.3-1.0可达100% StdA+率

**When all indicators are explored:**
- Try **NEWS_SENTIMENT** — 全新维度，未测试
- Try **multi-factor combos** with 3-5 proven factors
- Try **ultra-low TP** for high-score factors with wr<60%
- Use **exploration engine API** for automated execution: `POST /api/exploration-workflow/start?rounds=3&experiments_per_round=50`

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

# Standard A: score >= 0.80, ret > 60%, dd < 18%, trades >= 50, win_rate > 60%
promoted_a = []
for eid in exp_ids:
    for s in api(f'lab/experiments/{eid}').get('strategies', []):
        if s.get('status') != 'done': continue
        score = s.get('score',0) or 0
        ret = s.get('total_return_pct',0) or 0
        dd = abs(s.get('max_drawdown_pct',100) or 100)
        trades = s.get('total_trades',0) or 0
        wr = s.get('win_rate',0) or 0
        if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
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
- `score >= 0.80`
- `total_return_pct > 60`
- `max_drawdown_pct < 18` (absolute value)
- `total_trades >= 50`
- `win_rate > 60`

**Standard B (市场阶段冠军)** — ALL conditions must be met:
- Has highest profit in a specific regime (bull/bear/sideways) across ALL experiments
- That regime's profit > 0 (from `regime_stats`)
- `total_return_pct > 0`
- That regime's `total_pnl > 100` (skip negligible profits like 26元 on 10万)

## Step 7b: Strategy Pool Rebalance

After promoting new strategies, rebalance the pool to archive redundant strategies (same buy/sell conditions, only exit params differ). Each signal fingerprint family keeps max 15 active members.

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api_post(path, params=''):
    url = f'http://127.0.0.1:8050/api/{path}'
    if params: url += f'?{params}'
    r = subprocess.run(['curl','-s','-X','POST',url],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# Dry-run first to see impact
dry = api_post('strategies/pool/rebalance', 'max_per_family=15&dry_run=true')
print(f'Dry-run: {dry.get(\"families_count\",0)} families, would archive {dry.get(\"archived_count\",0)}, active={dry.get(\"active_strategies\",0)}')

# Execute rebalance
result = api_post('strategies/pool/rebalance', 'max_per_family=15')
print(f'Rebalance: {result.get(\"families_count\",0)} families, archived {result.get(\"archived_count\",0)}, active={result.get(\"active_strategies\",0)}')
"
```

Output summary:
```
策略池 Rebalance: X 家族, 归档 Y 个冗余策略, 当前活跃 Z 个
```

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
8. **下一步建议**: REPLACE (not append) the `## 下一步建议` section with this round's prioritized suggestions. Keep 4-8 actionable items ranked by expected impact. This section is read by Step 1a at the start of the next session.

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
