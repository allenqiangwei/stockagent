# Confidence 评分系统升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the confidence scoring system to be more accurate and trustworthy by enriching its input features (Gamma raw dimensions, Beta unique features, fixed Alpha), adding proper cross-validation and calibration monitoring, and providing the user with enough evidence to transition from observation to live trading.

**Architecture:** The confidence model is a LogisticRegression (currently AUC=0.825) that predicts trade win probability from 6 features. We upgrade it in 4 phases: (0) validate current model with time-series CV, (1) enrich inputs from 6 to ~15 features, (2) add calibration monitoring and regime analysis, (3) add frontend trust indicators. All changes are backward-compatible — the model retrains automatically.

**Tech Stack:** Python, sklearn LogisticRegression, SQLAlchemy, PostgreSQL, Next.js/React

---

## File Structure

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `api/services/confidence_scorer.py` | Core confidence model — features, training, prediction | Major modify |
| `api/services/signal_engine.py:585-648` | Alpha scoring — `_compute_alpha_score()` | Modify |
| `api/services/beta_scorer.py:192-225` | Where confidence is called with features | Modify |
| `api/models/confidence.py` | ConfidenceModel ORM | Minor modify |
| `api/routers/ai_lab.py` or `api/routers/ops.py` | API endpoint for model report + validation | Minor modify |
| `web/src/app/ai/page.tsx` | Frontend confidence display | Minor modify |
| `scripts/validate_confidence.py` | One-off validation script (Phase 0) | Create |

---

### Task 1: Phase 0 — Validate Current Model (Time-Series CV)

**Files:**
- Create: `scripts/validate_confidence.py`

This task answers the critical question: is AUC=0.825 real or overfitted?

- [ ] **Step 1: Create validation script**

```python
"""Validate confidence model with time-series cross-validation.

Splits data chronologically: train on first N months, test on next month.
Reports per-fold AUC, Brier, calibration, and regime breakdown.
"""
import numpy as np
from datetime import datetime
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sqlalchemy import text

from api.models.base import SessionLocal

FEATURE_NAMES = [
    "alpha_score", "gamma_score", "has_gamma",
    "trend_strength", "volatility", "index_return_pct",
]


def load_data(db):
    """Load training data with dates for time-series split."""
    sql = text("""
        SELECT p.alpha_score, p.gamma_score,
               mr.trend_strength, mr.volatility, mr.index_return_pct,
               r.pnl_pct, r.first_buy_date
        FROM bot_trade_plans p
        JOIN bot_trade_reviews r
            ON r.stock_code = p.stock_code
            AND r.strategy_id = p.strategy_id
            AND r.first_buy_date = p.plan_date
        JOIN market_regimes mr
            ON r.first_buy_date BETWEEN mr.week_start::text AND mr.week_end::text
        WHERE p.status = 'executed'
            AND p.direction = 'buy'
            AND p.alpha_score IS NOT NULL
        ORDER BY r.first_buy_date
    """)
    rows = db.execute(sql).fetchall()

    X, y, dates = [], [], []
    for row in rows:
        alpha = float(row[0]) if row[0] is not None else 0.0
        gamma = float(row[1]) if row[1] is not None else 0.0
        has_gamma = 1.0 if row[1] is not None else 0.0
        trend = float(row[2]) if row[2] is not None else 0.0
        vol = float(row[3]) if row[3] is not None else 0.0
        idx_ret = float(row[4]) if row[4] is not None else 0.0
        pnl = float(row[5]) if row[5] is not None else 0.0

        X.append([alpha, gamma, has_gamma, trend, vol, idx_ret])
        y.append(1 if pnl > 0 else 0)
        dates.append(str(row[6]))

    return np.array(X), np.array(y), dates


def time_series_cv(X, y, dates, n_splits=5):
    """Expanding window CV: train on first k folds, test on fold k+1."""
    unique_weeks = sorted(set(d[:7] for d in dates))  # YYYY-MM granularity
    fold_size = len(unique_weeks) // (n_splits + 1)

    results = []
    for i in range(n_splits):
        train_end_month = unique_weeks[(i + 1) * fold_size]
        test_end_month = unique_weeks[min((i + 2) * fold_size, len(unique_weeks) - 1)]

        train_mask = np.array([d[:7] <= train_end_month for d in dates])
        test_mask = np.array([train_end_month < d[:7] <= test_end_month for d in dates])

        if test_mask.sum() < 10:
            continue

        X_train, y_train = X[train_mask], y[train_mask]
        X_test, y_test = X[test_mask], y[test_mask]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        lr = LogisticRegression(C=1.0, max_iter=1000)
        lr.fit(X_train_s, y_train)

        proba = lr.predict_proba(X_test_s)[:, 1]
        auc = roc_auc_score(y_test, proba)
        brier = brier_score_loss(y_test, proba)

        # Calibration: bin probabilities and compare to actual rates
        bins = [0, 0.3, 0.5, 0.6, 0.7, 0.8, 1.01]
        cal_rows = []
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (proba >= lo) & (proba < hi)
            if mask.sum() >= 5:
                actual = y_test[mask].mean()
                predicted = proba[mask].mean()
                cal_rows.append(f"    [{lo:.1f}-{hi:.1f}) n={mask.sum():>4} predicted={predicted:.3f} actual={actual:.3f}")

        results.append({
            "fold": i + 1,
            "train": train_mask.sum(),
            "test": test_mask.sum(),
            "auc": auc,
            "brier": brier,
            "test_period": f"{train_end_month}~{test_end_month}",
            "calibration": cal_rows,
        })

    return results


if __name__ == "__main__":
    db = SessionLocal()
    try:
        X, y, dates = load_data(db)
        print(f"Total samples: {len(y)}")
        print(f"Positive rate: {y.mean():.3f}")
        print(f"Date range: {dates[0]} ~ {dates[-1]}")
        print()

        results = time_series_cv(X, y, dates)

        aucs = []
        for r in results:
            print(f"Fold {r['fold']}: {r['test_period']} train={r['train']} test={r['test']}")
            print(f"  AUC={r['auc']:.4f}  Brier={r['brier']:.4f}")
            for c in r["calibration"]:
                print(c)
            print()
            aucs.append(r["auc"])

        print(f"=== Summary ===")
        print(f"In-sample AUC (current model): 0.8248")
        print(f"CV AUC: mean={np.mean(aucs):.4f} std={np.std(aucs):.4f}")
        print(f"CV AUC range: {min(aucs):.4f} ~ {max(aucs):.4f}")
        if np.mean(aucs) >= 0.80:
            print("VERDICT: Model is genuinely strong (CV confirms in-sample)")
        elif np.mean(aucs) >= 0.70:
            print("VERDICT: Model is decent but some overfitting (CV < in-sample)")
        else:
            print("VERDICT: Model is overfitted (CV much lower than in-sample)")
    finally:
        db.close()
```

- [ ] **Step 2: Run validation**

Run: `cd /Users/allenqiang/stockagent && python scripts/validate_confidence.py`

Record the CV-AUC result. If CV-AUC >= 0.75, proceed to Task 2. If < 0.70, the model is overfitted and Task 2 becomes critical (not optional).

- [ ] **Step 3: Commit**

```bash
git add scripts/validate_confidence.py
git commit -m "feat: add confidence model time-series cross-validation script"
```

---

### Task 2: Gamma Raw Features — Expand 1 Score to 6 Dimensions

**Files:**
- Modify: `api/services/confidence_scorer.py:21-28` (FEATURE_NAMES)
- Modify: `api/services/confidence_scorer.py:116-159` (_build_training_data)
- Modify: `api/services/confidence_scorer.py:273-314` (predict_confidence)
- Modify: `api/services/beta_scorer.py:192-225` (where confidence is called)

- [ ] **Step 1: Update FEATURE_NAMES**

In `api/services/confidence_scorer.py`, replace:

```python
FEATURE_NAMES = [
    "alpha_score",
    "gamma_score",
    "has_gamma",
    "trend_strength",
    "volatility",
    "index_return_pct",
]
```

with:

```python
FEATURE_NAMES = [
    "alpha_score",
    # Gamma raw dimensions (replacing single gamma_score)
    "gamma_daily_strength",
    "gamma_weekly_resonance",
    "gamma_structure_health",
    "gamma_mmd_age",
    "gamma_bc_confirmed",
    "has_gamma",
    # Market context (from Beta's unique features)
    "trend_strength",
    "volatility",
    "index_return_pct",
    "sector_heat_score",
    "regime_encoded",
    "day_of_week",
    "stock_return_5d",
    "volume_ratio_5d",
]
```

- [ ] **Step 2: Update _build_training_data to join gamma_snapshots and beta_snapshots**

Replace the `_build_training_data` function:

```python
def _build_training_data(db: Session) -> tuple[np.ndarray, np.ndarray]:
    """Build training data from executed buy plans joined with gamma, market, and review data.

    Returns (X, y) where X has columns matching FEATURE_NAMES and
    y is binary (1 = profitable, 0 = loss).
    """
    sql = text("""
        SELECT p.alpha_score,
               gs.daily_strength, gs.weekly_resonance, gs.structure_health,
               gs.daily_mmd_age,
               CASE WHEN gs.id IS NOT NULL THEN 1.0 ELSE 0.0 END as has_gamma,
               mr.trend_strength, mr.volatility, mr.index_return_pct,
               bs.sector_heat_score, bs.market_regime, bs.day_of_week,
               bs.stock_return_5d, bs.volume_ratio_5d,
               r.pnl_pct
        FROM bot_trade_plans p
        JOIN bot_trade_reviews r
            ON r.stock_code = p.stock_code
            AND r.strategy_id = p.strategy_id
            AND r.first_buy_date = p.plan_date
        JOIN market_regimes mr
            ON r.first_buy_date BETWEEN mr.week_start::text AND mr.week_end::text
        LEFT JOIN gamma_snapshots gs
            ON gs.stock_code = p.stock_code AND gs.snapshot_date = p.plan_date
        LEFT JOIN beta_snapshots bs
            ON bs.stock_code = p.stock_code AND bs.snapshot_date = p.plan_date
        WHERE p.status = 'executed'
            AND p.direction = 'buy'
            AND p.alpha_score IS NOT NULL
    """)

    rows = db.execute(sql).fetchall()
    if not rows:
        return np.empty((0, len(FEATURE_NAMES))), np.empty(0)

    REGIME_MAP = {"trending_bull": 1, "ranging": 0, "trending_bear": -1, "volatile": -0.5}

    X_list, y_list = [], []
    for row in rows:
        def f(v): return float(v) if v is not None else 0.0

        bc_confirmed = 0.0
        if row[3] is not None:  # structure_health exists
            # bc_confirmed approximated: structure_health >= 10 means BC present
            bc_confirmed = 1.0 if f(row[3]) >= 10 else 0.0

        regime_str = row[10] if row[10] else "ranging"
        regime_enc = REGIME_MAP.get(regime_str, 0.0)

        X_list.append([
            f(row[0]),   # alpha_score
            f(row[1]),   # gamma_daily_strength
            f(row[2]),   # gamma_weekly_resonance
            f(row[3]),   # gamma_structure_health
            f(row[4]),   # gamma_mmd_age
            bc_confirmed,  # gamma_bc_confirmed
            f(row[5]),   # has_gamma
            f(row[6]),   # trend_strength
            f(row[7]),   # volatility
            f(row[8]),   # index_return_pct
            f(row[9]),   # sector_heat_score
            regime_enc,  # regime_encoded
            f(row[11]),  # day_of_week
            f(row[12]),  # stock_return_5d
            f(row[13]),  # volume_ratio_5d
        ])
        y_list.append(1 if f(row[14]) > 0 else 0)

    return np.array(X_list), np.array(y_list)
```

- [ ] **Step 3: Update predict_confidence to accept expanded features**

Replace the `predict_confidence` function signature and body:

```python
def predict_confidence(
    db: Session,
    alpha: float,
    gamma_snapshot: dict | None = None,
    trend_strength: float = 0.0,
    volatility: float = 0.0,
    index_return_pct: float = 0.0,
    sector_heat_score: float = 0.0,
    regime: str = "ranging",
    day_of_week: int = 0,
    stock_return_5d: float = 0.0,
    volume_ratio_5d: float = 0.0,
) -> float | None:
    """Predict trade confidence score (0-100) using the active model.

    Args:
        gamma_snapshot: dict with daily_strength, weekly_resonance,
                       structure_health, daily_mmd_age keys. None if no gamma.
    """
    global _cached_params

    params = None
    with _cache_lock:
        params = _cached_params

    if params is None:
        params = _load_active_model(db)
        if params is None:
            return None

    REGIME_MAP = {"trending_bull": 1, "ranging": 0, "trending_bear": -1, "volatile": -0.5}

    if gamma_snapshot:
        daily_strength = float(gamma_snapshot.get("daily_strength", 0))
        weekly_resonance = float(gamma_snapshot.get("weekly_resonance", 0))
        structure_health = float(gamma_snapshot.get("structure_health", 0))
        mmd_age = float(gamma_snapshot.get("daily_mmd_age", 0))
        bc_confirmed = 1.0 if structure_health >= 10 else 0.0
        has_gamma = 1.0
    else:
        daily_strength = weekly_resonance = structure_health = mmd_age = bc_confirmed = 0.0
        has_gamma = 0.0

    features = [
        float(alpha),
        daily_strength,
        weekly_resonance,
        structure_health,
        mmd_age,
        bc_confirmed,
        has_gamma,
        float(trend_strength),
        float(volatility),
        float(index_return_pct),
        float(sector_heat_score),
        float(REGIME_MAP.get(regime, 0)),
        float(day_of_week),
        float(stock_return_5d),
        float(volume_ratio_5d),
    ]

    try:
        score = _predict_from_params(params, features)
        return round(score, 1)
    except Exception as e:
        logger.warning("Confidence prediction failed: %s", e)
        return None
```

- [ ] **Step 4: Update beta_scorer.py call site**

In `api/services/beta_scorer.py`, find where `predict_confidence` is called (around line 192-225) and update it to pass expanded features. The exact location is inside `score_and_create_plans()`. Update the confidence call to:

```python
        # Build gamma snapshot dict for confidence model
        gamma_snap_dict = None
        if gamma is not None:
            from api.models.gamma_factor import GammaSnapshot as GS
            snap = db.query(GS).filter_by(
                stock_code=code, snapshot_date=trade_date
            ).first()
            if snap:
                gamma_snap_dict = {
                    "daily_strength": snap.daily_strength,
                    "weekly_resonance": snap.weekly_resonance,
                    "structure_health": snap.structure_health,
                    "daily_mmd_age": snap.daily_mmd_age,
                }

        # Confidence with enriched features
        conf = predict_confidence(
            db, alpha,
            gamma_snapshot=gamma_snap_dict,
            trend_strength=shared_context.get("trend_strength", 0),
            volatility=shared_context.get("volatility", 0),
            index_return_pct=shared_context.get("index_return_pct", 0),
            sector_heat_score=shared_context.get("sector_heat_score", 0),
            regime=shared_context.get("market_regime", "ranging"),
            day_of_week=datetime.now().weekday(),
            stock_return_5d=features.get("stock_return_5d", 0),
            volume_ratio_5d=features.get("volume_ratio_5d", 0),
        )
```

- [ ] **Step 5: Retrain model and compare**

```bash
cd /Users/allenqiang/stockagent
# Trigger retrain via API
curl -s -X POST "http://localhost:8050/api/ops/confidence/train" | python3 -m json.tool
```

Compare new AUC vs old 0.825. Log the result.

- [ ] **Step 6: Commit**

```bash
git add api/services/confidence_scorer.py api/services/beta_scorer.py
git commit -m "feat: expand confidence features — Gamma raw 6 dims + Beta market context"
```

---

### Task 3: Fix Alpha Scoring — Penalize Complexity Instead of Rewarding It

**Files:**
- Modify: `api/services/signal_engine.py:585-648` (`_compute_alpha_score`)

- [ ] **Step 1: Reverse condition depth from bonus to penalty**

In `api/services/signal_engine.py`, replace the `_compute_alpha_score` method's depth scoring section (lines 633-640):

```python
        # ── 3. Simplicity bonus (0-30): fewer conditions = more robust ──
        # Replaces old "condition depth" which rewarded complexity (overfitting).
        # 3 conditions (base RSI+ATR) = 30 (maximum), 4 = 20, 5 = 10, 6+ = 0
        max_conds = 0
        for s in buy_strategy_objects:
            n_conds = len(s.buy_conditions or [])
            if n_conds > max_conds:
                max_conds = n_conds
        simplicity_score = max(0.0, 30.0 - max(0, (max_conds - 3)) * 10.0)
```

Also update the return breakdown key from "diversity" to "simplicity":

```python
        total = float(round(count_score + quality_score + simplicity_score, 1))
        breakdown = {
            "count": float(round(count_score, 1)),
            "quality": float(round(quality_score, 1)),
            "simplicity": float(round(simplicity_score, 1)),
        }
        return total, breakdown
```

- [ ] **Step 2: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "fix: Alpha scoring — penalize complexity instead of rewarding it"
```

---

### Task 4: Add Calibration Monitoring to Confidence Model

**Files:**
- Modify: `api/services/confidence_scorer.py` (add calibration to training output)
- Modify: `api/models/confidence.py` (add calibration_data field)

- [ ] **Step 1: Add calibration_data field to ConfidenceModel**

In `api/models/confidence.py`, add:

```python
    calibration_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
```

- [ ] **Step 2: Compute and store calibration during training**

In `api/services/confidence_scorer.py`, inside `_train_lr()`, after computing AUC and Brier, add calibration computation:

```python
    # Calibration curve: bin predictions, compare to actual positive rate
    bins = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    calibration = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (proba >= lo) & (proba < hi)
        if mask.sum() >= 5:
            calibration.append({
                "bin": f"{lo:.1f}-{hi:.1f}",
                "count": int(mask.sum()),
                "predicted": round(float(proba[mask].mean()), 4),
                "actual": round(float(y[mask].mean()), 4),
            })
```

Add `"calibration": calibration` to the return dict.

Then in `train_confidence_model()`, save it:

```python
    model = ConfidenceModel(
        ...
        calibration_data=result.get("calibration"),
    )
```

- [ ] **Step 3: Add regime breakdown to model report**

In `get_model_report()`, add calibration data to the report:

```python
    if model.calibration_data:
        report["calibration"] = model.calibration_data
```

- [ ] **Step 4: Commit**

```bash
git add api/services/confidence_scorer.py api/models/confidence.py
git commit -m "feat: add calibration curve data to confidence model training"
```

---

### Task 5: Analyze Failure Cases (Confidence >= 60% but Lost)

**Files:**
- Create: `scripts/analyze_confidence_failures.py`

- [ ] **Step 1: Create analysis script**

```python
"""Analyze the ~2.4% of trades where confidence >= 60% but lost money."""
from api.models.base import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    sql = text("""
        WITH matched AS (
            SELECT DISTINCT ON (br.id)
                br.stock_code, br.pnl_pct, br.holding_days, br.exit_reason,
                br.regime_changed, br.volume_trend_slope, br.sector_heat_delta,
                bp.confidence, bp.alpha_score, bp.gamma_score,
                bp.plan_date, bp.stock_name,
                mr.trend_strength, mr.volatility, mr.market_regime
            FROM beta_reviews br
            JOIN bot_trade_plans bp ON br.stock_code = bp.stock_code
                AND bp.created_at BETWEEN br.created_at - interval '3 days' AND br.created_at
            LEFT JOIN market_regimes mr
                ON bp.plan_date BETWEEN mr.week_start::text AND mr.week_end::text
            WHERE bp.confidence >= 60
            ORDER BY br.id, ABS(EXTRACT(EPOCH FROM (bp.created_at - br.created_at)))
        )
        SELECT * FROM matched WHERE pnl_pct <= 0
        ORDER BY pnl_pct ASC
    """)

    rows = db.execute(sql).fetchall()
    print(f"Failures with confidence >= 60%: {len(rows)}")
    print()
    for r in rows:
        print(f"  {r.plan_date} {r.stock_code} {r.stock_name}")
        print(f"    PnL={r.pnl_pct}% hold={r.holding_days}d exit={r.exit_reason}")
        print(f"    conf={r.confidence} alpha={r.alpha_score} gamma={r.gamma_score}")
        print(f"    regime={r.market_regime} trend={r.trend_strength} vol={r.volatility}")
        print(f"    regime_changed={r.regime_changed} sector_delta={r.sector_heat_delta}")
        print()
finally:
    db.close()
```

- [ ] **Step 2: Run and record findings**

```bash
cd /Users/allenqiang/stockagent && python scripts/analyze_confidence_failures.py
```

Record common patterns (specific regime? specific sector? gamma missing?).

- [ ] **Step 3: Commit**

```bash
git add scripts/analyze_confidence_failures.py
git commit -m "feat: add confidence failure case analysis script"
```

---

### Task 6: Add Confidence Trust Indicators to Frontend

**Files:**
- Modify: `web/src/app/ai/page.tsx` (confidence display area)
- Modify: `web/src/lib/api.ts` (add confidence report endpoint)

- [ ] **Step 1: Add API function for confidence model report**

In `web/src/lib/api.ts`, add to the `exploration` or `lab` object:

```typescript
  confidenceReport: () =>
    request<{
      status: string; version: number; auc_score: number; brier_score: number;
      training_samples: number; positive_rate: number;
      coefficients: Record<string, number>;
      calibration: Array<{ bin: string; count: number; predicted: number; actual: number }>;
    }>("/ops/confidence/report"),
```

- [ ] **Step 2: Add trust indicator next to confidence display**

In `web/src/app/ai/page.tsx`, find the confidence badge display (around line 929) and add a small tooltip or indicator showing model health:

```tsx
{plan.confidence != null ? `${plan.confidence.toFixed(0)}%` :
  combined != null ? `${(combined * 100).toFixed(0)}%` : "—"}
{/* Model trust indicator */}
{plan.confidence != null && plan.confidence >= 60 && (
  <span className="text-[9px] text-emerald-500/60 ml-1">AUC {modelAuc}</span>
)}
```

This is intentionally minimal — just showing the model's AUC score next to high-confidence trades so the user can see at a glance whether the model is still healthy.

- [ ] **Step 3: Commit**

```bash
git add web/src/app/ai/page.tsx web/src/lib/api.ts
git commit -m "feat: add confidence model trust indicators to AI trading page"
```

---

### Task 7: Retrain, Validate, and Compare

**Files:**
- No new files — uses existing infrastructure

- [ ] **Step 1: Retrain with all improvements applied**

```bash
# Restart server to load all code changes
cd /Users/allenqiang/stockagent
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
lsof -ti:8050 | xargs kill -9 2>/dev/null
sleep 3
NO_PROXY=localhost,127.0.0.1 nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/stockagent_8050.log 2>&1 &
sleep 6

# Retrain confidence model
NO_PROXY=localhost,127.0.0.1 curl -s -X POST "http://localhost:8050/api/ops/confidence/train" | python3 -m json.tool
```

- [ ] **Step 2: Run cross-validation on new model**

```bash
python scripts/validate_confidence.py
```

Compare: old CV-AUC vs new CV-AUC. Expected improvement: +0.02-0.06.

- [ ] **Step 3: Run failure analysis on new model**

```bash
python scripts/analyze_confidence_failures.py
```

Check if failure count decreased from the old model.

- [ ] **Step 4: Record results and commit**

```bash
git add -A
git commit -m "feat: confidence model v2 — enriched features, validated with time-series CV"
```

---

## Success Criteria

| Metric | Before | Target | How to Verify |
|--------|--------|--------|---------------|
| In-sample AUC | 0.825 | ≥ 0.85 | `curl /ops/confidence/report` |
| CV AUC | unknown | ≥ 0.78 | `python scripts/validate_confidence.py` |
| Alpha weight | -0.27 (negative!) | positive | Check coefficients in model report |
| Features | 6 | ~15 | Check FEATURE_NAMES |
| Gamma features | 1 (compressed) | 6 (raw) | Check FEATURE_NAMES |
| Calibration | unmeasured | Brier < 0.18 | Model report |
| Failures ≥60% | ~14/592 (2.4%) | ≤ 10 (< 2%) | Failure analysis script |
