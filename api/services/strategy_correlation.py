"""Strategy return correlation analysis for deduplication.

Identifies strategies within the same indicator family whose backtested
daily returns are highly correlated (>0.95), indicating they capture
the same signal despite different condition structures.
"""

import logging
from collections import defaultdict

from sqlalchemy.orm import Session

from api.models.strategy import Strategy

logger = logging.getLogger(__name__)

# Strategies with return correlation above this threshold are considered duplicates
CORRELATION_THRESHOLD = 0.95


def find_correlated_pairs(db: Session, family: str | None = None,
                          threshold: float = CORRELATION_THRESHOLD) -> list[dict]:
    """Find pairs of active strategies with highly correlated returns.

    Uses regime_stats daily PnL patterns as a proxy for return correlation:
    strategies with identical regime performance profiles (same sign, similar magnitude
    across all regimes) are likely capturing the same signal.

    Returns list of {strategy_a, strategy_b, correlation, recommendation}.
    """
    query = db.query(Strategy).filter(
        Strategy.archived_at.is_(None),
        Strategy.backtest_summary.isnot(None),
    )
    if family:
        query = query.filter(Strategy.indicator_family == family)

    strategies = query.all()

    # Extract regime-based performance vector for each strategy
    vectors: dict[int, dict] = {}
    for s in strategies:
        bs = s.backtest_summary or {}
        rs = bs.get("regime_stats", {}) or {}
        if not rs:
            continue
        # Create performance vector: {regime: total_pnl}
        vec = {}
        for regime, data in rs.items():
            vec[regime] = (data or {}).get("total_pnl", 0)
        vectors[s.id] = {"strategy": s, "vec": vec, "score": bs.get("score", 0)}

    # Compare all pairs within same indicator family
    pairs = []
    ids = list(vectors.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = vectors[ids[i]], vectors[ids[j]]
            # Same indicator family check
            sa, sb = a["strategy"], b["strategy"]
            if sa.indicator_family != sb.indicator_family:
                continue

            # Compute regime-based similarity
            all_regimes = set(a["vec"].keys()) | set(b["vec"].keys())
            if len(all_regimes) < 2:
                continue

            # Cosine similarity of regime PnL vectors
            dot = sum(a["vec"].get(r, 0) * b["vec"].get(r, 0) for r in all_regimes)
            mag_a = sum(v ** 2 for v in a["vec"].values()) ** 0.5
            mag_b = sum(v ** 2 for v in b["vec"].values()) ** 0.5
            if mag_a == 0 or mag_b == 0:
                continue
            similarity = dot / (mag_a * mag_b)

            if similarity >= threshold:
                # Recommend archiving the lower-scoring one
                keep = sa if a["score"] >= b["score"] else sb
                archive = sb if keep == sa else sa
                pairs.append({
                    "keep_id": keep.id,
                    "keep_name": keep.name[:60],
                    "keep_score": (keep.backtest_summary or {}).get("score", 0),
                    "archive_id": archive.id,
                    "archive_name": archive.name[:60],
                    "archive_score": (archive.backtest_summary or {}).get("score", 0),
                    "similarity": round(similarity, 4),
                })

    return sorted(pairs, key=lambda p: -p["similarity"])


def deduplicate_correlated(db: Session, threshold: float = CORRELATION_THRESHOLD,
                           dry_run: bool = True) -> dict:
    """Archive the lower-scoring strategy in each correlated pair.

    Returns summary of actions taken.
    """
    from datetime import datetime

    pairs = find_correlated_pairs(db, threshold=threshold)

    archived_ids = set()
    actions = []

    for pair in pairs:
        aid = pair["archive_id"]
        if aid in archived_ids:
            continue  # already handled

        if not dry_run:
            # Fix 2: use db.get() instead of db.query().get()
            s = db.get(Strategy, aid)
            if s and s.archived_at is None:
                s.archived_at = datetime.now()
                s.enabled = False
                s.family_role = "archive"
                archived_ids.add(aid)
                actions.append(pair)
        else:
            archived_ids.add(aid)
            actions.append(pair)

    if not dry_run:
        db.commit()

    return {
        "dry_run": dry_run,
        "threshold": threshold,
        "correlated_pairs_found": len(pairs),
        "archived_count": len(archived_ids),
        "actions": actions[:20],  # top 20 for display
    }
