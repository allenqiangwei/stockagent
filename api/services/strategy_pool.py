"""Strategy Pool Manager — groups strategies by signal fingerprint, keeps top-N per family."""

import hashlib
import json
import logging
from datetime import datetime
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.strategy import Strategy

logger = logging.getLogger(__name__)


def _canonical_conditions(conditions: list[dict]) -> str:
    """Stable string representation of conditions, sorted for consistent hashing."""
    if not conditions:
        return "[]"

    def sort_key(c: dict) -> tuple:
        return (
            c.get("field", ""),
            json.dumps(c.get("params", {}), sort_keys=True),
            c.get("operator", ""),
            c.get("compare_type", ""),
            str(c.get("compare_value", "")),
            str(c.get("consecutive_n", "")),
            c.get("direction", ""),
            str(c.get("lookback_n", "")),
        )

    sorted_conds = sorted(conditions, key=sort_key)
    return json.dumps(sorted_conds, sort_keys=True, ensure_ascii=False)


def compute_fingerprint(buy_conditions: list[dict], sell_conditions: list[dict]) -> str:
    """SHA-256 hash of canonical buy+sell conditions."""
    canonical = _canonical_conditions(buy_conditions or []) + "|" + _canonical_conditions(sell_conditions or [])
    return hashlib.sha256(canonical.encode()).hexdigest()


class StrategyPoolManager:
    """Manages the strategy pool by grouping strategies into signal families."""

    def __init__(self, db: Session):
        self.db = db

    def compute_all_fingerprints(self) -> int:
        """Compute signal_fingerprint for all strategies that don't have one. Returns count updated."""
        strategies = self.db.query(Strategy).filter(
            Strategy.signal_fingerprint.is_(None)
        ).all()

        count = 0
        for s in strategies:
            pf = s.portfolio_config or {}
            if pf.get("type") == "combo":
                continue
            s.signal_fingerprint = compute_fingerprint(s.buy_conditions or [], s.sell_conditions or [])
            count += 1

        if count:
            self.db.commit()
            logger.info("Computed fingerprints for %d strategies", count)
        return count

    def rebalance(self, max_per_family: int = 15, dry_run: bool = False) -> dict:
        """Rebalance pool: keep top max_per_family per family, archive rest."""
        self.compute_all_fingerprints()

        all_strategies = self.db.query(Strategy).filter(
            Strategy.signal_fingerprint.isnot(None)
        ).all()

        families: dict[str, list[Strategy]] = defaultdict(list)
        for s in all_strategies:
            families[s.signal_fingerprint].append(s)

        archived_count = 0
        activated_count = 0
        details = []

        for fp, members in families.items():
            members.sort(key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0, reverse=True)
            selected = self._select_diverse_top(members, max_per_family)
            selected_ids = {s.id for s in selected}

            family_archived = 0
            family_activated = 0

            for rank, s in enumerate(members):
                if s.id in selected_ids:
                    new_role = "champion" if rank == 0 else "active"
                    was_archived = s.archived_at is not None
                    if not dry_run:
                        s.family_rank = rank + 1
                        s.family_role = new_role
                        s.archived_at = None
                        s.enabled = True
                    if was_archived:
                        family_activated += 1
                        activated_count += 1
                else:
                    was_active = s.archived_at is None
                    if not dry_run:
                        s.family_rank = None
                        s.family_role = "archive"
                        if s.archived_at is None:
                            s.archived_at = datetime.now()
                        s.enabled = False
                    if was_active:
                        family_archived += 1
                        archived_count += 1

            details.append({
                "fingerprint": fp[:16],
                "champion": members[0].name[:60] if members else "?",
                "total": len(members),
                "active": len(selected),
                "archived_this_run": family_archived,
            })

        if not dry_run:
            self.db.commit()

        active_total = self.db.query(Strategy).filter(
            Strategy.archived_at.is_(None),
            Strategy.signal_fingerprint.isnot(None),
        ).count()

        return {
            "dry_run": dry_run,
            "families_count": len(families),
            "archived_count": archived_count,
            "activated_count": activated_count,
            "active_strategies": active_total,
            "total_strategies": len(all_strategies),
            "details": sorted(details, key=lambda d: -d["total"]),
        }

    def _select_diverse_top(self, members: list[Strategy], max_count: int) -> list[Strategy]:
        """Select top members with diverse SL/TP/MHD params. Members pre-sorted by score desc."""
        selected: list[Strategy] = []
        seen_params: set[tuple] = set()

        for s in members:
            if len(selected) >= max_count:
                break
            ec = s.exit_config or {}
            param_key = (ec.get("stop_loss_pct"), ec.get("take_profit_pct"), ec.get("max_hold_days"))
            if param_key in seen_params:
                continue
            seen_params.add(param_key)
            selected.append(s)

        return selected

    def daily_health_check(self) -> dict:
        """Lightweight check before signal generation."""
        computed = self.compute_all_fingerprints()

        family_sizes = (
            self.db.query(Strategy.signal_fingerprint, func.count(Strategy.id))
            .filter(Strategy.archived_at.is_(None), Strategy.signal_fingerprint.isnot(None))
            .group_by(Strategy.signal_fingerprint)
            .all()
        )

        oversized = [(fp, cnt) for fp, cnt in family_sizes if cnt > 15]
        active_count = sum(cnt for _, cnt in family_sizes)

        return {
            "fingerprints_computed": computed,
            "active_strategies": active_count,
            "family_count": len(family_sizes),
            "oversized_families": len(oversized),
            "healthy": len(oversized) == 0,
        }

    def get_pool_status(self) -> dict:
        """Comprehensive pool status for API."""
        total = self.db.query(Strategy).count()
        active = self.db.query(Strategy).filter(Strategy.archived_at.is_(None)).count()

        families_raw = self.db.query(Strategy).filter(Strategy.signal_fingerprint.isnot(None)).all()
        families: dict[str, list[Strategy]] = defaultdict(list)
        for s in families_raw:
            families[s.signal_fingerprint].append(s)

        families_summary = []
        regime_map: dict[str, dict] = defaultdict(lambda: {"families": set(), "strategies": 0})

        for fp, members in sorted(families.items(), key=lambda x: -len(x[1])):
            active_members = [m for m in members if m.archived_at is None]
            archived_members = [m for m in members if m.archived_at is not None]
            champion = max(active_members, key=lambda s: (s.backtest_summary or {}).get("score", 0), default=None) if active_members else None

            regimes = []
            if champion and champion.backtest_summary:
                rs = champion.backtest_summary.get("regime_stats", {}) or {}
                for rname, rdata in rs.items():
                    if (rdata or {}).get("total_pnl", 0) > 0:
                        regimes.append(rname)

            exit_params = [m.exit_config or {} for m in active_members]
            sl_vals = [abs(ec.get("stop_loss_pct", 0) or 0) for ec in exit_params if ec.get("stop_loss_pct")]
            tp_vals = [ec.get("take_profit_pct", 0) or 0 for ec in exit_params if ec.get("take_profit_pct")]
            mhd_vals = [ec.get("max_hold_days", 0) or 0 for ec in exit_params if ec.get("max_hold_days")]

            fs = {
                "fingerprint": fp,
                "representative_name": champion.name[:80] if champion else members[0].name[:80],
                "active_count": len(active_members),
                "archived_count": len(archived_members),
                "champion_score": (champion.backtest_summary or {}).get("score", 0) if champion else 0,
                "champion_id": champion.id if champion else 0,
                "avg_score": sum((m.backtest_summary or {}).get("score", 0) or 0 for m in active_members) / max(len(active_members), 1),
                "regime_coverage": regimes,
                "exit_param_range": {
                    "sl": [min(sl_vals, default=0), max(sl_vals, default=0)],
                    "tp": [min(tp_vals, default=0), max(tp_vals, default=0)],
                    "mhd": [min(mhd_vals, default=0), max(mhd_vals, default=0)],
                },
            }
            families_summary.append(fs)

            for regime in regimes:
                regime_map[regime]["families"].add(fp)
                regime_map[regime]["strategies"] += len(active_members)

        regime_coverage = {
            k: {"families": len(v["families"]), "strategies": v["strategies"]}
            for k, v in regime_map.items()
        }

        return {
            "total_strategies": total,
            "active_strategies": active,
            "archived_strategies": total - active,
            "family_count": len(families),
            "families_summary": sorted(families_summary, key=lambda f: -f["champion_score"]),
            "regime_coverage": regime_coverage,
            "last_rebalance_at": None,
            "signal_eval_reduction": f"{total} → {len(families)} unique evaluations per stock",
        }
