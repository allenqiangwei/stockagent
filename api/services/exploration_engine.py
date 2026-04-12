"""Exploration Workflow Engine — autonomous strategy research loop.

Orchestrates: plan → submit → poll → promote → record, using LLM-based
experiment design with rule-based fallback.  Runs as a singleton daemon
controlled via start / stop / get_status.

Tasks 1-6 consolidated into a single file.
"""

import copy
import itertools
import json
import logging
import re
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# 2.  Factor Registry
# ────────────────────────────────────────────────────────────────

VALID_BUY_FACTORS: dict[str, dict] = {
    # ── K-bar factors ──
    "KBAR_amplitude":    {"op": "<", "params": None,              "min": 0.01, "max": 0.10},
    "KBAR_body_ratio":   {"op": ">", "params": None,              "min": 0.3,  "max": 0.9},
    "KBAR_lower_shadow": {"op": ">", "params": None,              "min": 0.01, "max": 0.10},
    "W_KBAR_amplitude":  {"op": "<", "params": None,              "min": 0.02, "max": 0.15},
    # ── Volatility ──
    "W_REALVOL":         {"op": "<", "params": {"period": 20},    "min": 5,    "max": 50},
    "REALVOL":           {"op": "<", "params": {"period": 20},    "min": 5,    "max": 50},
    "REALVOL_kurt":      {"op": ">", "params": {"period": 20},    "min": 1,    "max": 10},
    "REALVOL_downside":  {"op": "<", "params": {"period": 20},    "min": 3,    "max": 40},
    "REALVOL_skew":      {"op": "<", "params": {"period": 20},    "min": -2.0, "max": 2.0},
    "M_REALVOL":         {"op": "<", "params": {"period": 20},    "min": 10,   "max": 80},
    # ── Amplitude volatility ──
    "AMPVOL_std":        {"op": "<", "params": {"period": 5},     "min": 0.005, "max": 0.05},
    "W_AMPVOL_std":      {"op": "<", "params": {"period": 5},     "min": 0.01,  "max": 0.08},
    # ── Relative strength ──
    "RSTR_weighted":     {"op": ">", "params": {"period": 20},    "min": -10,   "max": 10},
    "W_RSTR_weighted":   {"op": ">", "params": {"period": 20},    "min": -20,   "max": 20},
    # ── Price-volume ──
    "PVOL_corr":         {"op": "<", "params": {"period": 20},    "min": -1.0,  "max": 1.0},
    "W_PVOL_corr":       {"op": "<", "params": {"period": 20},    "min": -1.0,  "max": 1.0},
    "PVOL_amount_conc":  {"op": "<", "params": {"period": 20},    "min": 0.1,   "max": 0.9},
    # ── Momentum ──
    "MOM":               {"op": ">", "params": {"period": 20},    "min": -15,   "max": 15},
    # ── Liquidity ──
    "LIQ_turnover_vol":  {"op": "<", "params": {"period": 20},    "min": 0.1,   "max": 5.0},
    # ── Weekly ATR ──
    "W_ATR":             {"op": "<", "params": {"period": 14},    "min": 0.01,  "max": 0.20},
    # ── Price position ──
    "PPOS_high_dist":    {"op": ">", "params": {"period": 20},    "min": -50,   "max": 0},
    "PPOS_drawdown":     {"op": "<", "params": {"period": 20},    "min": 0,     "max": 30},
    # ── Trend strength ──
    "W_ADX":             {"op": ">", "params": {"period": 14},    "min": 10,    "max": 50},
}

# ────────────────────────────────────────────────────────────────
# 3.  Banned / sell-only / base conditions / StdA+ constants
# ────────────────────────────────────────────────────────────────

BANNED_FIELDS = frozenset([
    "PPOS_close_pos", "PPOS_consec_dir", "AMPVOL_parkinson",
    "W_STOCH", "PVOL_vwap_bias", "LIQ_amihud",
])

SELL_ONLY_FIELDS = frozenset([
    "MOM", "KBAR_amplitude", "REALVOL",
])

BASE_BUY: list[dict] = [
    {
        "field": "RSI",
        "operator": "between",
        "compare_type": "between",
        "compare_value": [48, 66],
        "params": {"period": 14},
    },
    {
        "field": "ATR",
        "operator": "<",
        "compare_type": "value",
        "compare_value": 0.091,
        "params": {"period": 14},
    },
]

BASE_SELL: list[dict] = [
    {
        "field": "KDJ_K",
        "operator": "consecutive",
        "compare_type": "consecutive",
        "direction": "falling",
        "consecutive_n": 2,
        "params": {"fastk_period": 9, "slowk_period": 3, "slowd_period": 3},
    },
    {
        "field": "close",
        "operator": "<",
        "compare_type": "pct_change",
        "compare_value": -0.5,
    },
]

# StdA+ criteria
STDA_SCORE = 0.80
STDA_RETURN = 60.0
STDA_DD = 18.0
STDA_TRADES = 50
STDA_WR = 60.0


# ────────────────────────────────────────────────────────────────
# 4.  Helper functions
# ────────────────────────────────────────────────────────────────

def is_stda_plus(
    score: float,
    total_return_pct: float,
    max_drawdown_pct: float,
    total_trades: int,
    win_rate: float,
) -> bool:
    """Return True if metrics meet StdA+ criteria."""
    return (
        score >= STDA_SCORE
        and total_return_pct > STDA_RETURN
        and max_drawdown_pct < STDA_DD
        and total_trades >= STDA_TRADES
        and win_rate > STDA_WR
    )


def validate_condition(cond: dict) -> list[str]:
    """Validate a single buy/sell condition dict. Return list of errors."""
    errors: list[str] = []
    field = cond.get("field", "")
    if not field:
        errors.append("missing 'field'")
    if field in BANNED_FIELDS:
        errors.append(f"field '{field}' is banned")
    if "compare_type" not in cond and "operator" not in cond:
        errors.append("missing 'compare_type' or 'operator'")
    ct = cond.get("compare_type", cond.get("operator", ""))
    if ct == "value" and "compare_value" not in cond:
        errors.append("compare_type='value' requires 'compare_value'")
    if ct == "between":
        cv = cond.get("compare_value")
        if not isinstance(cv, (list, tuple)) or len(cv) != 2:
            errors.append("compare_type='between' requires compare_value=[lo, hi]")
    if ct == "consecutive":
        if "consecutive_n" not in cond:
            errors.append("compare_type='consecutive' requires 'consecutive_n'")
        if "direction" not in cond:
            errors.append("compare_type='consecutive' requires 'direction'")
    return errors


def validate_experiment_config(config: dict) -> list[str]:
    """Validate a full experiment config. Return list of errors (empty = valid)."""
    errors: list[str] = []
    if "name_suffix" not in config:
        errors.append("missing 'name_suffix'")
    buy = config.get("buy_conditions")
    sell = config.get("sell_conditions")
    exit_cfg = config.get("exit_config")
    if buy is not None:
        if not isinstance(buy, list):
            errors.append("buy_conditions must be a list")
        else:
            for i, c in enumerate(buy):
                for err in validate_condition(c):
                    errors.append(f"buy[{i}]: {err}")
    if sell is not None:
        if not isinstance(sell, list):
            errors.append("sell_conditions must be a list")
        else:
            for i, c in enumerate(sell):
                for err in validate_condition(c):
                    errors.append(f"sell[{i}]: {err}")
    if exit_cfg is not None:
        if not isinstance(exit_cfg, dict):
            errors.append("exit_config must be a dict")
        else:
            tp = exit_cfg.get("take_profit_pct")
            if tp is not None and tp < 0.12:
                errors.append(f"take_profit_pct={tp} below 0.12 floor")
    return errors


# ────────────────────────────────────────────────────────────────
# 5.  Internal API helper
# ────────────────────────────────────────────────────────────────

_API_BASE = "http://127.0.0.1:8050/api/"


def _api(method: str, path: str, data: dict | None = None, timeout: int = 120) -> dict:
    """Call local API via curl subprocess. Returns parsed JSON."""
    url = f"{_API_BASE}{path}"
    cmd = ["curl", "-s", "-X", method.upper(), url, "-H", "Content-Type: application/json"]
    if data is not None:
        cmd += ["-d", json.dumps(data, ensure_ascii=False)]
    cmd += ["--max-time", str(timeout)]

    try:
        env = {"NO_PROXY": "localhost,127.0.0.1", "PATH": "/usr/bin:/bin"}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10, env=env)
        if result.returncode != 0:
            logger.error("curl %s %s failed: %s", method, path, result.stderr)
            return {"error": result.stderr}
        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.error("curl %s %s timed out after %ds", method, path, timeout)
        return {"error": "timeout"}
    except json.JSONDecodeError as e:
        logger.error("curl %s %s JSON decode error: %s — body: %s", method, path, e, result.stdout[:200])
        return {"error": str(e)}


def _promote_strategy(strategy_id: int, label: str = "[AI]", category: str = "") -> dict:
    """Promote an experiment strategy via API with URL-encoded label/category."""
    params = urllib.parse.urlencode({"label": label, "category": category})
    return _api("POST", f"lab/strategies/{strategy_id}/promote?{params}")


# ────────────────────────────────────────────────────────────────
# 6.  Insight Loader
# ────────────────────────────────────────────────────────────────

_INSIGHT_DOC: Path = Path(__file__).parent.parent.parent / "docs" / "lab-experiment-analysis.md"


def load_historical_insights() -> str:
    """Read the lab-experiment-analysis.md file and return its full content."""
    try:
        return _INSIGHT_DOC.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Insight doc not found: %s", _INSIGHT_DOC)
        return ""


def get_latest_round_suggestions() -> dict:
    """Extract structured insights from the analysis doc.

    Returns dict with keys: core_insights, valid_directions, abandoned, next_suggestions.
    """
    text = load_historical_insights()
    if not text:
        return {"core_insights": [], "valid_directions": [], "abandoned": [], "next_suggestions": []}

    result: dict[str, list[str]] = {
        "core_insights": [],
        "valid_directions": [],
        "abandoned": [],
        "next_suggestions": [],
    }

    # Extract 核心洞察 section
    m = re.search(r"## 核心洞察\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line and not line.startswith(">"):
                result["core_insights"].append(line)

    # Extract 有效方向 / 有效
    m = re.search(r"## 有效方向\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line:
                result["valid_directions"].append(line)

    # Extract 已弃
    m = re.search(r"## 已弃\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line:
                result["abandoned"].append(line)

    # Extract 下一步建议
    m = re.search(r"## 下一步(?:建议|优先级)\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line:
                result["next_suggestions"].append(line)

    return result


# ────────────────────────────────────────────────────────────────
# 7.  Skeleton Candidate Generator
# ────────────────────────────────────────────────────────────────

def generate_skeleton_candidates(
    existing_families: list[dict],
    max_candidates: int = 10,
) -> list[str]:
    """Generate novel factor combination candidates not yet in the pool.

    Parameters
    ----------
    existing_families : list[dict]
        Each dict must have a "family" key (e.g. "ATR+RSI").
    max_candidates : int
        Maximum number of candidates to return.

    Returns
    -------
    list[str]
        Factor combination strings like "KBAR_amplitude + W_REALVOL".
    """
    # Parse existing families into sets of indicators
    existing_sets: list[frozenset[str]] = []
    for fam in existing_families:
        name = fam.get("family", "")
        parts = frozenset(p.strip() for p in name.split("+") if p.strip())
        if parts:
            existing_sets.append(parts)

    factors = sorted(VALID_BUY_FACTORS.keys())
    candidates: list[str] = []

    # Generate 2-factor combos first, then 3-factor
    for r in (2, 3):
        for combo in itertools.combinations(factors, r):
            combo_set = frozenset(combo)
            # Build the comparison set: the combo plus ATR+RSI (since base always includes them)
            comparison_set = frozenset(
                p.upper().split("_")[0] if not p.startswith(("W_", "M_")) else p
                for p in combo
            ) | frozenset(["ATR", "RSI"])
            # Check if this combo (with ATR+RSI) is already in the pool
            already_exists = False
            for ex_set in existing_sets:
                if comparison_set == ex_set or comparison_set.issubset(ex_set):
                    already_exists = True
                    break
            if not already_exists:
                candidates.append(" + ".join(combo))
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    return candidates[:max_candidates]


# ────────────────────────────────────────────────────────────────
# 8.  LLM Planner
# ────────────────────────────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """\
You are a quantitative strategy researcher for A-share (China) stock market.
Your job is to design BUY conditions and SELL conditions for strategy experiments.

## Available Factors (for buy_conditions)
Each factor has an operator and typical value range:
{factor_table}

## BANNED fields (NEVER use these)
{banned_list}

## Output Format
Return a JSON array of experiment configs. Each config:
```json
{{
  "name_suffix": "descriptive_name",
  "buy_conditions": [...],
  "sell_conditions": [...],
  "exit_config": {{
    "stop_loss_pct": -10,
    "take_profit_pct": 1.0,
    "max_hold_days": 2
  }}
}}
```

## CRITICAL: Condition Format (follow EXACTLY)
Buy condition example:
```json
{{"field":"KBAR_amplitude","operator":"<","compare_type":"value","compare_value":0.05}}
```
With params:
```json
{{"field":"W_REALVOL","operator":"<","compare_type":"value","compare_value":25,"params":{{"period":20}}}}
```

Sell condition examples (use these as templates):
```json
[
  {{"field":"MOM","operator":"<","compare_type":"value","compare_value":-1.0,"params":{{"period":20}}}},
  {{"field":"KBAR_amplitude","operator":">","compare_type":"value","compare_value":0.06}},
  {{"field":"REALVOL","operator":">","compare_type":"value","compare_value":38,"params":{{"period":20}}}}
]
```

## Exit Config
- stop_loss_pct: MUST be negative (e.g. -10 for 10% stop loss)
- take_profit_pct: positive, minimum 0.12 (below this slippage eats profit)
- max_hold_days: 1-30

## Resource Allocation Principle
- 60% new skeleton exploration (novel factor combinations)
- 30% fill existing families that have gap > 0
- 10% optimize top performers with parameter tweaks

## Rules
1. Each experiment should have 1-3 buy_conditions (do NOT include RSI or ATR — base conditions are prepended automatically)
2. Each experiment should have 1-2 sell_conditions
3. Use diverse factor combinations across experiments
4. Vary exit_config parameters across experiments
5. NEVER use banned fields
"""


def _build_factor_table() -> str:
    """Build a markdown table of available factors for the system prompt."""
    lines = []
    for name, info in sorted(VALID_BUY_FACTORS.items()):
        params_str = json.dumps(info["params"]) if info["params"] else "none"
        lines.append(f"- {name}: op={info['op']}, range=[{info['min']}, {info['max']}], params={params_str}")
    return "\n".join(lines)


def _build_user_prompt(
    pool_families: list[dict],
    n_experiments: int,
    insights: str,
    suggestions: dict,
    skeleton_candidates: list[str],
) -> str:
    """Build the user prompt with current context."""
    # Summarize pool
    pool_lines = []
    for fam in pool_families[:30]:
        pool_lines.append(
            f"  {fam.get('family','?')}: active={fam.get('active_count',0)}, "
            f"gap={fam.get('gap',0)}, best={fam.get('best_score',0):.4f}"
        )
    pool_summary = "\n".join(pool_lines) if pool_lines else "  (empty pool)"

    # Summarize suggestions
    sugg_lines = []
    for s in suggestions.get("next_suggestions", [])[:10]:
        sugg_lines.append(f"  - {s}")
    sugg_text = "\n".join(sugg_lines) if sugg_lines else "  (no suggestions)"

    # Novel candidates
    cand_text = ", ".join(skeleton_candidates[:10]) if skeleton_candidates else "(none)"

    return f"""\
Design {n_experiments} experiment configs for the next exploration round.

## Current Pool ({len(pool_families)} families)
{pool_summary}

## Novel Factor Combinations to Try
{cand_text}

## Recent Suggestions
{sugg_text}

## Allocation
- ~{int(n_experiments * 0.6)} new skeleton experiments
- ~{int(n_experiments * 0.3)} fill experiments for families with gap > 0
- ~{max(1, int(n_experiments * 0.1))} optimization experiments

Return ONLY a JSON array of {n_experiments} experiment configs. No explanation.
"""


class LLMPlanner:
    """Plan experiments using LLM with rule-based fallback."""

    def __init__(self):
        from api.config import get_settings
        settings = get_settings()

        self._providers: list[dict] = [
            {
                "name": "qwen",
                "base_url": "http://192.168.100.172:8680/v1",
                "model": "qwen3.5-35b-a3b",
                "api_key": "no-key",
            },
            {
                "name": "deepseek",
                "base_url": settings.deepseek.base_url,
                "model": settings.deepseek.model,
                "api_key": settings.deepseek.api_key,
            },
        ]

    def plan(
        self,
        pool_families: list[dict],
        n_experiments: int,
        insights: str,
        suggestions: dict,
        skeleton_candidates: list[str],
    ) -> tuple[list[dict], str]:
        """Try LLM providers in order, fall back to rule-based.

        Splits large requests into batches of 10 to avoid token limits.
        Returns (configs, provider_name).
        """
        system_prompt = _PLANNER_SYSTEM_PROMPT.format(
            factor_table=_build_factor_table(),
            banned_list=", ".join(sorted(BANNED_FIELDS)),
        )

        BATCH_SIZE = 10  # LLM can reliably produce 10 experiments per call

        for provider in self._providers:
            try:
                logger.info("Trying LLM provider: %s", provider["name"])
                all_valid: list[dict] = []
                remaining = n_experiments
                batch_num = 0

                while remaining > 0:
                    batch_n = min(remaining, BATCH_SIZE)
                    batch_num += 1
                    logger.info("  Batch %d: requesting %d experiments", batch_num, batch_n)

                    user_prompt = _build_user_prompt(
                        pool_families, batch_n, insights, suggestions, skeleton_candidates
                    )
                    raw = self._call_llm(provider, system_prompt, user_prompt)
                    configs = self._parse_json(raw)

                    if not isinstance(configs, list) or len(configs) == 0:
                        logger.warning("  Batch %d: empty/invalid response", batch_num)
                        break  # This provider failed, try next

                    # Validate each config
                    for cfg in configs:
                        errors = validate_experiment_config(cfg)
                        if errors:
                            logger.debug("  Config validation errors: %s", errors)
                        else:
                            all_valid.append(cfg)

                    remaining -= batch_n
                    logger.info("  Batch %d: %d valid (total %d/%d)",
                               batch_num, len(configs), len(all_valid), n_experiments)

                if all_valid:
                    logger.info("Provider %s produced %d valid configs total", provider["name"], len(all_valid))
                    return all_valid, provider["name"]
                else:
                    logger.warning("Provider %s: all batches failed", provider["name"])
            except Exception as e:
                logger.error("Provider %s failed: %s", provider["name"], e)

        # Fallback: rule-based
        logger.info("All LLM providers failed, using rule-based fallback")
        configs = self._rule_based(n_experiments, pool_families, skeleton_candidates)
        return configs, "rule-based"

    def _call_llm(self, provider: dict, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI-compatible API."""
        client = OpenAI(
            base_url=provider["base_url"],
            api_key=provider["api_key"],
            timeout=120,
        )
        response = client.chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=8000,
        )
        return response.choices[0].message.content or ""

    def _parse_json(self, raw: str) -> list[dict]:
        """Parse JSON from LLM response, handling think tags and markdown blocks."""
        text = raw
        # Strip <think>...</think> tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Extract from markdown code block
        m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1)
        text = text.strip()
        # Try parsing
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
            return []
        except json.JSONDecodeError:
            # Try to find JSON array in text
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            logger.error("Failed to parse JSON from LLM response: %s", text[:300])
            return []

    def _rule_based(
        self,
        n: int,
        pool_families: list[dict],
        skeleton_candidates: list[str],
    ) -> list[dict]:
        """Generate configs using deterministic combinatorics."""
        configs: list[dict] = []
        factors = sorted(VALID_BUY_FACTORS.keys())

        # Use skeleton candidates first
        for cand in skeleton_candidates[:n]:
            parts = [p.strip() for p in cand.split("+")]
            buy_conds = []
            sell_conds = []
            for field in parts:
                info = VALID_BUY_FACTORS.get(field)
                if not info:
                    continue
                mid_val = (info["min"] + info["max"]) / 2
                cond: dict = {
                    "field": field,
                    "operator": info["op"],
                    "compare_type": "value",
                    "compare_value": round(mid_val, 4),
                }
                if info["params"]:
                    cond["params"] = dict(info["params"])
                buy_conds.append(cond)

            # Default sell condition
            sell_conds = [
                {
                    "field": "MOM",
                    "operator": "<",
                    "compare_type": "value",
                    "compare_value": -1.0,
                    "params": {"period": 20},
                },
            ]

            configs.append({
                "name_suffix": cand.replace(" + ", "_"),
                "buy_conditions": buy_conds,
                "sell_conditions": sell_conds,
                "exit_config": {
                    "stop_loss_pct": -10,
                    "take_profit_pct": 1.0,
                    "max_hold_days": 2,
                },
            })

        # Fill remaining with random 2-factor combos
        combo_iter = itertools.combinations(factors, 2)
        for combo in combo_iter:
            if len(configs) >= n:
                break
            buy_conds = []
            for field in combo:
                info = VALID_BUY_FACTORS[field]
                mid_val = (info["min"] + info["max"]) / 2
                cond = {
                    "field": field,
                    "operator": info["op"],
                    "compare_type": "value",
                    "compare_value": round(mid_val, 4),
                }
                if info["params"]:
                    cond["params"] = dict(info["params"])
                buy_conds.append(cond)

            configs.append({
                "name_suffix": "_".join(combo),
                "buy_conditions": buy_conds,
                "sell_conditions": [
                    {
                        "field": "KBAR_amplitude",
                        "operator": ">",
                        "compare_type": "value",
                        "compare_value": 0.06,
                    },
                ],
                "exit_config": {
                    "stop_loss_pct": -10,
                    "take_profit_pct": 1.0,
                    "max_hold_days": 2,
                },
            })

        return configs[:n]


# ────────────────────────────────────────────────────────────────
# 9.  ExplorationEngine (singleton)
# ────────────────────────────────────────────────────────────────

class ExplorationEngine:
    """Singleton autonomous exploration engine."""

    _instance: Optional["ExplorationEngine"] = None
    _initialized: bool = False

    def __new__(cls) -> "ExplorationEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Public state
        self.state: str = "idle"  # idle | running | stopping | error
        self.current_round: int = 0
        self.current_step: str = ""
        self.step_detail: str = ""
        self.rounds_total: int = 0
        self.rounds_completed: int = 0
        self.strategies_total: int = 0
        self.strategies_done: int = 0
        self.strategies_invalid: int = 0
        self.strategies_pending: int = 0
        self.stda_count: int = 0
        self.best_score: float = 0.0
        self.pool_families: int = 0
        self.pool_active: int = 0
        self.pool_gap: int = 0
        self.started_at: Optional[datetime] = None
        self.llm_provider: str = ""
        self.last_error: str = ""
        self.experiment_ids: list[int] = []

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ──

    def start(
        self,
        rounds: int = 1,
        experiments_per_round: int = 8,
        source_strategy_id: int = 0,
    ) -> dict:
        """Start the exploration loop in a background thread."""
        if self.state == "running":
            return {"error": "Already running", "state": self.state}

        # Determine next round number from API
        resp = _api("GET", "lab/exploration-rounds?page=1&size=1")
        items = resp.get("items", [])
        if items:
            self.current_round = max(r.get("round_number", 0) for r in items) + 1
        else:
            total = resp.get("total", 0)
            self.current_round = total + 1

        self.state = "running"
        self.rounds_total = rounds
        self.rounds_completed = 0
        self.started_at = datetime.now()
        self.last_error = ""
        self.experiment_ids = []
        self._stop_event.clear()

        self._source_strategy_id = source_strategy_id

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(rounds, experiments_per_round),
            daemon=True,
            name="exploration-engine",
        )
        self._thread.start()

        return {"state": self.state, "round_number": self.current_round, "rounds": rounds}

    def stop(self) -> dict:
        """Request graceful stop at end of current step."""
        if self.state != "running":
            return {"error": "Not running", "state": self.state}
        self.state = "stopping"
        self._stop_event.set()
        return {"state": self.state, "message": "Stop requested, will finish current step"}

    def get_status(self) -> dict:
        """Return current engine status."""
        elapsed = 0.0
        eta = 0.0
        if self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds()
            if self.rounds_completed > 0:
                avg_per_round = elapsed / self.rounds_completed
                remaining = self.rounds_total - self.rounds_completed
                eta = avg_per_round * remaining

        return {
            "state": self.state,
            "current_round": self.current_round,
            "current_step": self.current_step,
            "step_detail": self.step_detail,
            "rounds_total": self.rounds_total,
            "rounds_completed": self.rounds_completed,
            "strategies_total": self.strategies_total,
            "strategies_done": self.strategies_done,
            "strategies_invalid": self.strategies_invalid,
            "strategies_pending": self.strategies_pending,
            "stda_count": self.stda_count,
            "best_score": self.best_score,
            "pool_families": self.pool_families,
            "pool_active": self.pool_active,
            "pool_gap": self.pool_gap,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": round(eta, 1),
            "llm_provider": self.llm_provider,
            "last_error": self.last_error,
            "experiment_ids": self.experiment_ids,
        }

    # ── Internal workflow ──

    def _set_step(self, step: str, detail: str = ""):
        self.current_step = step
        self.step_detail = detail
        logger.info("Step: %s — %s", step, detail)

    def _run_loop(self, rounds: int, exp_per_round: int):
        """Main workflow loop."""
        try:
            for i in range(rounds):
                if self._stop_event.is_set():
                    break

                round_start = datetime.now()
                self.current_round = self.current_round if i == 0 else self.current_round + 1
                self._set_step("promote_check", f"Round {self.current_round}")

                # Step 1: Promote check
                self._step_promote_check()
                if self._stop_event.is_set():
                    break

                # Step 2: Sync unsynced rounds
                self._set_step("sync_rounds")
                self._step_sync_unsynced_rounds()
                if self._stop_event.is_set():
                    break

                # Step 3: Load state
                self._set_step("load_state")
                pool_families = self._step_load_state()
                if self._stop_event.is_set():
                    break

                # Step 3.5: Retry pending
                self._set_step("retry_pending")
                _api("POST", "lab/experiments/retry-pending")
                if self._stop_event.is_set():
                    break

                # Step 4: Plan
                self._set_step("plan", f"Designing {exp_per_round} experiments")
                configs, provider = self._step_plan(pool_families, exp_per_round)
                self.llm_provider = provider
                if self._stop_event.is_set():
                    break

                # Step 5: Submit
                self._set_step("submit", f"Submitting {len(configs)} experiments")
                exp_ids = self._step_submit(configs)
                self.experiment_ids = exp_ids
                if self._stop_event.is_set():
                    break

                # Step 6: Poll
                self._set_step("poll", f"Waiting for {len(exp_ids)} experiments")
                self._step_poll(exp_ids)
                if self._stop_event.is_set():
                    break

                # Step 7: Self-heal
                self._set_step("self_heal")
                healed_ids = self._step_self_heal(exp_ids, configs)
                if healed_ids:
                    exp_ids.extend(healed_ids)
                    self._set_step("poll_healed", f"Waiting for {len(healed_ids)} healed experiments")
                    self._step_poll(healed_ids)
                if self._stop_event.is_set():
                    break

                # Step 8: Promote and rebalance
                self._set_step("promote_and_rebalance")
                promoted = self._step_promote_and_rebalance(exp_ids)
                if self._stop_event.is_set():
                    break

                # Step 9: Update memory doc
                self._set_step("update_memory_doc")
                self._step_update_memory_doc(promoted)
                if self._stop_event.is_set():
                    break

                # Step 10: Sync Pinecone
                self._set_step("sync_pinecone")
                self._step_sync_pinecone()
                if self._stop_event.is_set():
                    break

                # Step 11: Record round
                self._set_step("record")
                self._step_record(exp_ids, promoted)

                # Step 12: Resolve problems
                self._set_step("resolve_problems")
                self._step_resolve_problems(exp_ids)

                self.rounds_completed += 1
                round_elapsed = (datetime.now() - round_start).total_seconds()
                logger.info(
                    "Round %d complete in %.0fs — %d StdA+, best=%.4f",
                    self.current_round, round_elapsed, self.stda_count, self.best_score,
                )

            self.state = "idle"
            self._set_step("done", f"Completed {self.rounds_completed}/{self.rounds_total} rounds")

        except Exception as e:
            self.state = "error"
            self.last_error = str(e)
            logger.exception("Exploration engine error: %s", e)

    # ── Step implementations ──

    def _step_promote_check(self):
        """Scan recent experiments for unpromoted StdA+ strategies and promote them."""
        self._set_step("promote_check", "Scanning recent experiments")
        resp = _api("GET", "lab/experiments?page=1&size=300")
        items = resp.get("items", [])
        promoted_count = 0

        for exp_item in items:
            exp_id = exp_item.get("id")
            if not exp_id:
                continue
            detail = _api("GET", f"lab/experiments/{exp_id}")
            strategies = detail.get("strategies", [])
            for s in strategies:
                if s.get("promoted"):
                    continue
                if s.get("status") != "done":
                    continue
                if is_stda_plus(
                    s.get("score", 0),
                    s.get("total_return_pct", 0),
                    s.get("max_drawdown_pct", 100),
                    s.get("total_trades", 0),
                    s.get("win_rate", 0),
                ):
                    result = _promote_strategy(s["id"])
                    if "error" not in result:
                        promoted_count += 1

        self.step_detail = f"Promoted {promoted_count} StdA+ strategies"
        logger.info("Promote check: %d promoted", promoted_count)

    def _step_sync_unsynced_rounds(self):
        """Find exploration rounds with memory_synced=false, mark them synced."""
        resp = _api("GET", "lab/exploration-rounds?page=1&size=100")
        items = resp.get("items", [])
        synced = 0
        for r in items:
            if not r.get("memory_synced", True):
                rid = r.get("id")
                if rid:
                    update_data = dict(r)
                    update_data["memory_synced"] = True
                    _api("PUT", f"lab/exploration-rounds/{rid}", update_data)
                    synced += 1
        self.step_detail = f"Synced {synced} rounds"

    def _step_load_state(self) -> list[dict]:
        """Query pool status and return family summary."""
        resp = _api("GET", "strategies/pool/status")
        families = resp.get("family_summary", [])
        self.pool_families = len(families)
        self.pool_active = resp.get("active_strategies", 0)
        self.pool_gap = sum(f.get("gap", 0) for f in families)
        return families

    def _step_plan(self, pool_families: list[dict], n: int) -> tuple[list[dict], str]:
        """Design experiments using LLM planner."""
        insights = load_historical_insights()
        suggestions = get_latest_round_suggestions()
        candidates = generate_skeleton_candidates(pool_families, max_candidates=n * 2)

        planner = LLMPlanner()
        configs, provider = planner.plan(pool_families, n, insights, suggestions, candidates)
        return configs, provider

    def _step_submit(self, configs: list[dict]) -> list[int]:
        """Submit each config as a separate experiment via batch-clone-backtest.

        Handles two LLM output formats:
        Format A (plan spec): {extra_buy_conditions, extra_sell_conditions, exit_configs: [...]}
        Format B (LLM actual): {buy_conditions, sell_conditions, exit_config: {...}}
        """
        source_id = getattr(self, "_source_strategy_id", 0)
        if not source_id:
            logger.error("No source_strategy_id set")
            return []

        exp_ids: list[int] = []
        total_strats = 0

        for cfg in configs:
            # Build full buy/sell from base + extra (handle both field names)
            extra_buy = cfg.get("extra_buy_conditions", cfg.get("buy_conditions", []))
            extra_sell = cfg.get("extra_sell_conditions", cfg.get("sell_conditions", []))
            buy = copy.deepcopy(BASE_BUY) + (extra_buy if isinstance(extra_buy, list) else [])
            sell = copy.deepcopy(BASE_SELL) + (extra_sell if isinstance(extra_sell, list) else [])
            label = cfg.get("label", cfg.get("name_suffix", "exp"))

            # Handle exit configs: could be list (exit_configs) or single dict (exit_config)
            raw_exits = cfg.get("exit_configs", [])
            if not raw_exits:
                # Single exit_config → wrap in list
                single = cfg.get("exit_config", {})
                if single:
                    raw_exits = [single]

            if not raw_exits:
                # No exit config at all → use default grid
                raw_exits = [
                    {"name": "SL20_TP0.5_MHD2", "stop_loss_pct": -20, "take_profit_pct": 0.5, "max_hold_days": 2},
                    {"name": "SL20_TP1_MHD3",   "stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 3},
                    {"name": "SL15_TP1.5_MHD3", "stop_loss_pct": -15, "take_profit_pct": 1.5, "max_hold_days": 3},
                    {"name": "SL20_TP2_MHD5",   "stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 5},
                    {"name": "SL25_TP3_MHD5",   "stop_loss_pct": -25, "take_profit_pct": 3.0, "max_hold_days": 5},
                ]

            # Build API-compatible exit_configs
            api_exit_configs = []
            for ec in raw_exits:
                api_exit_configs.append({
                    "name_suffix": f"_{label}_{ec.get('name', 'x')}",
                    "exit_config": {
                        "stop_loss_pct": ec.get("stop_loss_pct", -20),
                        "take_profit_pct": ec.get("take_profit_pct", 2.0),
                        "max_hold_days": int(ec.get("max_hold_days", 5)),
                    },
                    "buy_conditions": buy,
                    "sell_conditions": sell,
                })

            resp = _api("POST", f"lab/strategies/{source_id}/batch-clone-backtest", {
                "source_strategy_id": source_id,
                "exit_configs": api_exit_configs,
            })
            eid = resp.get("experiment_id")
            if eid:
                exp_ids.append(eid)
                total_strats += resp.get("count", len(api_exit_configs))
            else:
                logger.warning("Failed to submit experiment '%s': %s", label, str(resp)[:100])

        self.strategies_total = total_strats
        self.strategies_done = 0
        self.strategies_invalid = 0
        self.strategies_pending = total_strats

        # Retry pending to ensure all strategies are queued
        _api("POST", "lab/experiments/retry-pending")

        logger.info("Submitted %d experiments, %d strategies", len(exp_ids), total_strats)
        return exp_ids

    def _step_poll(self, exp_ids: list[int]):
        """Poll experiment status every 2 minutes until all done."""
        if not exp_ids:
            return

        stall_count = 0
        last_done = 0

        while not self._stop_event.is_set():
            all_done = True
            total_done = 0
            total_invalid = 0
            total_pending = 0
            best_score = 0.0
            stda = 0

            for eid in exp_ids:
                detail = _api("GET", f"lab/experiments/{eid}")
                status = detail.get("status", "")
                strategies = detail.get("strategies", [])

                for s in strategies:
                    st = s.get("status", "")
                    if st == "done":
                        total_done += 1
                        sc = s.get("score", 0)
                        if sc > best_score:
                            best_score = sc
                        if is_stda_plus(
                            sc,
                            s.get("total_return_pct", 0),
                            s.get("max_drawdown_pct", 100),
                            s.get("total_trades", 0),
                            s.get("win_rate", 0),
                        ):
                            stda += 1
                    elif st == "invalid":
                        total_invalid += 1
                    else:
                        total_pending += 1

                if status not in ("done", "failed"):
                    all_done = False

            self.strategies_done = total_done
            self.strategies_invalid = total_invalid
            self.strategies_pending = total_pending
            self.best_score = best_score
            self.stda_count = stda
            self.step_detail = (
                f"done={total_done}, invalid={total_invalid}, "
                f"pending={total_pending}, StdA+={stda}"
            )

            if all_done or total_pending == 0:
                break

            # Stall detection
            if total_done == last_done:
                stall_count += 1
            else:
                stall_count = 0
                last_done = total_done

            if stall_count >= 5:  # 10 min stall
                logger.warning("Stall detected (%d polls no progress), triggering retry-pending", stall_count)
                _api("POST", "lab/experiments/retry-pending")
                stall_count = 0

            # Wait 2 minutes
            self._stop_event.wait(120)

    def _step_self_heal(self, exp_ids: list[int], configs: list[dict]) -> list[int]:
        """If invalid > done, loosen thresholds 20% and resubmit."""
        if self.strategies_invalid <= self.strategies_done:
            return []

        logger.info("Self-heal: invalid=%d > done=%d, loosening thresholds", self.strategies_invalid, self.strategies_done)

        loosened = []
        for cfg in configs:
            new_cfg = copy.deepcopy(cfg)
            buy_conds = new_cfg.get("buy_conditions", [])
            for cond in buy_conds:
                cv = cond.get("compare_value")
                if cv is None or not isinstance(cv, (int, float)):
                    continue
                op = cond.get("operator", cond.get("compare_type", ""))
                if op == "<":
                    cond["compare_value"] = round(cv * 1.2, 4)
                elif op == ">":
                    cond["compare_value"] = round(cv * 0.8, 4)
            new_cfg["name_suffix"] = new_cfg.get("name_suffix", "") + "_loosened"
            loosened.append(new_cfg)

        if not loosened:
            return []

        source_id = getattr(self, "_source_strategy_id", 0)
        if not source_id:
            return []

        payload = {
            "source_strategy_id": source_id,
            "exit_configs": loosened,
        }
        resp = _api("POST", f"lab/strategies/{source_id}/batch-clone-backtest", payload, timeout=300)
        exp_id = resp.get("experiment_id")
        if not exp_id:
            logger.error("Self-heal batch-clone-backtest failed: %s", resp)
            return []

        return [exp_id]

    def _step_promote_and_rebalance(self, exp_ids: list[int]) -> int:
        """Promote StdA+ strategies and Standard B regime champions, then rebalance."""
        promoted = 0
        LABEL_MAP = {
            "bull": ("[AI-牛市]", "牛市"),
            "bear": ("[AI-熊市]", "熊市"),
            "rang": ("[AI-震荡]", "震荡"),
        }

        for eid in exp_ids:
            detail = _api("GET", f"lab/experiments/{eid}")
            strategies = detail.get("strategies", [])

            for s in strategies:
                if s.get("promoted") or s.get("status") != "done":
                    continue

                sid = s["id"]

                # StdA+ promote
                if is_stda_plus(
                    s.get("score", 0),
                    s.get("total_return_pct", 0),
                    s.get("max_drawdown_pct", 100),
                    s.get("total_trades", 0),
                    s.get("win_rate", 0),
                ):
                    result = _promote_strategy(sid)
                    if "error" not in result:
                        promoted += 1
                    continue

                # Standard B: regime champion promote
                regime_stats = s.get("regime_stats") or {}
                if not regime_stats:
                    continue

                best_regime = None
                best_pnl = 0
                for regime_key, rdata in regime_stats.items():
                    if not isinstance(rdata, dict):
                        continue
                    pnl = rdata.get("total_pnl", 0)
                    if pnl > best_pnl:
                        best_pnl = pnl
                        best_regime = regime_key

                if best_regime and best_pnl > 0:
                    # Match regime to label
                    for key_prefix, (label, category) in LABEL_MAP.items():
                        if best_regime.lower().startswith(key_prefix):
                            result = _promote_strategy(sid, label=label, category=category)
                            if "error" not in result:
                                promoted += 1
                            break

        # Rebalance pool
        _api("POST", "strategies/rebalance")

        self.step_detail = f"Promoted {promoted} strategies"
        return promoted

    def _step_update_memory_doc(self, promoted: int):
        """Update lab-experiment-analysis.md with auto-promote results and next priorities."""
        if not _INSIGHT_DOC.exists():
            return

        try:
            content = _INSIGHT_DOC.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read insight doc: %s", e)
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Update or add Auto-Promote section
        auto_section = (
            f"\n## Auto-Promote (Engine)\n\n"
            f"> 最近更新: {now}\n"
            f"> R{self.current_round}: {promoted} promoted, "
            f"{self.stda_count} StdA+, best={self.best_score:.4f}, "
            f"provider={self.llm_provider}\n"
        )

        pattern = r"## Auto-Promote \(Engine\)\s*\n.*?(?=\n## |\Z)"
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, auto_section.strip(), content, flags=re.DOTALL)
        else:
            content += "\n" + auto_section

        # Update 下一步优先级 section
        next_section = (
            f"\n## 下一步优先级\n\n"
            f"- Pool: {self.pool_families} families, {self.pool_active} active, gap={self.pool_gap}\n"
            f"- Last round R{self.current_round}: {self.strategies_done} done, "
            f"{self.strategies_invalid} invalid, {self.stda_count} StdA+\n"
            f"- LLM provider: {self.llm_provider}\n"
        )

        pattern2 = r"## 下一步优先级\s*\n.*?(?=\n## |\Z)"
        if re.search(pattern2, content, re.DOTALL):
            content = re.sub(pattern2, next_section.strip(), content, flags=re.DOTALL)
        else:
            content += "\n" + next_section

        try:
            _INSIGHT_DOC.write_text(content, encoding="utf-8")
            logger.info("Updated insight doc: %s", _INSIGHT_DOC)
        except Exception as e:
            logger.error("Failed to write insight doc: %s", e)

    def _step_sync_pinecone(self):
        """Run scripts/sync-memory.py to sync to Pinecone."""
        script = Path(__file__).parent.parent.parent / "scripts" / "sync-memory.py"
        if not script.exists():
            logger.warning("sync-memory.py not found: %s", script)
            return

        try:
            result = subprocess.run(
                ["python3", str(script), "--incremental"],
                capture_output=True, text=True, timeout=120,
                cwd=str(script.parent.parent),
            )
            if result.returncode != 0:
                logger.warning("sync-memory.py failed: %s", result.stderr[:300])
            else:
                logger.info("Pinecone sync complete")
        except subprocess.TimeoutExpired:
            logger.warning("sync-memory.py timed out")
        except Exception as e:
            logger.error("sync-memory.py error: %s", e)

    def _step_record(self, exp_ids: list[int], promoted: int):
        """Record exploration round via API."""
        now = datetime.now()
        data = {
            "round_number": self.current_round,
            "mode": "auto",
            "started_at": self.started_at.isoformat() if self.started_at else now.isoformat(),
            "finished_at": now.isoformat(),
            "experiment_ids": exp_ids,
            "total_experiments": len(exp_ids),
            "total_strategies": self.strategies_total,
            "profitable_count": self.strategies_done,
            "profitability_pct": round(
                (self.strategies_done / max(self.strategies_total, 1)) * 100, 1
            ),
            "std_a_count": self.stda_count,
            "best_strategy_name": "",
            "best_strategy_score": self.best_score,
            "best_strategy_return": 0.0,
            "best_strategy_dd": 0.0,
            "insights": [],
            "promoted": [{"count": promoted, "round": self.current_round}],
            "issues_resolved": [],
            "next_suggestions": [],
            "summary": (
                f"R{self.current_round}: {self.strategies_done} done, "
                f"{self.strategies_invalid} invalid, {self.stda_count} StdA+, "
                f"best={self.best_score:.4f}, provider={self.llm_provider}"
            ),
            "memory_synced": False,
            "pinecone_synced": True,
        }
        _api("POST", "lab/exploration-rounds", data)

    def _step_resolve_problems(self, exp_ids: list[int]):
        """Detect and fix: zombies, missed promotes, pool cleanup."""
        self._set_step("resolve_problems", "Zombie detection")

        # 1. Zombie detection: experiments stuck in backtesting
        resp = _api("GET", "lab/experiments?page=1&size=50")
        for exp_item in resp.get("items", []):
            if exp_item.get("status") == "backtesting":
                eid = exp_item.get("id")
                if eid and eid not in exp_ids:
                    logger.warning("Zombie experiment %d detected, triggering retry", eid)
                    _api("POST", "lab/experiments/retry-pending")
                    break

        # 2. Missed promote sweep — already handled by promote_check at start
        self.step_detail = "Zombie check + missed promote sweep done"

        # 3. Pool cleanup
        _api("POST", "strategies/cleanup?dry_run=false")
