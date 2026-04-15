#!/usr/bin/env python3
"""Initialize experience.json from historical experiment data.

Scans all ExperimentStrategy records in the database, computes:
- factor_scores: per-factor success rate, optimal threshold range, proven combos
- combo_scores: per-combination success rate and best score
- exit_patterns: proven exit config patterns from top strategies
- top_templates: actual buy_conditions from top 20 StdA+ strategies (for few-shot)
"""

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/Users/allenqiang/stockagent")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

from api.models.base import SessionLocal
from api.models.ai_lab import ExperimentStrategy

# StdA+ criteria
STDA_SCORE = 0.80
STDA_RETURN = 60.0
STDA_DD = 18.0
STDA_TRADES = 50
STDA_WR = 60.0

# Base factors to skip when extracting "extra" buy factors
BASE_FIELDS = frozenset({"RSI", "ATR", "close", "volume", "high", "low", "open"})

OUTPUT_PATH = Path(__file__).parent.parent / "config" / "experience.json"


def is_stda_plus(s: ExperimentStrategy) -> bool:
    return (
        (s.score or 0) >= STDA_SCORE
        and (s.total_return_pct or 0) > STDA_RETURN
        and abs(s.max_drawdown_pct or 100) < STDA_DD
        and (s.total_trades or 0) >= STDA_TRADES
        and (s.win_rate or 0) > STDA_WR
    )


def extract_factors(buy_conditions: list[dict]) -> list[tuple[str, str, float]]:
    """Extract extra factors from buy_conditions.

    Returns list of (field, operator, compare_value) tuples.
    Skips base fields (RSI, ATR, close, etc.).
    """
    factors = []
    if not isinstance(buy_conditions, list):
        return factors
    for cond in buy_conditions:
        field = cond.get("field", "")
        if not field or field in BASE_FIELDS:
            continue
        op = cond.get("operator", "")
        cv = cond.get("compare_value")
        if cv is not None and isinstance(cv, (int, float)):
            factors.append((field, op, float(cv)))
    return factors


def main():
    session = SessionLocal()
    try:
        log.info("Querying all done ExperimentStrategy records...")
        strategies = (
            session.query(ExperimentStrategy)
            .filter(ExperimentStrategy.status == "done")
            .all()
        )
        log.info("Found %d done strategies", len(strategies))

        # ── Per-factor tracking ──
        # factor_name -> {total, stda_count, best_score, thresholds_all, thresholds_stda}
        factor_stats: dict[str, dict] = defaultdict(lambda: {
            "total": 0,
            "stda_count": 0,
            "best_score": 0.0,
            "thresholds_all": [],
            "thresholds_stda": [],
        })

        # ── Per-combo tracking ──
        # combo_key (sorted factor names joined by +) -> {total, stda_count, best_score}
        combo_stats: dict[str, dict] = defaultdict(lambda: {
            "total": 0,
            "stda_count": 0,
            "best_score": 0.0,
        })

        # ── Exit config tracking for top strategies ──
        exit_patterns: list[dict] = []

        # ── Top StdA+ strategies for templates ──
        stda_strategies: list[tuple[float, dict, dict]] = []  # (score, buy_conditions, exit_config)

        for s in strategies:
            buy_conds = s.buy_conditions or []
            factors = extract_factors(buy_conds)

            if not factors:
                continue  # No extra factors, skip

            stda = is_stda_plus(s)
            score = s.score or 0

            # Update factor stats
            for field, op, cv in factors:
                fs = factor_stats[field]
                fs["total"] += 1
                fs["thresholds_all"].append(cv)
                if stda:
                    fs["stda_count"] += 1
                    fs["thresholds_stda"].append(cv)
                if score > fs["best_score"]:
                    fs["best_score"] = score

            # Update combo stats
            factor_names = sorted(set(f[0] for f in factors))
            if len(factor_names) >= 1:
                combo_key = "+".join(factor_names)
                cs = combo_stats[combo_key]
                cs["total"] += 1
                if stda:
                    cs["stda_count"] += 1
                if score > cs["best_score"]:
                    cs["best_score"] = score

            # Track StdA+ for templates
            if stda:
                stda_strategies.append((score, buy_conds, s.exit_config or {}))

        # ── Compute final factor_scores ──
        factor_scores: dict[str, dict] = {}
        for name, fs in factor_stats.items():
            rate = fs["stda_count"] / max(fs["total"], 1) * 100
            optimal_range = None
            if fs["thresholds_stda"] and len(fs["thresholds_stda"]) >= 2:
                sorted_vals = sorted(fs["thresholds_stda"])
                n = len(sorted_vals)
                p10_idx = max(0, int(n * 0.1))
                p90_idx = min(n - 1, int(n * 0.9))
                optimal_range = [
                    round(sorted_vals[p10_idx], 6),
                    round(sorted_vals[p90_idx], 6),
                ]
            elif fs["thresholds_stda"]:
                # Only one StdA+ threshold — use it as both bounds
                val = fs["thresholds_stda"][0]
                optimal_range = [round(val, 6), round(val, 6)]

            factor_scores[name] = {
                "total": fs["total"],
                "stda_count": fs["stda_count"],
                "stda_rate_pct": round(rate, 1),
                "best_score": round(fs["best_score"], 4),
                "optimal_range": optimal_range,
            }

        # ── Compute final combo_scores ──
        combo_scores: dict[str, dict] = {}
        for combo_key, cs in combo_stats.items():
            rate = cs["stda_count"] / max(cs["total"], 1) * 100
            combo_scores[combo_key] = {
                "total": cs["total"],
                "stda_count": cs["stda_count"],
                "stda_rate_pct": round(rate, 1),
                "best_score": round(cs["best_score"], 4),
            }

        # ── Top templates (top 20 StdA+ by score) ──
        stda_strategies.sort(key=lambda x: -x[0])
        top_templates = []
        for score, buy_conds, exit_cfg in stda_strategies[:20]:
            top_templates.append({
                "score": round(score, 4),
                "buy_conditions": buy_conds,
                "exit_config": exit_cfg,
            })

        # ── Exit patterns from top 50 StdA+ ──
        exit_counter: dict[str, int] = defaultdict(int)
        for score, buy_conds, exit_cfg in stda_strategies[:50]:
            if exit_cfg:
                key = json.dumps(exit_cfg, sort_keys=True)
                exit_counter[key] += 1
        exit_patterns = []
        for cfg_str, count in sorted(exit_counter.items(), key=lambda x: -x[1])[:10]:
            exit_patterns.append({
                "config": json.loads(cfg_str),
                "count": count,
            })

        # ── Assemble and write ──
        experience = {
            "meta": {
                "generated_at": __import__("datetime").datetime.now().isoformat(),
                "total_strategies_scanned": len(strategies),
                "total_with_extra_factors": sum(1 for fs in factor_stats.values() if fs["total"] > 0),
                "total_stda_plus": len(stda_strategies),
            },
            "factor_scores": dict(sorted(factor_scores.items(), key=lambda x: -x[1]["stda_rate_pct"])),
            "combo_scores": dict(sorted(combo_scores.items(), key=lambda x: -x[1]["stda_rate_pct"])),
            "exit_patterns": exit_patterns,
            "top_templates": top_templates,
        }

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(experience, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Wrote %s", OUTPUT_PATH)
        log.info("  Factors: %d", len(factor_scores))
        log.info("  Combos: %d", len(combo_scores))
        log.info("  Templates: %d", len(top_templates))
        log.info("  Exit patterns: %d", len(exit_patterns))
        log.info("  Total StdA+: %d", len(stda_strategies))

    finally:
        session.close()


if __name__ == "__main__":
    main()
