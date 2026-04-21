# StockAgent Decision Layer Upgrade — Spec & Execution Plan

## Context

StockAgent is a personal A-share quantitative trading system (FastAPI + Next.js + PostgreSQL). The system currently has four scoring dimensions for trade signals:

- **Alpha (0-100)**: Strategy consensus — how many independent strategy families triggered a buy signal, weighted by backtest quality and simplicity
- **Beta (0-1)**: Market environment probability — regime, sentiment, sector heat, valuation, computed by XGBoost or rule-based scorecard
- **Gamma (0-100)**: Technical structure confirmation — Chan Theory (缠论) buy point strength, weekly resonance, divergence confirmation
- **Confidence (0-100)**: Logistic Regression model predicting trade win probability from alpha+gamma+market features

**Current problem**: Beta and Confidence both predict "will this trade be profitable" but neither participates in decision-making. Combined Score (which determines plan ranking) only uses Alpha+Gamma. Position sizing is fixed at 100k CNY per trade regardless of confidence. No pre-plan risk gate exists.

**Goal**: Restructure the scoring pipeline so that:
1. Combined Score = Alpha + Gamma + Beta (three-factor ranking)
2. Confidence determines position sizing (not ranking)
3. Risk Gate blocks obviously bad plans before creation
4. Exploration engine gets multiple-testing correction
5. Strategy pool gets overlap dedup and decay monitoring

---

## Architecture After Changes

```
Signal Trigger (signal_engine)
  |
  v
Alpha (0-100) -- consensus --\
Gamma (0-100) -- structure ---+-> Combined Score (0~1) -> plan ranking
Beta  (0-1)   -- environment -/
  |
  v
Risk Gate -- ST? limit-up? daily loss? -- block if fails
  |
  v
Confidence (0-100) -- win probability -> position sizing (0.5x / 1.0x / 1.5x)
  |
  v
BotTradePlan (sorted by combined_score, sized by confidence)
  |
  v
Execution -> Review -> Training data feedback
  |
  v
Exploration Engine
  |-- DSR dynamic threshold (more tests -> higher bar)
  |-- Signal overlap dedup (Jaccard > 0.80 -> drop weaker)
  +-- Champion decay monitor (dormant 60d / 3 consecutive losses -> demote)
```

---

## Change List (10 items, 3 priorities)

### P0-A: Beta Joins Combined Score

**File**: `api/services/beta_scorer.py`

**Rationale**: Beta measures market environment favorability (regime, sentiment, sector heat, PE valuation). Currently computed but not used for ranking. Adding it to combined_score makes ranking aware of market conditions, not just signal strength.

#### Step 1: Replace weight tables (lines 22-33)

DELETE the old tables:
```python
WEIGHT_TABLE = {
    "cold": (0.80, 0.20),
    "warm": (0.60, 0.40),
    "mature": (0.50, 0.50),
}

# Gamma weight table: (alpha_weight, gamma_weight)
GAMMA_WEIGHT_TABLE = {
    "cold": (0.80, 0.20),     # < 30 completed trades with gamma
    "warm": (0.60, 0.40),     # 30-99
    "mature": (0.50, 0.50),   # >= 100
}
```

REPLACE WITH:
```python
# Three-factor weight table: (alpha, gamma, beta)
# Alpha = strategy consensus, Gamma = structure confirmation, Beta = environment
WEIGHT_TABLE_3F = {
    "cold":   (0.70, 0.15, 0.15),   # little data — trust strategy signals most
    "warm":   (0.50, 0.30, 0.20),   # gamma proven — increase structure weight
    "mature": (0.40, 0.30, 0.30),   # beta ML mature — full three-factor
}

# Two-factor fallback when gamma is unavailable: (alpha, beta)
WEIGHT_TABLE_2F = {
    "cold":   (0.85, 0.15),
    "warm":   (0.70, 0.30),
    "mature": (0.60, 0.40),
}

_PHASE_ORDER = ["cold", "warm", "mature"]
```

#### Step 2: Change phase calculation (lines 141-143)

DELETE:
```python
    beta_phase = _get_phase(db)
    gamma_phase = _get_gamma_phase(db)
    alpha_w, gamma_w = GAMMA_WEIGHT_TABLE[gamma_phase]
```

REPLACE WITH:
```python
    beta_phase = _get_phase(db)
    gamma_phase = _get_gamma_phase(db)
    # Use the more conservative phase for weight selection
    phase = min(beta_phase, gamma_phase,
                key=lambda p: _PHASE_ORDER.index(p))
```

#### Step 3: Restructure signal loop — move beta computation before combined (lines 192-225)

The current code computes combined_score BEFORE beta, then marks beta as "not for ranking". The new code must compute beta FIRST, then include it in combined_score.

DELETE lines 192-225 (from `# Score the stock` through `beta = predict_beta_score(db, features)`).

REPLACE WITH:
```python
        # Score the stock (same alpha/gamma/beta for all sub-positions of this signal)
        alpha = signal.final_score or 0.0
        gamma = signal.gamma_score  # May be None if chanlun-pro was unavailable

        # Build feature context for beta prediction
        features = {
            "stock_code": code,
            "alpha_score": alpha,
            "day_of_week": datetime.now().weekday(),
            **shared_context,
            **_load_stock_beta_context(db, code),
        }

        # Add gamma features for beta ML model
        if gamma is not None:
            from api.models.gamma_factor import GammaSnapshot as GS
            snap = db.query(GS).filter_by(
                stock_code=code, snapshot_date=trade_date
            ).first()
            if snap:
                features["gamma_score"] = snap.gamma_score
                features["daily_mmd_type"] = snap.daily_mmd_type
                features["daily_mmd_age"] = snap.daily_mmd_age
                features["weekly_resonance"] = snap.weekly_resonance

        beta = predict_beta_score(db, features)

        # Three-factor combined score: alpha(consensus) + gamma(structure) + beta(environment)
        if gamma is not None:
            alpha_w, gamma_w, beta_w = WEIGHT_TABLE_3F[phase]
            combined = round(
                (alpha / 100.0) * alpha_w + (gamma / 100.0) * gamma_w + beta * beta_w,
                4,
            )
        else:
            alpha_w, beta_w = WEIGHT_TABLE_2F[phase]
            combined = round(
                (alpha / 100.0) * alpha_w + beta * beta_w,
                4,
            )
```

#### Step 4: Update thinking string (line ~327)

FIND:
```python
                thinking=(
                    f"[C={confidence or '?'}] {strategy_name or 'signal'} "
                    f"alpha={alpha:.1f} gamma={gamma or 0:.1f} "
                    f"combined={combined:.4f}"
                ),
```

REPLACE WITH:
```python
                thinking=(
                    f"[C={confidence or '?'}] {strategy_name or 'signal'} "
                    f"alpha={alpha:.1f} beta={beta:.2f} gamma={gamma or 0:.1f} "
                    f"combined={combined:.4f}"
                ),
```

#### Step 5: Update log line (line ~383)

FIND:
```python
        logger.info(
            "Beta scorer: %d plans (%d stocks) for %s (gamma_phase=%s)",
            len(plans),
            len({p["stock_code"] for p in plans}),
            plan_date,
            gamma_phase,
        )
```

REPLACE WITH:
```python
        logger.info(
            "Beta scorer: %d plans (%d stocks) for %s (phase=%s, beta=%s, gamma=%s)",
            len(plans),
            len({p["stock_code"] for p in plans}),
            plan_date, phase, beta_phase, gamma_phase,
        )
```

#### Step 6: Update return dict (line ~377)

FIND: `"phase": gamma_phase,`
REPLACE WITH: `"phase": phase,`

---

**File**: `api/services/signal_engine.py` (lines 788-795)

This is a display-only combined_score computed in `_format_signal()`. It currently uses hardcoded cold-start 80/20 weights. Sync to new three-factor structure with beta neutral value.

FIND:
```python
        # Combined score for display purposes.
        # Uses cold-start weights (80/20) as a static approximation.
        # The actual decision-time combined_score lives in BotTradePlan
        # and uses dynamic phase-based weights from _get_gamma_phase().
        if row.gamma_score is not None:
            combined = round((alpha_score / 100.0) * 0.8 + (row.gamma_score / 100.0) * 0.2, 4)
        else:
            combined = round(alpha_score / 100.0, 4)
```

REPLACE WITH:
```python
        # Combined score for display purposes (static cold-start approximation).
        # The actual decision-time combined_score lives in BotTradePlan
        # and uses dynamic phase-based weights with real beta values.
        _BETA_NEUTRAL = 0.5  # neutral beta for display when not yet computed
        if row.gamma_score is not None:
            combined = round(
                (alpha_score / 100.0) * 0.70 + (row.gamma_score / 100.0) * 0.15 + _BETA_NEUTRAL * 0.15,
                4,
            )
        else:
            combined = round(
                (alpha_score / 100.0) * 0.85 + _BETA_NEUTRAL * 0.15,
                4,
            )
```

---

**File**: `api/services/claude_runner.py` (line ~94)

FIND:
```python
  - beta_score: copy directly from /api/bot/plans/pending for this stock (the "beta_score" field). If not available, use 50 (neutral).
```

REPLACE WITH:
```python
  - beta_score: environment factor (0-1) reflecting market regime, sector heat, valuation, and sentiment. Already factored into combined_score. 0.5=neutral, >0.6=favorable, <0.4=unfavorable.
```

---

### P0-B: Confidence Controls Position Sizing

**File**: `api/services/beta_scorer.py`

**Rationale**: Currently every plan gets a fixed ~100k CNY position. Confidence (LR model predicting win probability) should scale position size — high confidence = larger position, low confidence = smaller.

#### Step 1: Remove fixed quantity calculation from per-signal level

FIND (lines 231-233, currently OUTSIDE the strategy loop):
```python
        quantity = int(100_000 / plan_price / 100) * 100
        if quantity <= 0:
            quantity = 100
```

REPLACE WITH:
```python
        base_quantity = int(100_000 / plan_price / 100) * 100
        if base_quantity <= 0:
            base_quantity = 100
```

#### Step 2: Add confidence-based sizing inside the strategy loop

FIND the line just before `plan = BotTradePlan(` (line ~317). INSERT BEFORE IT:

```python
            # Position sizing based on confidence score
            if confidence is not None and confidence >= 65:
                quantity = max(100, int(base_quantity * 1.5 / 100) * 100)
            elif confidence is not None and confidence >= 45:
                quantity = base_quantity
            else:
                # Low confidence or no model — half position
                quantity = max(100, int(base_quantity * 0.5 / 100) * 100)
```

---

### P0-C: Risk Gate (Pre-Plan Safety Checks)

**File**: `api/services/beta_scorer.py`

**Rationale**: Currently plans are created for any stock with a buy signal, including ST stocks, stocks at limit-up (can't buy), and when the portfolio has already exceeded daily loss limits. These should be blocked before plan creation.

#### Step 1: Add daily loss circuit breaker

FIND (inside `score_and_create_plans`, after `shared_context = ...`, before the signal loop):
```python
    # Pre-load current counts per stock to enforce concentration limit
```

INSERT BEFORE THAT LINE:
```python
    # Daily loss circuit breaker
    _DAILY_LOSS_LIMIT = -5.0  # percent — stop creating new plans if today's avg sell P&L is worse
    if _daily_loss_exceeded(db, trade_date, _DAILY_LOSS_LIMIT):
        logger.warning("Beta scorer: daily loss limit %.1f%% exceeded, no new plans", _DAILY_LOSS_LIMIT)
        return []

```

#### Step 2: Add per-stock risk gate call

FIND (inside the signal loop, after the concentration check):
```python
        available_slots = MAX_POSITIONS_PER_STOCK - current_count
```

INSERT AFTER:
```python
        # Risk gate: block ST, limit-up, suspended stocks
        if _is_blocked(db, code, trade_date):
            continue
```

#### Step 3: Add the two new functions at the end of the file

APPEND to the end of `beta_scorer.py`:

```python

def _is_blocked(db: Session, stock_code: str, trade_date: str) -> bool:
    """Pre-plan safety checks: ST, limit-up (can't buy at open)."""
    from api.models.stock import Stock, DailyPrice
    from src.backtest.engine import calc_limit_prices
    from api.services.bot_trading_engine import _get_prev_close

    # ST / delisting check
    stock = db.query(Stock).filter(Stock.code == stock_code).first()
    if stock and stock.name and ("ST" in stock.name or "退" in stock.name):
        logger.debug("Risk gate: %s blocked (ST/delisting)", stock_code)
        return True

    # Limit-up check: if today's open >= limit_up, can't buy (no liquidity)
    prev_close = _get_prev_close(db, stock_code, trade_date)
    if prev_close and prev_close > 0:
        limit_up, _ = calc_limit_prices(stock_code, prev_close)
        today = db.query(DailyPrice).filter(
            DailyPrice.stock_code == stock_code,
            DailyPrice.trade_date == trade_date,
        ).first()
        if today and today.open >= limit_up:
            logger.debug("Risk gate: %s blocked (limit-up at open)", stock_code)
            return True

    return False


def _daily_loss_exceeded(db: Session, trade_date: str, limit_pct: float) -> bool:
    """Return True if today's average realized sell P&L is worse than limit_pct."""
    from api.models.bot_trading import BotTrade
    today_sells = (
        db.query(BotTrade)
        .filter(BotTrade.trade_date == trade_date, BotTrade.action == "sell")
        .all()
    )
    if not today_sells:
        return False
    total_pnl = sum(t.pnl_pct or 0 for t in today_sells)
    avg_pnl = total_pnl / len(today_sells)
    return avg_pnl < limit_pct
```

---

### P0-D: Raise Confidence AUC Deployment Threshold

**File**: `api/services/confidence_scorer.py`

**Rationale**: Current AUC threshold of 0.52 is too low — a model that's 2% better than random has no economic value. Raise to 0.55.

There are 4 occurrences of `0.52` in `train_confidence_model()` (lines 228, 254, 256, 265). Change ALL of them:

FIND (line 228):
```python
    AUC guard: if AUC < 0.52, the model is not deployed (not marked as active).
```
REPLACE WITH:
```python
    AUC guard: if AUC < 0.55, the model is not deployed (not marked as active).
```

FIND (line 254):
```python
    if result["auc"] < 0.52:
```
REPLACE WITH:
```python
    if result["auc"] < 0.55:
```

FIND (line 256):
```python
            "Confidence model AUC %.4f < 0.52 — not deploying (samples=%d)",
```
REPLACE WITH:
```python
            "Confidence model AUC %.4f < 0.55 — not deploying (samples=%d)",
```

FIND (line 265):
```python
            "message": f"AUC {result['auc']:.4f} < 0.52 threshold — model not deployed.",
```
REPLACE WITH:
```python
            "message": f"AUC {result['auc']:.4f} < 0.55 threshold — model not deployed.",
```

---

### P1-E: DSR Simplified Multiple Testing Penalty

**File**: `api/services/exploration_engine.py`

**Rationale**: The system has tested 85,677 strategy candidates (from `experience.json` meta). More testing = higher chance of finding strategies that look good by luck. The StdA+ score threshold should rise with the number of candidates tested.

#### Step 1: Add import and dynamic threshold function

FIND (line ~206, after `STDA_WR = 60.0`):

INSERT AFTER:
```python

def _adjusted_stda_score(experience: dict) -> float:
    """Raise StdA+ score threshold based on total candidates tested.

    Simplified Deflated Sharpe intuition: more tests -> higher bar.
    At 10k candidates: 0.80 -> 0.82
    At 85k candidates: 0.80 -> 0.85
    At 500k candidates: 0.80 -> 0.88
    Capped at +0.10 above base.
    """
    import math
    total = experience.get("meta", {}).get("total_strategies_scanned", 0)
    if total <= 1000:
        return STDA_SCORE
    haircut = min(0.10, 0.02 * math.log10(total / 1000))
    return round(STDA_SCORE + haircut, 4)
```

#### Step 2: Make `is_stda_plus` accept optional threshold

FIND:
```python
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
```

REPLACE WITH:
```python
def is_stda_plus(
    score: float,
    total_return_pct: float,
    max_drawdown_pct: float,
    total_trades: int,
    win_rate: float,
    *,
    score_threshold: float | None = None,
) -> bool:
    """Return True if metrics meet StdA+ criteria."""
    threshold = score_threshold if score_threshold is not None else STDA_SCORE
    return (
        threshold <= score  # NOTE: changed from `score >= STDA_SCORE`
        and total_return_pct > STDA_RETURN
        and max_drawdown_pct < STDA_DD
        and total_trades >= STDA_TRADES
```

#### Step 3: Use dynamic threshold in promote step

FIND in `_step_promote_and_rebalance` (line ~2312):
```python
                if is_stda_plus(
                    s.get("score", 0),
                    s.get("total_return_pct", 0),
                    s.get("max_drawdown_pct", 100),
                    s.get("total_trades", 0),
                    s.get("win_rate", 0),
                ):
```

REPLACE WITH:
```python
                adjusted_score = _adjusted_stda_score(load_experience())
                if is_stda_plus(
                    s.get("score", 0),
                    s.get("total_return_pct", 0),
                    s.get("max_drawdown_pct", 100),
                    s.get("total_trades", 0),
                    s.get("win_rate", 0),
                    score_threshold=adjusted_score,
                ):
```

#### Step 4: Update promote log (line ~2364)

FIND:
```python
        logger.info("Promote complete: %d StdA+ (Standard A), %d regime champions (Standard B)",
                    promoted_a, promoted_b)
```

REPLACE WITH:
```python
        logger.info("Promote complete: %d StdA+ (threshold=%.4f), %d regime champions",
                    promoted_a, _adjusted_stda_score(load_experience()), promoted_b)
```

---

### P1-F: Strategy Signal Overlap Deduplication

**File**: `api/services/strategy_pool.py`

**Rationale**: Fingerprint dedup catches identical buy/sell conditions, but two strategies with slightly different parameters (e.g. RSI 47-67 vs RSI 48-68) can have 90%+ signal overlap. Within each family during rebalance, compute Jaccard similarity of recent signal triggers and drop the weaker redundant strategy.

#### Verified: ActionSignal model exists

`api/models/signal.py` has `ActionSignal` (table `action_signals_v2`) with fields:
- `stock_code` (String(6))
- `trade_date` (String(10))
- `action` (String(4)) — values: "BUY" / "SELL"
- `strategy_name` (String(100)) — **NOTE: uses strategy_name, NOT strategy_id**

Because ActionSignal uses `strategy_name` (not `strategy_id`), the overlap query must join through strategy name. Add the following method to `StrategyPoolManager` class:

```python
    def _deduplicate_by_overlap(self, strategies: list, max_overlap: float = 0.80) -> list:
        """Remove strategies whose recent buy triggers overlap > max_overlap with a better one.

        Uses Jaccard similarity on (stock_code, trade_date) pairs from last 180 days.
        Strategies are assumed to be pre-sorted by score descending.
        ActionSignal uses strategy_name (not strategy_id), so we match by name.
        """
        from api.models.signal import ActionSignal
        from datetime import date, timedelta

        cutoff = (date.today() - timedelta(days=180)).isoformat()
        keep = []
        signal_cache: dict[str, set] = {}  # strategy_name -> set of (code, date) pairs

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
                    logger.debug("Overlap dedup: S%d (%s) overlaps %.0f%% with S%d (%s)",
                                 s.id, sname, intersection / union * 100, kept.id, kname)
                    break

            if not is_redundant:
                keep.append(s)

        if len(keep) < len(strategies):
            logger.info("Overlap dedup: kept %d/%d strategies", len(keep), len(strategies))
        return keep
```

Then call it in `rebalance_by_skeleton()`, after `selected = self._select_diverse_top(members, max_per_family)` (line ~263):

```python
            selected = self._select_diverse_top(members, max_per_family)
            # Pass 1.5: deduplicate by signal overlap within family
            if len(selected) > 1:
                selected = self._deduplicate_by_overlap(selected)
```

---

### P1-G: Champion Decay Monitoring

**File**: `api/services/strategy_pool.py`

**Rationale**: Promoted champion strategies may stop triggering signals or start losing consistently. Auto-demote them.

Add this method to `StrategyPoolManager`:

```python
    def check_champion_decay(self) -> list[dict]:
        """Check champion strategies for performance decay and demote if needed.

        Rules:
        - dormant: no trade plan in 60+ days -> demote champion to active
        - losing: last 3 trade reviews all lost money -> demote to archive
        """
        from api.models.bot_trading import BotTradePlan, BotTradeReview
        from api.models.strategy import Strategy
        from datetime import date, timedelta, datetime

        champions = self.db.query(Strategy).filter(
            Strategy.family_role == "champion",
            Strategy.enabled.is_(True),
        ).all()

        demoted = []
        cutoff_60d = (date.today() - timedelta(days=60)).isoformat()

        for s in champions:
            # Check dormancy
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

            # Check losing streak
            recent_reviews = (
                self.db.query(BotTradeReview)
                .filter(BotTradeReview.strategy_id == s.id)
                .order_by(BotTradeReview.last_sell_date.desc())
                .limit(3)
                .all()
            )
            if len(recent_reviews) >= 3 and all((r.pnl_pct or 0) < 0 for r in recent_reviews):
                s.family_role = "archive"
                s.archived_at = datetime.now()
                demoted.append({"id": s.id, "name": s.name, "reason": "losing_streak_3"})
                logger.info("Decay: S%d champion->archive (3 consecutive losses)", s.id)

        if demoted:
            self.db.commit()
        return demoted
```

**File**: `api/services/exploration_engine.py`

Call decay check after rebalance in `_step_promote_and_rebalance`, at the end (after line ~2372):

FIND:
```python
        promoted = promoted_a + promoted_b
        self.step_detail = f"Promoted {promoted_a} StdA+ + {promoted_b} regime, rebalanced ({active} active, {archived} archived)"
        return promoted
```

INSERT BEFORE `return promoted`:
```python
        # Check champion decay (uses existing _api helper, router prefix is /api/strategies)
        try:
            decay_resp = _api("POST", "strategies/pool/check-decay")
            decay_count = decay_resp.get("demoted_count", 0)
            if decay_count:
                logger.info("Decay check: %d champions demoted", decay_count)
        except Exception as e:
            logger.warning("Decay check failed (non-fatal): %s", e)
```

**NOTE**: `_api()` is the exploration_engine's existing internal HTTP helper (already defined at the top of the file). It auto-prepends `http://127.0.0.1:8050/api/`. This requires a new API endpoint. Add to `api/routers/strategies.py` (router prefix is `/api/strategies`):

```python
@router.post("/pool/check-decay")
def check_champion_decay(db: Session = Depends(get_db)):
    """Run champion decay check — demote dormant or losing champions."""
    mgr = StrategyPoolManager(db)
    demoted = mgr.check_champion_decay()
    return {"demoted_count": len(demoted), "demoted": demoted}
```

---

### P2-H: DailyPrice Add snapshot_date and adjust_mode

**File**: `api/models/stock.py` (DailyPrice class, line ~39)

**Rationale**: Enables future point-in-time (PIT) data verification. Records when data was ingested and what adjustment mode it uses.

FIND:
```python
    adj_factor: Mapped[float] = mapped_column(Float, default=1.0)

    __table_args__ = (
```

REPLACE WITH:
```python
    adj_factor: Mapped[float] = mapped_column(Float, default=1.0)
    snapshot_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    adjust_mode: Mapped[str | None] = mapped_column(String(4), nullable=True)  # raw/qfq/hfq

    __table_args__ = (
```

**Database Migration** (run manually or via alembic):
```sql
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS snapshot_date DATE;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS adjust_mode VARCHAR(4);
```

**File**: `api/services/data_collector.py`

Find where `DailyPrice` objects are created (search for `DailyPrice(` in the file). Add to each creation:
```python
    snapshot_date=date.today(),
    adjust_mode="raw",
```

Add `from datetime import date` if not already imported.

---

### P2-I: Gamma Service Availability Monitoring

**File**: `api/services/beta_scorer.py`

**Rationale**: When chanlun-pro (localhost:9900) is down, all gamma_score values become None, and combined_score silently degrades to alpha-only. A warning log helps detect this.

FIND (inside `score_and_create_plans`, just before or after `plans.sort(...)`):
```python
    if plans:
        plans.sort(key=lambda x: x["combined_score"], reverse=True)
        db.commit()
```

INSERT AFTER `plans.sort(...)` and BEFORE `db.commit()`:
```python
        # Monitor gamma coverage — warn if chanlun-pro may be down
        gamma_count = sum(1 for p in plans if p.get("gamma_score") is not None)
        gamma_coverage = gamma_count / len(plans) if plans else 0
        if plans and gamma_coverage < 0.70:
            logger.warning(
                "Gamma coverage %.0f%% (%d/%d plans) — chanlun-pro may be unavailable",
                gamma_coverage * 100, gamma_count, len(plans),
            )
```

---

## Files Changed Summary

| Priority | File | Changes |
|----------|------|---------|
| P0-A | `api/services/beta_scorer.py` | Weight tables, phase calc, combined formula, thinking, log |
| P0-A | `api/services/signal_engine.py` | Display combined_score sync (~8 lines) |
| P0-A | `api/services/claude_runner.py` | AI prompt beta description (~3 lines) |
| P0-B | `api/services/beta_scorer.py` | base_quantity + confidence sizing (~10 lines) |
| P0-C | `api/services/beta_scorer.py` | `_is_blocked()`, `_daily_loss_exceeded()`, call sites (~50 lines) |
| P0-D | `api/services/confidence_scorer.py` | AUC 0.52 -> 0.55 (~1 line) |
| P1-E | `api/services/exploration_engine.py` | `_adjusted_stda_score()`, `is_stda_plus` param, promote call (~30 lines) |
| P1-F | `api/services/strategy_pool.py` | `_deduplicate_by_overlap()` + call site (~55 lines) |
| P1-G | `api/services/strategy_pool.py` | `check_champion_decay()` (~45 lines) |
| P1-G | `api/services/exploration_engine.py` | call decay after rebalance (~8 lines) |
| P1-G | `api/routers/strategies.py` | new endpoint `/pool/check-decay` (~6 lines) |
| P2-H | `api/models/stock.py` | 2 new columns on DailyPrice (~2 lines) |
| P2-H | `api/services/data_collector.py` | fill snapshot_date + adjust_mode (~3 lines) |
| P2-H | SQL migration | ALTER TABLE (~2 lines) |
| P2-I | `api/services/beta_scorer.py` | gamma coverage warning (~6 lines) |

## Files NOT Changed (confirmation)

- `api/models/bot_trading.py` — beta_score, combined_score, confidence fields already exist
- `api/schemas/bot_trading.py` — schema already has all fields
- `web/src/types/index.ts` — TypeScript types already have beta_score
- `api/routers/bot_trading.py` — sorts by combined_score.desc(), auto-reflects new values
- `api/routers/beta.py` — same, sorts by combined_score.desc()
- `api/services/beta_ml.py` — predict_beta_score() interface unchanged
- `api/services/beta_engine.py` — snapshot capture unchanged
- `api/services/signal_grader.py` — reads combined_score from DB, auto-reflects
- `api/services/diary_service.py` — read-only display

## Verification

### P0 Verification
1. Start the server: `python -m uvicorn api.main:app --port 8050`
2. Trigger signal scan: `POST /api/signals/scan`
3. Check plans: `GET /api/bot/plans/pending`
4. Verify:
   - `combined_score` values differ from before (beta influence visible)
   - `thinking` field contains `beta=X.XX`
   - Plans with high alpha but bad beta (bear market, cold sector) rank lower than before
   - ST stocks and limit-up stocks are NOT in the plan list
   - Plans with `confidence >= 65` have larger `quantity` than `confidence < 45` plans
5. Check logs for: `"phase=..."` in beta scorer log line

### P1 Verification
1. Run exploration: `POST /api/lab/exploration/start`
2. After a round completes, check logs for:
   - `"threshold=0.8XXX"` in promote log (dynamic threshold)
   - `"Decay check:"` in post-rebalance log
3. Call `POST /api/strategies/pool/check-decay` directly and verify response
4. Call `POST /api/strategies/pool/rebalance?max_per_family=15` and check for `"Overlap dedup:"` in logs

### P2 Verification
1. Run data collection: `POST /api/data/sync`
2. Query DB: `SELECT snapshot_date, adjust_mode FROM daily_prices ORDER BY id DESC LIMIT 5`
3. Verify new rows have `snapshot_date = today` and `adjust_mode = 'raw'`
4. Old rows should have `NULL` for both columns (backward compatible)

## Implementation Order

```
Day 1: P0-A (beta into combined) + P0-D (AUC threshold)
Day 2: P0-B (confidence sizing) + P0-C (risk gate)
Day 3: P1-E (DSR threshold)
Day 4: P1-F (overlap dedup) + P1-G (decay monitoring)
Day 5: P2-H (DailyPrice fields) + P2-I (gamma monitoring)
```

Each step is independently deployable. No cross-step hard dependencies.
