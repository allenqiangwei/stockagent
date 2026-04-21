#!/usr/bin/env python3
"""Round 552: Peak-hunting + sell condition comparison + MHD exploration.

R551 found:
- lt2dLow ATR0.107 = 8376% (new all-time)
- aR2vF2 ATR0.11 = 100% StdA+, SL insensitive
- KDJ + ATR>=0.10 = signal explosion (invalid)

This round:
1. lt2dLow ATR ultra-fine 0.103-0.108 (peak hunting)
2. lt2dLow ATR0.105/0.107 SL fine-tune across MHD
3. aR2vF2 ATR0.11 MHD sweep (2-10)
4. fall2d (conservative sell) ATR sweep
5. gt5dHigh (high-wr sell) ATR sweep
6. lt2dLow vs fall2d at ATR0.105
7. aR2vF2 extreme ATR push (0.12-0.14)
"""

import subprocess, json, time, sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}

ES_MACD_RSI = 20989
ES_EMA_ATR = 20980


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


def rsi_atr_buy(atr_thresh=0.09):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": 50},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def ema_atr_buy(atr_thresh=0.09):
    return [
        {"field": "close", "params": {}, "operator": ">",
         "compare_type": "field", "compare_field": "EMA",
         "compare_params": {"length": 12}, "label": "close>EMA12"},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


SELL_AR2VF2 = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
]

SELL_LT2DLOW = [
    {"field": "close", "params": {}, "compare_type": "lookback_min",
     "operator": "<", "lookback_n": 2, "label": "lt2dLow"},
]

SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]

SELL_GT5DHIGH = [
    {"field": "close", "params": {}, "compare_type": "lookback_max",
     "operator": ">", "lookback_n": 5, "label": "gt5dHigh"},
]


def grid_18(mhd=5):
    configs = []
    for sl in [10, 12, 15, 20, 25, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_sl_fine(mhd=5):
    """SL{5-15} x TP{1,1.5,2} = 33 configs."""
    configs = []
    for sl in [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_mhd_sweep():
    """MHD{2,4,6,8,10} x SL{8,10,12} x TP{1,1.5,2} = 45 configs."""
    configs = []
    for mhd in [2, 4, 6, 8, 10]:
        for sl in [8, 10, 12]:
            for tp in [1.0, 1.5, 2.0]:
                configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_gt5dhigh():
    """For gt5dHigh sell: TP{0.12,0.15,0.18,1.0} x SL{10,15,20,99} x MHD{10,15} = 32 configs."""
    configs = []
    for mhd in [10, 15]:
        for sl in [10, 15, 20, 99]:
            for tp in [0.12, 0.15, 0.18, 1.0]:
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
    print("Round 552: Peak-hunting + Sell Comparison + MHD Exploration")
    print("=" * 60)

    # D1: lt2dLow ATR ultra-fine peak hunting (0.103, 0.104, 0.106, 0.108)
    print("\n── D1: lt2dLow ATR ultra-fine peak ──")
    for atr_thousandths in [103, 104, 106, 108]:
        atr = atr_thousandths / 1000.0
        eid = submit(f"RSI lt2dLow ATR{atr:.3f}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd=5), f"RSI_lt2dLow_ATR{atr:.3f}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: lt2dLow ATR0.105 SL fine-tune with MHD{3,5,7}
    print("\n── D2: lt2dLow ATR0.105 SL-fine MHD sweep ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI lt2dLow ATR0.105 SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.105), SELL_LT2DLOW,
                     grid_sl_fine(mhd=mhd), f"RSI_lt2dLow_ATR0105_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D3: lt2dLow ATR0.107 SL fine-tune with MHD{3,5,7}
    print("\n── D3: lt2dLow ATR0.107 SL-fine MHD sweep ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI lt2dLow ATR0.107 SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.107), SELL_LT2DLOW,
                     grid_sl_fine(mhd=mhd), f"RSI_lt2dLow_ATR0107_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D4: aR2vF2 ATR0.11 MHD sweep (all MHD values)
    print("\n── D4: aR2vF2 ATR0.11 MHD sweep ──")
    eid = submit("RSI aR2vF2 ATR0.11 MHD sweep", ES_MACD_RSI,
                 rsi_atr_buy(atr_thresh=0.11), SELL_AR2VF2,
                 grid_mhd_sweep(), "RSI_aR2vF2_ATR011_MHDsweep")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    # Also EMA buy + aR2vF2 ATR0.11 MHD sweep
    eid = submit("EMA aR2vF2 ATR0.11 MHD sweep", ES_EMA_ATR,
                 ema_atr_buy(atr_thresh=0.11), SELL_AR2VF2,
                 grid_mhd_sweep(), "EMA_aR2vF2_ATR011_MHDsweep")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    # D5: fall2d (conservative sell) ATR sweep
    print("\n── D5: fall2d conservative sell ATR sweep ──")
    for atr in [0.09, 0.095, 0.10, 0.105, 0.11]:
        eid = submit(f"RSI fall2d ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_FALL2D,
                     grid_18(mhd=5), f"RSI_fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: gt5dHigh (high-wr sell) ATR sweep
    print("\n── D6: gt5dHigh high-wr sell ATR sweep ──")
    for atr in [0.09, 0.10, 0.11]:
        eid = submit(f"RSI gt5dHigh ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_GT5DHIGH,
                     grid_gt5dhigh(), f"RSI_gt5dHigh_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # Also EMA buy + gt5dHigh
    for atr in [0.09, 0.10, 0.11]:
        eid = submit(f"EMA gt5dHigh ATR{atr}", ES_EMA_ATR,
                     ema_atr_buy(atr_thresh=atr), SELL_GT5DHIGH,
                     grid_gt5dhigh(), f"EMA_gt5dHigh_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D7: lt2dLow vs fall2d at ATR0.105 comparison
    print("\n── D7: lt2dLow vs fall2d at ATR0.105 ──")
    # lt2dLow already tested; test fall2d at same ATR
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI fall2d ATR0.105 SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.105), SELL_FALL2D,
                     grid_sl_fine(mhd=mhd), f"RSI_fall2d_ATR0105_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D8: aR2vF2 extreme ATR push (0.12, 0.13, 0.14)
    print("\n── D8: aR2vF2 extreme ATR push ──")
    for atr in [0.12, 0.13, 0.14]:
        eid = submit(f"RSI aR2vF2 ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_18(mhd=5), f"RSI_aR2vF2_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")

    with open("/tmp/r552_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r552_experiments.json")


if __name__ == "__main__":
    main()
