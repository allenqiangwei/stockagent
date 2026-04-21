# Strategy Pool Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce 6,119 redundant strategies to ~330-500 active strategies by grouping identical buy/sell signal families and keeping max 15 per family, with 180x signal generation speedup.

**Architecture:** Add `signal_fingerprint` to Strategy model for family grouping. New `StrategyPoolManager` service handles rebalancing (archive surplus, keep diverse top-15). Signal engine evaluates buy/sell conditions once per fingerprint group instead of per-strategy.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, PostgreSQL, hashlib (SHA-256)

---

### Task 1: Strategy Model — Add fingerprint and family fields

**Files:**
- Modify: `api/models/strategy.py:11-29`

**Step 1: Add new columns to Strategy model**

In `api/models/strategy.py`, add 4 new columns after `source_experiment_id` (line 27):

```python
"""Strategy ORM model — stores rules, buy/sell conditions, exit config as JSON."""

from datetime import datetime

from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    rules: Mapped[dict] = mapped_column(JSON, default=list)
    buy_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    sell_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    exit_config: Mapped[dict] = mapped_column(JSON, default=dict)
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rank_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    portfolio_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    backtest_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    source_experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # ── Strategy Pool fields ──
    signal_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, default=None)
    family_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    family_role: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**Step 2: Run Alembic migration (or manual ALTER TABLE)**

The project uses SQLAlchemy `create_all()` on startup (check `api/main.py`). If `create_all()` is used, new nullable columns will be added automatically on restart. If Alembic is used, generate a migration:

```bash
cd /Users/allenqiang/stockagent
# Check if alembic is configured
ls alembic.ini 2>/dev/null || echo "No alembic — relies on create_all()"
```

If no Alembic, manually add columns via SQL:

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import engine
from sqlalchemy import text
with engine.connect() as conn:
    for stmt in [
        'ALTER TABLE strategies ADD COLUMN IF NOT EXISTS signal_fingerprint VARCHAR(64)',
        'ALTER TABLE strategies ADD COLUMN IF NOT EXISTS family_rank INTEGER',
        'ALTER TABLE strategies ADD COLUMN IF NOT EXISTS family_role VARCHAR(20)',
        'ALTER TABLE strategies ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP',
        'CREATE INDEX IF NOT EXISTS ix_strategies_signal_fingerprint ON strategies (signal_fingerprint)',
    ]:
        conn.execute(text(stmt))
    conn.commit()
    print('Migration done')
"
```

**Step 3: Verify columns exist**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import engine
from sqlalchemy import inspect
cols = [c['name'] for c in inspect(engine).get_columns('strategies')]
for needed in ['signal_fingerprint', 'family_rank', 'family_role', 'archived_at']:
    status = '✓' if needed in cols else '✗ MISSING'
    print(f'  {status} {needed}')
"
```

Expected: All 4 columns show ✓

**Step 4: Commit**

```bash
git add api/models/strategy.py
git commit -m "feat(strategy): add signal_fingerprint and family fields for pool management"
```

---

### Task 2: Strategy Schemas — Add family response models

**Files:**
- Modify: `api/schemas/strategy.py:87-103`

**Step 1: Add new fields to StrategyResponse and add PoolStatus/FamilySummary schemas**

Append to `api/schemas/strategy.py` after existing StrategyResponse, and also update StrategyResponse:

```python
class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str
    rules: list[dict]
    buy_conditions: list[dict]
    sell_conditions: list[dict]
    exit_config: dict
    weight: float
    enabled: bool
    rank_config: Optional[dict] = None
    portfolio_config: Optional[dict] = None
    category: Optional[str] = None
    backtest_summary: Optional[dict] = None
    source_experiment_id: Optional[int] = None
    signal_fingerprint: Optional[str] = None
    family_rank: Optional[int] = None
    family_role: Optional[str] = None
    archived_at: Optional[str] = None

    model_config = {"from_attributes": True}


class FamilySummary(BaseModel):
    fingerprint: str
    representative_name: str
    active_count: int
    archived_count: int
    champion_score: float
    champion_id: int
    avg_score: float
    regime_coverage: list[str]
    exit_param_range: dict  # {"sl": [min, max], "tp": [min, max], "mhd": [min, max]}


class RegimeCoverage(BaseModel):
    families: int
    strategies: int


class PoolStatus(BaseModel):
    total_strategies: int
    active_strategies: int
    archived_strategies: int
    family_count: int
    families_summary: list[FamilySummary]
    regime_coverage: dict[str, RegimeCoverage]
    last_rebalance_at: Optional[str] = None
    signal_eval_reduction: str


class RebalanceResult(BaseModel):
    archived_count: int
    activated_count: int
    families_count: int
    active_strategies: int
    details: list[dict]  # per-family changes
```

**Step 2: Commit**

```bash
git add api/schemas/strategy.py
git commit -m "feat(schema): add pool status and family summary response models"
```

---

### Task 3: StrategyPoolManager — Core service

**Files:**
- Create: `api/services/strategy_pool.py`
- Test: Run `rebalance` on actual data via API after Task 5

**Step 1: Write the StrategyPoolManager**

Create `api/services/strategy_pool.py`:

```python
"""Strategy Pool Manager — groups strategies by signal fingerprint, keeps top-N per family."""

import hashlib
import json
import logging
from datetime import datetime
from collections import defaultdict

from sqlalchemy.orm import Session

from api.models.strategy import Strategy

logger = logging.getLogger(__name__)

# ── Fingerprint computation ──────────────────────────────


def _canonical_conditions(conditions: list[dict]) -> str:
    """Produce a stable string representation of buy/sell conditions.

    Sorts conditions by (field, operator, compare_type) to ensure
    semantically identical condition sets produce the same hash
    regardless of original order.
    """
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


# ── Pool Manager ─────────────────────────────────────────


class StrategyPoolManager:
    """Manages the strategy pool by grouping strategies into signal families."""

    def __init__(self, db: Session):
        self.db = db

    def compute_all_fingerprints(self) -> int:
        """Compute signal_fingerprint for all strategies that don't have one.

        Returns count of strategies updated.
        """
        strategies = self.db.query(Strategy).filter(
            Strategy.signal_fingerprint.is_(None)
        ).all()

        count = 0
        for s in strategies:
            # Skip combo strategies — they have no direct buy/sell conditions
            pf = s.portfolio_config or {}
            if pf.get("type") == "combo":
                continue
            s.signal_fingerprint = compute_fingerprint(
                s.buy_conditions or [], s.sell_conditions or []
            )
            count += 1

        if count:
            self.db.commit()
            logger.info("Computed fingerprints for %d strategies", count)
        return count

    def rebalance(self, max_per_family: int = 15, dry_run: bool = False) -> dict:
        """Rebalance the strategy pool.

        For each signal fingerprint family:
        1. Rank by score descending
        2. Keep top max_per_family with diverse SL/TP/MHD params
        3. Archive the rest (set archived_at, enabled=False)

        Returns a summary of changes made.
        """
        # Ensure all fingerprints are computed
        self.compute_all_fingerprints()

        # Group strategies by fingerprint
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
            # Sort by score descending
            members.sort(
                key=lambda s: (s.backtest_summary or {}).get("score", 0) or 0,
                reverse=True,
            )

            # Select top members with param diversity
            selected = self._select_diverse_top(members, max_per_family)
            selected_ids = {s.id for s in selected}

            family_archived = 0
            family_activated = 0
            champion_name = members[0].name if members else "?"

            for rank, s in enumerate(members):
                if s.id in selected_ids:
                    new_rank = rank + 1
                    new_role = "champion" if rank == 0 else "active"
                    was_archived = s.archived_at is not None

                    if not dry_run:
                        s.family_rank = new_rank
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
                        s.archived_at = s.archived_at or datetime.now()
                        s.enabled = False

                    if was_active:
                        family_archived += 1
                        archived_count += 1

            details.append({
                "fingerprint": fp[:16],
                "champion": champion_name[:60],
                "total": len(members),
                "active": len(selected),
                "archived_this_run": family_archived,
                "activated_this_run": family_activated,
            })

        if not dry_run:
            self.db.commit()

        # Count final state
        active_total = self.db.query(Strategy).filter(
            Strategy.archived_at.is_(None),
            Strategy.signal_fingerprint.isnot(None),
        ).count()

        result = {
            "dry_run": dry_run,
            "families_count": len(families),
            "archived_count": archived_count,
            "activated_count": activated_count,
            "active_strategies": active_total,
            "total_strategies": len(all_strategies),
            "details": sorted(details, key=lambda d: -d["total"]),
        }

        if not dry_run:
            logger.info(
                "Pool rebalance: %d families, %d archived, %d active",
                len(families), archived_count, active_total,
            )

        return result

    def _select_diverse_top(self, members: list[Strategy], max_count: int) -> list[Strategy]:
        """Select top members ensuring SL/TP/MHD parameter diversity.

        Members are already sorted by score descending.
        Deduplicates by (SL, TP, MHD) tuple — if two strategies have identical
        exit params, only the higher-scored one is kept.
        """
        selected: list[Strategy] = []
        seen_params: set[tuple] = set()

        for s in members:
            if len(selected) >= max_count:
                break

            ec = s.exit_config or {}
            param_key = (
                ec.get("stop_loss_pct"),
                ec.get("take_profit_pct"),
                ec.get("max_hold_days"),
            )

            if param_key in seen_params:
                continue

            seen_params.add(param_key)
            selected.append(s)

        return selected

    def daily_health_check(self) -> dict:
        """Lightweight pre-signal-generation check.

        1. Compute missing fingerprints
        2. Archive any family that exceeded max_per_family
        3. Check regime coverage

        Returns health status dict.
        """
        # 1. Compute missing fingerprints
        computed = self.compute_all_fingerprints()

        # 2. Count family sizes
        from sqlalchemy import func
        family_sizes = (
            self.db.query(
                Strategy.signal_fingerprint,
                func.count(Strategy.id),
            )
            .filter(
                Strategy.archived_at.is_(None),
                Strategy.signal_fingerprint.isnot(None),
            )
            .group_by(Strategy.signal_fingerprint)
            .all()
        )

        oversized = [(fp, cnt) for fp, cnt in family_sizes if cnt > 15]

        # 3. Count active strategies
        active_count = self.db.query(Strategy).filter(
            Strategy.archived_at.is_(None),
            Strategy.enabled.is_(True),
        ).count()

        family_count = len(family_sizes)

        return {
            "fingerprints_computed": computed,
            "active_strategies": active_count,
            "family_count": family_count,
            "oversized_families": len(oversized),
            "healthy": len(oversized) == 0,
        }

    def get_pool_status(self) -> dict:
        """Return comprehensive pool status for the API."""
        from sqlalchemy import func

        total = self.db.query(Strategy).count()
        active = self.db.query(Strategy).filter(
            Strategy.archived_at.is_(None),
        ).count()

        # Family summary
        families_raw = (
            self.db.query(Strategy)
            .filter(Strategy.signal_fingerprint.isnot(None))
            .all()
        )

        families: dict[str, list[Strategy]] = defaultdict(list)
        for s in families_raw:
            families[s.signal_fingerprint].append(s)

        families_summary = []
        for fp, members in sorted(families.items(), key=lambda x: -len(x[1])):
            active_members = [m for m in members if m.archived_at is None]
            archived_members = [m for m in members if m.archived_at is not None]

            # Champion = highest score among active
            champion = max(active_members, key=lambda s: (s.backtest_summary or {}).get("score", 0), default=None)

            # Regime coverage from champion's backtest_summary
            regimes = []
            if champion and champion.backtest_summary:
                rs = champion.backtest_summary.get("regime_stats", {}) or {}
                for rname, rdata in rs.items():
                    if (rdata or {}).get("total_pnl", 0) > 0:
                        regimes.append(rname)

            # Exit param range
            exit_params = [m.exit_config or {} for m in active_members]
            sl_vals = [abs(ec.get("stop_loss_pct", 0) or 0) for ec in exit_params if ec.get("stop_loss_pct")]
            tp_vals = [ec.get("take_profit_pct", 0) or 0 for ec in exit_params if ec.get("take_profit_pct")]
            mhd_vals = [ec.get("max_hold_days", 0) or 0 for ec in exit_params if ec.get("max_hold_days")]

            families_summary.append({
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
            })

        # Overall regime coverage
        regime_map: dict[str, dict] = defaultdict(lambda: {"families": set(), "strategies": 0})
        for fs in families_summary:
            for regime in fs["regime_coverage"]:
                regime_map[regime]["families"].add(fs["fingerprint"])
                regime_map[regime]["strategies"] += fs["active_count"]

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
            "last_rebalance_at": None,  # TODO: track in DB or config
            "signal_eval_reduction": f"{total} → {len(families)} unique evaluations per stock",
        }
```

**Step 2: Verify import works**

```bash
cd /Users/allenqiang/stockagent
NO_PROXY=localhost,127.0.0.1 python3 -c "from api.services.strategy_pool import StrategyPoolManager, compute_fingerprint; print('Import OK')"
```

**Step 3: Commit**

```bash
git add api/services/strategy_pool.py
git commit -m "feat(pool): add StrategyPoolManager with fingerprint grouping and rebalance"
```

---

### Task 4: Router — Add pool management endpoints

**Files:**
- Modify: `api/routers/strategies.py`

**Step 1: Add pool endpoints**

Add these endpoints to `api/routers/strategies.py` (after the existing `cleanup_strategies` endpoint, before the `create_combo_strategy` endpoint):

```python
@router.post("/pool/rebalance")
def rebalance_pool(
    max_per_family: int = Query(15, description="Max active strategies per signal family"),
    dry_run: bool = Query(False, description="If true, report changes without executing"),
    db: Session = Depends(get_db),
):
    """Rebalance strategy pool: archive redundant strategies, keep top-N per family."""
    from api.services.strategy_pool import StrategyPoolManager
    mgr = StrategyPoolManager(db)
    return mgr.rebalance(max_per_family=max_per_family, dry_run=dry_run)


@router.get("/pool/status")
def pool_status(db: Session = Depends(get_db)):
    """Return comprehensive strategy pool status."""
    from api.services.strategy_pool import StrategyPoolManager
    mgr = StrategyPoolManager(db)
    return mgr.get_pool_status()


@router.get("/families")
def list_families(db: Session = Depends(get_db)):
    """List strategy families grouped by signal fingerprint."""
    from api.services.strategy_pool import StrategyPoolManager
    mgr = StrategyPoolManager(db)
    status = mgr.get_pool_status()
    return status["families_summary"]


@router.get("/families/{fingerprint}")
def get_family(fingerprint: str, db: Session = Depends(get_db)):
    """Get all strategies in a specific signal family (including archived)."""
    strategies = (
        db.query(Strategy)
        .filter(Strategy.signal_fingerprint == fingerprint)
        .order_by(Strategy.family_rank.nullslast(), Strategy.id)
        .all()
    )
    if not strategies:
        raise HTTPException(404, "Family not found")
    return [StrategyResponse.model_validate(s) for s in strategies]


@router.post("/{strategy_id}/unarchive")
def unarchive_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """Restore an archived strategy to active status."""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    if s.archived_at is None:
        return {"message": "Strategy is already active", "id": strategy_id}
    s.archived_at = None
    s.enabled = True
    s.family_role = "active"
    db.commit()
    return {"message": "Strategy unarchived", "id": strategy_id}
```

**IMPORTANT: Route ordering.** FastAPI matches routes in definition order. The `/pool/rebalance`, `/pool/status`, `/families` routes must be defined BEFORE `/{strategy_id}` routes, otherwise `pool` and `families` will be captured as a `strategy_id` parameter. Check that the existing routes are already ordered correctly (they are: `/indicator-groups` → `""` → `/{strategy_id}` → `/cleanup` → `/combo` → `/{strategy_id}/clone`). Insert the new routes AFTER `/cleanup` but BEFORE `/combo`.

**Step 2: Verify endpoints are registered**

```bash
cd /Users/allenqiang/stockagent
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
for r in sorted(routes):
    if 'strateg' in r or 'pool' in r or 'famil' in r:
        print(r)
"
```

Expected output should include `/api/strategies/pool/rebalance`, `/api/strategies/pool/status`, `/api/strategies/families`, etc.

**Step 3: Commit**

```bash
git add api/routers/strategies.py
git commit -m "feat(api): add pool rebalance, status, families, and unarchive endpoints"
```

---

### Task 5: Test rebalance on real data

**Files:** None (API testing)

**Step 1: Dry-run rebalance**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/strategies/pool/rebalance?dry_run=true&max_per_family=15" | python3 -m json.tool | head -30
```

Expected: See `dry_run: true`, `families_count: ~33`, `archived_count: ~5600+`

**Step 2: Check pool status before rebalance**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/strategies/pool/status" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Total: {d[\"total_strategies\"]}')
print(f'Active: {d[\"active_strategies\"]}')
print(f'Archived: {d[\"archived_strategies\"]}')
print(f'Families: {d[\"family_count\"]}')
print(f'Eval reduction: {d[\"signal_eval_reduction\"]}')
"
```

**Step 3: Execute actual rebalance**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/strategies/pool/rebalance?max_per_family=15" | python3 -m json.tool
```

**Step 4: Verify post-rebalance state**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/strategies/pool/status" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Active: {d[\"active_strategies\"]} (was 6119)')
print(f'Archived: {d[\"archived_strategies\"]}')
print(f'Families: {d[\"family_count\"]}')
for f in d['families_summary'][:5]:
    print(f'  {f[\"representative_name\"][:50]}: {f[\"active_count\"]} active, champion={f[\"champion_score\"]:.4f}')
"
```

Expected: Active ~330-500, Archived ~5600+, Families ~33

**Step 5: Commit (no code changes, just verify)**

No code to commit — this is a verification step.

---

### Task 6: Signal Engine — Fingerprint-grouped evaluation

**Files:**
- Modify: `api/services/signal_engine.py:120-218` (generate_signals_stream)
- Modify: `api/services/signal_engine.py:256-339` (_evaluate_stock)

**Step 1: Modify _evaluate_stock to accept fingerprint groups**

In `signal_engine.py`, modify `_evaluate_stock` (line 225) to evaluate by fingerprint groups. The key change is: instead of iterating all strategies and computing indicators per-strategy, group regular strategies by fingerprint, compute indicators once per group, and evaluate conditions once per group.

Replace the `for strat in strategies:` loop (lines 256-339) in `_evaluate_stock`:

```python
    def _evaluate_stock(
        self,
        stock_code: str,
        trade_date: str,
        strategies: list[Strategy],
        stock_name: str = "",
        is_held: bool = False,
        sentiment_score: Optional[float] = None,
    ) -> Optional[dict]:
        """Evaluate all enabled strategies on a single stock.

        Strategies with the same signal_fingerprint share identical buy/sell
        conditions, so we evaluate conditions once per fingerprint group.
        """
        from datetime import datetime, timedelta
        from collections import defaultdict

        end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=250)
        start_str = start_dt.strftime("%Y-%m-%d")

        df = self.collector.get_daily_df(stock_code, start_str, trade_date)
        if df is None or df.empty or len(df) < 60:
            return None

        buy_triggered = False
        buy_strategies: list[str] = []
        sell_triggered = False
        sell_strategies: list[str] = []

        # Pre-load member strategies for combo strategies (cache by strat id)
        combo_members_cache: dict[int, list[Strategy]] = {}

        # Group regular strategies by fingerprint for batch evaluation
        fp_groups: dict[str, list[Strategy]] = defaultdict(list)
        combo_strats: list[Strategy] = []

        for strat in strategies:
            pf_config = strat.portfolio_config or {}
            if pf_config.get("type") == "combo":
                combo_strats.append(strat)
            elif strat.signal_fingerprint:
                fp_groups[strat.signal_fingerprint].append(strat)
            else:
                # No fingerprint yet — treat as solo group
                fp_groups[f"_solo_{strat.id}"].append(strat)

        # ── Evaluate fingerprint groups (one eval per group) ──
        for fp, group in fp_groups.items():
            representative = group[0]
            buy_conds = representative.buy_conditions or []
            sell_conds = representative.sell_conditions or []
            all_conds = buy_conds + sell_conds
            if not all_conds:
                continue

            collected = collect_indicator_params(all_conds)
            config = IndicatorConfig.from_collected_params(collected)
            full_df = self.indicator_engine.compute(df, config=config)

            if buy_conds:
                triggered, _ = evaluate_conditions(buy_conds, full_df, mode="AND")
                if triggered:
                    buy_triggered = True
                    for s in group:
                        buy_strategies.append(s.name)

            if is_held and sell_conds:
                triggered, _ = evaluate_conditions(sell_conds, full_df, mode="OR")
                if triggered:
                    sell_triggered = True
                    for s in group:
                        sell_strategies.append(s.name)

        # ── Evaluate combo strategies (unchanged) ──
        for strat in combo_strats:
            pf_config = strat.portfolio_config or {}
            member_ids = pf_config.get("member_ids", [])
            if strat.id not in combo_members_cache:
                combo_members_cache[strat.id] = (
                    self.db.query(Strategy)
                    .filter(Strategy.id.in_(member_ids))
                    .all()
                )
            members = combo_members_cache[strat.id]
            vote_threshold = pf_config.get("vote_threshold", 2)
            sell_mode = pf_config.get("sell_mode", "any")

            all_member_conds = []
            for m in members:
                all_member_conds.extend(m.buy_conditions or [])
                all_member_conds.extend(m.sell_conditions or [])
            if not all_member_conds:
                continue

            collected = collect_indicator_params(all_member_conds)
            config = IndicatorConfig.from_collected_params(collected)
            full_df = self.indicator_engine.compute(df, config=config)

            buy_votes = 0
            voting_members: list[str] = []
            for m in members:
                m_buy = m.buy_conditions or []
                if m_buy:
                    triggered, _ = evaluate_conditions(m_buy, full_df, mode="AND")
                    if triggered:
                        buy_votes += 1
                        voting_members.append(m.name)

            if buy_votes >= vote_threshold:
                buy_triggered = True
                buy_strategies.append(f"{strat.name}({buy_votes}/{len(members)}票)")

            if is_held:
                sell_votes = 0
                for m in members:
                    m_sell = m.sell_conditions or []
                    if m_sell:
                        triggered, _ = evaluate_conditions(m_sell, full_df, mode="OR")
                        if triggered:
                            sell_votes += 1

                if sell_mode == "any" and sell_votes > 0:
                    sell_triggered = True
                    sell_strategies.append(strat.name)
                elif sell_mode == "majority" and sell_votes > len(members) / 2:
                    sell_triggered = True
                    sell_strategies.append(strat.name)

        # ── Action determination (unchanged from here) ──
        if sell_triggered:
            action = "sell"
        elif buy_triggered:
            action = "buy"
        else:
            action = "hold"

        if action == "hold":
            return None

        if sentiment_score is not None and action == "buy" and sentiment_score < 30:
            if len(buy_strategies) < 2:
                return None

        matched = sell_strategies if action == "sell" else buy_strategies
        seen: set[str] = set()
        reasons = []
        for name in matched:
            if name not in seen:
                seen.add(name)
                reasons.append(name)

        alpha_score = 0.0
        score_breakdown = {"oversold": 0.0, "consensus": 0.0, "volume_price": 0.0}
        if action == "buy":
            alpha_score, score_breakdown = self._compute_alpha_score(
                df, buy_strategies, len(strategies)
            )

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "action": action,
            "reasons": reasons,
            "sentiment_score": sentiment_score,
            "alpha_score": alpha_score,
            "score_breakdown": score_breakdown,
        }
```

**Step 2: Update strategy loading to filter archived**

In `generate_signals_stream` (line 131), update the query to exclude archived strategies:

```python
        query = self.db.query(Strategy).filter(
            Strategy.enabled.is_(True),
            Strategy.archived_at.is_(None),
        )
```

Also update `generate_signals` (the non-streaming version, if it exists) with the same filter.

**Step 3: Verify signal engine still works**

```bash
# Quick check: load and count strategies
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import SessionLocal
from api.models.strategy import Strategy
db = SessionLocal()
active = db.query(Strategy).filter(Strategy.enabled.is_(True), Strategy.archived_at.is_(None)).count()
total = db.query(Strategy).count()
print(f'Signal engine will evaluate: {active} active (of {total} total)')

# Count unique fingerprints
from sqlalchemy import func
fps = db.query(func.count(func.distinct(Strategy.signal_fingerprint))).filter(
    Strategy.archived_at.is_(None), Strategy.signal_fingerprint.isnot(None)
).scalar()
print(f'Unique fingerprints (condition evaluations per stock): {fps}')
db.close()
"
```

**Step 4: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "perf(signal): evaluate buy/sell conditions once per fingerprint group"
```

---

### Task 7: Signal Scheduler — Insert daily health check

**Files:**
- Modify: `api/services/signal_scheduler.py:222-237`

**Step 1: Add health check before signal generation**

In `signal_scheduler.py`, before Step 4 (line 222 `# Step 4: Generate trading signals`), insert a health check step:

```python
                    # Step 3b: Strategy pool health check
                    self._sync_step = "策略池检查"
                    jm.update_progress(job_id, 75, "策略池健康检查")
                    try:
                        from api.services.strategy_pool import StrategyPoolManager
                        pool_mgr = StrategyPoolManager(db)
                        health = pool_mgr.daily_health_check()
                        logger.info(
                            "Pool health: %d active, %d families, %d oversized",
                            health["active_strategies"],
                            health["family_count"],
                            health["oversized_families"],
                        )
                    except Exception as e:
                        logger.warning("Pool health check failed (non-fatal): %s", e)
```

Insert this between Step 3 (exit monitoring, ends ~line 220) and Step 4 (signal generation, starts ~line 222).

**Step 2: Commit**

```bash
git add api/services/signal_scheduler.py
git commit -m "feat(scheduler): add strategy pool health check before signal generation"
```

---

### Task 8: Explore-strategies SKILL — Add Step 7b

**Files:**
- Modify: `.claude/skills/explore-strategies/SKILL.md`

**Step 1: Add Step 7b after Step 7 (Auto-Promote)**

After the Step 7 section (Auto-Promote) in the SKILL.md file, add:

```markdown
## Step 7b: Strategy Pool Rebalance

After promoting new strategies, rebalance the pool to archive redundant strategies:

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
import subprocess, json

def api_post(path, params=''):
    url = f'http://127.0.0.1:8050/api/{path}'
    if params: url += f'?{params}'
    r = subprocess.run(['curl','-s','-X','POST',url],
                       capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

# First dry-run to see what would change
dry = api_post('strategies/pool/rebalance', 'max_per_family=15&dry_run=true')
print(f'Dry-run: {dry.get(\"families_count\",0)} families, would archive {dry.get(\"archived_count\",0)}, active={dry.get(\"active_strategies\",0)}')

# Execute rebalance
result = api_post('strategies/pool/rebalance', 'max_per_family=15')
print(f'Rebalance: {result.get(\"families_count\",0)} families, archived {result.get(\"archived_count\",0)}, active={result.get(\"active_strategies\",0)}')
"
```

Output summary:
```
策略池 Rebalance: X 家族, 归档 Y 个冗余策略, 当前活跃 Z 个
```
```

**Step 2: Commit**

```bash
git add .claude/skills/explore-strategies/SKILL.md
git commit -m "feat(skill): add Step 7b strategy pool rebalance to explore-strategies"
```

---

### Task 9: Frontend — Family view on strategies page

**Files:**
- Modify: `web/src/app/strategies/page.tsx`
- Modify: `web/src/lib/api.ts` (add pool API calls)
- Modify: `web/src/types/index.ts` (add types)

**Step 1: Add TypeScript types**

In `web/src/types/index.ts`, add:

```typescript
export interface FamilySummary {
  fingerprint: string;
  representative_name: string;
  active_count: number;
  archived_count: number;
  champion_score: number;
  champion_id: number;
  avg_score: number;
  regime_coverage: string[];
  exit_param_range: {
    sl: [number, number];
    tp: [number, number];
    mhd: [number, number];
  };
}

export interface PoolStatus {
  total_strategies: number;
  active_strategies: number;
  archived_strategies: number;
  family_count: number;
  families_summary: FamilySummary[];
  regime_coverage: Record<string, { families: number; strategies: number }>;
  last_rebalance_at: string | null;
  signal_eval_reduction: string;
}
```

**Step 2: Add API functions**

In `web/src/lib/api.ts`, add:

```typescript
export async function getPoolStatus(): Promise<PoolStatus> {
  return request('/api/strategies/pool/status');
}

export async function rebalancePool(maxPerFamily = 15, dryRun = false): Promise<any> {
  return request(`/api/strategies/pool/rebalance?max_per_family=${maxPerFamily}&dry_run=${dryRun}`, {
    method: 'POST',
  });
}

export async function listFamilies(): Promise<FamilySummary[]> {
  return request('/api/strategies/families');
}
```

**Step 3: Add pool status card and family view to strategies page**

This is the largest frontend change. Add a "Pool Status" card at the top of the strategies page showing:
- Active / Archived / Total counts
- Family count
- Signal eval reduction metric
- A "Rebalance" button (with confirmation)

Below the status card, add a "Family View" tab that shows strategies grouped by fingerprint in collapsible sections.

The exact React implementation depends on the existing page structure. Read `web/src/app/strategies/page.tsx` to understand the current layout before implementing.

Key UI elements:
- **Stats bar**: `活跃 420 | 归档 5699 | 家族 33 | 评估优化 6119→33/stock`
- **Rebalance button**: `POST /api/strategies/pool/rebalance` with loading state
- **Family accordion**: Each family shows champion name + score, expandable to show all members
- **Archive badge**: Gray badge on archived strategies

**Step 4: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/app/strategies/page.tsx
git commit -m "feat(web): add strategy pool status card and family view"
```

---

### Task 10: End-to-end verification

**Step 1: Verify full flow**

```bash
# 1. Check pool status
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/strategies/pool/status" | python3 -c "
import json, sys; d = json.load(sys.stdin)
print(f'Active: {d[\"active_strategies\"]}, Families: {d[\"family_count\"]}')
"

# 2. List families
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/strategies/families" | python3 -c "
import json, sys; fams = json.load(sys.stdin)
for f in fams[:5]:
    print(f'{f[\"representative_name\"][:50]}: {f[\"active_count\"]} active, score={f[\"champion_score\"]:.4f}')
"

# 3. Verify signal generation only loads active strategies
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import SessionLocal
from api.models.strategy import Strategy
db = SessionLocal()
active = db.query(Strategy).filter(Strategy.enabled.is_(True), Strategy.archived_at.is_(None)).count()
print(f'Signal engine will load: {active} strategies (was 6119)')
db.close()
"

# 4. Test unarchive
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://127.0.0.1:8050/api/strategies/13920/unarchive" | python3 -m json.tool
```

**Step 2: Verify daily health check integration**

```bash
NO_PROXY=localhost,127.0.0.1 python3 -c "
from api.models.base import SessionLocal
from api.services.strategy_pool import StrategyPoolManager
db = SessionLocal()
mgr = StrategyPoolManager(db)
health = mgr.daily_health_check()
print(f'Health: {health}')
db.close()
"
```

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete strategy pool optimization — fingerprint families, rebalance, signal speedup"
```
