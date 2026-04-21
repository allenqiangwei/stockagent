"""Strategy Pool Manager — groups strategies by signal fingerprint, keeps top-N per family."""

import hashlib
import json
import logging
import re
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


def _extract_skeleton(name: str, buy_conditions: list[dict] | None = None,
                      sell_conditions: list[dict] | None = None) -> str:
    """Extract strategy skeleton from buy/sell condition structure.

    Derives skeleton from the actual indicator fields and compare_types used,
    rather than the strategy name (which accumulates clone-chain history).

    e.g. buy=[RSI:between, ATR:lt, close:lookback_min, close:lookback_max, ATR:lookback_max]
         sell=[close:lookback_min]
         → 'ATR:lkmax|ATR:lt|RSI:btw|close:lkmax|close:lkmin||close:lkmin'

    Falls back to name-based extraction when conditions are not available.
    """
    if buy_conditions or sell_conditions:
        return _skeleton_from_conditions(buy_conditions or [], sell_conditions or [])

    # Fallback: name-based extraction for legacy strategies without conditions
    skeleton = re.sub(r"\d+\.\d+|\d+", "N", name or "")
    return skeleton[:80]


# Abbreviation map for compare_type to keep skeleton concise
_CT_ABBREV = {
    "value": "val", "field": "fld", "between": "btw",
    "lookback_min": "lkmin", "lookback_max": "lkmax",
    "lookback_value": "lkval", "consecutive": "cons",
    "pct_change": "pchg", "pct_diff": "pdif",
    "gt": "gt", "lt": "lt", "gte": "gte", "lte": "lte",
}


def _cond_key(c: dict) -> str:
    """Stable key for a single condition: 'field:compare_type_abbrev'."""
    field = c.get("field", "?")
    # Strip numeric params from field name (e.g. RSI_14 → RSI, ATR_14 → ATR)
    field = re.sub(r"_\d+.*$", "", field)
    ct = c.get("compare_type", "val")
    ct_short = _CT_ABBREV.get(ct, ct[:4])
    return f"{field}:{ct_short}"


def _skeleton_from_conditions(buy_conds: list[dict], sell_conds: list[dict]) -> str:
    """Build skeleton string from condition fields and compare_types.

    Each condition contributes 'field:compare_type_abbrev'.
    Buy and sell groups are separated by '||'.
    Conditions within each group are sorted for stability.
    """
    buy_keys = sorted(_cond_key(c) for c in buy_conds)
    sell_keys = sorted(_cond_key(c) for c in sell_conds)
    skeleton = "|".join(buy_keys) + "||" + "|".join(sell_keys)
    return skeleton[:120]


def extract_indicator_family(buy_conditions: list[dict] | None) -> str:
    """Extract Level 1 indicator family from buy conditions.

    Only considers which indicator fields are used, ignoring:
    - sell conditions (Level 2)
    - parameter values / thresholds (Level 3)
    - price fields (close, high, low, volume) unless used with compare_field

    Returns sorted indicator set string, e.g. "ATR+RSI" or "KDJ+PSAR+VPT".
    """
    if not buy_conditions:
        return "UNKNOWN"

    indicators = set()
    # Fields to exclude — these are price/volume, not indicators
    PRICE_FIELDS = {"close", "high", "low", "open", "volume"}

    for cond in buy_conditions:
        field = cond.get("field", "")
        # Normalize: strip params suffix (RSI_14 → RSI, BOLL_middle → BOLL)
        base = re.sub(r"_\d+.*$", "", field)  # RSI_14 → RSI
        base = re.sub(r"_[a-z]+$", "", base)  # BOLL_middle → BOLL, BOLL_wband → BOLL
        # Keep KDJ_K as KDJ, STOCHRSI_k as STOCHRSI
        base = base.split("_")[0] if "_" in base and base.split("_")[0] in (
            "KDJ", "MACD", "STOCHRSI", "STOCH", "BOLL", "KELTNER", "ICHIMOKU", "DONCHIAN"
        ) else base

        if base.lower() not in PRICE_FIELDS and base != "?":
            indicators.add(base.upper())

        # Also extract compare_field (e.g. close > EMA → EMA is an indicator)
        compare_field = cond.get("compare_field", "")
        if compare_field:
            cf_base = compare_field.split("_")[0] if "_" in compare_field else compare_field
            if cf_base.lower() not in PRICE_FIELDS:
                indicators.add(cf_base.upper())

    if not indicators:
        return "PRICE_ONLY"

    return "+".join(sorted(indicators))


def _extract_sell_structure(sell_conditions: list[dict] | None) -> str:
    """Extract Level 2 sell condition structure signature.

    Returns a stable string representing the sell logic type,
    e.g. 'close:lkmin' or 'ATR:cons|volume:cons'.
    """
    if not sell_conditions:
        return "NONE"
    keys = sorted(_cond_key(c) for c in sell_conditions)
    return "|".join(keys)


def _skeleton_quota(avg_score: float) -> int:
    """Legacy alias — delegates to _family_quota."""
    return _family_quota(avg_score)


def _family_quota(avg_score: float) -> int:
    """Level 1 quota: max active strategies per indicator family.

    Higher-scoring families earn more slots. This is the TOTAL cap
    for all signal structures and parameter variants within the family.
    """
    if avg_score >= 0.87:
        return 200
    if avg_score >= 0.85:
        return 150
    if avg_score >= 0.83:
        return 100
    if avg_score >= 0.81:
        return 50
    return 20


# Level 2: minimum distinct sell structures per family
MIN_SELL_STRUCTURES = 3

# Level 3: max strategies per fingerprint (same buy+sell, different exit params)
MAX_PER_FINGERPRINT = 15


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

    def compute_all_families(self) -> int:
        """Compute indicator_family for all strategies that don't have one."""
        strategies = self.db.query(Strategy).filter(
            Strategy.indicator_family.is_(None),
            Strategy.buy_conditions.isnot(None),
        ).all()

        count = 0
        for s in strategies:
            s.indicator_family = extract_indicator_family(s.buy_conditions)
            count += 1

        if count:
            self.db.commit()
            logger.info("Computed indicator_family for %d strategies", count)
        return count

    def rebalance(self, max_per_family: int = 3, dry_run: bool = False) -> dict:
        """Rebalance pool: keep top max_per_family per family (diverse SL/TP/MHD params).

        Archives all but the top max_per_family strategies within each fingerprint family.
        No global cap — all families can contribute up to max_per_family active strategies.
        """
        self.compute_all_fingerprints()

        all_strategies = self.db.query(Strategy).filter(
            Strategy.signal_fingerprint.isnot(None)
        ).all()

        families: dict[str, list[Strategy]] = defaultdict(list)
        wf_blocked = 0
        cooldown_blocked = 0
        for s in all_strategies:
            # Respect walk-forward gate: strategies that failed WF validation
            # must stay archived — never re-activate them via rebalance.
            wf = (s.backtest_summary or {}).get("walk_forward")
            if wf and wf.get("wfe_pct", 100) < 50:
                if s.enabled and not dry_run:
                    s.enabled = False
                    s.family_role = "archive"
                    if s.archived_at is None:
                        s.archived_at = datetime.now()
                wf_blocked += 1
                continue
            # Respect decay cooldown: strategy in 14-day cooldown cannot be reactivated
            if self.is_in_cooldown(s):
                cooldown_blocked += 1
                continue
            families[s.signal_fingerprint].append(s)
        if wf_blocked:
            logger.info("Rebalance: %d strategies blocked by walk-forward gate", wf_blocked)
        if cooldown_blocked:
            logger.info("Rebalance: %d strategies blocked by decay cooldown", cooldown_blocked)

        archived_count = 0
        activated_count = 0
        details = []

        # Pass 1: per-family limit
        candidate_active: list[Strategy] = []
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
                    candidate_active.append(s)
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

    def rebalance_by_skeleton(self, dry_run: bool = False) -> dict:
        """Three-tier rebalance: Family -> Signal Structure -> Parameter Variant.

        Level 1 (Indicator Family): Total cap per indicator set (e.g. ATR+RSI <= 200)
        Level 2 (Signal Structure): Min diversity of sell conditions within family (>= 3 types)
        Level 3 (Fingerprint):      Max per identical buy+sell fingerprint (<= 15)
        """
        self.compute_all_fingerprints()
        self.compute_all_families()

        all_strategies = self.db.query(Strategy).filter(
            Strategy.signal_fingerprint.isnot(None)
        ).all()

        # -- Group: Family -> Sell Structure -> Fingerprint -> [strategies] --
        tree: dict[str, dict[str, dict[str, list]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )

        wf_blocked_skel = 0
        for s in all_strategies:
            # Respect walk-forward gate: never re-activate WF-failed strategies
            wf = (s.backtest_summary or {}).get("walk_forward")
            if wf and wf.get("wfe_pct", 100) < 50:
                if s.enabled and not dry_run:
                    s.enabled = False
                    s.family_role = "archive"
                    if s.archived_at is None:
                        s.archived_at = datetime.now()
                wf_blocked_skel += 1
                continue
            family = s.indicator_family or extract_indicator_family(s.buy_conditions)
            sell_struct = _extract_sell_structure(s.sell_conditions)
            fp = s.signal_fingerprint
            tree[family][sell_struct][fp].append(s)
        if wf_blocked_skel:
            logger.info("Rebalance (skeleton): %d strategies blocked by walk-forward gate", wf_blocked_skel)

        selected_ids: set[int] = set()
        family_stats: list[dict] = []

        for family, sell_groups in tree.items():
            # Collect all champions (best per fingerprint) across all sell structures
            all_champions = []
            for sell_struct, fp_groups in sell_groups.items():
                for fp, members in fp_groups.items():
                    best = max(members, key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0)
                    all_champions.append((best, sell_struct, fp, members))

            all_champions.sort(key=lambda x: (x[0].backtest_summary or {}).get("score", 0) or 0, reverse=True)

            # L1: Determine family quota from avg score of top champions
            top_scores = [(c[0].backtest_summary or {}).get("score", 0) or 0 for c in all_champions[:80]]
            avg_score = sum(top_scores) / max(len(top_scores), 1)
            family_cap = _family_quota(avg_score)

            # L2: Ensure sell structure diversity -- reserve slots for underrepresented sell types
            sell_struct_counts: dict[str, int] = defaultdict(int)
            chosen_champions: list[tuple] = []

            # First pass: pick best champion from each sell structure (diversity guarantee)
            seen_sell = set()
            for champ, sell_s, fp, members in all_champions:
                if sell_s not in seen_sell and len(chosen_champions) < family_cap:
                    chosen_champions.append((champ, sell_s, fp, members))
                    seen_sell.add(sell_s)
                    sell_struct_counts[sell_s] += 1

            # Second pass: fill remaining quota with best remaining champions (Fix 5: set-based)
            seen_fps = {fp for _, _, fp, _ in chosen_champions}
            for champ, sell_s, fp, members in all_champions:
                if len(chosen_champions) >= family_cap:
                    break
                if fp not in seen_fps:
                    chosen_champions.append((champ, sell_s, fp, members))
                    seen_fps.add(fp)
                    sell_struct_counts[sell_s] += 1

            # L3: For each chosen champion, add diverse exit param variants.
            # family_cap is the TOTAL active strategy cap for the entire family.
            # Distribute slots across chosen fingerprints: each gets floor(cap/n) slots.
            family_selected: set[int] = set()
            n_chosen = max(len(chosen_champions), 1)
            per_fp_limit = max(family_cap // n_chosen, 1)
            # Cap per-fingerprint at MAX_PER_FINGERPRINT
            per_fp_limit = min(per_fp_limit, MAX_PER_FINGERPRINT)
            family_candidates: list[Strategy] = []

            for champ, sell_s, fp, members in chosen_champions:
                members_sorted = sorted(members, key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0, reverse=True)
                family_candidates.extend(self._select_diverse_top(members_sorted, per_fp_limit))

            family_candidates.sort(
                key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0,
                reverse=True,
            )
            if len(family_candidates) > 1:
                family_candidates = self._deduplicate_by_overlap(family_candidates)

            for s in family_candidates:
                if len(family_selected) >= family_cap:
                    break
                family_selected.add(s.id)

            selected_ids.update(family_selected)

            family_stats.append({
                "family": family,
                "avg_score": round(avg_score, 4),
                "quota": family_cap,
                "sell_structures": len(sell_groups),
                "sell_structures_selected": len(seen_sell),
                "fingerprint_families": sum(len(fps) for fps in sell_groups.values()),
                "fingerprints_selected": len(chosen_champions),
                "selected": len(family_selected),
            })

        # -- Apply activate / archive --
        initially_archived = {s.id for s in all_strategies if s.archived_at is not None}
        archived_count = 0
        activated_count = 0

        for s in all_strategies:
            if s.id in selected_ids:
                if not dry_run:
                    s.archived_at = None
                    s.enabled = True
                    s.family_role = "champion"
                if s.id in initially_archived:
                    activated_count += 1
            else:
                if not dry_run:
                    s.family_role = "archive"
                    if s.archived_at is None:
                        s.archived_at = datetime.now()
                    s.enabled = False
                if s.id not in initially_archived:
                    archived_count += 1

        if not dry_run:
            self.db.commit()

        active_total = self.db.query(Strategy).filter(
            Strategy.archived_at.is_(None),
            Strategy.signal_fingerprint.isnot(None),
        ).count() if not dry_run else len(selected_ids)

        return {
            "dry_run": dry_run,
            "family_count": len(tree),
            "archived_count": archived_count,
            "activated_count": activated_count,
            "active_strategies": active_total,
            "total_strategies": len(all_strategies),
            "families": sorted(family_stats, key=lambda d: -d["avg_score"]),
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

    def _deduplicate_by_overlap(self, strategies: list[Strategy], max_overlap: float = 0.80) -> list[Strategy]:
        """Remove strategies whose recent buy triggers overlap > max_overlap with a better one."""
        from api.models.signal import ActionSignal
        from datetime import date, timedelta

        cutoff = (date.today() - timedelta(days=180)).isoformat()
        keep: list[Strategy] = []
        signal_cache: dict[str, set] = {}

        for s in strategies:
            sname = s.name
            if sname not in signal_cache:
                signal_cache[sname] = set(
                    (r.stock_code, r.trade_date)
                    for r in self.db.query(ActionSignal.stock_code, ActionSignal.trade_date)
                    .filter(
                        ActionSignal.strategy_name == sname,
                        ActionSignal.action == "BUY",
                        ActionSignal.trade_date >= cutoff,
                    ).all()
                )

            signals_s = signal_cache[sname]
            if not signals_s:
                keep.append(s)
                continue

            is_redundant = False
            for kept in keep:
                kname = kept.name
                if kname not in signal_cache:
                    signal_cache[kname] = set(
                        (r.stock_code, r.trade_date)
                        for r in self.db.query(ActionSignal.stock_code, ActionSignal.trade_date)
                        .filter(
                            ActionSignal.strategy_name == kname,
                            ActionSignal.action == "BUY",
                            ActionSignal.trade_date >= cutoff,
                        ).all()
                    )
                signals_k = signal_cache[kname]
                if not signals_k:
                    continue

                intersection = len(signals_s & signals_k)
                union = len(signals_s | signals_k)
                if union > 0 and intersection / union > max_overlap:
                    is_redundant = True
                    logger.debug(
                        "Overlap dedup: S%d (%s) overlaps %.0f%% with S%d (%s)",
                        s.id, sname, intersection / union * 100, kept.id, kname,
                    )
                    break

            if not is_redundant:
                keep.append(s)

        if len(keep) < len(strategies):
            logger.info("Overlap dedup: kept %d/%d strategies", len(keep), len(strategies))
        return keep

    # ── Decay constants ──
    DECAY_COOLDOWN_DAYS = 14     # rebalance won't touch during cooldown
    DECAY_PROBATION_DISCOUNT = 0.70   # alpha quality score multiplier
    DECAY_EWMA_LAMBDA = 0.94    # halflife ≈ 11 trades
    DECAY_EWMA_RECOVERY = 0.55  # EWMA threshold to exit probation
    DECAY_PROBATION_MIN_DAYS = 14  # minimum observation days
    DECAY_PROBATION_MIN_TRADES = 5  # minimum trades during observation
    DECAY_PROBATION_MIN_WR = 0.60  # win rate threshold (3/5)
    DECAY_PROBATION_MAX_CONSEC_LOSS = 2  # max consecutive losses allowed

    def check_champion_decay(self) -> list[dict]:
        """Check champion strategies for performance decay and demote if needed.

        Decay rules:
        - dormant_60d: no trade plan in 60+ days → champion→active (no cooldown)
        - losing_streak_3: last 3 reviews all lost → archive + 14-day cooldown + probation

        Cooldown: strategy is archived, rebalance skips it for 14 days.
        After cooldown: strategy re-enters pool with probation mark (alpha discount).
        Probation clears when exit conditions are met (see update_decay_probation).
        """
        from api.models.bot_trading import BotTradePlan, BotTradeReview
        from datetime import date, timedelta, datetime as dt

        champions = self.db.query(Strategy).filter(
            Strategy.family_role == "champion",
            Strategy.enabled.is_(True),
        ).all()

        demoted = []
        cutoff_60d = (date.today() - timedelta(days=60)).isoformat()

        for s in champions:
            recent_plan = (
                self.db.query(BotTradePlan)
                .filter(
                    BotTradePlan.strategy_id == s.id,
                    BotTradePlan.plan_date >= cutoff_60d,
                )
                .first()
            )
            if not recent_plan:
                s.family_role = "active"
                demoted.append({"id": s.id, "name": s.name, "reason": "dormant_60d"})
                logger.info("Decay: S%d champion->active (dormant 60d)", s.id)
                continue

            recent_reviews = (
                self.db.query(BotTradeReview)
                .filter(BotTradeReview.strategy_id == s.id)
                .order_by(BotTradeReview.last_sell_date.desc())
                .limit(3)
                .all()
            )
            if len(recent_reviews) >= 3 and all((r.pnl_pct or 0) < 0 for r in recent_reviews):
                s.family_role = "archive"
                s.archived_at = dt.now()
                s.enabled = False
                # Write cooldown + probation metadata into backtest_summary
                bs = dict(s.backtest_summary or {})
                cooldown_end = (date.today() + timedelta(days=self.DECAY_COOLDOWN_DAYS)).isoformat()
                bs["decay_cooldown_until"] = cooldown_end
                bs["decay_probation"] = True
                bs["decay_ewma"] = 0.30  # ~3 consecutive losses
                bs["decay_probation_start"] = cooldown_end
                bs["decay_probation_trades"] = 0
                bs["decay_probation_wins"] = 0
                bs["decay_consecutive_losses"] = 0
                s.backtest_summary = bs
                demoted.append({"id": s.id, "name": s.name, "reason": "losing_streak_3",
                                "cooldown_until": cooldown_end})
                logger.info("Decay: S%d champion->archive (3 consecutive losses, cooldown until %s)",
                            s.id, cooldown_end)

        if demoted:
            self.db.commit()
        return demoted

    @staticmethod
    def is_in_cooldown(strategy: Strategy) -> bool:
        """Return True if strategy is in decay cooldown (rebalance must skip)."""
        from datetime import date
        bs = strategy.backtest_summary or {}
        cooldown_until = bs.get("decay_cooldown_until")
        if not cooldown_until:
            return False
        return date.today().isoformat() < cooldown_until

    @staticmethod
    def is_on_probation(strategy: Strategy) -> bool:
        """Return True if strategy has a probation mark (alpha discount applies)."""
        bs = strategy.backtest_summary or {}
        return bool(bs.get("decay_probation"))

    @staticmethod
    def get_probation_discount(strategy: Strategy) -> float:
        """Return alpha quality multiplier. 1.0 = normal, 0.7 = on probation."""
        bs = strategy.backtest_summary or {}
        if bs.get("decay_probation"):
            return 0.70
        return 1.0

    @staticmethod
    def update_decay_probation(strategy: Strategy, is_profitable: bool) -> bool:
        """Update probation state after a trade completes. Returns True if probation cleared.

        EWMA update: confidence_t = λ × confidence_{t-1} + (1-λ) × outcome
        Exit conditions (4-choose-3):
          1. ≥14 trading days since probation start
          2. ≥5 trades with win rate ≥60%
          3. EWMA confidence ≥ 0.55
          4. No 2 consecutive losses during probation
        """
        from datetime import date

        bs = dict(strategy.backtest_summary or {})
        if not bs.get("decay_probation"):
            return False

        # Update EWMA
        lam = 0.94
        old_ewma = bs.get("decay_ewma", 0.5)
        outcome = 1.0 if is_profitable else 0.0
        new_ewma = round(lam * old_ewma + (1 - lam) * outcome, 4)
        bs["decay_ewma"] = new_ewma

        # Update trade counts
        trades = bs.get("decay_probation_trades", 0) + 1
        wins = bs.get("decay_probation_wins", 0) + (1 if is_profitable else 0)
        bs["decay_probation_trades"] = trades
        bs["decay_probation_wins"] = wins

        # Update consecutive losses
        if is_profitable:
            bs["decay_consecutive_losses"] = 0
        else:
            bs["decay_consecutive_losses"] = bs.get("decay_consecutive_losses", 0) + 1

        # Check exit conditions (4-choose-3)
        conditions_met = 0

        # Condition 1: ≥14 trading days
        prob_start = bs.get("decay_probation_start", "")
        if prob_start and date.today().isoformat() >= prob_start:
            from datetime import timedelta
            start_date = date.fromisoformat(prob_start)
            if (date.today() - start_date).days >= 14:
                conditions_met += 1

        # Condition 2: ≥5 trades with wr ≥60%
        if trades >= 5 and (wins / trades) >= 0.60:
            conditions_met += 1

        # Condition 3: EWMA ≥ 0.55
        if new_ewma >= 0.55:
            conditions_met += 1

        # Condition 4: no 2 consecutive losses
        if bs.get("decay_consecutive_losses", 0) < 2:
            conditions_met += 1

        strategy.backtest_summary = bs

        # 4-choose-3: clear probation
        if conditions_met >= 3:
            bs.pop("decay_cooldown_until", None)
            bs.pop("decay_probation", None)
            bs.pop("decay_ewma", None)
            bs.pop("decay_probation_start", None)
            bs.pop("decay_probation_trades", None)
            bs.pop("decay_probation_wins", None)
            bs.pop("decay_consecutive_losses", None)
            strategy.backtest_summary = bs
            logger.info("Probation cleared: S%d (met %d/4 conditions, trades=%d, wr=%.0f%%, ewma=%.2f)",
                        strategy.id, conditions_met, trades, (wins/trades*100) if trades else 0, new_ewma)
            return True

        logger.debug("Probation update: S%d (met %d/4, trades=%d, wr=%.0f%%, ewma=%.2f, consec_loss=%d)",
                     strategy.id, conditions_met, trades, (wins/trades*100) if trades else 0,
                     new_ewma, bs.get("decay_consecutive_losses", 0))
        return False

    # Max members per family before auto-rebalance is triggered
    MAX_PER_FAMILY = 3

    def daily_health_check(self) -> dict:
        """Check pool health and auto-rebalance if any family exceeds MAX_PER_FAMILY."""
        computed = self.compute_all_fingerprints()

        family_sizes = (
            self.db.query(Strategy.signal_fingerprint, func.count(Strategy.id))
            .filter(Strategy.archived_at.is_(None), Strategy.signal_fingerprint.isnot(None))
            .group_by(Strategy.signal_fingerprint)
            .all()
        )

        oversized = [(fp, cnt) for fp, cnt in family_sizes if cnt > self.MAX_PER_FAMILY]
        active_count = sum(cnt for _, cnt in family_sizes)

        rebalanced = False
        if oversized:
            logger.warning(
                "Strategy pool has %d oversized families, auto-rebalancing by skeleton...",
                len(oversized),
            )
            self.rebalance_by_skeleton()
            active_count = self.db.query(Strategy).filter(
                Strategy.archived_at.is_(None),
                Strategy.signal_fingerprint.isnot(None),
            ).count()
            rebalanced = True
            logger.info("Auto-rebalance done: %d active strategies", active_count)

        return {
            "fingerprints_computed": computed,
            "active_strategies": active_count,
            "family_count": len(family_sizes),
            "oversized_families": len(oversized),
            "healthy": not oversized,
            "rebalanced": rebalanced,
        }

    def get_skeleton_competition_threshold(self, skeleton: str,
                                           indicator_family: str | None = None) -> tuple[float, int, int]:
        """Return (min_score_to_compete, current_active, quota) for a strategy.

        Uses indicator_family (Level 1) if provided, falls back to skeleton match.
        """
        all_active = self.db.query(Strategy).filter(
            Strategy.archived_at.is_(None),
            Strategy.signal_fingerprint.isnot(None),
        ).all()

        # Match by indicator_family (Level 1) if available
        by_fp: dict[str, Strategy] = {}
        for s in all_active:
            if indicator_family:
                fam = s.indicator_family or extract_indicator_family(s.buy_conditions)
                if fam != indicator_family:
                    continue
            else:
                sk = _extract_skeleton(s.name, s.buy_conditions, s.sell_conditions)
                if sk != skeleton:
                    continue
            fp = s.signal_fingerprint
            existing = by_fp.get(fp)
            s_score = (s.backtest_summary or {}).get("score", 0) or 0
            if existing is None or s_score > ((existing.backtest_summary or {}).get("score", 0) or 0):
                by_fp[fp] = s

        champions = list(by_fp.values())
        current_active = len(champions)

        if champions:
            avg = sum((s.backtest_summary or {}).get("score", 0) or 0 for s in champions) / len(champions)
        else:
            avg = 0.0
        quota = _family_quota(avg)

        if current_active < quota:
            return 0.80, current_active, quota

        min_score = min((s.backtest_summary or {}).get("score", 0) or 0 for s in champions)
        return min_score, current_active, quota

    def get_pool_status(self) -> dict:
        """Comprehensive pool status for API — active strategies only."""
        total = self.db.query(Strategy).count()
        active = self.db.query(Strategy).filter(Strategy.archived_at.is_(None)).count()

        # Only load active strategies for pool stats
        families_raw = (
            self.db.query(Strategy)
            .filter(Strategy.signal_fingerprint.isnot(None), Strategy.archived_at.is_(None))
            .all()
        )
        families: dict[str, list[Strategy]] = defaultdict(list)
        for s in families_raw:
            families[s.signal_fingerprint].append(s)

        families_summary = []
        regime_map: dict[str, dict] = defaultdict(lambda: {"families": set(), "strategies": 0})

        for fp, members in sorted(families.items(), key=lambda x: -len(x[1])):
            active_members = members  # all are active since we pre-filtered
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
                "archived_count": 0,
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

        result = {
            "total_strategies": total,
            "active_strategies": active,
            "archived_strategies": total - active,
            "family_count": len(families),
            "families_summary": sorted(families_summary, key=lambda f: -f["champion_score"]),
            "regime_coverage": regime_coverage,
            "last_rebalance_at": None,
            "signal_eval_reduction": f"{active} → {len(families)} unique evaluations per stock",
        }

        # Family-level summary (Level 1)
        family_groups: dict[str, list] = defaultdict(list)
        for fs in families_summary:
            # Find family from any strategy in this fingerprint
            for s in families.get(fs["fingerprint"], []):
                fam = s.indicator_family or extract_indicator_family(s.buy_conditions)
                family_groups[fam].append(fs)
                break

        family_summary = []
        for fam, fps in family_groups.items():
            active_total = sum(f["active_count"] for f in fps)
            best_score = max((f["champion_score"] for f in fps), default=0)
            avg = sum(f["champion_score"] for f in fps if f["champion_score"] > 0) / max(len([f for f in fps if f["champion_score"] > 0]), 1)
            quota = _family_quota(avg)
            family_summary.append({
                "family": fam,
                "active_count": active_total,
                "quota": quota,
                "gap": max(0, quota - active_total),
                "fingerprint_count": len(fps),
                "best_score": best_score,
                "avg_score": round(avg, 4),
            })

        result["family_summary"] = sorted(family_summary, key=lambda f: -f["best_score"])
        return result
