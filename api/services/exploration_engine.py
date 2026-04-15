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
# 1b. Experience Database — distilled knowledge from 1200+ rounds
# ────────────────────────────────────────────────────────────────

_EXPERIENCE_PATH = Path(__file__).parent.parent.parent / "config" / "experience.json"
_CHECKPOINT_PATH = Path(__file__).parent.parent.parent / "config" / "exploration_checkpoint.json"


def load_experience() -> dict:
    """Load experience database. Returns empty dict if not found."""
    if not _EXPERIENCE_PATH.exists():
        return {}
    try:
        return json.loads(_EXPERIENCE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ────────────────────────────────────────────────────────────────
# 2.  Factor Registry — dynamically built from src.factors.registry
# ────────────────────────────────────────────────────────────────

# Factors whose operator should be ">" (buy when value is HIGH)
# Everything else defaults to "<" (buy when value is LOW)
_BUY_HIGH_FACTORS = frozenset({
    "MOM", "RSTR", "RSTR_weighted", "W_RSTR_weighted",
    "PVOL_corr", "W_PVOL_corr",
    "ADX", "W_ADX", "ADX_plus_di",
    "KBAR_lower_shadow",  # long lower shadow = buying pressure
    "PPOS_close_pos",     # high position = strong
    "PPOS_low_dist",      # far from low = strong
    "RSI", "KDJ_K", "KDJ_D", "MFI", "STOCH_K", "STOCHRSI_K",
    "LIQ_log_amount",     # high volume = good liquidity
})

# Factors to exclude from exploration (known bad / too noisy)
_EXCLUDE_FROM_EXPLORATION = frozenset({
    # Builtin base factors (already in BASE_BUY/SELL)
    "RSI", "ATR", "MA", "EMA", "OBV", "volume_ma",
    # Known bad (from historical experiments)
    "PPOS_close_pos", "PPOS_consec_dir", "AMPVOL_parkinson",
    "PVOL_vwap_bias", "LIQ_amihud",
    # Non-alpha (sentiment, not price/volume derived)
    "NEWS_SENTIMENT_3D", "NEWS_SENTIMENT_7D",
    # Too noisy / always fails
    "KDJ_K", "KDJ_D", "KDJ_J", "MACD", "MACD_signal", "MACD_hist",
    "NVI", "VPT", "CMF", "ADI", "FI", "EMV", "EMV_sma",
    "PPO", "PPO_signal", "PPO_hist", "PVO", "PVO_signal", "PVO_hist",
    "AO", "TSI", "TRIX", "DPO", "MASS", "KST", "KST_sig", "KST_diff",
    "AROON_up", "AROON_down", "AROON_osc",
    "VORTEX_pos", "VORTEX_neg", "VORTEX_diff",
    "ICHIMOKU_conv", "ICHIMOKU_base", "ICHIMOKU_a", "ICHIMOKU_b",
    "DONCHIAN_upper", "DONCHIAN_lower", "DONCHIAN_middle",
    "STC", "WR", "ROC",
    # Redundant with other fields
    "ADX_minus_di", "STOCH_D", "STOCHRSI_D",
    "BOLL_upper", "BOLL_lower", "BOLL_middle",
    "KELTNER_upper", "KELTNER_lower", "KELTNER_middle",
})


def _build_valid_factors() -> dict[str, dict]:
    """Build VALID_BUY_FACTORS dynamically from src.factors.registry.

    Auto-discovers all factors with field_ranges, assigns operator,
    extracts params. New factors added via @register_factor appear
    automatically — zero code changes needed.
    """
    # Import triggers auto-discovery of all factor modules
    import src.factors  # noqa: F401
    from src.factors.registry import FACTORS, get_all_field_ranges

    ranges = get_all_field_ranges()
    result: dict[str, dict] = {}

    for name, fdef in FACTORS.items():
        # Get default params for this factor group
        params = None
        if fdef.params:
            params = {k: v["default"] for k, v in fdef.params.items()}

        for field_name, _label in fdef.sub_fields:
            if field_name in _EXCLUDE_FROM_EXPLORATION:
                continue
            if field_name not in ranges:
                continue  # No range defined → skip

            lo, hi = ranges[field_name]
            op = ">" if field_name in _BUY_HIGH_FACTORS else "<"

            result[field_name] = {
                "op": op,
                "params": params,
                "min": lo,
                "max": hi,
            }

    # Also add W_ (weekly) variants for key factors
    weekly_candidates = [
        "REALVOL", "ATR", "AMPVOL_std", "RSTR_weighted",
        "PVOL_corr", "KBAR_amplitude", "ADX",
    ]
    for base_field in weekly_candidates:
        w_field = f"W_{base_field}"
        if w_field not in result and base_field in result:
            base = result[base_field]
            result[w_field] = {
                "op": base["op"],
                "params": base["params"],
                "min": base["min"],
                "max": base["max"] * 1.5,  # weekly values tend to be larger
            }

    return result


# Build at import time
VALID_BUY_FACTORS = _build_valid_factors()

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
        "operator": ">",
        "compare_type": "value",
        "compare_value": 48,
        "params": {"period": 14},
    },
    {
        "field": "RSI",
        "operator": "<",
        "compare_type": "value",
        "compare_value": 66,
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
    """Validate experiment config (supports both old and new simplified format)."""
    errors: list[str] = []

    # Must have a name
    if not config.get("name") and not config.get("name_suffix") and not config.get("label"):
        errors.append("missing name/name_suffix/label")

    # New simplified format: buy_factors = [{"factor": "X", "value": N}]
    buy_factors = config.get("buy_factors", [])
    if buy_factors:
        if not isinstance(buy_factors, list):
            errors.append("buy_factors must be a list")
        else:
            for i, bf in enumerate(buy_factors):
                factor = bf.get("factor", "")
                if not factor:
                    errors.append(f"buy_factors[{i}]: missing factor")
                elif factor in BANNED_FIELDS:
                    errors.append(f"buy_factors[{i}]: banned factor '{factor}'")
                elif factor not in VALID_BUY_FACTORS:
                    errors.append(f"buy_factors[{i}]: unknown factor '{factor}'")
                if "value" not in bf:
                    errors.append(f"buy_factors[{i}]: missing value")

    # Sell factors (same format)
    sell_factors = config.get("sell_factors", [])
    if sell_factors:
        if not isinstance(sell_factors, list):
            errors.append("sell_factors must be a list")
        else:
            for i, sf in enumerate(sell_factors):
                factor = sf.get("factor", "")
                if factor and factor in BANNED_FIELDS:
                    errors.append(f"sell_factors[{i}]: banned factor '{factor}'")

    # Old format: buy_conditions / sell_conditions (still supported)
    for key in ("buy_conditions", "sell_conditions"):
        conds = config.get(key)
        if conds is not None:
            if not isinstance(conds, list):
                errors.append(f"{key} must be a list")
            else:
                for i, c in enumerate(conds):
                    for err in validate_condition(c):
                        errors.append(f"{key}[{i}]: {err}")

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
    max_candidates: int = 30,
) -> list[str]:
    """Generate novel factor combination candidates not yet in the pool.

    Covers 2/3/4/5-factor combos, ranked by experience-based scoring:
    - Factors with high historical StdA+ rate get priority
    - Combos already tested with 0% rate are excluded
    - 4-5 factor combos only use proven factors (experience rate > 15%)

    Returns list of strings like "KBAR_amplitude + W_REALVOL".
    """
    # ── Parse existing pool families ──
    existing_sets: set[frozenset[str]] = set()
    for fam in existing_families:
        name = fam.get("family", "")
        parts = frozenset(p.strip() for p in name.split("+") if p.strip())
        if parts:
            existing_sets.add(parts)

    # ── Load experience for scoring + filtering ──
    exp = load_experience()
    factor_scores = exp.get("factor_scores", {})
    combo_scores = exp.get("combo_scores", {})

    # Build set of known-bad combos (0% StdA+ with >=10 experiments)
    bad_combos: set[frozenset[str]] = set()
    for combo_name, data in combo_scores.items():
        if data.get("total", 0) >= 10 and data.get("stda_count", 0) == 0:
            bad_combos.add(frozenset(combo_name.split("+")))

    # ── Score each factor by historical performance ──
    def _factor_score(name: str) -> float:
        """Higher = better. Balances exploitation (proven) vs exploration (unknown)."""
        data = factor_scores.get(name, {})
        total = data.get("total", 0)
        stda = data.get("stda_count", 0)
        if total == 0:
            return 0.20  # small exploration bonus (below proven factors)
        rate = stda / max(1, total)
        # Confidence-weighted: more experiments = more trust in the rate
        confidence = min(1.0, total / 50)  # ramp up to full confidence at 50 experiments
        return rate * confidence

    all_factors = sorted(VALID_BUY_FACTORS.keys())

    # Proven factors for 4-5 combos (rate > 15% or untested)
    proven_factors = [f for f in all_factors if _factor_score(f) > 0.15]

    # ── Check if combo is novel (not in pool) ──
    def _is_novel(combo: tuple[str, ...]) -> bool:
        # Normalize to family-level names (KBAR_amplitude → KBAR, W_REALVOL → W_REALVOL)
        family_parts = set()
        for p in combo:
            if p.startswith(("W_", "M_")):
                family_parts.add(p)
            else:
                family_parts.add(p.upper().split("_")[0])
        family_parts |= {"ATR", "RSI"}
        comparison = frozenset(family_parts)

        for ex_set in existing_sets:
            if comparison == ex_set or comparison.issubset(ex_set):
                return False
        return True

    def _is_bad(combo: tuple[str, ...]) -> bool:
        return frozenset(combo) in bad_combos

    # ── Generate candidates with scores ──
    scored: list[tuple[float, str]] = []  # (score, "A + B + C")

    # 2-factor combos
    for combo in itertools.combinations(all_factors, 2):
        if not _is_novel(combo) or _is_bad(combo):
            continue
        score = sum(_factor_score(f) for f in combo) / len(combo)
        scored.append((score, " + ".join(combo)))

    # 3-factor combos
    for combo in itertools.combinations(all_factors, 3):
        if not _is_novel(combo) or _is_bad(combo):
            continue
        score = sum(_factor_score(f) for f in combo) / len(combo)
        scored.append((score, " + ".join(combo)))

    # 4-factor combos (only proven factors, cap at 500 combos checked)
    count_4 = 0
    for combo in itertools.combinations(proven_factors, 4):
        if count_4 > 500:
            break
        count_4 += 1
        if not _is_novel(combo) or _is_bad(combo):
            continue
        score = sum(_factor_score(f) for f in combo) / len(combo)
        scored.append((score, " + ".join(combo)))

    # 5-factor combos (only top proven factors, cap at 200 combos checked)
    top_proven = [f for f in proven_factors if _factor_score(f) > 0.25][:15]
    count_5 = 0
    for combo in itertools.combinations(top_proven, 5):
        if count_5 > 200:
            break
        count_5 += 1
        if not _is_novel(combo) or _is_bad(combo):
            continue
        score = sum(_factor_score(f) for f in combo) / len(combo)
        scored.append((score, " + ".join(combo)))

    # ── Allocate slots per factor-count tier ──
    # Reserve slots: 20% two-factor, 30% three-factor, 30% four-factor, 20% five-factor
    by_tier: dict[int, list[tuple[float, str]]] = {}
    for score, name in scored:
        n = len(name.split(" + "))
        by_tier.setdefault(n, []).append((score, name))

    # Sort each tier by score
    for tier_list in by_tier.values():
        tier_list.sort(key=lambda x: -x[0])

    # Allocate proportionally
    tier_quotas = {2: 0.20, 3: 0.30, 4: 0.30, 5: 0.20}
    result: list[str] = []
    for tier, pct in tier_quotas.items():
        n_slots = max(2, int(max_candidates * pct))
        tier_candidates = by_tier.get(tier, [])
        for _, name in tier_candidates[:n_slots]:
            result.append(name)

    # Fill remaining slots from any tier
    all_remaining = []
    used = set(result)
    for tier_list in by_tier.values():
        for _, name in tier_list:
            if name not in used:
                all_remaining.append(name)
    all_remaining.sort(key=lambda x: -dict(scored).get(x, 0))
    result.extend(all_remaining[:max(0, max_candidates - len(result))])

    return result[:max_candidates]


# ────────────────────────────────────────────────────────────────
# 8.  LLM Planner
# ────────────────────────────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """\
你是A股量化策略研究员。设计探索实验。

## 简化输出格式
你只需要输出因子名称和阈值数字,代码会自动添加正确的operator和params。

## 可用因子及其阈值范围
{factor_table}

## 禁用因子
{banned_list}

## 输出格式 — 严格JSON数组
```json
[
  {{
    "name": "描述性名称",
    "buy_factors": [
      {{"factor": "KBAR_amplitude", "value": 0.03}},
      {{"factor": "W_REALVOL", "value": 25}}
    ],
    "sell_factors": [
      {{"factor": "MOM", "value": -1.0}},
      {{"factor": "KBAR_amplitude", "value": 0.06}}
    ],
    "stop_loss": -20,
    "take_profit": 2.0,
    "max_hold_days": 5
  }}
]
```

## 规则
1. 每个实验 1-3 个 buy_factors(不要包含RSI/ATR,已自动添加)
2. 每个实验 0-2 个 sell_factors(卖出信号)
3. value必须在因子的阈值范围内
4. **多样性要求(重要!)**: 10个实验中,第一个因子(buy_factors[0])至少使用5种不同的因子。不要所有实验都用同一个因子开头。均匀覆盖: KBAR类, REALVOL类, AMPVOL类, RSTR类, PVOL类, MOM, LIQ类, W_类。
5. 不同实验使用不同的exit参数(stop_loss在-10到-30之间, take_profit在0.5到5.0之间, max_hold_days在2到10之间)
6. 禁止使用禁用因子
7. 只输出JSON,不要解释
"""


def _build_factor_table() -> str:
    """Build a simplified factor list for the prompt (no operator — code handles it)."""
    lines = []
    for name, info in sorted(VALID_BUY_FACTORS.items()):
        direction = "低买高卖" if info["op"] == "<" else "高买低卖"
        lines.append(f"- {name}: 买入阈值范围 [{info['min']}, {info['max']}], {direction}")
    return "\n".join(lines)


def _factor_to_condition(factor: str, value: float, for_sell: bool = False) -> dict | None:
    """Convert simplified {factor, value} to full condition dict.

    For buy: uses the factor's registered operator (e.g. "<" for KBAR_amplitude)
    For sell: reverses the operator (e.g. ">" for KBAR_amplitude, meaning sell when amplitude is HIGH)

    If experience has an optimal_range for this factor, clamps to that range
    instead of the full registry range (P1: experience-guided thresholds).
    """
    meta = VALID_BUY_FACTORS.get(factor)
    if meta is None:
        logger.warning("Unknown factor '%s', skipping", factor)
        return None

    # Buy: use registered operator. Sell: reverse it.
    if for_sell:
        op = ">" if meta["op"] == "<" else "<"
    else:
        op = meta["op"]

    # Determine clamp range: prefer experience optimal_range over registry full range
    lo, hi = meta["min"], meta["max"]
    if not for_sell:
        exp = load_experience()
        factor_exp = exp.get("factor_scores", {}).get(factor, {})
        opt = factor_exp.get("optimal_range")
        if opt and len(opt) == 2:
            # Use optimal range but stay within registry bounds
            lo = max(meta["min"], opt[0])
            hi = min(meta["max"], opt[1])

    clamped = max(lo, min(hi, value))

    cond: dict = {
        "field": factor,
        "operator": op,
        "compare_type": "value",
        "compare_value": round(clamped, 4),
    }
    if meta.get("params"):
        cond["params"] = meta["params"]
    return cond


def _build_experience_section(experience: dict) -> str:
    """Build the experience section for the LLM prompt (P1)."""
    if not experience:
        return ""

    lines: list[str] = []
    lines.append("## 历史经验数据 (从1200+轮探索中提取)")

    # ── Top proven combos (by StdA+ rate, min 3 experiments) ──
    combo_scores = experience.get("combo_scores", {})
    proven = [
        (k, v) for k, v in combo_scores.items()
        if v.get("stda_rate_pct", 0) > 0 and v.get("total", 0) >= 3
    ]
    proven.sort(key=lambda x: -x[1]["stda_rate_pct"])

    if proven:
        lines.append("\n已验证高成功率组合:")
        for combo_key, cs in proven[:5]:
            lines.append(
                f"  - {combo_key}: {cs['stda_rate_pct']}% StdA+ rate "
                f"({cs['total']} experiments, best={cs['best_score']:.4f})"
            )

    # ── Factor optimal thresholds ──
    factor_scores = experience.get("factor_scores", {})
    factors_with_range = [
        (k, v) for k, v in factor_scores.items()
        if v.get("optimal_range") and v.get("stda_count", 0) >= 2
    ]
    factors_with_range.sort(key=lambda x: -x[1]["stda_rate_pct"])

    if factors_with_range:
        lines.append("\n各因子最优阈值范围(优先使用这些范围内的值):")
        for name, fs in factors_with_range[:15]:
            lo, hi = fs["optimal_range"]
            lines.append(
                f"  - {name}: [{lo}, {hi}] ({fs['stda_rate_pct']}% StdA+ rate, "
                f"{fs['stda_count']}/{fs['total']} experiments)"
            )

    # ── Combos to avoid (0% StdA+ with 10+ experiments) ──
    avoid = [
        (k, v) for k, v in combo_scores.items()
        if v.get("stda_count", 0) == 0 and v.get("total", 0) >= 10
    ]
    avoid.sort(key=lambda x: -x[1]["total"])

    if avoid:
        lines.append("\n避免这些组合(历史上0% StdA+):")
        for combo_key, cs in avoid[:10]:
            lines.append(f"  - {combo_key} ({cs['total']} experiments, 0% StdA+)")

    return "\n".join(lines)


def _build_few_shot_from_pool() -> str:
    """Extract top strategies from pool as few-shot examples (P2)."""
    try:
        resp = _api("GET", "strategies?sort_by=score&sort_order=desc&page=1&size=10")
        items = resp.get("items", [])
        if not items:
            return ""
    except Exception:
        return ""

    lines: list[str] = ["## 成功策略示例 (从策略池提取)"]
    for i, s in enumerate(items[:5], 1):
        bs = s.get("backtest_summary", {}) or {}
        buy_conds = s.get("buy_conditions", [])
        if not buy_conds:
            continue

        # Extract extra factors (skip RSI/ATR)
        extra = []
        for cond in buy_conds:
            field = cond.get("field", "")
            if field in ("RSI", "ATR", "close", "volume", "high", "low", "open"):
                continue
            cv = cond.get("compare_value", "?")
            op = cond.get("operator", "?")
            extra.append(f"{field} {op} {cv}")

        if not extra:
            continue

        score = bs.get("score", s.get("score", 0)) or 0
        ret = bs.get("total_return_pct", 0) or 0
        wr = bs.get("win_rate", 0) or 0

        lines.append(
            f"  {i}. factors=[{', '.join(extra)}] → "
            f"score={score:.4f}, return={ret:.0f}%, wr={wr:.0f}%"
        )

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_user_prompt(
    pool_families: list[dict],
    n_experiments: int,
    insights: str,
    suggestions: dict,
    skeleton_candidates: list[str],
    experience: dict | None = None,
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

    # Experience section (P1)
    exp_section = _build_experience_section(experience or {})

    # Few-shot from pool (P2)
    few_shot_section = _build_few_shot_from_pool()

    return f"""\
Design {n_experiments} experiment configs for the next exploration round.

## Current Pool ({len(pool_families)} families)
{pool_summary}

## Novel Factor Combinations to Try
{cand_text}

## Recent Suggestions
{sugg_text}

{exp_section}

{few_shot_section}

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
        experience: dict | None = None,
    ) -> tuple[list[dict], str]:
        """Try LLM providers in order, fall back to rule-based.

        Splits large requests into batches of 10 to avoid token limits.
        Returns (configs, provider_name).
        """
        self._experience = experience or {}
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
                        pool_families, batch_n, insights, suggestions,
                        skeleton_candidates, experience=self._experience,
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
        """Start the exploration loop in a background thread.

        Auto-detects checkpoint from a previous crash/restart and resumes
        from the last successful step if one exists.
        """
        if self.state == "running":
            return {"error": "Already running", "state": self.state}

        # Check for recovery checkpoint
        checkpoint = self._load_checkpoint()

        # Determine next round number from API
        resp = _api("GET", "lab/exploration-rounds?page=1&size=1")
        items = resp.get("items", [])
        if items:
            self.current_round = max(r.get("round_number", 0) for r in items) + 1
        else:
            total = resp.get("total", 0)
            self.current_round = total + 1

        self._exp_per_round = experiments_per_round  # store for checkpoint

        if checkpoint:
            # Resume from checkpoint
            self.current_round = checkpoint["round_number"]
            self.rounds_total = checkpoint.get("rounds_total", rounds)
            self.rounds_completed = checkpoint.get("rounds_completed", 0)
            self.experiment_ids = checkpoint.get("experiment_ids", [])
            self._source_strategy_id = checkpoint.get("source_strategy_id", source_strategy_id)
            self._exp_per_round = checkpoint.get("experiments_per_round", experiments_per_round)
            self.llm_provider = checkpoint.get("llm_provider", "")

            resume_step = checkpoint.get("current_step", "")
            logger.info("Resuming from checkpoint: round=%d, step=%s", self.current_round, resume_step)

            self.state = "running"
            self.started_at = datetime.now()
            self.last_error = ""
            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._run_loop_resume,
                args=(resume_step, checkpoint),
                daemon=True, name="exploration-engine",
            )
            self._thread.start()
            return {"state": "running", "round_number": self.current_round,
                    "resumed_from": resume_step, "rounds": self.rounds_total}

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

    _STEP_ORDER = [
        "promote_check", "sync_rounds", "load_state", "retry_pending",
        "plan", "submit", "poll", "self_heal",
        "promote_and_rebalance", "update_memory_doc", "sync_pinecone",
        "record", "resolve_problems", "update_experience",
    ]

    def _set_step(self, step: str, detail: str = ""):
        self.current_step = step
        self.step_detail = detail
        logger.info("Step: %s — %s", step, detail)

    # ── Checkpoint persistence ──

    def _save_checkpoint(self, step: str, data: dict | None = None):
        """Save checkpoint after each step completes."""
        checkpoint = {
            "round_number": self.current_round,
            "rounds_total": self.rounds_total,
            "rounds_completed": self.rounds_completed,
            "current_step": step,  # The step that JUST COMPLETED
            "experiment_ids": self.experiment_ids,
            "source_strategy_id": getattr(self, "_source_strategy_id", 0),
            "experiments_per_round": getattr(self, "_exp_per_round", 50),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": datetime.now().isoformat(),
            "llm_provider": self.llm_provider,
            "promoted_count": data.get("promoted", 0) if data else 0,
            "configs": data.get("configs", []) if data else [],
        }
        try:
            _CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to save checkpoint: %s", e)

    def _load_checkpoint(self) -> dict | None:
        """Load checkpoint if exists. Returns None if no checkpoint."""
        if not _CHECKPOINT_PATH.exists():
            return None
        try:
            data = json.loads(_CHECKPOINT_PATH.read_text(encoding="utf-8"))
            logger.info("Loaded checkpoint: round=%d, step=%s, updated=%s",
                        data.get("round_number", 0), data.get("current_step", "?"),
                        data.get("updated_at", "?"))
            return data
        except Exception as e:
            logger.warning("Failed to load checkpoint: %s", e)
            return None

    def _clear_checkpoint(self):
        """Remove checkpoint file after round completes successfully."""
        try:
            if _CHECKPOINT_PATH.exists():
                _CHECKPOINT_PATH.unlink()
                logger.info("Checkpoint cleared")
        except Exception:
            pass

    # ── Main workflow ──

    def _run_loop(self, rounds: int, exp_per_round: int):
        """Main workflow loop."""
        self._exp_per_round = exp_per_round
        try:
            for i in range(rounds):
                if self._stop_event.is_set():
                    break

                if i > 0:
                    self.current_round += 1

                self._execute_round(exp_per_round)
                self.rounds_completed += 1
                self._clear_checkpoint()

            self.state = "idle"
            self._set_step("done", f"Completed {self.rounds_completed}/{self.rounds_total} rounds")

        except Exception as e:
            self.state = "error"
            self.last_error = str(e)
            logger.exception("Exploration engine error: %s", e)

    def _run_loop_resume(self, resume_step: str, checkpoint: dict):
        """Resume a round from a checkpoint, then continue remaining rounds."""
        try:
            # Find where to resume from (the step AFTER the completed one)
            if resume_step in self._STEP_ORDER:
                resume_idx = self._STEP_ORDER.index(resume_step) + 1
            else:
                resume_idx = 0  # unknown step, start from beginning

            logger.info("Resuming round %d from step %d/%d (%s)",
                        self.current_round, resume_idx, len(self._STEP_ORDER),
                        self._STEP_ORDER[resume_idx] if resume_idx < len(self._STEP_ORDER) else "done")

            # Restore state from checkpoint
            exp_ids = checkpoint.get("experiment_ids", [])
            configs = checkpoint.get("configs", [])
            promoted = checkpoint.get("promoted_count", 0)
            exp_per_round = checkpoint.get("experiments_per_round", 50)

            # Execute remaining steps of the interrupted round
            self._execute_round_from(resume_idx, exp_ids, configs, promoted, exp_per_round)

            self.rounds_completed += 1
            self._clear_checkpoint()

            # Continue with remaining rounds
            remaining = self.rounds_total - self.rounds_completed
            if remaining > 0 and not self._stop_event.is_set():
                self.current_round += 1
                self._run_loop(remaining, exp_per_round)
            else:
                self.state = "idle"
                self._set_step("done", f"Completed {self.rounds_completed}/{self.rounds_total} rounds")

        except Exception as e:
            self.state = "error"
            self.last_error = str(e)
            logger.exception("Resume error: %s", e)

    def _execute_round(self, exp_per_round: int):
        """Execute one full round with checkpoint at each step."""
        return self._execute_round_from(0, [], [], 0, exp_per_round)

    def _execute_round_from(self, start_idx: int, exp_ids: list[int],
                            configs: list[dict], promoted: int,
                            exp_per_round: int):
        """Execute round steps starting from start_idx. Each step saves checkpoint."""
        pool_families: list[dict] = []
        round_start = datetime.now()

        # Steps that are safe to skip on failure
        SKIPPABLE = {"promote_check", "sync_rounds", "retry_pending",
                     "update_memory_doc", "sync_pinecone", "resolve_problems",
                     "update_experience"}

        for idx in range(start_idx, len(self._STEP_ORDER)):
            if self._stop_event.is_set():
                break

            step_name = self._STEP_ORDER[idx]

            try:
                if step_name == "promote_check":
                    self._set_step("promote_check", f"Round {self.current_round}")
                    self._step_promote_check()

                elif step_name == "sync_rounds":
                    self._set_step("sync_rounds")
                    self._step_sync_unsynced_rounds()

                elif step_name == "load_state":
                    self._set_step("load_state")
                    pool_families = self._step_load_state()

                elif step_name == "retry_pending":
                    self._set_step("retry_pending")
                    _api("POST", "lab/experiments/retry-pending")

                elif step_name == "plan":
                    self._set_step("plan", f"Designing {exp_per_round} experiments")
                    configs, provider = self._step_plan(pool_families, exp_per_round)
                    self.llm_provider = provider

                elif step_name == "submit":
                    self._set_step("submit", f"Submitting {len(configs)} experiments")
                    exp_ids = self._step_submit(configs)
                    self.experiment_ids = exp_ids

                elif step_name == "poll":
                    self._set_step("poll", f"Waiting for {len(exp_ids)} experiments")
                    self._step_poll(exp_ids)

                elif step_name == "self_heal":
                    self._set_step("self_heal")
                    # Save original poll stats before self-heal overwrites them
                    orig_done = self.strategies_done
                    orig_invalid = self.strategies_invalid
                    orig_stda = self.stda_count
                    orig_best = self.best_score
                    orig_total = self.strategies_total

                    healed_ids = self._step_self_heal(exp_ids, configs)
                    if healed_ids:
                        exp_ids.extend(healed_ids)
                        self._set_step("poll_healed", f"Waiting for {len(healed_ids)} healed experiments")
                        self._step_poll(healed_ids)

                        # Merge: accumulate healed stats on top of original
                        self.strategies_done += orig_done
                        self.strategies_invalid += orig_invalid
                        self.stda_count += orig_stda
                        self.best_score = max(self.best_score, orig_best)
                        self.strategies_total += orig_total
                        logger.info(
                            "Stats merged: done=%d, invalid=%d, StdA+=%d, best=%.4f (original + healed)",
                            self.strategies_done, self.strategies_invalid,
                            self.stda_count, self.best_score,
                        )
                    else:
                        # No heal needed — keep original stats
                        pass

                elif step_name == "promote_and_rebalance":
                    self._set_step("promote_and_rebalance")
                    promoted = self._step_promote_and_rebalance(exp_ids)

                elif step_name == "update_memory_doc":
                    self._set_step("update_memory_doc")
                    self._step_update_memory_doc(promoted)

                elif step_name == "sync_pinecone":
                    self._set_step("sync_pinecone")
                    self._step_sync_pinecone()

                elif step_name == "record":
                    self._set_step("record")
                    self._step_record(exp_ids, promoted)

                elif step_name == "resolve_problems":
                    self._set_step("resolve_problems")
                    self._step_resolve_problems(exp_ids)

                elif step_name == "update_experience":
                    self._set_step("update_experience")
                    self._update_experience(exp_ids)

                # Save checkpoint after EVERY successful step
                self._save_checkpoint(step_name, {
                    "configs": configs if step_name in ("plan", "submit") else [],
                    "promoted": promoted,
                })

            except Exception as e:
                logger.error("Step '%s' failed: %s", step_name, e)
                # Save checkpoint at the PREVIOUS step (the last successful one)
                if idx > 0:
                    self._save_checkpoint(self._STEP_ORDER[idx - 1], {
                        "configs": configs,
                        "promoted": promoted,
                    })

                if step_name in SKIPPABLE:
                    logger.warning("Skipping failed step '%s' and continuing", step_name)
                    continue
                else:
                    # Critical step failed — abort round
                    logger.error("Critical step '%s' failed, aborting round", step_name)
                    raise

        round_elapsed = (datetime.now() - round_start).total_seconds()
        logger.info(
            "Round %d complete in %.0fs — %d StdA+, best=%.4f",
            self.current_round, round_elapsed, self.stda_count, self.best_score,
        )

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
        """Design experiments using LLM planner (P1: experience-guided)."""
        insights = load_historical_insights()
        suggestions = get_latest_round_suggestions()
        candidates = generate_skeleton_candidates(pool_families, max_candidates=n * 2)
        experience = load_experience()

        planner = LLMPlanner()
        configs, provider = planner.plan(
            pool_families, n, insights, suggestions, candidates,
            experience=experience,
        )
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

        # Default exit grid — used for EVERY experiment to maximize coverage
        DEFAULT_EXIT_GRID = [
            {"name": "SL20_TP0.5_MHD2", "stop_loss_pct": -20, "take_profit_pct": 0.5, "max_hold_days": 2},
            {"name": "SL20_TP1_MHD3",   "stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 3},
            {"name": "SL15_TP1.5_MHD3", "stop_loss_pct": -15, "take_profit_pct": 1.5, "max_hold_days": 3},
            {"name": "SL20_TP2_MHD5",   "stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 5},
            {"name": "SL25_TP3_MHD5",   "stop_loss_pct": -25, "take_profit_pct": 3.0, "max_hold_days": 5},
            {"name": "SL20_TP4_MHD7",   "stop_loss_pct": -20, "take_profit_pct": 4.0, "max_hold_days": 7},
        ]

        for cfg in configs:
            label = cfg.get("name", cfg.get("label", cfg.get("name_suffix", "exp")))

            # ── Build buy conditions ──
            # New simplified format: buy_factors = [{"factor": "X", "value": N}]
            # Old format: buy_conditions = [{"field": "X", "operator": "<", ...}]
            buy = copy.deepcopy(BASE_BUY)
            buy_factors = cfg.get("buy_factors", [])
            if buy_factors:
                # New simplified format → convert via _factor_to_condition
                for bf in buy_factors:
                    cond = _factor_to_condition(bf.get("factor", ""), bf.get("value", 0), for_sell=False)
                    if cond:
                        buy.append(cond)
            else:
                # Legacy format: raw conditions
                extra = cfg.get("extra_buy_conditions", cfg.get("buy_conditions", []))
                if isinstance(extra, list):
                    buy.extend(extra)

            # ── Build sell conditions ──
            sell = copy.deepcopy(BASE_SELL)
            sell_factors = cfg.get("sell_factors", [])
            if sell_factors:
                for sf in sell_factors:
                    cond = _factor_to_condition(sf.get("factor", ""), sf.get("value", 0), for_sell=True)
                    if cond:
                        sell.append(cond)
            else:
                extra = cfg.get("extra_sell_conditions", cfg.get("sell_conditions", []))
                if isinstance(extra, list):
                    sell.extend(extra)

            # ── Build exit configs ──
            # Use LLM's exit params if provided, otherwise use default grid
            sl = cfg.get("stop_loss", cfg.get("stop_loss_pct", -20))
            tp = cfg.get("take_profit", cfg.get("take_profit_pct", 2.0))
            mhd = cfg.get("max_hold_days", 5)

            # Always use the full default grid to maximize StdA+ chances
            exit_grid = DEFAULT_EXIT_GRID

            api_exit_configs = []
            for ec in exit_grid:
                api_exit_configs.append({
                    "name_suffix": f"_{label}_{ec['name']}",
                    "exit_config": {
                        "stop_loss_pct": ec["stop_loss_pct"],
                        "take_profit_pct": ec["take_profit_pct"],
                        "max_hold_days": ec["max_hold_days"],
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
        promoted_a = 0  # Standard A (StdA+)
        promoted_b = 0  # Standard B (regime champions)
        LABEL_MAP = {
            "bull": ("[AI-牛市]", "牛市"),
            "bear": ("[AI-熊市]", "熊市"),
            "rang": ("[AI-震荡]", "震荡"),
        }
        regime_best: dict[str, tuple[int, float]] = {}  # key → (sid, pnl)

        for eid in exp_ids:
            detail = _api("GET", f"lab/experiments/{eid}")
            strategies = detail.get("strategies", [])

            for s in strategies:
                if s.get("promoted") or s.get("status") != "done":
                    continue

                sid = s["id"]

                # Standard A: StdA+ promote
                if is_stda_plus(
                    s.get("score", 0),
                    s.get("total_return_pct", 0),
                    s.get("max_drawdown_pct", 100),
                    s.get("total_trades", 0),
                    s.get("win_rate", 0),
                ):
                    result = _promote_strategy(sid)
                    if "error" not in result:
                        promoted_a += 1

                # Standard B: track regime champions (even if already promoted as StdA+)
                ret = s.get("total_return_pct", 0) or 0
                if ret <= 0:
                    continue
                regime_stats = s.get("regime_stats") or {}
                for rname, rdata in regime_stats.items():
                    if not isinstance(rdata, dict):
                        continue
                    pnl = rdata.get("total_pnl", 0) or 0
                    if pnl <= 100:
                        continue
                    for key in LABEL_MAP:
                        if key in rname.lower():
                            if key not in regime_best or pnl > regime_best[key][1]:
                                regime_best[key] = (sid, pnl)
                            break

        # Promote Standard B regime champions
        for key, (sid, pnl) in regime_best.items():
            label, cat = LABEL_MAP[key]
            result = _promote_strategy(sid, label=label, category=cat)
            if "error" not in result:
                promoted_b += 1
            logger.info("Standard B: %s champion S%d (pnl=%.0f) → %s", key, sid, pnl, label)

        logger.info("Promote complete: %d StdA+ (Standard A), %d regime champions (Standard B)",
                    promoted_a, promoted_b)

        # Rebalance pool
        rebalance_result = _api("POST", "strategies/pool/rebalance?max_per_family=15")
        archived = rebalance_result.get("archived_count", 0)
        active = rebalance_result.get("active_strategies", 0)
        families = rebalance_result.get("families_count", 0)
        logger.info("Rebalance: %d families, archived %d, active %d", families, archived, active)

        promoted = promoted_a + promoted_b
        self.step_detail = f"Promoted {promoted_a} StdA+ + {promoted_b} regime, rebalanced ({active} active, {archived} archived)"
        return promoted

    def _step_update_memory_doc(self, promoted: int):
        """Update lab-experiment-analysis.md with round results.

        Updates 4 sections:
        1. Auto-Promote 记录 — cumulative count + this round's stats
        2. 探索状态 — current pool composition
        3. 下一步优先级 — data-driven next suggestions
        4. 历史实验摘要 — round count + strategy count
        """
        if not _INSIGHT_DOC.exists():
            return

        try:
            content = _INSIGHT_DOC.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read insight doc: %s", e)
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rate = self.stda_count / max(1, self.strategies_done) * 100

        # ── 1. Auto-Promote 记录 ──
        # Try to update existing cumulative count
        count_match = re.search(r"累计 \*\*(\d[\d,]*)\+?\*\*", content)
        old_count = int(count_match.group(1).replace(",", "")) if count_match else 0
        new_count = old_count + self.stda_count

        auto_section = (
            f"## Auto-Promote 记录\n\n"
            f"> 累计 **{new_count:,}+** 个StdA+策略已promote。\n"
            f"> **R{self.current_round}** (Engine, {now}): "
            f"**{self.stda_count} StdA+ ({rate:.1f}%)** — "
            f"best={self.best_score:.4f}, promoted={promoted}, "
            f"provider={self.llm_provider}。"
            f"Pool: {self.pool_families}家族, {self.pool_active}活跃\n"
        )

        pattern = r"## Auto-Promote[^\n]*\n\n(?:>.*\n)+"
        if re.search(pattern, content):
            content = re.sub(pattern, auto_section, content)
        else:
            content += "\n" + auto_section

        # ── 2. 下一步优先级 ──
        # Get top-gap families for suggestions
        pool_status = _api("GET", "strategies/pool/status")
        families = pool_status.get("family_summary", [])
        top_gaps = sorted(families, key=lambda f: -f.get("gap", 0))[:5]
        gap_lines = "\n".join(
            f"  - {f['family']} (gap={f['gap']}, avg={f['avg_score']:.4f})"
            for f in top_gaps if f.get("gap", 0) > 0
        )

        next_section = (
            f"## 下一步优先级\n\n"
            f"### R{self.current_round} 自动探索结果 ({now})\n\n"
            f"**{self.stda_count} StdA+ ({rate:.1f}%)**, "
            f"best={self.best_score:.4f}, provider={self.llm_provider}\n\n"
            f"### 下一步优先级 (R{self.current_round + 1}+)\n\n"
            f"1. **填充 top-gap 家族**:\n{gap_lines}\n"
            f"2. **新因子组合探索** — pool gap={self.pool_gap}\n"
            f"3. **优化已满家族** — 尝试新 sell 条件\n"
        )

        pattern2 = r"## 下一步优先级\s*\n[\s\S]*?(?=\n## 历史|$)"
        if re.search(pattern2, content):
            content = re.sub(pattern2, next_section, content)
        else:
            content += "\n" + next_section

        # ── 3. 历史实验摘要 — update round count ──
        hist_match = re.search(r"(\d+)轮探索累计", content)
        if hist_match:
            old_rounds = int(hist_match.group(1))
            content = content.replace(
                f"{old_rounds}轮探索累计",
                f"{self.current_round}轮探索累计"
            )

        try:
            _INSIGHT_DOC.write_text(content, encoding="utf-8")
            logger.info("Updated insight doc: Auto-Promote + 下一步 + 历史摘要")
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
                ["python3", str(script)],
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
        issues: list[str] = []

        # 1. Zombie detection
        self._set_step("resolve_problems", "检测zombie实验")
        zombies = 0
        resp = _api("GET", "lab/experiments?page=1&size=50")
        for exp_item in resp.get("items", []):
            if exp_item.get("status") in ("backtesting", "pending") and exp_item.get("id") not in exp_ids:
                zombies += 1
        if zombies:
            _api("POST", "lab/experiments/retry-pending")
            issues.append(f"Retried {zombies} zombie experiments")
            logger.info("Step 10: retried %d zombie experiments", zombies)

        # 2. Missed promote sweep
        missed = 0
        for eid in exp_ids:
            detail = _api("GET", f"lab/experiments/{eid}")
            for s in detail.get("strategies", []):
                if s.get("status") == "done" and not s.get("promoted"):
                    if is_stda_plus(s.get("score",0), s.get("total_return_pct",0),
                                   s.get("max_drawdown_pct",100), s.get("total_trades",0),
                                   s.get("win_rate",0)):
                        _promote_strategy(s["id"])
                        missed += 1
        if missed:
            issues.append(f"Promoted {missed} missed StdA+ strategies")
            logger.info("Step 10: promoted %d missed strategies", missed)

        # 3. Pool cleanup (remove below-threshold strategies)
        cleanup = _api("POST", "strategies/cleanup")
        deleted = cleanup.get("deleted", cleanup.get("would_delete", 0))
        kept = cleanup.get("kept", cleanup.get("would_keep", 0))
        if deleted:
            issues.append(f"Cleanup: deleted {deleted}, kept {kept}")
            logger.info("Step 10: cleanup deleted %d, kept %d", deleted, kept)

        summary = "; ".join(issues) if issues else "无问题"
        self.step_detail = summary
        logger.info("Step 10 complete: %s", summary)

    def _update_experience(self, exp_ids: list[int]):
        """Update experience.json with results from this round (P3 feedback loop).

        Incrementally updates factor_scores and combo_scores with new data
        from the current round's experiments. Lightweight — only processes
        this round's strategies, not the full history.
        """
        exp_db = load_experience()
        if not exp_db:
            # No experience file yet — skip (run init_experience.py first)
            logger.info("No experience.json found, skipping P3 update")
            return

        factor_scores = exp_db.get("factor_scores", {})
        combo_scores = exp_db.get("combo_scores", {})

        base_fields = frozenset({"RSI", "ATR", "close", "volume", "high", "low", "open"})
        updated_factors = 0
        updated_combos = 0

        for eid in exp_ids:
            exp = _api("GET", f"lab/experiments/{eid}")
            for s in exp.get("strategies", []):
                if s.get("status") != "done":
                    continue

                buy_conds = s.get("buy_conditions", [])
                if not isinstance(buy_conds, list):
                    continue

                # Extract extra factors
                factors: list[tuple[str, float]] = []
                for cond in buy_conds:
                    field = cond.get("field", "")
                    if not field or field in base_fields:
                        continue
                    cv = cond.get("compare_value")
                    if cv is not None and isinstance(cv, (int, float)):
                        factors.append((field, float(cv)))

                if not factors:
                    continue

                stda = is_stda_plus(
                    s.get("score", 0),
                    s.get("total_return_pct", 0),
                    s.get("max_drawdown_pct", 100),
                    s.get("total_trades", 0),
                    s.get("win_rate", 0),
                )
                score = s.get("score", 0)

                # Update factor_scores
                for field, cv in factors:
                    if field not in factor_scores:
                        factor_scores[field] = {
                            "total": 0,
                            "stda_count": 0,
                            "stda_rate_pct": 0.0,
                            "best_score": 0.0,
                            "optimal_range": None,
                        }
                    fs = factor_scores[field]
                    fs["total"] += 1
                    if stda:
                        fs["stda_count"] += 1
                    if score > fs.get("best_score", 0):
                        fs["best_score"] = round(score, 4)
                    # Recompute rate
                    fs["stda_rate_pct"] = round(
                        fs["stda_count"] / max(fs["total"], 1) * 100, 1
                    )
                    updated_factors += 1

                # Update combo_scores
                factor_names = sorted(set(f[0] for f in factors))
                if factor_names:
                    combo_key = "+".join(factor_names)
                    if combo_key not in combo_scores:
                        combo_scores[combo_key] = {
                            "total": 0,
                            "stda_count": 0,
                            "stda_rate_pct": 0.0,
                            "best_score": 0.0,
                        }
                    cs = combo_scores[combo_key]
                    cs["total"] += 1
                    if stda:
                        cs["stda_count"] += 1
                    if score > cs.get("best_score", 0):
                        cs["best_score"] = round(score, 4)
                    cs["stda_rate_pct"] = round(
                        cs["stda_count"] / max(cs["total"], 1) * 100, 1
                    )
                    updated_combos += 1

        if updated_factors == 0 and updated_combos == 0:
            return

        # Update meta
        meta = exp_db.get("meta", {})
        meta["last_updated"] = datetime.now().isoformat()
        meta["last_round"] = self.current_round
        exp_db["meta"] = meta
        exp_db["factor_scores"] = factor_scores
        exp_db["combo_scores"] = combo_scores

        try:
            _EXPERIENCE_PATH.write_text(
                json.dumps(exp_db, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "P3: Updated experience.json — %d factor updates, %d combo updates",
                updated_factors, updated_combos,
            )
        except Exception as e:
            logger.error("P3: Failed to write experience.json: %s", e)
