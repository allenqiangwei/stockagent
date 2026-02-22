# AI Strategy Selection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add AI strategy selection step before signal generation — Claude picks 3-5 strategy families based on market conditions, only those run.

**Architecture:** Two-phase Claude call integrated into existing scheduler. Phase 1 selects strategies, system generates signals, Phase 2 analyzes (existing flow).

**Tech Stack:** Python, SQLAlchemy, Claude CLI, FastAPI

---

### Task 1: Build strategy family summary function

**Files:**
- Create: `api/services/strategy_selector.py`

**Step 1: Create the module with both functions**

```python
"""Strategy family selector — groups strategies into families, builds summary for AI."""

import logging
import re
from sqlalchemy.orm import Session

from api.models.strategy import Strategy

logger = logging.getLogger(__name__)

_PARAM_SUFFIX_RE = re.compile(
    r'(_SL\d+.*|_TP\d+.*|_MHD\d+.*|_调参.*|_紧止损.*|_快止盈.*|_全紧.*|_快轮换.*|_v\d+.*)$'
)
_AI_PREFIX_RE = re.compile(r'^\[AI[^\]]*\]\s*')


def _get_family_name(strategy_name: str) -> str:
    """Extract family name by stripping AI prefix and parameter suffixes."""
    base = _AI_PREFIX_RE.sub('', strategy_name)
    base = _PARAM_SUFFIX_RE.sub('', base)
    return base


def build_family_summary(db: Session) -> list[dict]:
    """Build family-level summary table from all enabled strategies.

    Returns ~22 rows, one per family, with the best variant's stats.
    """
    strategies = (
        db.query(Strategy)
        .filter(Strategy.enabled.is_(True), Strategy.backtest_summary.isnot(None))
        .all()
    )

    # Group by family, track best variant per family (by score)
    families: dict[str, Strategy] = {}
    variant_counts: dict[str, int] = {}

    for s in strategies:
        fam = _get_family_name(s.name)
        variant_counts[fam] = variant_counts.get(fam, 0) + 1
        bs = s.backtest_summary or {}
        score = bs.get("score", 0) or 0
        current_best = families.get(fam)
        if current_best is None or score > (current_best.backtest_summary or {}).get("score", 0):
            families[fam] = s

    result = []
    for fam, s in sorted(families.items(), key=lambda x: -(x[1].backtest_summary or {}).get("score", 0)):
        bs = s.backtest_summary or {}
        regime = bs.get("regime_stats", {})
        result.append({
            "family": fam,
            "best_id": s.id,
            "variants": variant_counts.get(fam, 1),
            "score": round(bs.get("score", 0), 3),
            "total_return_pct": round(bs.get("total_return_pct", 0), 1),
            "max_drawdown_pct": round(bs.get("max_drawdown_pct", 0), 1),
            "bull_avg_pnl": round(regime.get("trending_bull", {}).get("avg_pnl", 0), 2),
            "bear_avg_pnl": round(regime.get("trending_bear", {}).get("avg_pnl", 0), 2),
            "range_avg_pnl": round(regime.get("ranging", {}).get("avg_pnl", 0), 2),
        })
    return result


def format_family_table(summaries: list[dict]) -> str:
    """Format family summaries as a readable text table for Claude prompt."""
    lines = ["族名 | score | 收益 | 回撤 | 牛市 | 熊市 | 震荡 | 变体"]
    lines.append("--- | --- | --- | --- | --- | --- | --- | ---")
    for s in summaries:
        lines.append(
            f"{s['family']} | {s['score']:.3f} | {s['total_return_pct']:+.1f}% | "
            f"{s['max_drawdown_pct']:.1f}% | {s['bull_avg_pnl']:.2f} | "
            f"{s['bear_avg_pnl']:.2f} | {s['range_avg_pnl']:.2f} | {s['variants']}"
        )
    return "\n".join(lines)


def select_strategies_by_families(db: Session, family_names: list[str]) -> list[int]:
    """Map AI-selected family names to best strategy IDs (one per family).

    Returns list of strategy IDs (the highest-score variant from each matched family).
    """
    strategies = (
        db.query(Strategy)
        .filter(Strategy.enabled.is_(True), Strategy.backtest_summary.isnot(None))
        .all()
    )

    # Build family -> best strategy mapping
    best_per_family: dict[str, tuple[int, float]] = {}
    for s in strategies:
        fam = _get_family_name(s.name)
        score = (s.backtest_summary or {}).get("score", 0) or 0
        if fam not in best_per_family or score > best_per_family[fam][1]:
            best_per_family[fam] = (s.id, score)

    selected_ids = []
    for name in family_names:
        if name in best_per_family:
            selected_ids.append(best_per_family[name][0])
        else:
            logger.warning("AI selected unknown family '%s', skipping", name)

    return selected_ids


def get_fallback_strategy_ids(db: Session, top_n: int = 5) -> list[int]:
    """Fallback: return strategy IDs of top N families by score."""
    summaries = build_family_summary(db)
    return [s["best_id"] for s in summaries[:top_n]]
```

**Step 2: Verify module loads**

Run: `source venv/bin/activate && python3 -c "from api.services.strategy_selector import build_family_summary; print('OK')"`
Expected: OK

**Step 3: Smoke test**

Run: `source venv/bin/activate && python3 -c "
from api.models.base import SessionLocal
from api.services.strategy_selector import build_family_summary, format_family_table, get_fallback_strategy_ids
db = SessionLocal()
s = build_family_summary(db)
print(f'Families: {len(s)}')
print(format_family_table(s)[:500])
fb = get_fallback_strategy_ids(db)
print(f'Fallback IDs: {fb}')
db.close()
"`

**Step 4: Commit**

```bash
git add api/services/strategy_selector.py
git commit -m "feat: add strategy family summary builder for AI selection"
```

---

### Task 2: Add run_strategy_selection to claude_runner.py

**Files:**
- Modify: `api/services/claude_runner.py`

**Step 1: Add the strategy selection system prompt and function**

After the existing `_CHAT_SYSTEM_PROMPT`, add:

```python
_STRATEGY_SELECTION_PROMPT_TEMPLATE = """\
你是 StockAgent 的策略选择引擎。根据当前市场环境，从策略族中选择最适合的 3-5 个。

可用 API:
- GET /api/news/sentiment/latest — 市场情绪分析
- GET /api/market/quote?code=000001 — 上证指数实时行情
- GET /api/bot/portfolio — 当前持仓

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...

以下是策略族摘要表（regime 列: 牛市/熊市/震荡下的平均每笔盈亏%%）：

{family_table}

选择规则：
1. 判断当前市场环境（牛市/熊市/震荡/转换期）
2. 优先选 regime 表现匹配当前环境的族
3. 如有持仓，确保至少 1 个族对持仓股的卖出信号覆盖好
4. 选 3-5 个族，平衡进攻性和防御性

返回 JSON（不要 markdown 围栏）：
{{"market_assessment": "bull|bear|ranging|transition", "selected_families": ["族名1", "族名2", ...], "reasoning": "选择理由"}}
"""


def run_strategy_selection(family_table: str) -> dict | None:
    """Run Claude to select strategy families based on market conditions.

    Returns {"market_assessment": str, "selected_families": [str], "reasoning": str}
    or None on failure.
    """
    prompt = (
        "请分析当前市场环境，从策略族中选择 3-5 个最适合的策略族。"
        "先查看市场情绪和上证指数行情，然后基于策略族表格做出选择。"
        "返回指定的 JSON 格式。"
    )

    system_prompt = _STRATEGY_SELECTION_PROMPT_TEMPLATE.format(family_table=family_table)

    args = [
        "-p", prompt,
        "--output-format", "json",
        "--model", _MODEL,
        "--append-system-prompt", system_prompt,
        "--permission-mode", "bypassPermissions",
    ]

    try:
        output = _run_cli(args, timeout=300)
    except Exception as e:
        logger.error("AI strategy selection failed: %s", e)
        return None

    result_text = output.get("result", "")
    if not result_text:
        logger.warning("AI strategy selection returned empty result")
        return None

    # Parse JSON
    cleaned = result_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("AI strategy selection result not parseable as JSON: %s", cleaned[:200])
        return None

    families = result.get("selected_families", [])
    if not isinstance(families, list) or len(families) == 0:
        logger.warning("AI strategy selection returned no families")
        return None

    logger.info("AI selected %d strategy families: %s", len(families), families)
    return result
```

**Step 2: Verify import**

Run: `source venv/bin/activate && python3 -c "from api.services.claude_runner import run_strategy_selection; print('OK')"`

**Step 3: Commit**

```bash
git add api/services/claude_runner.py
git commit -m "feat: add run_strategy_selection Claude call for family selection"
```

---

### Task 3: Add strategy_ids parameter to generate_signals_stream

**Files:**
- Modify: `api/services/signal_engine.py:110-131`

**Step 1: Add strategy_ids parameter**

Change `generate_signals_stream` signature and strategy loading:

```python
def generate_signals_stream(
    self,
    trade_date: str,
    stock_codes: Optional[list[str]] = None,
    strategy_ids: Optional[list[int]] = None,
) -> Generator[str, None, None]:
```

Replace lines 126-128:
```python
    strategies = (
        self.db.query(Strategy).filter(Strategy.enabled.is_(True)).all()
    )
```
With:
```python
    query = self.db.query(Strategy).filter(Strategy.enabled.is_(True))
    if strategy_ids:
        query = query.filter(Strategy.id.in_(strategy_ids))
    strategies = query.all()
```

**Step 2: Verify existing signal generation still works**

Run: `source venv/bin/activate && python3 -c "
from api.models.base import SessionLocal
from api.services.signal_engine import SignalEngine
db = SessionLocal()
e = SignalEngine(db)
# Just verify it accepts the parameter
import inspect
sig = inspect.signature(e.generate_signals_stream)
print('Params:', list(sig.parameters.keys()))
db.close()
"`
Expected: `Params: ['self', 'trade_date', 'stock_codes', 'strategy_ids']`

**Step 3: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "feat: add strategy_ids filter to generate_signals_stream"
```

---

### Task 4: Wire strategy selection into scheduler

**Files:**
- Modify: `api/services/signal_scheduler.py:130-147`

**Step 1: Replace Step 3 (signal generation) with strategy selection + filtered generation**

Replace lines 143-146:
```python
                    # Step 3: Generate signals
                    engine = SignalEngine(db)
                    for _ in engine.generate_signals_stream(trade_date):
                        pass
                    logger.info("Scheduled signal generation completed for %s", trade_date)
```

With:
```python
                    # Step 3: AI strategy selection
                    selected_ids = None
                    try:
                        from api.services.strategy_selector import (
                            build_family_summary, format_family_table,
                            select_strategies_by_families, get_fallback_strategy_ids,
                        )
                        from api.services.claude_runner import run_strategy_selection

                        summaries = build_family_summary(db)
                        if summaries:
                            table = format_family_table(summaries)
                            selection = run_strategy_selection(table)
                            if selection and selection.get("selected_families"):
                                selected_ids = select_strategies_by_families(
                                    db, selection["selected_families"]
                                )
                                logger.info(
                                    "AI selected strategies: %s (IDs: %s)",
                                    selection["selected_families"], selected_ids,
                                )
                            if not selected_ids:
                                selected_ids = get_fallback_strategy_ids(db)
                                logger.info("Using fallback strategy IDs: %s", selected_ids)
                        else:
                            logger.warning("No family summaries available, running all strategies")
                    except Exception as e:
                        logger.error("Strategy selection failed (non-fatal): %s", e)
                        try:
                            from api.services.strategy_selector import get_fallback_strategy_ids
                            selected_ids = get_fallback_strategy_ids(db)
                            logger.info("Fallback after error, IDs: %s", selected_ids)
                        except Exception:
                            pass

                    # Step 4: Generate signals (filtered by selected strategies)
                    engine = SignalEngine(db)
                    for _ in engine.generate_signals_stream(trade_date, strategy_ids=selected_ids):
                        pass
                    logger.info("Scheduled signal generation completed for %s", trade_date)
```

Also update the step comment on the AI analysis line:
```python
                # Step 5: Run AI daily analysis
```

**Step 2: Verify file loads**

Run: `source venv/bin/activate && python3 -c "from api.services.signal_scheduler import SignalScheduler; print('OK')"`

**Step 3: Commit**

```bash
git add api/services/signal_scheduler.py
git commit -m "feat: wire AI strategy selection into scheduler before signal generation"
```

---

### Task 5: Wire strategy selection into manual analyze endpoint

**Files:**
- Modify: `api/routers/ai_analyst.py:168-202`

**Step 1: Add strategy selection before analysis in trigger_analysis**

The manual `POST /api/ai/analyze` endpoint currently calls `run_daily_analysis` directly. Add strategy selection + signal generation before it:

```python
@router.post("/analyze")
def trigger_analysis(
    report_date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: Session = Depends(get_db),
):
    """Manually trigger AI daily analysis for a given date."""
    from api.services.claude_runner import run_daily_analysis, run_strategy_selection
    from api.services.strategy_selector import (
        build_family_summary, format_family_table,
        select_strategies_by_families, get_fallback_strategy_ids,
    )
    from api.services.signal_engine import SignalEngine

    target_date = report_date or date.today().isoformat()

    # Step 1: AI strategy selection
    selected_ids = None
    try:
        summaries = build_family_summary(db)
        if summaries:
            table = format_family_table(summaries)
            selection = run_strategy_selection(table)
            if selection and selection.get("selected_families"):
                selected_ids = select_strategies_by_families(
                    db, selection["selected_families"]
                )
            if not selected_ids:
                selected_ids = get_fallback_strategy_ids(db)
    except Exception:
        pass

    # Step 2: Generate signals with selected strategies
    if selected_ids:
        try:
            engine = SignalEngine(db)
            for _ in engine.generate_signals_stream(target_date, strategy_ids=selected_ids):
                pass
        except Exception:
            pass

    # Step 3: AI analysis (existing)
    result = run_daily_analysis(target_date)
    # ... rest unchanged
```

**Step 2: Commit**

```bash
git add api/routers/ai_analyst.py
git commit -m "feat: add strategy selection to manual analyze endpoint"
```

---

### Task 6: Update AI analysis system prompt

**Files:**
- Modify: `api/services/claude_runner.py` (the `_ANALYSIS_SYSTEM_PROMPT`)

**Step 1: Add context about AI-selected strategies**

After the `CRITICAL WORKFLOW` section, add:

```
注意：今日信号是基于 AI 策略选择引擎筛选的策略生成的，不是全部策略库。
信号中的 alpha_score 反映了选中策略的综合评分，直接在 recommendations 中传回。
```

**Step 2: Commit**

```bash
git add api/services/claude_runner.py
git commit -m "feat: update analysis prompt with strategy selection context"
```

---

### Task 7: End-to-end smoke test

**Step 1: Test family summary**

```bash
source venv/bin/activate && python3 -c "
from api.models.base import SessionLocal
from api.services.strategy_selector import build_family_summary, format_family_table, select_strategies_by_families, get_fallback_strategy_ids
db = SessionLocal()
summaries = build_family_summary(db)
print(f'Families: {len(summaries)}')
table = format_family_table(summaries)
print(table[:600])
print()
# Test select
ids = select_strategies_by_families(db, ['全指标综合_中性版C', 'PSAR趋势动量_保守版A', 'UltimateOsc_中性版C'])
print(f'Selected IDs: {ids}')
# Test fallback
fb = get_fallback_strategy_ids(db)
print(f'Fallback IDs: {fb}')
# Test unknown family
ids2 = select_strategies_by_families(db, ['不存在的策略'])
print(f'Unknown family IDs: {ids2}')
db.close()
"
```

Expected: 22 families, 3 selected IDs, 5 fallback IDs, empty list for unknown.

**Step 2: Test signal generation with strategy_ids**

```bash
source venv/bin/activate && python3 -c "
from api.models.base import SessionLocal
from api.services.signal_engine import SignalEngine
db = SessionLocal()
e = SignalEngine(db)
count = 0
for event in e.generate_signals_stream('2026-02-17', strategy_ids=[99, 705, 354]):
    count += 1
print(f'Events emitted: {count}')
db.close()
"
```

Expected: events emitted (fewer signals than running all 1029 strategies).

**Step 3: Commit (if any fixes needed)**

```bash
git commit -am "fix: smoke test fixes for AI strategy selection"
```
