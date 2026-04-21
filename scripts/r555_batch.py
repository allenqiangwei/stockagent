#!/usr/bin/env python3
"""Round 555: Triple sell optimization + RSI range tuning + MHD sweep.

R554 found:
- RSI4060+MACD+aR2vF2+fall2d = 100% StdA+, 0 invalid (most reliable)
- SLfine (SL5-15) = 0.8495 score, dd=6.9% (lowest!)
- Triple sell (aR2vF2+fall2d+lt2dLow) = 0.8535 + 9364% ret
- RSI4060 > RSI5070 confirmed across all directions

This round:
1. Triple sell SLfine MHD{3,5,7} (optimize 0.8535)
2. Triple sell + RSI4060+MACD (4-cond buy + 4-cond sell)
3. RSI4060+MACD + aR2vF2+fall2d SLfine ATR{0.095,0.10,0.105}
4. RSI35-55 + aR2vF2+fall2d (narrow range test)
5. RSI45-55 + aR2vF2+fall2d (ultra-narrow range)
6. aR2vF2+fall2d MHD{3,7,10} with RSI4060
7. fall2d-only SLfine (simpler sell, what score?)
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


def rsi_buy(rsi_lo=40, rsi_hi=60, atr_thresh=0.09):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def rsi_macd_buy(rsi_lo=40, rsi_hi=60, atr_thresh=0.09):
    return rsi_buy(rsi_lo, rsi_hi, atr_thresh) + [
        {"field": "MACD_hist", "params": {"fast": 12, "slow": 26, "signal": 9},
         "operator": ">", "compare_type": "value", "compare_value": 0,
         "label": "MACD_hist>0"},
    ]


SELL_AR2VF2_FALL2D = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]

SELL_TRIPLE = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
    {"field": "close", "params": {}, "compare_type": "lookback_min",
     "operator": "<", "lookback_n": 2, "label": "lt2dLow"},
]

SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]


def grid_sl_fine(mhd=5):
    configs = []
    for sl in [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_18(mhd=5):
    configs = []
    for sl in [10, 12, 15, 20, 25, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_mhd(mhd_list, sl_list=[10, 12, 15, 20], tp_list=[1.0, 1.5, 2.0]):
    configs = []
    for mhd in mhd_list:
        for sl in sl_list:
            for tp in tp_list:
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
    print("Round 555: Triple Sell Optimization + RSI Range Tuning")
    print("=" * 60)

    # D1: Triple sell SLfine MHD{3,5,7}
    print("\n── D1: Triple sell SLfine ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI5070 tripleSell SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(50, 70, 0.09), SELL_TRIPLE,
                     grid_sl_fine(mhd=mhd), f"RSI5070_tripleSell_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: Triple sell + RSI4060+MACD (4-cond buy + 4-cond sell)
    print("\n── D2: Triple sell + RSI4060+MACD ──")
    for atr in [0.09, 0.095, 0.10, 0.105]:
        eid = submit(f"RSI4060+MACD tripleSell ATR{atr}", ES_MACD_RSI,
                     rsi_macd_buy(40, 60, atr), SELL_TRIPLE,
                     grid_18(mhd=5), f"RSI4060_MACD_tripleSell_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D3: RSI4060+MACD + aR2vF2+fall2d SLfine ATR sweep
    print("\n── D3: RSI4060+MACD aR2vF2+fall2d SLfine ──")
    for atr in [0.095, 0.10, 0.105]:
        eid = submit(f"RSI4060+MACD aR2vF2+fall2d SLfine ATR{atr}", ES_MACD_RSI,
                     rsi_macd_buy(40, 60, atr), SELL_AR2VF2_FALL2D,
                     grid_sl_fine(mhd=5), f"RSI4060_MACD_aR2vF2fall2d_SLfine_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D4: RSI35-55 + aR2vF2+fall2d (narrow range test)
    print("\n── D4: RSI3555 + aR2vF2+fall2d ──")
    for atr in [0.09, 0.095, 0.10]:
        eid = submit(f"RSI3555 aR2vF2+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi_buy(35, 55, atr), SELL_AR2VF2_FALL2D,
                     grid_18(mhd=5), f"RSI3555_aR2vF2fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D5: RSI45-55 + aR2vF2+fall2d (ultra-narrow)
    print("\n── D5: RSI4555 + aR2vF2+fall2d ──")
    for atr in [0.09, 0.10]:
        eid = submit(f"RSI4555 aR2vF2+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi_buy(45, 55, atr), SELL_AR2VF2_FALL2D,
                     grid_18(mhd=5), f"RSI4555_aR2vF2fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: aR2vF2+fall2d MHD{3,7,10} with RSI4060
    print("\n── D6: aR2vF2+fall2d MHD sweep ──")
    eid = submit("RSI4060 aR2vF2+fall2d MHD{3,5,7,10}", ES_MACD_RSI,
                 rsi_buy(40, 60, 0.09), SELL_AR2VF2_FALL2D,
                 grid_mhd([3, 5, 7, 10]), f"RSI4060_aR2vF2fall2d_MHDsweep")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    # D7: fall2d-only SLfine (simpler sell baseline)
    print("\n── D7: fall2d-only SLfine ──")
    for mhd in [3, 5]:
        eid = submit(f"RSI4060 fall2d SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(40, 60, 0.09), SELL_FALL2D,
                     grid_sl_fine(mhd=mhd), f"RSI4060_fall2d_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D8: Triple sell RSI4060 SLfine (best of D1+D2 combine)
    print("\n── D8: Triple sell RSI4060 SLfine ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI4060 tripleSell SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(40, 60, 0.09), SELL_TRIPLE,
                     grid_sl_fine(mhd=mhd), f"RSI4060_tripleSell_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")

    with open("/tmp/r555_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r555_experiments.json")


if __name__ == "__main__":
    main()
