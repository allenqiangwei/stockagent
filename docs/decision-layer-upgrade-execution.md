# StockAgent Decision Layer Upgrade — Execution Plan

> **For ChatGPT**: This plan tells you exactly what to do, in what order, one file at a time.
> The full spec with rationale is in `swirling-noodling-lantern.md` — refer to it for context.

## Pre-Requisites

- Read the full spec first: `/Users/allenqiang/.claude/plans/swirling-noodling-lantern.md`
- Working directory: `/Users/allenqiang/stockagent`
- Server: FastAPI on port 8050
- Database: PostgreSQL

## Execution Rules

1. **One file at a time** — apply ALL changes to a file in a single pass, then move to the next file
2. **Read before edit** — always read the current file content before making changes
3. **No line number trust** — line numbers in the spec are approximate. Match by code content, not line number
4. **Test after each file** — run `python -c "import api.services.beta_scorer"` (or equivalent) after editing each file to catch syntax errors
5. **Commit after each phase** — commit P0 files together, P1 files together, P2 files together

---

## Phase 1: P0 Changes (Day 1-2)

### File 1 of 6: `api/services/beta_scorer.py`

This file has changes from **P0-A + P0-B + P0-C + P2-I** (4 changes). Apply ALL at once:

**Order within file (top to bottom):**

1. **[P0-A Step 1]** Replace the two weight tables at the top of the file (WEIGHT_TABLE + GAMMA_WEIGHT_TABLE) with WEIGHT_TABLE_3F + WEIGHT_TABLE_2F + _PHASE_ORDER
2. **[P0-A Step 2]** In `score_and_create_plans()`, replace the phase calculation (beta_phase/gamma_phase/alpha_w,gamma_w) with unified `phase = min(...)`
3. **[P0-C Step 1]** Right after `shared_context = _load_shared_beta_context(...)`, INSERT daily loss circuit breaker check
4. **[P0-A Step 3]** In the signal loop, DELETE the old combined score calculation + beta computation block. REPLACE with the new version that computes beta FIRST, then three-factor combined
5. **[P0-C Step 2]** In the signal loop, right after `available_slots = ...`, INSERT the `_is_blocked()` call
6. **[P0-B Step 1]** Change `quantity = int(100_000 / ...)` to `base_quantity = int(100_000 / ...)`
7. **[P0-B Step 2]** Inside the strategy loop, just before `plan = BotTradePlan(`, INSERT confidence-based quantity calculation
8. **[P0-A Step 4]** Update the `thinking=` string to include `beta={beta:.2f}`
9. **[P0-A Step 6]** In the return dict, change `"phase": gamma_phase` to `"phase": phase`
10. **[P2-I]** After `plans.sort(...)` and before `db.commit()`, INSERT gamma coverage monitoring
11. **[P0-A Step 5]** Update the logger.info line with phase/beta_phase/gamma_phase
12. **[P0-C Step 3]** APPEND `_is_blocked()` and `_daily_loss_exceeded()` functions at the end of the file

**Syntax check:**
```bash
cd /Users/allenqiang/stockagent && python -c "from api.services.beta_scorer import score_and_create_plans; print('OK')"
```

---

### File 2 of 6: `api/services/signal_engine.py`

This file has **1 change** from P0-A.

1. Find the `_format_signal()` method's combined score display calculation (search for `"Combined score for display"`)
2. Replace the 2-factor 80/20 calculation with the 3-factor version using _BETA_NEUTRAL = 0.5

**Syntax check:**
```bash
python -c "from api.services.signal_engine import SignalEngine; print('OK')"
```

---

### File 3 of 6: `api/services/claude_runner.py`

This file has **1 change** from P0-A.

1. Find the line containing `beta_score: copy directly from` in the AI prompt string
2. Replace with the new description about environment factor

**Syntax check:**
```bash
python -c "from api.services.claude_runner import *; print('OK')"
```

---

### File 4 of 6: `api/services/confidence_scorer.py`

This file has **1 change** from P0-D.

1. Find ALL 4 occurrences of `0.52` in `train_confidence_model()`:
   - Comment: `AUC guard: if AUC < 0.52`
   - Condition: `if result["auc"] < 0.52:`
   - Log message: `"Confidence model AUC %.4f < 0.52`
   - Return message: `"AUC {result['auc']:.4f} < 0.52 threshold`
2. Replace all 4 with `0.55`

**Syntax check:**
```bash
python -c "from api.services.confidence_scorer import train_confidence_model; print('OK')"
```

---

### P0 Verification Checkpoint

```bash
# Start server
python -m uvicorn api.main:app --port 8050 &

# Wait for startup
sleep 3

# Trigger signal scan (will exercise beta_scorer + signal_engine)
curl -X POST http://127.0.0.1:8050/api/signals/scan

# Check pending plans — should have beta in thinking, varied quantities
curl http://127.0.0.1:8050/api/bot/plans/pending | python -m json.tool | head -50

# Kill server
kill %1
```

**What to verify in the output:**
- `thinking` field contains `beta=X.XX`
- `combined_score` values are different from each other (beta influence)
- `quantity` values vary (confidence sizing: some 100, some 200, some 300+)
- No ST stocks in the plan list

**Commit:**
```bash
git add api/services/beta_scorer.py api/services/signal_engine.py api/services/claude_runner.py api/services/confidence_scorer.py
git commit -m "feat: three-factor combined score (alpha+gamma+beta), confidence-based position sizing, risk gate, AUC threshold 0.55"
```

---

## Phase 2: P1 Changes (Day 3-4)

### File 5 of 6: `api/services/exploration_engine.py`

This file has changes from **P1-E + P1-G** (2 changes). Apply together:

**Order within file:**

1. **[P1-E Step 1]** After `STDA_WR = 60.0` (near line 205), INSERT the `_adjusted_stda_score()` function
2. **[P1-E Step 2]** Modify the `is_stda_plus()` function signature to accept `score_threshold` kwarg. Change `score >= STDA_SCORE` to `threshold <= score`
3. **[P1-E Step 3]** In `_step_promote_and_rebalance()`, before the `is_stda_plus()` call, add `adjusted_score = _adjusted_stda_score(load_experience())` and pass it as `score_threshold=adjusted_score`
4. **[P1-E Step 4]** Update the promote log to show `threshold=%.4f`
5. **[P1-G]** At the end of `_step_promote_and_rebalance()`, before `return promoted`, INSERT the decay check call using `_api("POST", "strategies/pool/check-decay")`

**Important**: `_api()` is already defined in this file (search for `def _api(`) — do NOT import requests or create a new HTTP helper.

**Syntax check:**
```bash
python -c "from api.services.exploration_engine import is_stda_plus; print('OK')"
```

---

### File 6 of 6: `api/services/strategy_pool.py`

This file has changes from **P1-F + P1-G** (2 changes). Apply together:

1. **[P1-F]** Add `_deduplicate_by_overlap()` method to `StrategyPoolManager` class.
   - **CRITICAL**: ActionSignal uses `strategy_name` (String), NOT `strategy_id` (Integer). Match by `s.name`.
   - **CRITICAL**: ActionSignal action values are uppercase: `"BUY"`, not `"buy"`.
2. **[P1-F]** In `rebalance_by_skeleton()`, after `selected = self._select_diverse_top(...)`, call `self._deduplicate_by_overlap(selected)`
3. **[P1-G]** Add `check_champion_decay()` method to `StrategyPoolManager` class

**Syntax check:**
```bash
python -c "from api.services.strategy_pool import StrategyPoolManager; print('OK')"
```

---

### File 7 (new endpoint): `api/routers/strategies.py`

1. Add the `/pool/check-decay` POST endpoint (see spec for code)
2. Ensure `StrategyPoolManager` is importable: `from api.services.strategy_pool import StrategyPoolManager`

**Syntax check:**
```bash
python -c "from api.routers.strategies import router; print('OK')"
```

---

### P1 Verification Checkpoint

```bash
# Start server
python -m uvicorn api.main:app --port 8050 &
sleep 3

# Test decay endpoint directly
curl -X POST http://127.0.0.1:8050/api/strategies/pool/check-decay | python -m json.tool

# Test rebalance (will trigger overlap dedup)
curl -X POST "http://127.0.0.1:8050/api/strategies/pool/rebalance?max_per_family=15" | python -m json.tool

# Check server logs for "Overlap dedup:" and "Decay:" messages

kill %1
```

**Commit:**
```bash
git add api/services/exploration_engine.py api/services/strategy_pool.py api/routers/strategies.py
git commit -m "feat: DSR dynamic threshold, signal overlap dedup, champion decay monitoring"
```

---

## Phase 3: P2 Changes (Day 5)

### File 8: `api/models/stock.py`

1. Add `snapshot_date` and `adjust_mode` columns to `DailyPrice` class (see spec)
2. Add `from sqlalchemy import String` to imports if not present (String(4) for adjust_mode)

---

### File 9: Database Migration

```bash
# Connect to PostgreSQL and run:
psql -d stockagent -c "ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS snapshot_date DATE;"
psql -d stockagent -c "ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS adjust_mode VARCHAR(4);"
```

---

### File 10: `api/services/data_collector.py`

1. Find ALL locations where `DailyPrice(` objects are created
2. Add `snapshot_date=date.today(), adjust_mode="raw",` to each
3. Ensure `from datetime import date` is in imports

---

### P2 Verification

```bash
# Trigger data sync
curl -X POST http://127.0.0.1:8050/api/data/sync

# Check new columns
psql -d stockagent -c "SELECT stock_code, trade_date, snapshot_date, adjust_mode FROM daily_prices ORDER BY id DESC LIMIT 5;"
```

**Commit:**
```bash
git add api/models/stock.py api/services/data_collector.py
git commit -m "feat: DailyPrice PIT fields (snapshot_date, adjust_mode)"
```

---

## Quick Reference: What's in Each File

| File | Changes from | Total edits |
|------|-------------|-------------|
| `api/services/beta_scorer.py` | P0-A, P0-B, P0-C, P2-I | 12 edits |
| `api/services/signal_engine.py` | P0-A | 1 edit |
| `api/services/claude_runner.py` | P0-A | 1 edit |
| `api/services/confidence_scorer.py` | P0-D | 4 replacements |
| `api/services/exploration_engine.py` | P1-E, P1-G | 5 edits |
| `api/services/strategy_pool.py` | P1-F, P1-G | 2 new methods + 1 call site |
| `api/routers/strategies.py` | P1-G | 1 new endpoint |
| `api/models/stock.py` | P2-H | 2 new columns |
| `api/services/data_collector.py` | P2-H | fill new fields |
| SQL migration | P2-H | 2 ALTER TABLE |

**Total: 10 files, 3 commits, 5 days**
