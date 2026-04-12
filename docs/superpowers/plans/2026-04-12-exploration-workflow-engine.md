# Exploration Workflow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify the strategy exploration workflow into a FastAPI-integrated engine with REST API control, LLM-powered planning (Qwen primary), and automated backtest-promote-record pipeline.

**Architecture:** Single service file (`exploration_engine.py`) containing `ExplorationEngine` (singleton, background thread), `LLMPlanner` (Qwen→DeepSeek→rules fallback), and config validation. Single router file (`exploration_workflow.py`) with 4 endpoints. Integrated into existing FastAPI app.

**Tech Stack:** Python 3.11, FastAPI, OpenAI SDK (for Qwen/DeepSeek), SQLAlchemy, threading

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `api/services/exploration_engine.py` | Create | Engine core: LLMPlanner, ConfigValidator, ExplorationEngine |
| `api/routers/exploration_workflow.py` | Create | 4 REST endpoints: start, stop, status, history |
| `api/main.py` | Modify (line ~538) | Register new router |

---

### Task 1: Config Validator

The validator checks LLM-generated experiment configs for correctness. This is a pure function with no external dependencies — ideal to build and test first.

**Files:**
- Create: `api/services/exploration_engine.py`

- [ ] **Step 1: Create file with factor registry and validator**

```python
"""Exploration Workflow Engine.

Automated strategy exploration: LLM-powered planning → batch submission
→ polling → promote → record. Controlled via REST API.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Factor Registry ──────────────────────────────────────────────

# field_name → {operator, params_required, typical_min, typical_max}
VALID_BUY_FACTORS: dict[str, dict] = {
    "KBAR_amplitude":    {"op": "<", "params": None,            "min": 0.01, "max": 0.10},
    "W_REALVOL":         {"op": "<", "params": {"period": 20},  "min": 5,    "max": 50},
    "REALVOL":           {"op": "<", "params": {"period": 20},  "min": 5,    "max": 60},
    "REALVOL_kurt":      {"op": "<", "params": {"period": 20},  "min": 1,    "max": 8},
    "REALVOL_downside":  {"op": "<", "params": {"period": 20},  "min": 5,    "max": 40},
    "AMPVOL_std":        {"op": "<", "params": {"period": 5},   "min": 0.005,"max": 0.05},
    "W_AMPVOL_std":      {"op": "<", "params": {"period": 5},   "min": 0.01, "max": 0.08},
    "RSTR_weighted":     {"op": ">", "params": {"period": 20},  "min": -2,   "max": 3},
    "W_RSTR_weighted":   {"op": ">", "params": {"period": 20},  "min": -2,   "max": 3},
    "PVOL_corr":         {"op": ">", "params": {"period": 20},  "min": -0.5, "max": 0.8},
    "PVOL_amount_conc":  {"op": "<", "params": {"period": 20},  "min": 0.05, "max": 0.9},
    "MOM":               {"op": ">", "params": {"period": 20},  "min": -3,   "max": 5},
    "LIQ_turnover_vol":  {"op": ">", "params": {"period": 20},  "min": 0.1,  "max": 5},
    "W_ATR":             {"op": "<", "params": {"period": 14},  "min": 0.01, "max": 0.15},
    "W_KBAR_amplitude":  {"op": "<", "params": None,            "min": 0.02, "max": 0.15},
    "PPOS_high_dist":    {"op": "<", "params": {"period": 20},  "min": -15,  "max": 0},
    "M_REALVOL":         {"op": "<", "params": {"period": 20},  "min": 5,    "max": 50},
    "KBAR_body_ratio":   {"op": "<", "params": None,            "min": 0.05, "max": 0.8},
    "PPOS_drawdown":     {"op": "<", "params": {"period": 20},  "min": -20,  "max": 0},
    "REALVOL_skew":      {"op": ">", "params": {"period": 20},  "min": -3,   "max": 3},
    "W_ADX":             {"op": ">", "params": {"period": 14},  "min": 10,   "max": 50},
    "W_PVOL_corr":       {"op": ">", "params": {"period": 20},  "min": -0.5, "max": 0.8},
    "KBAR_lower_shadow": {"op": ">", "params": None,            "min": 0.05, "max": 0.5},
}

# Fields that must NEVER appear
BANNED_FIELDS = frozenset({
    "PPOS_close_pos", "PPOS_consec_dir", "AMPVOL_parkinson",
    "W_STOCH", "PVOL_vwap_bias", "LIQ_amihud",
})

# Sell conditions can use the same fields (reversed direction) plus these:
SELL_ONLY_FIELDS = frozenset({"KDJ_K", "close"})


def validate_condition(cond: dict, context: str = "") -> list[str]:
    """Validate a single buy/sell condition dict. Returns list of issues."""
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
    """Validate a full experiment config from LLM output.

    Returns (is_valid, list_of_issues).
    """
    issues: list[str] = []

    # type
    exp_type = config.get("type", "")
    if exp_type not in ("fill", "new", "opt"):
        issues.append(f"bad type '{exp_type}'")

    # label
    if not config.get("label"):
        issues.append("missing label")

    # buy conditions
    buys = config.get("extra_buy_conditions", [])
    if not isinstance(buys, list):
        issues.append("extra_buy_conditions not a list")
    else:
        for i, c in enumerate(buys):
            issues.extend(validate_condition(c, f"buy[{i}]"))

    # sell conditions
    sells = config.get("extra_sell_conditions", [])
    if not isinstance(sells, list):
        issues.append("extra_sell_conditions not a list")
    else:
        for i, c in enumerate(sells):
            issues.extend(validate_condition(c, f"sell[{i}]"))

    # exit configs
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
            if sl is None:
                issues.append(f"exit[{i}]: missing stop_loss_pct")
            elif not isinstance(sl, (int, float)) or sl > 0:
                issues.append(f"exit[{i}]: stop_loss_pct must be negative, got {sl}")
            if tp is None:
                issues.append(f"exit[{i}]: missing take_profit_pct")
            elif not isinstance(tp, (int, float)) or tp <= 0:
                issues.append(f"exit[{i}]: take_profit_pct must be positive, got {tp}")
            if mhd is None:
                issues.append(f"exit[{i}]: missing max_hold_days")
            elif not isinstance(mhd, int) or mhd < 1:
                issues.append(f"exit[{i}]: max_hold_days must be positive int, got {mhd}")

    return len(issues) == 0, issues
```

- [ ] **Step 2: Verify file loads without errors**

Run:
```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import validate_experiment_config, VALID_BUY_FACTORS; print(f'Loaded: {len(VALID_BUY_FACTORS)} factors')"
```
Expected: `Loaded: 23 factors`

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add config validator and factor registry"
```

---

### Task 2: LLM Planner

The planner calls Qwen (primary) → DeepSeek (fallback) → rule-based (last resort) to generate experiment configs.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add LLM prompt constants**

Append to `api/services/exploration_engine.py`:

```python
# ── LLM Planner ──────────────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """你是A股量化策略研究员。根据策略池状态规划探索实验。

## 基础买入条件(固定,不需指定)
RSI(14) 48-66 + ATR(14) < 0.091

## 条件格式(buy和sell通用)
所有条件必须严格使用以下格式:
{"field":"字段名","operator":"<或>","compare_type":"value","compare_value":数值}
如果字段需要参数: {"field":"字段名","operator":"<","compare_type":"value","compare_value":数值,"params":{"period":20}}

⚠️ 严禁使用其他格式! 不允许: type, threshold, trailing_stop, factor_cross 等自定义字段。

## 可用Alpha因子
买入(operator和典型值):
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

卖出(使用同样因子的反向条件):
- KBAR_amplitude > 0.05-0.08 → 振幅过大卖出
- REALVOL > 30-45 (params period=20) → 波动率升高卖出
- MOM < -1到-2 (params period=20) → 动量转负卖出
- RSTR_weighted < -0.5到-1 (params period=20) → 动量反转卖出
- AMPVOL_std > 0.025-0.04 (params period=5) → 振幅波动扩大卖出

## 正确的sell条件示例:
[
  {"field":"MOM","operator":"<","compare_type":"value","compare_value":-1.0,"params":{"period":20}},
  {"field":"KBAR_amplitude","operator":">","compare_type":"value","compare_value":0.06}
]

## 已弃(禁用): PPOS_close_pos, PPOS_consec_dir, AMPVOL_parkinson, W_STOCH, PVOL_vwap_bias, LIQ_amihud

## Exit Config格式
{"name":"SL20_TP2_MHD5","stop_loss_pct":-20,"take_profit_pct":2.0,"max_hold_days":5}"""


def _build_user_prompt(pool_families: list[dict], n_experiments: int) -> str:
    """Build user prompt from pool state."""
    # Sort by gap descending, take top 15
    top = sorted(pool_families, key=lambda f: -f.get("gap", 0))[:15]
    lines = [f"  {f['family']}(gap={f['gap']}, avg={f['avg_score']:.4f})" for f in top]
    pool_text = "\n".join(lines)

    n_fill = max(1, n_experiments * 3 // 10)
    n_new = max(1, n_experiments * 6 // 10)
    n_opt = max(1, n_experiments - n_fill - n_new)

    return f"""池状态: {len(pool_families)}家族, 总gap={sum(f.get('gap',0) for f in pool_families)}
Top gaps:
{pool_text}

请输出{n_experiments}个实验配置({n_fill}个fill + {n_new}个新骨架 + {n_opt}个优化), JSON数组:
[
  {{
    "type": "fill或new或opt",
    "label": "英文标签",
    "extra_buy_conditions": [{{"field":"W_ATR","operator":"<","compare_type":"value","compare_value":0.06,"params":{{"period":14}}}}],
    "extra_sell_conditions": [],
    "exit_configs": [{{"name":"SL20_TP2_MHD5","stop_loss_pct":-20,"take_profit_pct":2.0,"max_hold_days":5}}]
  }}
]

要求:
1. 每个实验至少5个exit_configs
2. 新骨架用2-3个因子组合
3. fill针对top-gap家族
4. opt的extra_sell_conditions非空,使用标准条件格式
5. 只输出JSON,不要解释"""
```

- [ ] **Step 2: Add LLMPlanner class**

Append to the same file:

```python
from openai import OpenAI


class LLMPlanner:
    """Call Qwen (primary) → DeepSeek (fallback) → rules to plan experiments."""

    def __init__(self):
        from api.config import get_settings
        settings = get_settings()
        ds_key = settings.deepseek.api_key

        self._providers = [
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

    def plan(
        self, pool_families: list[dict], n_experiments: int
    ) -> tuple[list[dict], str]:
        """Generate experiment configs. Returns (configs, provider_name)."""
        user_prompt = _build_user_prompt(pool_families, n_experiments)

        for prov in self._providers:
            try:
                logger.info("LLMPlanner: trying %s ...", prov["name"])
                configs = self._call_llm(prov, user_prompt)
                valid = [c for c in configs if validate_experiment_config(c)[0]]
                logger.info(
                    "LLMPlanner: %s returned %d configs, %d valid",
                    prov["name"], len(configs), len(valid),
                )
                if len(valid) >= n_experiments * 0.5:
                    return valid, prov["name"]
                logger.warning(
                    "LLMPlanner: %s only %d/%d valid, trying next",
                    prov["name"], len(valid), n_experiments,
                )
            except Exception:
                logger.exception("LLMPlanner: %s failed", prov["name"])

        # Rule-based fallback
        logger.info("LLMPlanner: all LLMs failed, using rule-based fallback")
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
        """Extract JSON array from LLM output (handles think tags, markdown)."""
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
        configs: list[dict] = []
        exit_grid = [
            {"name": "SL20_TP0.5_MHD2", "stop_loss_pct": -20, "take_profit_pct": 0.5, "max_hold_days": 2},
            {"name": "SL20_TP1_MHD3",   "stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 3},
            {"name": "SL15_TP1.5_MHD3", "stop_loss_pct": -15, "take_profit_pct": 1.5, "max_hold_days": 3},
            {"name": "SL20_TP2_MHD5",   "stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 5},
            {"name": "SL25_TP3_MHD5",   "stop_loss_pct": -25, "take_profit_pct": 3.0, "max_hold_days": 5},
            {"name": "SL20_TP4_MHD7",   "stop_loss_pct": -20, "take_profit_pct": 4.0, "max_hold_days": 7},
        ]

        # Fill: top-gap families with threshold variations
        thresholds = {"W_ATR": [0.05, 0.07], "W_REALVOL": [20, 25, 30],
                      "AMPVOL_std": [0.015, 0.02], "REALVOL": [22, 28]}
        sorted_fams = sorted(pool_families, key=lambda f: -f.get("gap", 0))

        for fam in sorted_fams[:n // 3]:
            # Pick a factor that matches the family name
            for factor, vals in thresholds.items():
                if factor.replace("_", "").upper() in fam["family"].replace("_", "").upper():
                    for v in vals[:1]:
                        meta = VALID_BUY_FACTORS.get(factor, {})
                        cond = {"field": factor, "operator": meta.get("op", "<"),
                                "compare_type": "value", "compare_value": v}
                        if meta.get("params"):
                            cond["params"] = meta["params"]
                        configs.append({
                            "type": "fill", "label": f"fill_{factor}_{v}",
                            "extra_buy_conditions": [cond],
                            "extra_sell_conditions": [],
                            "exit_configs": exit_grid,
                        })
                    break
            if len(configs) >= n // 3:
                break

        # New: simple 2-factor combos from registry
        factor_list = list(VALID_BUY_FACTORS.keys())
        import itertools
        for a, b in itertools.combinations(factor_list[:10], 2):
            if len(configs) >= n * 9 // 10:
                break
            ma, mb = VALID_BUY_FACTORS[a], VALID_BUY_FACTORS[b]
            ca = {"field": a, "operator": ma["op"], "compare_type": "value",
                  "compare_value": (ma["min"] + ma["max"]) / 2}
            cb = {"field": b, "operator": mb["op"], "compare_type": "value",
                  "compare_value": (mb["min"] + mb["max"]) / 2}
            if ma.get("params"):
                ca["params"] = ma["params"]
            if mb.get("params"):
                cb["params"] = mb["params"]
            configs.append({
                "type": "new", "label": f"new_{a}_{b}",
                "extra_buy_conditions": [ca, cb],
                "extra_sell_conditions": [],
                "exit_configs": exit_grid,
            })

        return configs[:n]
```

- [ ] **Step 3: Verify LLMPlanner loads**

Run:
```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import LLMPlanner; p = LLMPlanner(); print(f'Providers: {[p[\"name\"] for p in p._providers]}')"
```
Expected: `Providers: ['qwen', 'deepseek']`

- [ ] **Step 4: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add LLM planner with Qwen/DeepSeek/rules fallback"
```

---

### Task 3: Exploration Engine Core

The main engine class that orchestrates the workflow loop in a background thread.

**Files:**
- Modify: `api/services/exploration_engine.py`

- [ ] **Step 1: Add engine class with internal API helpers**

Append to `api/services/exploration_engine.py`:

```python
import threading
import time as _time
from datetime import datetime


def _internal_api(method: str, path: str, data: dict | None = None) -> dict:
    """Call our own FastAPI endpoints via HTTP (localhost:8050).

    This avoids importing and calling service functions directly,
    keeping the engine decoupled from internal implementations.
    """
    import subprocess
    cmd = ["curl", "-s"]
    if method.upper() != "GET":
        cmd.extend(["-X", method.upper()])
    url = f"http://127.0.0.1:8050/api/{path}"
    if data is not None:
        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(data)])
    cmd.append(url)
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        env={"NO_PROXY": "localhost,127.0.0.1", "PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, Exception):
        logger.error("_internal_api %s %s failed: %s", method, path, r.stdout[:200])
        return {}


class ExplorationEngine:
    """Singleton engine running exploration loop in a background thread."""

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
        self.state = "IDLE"
        self.current_round = 0
        self.current_step = ""
        self.step_detail = ""
        self.rounds_total = 0
        self.rounds_completed = 0
        self.strategies_total = 0
        self.strategies_done = 0
        self.strategies_invalid = 0
        self.strategies_pending = 0
        self.stda_count = 0
        self.best_score = 0.0
        self.pool_families = 0
        self.pool_active = 0
        self.pool_gap = 0
        self.started_at: Optional[str] = None
        self.llm_provider = ""
        self.last_error: Optional[str] = None
        self.experiment_ids: list[int] = []
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

        # Determine next round number
        rounds_data = _internal_api("GET", "lab/exploration-rounds")
        items = rounds_data.get("items", rounds_data) if isinstance(rounds_data, dict) else rounds_data
        if items and isinstance(items, list):
            self.current_round = max(r.get("round_number", 0) for r in items) + 1
        else:
            self.current_round = 1

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(rounds, experiments_per_round),
            daemon=True,
            name="exploration-engine",
        )
        self._thread.start()
        self.state = "RUNNING"
        logger.info("Exploration started: %d rounds × %d experiments, round=%d",
                     rounds, experiments_per_round, self.current_round)
        return {"message": "Exploration started", "round_number": self.current_round}

    def stop(self) -> dict:
        if self.state != "RUNNING":
            return {"error": f"Not running (state={self.state})"}
        self._stop_event.set()
        self.state = "STOPPING"
        logger.info("Exploration stop requested")
        return {"message": "Stop requested, will finish current round"}

    def get_status(self) -> dict:
        elapsed = 0.0
        if self.started_at:
            try:
                start_dt = datetime.fromisoformat(self.started_at)
                elapsed = (datetime.now() - start_dt).total_seconds()
            except ValueError:
                pass
        # Estimate remaining
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
            "pool": {
                "families": self.pool_families,
                "active": self.pool_active,
                "gap": self.pool_gap,
            },
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

                logger.info("=== Round %d (R%d) starting ===", i + 1, self.current_round)

                # Step 1: Load state
                self._set_step("loading_state", "查询池状态")
                pool_families = self._step_load_state()

                if self._stop_event.is_set():
                    break

                # Step 2: Plan
                self._set_step("planning", "LLM规划实验方向")
                configs, provider = self._step_plan(pool_families, exp_per_round)
                self.llm_provider = provider

                if self._stop_event.is_set():
                    break

                # Step 3: Submit
                self._set_step("submitting", f"提交{len(configs)}个实验")
                exp_ids = self._step_submit(configs)
                self.experiment_ids = exp_ids

                # Step 4: Poll
                self._set_step("polling", "等待回测完成")
                self._step_poll(exp_ids)

                # Step 5: Promote
                self._set_step("promoting", "Promote StdA+策略")
                promoted = self._step_promote(exp_ids)

                # Step 6: Record
                self._set_step("updating", "保存轮次记录")
                self._step_record(exp_ids, promoted)

                self.rounds_completed += 1
                self.current_round += 1
                logger.info(
                    "=== Round complete: %d StdA+ promoted, best=%.4f ===",
                    promoted, self.best_score,
                )

        except Exception as e:
            logger.exception("Exploration engine error")
            self.last_error = str(e)
            self.state = "ERROR"
            return

        self.state = "IDLE"
        self.current_step = ""
        self.step_detail = ""
        logger.info("Exploration finished: %d rounds completed", self.rounds_completed)

    def _set_step(self, step: str, detail: str):
        self.current_step = step
        self.step_detail = detail
        logger.info("Step: %s — %s", step, detail)

    # ── Step Implementations ─────────────────────────────────────

    def _step_load_state(self) -> list[dict]:
        """Query pool status and retry-pending."""
        # Retry pending experiments (unstick queue)
        _internal_api("POST", "lab/experiments/retry-pending")

        # Get pool status
        status = _internal_api("GET", "strategies/pool/status")
        families = status.get("family_summary", [])
        self.pool_families = len(families)
        self.pool_active = sum(f.get("active_count", 0) for f in families)
        self.pool_gap = sum(f.get("gap", 0) for f in families)
        return families

    def _step_plan(self, pool_families: list[dict], n: int) -> tuple[list[dict], str]:
        """Call LLM planner to generate experiment configs."""
        configs, provider = self._planner.plan(pool_families, n)
        self.step_detail = f"{provider}生成{len(configs)}个有效配置"
        return configs, provider

    def _step_submit(self, configs: list[dict]) -> list[int]:
        """Submit experiments via batch-clone-backtest API."""
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

        exp_ids: list[int] = []
        total_strats = 0
        sid = self._source_strategy_id

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

            result = _internal_api("POST", f"lab/strategies/{sid}/batch-clone-backtest", {
                "source_strategy_id": sid,
                "exit_configs": exit_configs,
            })
            eid = result.get("experiment_id")
            if eid:
                exp_ids.append(eid)
                total_strats += result.get("count", 0)

        self.strategies_total = total_strats
        self.strategies_done = 0
        self.strategies_invalid = 0
        self.strategies_pending = total_strats
        self.stda_count = 0
        self.best_score = 0.0

        # Retry-pending to ensure queue processes
        _internal_api("POST", "lab/experiments/retry-pending")

        self.step_detail = f"已提交{len(exp_ids)}个实验, {total_strats}个策略"
        logger.info("Submitted %d experiments, %d strategies", len(exp_ids), total_strats)
        return exp_ids

    def _step_poll(self, exp_ids: list[int]):
        """Poll until all strategies are done. Updates stats in real-time."""
        max_polls = 600  # 600 × 2min = 20 hours max
        for poll in range(max_polls):
            if self._stop_event.is_set():
                break

            done = inv = pend = bt = stda = 0
            best = 0.0

            for eid in exp_ids:
                exp = _internal_api("GET", f"lab/experiments/{eid}")
                for s in exp.get("strategies", []):
                    st = s.get("status", "")
                    if st == "done":
                        done += 1
                        sc = s.get("score", 0) or 0
                        ret = s.get("total_return_pct", 0) or 0
                        dd = abs(s.get("max_drawdown_pct", 100) or 100)
                        tr = s.get("total_trades", 0) or 0
                        wr = s.get("win_rate", 0) or 0
                        if sc > best:
                            best = sc
                        if sc >= 0.80 and ret > 60 and dd < 18 and tr >= 50 and wr > 60:
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
            total = done + inv + pend
            self.strategies_total = total

            pct = done / max(1, total) * 100
            self.step_detail = f"回测进度: {done}/{total} ({pct:.0f}%), {stda} StdA+, best={best:.4f}"

            if pend == 0:
                logger.info("All strategies complete: %d done, %d invalid, %d StdA+",
                           done, inv, stda)
                break

            _time.sleep(120)  # 2 minutes

    def _step_promote(self, exp_ids: list[int]) -> int:
        """Promote qualifying strategies and rebalance pool."""
        import urllib.parse
        promoted = 0
        label = urllib.parse.quote("[AI]")
        cat = urllib.parse.quote("全能")

        for eid in exp_ids:
            exp = _internal_api("GET", f"lab/experiments/{eid}")
            for s in exp.get("strategies", []):
                if s.get("status") != "done" or s.get("promoted"):
                    continue
                sc = s.get("score", 0) or 0
                ret = s.get("total_return_pct", 0) or 0
                dd = abs(s.get("max_drawdown_pct", 100) or 100)
                tr = s.get("total_trades", 0) or 0
                wr = s.get("win_rate", 0) or 0
                if sc >= 0.80 and ret > 60 and dd < 18 and tr >= 50 and wr > 60:
                    result = _internal_api(
                        "POST",
                        f"lab/strategies/{s['id']}/promote?label={label}&category={cat}",
                    )
                    if result.get("message") != "Already promoted":
                        promoted += 1

        # Rebalance
        _internal_api("POST", "strategies/pool/rebalance?max_per_family=15")

        self.step_detail = f"Promoted {promoted}, rebalanced"
        logger.info("Promoted %d strategies, rebalanced pool", promoted)
        return promoted

    def _step_record(self, exp_ids: list[int], promoted: int):
        """Save exploration round to API."""
        _internal_api("POST", "lab/exploration-rounds", {
            "round_number": self.current_round,
            "mode": "auto",
            "started_at": self.started_at or datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
            "experiment_ids": exp_ids,
            "total_experiments": len(exp_ids),
            "total_strategies": self.strategies_done + self.strategies_invalid,
            "profitable_count": self.stda_count,
            "profitability_pct": self.stda_count / max(1, self.strategies_done) * 100,
            "std_a_count": self.stda_count,
            "best_strategy_name": "",
            "best_strategy_score": self.best_score,
            "best_strategy_return": 0,
            "best_strategy_dd": 0,
            "insights": [f"R{self.current_round}: {self.stda_count} StdA+, best={self.best_score:.4f}, provider={self.llm_provider}"],
            "promoted": [],
            "issues_resolved": [],
            "next_suggestions": ["Continue fills"],
            "summary": f"R{self.current_round}: {self.strategies_done} done, {self.stda_count} StdA+, promoted={promoted}",
            "memory_synced": False,
            "pinecone_synced": False,
        })

        # Update pool stats
        status = _internal_api("GET", "strategies/pool/status")
        families = status.get("family_summary", [])
        self.pool_families = len(families)
        self.pool_active = sum(f.get("active_count", 0) for f in families)
        self.pool_gap = sum(f.get("gap", 0) for f in families)
```

- [ ] **Step 2: Verify engine loads and instantiates**

Run:
```bash
cd /Users/allenqiang/stockagent && python3 -c "from api.services.exploration_engine import ExplorationEngine; e = ExplorationEngine(); print(e.get_status()['state'])"
```
Expected: `IDLE`

- [ ] **Step 3: Commit**

```bash
git add api/services/exploration_engine.py
git commit -m "feat(exploration): add ExplorationEngine with full workflow loop"
```

---

### Task 4: REST API Router

4 endpoints: start, stop, status, history.

**Files:**
- Create: `api/routers/exploration_workflow.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create router file**

```python
"""Exploration Workflow REST API.

Control the automated strategy exploration engine.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.services.exploration_engine import ExplorationEngine

router = APIRouter(prefix="/api/exploration-workflow", tags=["exploration-workflow"])

# Singleton engine instance
_engine = ExplorationEngine()


@router.post("/start")
def start_exploration(
    rounds: int = Query(1, ge=1, le=100, description="Number of exploration rounds"),
    experiments_per_round: int = Query(50, ge=5, le=200, description="Experiments per round"),
    source_strategy_id: int = Query(116987, description="Source experiment strategy ID to clone from"),
):
    """Start the exploration workflow in background."""
    return _engine.start(rounds, experiments_per_round, source_strategy_id)


@router.post("/stop")
def stop_exploration():
    """Request graceful stop after current round completes."""
    return _engine.stop()


@router.get("/status")
def get_status():
    """Get real-time workflow status."""
    return _engine.get_status()


@router.get("/history")
def get_history(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
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
            "memory_synced": r.memory_synced,
        }
        for r in rounds
    ]
```

- [ ] **Step 2: Register router in main.py**

Add to `api/main.py` after the existing imports (around line 18):

```python
from api.routers import market, stocks, strategies, signals, backtest, news, config, ai_lab, ai_analyst, news_signals, bot_trading, beta, auth, jobs, ops, artifacts, memory, tdx, exploration_workflow
```

And add after line 538 (after `app.include_router(tdx.router)`):

```python
app.include_router(exploration_workflow.router)
```

- [ ] **Step 3: Verify endpoints load**

Run:
```bash
cd /Users/allenqiang/stockagent && python3 -c "
from api.routers.exploration_workflow import router
print(f'Routes: {len(router.routes)}')
for r in router.routes:
    print(f'  {r.methods} {r.path}')
"
```
Expected:
```
Routes: 4
  {'POST'} /start
  {'POST'} /stop
  {'GET'} /status
  {'GET'} /history
```

- [ ] **Step 4: Commit**

```bash
git add api/routers/exploration_workflow.py api/main.py
git commit -m "feat(exploration): add REST API router with start/stop/status/history"
```

---

### Task 5: Integration Test

Test the full workflow with a minimal 2-experiment run.

**Files:**
- No new files (manual testing against running server)

- [ ] **Step 1: Test status endpoint (server must be running)**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | python3 -m json.tool
```
Expected: `{"state": "IDLE", ...}`

- [ ] **Step 2: Test start with 1 round, 2 experiments**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/exploration-workflow/start?rounds=1&experiments_per_round=2" | python3 -m json.tool
```
Expected: `{"message": "Exploration started", "round_number": ...}`

- [ ] **Step 3: Poll status until complete**

```bash
# Check every 30s
for i in $(seq 1 20); do
  sleep 30
  NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"state\"]} | {d[\"current_step\"]} | done={d[\"strategies\"][\"done\"]}/{d[\"strategies\"][\"total\"]} StdA+={d[\"strategies\"][\"stda_count\"]}')"
  # Break if IDLE
done
```
Expected: Transitions through `RUNNING|loading_state → planning → submitting → polling → promoting → updating → IDLE`

- [ ] **Step 4: Verify history shows the round**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/exploration-workflow/history?limit=1" | python3 -m json.tool
```
Expected: Latest round with `std_a_count >= 0`

- [ ] **Step 5: Commit (if any fixes were needed)**

```bash
git add -A && git commit -m "fix(exploration): integration test fixes"
```

---

### Task 6: Test Stop Behavior

- [ ] **Step 1: Start a 3-round exploration**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/exploration-workflow/start?rounds=3&experiments_per_round=2"
```

- [ ] **Step 2: Wait for polling phase, then stop**

```bash
sleep 60
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/exploration-workflow/stop
```
Expected: `{"message": "Stop requested, will finish current round"}`

- [ ] **Step 3: Verify state transitions to STOPPING then IDLE**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/exploration-workflow/status | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"state\"]} rounds_completed={d[\"rounds_config\"][\"completed\"]}')"
```
Expected: `STOPPING` initially, then `IDLE` after current round finishes. `rounds_completed` should be 1 (not 3).
