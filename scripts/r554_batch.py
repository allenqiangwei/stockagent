#!/usr/bin/env python3
"""Round 554: Ultimate combo — best buy + best sell conditions.

R553 found:
- RSI40-60 > RSI50-70 (score 0.8437)
- MACD_hist>0 = 100% StdA+ as 4th buy
- aR2vF2+fall2d combined sell = 100% StdA+, 0.8430
- gt5dHigh@MHD15 = 100% StdA+, wr=74.7%

This round: combine everything.
1. RSI40-60 + ATR + aR2vF2+fall2d (best buy + best sell)
2. RSI40-60 + ATR + MACD_hist>0 + aR2vF2+fall2d (4 cond buy + dual sell)
3. RSI40-60 + ATR + aR2vF2+fall2d SLfine across MHD
4. gt5dHigh with RSI40-60 + MACD_hist
5. RSI45-65 + aR2vF2+fall2d ATR sweep
6. lt2dLow + fall2d + aR2vF2 triple sell
7. fall2d ATR0.10 combined with lookback buy conditions
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


def rsi4060_atr_buy(atr_thresh=0.09):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": 40},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": 60},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def rsi4565_atr_buy(atr_thresh=0.09):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": 45},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": 65},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def rsi4060_atr_macd_buy(atr_thresh=0.09):
    """4-condition buy: RSI40-60 + ATR + MACD_hist>0"""
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": 40},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": 60},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
        {"field": "MACD_hist", "params": {"fast": 12, "slow": 26, "signal": 9},
         "operator": ">", "compare_type": "value", "compare_value": 0,
         "label": "MACD_hist>0"},
    ]


def rsi_atr_buy(atr_thresh=0.09):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": 50},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


SELL_AR2VF2_FALL2D = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]

SELL_AR2VF2 = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
]

SELL_GT5DHIGH = [
    {"field": "close", "params": {}, "compare_type": "lookback_max",
     "operator": ">", "lookback_n": 5, "label": "gt5dHigh"},
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
    print("Round 554: Ultimate Combo — Best Buy + Best Sell")
    print("=" * 60)

    # D1: RSI40-60 + aR2vF2+fall2d ATR sweep (best buy + best sell)
    print("\n── D1: RSI40-60 + aR2vF2+fall2d ATR sweep ──")
    for atr in [0.08, 0.085, 0.09, 0.095, 0.10, 0.105, 0.11]:
        eid = submit(f"RSI4060 aR2vF2+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi4060_atr_buy(atr_thresh=atr), SELL_AR2VF2_FALL2D,
                     grid_18(mhd=5), f"RSI4060_aR2vF2fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: RSI40-60 + MACD_hist + aR2vF2+fall2d ATR sweep (4-cond buy + dual sell)
    print("\n── D2: RSI4060+MACDhist + aR2vF2+fall2d ──")
    for atr in [0.09, 0.095, 0.10, 0.105, 0.11]:
        eid = submit(f"RSI4060+MACD aR2vF2+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi4060_atr_macd_buy(atr_thresh=atr), SELL_AR2VF2_FALL2D,
                     grid_18(mhd=5), f"RSI4060_MACD_aR2vF2fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D3: RSI40-60 + aR2vF2+fall2d ATR0.09 SLfine MHD{3,5,7}
    print("\n── D3: RSI4060 aR2vF2+fall2d SLfine ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI4060 aR2vF2+fall2d ATR0.09 SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi4060_atr_buy(atr_thresh=0.09), SELL_AR2VF2_FALL2D,
                     grid_sl_fine(mhd=mhd), f"RSI4060_aR2vF2fall2d_ATR009_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D4: gt5dHigh with RSI40-60 + MACD_hist
    print("\n── D4: gt5dHigh + RSI4060+MACD ──")
    for mhd in [10, 15, 20]:
        eid = submit(f"RSI4060+MACD gt5dHigh MHD{mhd}", ES_MACD_RSI,
                     rsi4060_atr_macd_buy(atr_thresh=0.09), SELL_GT5DHIGH,
                     grid_gt5dhigh(mhd=mhd), f"RSI4060_MACD_gt5dHigh_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D5: RSI45-65 + aR2vF2+fall2d ATR sweep
    print("\n── D5: RSI4565 + aR2vF2+fall2d ──")
    for atr in [0.09, 0.095, 0.10, 0.105]:
        eid = submit(f"RSI4565 aR2vF2+fall2d ATR{atr}", ES_MACD_RSI,
                     rsi4565_atr_buy(atr_thresh=atr), SELL_AR2VF2_FALL2D,
                     grid_18(mhd=5), f"RSI4565_aR2vF2fall2d_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: Triple sell (aR2vF2+fall2d+lt2dLow) at ATR0.09/0.10
    print("\n── D6: Triple sell aR2vF2+fall2d+lt2dLow ──")
    for atr in [0.09, 0.10, 0.105]:
        eid = submit(f"RSI tripleSell ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_TRIPLE,
                     grid_18(mhd=5), f"RSI_tripleSell_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D7: RSI40-60 + aR2vF2 only (no fall2d) at extreme ATR0.11 to compare
    print("\n── D7: RSI4060 + aR2vF2 only ATR extreme ──")
    for atr in [0.09, 0.10, 0.11]:
        eid = submit(f"RSI4060 aR2vF2 ATR{atr}", ES_MACD_RSI,
                     rsi4060_atr_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_18(mhd=5), f"RSI4060_aR2vF2_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")

    with open("/tmp/r554_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r554_experiments.json")


if __name__ == "__main__":
    main()
