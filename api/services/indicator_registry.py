"""Thin compatibility proxy — delegates to src.factors.registry.

All existing import paths and function signatures are preserved.
EXTENDED_INDICATORS excludes the 9 builtin factors to match prior behavior.
"""

import logging
from typing import Any

import pandas as pd

# Side-effect import: triggers auto-discovery of ALL factor modules
# (builtin, oscillator, trend, volatility, volume, price_action, liquidity, sentiment)
import src.factors  # noqa: F401

from src.factors.registry import (
    FACTORS,
    compute_factor,
    get_all_sub_fields,
    get_factor_docs,
)

logger = logging.getLogger(__name__)

# ── Builtin names — excluded from EXTENDED_INDICATORS ─────

_BUILTIN_NAMES = {"MA", "EMA", "RSI", "MACD", "KDJ", "ADX", "OBV", "ATR", "VOLUME_MA"}

# ── Build compatibility dicts (only extended factors) ─────

EXTENDED_INDICATORS: dict[str, dict[str, Any]] = {}
for _name, _f in FACTORS.items():
    if _name not in _BUILTIN_NAMES:
        EXTENDED_INDICATORS[_name] = {
            "label": _f.label,
            "sub_fields": _f.sub_fields,
            "params": {k: dict(v) for k, v in _f.params.items()},
        }

_COMPUTE_FUNCTIONS: dict[str, callable] = {
    name: f.compute_fn for name, f in FACTORS.items() if name not in _BUILTIN_NAMES
}


# ── Column name resolution for extended indicators ────────

def resolve_extended_column(field: str, params: dict | None = None) -> str | None:
    """Resolve an extended indicator field + params to a DataFrame column name.

    Returns None if not an extended indicator.
    """
    group = get_extended_field_group(field)
    if group is None:
        return None

    meta = EXTENDED_INDICATORS[group]
    if not meta["params"]:
        # No params -> column name is just the field name (ADI, NVI, VPT, etc.)
        return field

    defaults = {k: v["default"] for k, v in meta["params"].items()}
    effective = dict(defaults)
    if params:
        effective.update(params)

    # Build suffix from all param values in definition order
    suffix = "_" + "_".join(str(effective[k]) for k in meta["params"])
    return f"{field}{suffix}"


def get_extended_field_group(field: str) -> str | None:
    """Find the extended indicator group for a given field name."""
    for group_name, meta in EXTENDED_INDICATORS.items():
        for sub_field, _ in meta["sub_fields"]:
            if sub_field == field:
                return group_name
    return None


def compute_extended_indicator(
    df: pd.DataFrame, group: str, params: dict | None = None,
) -> pd.DataFrame:
    """Compute an extended indicator and return its columns as a DataFrame."""
    if group not in _COMPUTE_FUNCTIONS:
        raise ValueError(f"No compute function for extended indicator: {group}")

    meta = EXTENDED_INDICATORS[group]
    defaults = {k: v["default"] for k, v in meta["params"].items()}
    effective = dict(defaults)
    if params:
        effective.update(params)

    return _COMPUTE_FUNCTIONS[group](df, effective)


def is_extended_indicator(field: str) -> bool:
    """Check if a field belongs to an extended indicator."""
    return get_extended_field_group(field) is not None


def get_all_fields() -> list[str]:
    """Get all available field names (built-in + extended)."""
    from src.signals.rule_engine import INDICATOR_GROUPS

    fields = []
    for group_def in INDICATOR_GROUPS.values():
        for sub_field, _ in group_def["sub_fields"]:
            fields.append(sub_field)
    for meta in EXTENDED_INDICATORS.values():
        for sub_field, _ in meta["sub_fields"]:
            fields.append(sub_field)
    return fields


def get_all_indicator_docs() -> str:
    """Build a documentation string of all indicators for AI prompts."""
    from src.signals.rule_engine import INDICATOR_GROUPS

    lines = []
    seen = set()

    # Built-in indicators
    for group_name, group_def in INDICATOR_GROUPS.items():
        seen.add(group_name)
        fields_str = ", ".join(f'"{sf}"' for sf, _ in group_def["sub_fields"])
        params_str = ", ".join(
            f'{k}(默认{v["default"]})'
            for k, v in group_def["params"].items()
        ) if group_def["params"] else "无参数"
        lines.append(f"- **{group_def['label']}** ({group_name}): 字段=[{fields_str}], 参数=[{params_str}]")

    # Extended indicators not in INDICATOR_GROUPS
    for group_name, meta in EXTENDED_INDICATORS.items():
        if group_name in seen:
            continue
        fields_str = ", ".join(f'"{sf}"' for sf, _ in meta["sub_fields"])
        params_str = ", ".join(
            f'{k}(默认{v["default"]})'
            for k, v in meta["params"].items()
        ) if meta["params"] else "无参数"
        lines.append(f"- **{meta['label']}** ({group_name}): 字段=[{fields_str}], 参数=[{params_str}]")

    # Multi-timeframe support
    lines.append("")
    lines.append("## 多周期指标 (Multi-Timeframe)")
    lines.append("以上所有指标均可加 W_ (周线) 或 M_ (月线) 前缀，在更大周期上计算后向前填充到日线。")
    lines.append("- 周线指标: 字段名前加 `W_`，如 `W_RSI`(周线RSI)、`W_EMA`(周线EMA)、`W_ATR`(周线ATR)")
    lines.append("- 月线指标: 字段名前加 `M_`，如 `M_RSI`(月线RSI)、`M_EMA`(月线EMA)")
    lines.append("- 参数格式与日线完全相同，如 {\"field\": \"W_RSI\", \"params\": {\"period\": 14}, ...}")
    lines.append("- 可与日线指标混合使用，实现多周期过滤（如：日线RSI超卖 + 周线趋势向上）")
    lines.append("- 周线OHLCV也可直接引用: W_close, W_high, W_low, W_open")
    lines.append("- 注意: 周线指标需要约70个交易日预热, 月线需要更长, 建议优先使用周线")

    # News sentiment
    lines.append("")
    lines.append("## 新闻情绪指标 (News Sentiment)")
    lines.append("基于个股关联新闻的滚动情绪评分，取值 [-1.0, +1.0]（+1全正面, -1全负面, 0中性/无新闻）")
    lines.append("- `NEWS_SENTIMENT_3D`: 近3日新闻情绪")
    lines.append("- `NEWS_SENTIMENT_7D`: 近7日新闻情绪")
    lines.append("- 无参数，无需 W_/M_ 前缀")
    lines.append("- 仅在实盘信号生成时有效，回测中默认为NaN（条件不触发）")
    lines.append("- 示例: {\"field\": \"NEWS_SENTIMENT_3D\", \"operator\": \">\", \"compare_type\": \"value\", \"compare_value\": 0.3}")

    return "\n".join(lines)


def register_extended_indicators():
    """Register all extended indicators into the rule engine's INDICATOR_GROUPS.

    Call this at startup so validate_rule() and resolve_column_name() work
    for extended indicators too.
    """
    from src.signals.rule_engine import INDICATOR_GROUPS

    for group_name, meta in EXTENDED_INDICATORS.items():
        if group_name not in INDICATOR_GROUPS:
            INDICATOR_GROUPS[group_name] = meta
            logger.info("Registered extended indicator: %s", group_name)
