# Signal Reuse & Exit Grid Expansion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant stock data loading and indicator computation across experiments in one exploration round, parallelize trade simulations, and expand the exit grid from 10 to 25 configs.

**Architecture:** Merge all per-config API calls in `_step_submit()` into a SINGLE `batch-clone-backtest` call. The existing endpoint already handles different buy/sell conditions via `_revectorize()` + `_cond_cache`. Then parallelize the serial simulation loop in `_run_batch()` using ThreadPoolExecutor. Finally, replace the hardcoded exit grid with a parameterized generator.

**Tech Stack:** Python, FastAPI, SQLAlchemy, threading, concurrent.futures

**Performance Impact:**
| Metric | Current (30×10) | After (1×750) |
|--------|-----------------|---------------|
| Data loads | 30 × ~30s = 900s | 1 × 30s |
| Indicator compute | 30 × ~30s = 900s | 1 × ~30s |
| Signal vectorize | 30 × 5s = 150s | 30 × 5s (cached) |
| Simulations | 300 serial (4 parallel batches) | 750 with 4-worker pool |
| **Total est.** | **~22 min** | **~35 min for 2.5× more strategies** |
| **Per-strategy cost** | **4.4s** | **2.8s** |

---

### Task 1: Merge `_step_submit` into Single Bulk API Call

**Files:**
- Modify: `api/services/exploration_engine.py:1785-1884` (`_step_submit` method)

**Why:** Currently loops over 30 configs making 30 HTTP calls. Each triggers independent stock data loading + indicator computation (~60s each). Merging into 1 call saves ~29 × 60s = 29 minutes of redundant I/O.

- [ ] **Step 1: Refactor `_step_submit` to build all exit_configs in one list**

Replace the per-config loop that makes individual API calls with a single aggregated call:

```python
def _step_submit(self, configs: list[dict]) -> list[int]:
    """Submit ALL configs as a single batch-clone-backtest call.

    Merges all configs × exit_grid into one API call so that
    stock data loading + indicator computation happens ONCE.
    """
    source_id = getattr(self, "_source_strategy_id", 0)
    if not source_id:
        logger.error("No source_strategy_id set")
        return []

    exit_grid = generate_exit_grid()  # Task 3

    all_exit_configs = []
    for cfg in configs:
        label = cfg.get("name", cfg.get("label", cfg.get("name_suffix", "exp")))

        # ── Build buy conditions ──
        buy = copy.deepcopy(BASE_BUY)
        buy_factors = cfg.get("buy_factors", [])
        if buy_factors:
            for bf in buy_factors:
                cond = _factor_to_condition(bf.get("factor", ""), bf.get("value", 0), for_sell=False)
                if cond:
                    buy.append(cond)
        else:
            extra = cfg.get("extra_buy_conditions", cfg.get("buy_conditions", []))
            if isinstance(extra, list):
                buy.extend(extra)

        # ── Build sell conditions ──
        sell = copy.deepcopy(BASE_SELL)
        sell_factors = cfg.get("sell_factors", [])
        if sell_factors:
            for sf in sell_factors:
                cond = _factor_to_condition(sf.get("factor", ""), sf.get("value", 0), for_sell=True)
                if cond:
                    sell.append(cond)
        else:
            extra = cfg.get("extra_sell_conditions", cfg.get("sell_conditions", []))
            if isinstance(extra, list):
                sell.extend(extra)

        # ── Expand exit grid ──
        for ec in exit_grid:
            all_exit_configs.append({
                "name_suffix": f"_{label}_{ec['name']}",
                "exit_config": {
                    "stop_loss_pct": ec["stop_loss_pct"],
                    "take_profit_pct": ec["take_profit_pct"],
                    "max_hold_days": ec["max_hold_days"],
                },
                "buy_conditions": buy,
                "sell_conditions": sell,
            })

    if not all_exit_configs:
        return []

    # Single API call — data loaded ONCE, indicators computed ONCE
    resp = _api("POST", f"lab/strategies/{source_id}/batch-clone-backtest", {
        "source_strategy_id": source_id,
        "exit_configs": all_exit_configs,
    }, timeout=600)

    exp_ids = []
    eid = resp.get("experiment_id")
    if eid:
        exp_ids.append(eid)
        self.strategies_total = resp.get("count", len(all_exit_configs))
    else:
        logger.error("Bulk submit failed: %s", str(resp)[:200])

    self.strategies_done = 0
    self.strategies_invalid = 0
    self.strategies_pending = self.strategies_total
    return exp_ids
```

- [ ] **Step 2: Verify `_step_poll` works with fewer experiment IDs**

`_step_poll` iterates `exp_ids` and aggregates stats. With 1 experiment ID instead of 30, the loop is simpler but logic is identical. **No code change needed** — just verify by reading the poll loop at line 1892.

- [ ] **Step 3: Verify `_step_self_heal` still works**

`_step_self_heal` uses `self.strategies_invalid` and `self.strategies_done` counts (set by `_step_poll`). It resubmits loosened configs via NEW batch-clone-backtest calls. With 1 experiment, the counts are aggregated the same way. **No code change needed** — self-heal creates additional experiments as before.

- [ ] **Step 4: Verify `_collect_round_metadata` works with 1 experiment**

`_collect_round_metadata` iterates `exp_ids` and scans strategies. With 1 experiment containing all strategies, it works identically. **No code change needed.**

- [ ] **Step 5: Increase `_api` timeout for bulk call**

The bulk call creates hundreds of strategies. The existing 120s timeout may not be enough for creating 750 DB rows. The `_step_submit` code above already uses `timeout=600`.

---

### Task 2: Parallelize Simulations in `_run_batch`

**Files:**
- Modify: `api/routers/ai_lab.py:1042-1120` (simulation loop in `_run_batch`)

**Why:** Currently `_run_batch` runs simulations serially. With 750 strategies, serial execution takes ~2+ hours. Parallelizing with 4 workers reduces to ~30 minutes. `run_with_prepared()` is thread-safe (all mutable state is method-local).

**Design:** Separate compute (parallel, thread-safe) from DB writes (serial, one session). Each simulation returns a result object; DB updates happen serially afterwards.

- [ ] **Step 1: Extract simulation into a pure function**

Add a helper inside `_run_batch` that runs one simulation without DB access:

```python
def _simulate_one(sid_and_data):
    """Pure compute — no DB access. Returns (sid, result_or_error)."""
    sid, strat_name, exit_cfg, run_precomputed = sid_and_data
    try:
        cancel_ev = threading.Event()
        timer = threading.Timer(300, cancel_ev.set)
        timer.daemon = True
        timer.start()
        try:
            result = pe.run_with_prepared(
                strategy_name=strat_name,
                exit_config=exit_cfg,
                precomputed=run_precomputed,
                regime_map=regime_map,
                cancel_event=cancel_ev,
            )
            return (sid, "ok", result)
        except (SignalExplosionError, BacktestTimeoutError) as e:
            return (sid, "invalid", str(e)[:500])
        except Exception as e:
            return (sid, "failed", str(e)[:500])
        finally:
            timer.cancel()
    except Exception as e:
        return (sid, "failed", str(e)[:500])
```

- [ ] **Step 2: Build simulation work items (serial, with DB)**

Replace the current serial loop. First pass: read from DB, determine precomputed data, build work items:

```python
# ── Build work items (serial, needs DB) ──
work_items = []
for sid in cloned_ids:
    strat = session.query(ExperimentStrategy).get(sid)
    if not strat:
        continue
    strat.status = "backtesting"
    session.commit()

    strat_buy = strat.buy_conditions or []
    strat_sell = strat.sell_conditions or []
    conds_match = (json.dumps(strat_buy, sort_keys=True) == json.dumps(source_buy, sort_keys=True)
                   and json.dumps(strat_sell, sort_keys=True) == json.dumps(source_sell, sort_keys=True))

    if conds_match:
        run_precomputed = precomputed
    else:
        cond_key = json.dumps(strat_buy, sort_keys=True) + "|||" + json.dumps(strat_sell, sort_keys=True)
        if cond_key not in _cond_cache:
            _cond_cache[cond_key] = _revectorize(strat_buy, strat_sell, precomputed)
        run_precomputed = _cond_cache[cond_key]

    work_items.append((strat.id, strat.name, strat.exit_config or {}, run_precomputed))
```

- [ ] **Step 3: Run simulations in parallel**

```python
# ── Parallel simulation (pure compute, no DB) ──
n_sim_workers = min(4, os.cpu_count() or 4)
sim_results = {}
with ThreadPoolExecutor(max_workers=n_sim_workers) as sim_pool:
    futures = {sim_pool.submit(_simulate_one, item): item[0] for item in work_items}
    for fut in futures:
        sid = futures[fut]
        try:
            sim_results[sid] = fut.result()
        except Exception as e:
            sim_results[sid] = (sid, "failed", str(e)[:500])
```

- [ ] **Step 4: Write results to DB serially**

```python
# ── DB writes (serial, one session) ──
for sid, status, payload in sim_results.values():
    strat = session.query(ExperimentStrategy).get(sid)
    if not strat:
        continue

    if status == "invalid":
        strat.status = "invalid"
        strat.error_message = payload
        strat.score = 0.0
    elif status == "failed":
        strat.status = "failed"
        strat.error_message = payload
    else:
        result = payload  # PortfolioBacktestResult
        strat.total_trades = result.total_trades
        strat.win_rate = result.win_rate
        strat.total_return_pct = result.total_return_pct
        strat.max_drawdown_pct = result.max_drawdown_pct
        strat.avg_hold_days = result.avg_hold_days
        strat.avg_pnl_pct = result.avg_pnl_pct
        strat.regime_stats = result.regime_stats if result.regime_stats else None

        if result.total_trades == 0:
            strat.score = 0.0
            strat.status = "invalid"
            strat.error_message = "零交易"
        else:
            from api.config import get_settings
            lab_cfg = get_settings().ai_lab
            weights = {
                "weight_return": lab_cfg.weight_return,
                "weight_drawdown": lab_cfg.weight_drawdown,
                "weight_sharpe": lab_cfg.weight_sharpe,
                "weight_plr": lab_cfg.weight_plr,
            }
            strat.score = round(_compute_score(result, weights), 4)
            strat.status = "done"
    session.commit()
```

- [ ] **Step 5: Adjust semaphore usage**

The current code acquires 1 semaphore slot for the entire batch. With a mega-batch containing all strategies, this is correct — we want 1 batch at a time, with internal parallelism via ThreadPoolExecutor. No change needed to semaphore acquisition, but update the concurrency comment:

```python
# Acquire semaphore — one mega-batch at a time, internal parallelism via ThreadPoolExecutor
_BACKTEST_SEMAPHORE.acquire()
```

---

### Task 3: Parameterized Exit Grid Generator

**Files:**
- Modify: `api/services/exploration_engine.py` (replace `DEFAULT_EXIT_GRID` with function)

**Why:** Hardcoded 10 configs are arbitrary. A parameterized generator with constraint filtering covers the parameter space more scientifically and allows easy tuning.

- [ ] **Step 1: Define parameter ranges and constraints**

```python
def generate_exit_grid() -> list[dict]:
    """Generate exit configs by combining SL/TP/MHD ranges with constraint filtering.

    Constraints:
    - TP < 0.12 is below slippage floor → skip
    - TP >= 3.0 requires MHD >= 5 (needs time to reach high TP)
    - TP <= 0.5 requires MHD <= 2 (scalping exits fast)
    - SL tighter than -10 with MHD >= 7 → skip (tight SL + long hold = whipsaw)
    """
    SL_VALUES = [-12, -15, -20, -25]
    TP_VALUES = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0]
    MHD_VALUES = [1, 2, 3, 5, 7]

    grid = []
    for sl in SL_VALUES:
        for tp in TP_VALUES:
            for mhd in MHD_VALUES:
                # Constraint: TP floor (slippage eats profit below 0.12%)
                if tp < 0.12:
                    continue
                # Constraint: high TP needs time
                if tp >= 3.0 and mhd < 5:
                    continue
                # Constraint: scalping TP exits fast
                if tp <= 0.5 and mhd > 2:
                    continue
                # Constraint: tight SL + long hold = whipsaw
                if abs(sl) <= 12 and mhd >= 7:
                    continue
                # Constraint: very loose SL + very short hold is contradictory
                if abs(sl) >= 25 and mhd <= 1:
                    continue

                name = f"SL{abs(sl)}_TP{tp}_MHD{mhd}"
                grid.append({
                    "name": name,
                    "stop_loss_pct": sl,
                    "take_profit_pct": tp,
                    "max_hold_days": mhd,
                })

    logger.info("Generated exit grid: %d configs from %d×%d×%d space",
                len(grid), len(SL_VALUES), len(TP_VALUES), len(MHD_VALUES))
    return grid
```

Expected: ~25 configs after constraint filtering (from 4×8×5=160 raw combinations).

- [ ] **Step 2: Replace `DEFAULT_EXIT_GRID` usage**

In `_step_submit` (already done in Task 1), replace:
```python
exit_grid = DEFAULT_EXIT_GRID
```
with:
```python
exit_grid = generate_exit_grid()
```

- [ ] **Step 3: Remove the hardcoded `DEFAULT_EXIT_GRID` constant**

Delete the `DEFAULT_EXIT_GRID` list definition (lines 1802-1813) since it's replaced by the generator.

---

### Task 4: Integration Test & Verification

**Files:**
- No new files — test via API manually

- [ ] **Step 1: Verify exit grid generator output**

Run in Python REPL:
```python
from api.services.exploration_engine import generate_exit_grid
grid = generate_exit_grid()
print(f"Grid size: {len(grid)}")
for g in grid:
    print(f"  {g['name']}: SL={g['stop_loss_pct']}, TP={g['take_profit_pct']}, MHD={g['max_hold_days']}")
```

Expected: ~25 configs, all satisfying constraints.

- [ ] **Step 2: Verify bulk submit creates single experiment**

Start a test exploration round with `exp_per_round=3` (small). Check that `_step_submit` returns exactly 1 experiment ID containing `3 × len(grid)` strategies.

```bash
curl -s http://localhost:8050/api/lab/experiments/{eid} | python -m json.tool | head -5
```

Expected: one experiment with `strategy_count = 3 * ~25 = ~75`.

- [ ] **Step 3: Verify parallel simulation completes**

Monitor the experiment status during backtest. All strategies should progress to done/invalid.

```bash
watch -n 10 'curl -s http://localhost:8050/api/lab/experiments/{eid} | python -c "
import sys, json
d = json.load(sys.stdin)
strats = d.get(\"strategies\", [])
done = sum(1 for s in strats if s[\"status\"]==\"done\")
inv = sum(1 for s in strats if s[\"status\"]==\"invalid\")
pend = sum(1 for s in strats if s[\"status\"] not in (\"done\",\"invalid\",\"failed\"))
print(f\"done={done} invalid={inv} pending={pend} total={len(strats)}\")
"'
```

- [ ] **Step 4: Verify exploration round completes end-to-end**

Run one full exploration round and check:
- `_step_poll` correctly tracks done/invalid/pending
- `_step_promote_and_rebalance` promotes StdA+ strategies
- `_step_record` records round with correct metadata

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Single mega-experiment fails → lose entire round | `_step_self_heal` resubmits failed strategies as new experiments |
| 750 strategies overwhelms DB session | Serial DB writes with per-strategy commit |
| ThreadPoolExecutor memory pressure | Limit to 4 workers (matches current semaphore) |
| API timeout on creating 750 clones | Increased timeout to 600s in `_api` call |
| `_revectorize` called 30 times | Already cached by `_cond_cache` — only unique condition sets are vectorized |

## Rollback

If issues arise, revert `_step_submit` to the per-config loop pattern. The exit grid generator and parallel simulation are independent improvements that can be kept.
