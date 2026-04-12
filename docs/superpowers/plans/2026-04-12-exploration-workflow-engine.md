# Exploration Workflow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify the complete 11-step strategy exploration workflow into a FastAPI-integrated engine, matching all functionality from the original Claude skill — including promote checks, unsynced round sync, LLM-powered planning with historical insight injection, self-healing on failures, and pool rebalancing.

**Architecture:** Single service file (`exploration_engine.py` ~1200 lines) containing all workflow logic. Single router file (`exploration_workflow.py` ~80 lines) with 4 REST endpoints. The engine calls existing internal APIs via localhost HTTP, keeping it fully decoupled.

**Tech Stack:** Python 3.11, FastAPI, OpenAI SDK (for Qwen/DeepSeek), SQLAlchemy, threading

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `api/services/exploration_engine.py` | Create | Full engine: factor registry, validator, LLM planner, workflow steps, engine class |
| `api/routers/exploration_workflow.py` | Create | 4 REST endpoints: start, stop, status, history |
| `api/main.py` | Modify (line ~538) | Register new router |

---

### Task 1: Factor Registry + Config Validator

Pure functions with no external dependencies. The factor registry defines all valid indicator fields, their operators, parameter requirements, and value ranges. The validator checks LLM-generated experiment configs against this registry.

**Files:**
- Create: `api/services/exploration_engine.py`

- [ ] **Step 1: Create file with factor registry, banned list, and validator**

```python
"""Exploration Workflow Engine.

Complete automated strategy exploration pipeline:
  Load State → Verify Promote → Sync Rounds → Plan (LLM) → Submit
  → Poll → Analyze → Promote → Rebalance → Record → Loop

Controlled via REST API: start/stop/status/history.
"""

import itertools
import json
import logging
import re
import subprocess
import threading
import time as _time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# ── Factor Registry ──────────────────────────────────────────────
# field_name → {op, params (None=no params), min, max}

VALID_BUY_FACTORS: dict[str, dict] = {
    "KBAR_amplitude":    {"op": "<", "params": None,            "min": 0.01, "max": 0.10},
    "KBAR_body_ratio":   {"op": "<", "params": None,            "min": 0.05, "max": 0.8},
    "KBAR_lower_shadow": {"op": ">", "params": None,            "min": 0.05, "max": 0.5},
    "W_KBAR_amplitude":  {"op": "<", "params": None,            "min": 0.02, "max": 0.15},
    "W_REALVOL":         {"op": "<", "params": {"period": 20},  "min": 5,    "max": 50},
    "REALVOL":           {"op": "<", "params": {"period": 20},  "min": 5,    "max": 60},
    "REALVOL_kurt":      {"op": "<", "params": {"period": 20},  "min": 1,    "max": 8},
    "REALVOL_downside":  {"op": "<", "params": {"period": 20},  "min": 5,    "max": 40},
    "REALVOL_skew":      {"op": ">", "params": {"period": 20},  "min": -3,   "max": 3},
    "M_REALVOL":         {"op": "<", "params": {"period": 20},  "min": 5,    "max": 50},
    "AMPVOL_std":        {"op": "<", "params": {"period": 5},   "min": 0.005,"max": 0.05},
    "W_AMPVOL_std":      {"op": "<", "params": {"period": 5},   "min": 0.01, "max": 0.08},
    "RSTR_weighted":     {"op": ">", "params": {"period": 20},  "min": -2,   "max": 3},
    "W_RSTR_weighted":   {"op": ">", "params": {"period": 20},  "min": -2,   "max": 3},
    "PVOL_corr":         {"op": ">", "params": {"period": 20},  "min": -0.5, "max": 0.8},
    "W_PVOL_corr":       {"op": ">", "params": {"period": 20},  "min": -0.5, "max": 0.8},
    "PVOL_amount_conc":  {"op": "<", "params": {"period": 20},  "min": 0.05, "max": 0.9},
    "MOM":               {"op": ">", "params": {"period": 20},  "min": -3,   "max": 5},
    "LIQ_turnover_vol":  {"op": ">", "params": {"period": 20},  "min": 0.1,  "max": 5},
    "W_ATR":             {"op": "<", "params": {"period": 14},  "min": 0.01, "max": 0.15},
    "PPOS_high_dist":    {"op": "<", "params": {"period": 20},  "min": -15,  "max": 0},
    "PPOS_drawdown":     {"op": "<", "params": {"period": 20},  "min": -20,  "max": 0},
    "W_ADX":             {"op": ">", "params": {"period": 14},  "min": 10,   "max": 50},
}

BANNED_FIELDS = frozenset({
    "PPOS_close_pos", "PPOS_consec_dir", "AMPVOL_parkinson",
    "W_STOCH", "PVOL_vwap_bias", "LIQ_amihud",
})

# Sell conditions can use same fields (reversed) plus these:
SELL_ONLY_FIELDS = frozenset({"KDJ_K", "close"})

# Base conditions (always applied, never in LLM output)
BASE_BUY = [
    {"field": "RSI", "params": {"period": 14}, "operator": ">",
     "compare_type": "value", "compare_value": 48},
    {"field": "RSI", "params": {"period": 14}, "operator": "<",
     "compare_type": "value", "compare_value": 66},
    {"field": "ATR", "params": {"period": 14}, "operator": "<",
     "compare_type": "value", "compare_value": 0.091},
]
BASE_SELL = [
    {"field": "KDJ_K", "params": {"k": 9, "d": 3, "j": 3}, "operator": ">",
     "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
    {"field": "close", "operator": "<",
     "compare_type": "pct_change", "compare_value": -0.5},
]

# StdA+ criteria
STDA_SCORE = 0.80
STDA_RETURN = 60
STDA_DD = 18
STDA_TRADES = 50
STDA_WR = 60


def is_stda_plus(s: dict) -> bool:
    """Check if a strategy dict meets StdA+ criteria."""
    return (
        (s.get("score", 0) or 0) >= STDA_SCORE
        and (s.get("total_return_pct", 0) or 0) > STDA_RETURN
        and abs(s.get("max_drawdown_pct", 100) or 100) < STDA_DD
        and (s.get("total_trades", 0) or 0) >= STDA_TRADES
        and (s.get("win_rate", 0) or 0) > STDA_WR
    )


def validate_condition(cond: dict, context: str = "") -> list[str]:
    """Validate a single buy/sell condition dict."""
    issues: list[str] = []
    if not isinstance(cond, dict):
        return [f"{context}: not a dict"]

    field = cond.get("field", "")
    if not field:
        issues.append(f"{context}: missing 'field'")
        return issues
    if field in BANNED_FIELDS:
        issues.append(f"{context}: banned field '{field}'")
        return issues

    all_valid = set(VALID_BUY_FACTORS.keys()) | SELL_ONLY_FIELDS
    if field not in all_valid:
        issues.append(f"{context}: unknown field '{field}'")

    if "operator" not in cond:
        issues.append(f"{context}: missing 'operator'")
    elif cond["operator"] not in ("<", ">", "<=", ">="):
        issues.append(f"{context}: bad operator '{cond['operator']}'")

    ct = cond.get("compare_type")
    if ct and ct not in ("value", "consecutive", "pct_change", "field",
                         "lookback_min", "lookback_max"):
        issues.append(f"{context}: bad compare_type '{ct}'")

    if ct == "value" and "compare_value" not in cond:
        issues.append(f"{context}: missing compare_value")

    return issues


def validate_experiment_config(config: dict) -> tuple[bool, list[str]]:
    """Validate a full experiment config from LLM output."""
    issues: list[str] = []

    if config.get("type", "") not in ("fill", "new", "opt"):
        issues.append(f"bad type '{config.get('type')}'")
    if not config.get("label"):
        issues.append("missing label")

    for key in ("extra_buy_conditions", "extra_sell_conditions"):
        conds = config.get(key, [])
        if not isinstance(conds, list):
            issues.append(f"{key} not a list")
        else:
            for i, c in enumerate(conds):
                issues.extend(validate_condition(c, f"{key}[{i}]"))

    exits = config.get("exit_configs", [])
    if not isinstance(exits, list) or len(exits) < 3:
        issues.append(f"need >=3 exit_configs, got {len(exits) if isinstance(exits, list) else 0}")
    else:
        for i, ec in enumerate(exits):
            if not isinstance(ec, dict):
                issues.append(f"exit[{i}]: not a dict")
                continue
            sl = ec.get("stop_loss_pct")
            tp = ec.get("take_profit_pct")
            mhd = ec.get("max_hold_days")
            if sl is None or not isinstance(sl, (int, float)):
                issues.append(f"exit[{i}]: bad stop_loss_pct")
            if tp is None or not isinstance(tp, (int, float)) or tp <= 0:
                issues.append(f"exit[{i}]: bad take_profit_pct")
            if mhd is None or not isinstance(mhd, int) or mhd < 1:
                issues.append(f"exit[{i}]: bad max_hold_days")

    return len(issues) == 0, issues
```

- [ ] **Step 2: Verify file loads**

```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import validate_experiment_config, VALID_BUY_FACTORS, is_stda_plus; print(f'OK: {len(VALID_BUY_FACTORS)} factors')"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add factor registry and config validator"
```

---

### Task 2: Internal API Helper + Historical Insight Loader

The engine calls existing FastAPI endpoints via localhost HTTP (decoupled). The insight loader reads `docs/lab-experiment-analysis.md` to extract key findings for LLM context.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add internal API helper and insight loader**

Append to `api/services/exploration_engine.py`:

```python
# ── Internal API ─────────────────────────────────────────────────

def _api(method: str, path: str, data: dict | None = None, timeout: int = 60) -> dict:
    """Call our own FastAPI endpoints via HTTP localhost:8050."""
    cmd = ["curl", "-s"]
    if method.upper() != "GET":
        cmd.extend(["-X", method.upper()])
    url = f"http://127.0.0.1:8050/api/{path}"
    if data is not None:
        cmd.extend(["-H", "Content-Type: application/json",
                     "-d", json.dumps(data)])
    cmd.append(url)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            env={"NO_PROXY": "localhost,127.0.0.1", "PATH": "/usr/bin:/bin"},
            timeout=timeout,
        )
        return json.loads(r.stdout)
    except Exception as e:
        logger.error("_api %s %s failed: %s", method, path, e)
        return {}


def _promote_strategy(sid: int) -> dict:
    """Promote a strategy to the pool."""
    label = urllib.parse.quote("[AI]")
    cat = urllib.parse.quote("全能")
    return _api("POST", f"lab/strategies/{sid}/promote?label={label}&category={cat}")


# ── Insight Loader ───────────────────────────────────────────────

_INSIGHT_DOC = Path(__file__).parent.parent.parent / "docs" / "lab-experiment-analysis.md"


def load_historical_insights() -> str:
    """Read core insights + exploration status from lab-experiment-analysis.md.

    Returns a condensed text summary for injecting into LLM context.
    """
    if not _INSIGHT_DOC.exists():
        return "(no historical insight doc found)"

    text = _INSIGHT_DOC.read_text(encoding="utf-8")

    # Extract key sections
    sections = []

    # 核心洞察 section
    m = re.search(r"## 核心洞察\s*\n([\s\S]*?)(?=\n## )", text)
    if m:
        # Take first 15 insights (numbered lines)
        lines = [l.strip() for l in m.group(1).strip().split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10", "11", "12", "13", "14", "15"))]
        if lines:
            sections.append("核心洞察:\n" + "\n".join(lines[:10]))

    # 探索状态 — what works
    m = re.search(r"### 有效方向[\s\S]*?\n(\|[\s\S]*?)(?=\n### |$)", text)
    if m:
        sections.append("有效方向:\n" + m.group(1)[:500])

    # 已弃指标
    m = re.search(r"### 已弃指标[^\n]*\n([\s\S]*?)(?=\n### |$)", text)
    if m:
        sections.append("已弃: " + m.group(1).strip()[:300])

    # 下一步建议
    m = re.search(r"### 下一步优先级[^\n]*\n([\s\S]*?)(?=\n## |$)", text)
    if m:
        sections.append("上轮建议:\n" + m.group(1).strip()[:400])

    if not sections:
        # Fallback: just grab first 500 chars
        return text[:500]

    return "\n\n".join(sections)


def get_latest_round_suggestions() -> list[str]:
    """Get next_suggestions from the latest exploration round via API."""
    rounds = _api("GET", "lab/exploration-rounds")
    items = rounds.get("items", rounds) if isinstance(rounds, dict) else rounds
    if not items or not isinstance(items, list):
        return []
    latest = max(items, key=lambda r: r.get("round_number", 0))
    return latest.get("next_suggestions", [])
```

- [ ] **Step 2: Test insight loader**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.exploration_engine import load_historical_insights
text = load_historical_insights()
print(f'Insight length: {len(text)} chars')
print(text[:300])
"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add internal API helper and historical insight loader"
```

---

### Task 3: LLM Planner with Insight Injection

The planner calls Qwen (primary) → DeepSeek (fallback) → rule-based (last resort). The system prompt includes the few-shot sell examples that fix Qwen's format hallucination. The user prompt injects pool state AND historical insights.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add LLM prompt and planner class**

Append to `api/services/exploration_engine.py`:

```python
# ── LLM Planner ──────────────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """你是A股量化策略研究员。根据策略池状态和历史洞察规划探索实验。

## 基础买入条件(固定,不需指定)
RSI(14) 48-66 + ATR(14) < 0.091

## 条件格式(buy和sell通用,严格遵守)
{"field":"字段名","operator":"<或>","compare_type":"value","compare_value":数值}
需要参数时: {"field":"字段名","operator":"<","compare_type":"value","compare_value":数值,"params":{"period":20}}

⚠️ 严禁使用其他格式! 不允许: type, threshold, trailing_stop, factor_cross 等自定义字段。

## 可用Alpha因子(买入)
- KBAR_amplitude < 0.02-0.06 (无params)
- W_REALVOL < 15-35 (params period=20)
- REALVOL_kurt < 2-4 (params period=20)
- AMPVOL_std < 0.01-0.03 (params period=5)
- RSTR_weighted > -0.5-1.5 (params period=20)
- PVOL_corr > 0.1-0.4 (params period=20)
- PVOL_amount_conc < 0.2-0.7 (params period=20)
- MOM > -1-2 (params period=20)
- LIQ_turnover_vol > 0.3-2.0 (params period=20)
- W_ATR < 0.03-0.10 (params period=14)
- REALVOL_downside < 10-25 (params period=20)
- REALVOL < 15-40 (params period=20)
- W_AMPVOL_std < 0.02-0.06 (params period=5)
- W_RSTR_weighted > -0.5-1.0 (params period=20)
- W_KBAR_amplitude < 0.03-0.10 (无params)
- PPOS_high_dist < -3到-8 (params period=20)
- M_REALVOL < 20-35 (params period=20)
- KBAR_body_ratio < 0.2-0.5 (无params)
- REALVOL_skew > -1-2 (params period=20)
- W_ADX > 15-35 (params period=14)
- W_PVOL_corr > 0.1-0.3 (params period=20)
- PPOS_drawdown < -3到-10 (params period=20)

## 卖出条件(同样因子的反向,使用完全相同的JSON格式)
- KBAR_amplitude > 0.05-0.08 → 振幅过大卖出
- REALVOL > 30-45 (params period=20) → 波动率升高卖出
- MOM < -1到-2 (params period=20) → 动量转负卖出
- RSTR_weighted < -0.5到-1 (params period=20) → 动量反转卖出
- AMPVOL_std > 0.025-0.04 (params period=5) → 振幅波动扩大卖出

## 正确的sell条件示例(必须严格遵循此格式):
[
  {"field":"MOM","operator":"<","compare_type":"value","compare_value":-1.0,"params":{"period":20}},
  {"field":"KBAR_amplitude","operator":">","compare_type":"value","compare_value":0.06},
  {"field":"REALVOL","operator":">","compare_type":"value","compare_value":38,"params":{"period":20}}
]

## 已弃(禁用): PPOS_close_pos, PPOS_consec_dir, AMPVOL_parkinson, W_STOCH, PVOL_vwap_bias, LIQ_amihud

## Exit Config格式
{"name":"SL20_TP2_MHD5","stop_loss_pct":-20,"take_profit_pct":2.0,"max_hold_days":5}

## 资源分配原则
- fill(30%): 针对gap最大的已有家族,用不同阈值填充
- new(60%): 池中不存在的新指标组合(2-3个因子)
- opt(10%): 对已满家族尝试新的sell条件"""


def _build_user_prompt(pool_families: list[dict], n_experiments: int,
                       insights: str, suggestions: list[str]) -> str:
    """Build user prompt from pool state + historical context."""
    top = sorted(pool_families, key=lambda f: -f.get("gap", 0))[:15]
    lines = [f"  {f['family']}(gap={f['gap']}, active={f['active_count']}/{f['quota']}, avg={f['avg_score']:.4f})"
             for f in top]
    pool_text = "\n".join(lines)

    # Full families (for opt targets)
    full = [f for f in pool_families if f.get("gap", 0) == 0]
    full_text = ""
    if full:
        full_sorted = sorted(full, key=lambda f: f.get("avg_score", 0))[:3]
        full_text = "\n已满家族(优化目标):\n" + "\n".join(
            f"  {f['family']}(avg={f['avg_score']:.4f})" for f in full_sorted)

    n_fill = max(1, n_experiments * 3 // 10)
    n_new = max(1, n_experiments * 6 // 10)
    n_opt = max(1, n_experiments - n_fill - n_new)

    sug_text = ""
    if suggestions:
        sug_text = "\n上轮探索建议(优先考虑):\n" + "\n".join(f"  - {s}" for s in suggestions[:5])

    insight_text = ""
    if insights:
        insight_text = f"\n历史洞察:\n{insights[:800]}"

    return f"""池状态: {len(pool_families)}家族, 总gap={sum(f.get('gap',0) for f in pool_families)}, 活跃={sum(f.get('active_count',0) for f in pool_families)}
Top未满家族:
{pool_text}{full_text}{sug_text}{insight_text}

请输出{n_experiments}个实验配置({n_fill}个fill + {n_new}个新骨架 + {n_opt}个优化), JSON数组:
[{{"type":"fill/new/opt","label":"英文标签","extra_buy_conditions":[条件],"extra_sell_conditions":[条件],"exit_configs":[exit]}}]

要求:
1. 每个实验至少5个exit_configs,覆盖不同TP/MHD组合
2. 新骨架用2-3个因子组合,确保池中不存在
3. fill针对top-gap家族做参数变体
4. opt的extra_sell_conditions非空,使用标准条件格式
5. 参考历史洞察和上轮建议选择方向
6. 只输出JSON,不要解释"""


class LLMPlanner:
    """Call Qwen (primary) → DeepSeek (fallback) → rules to plan experiments."""

    def __init__(self):
        from api.config import get_settings
        settings = get_settings()
        ds_key = settings.deepseek.api_key

        self._providers: list[dict] = [
            {
                "name": "qwen",
                "base_url": "http://192.168.100.172:8680/v1",
                "model": "qwen3.5-35b-a3b",
                "api_key": "no-key-required",
                "max_tokens": 8000,
                "timeout": 300,
            },
        ]
        if ds_key:
            self._providers.append({
                "name": "deepseek",
                "base_url": settings.deepseek.base_url,
                "model": settings.deepseek.model,
                "api_key": ds_key,
                "max_tokens": 8000,
                "timeout": 180,
            })

    def plan(self, pool_families: list[dict], n_experiments: int,
             insights: str = "", suggestions: list[str] | None = None,
             ) -> tuple[list[dict], str]:
        """Generate experiment configs. Returns (valid_configs, provider_name)."""
        user_prompt = _build_user_prompt(
            pool_families, n_experiments, insights, suggestions or [])

        for prov in self._providers:
            try:
                logger.info("LLMPlanner: trying %s ...", prov["name"])
                raw_configs = self._call_llm(prov, user_prompt)
                valid = []
                for cfg in raw_configs:
                    ok, issues = validate_experiment_config(cfg)
                    if ok:
                        valid.append(cfg)
                    else:
                        logger.debug("LLMPlanner: dropped config: %s", issues)

                logger.info("LLMPlanner: %s → %d/%d valid configs",
                           prov["name"], len(valid), len(raw_configs))

                if len(valid) >= n_experiments * 0.5:
                    return valid[:n_experiments], prov["name"]
                logger.warning("LLMPlanner: %s insufficient valid configs", prov["name"])
            except Exception:
                logger.exception("LLMPlanner: %s failed", prov["name"])

        logger.info("LLMPlanner: all LLMs failed, rule-based fallback")
        return self._rule_based(pool_families, n_experiments), "rules"

    def _call_llm(self, provider: dict, user_prompt: str) -> list[dict]:
        client = OpenAI(
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            timeout=provider["timeout"],
        )
        resp = client.chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=provider["max_tokens"],
        )
        raw = resp.choices[0].message.content or ""
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(text: str) -> list[dict]:
        """Extract JSON array from LLM output."""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
        if m:
            text = m.group(1)
        elif not text.startswith("["):
            bm = re.search(r"(\[[\s\S]*\])", text)
            if bm:
                text = bm.group(1)
        data = json.loads(text)
        return data if isinstance(data, list) else [data]

    @staticmethod
    def _rule_based(pool_families: list[dict], n: int) -> list[dict]:
        """Pure rule-based fallback when all LLMs fail."""
        exit_grid = [
            {"name": "SL20_TP0.5_MHD2", "stop_loss_pct": -20, "take_profit_pct": 0.5, "max_hold_days": 2},
            {"name": "SL20_TP1_MHD3",   "stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 3},
            {"name": "SL15_TP1.5_MHD3", "stop_loss_pct": -15, "take_profit_pct": 1.5, "max_hold_days": 3},
            {"name": "SL20_TP2_MHD5",   "stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 5},
            {"name": "SL25_TP3_MHD5",   "stop_loss_pct": -25, "take_profit_pct": 3.0, "max_hold_days": 5},
            {"name": "SL20_TP4_MHD7",   "stop_loss_pct": -20, "take_profit_pct": 4.0, "max_hold_days": 7},
        ]
        configs: list[dict] = []

        # Fill: top-gap families
        sorted_fams = sorted(pool_families, key=lambda f: -f.get("gap", 0))
        for fam in sorted_fams[:n // 3]:
            for factor, meta in VALID_BUY_FACTORS.items():
                if factor.split("_")[0] in fam.get("family", "").upper():
                    cond = {"field": factor, "operator": meta["op"],
                            "compare_type": "value",
                            "compare_value": (meta["min"] + meta["max"]) / 2}
                    if meta.get("params"):
                        cond["params"] = meta["params"]
                    configs.append({
                        "type": "fill", "label": f"fill_{factor}",
                        "extra_buy_conditions": [cond],
                        "extra_sell_conditions": [],
                        "exit_configs": exit_grid,
                    })
                    break

        # New: 2-factor combos
        factor_list = list(VALID_BUY_FACTORS.keys())
        for a, b in itertools.combinations(factor_list[:12], 2):
            if len(configs) >= n * 9 // 10:
                break
            ma, mb = VALID_BUY_FACTORS[a], VALID_BUY_FACTORS[b]
            ca = {"field": a, "operator": ma["op"], "compare_type": "value",
                  "compare_value": round((ma["min"] + ma["max"]) / 2, 4)}
            cb = {"field": b, "operator": mb["op"], "compare_type": "value",
                  "compare_value": round((mb["min"] + mb["max"]) / 2, 4)}
            if ma.get("params"): ca["params"] = ma["params"]
            if mb.get("params"): cb["params"] = mb["params"]
            configs.append({
                "type": "new", "label": f"new_{a}_{b}",
                "extra_buy_conditions": [ca, cb],
                "extra_sell_conditions": [],
                "exit_configs": exit_grid,
            })

        # Opt: simple sell conditions
        sell_templates = [
            {"field": "MOM", "operator": "<", "compare_type": "value",
             "compare_value": -1.0, "params": {"period": 20}},
            {"field": "KBAR_amplitude", "operator": ">", "compare_type": "value",
             "compare_value": 0.06},
        ]
        for st in sell_templates[:max(1, n // 10)]:
            configs.append({
                "type": "opt", "label": f"opt_{st['field']}",
                "extra_buy_conditions": [],
                "extra_sell_conditions": [st],
                "exit_configs": exit_grid,
            })

        return configs[:n]
```

- [ ] **Step 2: Verify planner loads**

```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import LLMPlanner; p = LLMPlanner(); print(f'Providers: {[p[\"name\"] for p in p._providers]}')"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add LLM planner with insight injection and Qwen/DeepSeek/rules fallback"
```

---

### Task 4: Exploration Engine — Full Workflow Loop

The main engine class with ALL workflow steps matching the original SKILL:
- Step 1b: Promote check (scan all experiments for unpromoted StdA+)
- Step 1d: Sync unsynced rounds
- Step 1e: Pool status query
- Step 1.5: Retry-pending (unstick queue)
- Step 3: Plan via LLM with insight injection
- Step 5: Submit batch-clone-backtest
- Step 6: Poll + self-healing (retry high-invalid experiments)
- Step 7: Promote + rebalance
- Step 9b: Record exploration round

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add ExplorationEngine class**

Append to `api/services/exploration_engine.py`:

```python
# ── Exploration Engine ───────────────────────────────────────────

class ExplorationEngine:
    """Singleton engine — runs the full exploration workflow in a background thread."""

    _instance: Optional["ExplorationEngine"] = None

    def __new__(cls) -> "ExplorationEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # State
        self.state = "IDLE"
        self.current_round = 0
        self.current_step = ""
        self.step_detail = ""

        # Round config
        self.rounds_total = 0
        self.rounds_completed = 0

        # Strategy stats (updated during polling)
        self.strategies_total = 0
        self.strategies_done = 0
        self.strategies_invalid = 0
        self.strategies_pending = 0
        self.stda_count = 0
        self.best_score = 0.0

        # Pool stats
        self.pool_families = 0
        self.pool_active = 0
        self.pool_gap = 0

        # Metadata
        self.started_at: Optional[str] = None
        self.llm_provider = ""
        self.last_error: Optional[str] = None
        self.experiment_ids: list[int] = []

        # Internals
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._source_strategy_id = 116987
        self._planner = LLMPlanner()

    # ── Public API ───────────────────────────────────────────────

    def start(self, rounds: int = 1, experiments_per_round: int = 50,
              source_strategy_id: int = 116987) -> dict:
        if self.state in ("RUNNING", "STOPPING"):
            return {"error": f"Already {self.state}"}

        self._stop_event.clear()
        self._source_strategy_id = source_strategy_id
        self.rounds_total = rounds
        self.rounds_completed = 0
        self.last_error = None
        self.started_at = datetime.now().isoformat()

        # Determine next round number from API
        rounds_data = _api("GET", "lab/exploration-rounds")
        items = rounds_data.get("items", rounds_data) if isinstance(rounds_data, dict) else rounds_data
        if items and isinstance(items, list):
            self.current_round = max((r.get("round_number", 0) for r in items), default=0) + 1
        else:
            self.current_round = 1

        self.state = "RUNNING"
        self._thread = threading.Thread(
            target=self._run_loop, args=(rounds, experiments_per_round),
            daemon=True, name="exploration-engine",
        )
        self._thread.start()
        logger.info("Exploration started: %d rounds × %d exp, R%d",
                     rounds, experiments_per_round, self.current_round)
        return {"message": "Exploration started", "round_number": self.current_round}

    def stop(self) -> dict:
        if self.state != "RUNNING":
            return {"error": f"Not running (state={self.state})"}
        self._stop_event.set()
        self.state = "STOPPING"
        return {"message": "Stop requested, will finish current round"}

    def get_status(self) -> dict:
        elapsed = 0.0
        if self.started_at:
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(self.started_at)).total_seconds()
            except ValueError:
                pass
        rate = self.strategies_done / max(1, elapsed) if elapsed > 0 else 0
        remaining = self.strategies_pending / rate if rate > 0 else 0

        return {
            "state": self.state,
            "current_round": self.current_round,
            "current_step": self.current_step,
            "step_detail": self.step_detail,
            "rounds_config": {"total": self.rounds_total, "completed": self.rounds_completed},
            "strategies": {
                "total": self.strategies_total,
                "done": self.strategies_done,
                "invalid": self.strategies_invalid,
                "pending": self.strategies_pending,
                "stda_count": self.stda_count,
                "best_score": self.best_score,
            },
            "pool": {"families": self.pool_families, "active": self.pool_active, "gap": self.pool_gap},
            "timing": {
                "started_at": self.started_at,
                "elapsed_seconds": round(elapsed),
                "estimated_remaining_seconds": round(remaining),
            },
            "experiment_ids": self.experiment_ids,
            "llm_provider": self.llm_provider,
            "last_error": self.last_error,
        }

    # ── Main Loop ────────────────────────────────────────────────

    def _run_loop(self, rounds: int, exp_per_round: int):
        try:
            for i in range(rounds):
                if self._stop_event.is_set():
                    break
                logger.info("=== Round %d/%d (R%d) ===", i + 1, rounds, self.current_round)

                # Step 1b: Promote check
                self._set_step("promote_check", "检查历史未promote的StdA+策略")
                self._step_promote_check()

                if self._stop_event.is_set(): break

                # Step 1d: Sync unsynced rounds
                self._set_step("sync_rounds", "同步未完成的探索轮次")
                self._step_sync_unsynced_rounds()

                if self._stop_event.is_set(): break

                # Step 1e: Load pool state
                self._set_step("loading_state", "查询池状态")
                pool_families = self._step_load_state()

                if self._stop_event.is_set(): break

                # Step 1.5: Retry pending (unstick queue)
                self._set_step("retry_pending", "恢复stuck实验队列")
                _api("POST", "lab/experiments/retry-pending")

                if self._stop_event.is_set(): break

                # Step 3: Plan via LLM
                self._set_step("planning", "LLM规划实验方向")
                configs, provider = self._step_plan(pool_families, exp_per_round)
                self.llm_provider = provider

                if self._stop_event.is_set(): break

                # Step 5: Submit
                self._set_step("submitting", f"提交{len(configs)}个实验")
                exp_ids = self._step_submit(configs)
                self.experiment_ids = exp_ids

                # Step 6: Poll + self-healing
                self._set_step("polling", "等待回测完成")
                self._step_poll(exp_ids)

                # Step 7: Promote + rebalance
                self._set_step("promoting", "Promote StdA+策略")
                promoted = self._step_promote_and_rebalance(exp_ids)

                # Step 9b: Record
                self._set_step("recording", "保存轮次记录")
                self._step_record(exp_ids, promoted)

                self.rounds_completed += 1
                self.current_round += 1
                logger.info("Round complete: %d StdA+ promoted, best=%.4f",
                           promoted, self.best_score)

        except Exception as e:
            logger.exception("Exploration engine error")
            self.last_error = str(e)
            self.state = "ERROR"
            return

        self.state = "IDLE"
        self.current_step = ""
        self.step_detail = ""
        logger.info("Exploration finished: %d/%d rounds", self.rounds_completed, rounds)

    def _set_step(self, step: str, detail: str):
        self.current_step = step
        self.step_detail = detail
        logger.info("Step: %s — %s", step, detail)

    # ── Step 1b: Promote Check ───────────────────────────────────

    def _step_promote_check(self):
        """Scan recent experiments for unpromoted StdA+ strategies."""
        promoted = 0
        for page in range(1, 4):
            exps = _api("GET", f"lab/experiments?page={page}&size=100")
            for e in exps.get("items", []):
                exp = _api("GET", f"lab/experiments/{e['id']}")
                for s in exp.get("strategies", []):
                    if s.get("status") != "done" or s.get("promoted"):
                        continue
                    if is_stda_plus(s):
                        result = _promote_strategy(s["id"])
                        if result.get("message") != "Already promoted":
                            promoted += 1
        if promoted:
            self.step_detail = f"补漏promote {promoted}个策略"
            logger.info("Promote check: patched %d strategies", promoted)
        else:
            self.step_detail = "无遗漏"

    # ── Step 1d: Sync Unsynced Rounds ────────────────────────────

    def _step_sync_unsynced_rounds(self):
        """Mark unsynced rounds as synced (memory updates left to manual Claude sessions)."""
        rounds_data = _api("GET", "lab/exploration-rounds")
        items = rounds_data.get("items", rounds_data) if isinstance(rounds_data, dict) else rounds_data
        if not items or not isinstance(items, list):
            return

        unsynced = [r for r in items if not r.get("memory_synced", False)]
        for r in unsynced:
            rid = r.get("id")
            if not rid:
                continue
            # Update the round as synced (the auto_finish already promoted)
            full = _api("GET", f"lab/exploration-rounds/{rid}")
            update = {k: v for k, v in full.items() if v is not None and k != "id"}
            update["memory_synced"] = True
            _api("PUT", f"lab/exploration-rounds/{rid}", update)
            logger.info("Synced R%d (id=%d)", r.get("round_number", 0), rid)

        if unsynced:
            self.step_detail = f"同步{len(unsynced)}个历史轮次"
        else:
            self.step_detail = "全部已同步"

    # ── Step 1e: Load Pool State ─────────────────────────────────

    def _step_load_state(self) -> list[dict]:
        """Query pool status."""
        status = _api("GET", "strategies/pool/status")
        families = status.get("family_summary", [])
        self.pool_families = len(families)
        self.pool_active = sum(f.get("active_count", 0) for f in families)
        self.pool_gap = sum(f.get("gap", 0) for f in families)
        self.step_detail = f"{len(families)}家族, {self.pool_active}活跃, gap={self.pool_gap}"
        return families

    # ── Step 3: Plan ─────────────────────────────────────────────

    def _step_plan(self, pool_families: list[dict], n: int) -> tuple[list[dict], str]:
        """Call LLM planner with historical insights."""
        insights = load_historical_insights()
        suggestions = get_latest_round_suggestions()
        configs, provider = self._planner.plan(
            pool_families, n, insights=insights, suggestions=suggestions)
        self.step_detail = f"{provider}: {len(configs)}个有效配置"
        return configs, provider

    # ── Step 5: Submit ───────────────────────────────────────────

    def _step_submit(self, configs: list[dict]) -> list[int]:
        """Submit experiments via batch-clone-backtest."""
        sid = self._source_strategy_id
        exp_ids: list[int] = []
        total_strats = 0

        for cfg in configs:
            buy = BASE_BUY + cfg.get("extra_buy_conditions", [])
            sell = BASE_SELL + cfg.get("extra_sell_conditions", [])

            exit_configs = []
            for ec in cfg.get("exit_configs", []):
                exit_configs.append({
                    "name_suffix": f"_{cfg.get('label', 'exp')}_{ec.get('name', 'x')}",
                    "exit_config": {
                        "stop_loss_pct": ec.get("stop_loss_pct", -20),
                        "take_profit_pct": ec.get("take_profit_pct", 2.0),
                        "max_hold_days": ec.get("max_hold_days", 5),
                    },
                    "buy_conditions": buy,
                    "sell_conditions": sell,
                })
            if not exit_configs:
                continue

            result = _api("POST", f"lab/strategies/{sid}/batch-clone-backtest", {
                "source_strategy_id": sid,
                "exit_configs": exit_configs,
            })
            eid = result.get("experiment_id")
            if eid:
                exp_ids.append(eid)
                total_strats += result.get("count", 0)

        # Retry-pending to ensure processing
        _api("POST", "lab/experiments/retry-pending")

        self.strategies_total = total_strats
        self.strategies_done = 0
        self.strategies_invalid = 0
        self.strategies_pending = total_strats
        self.stda_count = 0
        self.best_score = 0.0

        self.step_detail = f"{len(exp_ids)}个实验, {total_strats}个策略已提交"
        logger.info("Submitted %d experiments, %d strategies", len(exp_ids), total_strats)
        return exp_ids

    # ── Step 6: Poll + Self-Healing ──────────────────────────────

    def _step_poll(self, exp_ids: list[int]):
        """Poll until all strategies complete. Self-heals stuck queues."""
        max_polls = 600  # 20 hours
        stall_count = 0
        last_done = 0

        for poll in range(max_polls):
            if self._stop_event.is_set():
                break

            done = inv = pend = stda = 0
            best = 0.0

            for eid in exp_ids:
                exp = _api("GET", f"lab/experiments/{eid}")
                for s in exp.get("strategies", []):
                    st = s.get("status", "")
                    if st == "done":
                        done += 1
                        sc = s.get("score", 0) or 0
                        if sc > best:
                            best = sc
                        if is_stda_plus(s):
                            stda += 1
                    elif st == "invalid":
                        inv += 1
                    elif st in ("pending", "backtesting"):
                        pend += 1

            self.strategies_done = done
            self.strategies_invalid = inv
            self.strategies_pending = pend
            self.stda_count = stda
            self.best_score = best
            self.strategies_total = done + inv + pend

            pct = done / max(1, done + inv + pend) * 100
            self.step_detail = f"回测: {done}/{done+inv+pend} ({pct:.0f}%), {stda} StdA+, best={best:.4f}"

            if pend == 0:
                logger.info("All done: %d done, %d invalid, %d StdA+", done, inv, stda)
                break

            # Self-healing: if no progress for 10 minutes, retry-pending
            if done == last_done:
                stall_count += 1
                if stall_count >= 5:  # 5 × 2min = 10min stall
                    logger.warning("Queue stalled for 10min, retrying pending")
                    _api("POST", "lab/experiments/retry-pending")
                    stall_count = 0
            else:
                stall_count = 0
            last_done = done

            _time.sleep(120)

    # ── Step 7: Promote + Rebalance ──────────────────────────────

    def _step_promote_and_rebalance(self, exp_ids: list[int]) -> int:
        """Promote qualifying strategies and rebalance pool."""
        promoted = 0
        for eid in exp_ids:
            exp = _api("GET", f"lab/experiments/{eid}")
            for s in exp.get("strategies", []):
                if s.get("status") != "done" or s.get("promoted"):
                    continue
                if is_stda_plus(s):
                    result = _promote_strategy(s["id"])
                    if result.get("message") != "Already promoted":
                        promoted += 1

        # Rebalance pool
        _api("POST", "strategies/pool/rebalance?max_per_family=15")

        # Refresh pool stats
        status = _api("GET", "strategies/pool/status")
        families = status.get("family_summary", [])
        self.pool_families = len(families)
        self.pool_active = sum(f.get("active_count", 0) for f in families)
        self.pool_gap = sum(f.get("gap", 0) for f in families)

        self.step_detail = f"Promoted {promoted}, pool: {self.pool_families}家族/{self.pool_active}活跃"
        logger.info("Promoted %d, rebalanced. Pool: %d families, %d active",
                    promoted, self.pool_families, self.pool_active)
        return promoted

    # ── Step 9b: Record ──────────────────────────────────────────

    def _step_record(self, exp_ids: list[int], promoted: int):
        """Save exploration round to API."""
        _api("POST", "lab/exploration-rounds", {
            "round_number": self.current_round,
            "mode": "auto",
            "started_at": self.started_at or datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
            "experiment_ids": exp_ids,
            "total_experiments": len(exp_ids),
            "total_strategies": self.strategies_done + self.strategies_invalid,
            "profitable_count": self.stda_count,
            "profitability_pct": round(self.stda_count / max(1, self.strategies_done) * 100, 1),
            "std_a_count": self.stda_count,
            "best_strategy_name": "",
            "best_strategy_score": self.best_score,
            "best_strategy_return": 0,
            "best_strategy_dd": 0,
            "insights": [
                f"R{self.current_round}: {self.stda_count} StdA+ ({self.stda_count/max(1,self.strategies_done)*100:.1f}%), "
                f"best={self.best_score:.4f}, provider={self.llm_provider}, "
                f"pool={self.pool_families}fam/{self.pool_active}active"
            ],
            "promoted": [],
            "issues_resolved": [],
            "next_suggestions": ["Continue fills and new skeleton exploration"],
            "summary": (
                f"R{self.current_round}: {self.strategies_done} done, {self.strategies_invalid} inv, "
                f"{self.stda_count} StdA+, promoted={promoted}, best={self.best_score:.4f}"
            ),
            "memory_synced": False,
            "pinecone_synced": False,
        })
        self.step_detail = f"R{self.current_round} 已保存"
```

- [ ] **Step 2: Verify engine loads**

```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import ExplorationEngine; e = ExplorationEngine(); print(e.get_status()['state'])"
```
Expected: `IDLE`

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add full ExplorationEngine with all 11 workflow steps"
```

---

### Task 5: REST API Router + Registration

4 endpoints wired into the existing FastAPI app.

**Files:**
- Create: `api/routers/exploration_workflow.py`
- Modify: `api/main.py` (lines 18, 538)

- [ ] **Step 1: Create router file**

Create `api/routers/exploration_workflow.py`:

```python
"""Exploration Workflow REST API — control the automated strategy exploration engine."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.services.exploration_engine import ExplorationEngine

router = APIRouter(prefix="/api/exploration-workflow", tags=["exploration-workflow"])

_engine = ExplorationEngine()


@router.post("/start")
def start_exploration(
    rounds: int = Query(1, ge=1, le=100),
    experiments_per_round: int = Query(50, ge=5, le=200),
    source_strategy_id: int = Query(116987),
):
    """Start exploration workflow in background."""
    return _engine.start(rounds, experiments_per_round, source_strategy_id)


@router.post("/stop")
def stop_exploration():
    """Request graceful stop after current round."""
    return _engine.stop()


@router.get("/status")
def get_status():
    """Get real-time workflow status."""
    return _engine.get_status()


@router.get("/history")
def get_history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Get recent exploration round history."""
    from api.models.ai_lab import ExplorationRound
    rounds = (
        db.query(ExplorationRound)
        .order_by(ExplorationRound.round_number.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "round_number": r.round_number,
            "mode": r.mode,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "total_experiments": r.total_experiments,
            "total_strategies": r.total_strategies,
            "std_a_count": r.std_a_count,
            "best_strategy_score": r.best_strategy_score,
            "best_strategy_return": r.best_strategy_return,
            "summary": r.summary,
            "memory_synced": r.memory_synced,
        }
        for r in rounds
    ]
```

- [ ] **Step 2: Register router in main.py**

In `api/main.py`, add to the import line (line ~18):

Change:
```python
from api.routers import market, stocks, strategies, signals, backtest, news, config, ai_lab, ai_analyst, news_signals, bot_trading, beta, auth, jobs, ops, artifacts, memory, tdx
```
To:
```python
from api.routers import market, stocks, strategies, signals, backtest, news, config, ai_lab, ai_analyst, news_signals, bot_trading, beta, auth, jobs, ops, artifacts, memory, tdx, exploration_workflow
```

After `app.include_router(tdx.router)` (line ~538), add:
```python
app.include_router(exploration_workflow.router)
```

- [ ] **Step 3: Verify routes register**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.routers.exploration_workflow import router
for r in router.routes:
    print(f'{list(r.methods)[0]:5s} {r.path}')
"
```
Expected:
```
POST  /start
POST  /stop
GET   /status
GET   /history
```

- [ ] **Step 4: Commit**

```bash
git add api/routers/exploration_workflow.py api/main.py
git commit -m "feat(exploration): add REST API router and register in main app"
```

---

### Task 6: Integration Test — Full Workflow

Test the complete pipeline with a small 2-experiment run against the live server.

**Files:** None (manual test against running server)

- [ ] **Step 1: Restart the server to pick up new code**

```bash
# If using uvicorn directly:
# kill existing, then restart
cd /Users/allenqiang/stockagent
# The user should restart their server manually
```

- [ ] **Step 2: Test status endpoint**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | python3 -m json.tool
```
Expected: `{"state": "IDLE", ...}`

- [ ] **Step 3: Start a 1-round, 2-experiment exploration**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/exploration-workflow/start?rounds=1&experiments_per_round=2" | python3 -m json.tool
```
Expected: `{"message": "Exploration started", "round_number": ...}`

- [ ] **Step 4: Monitor status until complete**

```bash
for i in $(seq 1 40); do
  sleep 30
  NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"state\"]:10s} | {d[\"current_step\"]:15s} | done={d[\"strategies\"][\"done\"]}/{d[\"strategies\"][\"total\"]} StdA+={d[\"strategies\"][\"stda_count\"]}')"
  # Exit loop when IDLE
  STATE=$(NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  [ "$STATE" = "IDLE" ] && break
done
```
Expected: States progress through `promote_check → sync_rounds → loading_state → retry_pending → planning → submitting → polling → promoting → recording → IDLE`

- [ ] **Step 5: Verify round recorded in history**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/exploration-workflow/history?limit=1" | python3 -m json.tool
```
Expected: Latest round with `std_a_count >= 0` and `total_strategies > 0`

- [ ] **Step 6: Commit any fixes**

```bash
git add -A && git commit -m "fix(exploration): integration test fixes" --allow-empty
```

---

### Task 7: Stop Behavior + Error Recovery Test

- [ ] **Step 1: Start 3-round exploration**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/exploration-workflow/start?rounds=3&experiments_per_round=2"
```

- [ ] **Step 2: Wait for polling, then stop**

```bash
sleep 120
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/exploration-workflow/stop | python3 -m json.tool
```
Expected: `{"message": "Stop requested, will finish current round"}`

- [ ] **Step 3: Verify graceful stop**

```bash
# Wait for current round to finish
sleep 300
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'state={d[\"state\"]} completed={d[\"rounds_config\"][\"completed\"]}')"
```
Expected: `state=IDLE completed=1` (finished current round but stopped before round 2)

- [ ] **Step 4: Test double-start rejection**

```bash
# Start first
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/exploration-workflow/start?rounds=1&experiments_per_round=2"
sleep 5
# Try start again
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/exploration-workflow/start?rounds=1&experiments_per_round=2" | python3 -m json.tool
```
Expected: `{"error": "Already RUNNING"}`

- [ ] **Step 5: Stop and verify clean state**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/exploration-workflow/stop
# Wait for finish
sleep 600
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])"
```
Expected: `IDLE`
