# Confidence Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the signal grader with a 0-100 confidence score (Logistic Regression) that predicts trade win probability using alpha, gamma, and market regime features.

**Architecture:** New `confidence_scorer.py` service trains a Logistic Regression model from completed trade reviews + market regime data. Model params stored as JSON in a new `confidence_models` DB table. No serialization libraries used — model coefficients stored as plain numbers, predictions computed with pure math (sigmoid + dot product). Integrated into `beta_scorer.py` plan creation. Frontend displays confidence and sorts by it.

**Tech Stack:** scikit-learn (training only), numpy, SQLAlchemy, FastAPI, Next.js/React

**Note:** This implementation uses JSON serialization for model storage (not binary serialization). Model params are simple numbers — 6 coefficients, 1 intercept, 12 scaler params — stored as a JSON dict. Prediction is pure math with no library dependency.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/models/confidence.py` | Create | ConfidenceModel ORM |
| `api/services/confidence_scorer.py` | Create | Train, predict, calibrate |
| `api/services/beta_scorer.py` | Modify | Replace signal_grader with confidence_scorer |
| `api/services/signal_scheduler.py` | Modify | Replace grader calibrate with confidence train |
| `api/models/bot_trading.py` | Modify | Add `confidence` column to BotTradePlan |
| `api/schemas/bot_trading.py` | Modify | Add `confidence` to schema |
| `api/routers/bot_trading.py` | Modify | Return confidence, sort by it |
| `api/routers/beta.py` | Modify | Add confidence API endpoints |
| `web/src/types/index.ts` | Modify | Add confidence field |
| `web/src/app/ai/page.tsx` | Modify | Display confidence, sort by it |
| `tests/test_confidence_scorer.py` | Create | Unit + integration tests |

---

### Task 1: ORM Model + DB Table

**Files:**
- Create: `api/models/confidence.py`

- [ ] **Step 1: Create the model file**

Create `api/models/confidence.py` with a `ConfidenceModel` class that has columns: id (PK), version (int), model_params (JSON — stores {coef, intercept, scaler_mean, scaler_scale}), feature_names (JSON), auc_score (float), brier_score (float), training_samples (int), positive_rate (float), is_active (bool), created_at (datetime). Follow the exact same ORM pattern as `api/models/beta_factor.py:BetaModelState`.

- [ ] **Step 2: Create DB table + add confidence column to bot_trade_plans**

Run a Python script that:
1. `ConfidenceModel.__table__.create(engine, checkfirst=True)`
2. `ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS confidence FLOAT`

- [ ] **Step 3: Add `confidence` field to BotTradePlan ORM model**

In `api/models/bot_trading.py`, add after the `signal_win_rate` line:
```python
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 4: Add `confidence` to schema**

In `api/schemas/bot_trading.py`, add after `signal_win_rate`:
```python
    confidence: Optional[float] = None
```

- [ ] **Step 5: Commit**

```
git commit -m "feat(confidence): add ConfidenceModel ORM + DB schema"
```

---

### Task 2: Core Confidence Scorer Service

**Files:**
- Create: `api/services/confidence_scorer.py`
- Create: `tests/test_confidence_scorer.py`

The scorer has three parts:

**A. Pure-math prediction** (`_sigmoid`, `_predict_from_params`): Takes model params dict + feature array, returns 0-100 score. No sklearn dependency — just `(X - mean) / scale`, dot product with coefficients, sigmoid, multiply by 100.

**B. Training** (`_train_lr`): Uses sklearn `LogisticRegression(C=1.0)` + `StandardScaler`. Extracts coef/intercept/scaler params as plain float lists. Returns a dict with `model_params`, `auc`, `brier`.

**C. DB integration** (`train_confidence_model`, `predict_confidence`, `get_model_report`): Builds training data via SQL JOIN (bot_trade_plans + bot_trade_reviews + market_regimes), saves model to DB, loads active model for prediction.

Feature vector (6 features):
1. `alpha_score` — from plan
2. `gamma_score` — from plan (0 if None)
3. `has_gamma` — 1.0 if gamma exists, else 0.0
4. `trend_strength` — from market_regimes
5. `volatility` — from market_regimes
6. `index_return_pct` — from market_regimes

Training SQL:
```sql
SELECT p.alpha_score, p.gamma_score,
       mr.trend_strength, mr.volatility, mr.index_return_pct,
       r.pnl_pct
FROM bot_trade_plans p
JOIN bot_trade_reviews r
    ON r.stock_code = p.stock_code AND r.strategy_id = p.strategy_id
    AND r.first_buy_date = p.plan_date
JOIN market_regimes mr
    ON r.first_buy_date BETWEEN mr.week_start::text AND mr.week_end::text
WHERE p.status = 'executed' AND p.direction = 'buy' AND p.alpha_score IS NOT NULL
```

Label: `pnl_pct > 0 → 1, else 0`

AUC guard: don't deploy if AUC < 0.52.

Thread-safe cache for active model params (global `_active_params` with `_lock`).

- [ ] **Step 1: Write tests**

Tests for: `_sigmoid` (boundary values), `_predict_from_params` (known input→output), `_train_lr` (synthetic data → correct output structure with auc, brier, model_params keys).

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement confidence_scorer.py**

Full implementation of all functions described above.

- [ ] **Step 4: Run tests to verify pass**

- [ ] **Step 5: Commit**

```
git commit -m "feat(confidence): add Logistic Regression confidence scorer"
```

---

### Task 3: Integrate into Plan Creation (beta_scorer)

**Files:**
- Modify: `api/services/beta_scorer.py` (~line 272)

- [ ] **Step 1: Replace signal_grader with confidence_scorer**

Find the block starting with `from api.services.signal_grader import grade_signal` (~line 272). Replace with:

1. Import `predict_confidence` from confidence_scorer
2. Query `MarketRegimeLabel` for current week's trend_strength, volatility, index_return_pct
3. Call `predict_confidence(db, alpha, gamma, trend_strength, volatility, index_return_pct)`
4. Set `plan.confidence = confidence` (the score)
5. Set `plan.signal_grade = None, plan.signal_win_rate = None` (deprecated)
6. Update `thinking` string to show `[C=XX]` instead of grade emoji

- [ ] **Step 2: Commit**

```
git commit -m "feat(confidence): integrate confidence scorer into plan creation"
```

---

### Task 4: Scheduler + API + Sorting

**Files:**
- Modify: `api/services/signal_scheduler.py`
- Modify: `api/routers/bot_trading.py`
- Modify: `api/routers/beta.py`

- [ ] **Step 1: Replace signal_grader in scheduler**

In `_run_loop` startup block (~line 118): replace `from api.services.signal_grader import calibrate` with `from api.services.confidence_scorer import train_confidence_model`, call `train_confidence_model(db)`.

In Step 5d-pre (~line 391): same replacement.

- [ ] **Step 2: Update sorting in bot_trading router**

In `list_plans`: sort by `BotTradePlan.confidence.desc().nullslast()` then `combined_score.desc().nullslast()`. Remove the `case`/`grade_order` logic.

In `list_pending_plans`: same sort order.

- [ ] **Step 3: Add confidence to plan serializer**

In `_plan_to_item()`, add: `confidence=getattr(p, "confidence", None)`

- [ ] **Step 4: Add confidence API endpoints to beta.py**

Three endpoints:
- `GET /api/beta/confidence/model` — returns model report (version, AUC, Brier, coefficients)
- `POST /api/beta/confidence/train` — manual retrain trigger
- `GET /api/beta/confidence/predict?alpha=X&gamma=Y&...` — single prediction

- [ ] **Step 5: Commit**

```
git commit -m "feat(confidence): scheduler + API + sorting by confidence"
```

---

### Task 5: Frontend

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/app/ai/page.tsx`

- [ ] **Step 1: Add confidence to TypeScript type**

In `BotTradePlanItem`, add after `signal_win_rate`:
```typescript
  confidence: number | null;
```

- [ ] **Step 2: Update plan card rendering**

Badge: show `XX%` with confidence value. Colors: >=60 emerald, 40-60 amber, <40 red. Falls back to source labels (止损/止盈/超期) if confidence is null.

Border: same color scheme based on confidence value.

Header text: change to `按置信度排序`.

- [ ] **Step 3: Commit**

```
git commit -m "feat(confidence): frontend display + sorting by confidence"
```

---

### Task 6: Train + Backfill + Verify

**Files:** None (runtime operations)

- [ ] **Step 1: Create table and train first model**

Run script to create `confidence_models` table and call `train_confidence_model(db)`. Print version, AUC, Brier, coefficients.

- [ ] **Step 2: Backfill existing plans**

Run script to update all `bot_trade_plans` that have `alpha_score IS NOT NULL AND confidence IS NULL` with predictions from the trained model. Use latest market_regime for backfill (approximate — exact per-plan date would require looping).

- [ ] **Step 3: Restart server and verify**

Restart uvicorn, verify:
- `GET /api/beta/confidence/model` returns active model
- `GET /api/bot/plans/pending` returns plans sorted by confidence desc
- First plan has highest confidence, last has lowest

- [ ] **Step 4: Commit**

```
git commit -m "feat(confidence): initial training + backfill completed"
```

---

## Summary

| Task | What | Key Deliverable |
|------|------|----------------|
| 1 | DB schema | `confidence_models` table + `confidence` column |
| 2 | Core scorer | Train LR, predict with pure math, no binary serialization |
| 3 | Plan creation | Each plan gets confidence score at creation |
| 4 | Scheduler + API | Daily retrain + 3 API endpoints + sort by confidence |
| 5 | Frontend | Display XX% badge, color-coded, sorted |
| 6 | Verify | Train, backfill, restart, end-to-end check |
