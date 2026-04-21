# Three-Tier Strategy Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat skeleton classification with a 3-level hierarchy (Indicator Family → Signal Structure → Parameter Variant) to unify Step 1e and rebalance, enforce per-family quotas, and add return-correlation deduplication.

**Architecture:** Add `indicator_family` field to Strategy model (Level 1 = core indicator set from buy conditions, ignoring sell/exit). Rewrite `rebalance_by_skeleton()` to use 3-tier quotas: L1 caps total per family, L2 enforces sell-condition diversity within family, L3 keeps per-fingerprint cap. Add optional return-correlation deduplication as post-rebalance pass.

**Tech Stack:** SQLAlchemy (model migration), Python (pool manager logic), FastAPI (endpoints)

---

### Task 1: Add `indicator_family` field to Strategy model + extraction function

**Files:**
- Modify: `api/models/strategy.py:28-32`
- Modify: `api/services/strategy_pool.py:45-94`
- Test: manual DB migration check

- [ ] **Step 1: Add `indicator_family` column to Strategy model**

In `api/models/strategy.py`, add after line 29 (`signal_fingerprint`):

```python
    indicator_family: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True, default=None)
```

- [ ] **Step 2: Write `extract_indicator_family()` function**

In `api/services/strategy_pool.py`, add after `_skeleton_from_conditions()` (after line 94):

```python
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
```

- [ ] **Step 3: Add `compute_all_families()` method to StrategyPoolManager**

In `api/services/strategy_pool.py`, add to `StrategyPoolManager` class after `compute_all_fingerprints()`:

```python
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
```

- [ ] **Step 4: Run server to trigger auto-migration, verify column exists**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import engine, Base
from api.models.strategy import Strategy
Base.metadata.create_all(engine)
print('Migration done')
"
```

- [ ] **Step 5: Backfill indicator_family for all existing strategies**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.services.strategy_pool import StrategyPoolManager
from api.models.base import SessionLocal
session = SessionLocal()
mgr = StrategyPoolManager(session)
n = mgr.compute_all_families()
print(f'Backfilled {n} strategies')
session.close()
"
```

- [ ] **Step 6: Verify backfill results**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import SessionLocal
from api.models.strategy import Strategy
from sqlalchemy import func
session = SessionLocal()
families = session.query(Strategy.indicator_family, func.count(Strategy.id)).group_by(Strategy.indicator_family).order_by(func.count(Strategy.id).desc()).all()
for fam, cnt in families[:20]:
    print(f'  {fam}: {cnt}')
print(f'Total families: {len(families)}')
session.close()
"
```

Expected: ~10-15 indicator families (ATR+RSI, ATR+KDJ, ATR+BOLL+VPT, etc.) instead of 230 skeletons.

- [ ] **Step 7: Commit**

```bash
git add api/models/strategy.py api/services/strategy_pool.py
git commit -m "feat(pool): add indicator_family field + extraction (Level 1 taxonomy)"
```

---

### Task 2: Rewrite `_skeleton_quota()` to 3-tier family quota system

**Files:**
- Modify: `api/services/strategy_pool.py:97-110`

- [ ] **Step 1: Replace `_skeleton_quota()` with `_family_quota()`**

Replace lines 97-110 in `api/services/strategy_pool.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add api/services/strategy_pool.py
git commit -m "feat(pool): 3-tier quota constants (L1 family, L2 sell diversity, L3 fingerprint)"
```

---

### Task 3: Rewrite `rebalance_by_skeleton()` to 3-tier rebalance

**Files:**
- Modify: `api/services/strategy_pool.py:220-332`

- [ ] **Step 1: Write `_extract_sell_structure()` helper**

Add after `extract_indicator_family()`:

```python
def _extract_sell_structure(sell_conditions: list[dict] | None) -> str:
    """Extract Level 2 sell condition structure signature.

    Returns a stable string representing the sell logic type,
    e.g. 'close:lkmin' or 'ATR:cons|volume:cons'.
    """
    if not sell_conditions:
        return "NONE"
    keys = sorted(_cond_key(c) for c in sell_conditions)
    return "|".join(keys)


# Reuse _cond_key from _skeleton_from_conditions (already defined)
```

- [ ] **Step 2: Rewrite `rebalance_by_skeleton()` as `rebalance_three_tier()`**

Replace `rebalance_by_skeleton()` (lines 220-332) with:

```python
    def rebalance_by_skeleton(self, dry_run: bool = False) -> dict:
        """Three-tier rebalance: Family → Signal Structure → Parameter Variant.

        Level 1 (Indicator Family): Total cap per indicator set (e.g. ATR+RSI ≤ 200)
        Level 2 (Signal Structure): Min diversity of sell conditions within family (≥ 3 types)
        Level 3 (Fingerprint):      Max per identical buy+sell fingerprint (≤ 15)
        """
        self.compute_all_fingerprints()
        self.compute_all_families()

        all_strategies = self.db.query(Strategy).filter(
            Strategy.signal_fingerprint.isnot(None)
        ).all()

        # ── Group: Family → Sell Structure → Fingerprint → [strategies] ──
        from collections import defaultdict
        tree: dict[str, dict[str, dict[str, list]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )

        for s in all_strategies:
            family = s.indicator_family or extract_indicator_family(s.buy_conditions)
            sell_struct = _extract_sell_structure(s.sell_conditions)
            fp = s.signal_fingerprint
            tree[family][sell_struct][fp].append(s)

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

            # L2: Ensure sell structure diversity — reserve slots for underrepresented sell types
            sell_struct_counts: dict[str, int] = defaultdict(int)
            chosen_champions: list[tuple] = []

            # First pass: pick best champion from each sell structure (diversity guarantee)
            seen_sell = set()
            for champ, sell_s, fp, members in all_champions:
                if sell_s not in seen_sell and len(chosen_champions) < family_cap:
                    chosen_champions.append((champ, sell_s, fp, members))
                    seen_sell.add(sell_s)
                    sell_struct_counts[sell_s] += 1

            # Second pass: fill remaining quota with best remaining champions
            for champ, sell_s, fp, members in all_champions:
                if len(chosen_champions) >= family_cap:
                    break
                if (champ, sell_s, fp, members) not in chosen_champions:
                    chosen_champions.append((champ, sell_s, fp, members))
                    sell_struct_counts[sell_s] += 1

            # L3: For each chosen champion, also select diverse exit param variants from same fingerprint
            for champ, sell_s, fp, members in chosen_champions:
                selected_ids.add(champ.id)
                # Add diverse variants from same fingerprint (up to MAX_PER_FINGERPRINT)
                members_sorted = sorted(members, key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0, reverse=True)
                diverse = self._select_diverse_top(members_sorted, MAX_PER_FINGERPRINT)
                for s in diverse:
                    selected_ids.add(s.id)

            family_stats.append({
                "family": family,
                "avg_score": round(avg_score, 4),
                "quota": family_cap,
                "sell_structures": len(sell_groups),
                "sell_structures_selected": len(seen_sell),
                "fingerprint_families": sum(len(fps) for fps in sell_groups.values()),
                "selected": len([c for c in chosen_champions]),
                "total_active": sum(1 for sid in selected_ids),  # running total
            })

        # ── Apply activate / archive ──
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
```

- [ ] **Step 3: Update endpoint response field names**

In `api/routers/strategies.py`, the rebalance endpoint returns the result dict directly — the field name changes from `skeleton_count` → `family_count` and `skeletons` → `families` happen automatically since we changed the return dict. No code change needed.

- [ ] **Step 4: Test rebalance dry-run**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST 'http://127.0.0.1:8050/api/strategies/pool/rebalance?max_per_family=15&dry_run=true' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Families: {d.get(\"family_count\",0)}')
print(f'Active: {d.get(\"active_strategies\",0)}')
print(f'Would archive: {d.get(\"archived_count\",0)}')
for f in d.get('families', [])[:10]:
    print(f'  {f[\"family\"]:30s} | avg={f[\"avg_score\"]:.4f} quota={f[\"quota\"]} sel={f[\"selected\"]} sell_types={f[\"sell_structures_selected\"]}')
"
```

Expected: ~10-15 families instead of 230, with ATR+RSI having quota=200 and properly distributed sell structures.

- [ ] **Step 5: Execute real rebalance**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST 'http://127.0.0.1:8050/api/strategies/pool/rebalance?max_per_family=15' | python3 -m json.tool
```

- [ ] **Step 6: Commit**

```bash
git add api/services/strategy_pool.py
git commit -m "feat(pool): 3-tier rebalance (family→sell_structure→fingerprint)"
```

---

### Task 4: Update `get_pool_status()` to report 3-tier hierarchy

**Files:**
- Modify: `api/services/strategy_pool.py:433-498`

- [ ] **Step 1: Add family-level summary to `get_pool_status()`**

Add to the return dict (after line 497):

```python
        # Family-level summary (Level 1)
        family_groups: dict[str, list] = defaultdict(list)
        for fs in families_summary:
            rep = fs.get("representative_name", "")
            # Find family from any active strategy in this fingerprint
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

        # Add to return dict
        result["family_summary"] = sorted(family_summary, key=lambda f: -f["best_score"])
```

- [ ] **Step 2: Commit**

```bash
git add api/services/strategy_pool.py
git commit -m "feat(pool): add family_summary (Level 1) to pool status API"
```

---

### Task 5: Update `get_skeleton_competition_threshold()` to use indicator family

**Files:**
- Modify: `api/services/strategy_pool.py:391-431`

- [ ] **Step 1: Rewrite to match by indicator_family instead of full skeleton**

```python
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
```

- [ ] **Step 2: Update promotion logic to pass indicator_family**

In `api/routers/ai_lab.py`, in the promote endpoint (~line 407), add indicator_family extraction:

```python
        indicator_family = extract_indicator_family(exp_strat.buy_conditions)
        threshold, current, quota = pool_mgr.get_skeleton_competition_threshold(
            skeleton, indicator_family=indicator_family
        )
```

Add import at top of promote function:
```python
        from api.services.strategy_pool import extract_indicator_family
```

Also set indicator_family on the new Strategy object (around line 420):
```python
        new_strat.indicator_family = indicator_family
```

- [ ] **Step 3: Commit**

```bash
git add api/services/strategy_pool.py api/routers/ai_lab.py
git commit -m "feat(pool): promotion uses indicator_family for competition threshold"
```

---

### Task 6: Update explore-strategies skill Step 1e to use `family_summary`

**Files:**
- Modify: `.claude/skills/explore-strategies/SKILL.md`

- [ ] **Step 1: Replace Step 1e skeleton check script**

Replace the Step 1e bash script to use the new `family_summary` from pool status:

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

status = api('strategies/pool/status')
families = status.get('family_summary', [])

print(f'=== 指标家族状态 (Level 1) ===')
print(f'总家族数: {len(families)}')
print()

for f in families:
    gap = f.get('gap', 0)
    status_icon = '🟡' if gap > 0 else '🔴'
    print(f'{status_icon} {f[\"family\"]:30s} | {f[\"active_count\"]}/{f[\"quota\"]} (gap={gap}) avg={f[\"avg_score\"]:.4f} fp={f[\"fingerprint_count\"]}')
"
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/explore-strategies/SKILL.md
git commit -m "feat(skill): Step 1e uses indicator_family (Level 1) for status check"
```

---

### Task 7: Add return-correlation deduplication (P3)

**Files:**
- Create: `api/services/strategy_correlation.py`
- Modify: `api/services/strategy_pool.py` (add call to correlation check)

- [ ] **Step 1: Create correlation analysis service**

```python
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
            s = db.query(Strategy).get(aid)
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
```

- [ ] **Step 2: Add correlation dedup endpoint**

In `api/routers/strategies.py`, add:

```python
@router.post("/pool/deduplicate")
def deduplicate_pool(
    threshold: float = 0.95,
    dry_run: bool = True,
    db: Session = Depends(get_db),
):
    """Find and archive strategies with highly correlated returns."""
    from api.services.strategy_correlation import deduplicate_correlated
    return deduplicate_correlated(db, threshold=threshold, dry_run=dry_run)
```

- [ ] **Step 3: Verify correlation dedup dry-run**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST 'http://127.0.0.1:8050/api/strategies/pool/deduplicate?threshold=0.95&dry_run=true' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Correlated pairs: {d[\"correlated_pairs_found\"]}')
print(f'Would archive: {d[\"archived_count\"]}')
for a in d.get('actions', [])[:5]:
    print(f'  Keep S{a[\"keep_id\"]} ({a[\"keep_score\"]:.4f}) | Archive S{a[\"archive_id\"]} ({a[\"archive_score\"]:.4f}) | sim={a[\"similarity\"]}')
"
```

- [ ] **Step 4: Commit**

```bash
git add api/services/strategy_correlation.py api/routers/strategies.py
git commit -m "feat(pool): P3 return-correlation deduplication endpoint"
```

---

### Task 8: Integration test — full rebalance cycle

**Files:** None (test via API calls)

- [ ] **Step 1: Restart server with all changes**

```bash
kill $(lsof -t -i :8050) 2>/dev/null
sleep 2
NO_PROXY=localhost,127.0.0.1 nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/uvicorn.log 2>&1 &
sleep 15
```

- [ ] **Step 2: Run full 3-tier rebalance and verify**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api_post(path):
    r = subprocess.run(['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def api_get(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# 1. Rebalance
rb = api_post('strategies/pool/rebalance?max_per_family=15')
print(f'Rebalance: {rb.get(\"family_count\",0)} families, {rb.get(\"active_strategies\",0)} active, archived {rb.get(\"archived_count\",0)}')

# 2. Check pool status with family summary
status = api_get('strategies/pool/status')
print(f'\\nPool: {status[\"active_strategies\"]} active / {status[\"total_strategies\"]} total')
for f in status.get('family_summary', []):
    print(f'  {f[\"family\"]:25s} | {f[\"active_count\"]}/{f[\"quota\"]} gap={f[\"gap\"]} avg={f[\"avg_score\"]:.4f}')

# 3. Correlation dedup dry-run
dedup = api_post('strategies/pool/deduplicate?threshold=0.95&dry_run=true')
print(f'\\nCorrelation dedup: {dedup.get(\"correlated_pairs_found\",0)} pairs, would archive {dedup.get(\"archived_count\",0)}')
"
```

Expected output should show:
- ~10-15 indicator families (not 230 skeletons)
- ATR+RSI capped at ≤200 (not 994)
- Each family has gap info for Step 1e
- Correlation dedup finds redundant strategies

- [ ] **Step 3: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(pool): complete 3-tier taxonomy (P0-P3) integration verified"
```
