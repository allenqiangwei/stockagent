"""Factor registration system — single source of truth for all indicators/factors."""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FactorDef:
    """Complete definition of a factor."""
    name: str                              # "MOM"
    label: str                             # "动量"
    sub_fields: list[tuple[str, str]]      # [("MOM", "动量%")]
    params: dict[str, dict[str, Any]]      # {"period": {"label": "周期", "default": 20, "type": "int"}}
    compute_fn: Callable                   # (df, params_dict) -> DataFrame
    field_ranges: dict[str, tuple] = field(default_factory=dict)  # {"MOM": (-100, 500)}
    category: str = ""                     # "price_action"


# ── Global registry ──────────────────────────────────────

FACTORS: dict[str, FactorDef] = {}


def register_factor(
    name: str,
    label: str,
    sub_fields: list[tuple[str, str]],
    params: dict[str, dict[str, Any]],
    field_ranges: dict[str, tuple] | None = None,
    category: str = "",
):
    """Decorator to register a factor compute function."""
    def decorator(fn: Callable) -> Callable:
        FACTORS[name] = FactorDef(
            name=name,
            label=label,
            sub_fields=sub_fields,
            params=params,
            compute_fn=fn,
            field_ranges=field_ranges or {},
            category=category,
        )
        return fn
    return decorator


# ── Public API ───────────────────────────────────────────

def get_factor(name: str) -> Optional[FactorDef]:
    return FACTORS.get(name)


def get_all_factors() -> dict[str, FactorDef]:
    return FACTORS


def compute_factor(df: pd.DataFrame, name: str, params: dict | None = None) -> pd.DataFrame:
    """Compute a factor by name. Merges user params with defaults."""
    factor = FACTORS.get(name)
    if factor is None:
        raise ValueError(f"Unknown factor: {name}")

    defaults = {k: v["default"] for k, v in factor.params.items()}
    effective = dict(defaults)
    if params:
        effective.update(params)

    return factor.compute_fn(df, effective)


def get_all_field_ranges() -> dict[str, tuple]:
    """Aggregate field_ranges from all registered factors."""
    ranges = {}
    for f in FACTORS.values():
        ranges.update(f.field_ranges)
    return ranges


def get_all_sub_fields() -> list[str]:
    """Get all registered sub-field names."""
    fields = []
    for f in FACTORS.values():
        for sub_field, _ in f.sub_fields:
            fields.append(sub_field)
    return fields


def get_factor_docs() -> str:
    """Build documentation string of all factors for AI prompts."""
    lines = []
    for name, f in sorted(FACTORS.items()):
        fields_str = ", ".join(sf for sf, _ in f.sub_fields)
        params_str = ", ".join(f"{k}={v.get('default', '?')}" for k, v in f.params.items())
        lines.append(f"- {name} ({f.label}): fields=[{fields_str}] params=[{params_str}]")
    return "\n".join(lines)
