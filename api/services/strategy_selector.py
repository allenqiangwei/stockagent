"""Strategy family summary builder for AI-driven strategy selection.

Groups strategy variants into families by stripping parameter suffixes,
picks the best-scoring variant per family, and provides helpers for
selecting strategies by family name.
"""

import logging
import re
from collections import defaultdict

from sqlalchemy.orm import Session

from api.models.strategy import Strategy

logger = logging.getLogger(__name__)

# Pattern to strip [AI...] prefix
_AI_PREFIX_RE = re.compile(r"^\[AI[^\]]*\]\s*")

# Parameter suffixes to strip (order matters: longer/compound first)
_PARAM_SUFFIX_RE = re.compile(
    r"(_SL\d+|_TP\d+|_MHD\d+|_调参|_紧止损|_快止盈|_全紧|_快轮换|_v\d+|_紧止损\d*pct|_快止盈\d*pct)"
)


def _get_family_name(strategy_name: str) -> str:
    """Strip [AI...] prefix and parameter suffixes to get the family base name.

    Examples:
        '[AI] PSAR趋势动量_保守版A_调参_SL10_TP14_v1505' -> 'PSAR趋势动量_保守版A'
        '[AI-牛市] KDJ+ATR动态止损_中性版C' -> 'KDJ+ATR动态止损_中性版C'
        'KDJ金叉_中性版A_紧止损' -> 'KDJ金叉_中性版A'
    """
    name = _AI_PREFIX_RE.sub("", strategy_name).strip()
    # Repeatedly strip parameter suffixes from the end
    while True:
        new_name = _PARAM_SUFFIX_RE.sub("", name)
        if new_name == name:
            break
        name = new_name
    return name


def build_family_summary(db: Session) -> list[dict]:
    """Load all enabled strategies with backtest_summary, group by family,
    pick highest-score variant per family.

    Returns list of dicts sorted by score descending:
        {family, best_id, variants, score, total_return_pct, max_drawdown_pct,
         bull_avg_pnl, bear_avg_pnl, range_avg_pnl}
    """
    strategies = (
        db.query(Strategy)
        .filter(Strategy.enabled == True, Strategy.backtest_summary != None)  # noqa: E712
        .all()
    )

    families: dict[str, list[Strategy]] = defaultdict(list)
    for s in strategies:
        family = _get_family_name(s.name)
        families[family].append(s)

    summaries = []
    for family, variants in families.items():
        # Pick the variant with the highest score
        best = max(variants, key=lambda s: (s.backtest_summary or {}).get("score", 0))
        bs = best.backtest_summary or {}
        regime = bs.get("regime_stats", {})

        summaries.append(
            {
                "family": family,
                "best_id": best.id,
                "variants": len(variants),
                "score": bs.get("score", 0),
                "total_return_pct": bs.get("total_return_pct", 0),
                "max_drawdown_pct": bs.get("max_drawdown_pct", 0),
                "bull_avg_pnl": regime.get("trending_bull", {}).get("avg_pnl", 0),
                "bear_avg_pnl": regime.get("trending_bear", {}).get("avg_pnl", 0),
                "range_avg_pnl": regime.get("ranging", {}).get("avg_pnl", 0),
            }
        )

    summaries.sort(key=lambda x: x["score"], reverse=True)
    return summaries


def format_family_table(summaries: list[dict]) -> str:
    """Format family summaries as a markdown-style text table.

    Headers: 族名 | score | 收益 | 回撤 | 牛市 | 熊市 | 震荡 | 变体
    """
    lines = []
    header = f"{'族名':<40s} | {'score':>6s} | {'收益':>7s} | {'回撤':>7s} | {'牛市':>6s} | {'熊市':>6s} | {'震荡':>6s} | {'变体':>4s}"
    lines.append(header)
    lines.append("-" * len(header))

    for s in summaries:
        line = (
            f"{s['family']:<40s} | "
            f"{s['score']:>6.4f} | "
            f"{s['total_return_pct']:>6.1f}% | "
            f"{s['max_drawdown_pct']:>6.1f}% | "
            f"{s['bull_avg_pnl']:>6.2f} | "
            f"{s['bear_avg_pnl']:>6.2f} | "
            f"{s['range_avg_pnl']:>6.2f} | "
            f"{s['variants']:>4d}"
        )
        lines.append(line)

    return "\n".join(lines)


def select_strategies_by_families(db: Session, family_names: list[str]) -> list[int]:
    """Map family names to their best strategy IDs (one per family).

    Logs warning for unknown family names.
    Returns list of strategy IDs.
    """
    summaries = build_family_summary(db)
    family_map = {s["family"]: s["best_id"] for s in summaries}

    ids = []
    for name in family_names:
        if name in family_map:
            ids.append(family_map[name])
        else:
            logger.warning("Unknown strategy family: %s", name)

    return ids


def get_fallback_strategy_ids(db: Session, top_n: int = 5) -> list[int]:
    """Return best_id from top N families by score."""
    summaries = build_family_summary(db)
    return [s["best_id"] for s in summaries[:top_n]]
