#!/usr/bin/env python3
"""Round 553: fall2d deep dive + gt5dHigh + sell combinations + RSI tuning.

R552 found:
- fall2d = 98% StdA+ (NEW sell condition!)
- gt5dHigh = 79.4% wr (29% StdA+)
- aR2vF2 ceiling at ATR0.11

This round:
1. fall2d ATR fine sweep 0.08-0.12
2. fall2d ATR0.10 SLfine MHD{3,5,7,10}
3. fall3d/fall1d vs fall2d comparison
4. gt5dHigh SLfine with higher MHD
5. aR2vF2+fall2d combined sell
6. lt2dLow+fall2d combined sell
7. RSI buy range tuning
8. MACD_hist buy condition + aR2vF2
"""

import subprocess, json, time, sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}

ES_MACD_RSI = 20989


def api_post(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'{API}/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True, env=ENV, timeout=120)
    try:
        return json.loads(r.stdout)
    except:
        print(f"ERROR: {r.stdout[:200]}", file=sys.stderr)
        return {}


def rsi_atr_buy(atr_thresh=0.09, rsi_lo=50, rsi_hi=70):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def rsi_atr_macd_buy(atr_thresh=0.09):
    """Add MACD_hist > 0 as extra buy filter."""
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": 50},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
        {"field": "MACD_hist", "params": {"fast": 12, "slow": 26, "signal": 9},
         "operator": ">", "compare_type": "value", "compare_value": 0,
         "label": "MACD_hist>0"},
    ]


SELL_AR2VF2 = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
]

SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]

SELL_FALL3D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 3, "direction": "falling", "label": "fall3d"},
]

SELL_FALL1D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 1, "direction": "falling", "label": "fall1d"},
]

SELL_LT2DLOW = [
    {"field": "close", "params": {}, "compare_type": "lookback_min",
     "operator": "<", "lookback_n": 2, "label": "lt2dLow"},
]

SELL_GT5DHIGH = [
    {"field": "close", "params": {}, "compare_type": "lookback_max",
     "operator": ">", "lookback_n": 5, "label": "gt5dHigh"},
]

# Combined sell conditions
SELL_AR2VF2_FALL2D = SELL_AR2VF2 + SELL_FALL2D
SELL_LT2DLOW_FALL2D = SELL_LT2DLOW + SELL_FALL2D


def grid_18(mhd=5):
    configs = []
    for sl in [10, 12, 15, 20, 25, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_sl_fine(mhd=5):
    configs = []
    for sl in [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_gt5dhigh(mhd=15):
    """For gt5dHigh: needs longer MHD. SL{10,15,20,99} x TP{1,1.5,2} = 12."""
    configs = []
    for sl in [10, 15, 20, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def make_batch(source_id, buy_conds, sell_conds, exit_grid, suffix_base):
    configs = []
    for ec in exit_grid:
        sl = abs(ec["stop_loss_pct"])
        tp = ec["take_profit_pct"]
        mhd = ec["max_hold_days"]
        suffix = f"{suffix_base}_SL{sl}_TP{tp}_MHD{mhd}"
        cfg = {"name_suffix": suffix, "exit_config": ec}
        if buy_conds is not None:
            cfg["buy_conditions"] = buy_conds
        if sell_conds is not None:
            cfg["sell_conditions"] = sell_conds
        configs.append(cfg)
    return {"source_strategy_id": source_id, "exit_configs": configs,
            "initial_capital": 100000, "max_positions": 10, "max_position_pct": 30}


def submit(label, source_id, buy, sell, grid, suffix):
    data = make_batch(source_id, buy, sell, grid, suffix)
    n = len(data["exit_configs"])
    print(f"  [{label}] ES{source_id} × {n}...", end=" ", flush=True)
    result = api_post(f"lab/strategies/{source_id}/batch-clone-backtest", data)
    eid = result.get("experiment_id")
    if eid:
        print(f"E{eid}")
    else:
        print(f"FAILED: {result}")
    return eid


def main():
    start_time = time.time()
    experiment_ids = []

    print("=" * 60)
    print("Round 553: fall2d Deep Dive + Sell Combinations")
    print("=" * 60)

    # D1: fall2d ATR fine sweep 0.080-0.120 (step ~0.005)
    print("\n── D1: fall2d ATR fine sweep ──")
    for atr_thousandths in [80, 85, 90, 95, 100, 105, 110, 115, 120]:
        atr = atr_thousandths / 1000.0
        eid = submit(f"RSI fall2d ATR{atr:.3f}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_FALL2D,
                     grid_18(mhd=5), f"RSI_fall2d_ATR{atr:.3f}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: fall2d ATR0.10 SLfine MHD{3,5,7,10}
    print("\n── D2: fall2d ATR0.10 SLfine MHD sweep ──")
    for mhd in [3, 5, 7, 10]:
        eid = submit(f"RSI fall2d ATR0.10 SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.10), SELL_FALL2D,
                     grid_sl_fine(mhd=mhd), f"RSI_fall2d_ATR010_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D3: fall3d/fall1d vs fall2d at ATR0.10
    print("\n── D3: fall1d/fall3d vs fall2d ──")
    for sell_name, sell_conds in [("fall1d", SELL_FALL1D), ("fall3d", SELL_FALL3D)]:
        eid = submit(f"RSI {sell_name} ATR0.10", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.10), sell_conds,
                     grid_18(mhd=5), f"RSI_{sell_name}_ATR010")
        if eid: experiment_ids.append(eid)
        time.sleep(2)
    # Also fall2d at ATR0.10 for direct comparison (already in D1)

    # D4: gt5dHigh SLfine with higher MHD
    print("\n── D4: gt5dHigh MHD{10,15,20} SLfine ──")
    for mhd in [10, 15, 20]:
        eid = submit(f"RSI gt5dHigh ATR0.09 MHD{mhd}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.09), SELL_GT5DHIGH,
                     grid_gt5dhigh(mhd=mhd), f"RSI_gt5dHigh_ATR009_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D5: aR2vF2 + fall2d combined sell at ATR 0.09/0.10/0.11
    print("\n── D5: aR2vF2+fall2d combined sell ──")
    for atr in [0.09, 0.10, 0.11]:
        eid = submit(f"RSI aR2vF2+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_AR2VF2_FALL2D,
                     grid_18(mhd=5), f"RSI_aR2vF2_fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: lt2dLow + fall2d combined sell at ATR0.105
    print("\n── D6: lt2dLow+fall2d combined sell ──")
    for atr in [0.10, 0.105]:
        eid = submit(f"RSI lt2dLow+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_LT2DLOW_FALL2D,
                     grid_18(mhd=5), f"RSI_lt2dLow_fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D7: RSI buy range tuning with aR2vF2 at ATR0.09
    print("\n── D7: RSI range tuning ──")
    for rsi_lo, rsi_hi in [(45, 65), (55, 75), (40, 60)]:
        eid = submit(f"RSI{rsi_lo}-{rsi_hi} aR2vF2 ATR0.09", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.09, rsi_lo=rsi_lo, rsi_hi=rsi_hi), SELL_AR2VF2,
                     grid_18(mhd=5), f"RSI{rsi_lo}_{rsi_hi}_aR2vF2_ATR009")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D8: MACD_hist>0 as extra buy filter + aR2vF2
    print("\n── D8: MACD_hist buy filter ──")
    for atr in [0.09, 0.10, 0.11]:
        eid = submit(f"RSI+MACDhist aR2vF2 ATR{atr}", ES_MACD_RSI,
                     rsi_atr_macd_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_18(mhd=5), f"RSI_MACDhist_aR2vF2_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")

    with open("/tmp/r553_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r553_experiments.json")


if __name__ == "__main__":
    main()
