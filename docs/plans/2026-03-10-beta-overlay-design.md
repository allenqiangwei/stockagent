# Beta Overlay System Design — ML-Driven Second-Layer Signal Scoring

**Date**: 2026-03-10
**Status**: Approved
**Approach**: XGBoost ML model with scorecard cold-start fallback

## 1. Overview

A closed-loop ML system that captures contextual factors (beta) when strategies fire buy signals, tracks factor evolution during holding periods, performs attribution analysis after exits, and retrains to improve future signal quality scoring.

### Core Loop (5 Steps)

```
EXECUTE (T+1开盘执行) → TRACK (持仓期每日追踪) → TRAIN (平仓后归因+重训练) → GENERATE (策略产生信号) → SCORE (Beta评分+创建计划)
```

### Cold-Start Strategy

| Phase | Sample Size | Model |
|-------|-------------|-------|
| Cold start | < 30 trades | Equal-weight scorecard (current beta_engine logic) |
| Warm | 30-100 trades | XGBoost with regularization (max_depth=3) |
| Mature | 100+ trades | Full XGBoost (max_depth=5, feature selection) |

Phase transition is automatic — no manual switching needed. The system checks completed trade count at each daily retraining cycle and selects the appropriate model tier.

## 2. Model Architecture

**Single global XGBoost binary classifier** with `strategy_family` as an input feature.

- **Target**: `P(profitable | features, strategy_family)` — binary: 1 if trade profit > 0, else 0
- **Why global**: Strategy families share market regime sensitivity; a global model learns cross-family patterns faster
- **Strategy family encoding**: One-hot or target encoding of strategy_family string (e.g., "RSI_ATR_DIP", "KDJ_MACD")

### XGBoost Configuration

```python
xgb_params = {
    'objective': 'binary:logistic',
    'eval_metric': 'auc',
    'max_depth': 3,        # 3 for warm, 5 for mature
    'learning_rate': 0.1,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'min_child_weight': 3,
    'reg_alpha': 0.1,      # L1 regularization
    'reg_lambda': 1.0,     # L2 regularization
    'missing': float('nan'),  # Native NaN handling
}
```

### Retraining

- **Frequency**: Daily, after market close (17:00 CST), after all exits processed
- **Data window**: Rolling 180 days of completed trades
- **Validation**: 5-fold time-series cross-validation (no future leakage)
- **Model versioning**: Each retrain creates a new version; rollback if AUC drops >5%

## 3. Feature Definitions (27 Features)

### 3a. Entry Snapshot Features (14)

Captured at signal generation time (before T+1 execution).

| # | Feature | Source Table | Column/Computation | Notes |
|---|---------|-------------|-------------------|-------|
| 1 | `regime_code` | market_regimes | regime (categorical) | bull/bear/sideways |
| 2 | `regime_confidence` | market_regimes | confidence (float) | 0-1 |
| 3 | `sector_heat_rank` | sector_heat | rank by score | Industry relative heat |
| 4 | `sector_heat_score` | sector_heat | score (float) | Absolute heat value |
| 5 | `index_return_5d` | index_daily | 5-day return of 000001 | Market momentum |
| 6 | `index_return_20d` | index_daily | 20-day return of 000001 | Medium-term trend |
| 7 | `stock_return_5d` | daily_prices | 5-day return of target stock | Stock momentum |
| 8 | `stock_volatility_20d` | daily_prices | 20-day stddev of returns | Volatility level |
| 9 | `volume_ratio_5d` | daily_prices | volume / 5-day avg volume | Volume anomaly |
| 10 | `alpha_score` | trading_signals_v2 | final_score | Strategy alpha signal strength |
| 11 | `strategy_family` | strategies | Derived from name pattern | e.g., "RSI_ATR_DIP" |
| 12 | `day_of_week` | Computed | 0-4 (Mon-Fri) | Weekday effect |
| 13 | `news_event_count` | news_events | Count within 3 days | Recent news activity |
| 14 | `pe_ratio` | daily_basic | pe_ttm | NaN if unavailable |

### 3b. Holding Period Trajectory Features (9)

Aggregated from daily tracking records after position is fully closed.

| # | Feature | Computation | Notes |
|---|---------|-------------|-------|
| 15 | `max_unrealized_gain` | max(daily_pnl_pct) during hold | Peak profit reached |
| 16 | `max_unrealized_loss` | min(daily_pnl_pct) during hold | Deepest drawdown |
| 17 | `holding_days` | Count of trading days held | Actual duration |
| 18 | `regime_changed` | 1 if regime differs entry vs exit | Regime stability |
| 19 | `volume_trend` | Linear regression slope of daily volume | Volume trend during hold |
| 20 | `price_path_volatility` | stddev(daily_returns) during hold | Intra-hold volatility |
| 21 | `sector_heat_delta` | exit_heat - entry_heat | Sector momentum shift |
| 22 | `news_event_during_hold` | Count of news events during hold | News exposure |
| 23 | `index_return_during_hold` | Index return from entry to exit | Market backdrop |

### 3c. Static Context Features (4)

| # | Feature | Source | Notes |
|---|---------|--------|-------|
| 24 | `industry` | stocks.industry | Industry category |
| 25 | `market_cap_bucket` | daily_basic.total_mv | NaN if unavailable; bucketed S/M/L |
| 26 | `turnover_rate` | daily_basic.turnover_rate | NaN if unavailable |
| 27 | `pb_ratio` | daily_basic.pb | NaN if unavailable |

### Data Availability

- **22 features immediately available** from existing DB tables (no external API calls)
- **5 features** (pe_ratio, market_cap_bucket, turnover_rate, pb_ratio, plus daily_basic derived) have 0 rows currently — XGBoost handles NaN natively, these become effective when daily_basic data pipeline is activated
- **No AkShare dependency** — all data from existing DB or computed

## 4. Data Model

### 4a. NEW: `beta_daily_tracks`

Daily tracking records for each active holding.

```python
class BetaDailyTrack(Base):
    __tablename__ = 'beta_daily_tracks'

    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey('bot_holdings.id'), nullable=False)
    stock_code = Column(String(10), nullable=False)
    track_date = Column(Date, nullable=False)

    # Daily snapshot
    close_price = Column(Float)
    daily_return_pct = Column(Float)         # vs previous day
    cumulative_pnl_pct = Column(Float)       # vs entry price
    volume = Column(BigInteger)
    volume_ratio = Column(Float)             # vs 5-day avg

    # Context
    regime_code = Column(String(20))
    sector_heat_score = Column(Float)
    index_close = Column(Float)              # 000001.SH
    news_event_count = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('holding_id', 'track_date'),
    )
```

### 4b. MODIFY: `beta_snapshots` (add fields)

```python
# New columns to add:
strategy_family = Column(String(50))    # Derived from strategy name
final_score = Column(Float)             # Alpha score at signal time
entry_price = Column(Float)             # T+1 open price
day_of_week = Column(Integer)           # 0-4
stock_return_5d = Column(Float)         # Pre-entry momentum
stock_volatility_20d = Column(Float)    # Pre-entry volatility
volume_ratio_5d = Column(Float)         # Pre-entry volume anomaly
index_return_5d = Column(Float)         # Market momentum
index_return_20d = Column(Float)        # Market medium-term trend
```

### 4c. MODIFY: `beta_reviews` (add trajectory aggregates)

```python
# New columns to add:
max_unrealized_gain = Column(Float)
max_unrealized_loss = Column(Float)
holding_days = Column(Integer)
regime_changed = Column(Boolean, default=False)
volume_trend_slope = Column(Float)
price_path_volatility = Column(Float)
sector_heat_delta = Column(Float)
news_events_during_hold = Column(Integer, default=0)
index_return_during_hold = Column(Float)
is_profitable = Column(Boolean)          # Target variable for XGBoost
```

### 4d. NEW: `beta_model_state`

```python
class BetaModelState(Base):
    __tablename__ = 'beta_model_state'

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    model_type = Column(String(20))          # 'scorecard' or 'xgboost'
    model_blob = Column(LargeBinary)         # Pickled model
    feature_importance = Column(JSON)        # {feature_name: importance_score}
    training_samples = Column(Integer)
    auc_score = Column(Float)
    accuracy = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Metadata
    training_window_start = Column(Date)
    training_window_end = Column(Date)
    hyperparams = Column(JSON)
```

## 5. Daily Operational Flow

### Step 1: Execute (09:25 CST)

Execute yesterday's approved plans at T+1 open price with 0.1% slippage.

- Bot trading engine executes `BotTradePlan` → creates `BotTrade` + `BotHolding`
- **On buy execution**: Capture entry beta snapshot → `beta_snapshots` (enhanced with new fields)
- **On sell execution**: Mark holding as closed, trigger trajectory aggregation

### Step 2: Track (15:30 CST, after market close)

For every active `BotHolding`:

```python
for holding in active_holdings:
    track = BetaDailyTrack(
        holding_id=holding.id,
        stock_code=holding.stock_code,
        track_date=today,
        close_price=today_close,
        daily_return_pct=compute_daily_return(holding),
        cumulative_pnl_pct=compute_cumulative_pnl(holding),
        volume=today_volume,
        volume_ratio=today_volume / avg_volume_5d,
        regime_code=current_regime,
        sector_heat_score=sector_heat,
        index_close=index_close,
        news_event_count=news_count_today,
    )
    db.add(track)
```

### Step 3: Train (17:00 CST)

For any positions fully closed today:

1. **Aggregate trajectory**: Query `beta_daily_tracks` for the closed holding, compute trajectory features (max gain, max loss, volume trend, etc.)
2. **Update beta_review**: Write aggregated features + `is_profitable` flag
3. **Retrain model** (if new closed trade count triggers it):
   - Query all completed `beta_reviews` with trajectory data
   - Build feature matrix from `beta_snapshots` + `beta_reviews`
   - Train XGBoost (or scorecard if < 30 samples)
   - Save new model version to `beta_model_state`
   - Log feature importance changes

### Step 4: Generate Signals (17:30 CST)

Strategy rule engine runs all enabled strategies against latest market data → produces `trading_signals_v2` entries for tomorrow.

*(This step is unchanged from current behavior)*

### Step 5: Score & Create Plans (18:00 CST)

For **ALL** strategies that generated buy signals today:

```python
for signal in today_buy_signals:
    # Compute alpha score (existing)
    alpha = signal.final_score

    # Compute beta score (new)
    features = build_feature_vector(signal)
    beta = model.predict_proba(features)  # P(profitable)

    # Combined score with stage-dependent weights
    combined = alpha * weight_alpha + beta * weight_beta
    # Weights: cold-start (0.8/0.2), warm (0.6/0.4), mature (0.5/0.5)

    # Create plan for ALL qualifying signals
    plan = BotTradePlan(
        stock_code=signal.stock_code,
        stock_name=signal.stock_name,
        strategy_id=signal.strategy_id,
        alpha_score=alpha,
        beta_score=beta,
        combined_score=combined,
        plan_type='buy',
        status='pending',
        ...
    )
    db.add(plan)
```

**Display vs Execute**:
- **Display to user**: Top 5-10 plans ranked by `combined_score` (shown in dashboard)
- **Actually execute**: ALL qualifying plans that pass minimum thresholds create `BotTradePlan` records
- **AI Analyst** annotates Top 5-10 with commentary but does NOT make buy/sell decisions

## 6. AI Analyst Role

The AI Analyst is redefined as **pure interpretation** — no buy decision authority.

### AI Retains

| Function | Description |
|----------|-------------|
| Market analysis | Daily commentary on regime, sector heat, key events |
| Holding advice | "Consider reducing position" based on trajectory patterns |
| Plan commentary | Annotate Top 5-10 plans with risk/opportunity analysis |
| Q&A | Answer user questions about strategies, signals, market |

### AI Removes

| Function | Replacement |
|----------|-------------|
| Buy recommendations | Replaced by Beta Score + combined ranking |
| entry_price setting | System uses T+1 open price automatically |
| BotTradePlan creation | System creates plans for ALL qualifying signals |

## 7. Scoring Weights by Phase

| Phase | Alpha Weight | Beta Weight | Rationale |
|-------|-------------|-------------|-----------|
| Cold start (< 30) | 0.80 | 0.20 | Scorecard unreliable, lean on proven alpha |
| Warm (30-100) | 0.60 | 0.40 | XGBoost learning, increasing trust |
| Mature (100+) | 0.50 | 0.50 | Equal partnership, both systems proven |

## 8. Implementation Priorities

1. **P0**: Database migrations (new tables + column additions)
2. **P0**: Daily tracking job (Step 2 — capture beta_daily_tracks)
3. **P1**: Trajectory aggregation on position close (Step 3a)
4. **P1**: XGBoost training pipeline with cold-start fallback (Step 3b-c)
5. **P2**: Signal scoring integration (Step 5 — beta score in plan creation)
6. **P2**: Dashboard display of Top 5-10 with beta scores
7. **P3**: AI Analyst role refactoring (remove buy decisions)
8. **P3**: Feature importance dashboard widget
