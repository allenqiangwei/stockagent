# Exploration Workflow Engine Implementation Plan (v3 — Complete)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify the COMPLETE 11-step strategy exploration workflow into a FastAPI-integrated engine — zero functionality loss vs the original Claude skill. Every step from the SKILL.md is implemented.

**Architecture:** Single service file (`exploration_engine.py` ~1400 lines) with all workflow logic. Single router file (`exploration_workflow.py` ~80 lines). The engine calls internal APIs via localhost HTTP, keeping it fully decoupled.

**Tech Stack:** Python 3.11, FastAPI, OpenAI SDK (for Qwen/DeepSeek), SQLAlchemy, threading

---

## SKILL Steps → Engine Methods Mapping

| SKILL Step | Engine Method | Task |
|------------|--------------|------|
| 1a Load memory doc | `load_historical_insights()` | T2 |
| 1a API suggestions | `get_latest_round_suggestions()` | T2 |
| 1b Promote check | `_step_promote_check()` | T4 |
| 1d Sync unsynced rounds | `_step_sync_unsynced_rounds()` | T4 |
| 1e Pool status | `_step_load_state()` | T4 |
| 1f Skeleton candidates | `_generate_skeleton_candidates()` | T2 |
| 1.5 Retry pending | inline in loop | T4 |
| 3 Plan (LLM) | `_step_plan()` → `LLMPlanner` | T3 |
| 5 Submit | `_step_submit()` | T4 |
| 6 Poll + self-heal | `_step_poll()` + `_step_self_heal()` | T4 |
| 7a Promote StdA+ | `_step_promote_and_rebalance()` | T4 |
| 7a Standard B (regime) | inside promote step | T4 |
| 7b Rebalance | inside promote step | T4 |
| 8a Update markdown | `_step_update_memory_doc()` | T5 |
| 8b Pinecone sync | `_step_sync_pinecone()` | T5 |
| 9b Save round | `_step_record()` | T4 |
| 10 Resolve problems | `_step_resolve_problems()` | T6 |
| 11 Loop/stop | `_run_loop()` | T4 |

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `api/services/exploration_engine.py` | Create | Everything: registry, validator, insight loader, skeleton generator, LLM planner, engine, memory updater, problem resolver |
| `api/routers/exploration_workflow.py` | Create | 4 REST endpoints |
| `api/main.py` | Modify (line ~538) | Register router |

---

### Task 1: Factor Registry + Config Validator + StdA+ Checker

**Files:**
- Create: `api/services/exploration_engine.py`

- [ ] **Step 1: Create file with all foundation code**

```python
"""Exploration Workflow Engine — Complete automated strategy exploration.

Pipeline: Load State → Verify Promote → Sync Rounds → Generate Candidates
→ Plan (LLM) → Submit → Poll + Self-Heal → Promote (A+B) → Rebalance
→ Update Memory Doc → Pinecone Sync → Record Round → Resolve Problems → Loop

Controlled via REST API: start / stop / status / history
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

SELL_ONLY_FIELDS = frozenset({"KDJ_K", "close"})

BASE_BUY = [
    {"field": "RSI", "params": {"period": 14}, "operator": ">", "compare_type": "value", "compare_value": 48},
    {"field": "RSI", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 66},
    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.091},
]
BASE_SELL = [
    {"field": "KDJ_K", "params": {"k": 9, "d": 3, "j": 3}, "operator": ">",
     "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
    {"field": "close", "operator": "<", "compare_type": "pct_change", "compare_value": -0.5},
]

STDA_SCORE, STDA_RETURN, STDA_DD, STDA_TRADES, STDA_WR = 0.80, 60, 18, 50, 60


def is_stda_plus(s: dict) -> bool:
    """Check if strategy dict meets StdA+ criteria."""
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
        return [f"{context}: missing 'field'"]
    if field in BANNED_FIELDS:
        return [f"{context}: banned field '{field}'"]
    all_valid = set(VALID_BUY_FACTORS.keys()) | SELL_ONLY_FIELDS
    if field not in all_valid:
        issues.append(f"{context}: unknown field '{field}'")
    if "operator" not in cond:
        issues.append(f"{context}: missing 'operator'")
    elif cond["operator"] not in ("<", ">", "<=", ">="):
        issues.append(f"{context}: bad operator")
    ct = cond.get("compare_type")
    if ct and ct not in ("value", "consecutive", "pct_change", "field", "lookback_min", "lookback_max"):
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
                issues.append(f"exit[{i}]: not a dict"); continue
            if not isinstance(ec.get("stop_loss_pct"), (int, float)):
                issues.append(f"exit[{i}]: bad stop_loss_pct")
            if not isinstance(ec.get("take_profit_pct"), (int, float)) or ec.get("take_profit_pct", 0) <= 0:
                issues.append(f"exit[{i}]: bad take_profit_pct")
            if not isinstance(ec.get("max_hold_days"), int) or ec.get("max_hold_days", 0) < 1:
                issues.append(f"exit[{i}]: bad max_hold_days")
    return len(issues) == 0, issues
```

- [ ] **Step 2: Verify**

```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import validate_experiment_config, VALID_BUY_FACTORS, is_stda_plus; print(f'OK: {len(VALID_BUY_FACTORS)} factors')"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add factor registry, config validator, StdA+ checker"
```

---

### Task 2: Internal API + Insight Loader + Skeleton Candidate Generator

Three utilities: HTTP helper for internal APIs, historical insight extractor from markdown, and code-level skeleton candidate matrix generator (Step 1f).

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Append internal API helper, insight loader, and skeleton generator**

Append to `api/services/exploration_engine.py`:

```python
# ── Internal API ─────────────────────────────────────────────────

def _api(method: str, path: str, data: dict | None = None, timeout: int = 60) -> dict:
    """Call our own FastAPI via HTTP localhost:8050."""
    cmd = ["curl", "-s"]
    if method.upper() != "GET":
        cmd.extend(["-X", method.upper()])
    url = f"http://127.0.0.1:8050/api/{path}"
    if data is not None:
        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(data)])
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           env={"NO_PROXY": "localhost,127.0.0.1", "PATH": "/usr/bin:/bin"},
                           timeout=timeout)
        return json.loads(r.stdout)
    except Exception as e:
        logger.error("_api %s %s: %s", method, path, e)
        return {}


def _promote_strategy(sid: int, label: str = "[AI]", category: str = "全能") -> dict:
    el = urllib.parse.quote(label)
    ec = urllib.parse.quote(category)
    return _api("POST", f"lab/strategies/{sid}/promote?label={el}&category={ec}")


# ── Insight Loader (Step 1a) ─────────────────────────────────────

_INSIGHT_DOC = Path(__file__).parent.parent.parent / "docs" / "lab-experiment-analysis.md"


def load_historical_insights() -> str:
    """Extract core insights + exploration status + next suggestions from markdown."""
    if not _INSIGHT_DOC.exists():
        return ""
    text = _INSIGHT_DOC.read_text(encoding="utf-8")
    sections = []

    # 核心洞察
    m = re.search(r"## 核心洞察\s*\n([\s\S]*?)(?=\n## )", text)
    if m:
        lines = [l.strip() for l in m.group(1).strip().split("\n")
                 if re.match(r"\d+\.", l.strip())]
        if lines:
            sections.append("核心洞察:\n" + "\n".join(lines[:10]))

    # 有效方向
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

    return "\n\n".join(sections) if sections else text[:500]


def get_latest_round_suggestions() -> list[str]:
    """Get next_suggestions from latest exploration round."""
    rounds = _api("GET", "lab/exploration-rounds")
    items = rounds.get("items", rounds) if isinstance(rounds, dict) else rounds
    if not items or not isinstance(items, list):
        return []
    latest = max(items, key=lambda r: r.get("round_number", 0))
    return latest.get("next_suggestions", [])


# ── Skeleton Candidate Generator (Step 1f) ───────────────────────

def generate_skeleton_candidates(existing_families: list[dict], max_candidates: int = 30) -> list[str]:
    """Generate new indicator combo candidates NOT in the pool.

    Produces human-readable strings like 'KBAR_amplitude + W_REALVOL'
    for injection into the LLM prompt.
    """
    # Parse existing family names into indicator sets
    existing_sets: set[frozenset[str]] = set()
    for fam in existing_families:
        name = fam.get("family", "")
        # Family names like "ATR+RSI+W_REALVOL" → {"ATR", "RSI", "W_REALVOL"}
        parts = frozenset(p.strip() for p in name.split("+") if p.strip())
        if parts:
            existing_sets.add(parts)

    # All factor names (without the base ATR+RSI which is always present)
    factors = sorted(VALID_BUY_FACTORS.keys())

    candidates: list[str] = []

    # 2-factor combos (will be ATR+RSI+factor1+factor2 in reality)
    for a, b in itertools.combinations(factors, 2):
        combo = frozenset({"ATR", "RSI", a, b})
        if combo not in existing_sets:
            candidates.append(f"{a} + {b}")
        if len(candidates) >= max_candidates:
            break

    # If not enough, try 3-factor combos
    if len(candidates) < max_candidates:
        for a, b, c in itertools.combinations(factors[:15], 3):
            if len(candidates) >= max_candidates:
                break
            combo = frozenset({"ATR", "RSI", a, b, c})
            if combo not in existing_sets:
                candidates.append(f"{a} + {b} + {c}")

    return candidates[:max_candidates]
```

- [ ] **Step 2: Test all three utilities**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.exploration_engine import load_historical_insights, generate_skeleton_candidates

# Test insight loader
insights = load_historical_insights()
print(f'Insights: {len(insights)} chars')
print(insights[:200])
print('---')

# Test skeleton generator (mock families)
families = [{'family': 'ATR+RSI', 'gap': 0}, {'family': 'ATR+RSI+W_REALVOL', 'gap': 100}]
candidates = generate_skeleton_candidates(families, max_candidates=5)
print(f'Candidates ({len(candidates)}): {candidates}')
"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add internal API, insight loader, skeleton candidate generator"
```

---

### Task 3: LLM Planner with Full Context Injection

The planner receives: pool state + historical insights + latest suggestions + skeleton candidates. Few-shot prompt fixes Qwen sell format. Fallback chain: Qwen → DeepSeek → rules.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Append planner system prompt, user prompt builder, and LLMPlanner class**

Append to `api/services/exploration_engine.py` the full `_PLANNER_SYSTEM_PROMPT`, `_build_user_prompt()`, and `LLMPlanner` class exactly as shown in the v2 plan's Task 3 Step 1 (the code is identical — the system prompt with few-shot sell examples, the user prompt builder that injects pool + insights + suggestions + skeleton candidates, and the LLMPlanner with `_call_llm`, `_parse_json`, `_rule_based`).

**One addition to `_build_user_prompt()`** — inject skeleton candidates:

```python
def _build_user_prompt(pool_families: list[dict], n_experiments: int,
                       insights: str, suggestions: list[str],
                       skeleton_candidates: list[str]) -> str:
    """Build user prompt from pool state + historical context + candidates."""
    # ... (same pool_text, full_text, n_fill/n_new/n_opt as before) ...

    # Add skeleton candidates
    cand_text = ""
    if skeleton_candidates:
        cand_text = "\n新骨架候选(池中不存在的组合,供参考):\n" + "\n".join(
            f"  - {c}" for c in skeleton_candidates[:15])

    return f"""池状态: {len(pool_families)}家族, 总gap=...
Top未满家族:
{pool_text}{full_text}{sug_text}{insight_text}{cand_text}

请输出{n_experiments}个实验配置...
"""
```

**And update `LLMPlanner.plan()` signature** to accept `skeleton_candidates`:

```python
def plan(self, pool_families, n_experiments, insights="", suggestions=None,
         skeleton_candidates=None) -> tuple[list[dict], str]:
    user_prompt = _build_user_prompt(
        pool_families, n_experiments, insights, suggestions or [],
        skeleton_candidates or [])
    # ... rest same ...
```

- [ ] **Step 2: Verify planner loads**

```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import LLMPlanner; p = LLMPlanner(); print(f'Providers: {[pr[\"name\"] for pr in p._providers]}')"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add LLM planner with insight + skeleton candidate injection"
```

---

### Task 4: Engine Core — Full Workflow Loop

The main class with ALL steps. This is the largest task.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Append ExplorationEngine class**

The class includes:
- `start()`, `stop()`, `get_status()` — public API
- `_run_loop()` — main loop calling all steps in order
- `_step_promote_check()` — Step 1b: scan 300 recent experiments for unpromoted StdA+
- `_step_sync_unsynced_rounds()` — Step 1d: find `memory_synced=false` rounds, mark synced
- `_step_load_state()` — Step 1e: query pool/status
- `_step_plan()` — Step 3: load insights + suggestions + candidates → LLM
- `_step_submit()` — Step 5: batch-clone-backtest + retry-pending
- `_step_poll()` — Step 6: 2-min polling with stall detection → retry-pending
- `_step_self_heal()` — Step 6 extension: if invalid_rate > 50%, re-submit with loosened thresholds
- `_step_promote_and_rebalance()` — Step 7a + 7b: StdA+ promote + Standard B regime champions + rebalance
- `_step_record()` — Step 9b: save round to API

The code is the same as v2 plan Task 4, with these additions:

**Standard B promote** (inside `_step_promote_and_rebalance`):

```python
# Standard B: regime champions
LABEL_MAP = {"bull": ("[AI-牛市]", "牛市"), "bear": ("[AI-熊市]", "熊市"), "rang": ("[AI-震荡]", "震荡")}
regime_best: dict[str, tuple[int, float]] = {}  # regime_key → (strategy_id, pnl)

for eid in exp_ids:
    exp = _api("GET", f"lab/experiments/{eid}")
    for s in exp.get("strategies", []):
        if s.get("status") != "done":
            continue
        ret = s.get("total_return_pct", 0) or 0
        if ret <= 0:
            continue
        for rname, rdata in (s.get("regime_stats") or {}).items():
            pnl = rdata.get("total_pnl", 0) or 0
            if pnl <= 100:
                continue
            for key in LABEL_MAP:
                if key in rname.lower():
                    if key not in regime_best or pnl > regime_best[key][1]:
                        regime_best[key] = (s["id"], pnl)
                    break

for key, (sid, pnl) in regime_best.items():
    label, cat = LABEL_MAP[key]
    _promote_strategy(sid, label, cat)
    logger.info("Standard B: %s champion S%d (pnl=%.0f)", key, sid, pnl)
```

**Self-heal** (called after `_step_poll` if invalid rate high):

```python
def _step_self_heal(self, exp_ids: list[int], original_configs: list[dict]) -> list[int]:
    """If invalid_rate > 50%, re-submit failed experiments with loosened thresholds."""
    if self.strategies_invalid <= self.strategies_done:
        return []  # invalid rate <= 50%, no action

    logger.warning("Self-heal: %d invalid vs %d done, re-submitting with loosened thresholds",
                  self.strategies_invalid, self.strategies_done)

    # Find which experiments had high invalid rate
    new_exp_ids: list[int] = []
    for cfg in original_configs:
        # Loosen buy condition thresholds by 20%
        loosened = json.loads(json.dumps(cfg))  # deep copy
        for cond in loosened.get("extra_buy_conditions", []):
            v = cond.get("compare_value")
            if v is not None and isinstance(v, (int, float)):
                if cond.get("operator") == "<":
                    cond["compare_value"] = round(v * 1.2, 4)  # widen upper bound
                elif cond.get("operator") == ">":
                    cond["compare_value"] = round(v * 0.8, 4)  # lower lower bound
        loosened["label"] = cfg.get("label", "x") + "_loosened"

        # Re-submit
        new_ids = self._submit_single(loosened)
        new_exp_ids.extend(new_ids)

    if new_exp_ids:
        _api("POST", "lab/experiments/retry-pending")
        logger.info("Self-heal: re-submitted %d experiments", len(new_exp_ids))

    return new_exp_ids
```

**Updated `_run_loop`** calls all steps:

```python
def _run_loop(self, rounds, exp_per_round):
    try:
        for i in range(rounds):
            if self._stop_event.is_set(): break

            # Step 1b
            self._set_step("promote_check", "检查历史未promote的StdA+")
            self._step_promote_check()
            if self._stop_event.is_set(): break

            # Step 1d
            self._set_step("sync_rounds", "同步未完成轮次")
            self._step_sync_unsynced_rounds()
            if self._stop_event.is_set(): break

            # Step 1e
            self._set_step("loading_state", "查询池状态")
            pool_families = self._step_load_state()
            if self._stop_event.is_set(): break

            # Step 1.5
            self._set_step("retry_pending", "恢复stuck队列")
            _api("POST", "lab/experiments/retry-pending")
            if self._stop_event.is_set(): break

            # Step 3
            self._set_step("planning", "LLM规划实验")
            configs, provider = self._step_plan(pool_families, exp_per_round)
            self.llm_provider = provider
            if self._stop_event.is_set(): break

            # Step 5
            self._set_step("submitting", f"提交{len(configs)}个实验")
            exp_ids = self._step_submit(configs)
            self.experiment_ids = exp_ids

            # Step 6: Poll
            self._set_step("polling", "等待回测")
            self._step_poll(exp_ids)

            # Step 6 extension: Self-heal
            heal_ids = self._step_self_heal(exp_ids, configs)
            if heal_ids:
                self._set_step("polling_heal", "自愈实验回测中")
                exp_ids.extend(heal_ids)
                self._step_poll(heal_ids)

            # Step 7: Promote + Rebalance (includes Standard B)
            self._set_step("promoting", "Promote + Rebalance")
            promoted = self._step_promote_and_rebalance(exp_ids)

            # Step 8a: Update memory doc
            self._set_step("updating_doc", "更新实验文档")
            self._step_update_memory_doc(promoted)

            # Step 8b: Pinecone sync
            self._set_step("syncing_pinecone", "Pinecone同步")
            self._step_sync_pinecone()

            # Step 9b: Record
            self._set_step("recording", "保存轮次记录")
            self._step_record(exp_ids, promoted)

            # Step 10: Resolve problems
            self._set_step("resolving", "检测并解决问题")
            self._step_resolve_problems(exp_ids)

            self.rounds_completed += 1
            self.current_round += 1

    except Exception as e:
        logger.exception("Engine error")
        self.last_error = str(e)
        self.state = "ERROR"
        return

    self.state = "IDLE"
    self.current_step = ""
    self.step_detail = ""
```

- [ ] **Step 2: Verify engine loads**

```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import ExplorationEngine; e = ExplorationEngine(); print(e.get_status()['state'])"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add ExplorationEngine with all 11 workflow steps including self-heal and Standard B"
```

---

### Task 5: Memory Doc Updater + Pinecone Sync (Step 8)

Updates `docs/lab-experiment-analysis.md` with round results and runs `scripts/sync-memory.py`.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add memory doc updater and Pinecone sync methods**

Add as methods of `ExplorationEngine`:

```python
def _step_update_memory_doc(self, promoted: int):
    """Step 8a: Update lab-experiment-analysis.md with round results."""
    if not _INSIGHT_DOC.exists():
        logger.warning("Memory doc not found, skipping update")
        return

    text = _INSIGHT_DOC.read_text(encoding="utf-8")

    # Update Auto-Promote record section
    old_promote = re.search(
        r"(> 累计 \*\*[\d,]+\+?\*\* 个StdA\+策略已promote。[\s\S]*?)(?=\n---)",
        text,
    )
    if old_promote:
        # Parse current cumulative count
        count_match = re.search(r"\*\*(\d[\d,]*)\+?\*\*", old_promote.group(1))
        old_count = int(count_match.group(1).replace(",", "")) if count_match else 0
        new_count = old_count + self.stda_count

        new_block = (
            f"> 累计 **{new_count:,}+** 个StdA+策略已promote。"
            f"策略来源: R1-R{self.current_round}, {self.current_round}轮探索。\n"
            f"> **R{self.current_round}**: **{self.stda_count} StdA+ "
            f"({self.stda_count/max(1,self.strategies_done)*100:.1f}%)** — "
            f"best={self.best_score:.4f}, provider={self.llm_provider}, "
            f"promoted={promoted}。Pool: {self.pool_families}家族, {self.pool_active}活跃"
        )
        text = text[:old_promote.start()] + new_block + text[old_promote.end():]

    # Update 下一步优先级 section
    old_next = re.search(
        r"(### 下一步优先级[^\n]*\n[\s\S]*?)(?=\n## 历史|$)",
        text,
    )
    if old_next:
        new_next = (
            f"### R{self.current_round} 自动探索结果\n\n"
            f"**{self.stda_count} StdA+ ({self.stda_count/max(1,self.strategies_done)*100:.1f}%)**, "
            f"best={self.best_score:.4f}, provider={self.llm_provider}\n\n"
            f"### 下一步优先级 (R{self.current_round + 1}+)\n\n"
            f"1. **继续fill top-gap家族** — pool gap={self.pool_gap}\n"
            f"2. **深度fill高分家族** — 验证有效方向的更多参数\n"
            f"3. **新骨架探索** — 未测试的因子组合\n"
        )
        text = text[:old_next.start()] + new_next + text[old_next.end():]

    _INSIGHT_DOC.write_text(text, encoding="utf-8")
    self.step_detail = f"文档已更新 (R{self.current_round})"
    logger.info("Memory doc updated for R%d", self.current_round)


def _step_sync_pinecone(self):
    """Step 8b: Run sync-memory.py to push to Pinecone."""
    script = Path(__file__).parent.parent.parent / "scripts" / "sync-memory.py"
    if not script.exists():
        logger.warning("sync-memory.py not found, skipping")
        self.step_detail = "sync脚本不存在,跳过"
        return
    try:
        r = subprocess.run(
            ["python3", str(script)],
            capture_output=True, text=True,
            cwd=str(script.parent.parent),
            timeout=120,
        )
        if r.returncode == 0:
            self.step_detail = "Pinecone同步完成"
            logger.info("Pinecone sync OK")
        else:
            self.step_detail = f"Pinecone同步失败: {r.stderr[:100]}"
            logger.warning("Pinecone sync failed: %s", r.stderr[:200])
    except Exception as e:
        self.step_detail = f"Pinecone同步异常: {e}"
        logger.warning("Pinecone sync error: %s", e)
```

- [ ] **Step 2: Verify methods exist**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.exploration_engine import ExplorationEngine
e = ExplorationEngine()
print(hasattr(e, '_step_update_memory_doc'))
print(hasattr(e, '_step_sync_pinecone'))
"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add memory doc updater and Pinecone sync (Step 8)"
```

---

### Task 6: Problem Resolver (Step 10)

Automated problem detection and resolution: zombie experiments, stuck queue, cleanup.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add problem resolver method**

Add as method of `ExplorationEngine`:

```python
def _step_resolve_problems(self, exp_ids: list[int]):
    """Step 10: Detect and resolve problems automatically.

    Handles:
    - Zombie experiments stuck in backtesting/pending
    - Strategies that should be promoted but weren't
    - Pool cleanup (remove below-threshold strategies)
    """
    issues_resolved: list[str] = []

    # 1. Check for zombie experiments (stuck > this round's experiments)
    zombies = 0
    recent_exps = _api("GET", "lab/experiments?page=1&size=50")
    for e in recent_exps.get("items", []):
        if e.get("id") in exp_ids:
            continue  # Skip current round
        if e.get("status") in ("backtesting", "pending", "generating"):
            exp = _api("GET", f"lab/experiments/{e['id']}")
            pend = sum(1 for s in exp.get("strategies", [])
                      if s.get("status") in ("pending", "backtesting"))
            if pend > 0:
                zombies += pend
    if zombies:
        _api("POST", "lab/experiments/retry-pending")
        issues_resolved.append(f"Retry-pending for {zombies} zombie strategies")
        logger.info("Step 10: retried %d zombie strategies", zombies)

    # 2. Final promote sweep (catch any missed in this round)
    missed = 0
    for eid in exp_ids:
        exp = _api("GET", f"lab/experiments/{eid}")
        for s in exp.get("strategies", []):
            if s.get("status") == "done" and not s.get("promoted") and is_stda_plus(s):
                _promote_strategy(s["id"])
                missed += 1
    if missed:
        issues_resolved.append(f"Promoted {missed} missed StdA+ strategies")

    # 3. Run pool cleanup
    cleanup = _api("POST", "strategies/cleanup")
    deleted = cleanup.get("deleted", 0)
    if deleted:
        issues_resolved.append(f"Cleaned up {deleted} below-threshold strategies")

    self.step_detail = f"{len(issues_resolved)} issues resolved" if issues_resolved else "无问题"
    logger.info("Step 10: %d issues resolved: %s", len(issues_resolved), issues_resolved)
```

- [ ] **Step 2: Verify**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.services.exploration_engine import ExplorationEngine
e = ExplorationEngine()
print(hasattr(e, '_step_resolve_problems'))
"
```

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add problem resolver (Step 10) — zombies, missed promotes, cleanup"
```

---

### Task 7: REST API Router + Registration

**Files:**
- Create: `api/routers/exploration_workflow.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create router**

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
            "round_number": r.round_number, "mode": r.mode,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "total_experiments": r.total_experiments,
            "total_strategies": r.total_strategies,
            "std_a_count": r.std_a_count,
            "best_strategy_score": r.best_strategy_score,
            "summary": r.summary,
            "memory_synced": r.memory_synced,
        }
        for r in rounds
    ]
```

- [ ] **Step 2: Register in main.py**

Add `exploration_workflow` to the import line and add `app.include_router(exploration_workflow.router)`.

- [ ] **Step 3: Verify**

```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.routers.exploration_workflow import router
for r in router.routes: print(f'{list(r.methods)[0]:5s} {r.path}')
"
```

- [ ] **Step 4: Commit**

```bash
git add api/routers/exploration_workflow.py api/main.py
git commit -m "feat(exploration): add REST API router and register in app"
```

---

### Task 8: Integration Test — Full Pipeline

Test the complete workflow with 2 experiments against live server.

- [ ] **Step 1: Test status (IDLE)**
- [ ] **Step 2: Start 1-round, 2-experiment exploration**
- [ ] **Step 3: Monitor through all steps until IDLE**
- [ ] **Step 4: Verify round in history**
- [ ] **Step 5: Verify memory doc was updated**
- [ ] **Step 6: Commit fixes**

(Same commands as v2 plan Task 6)

---

### Task 9: Stop Behavior + Error Recovery

- [ ] **Step 1: Start 3-round, stop during round 1**
- [ ] **Step 2: Verify graceful stop (completed=1, not 3)**
- [ ] **Step 3: Test double-start rejection**
- [ ] **Step 4: Verify clean IDLE state after stop**

(Same commands as v2 plan Task 7)
