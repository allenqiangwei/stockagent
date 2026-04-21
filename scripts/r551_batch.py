#!/usr/bin/env python3
"""Round 551: Fine-grained optimization around discovered optima.

R550 found:
- aR2vF2 ATR0.11 = dd 7.7%, ret 3820% (lowest dd ever)
- lt2dLow ATR0.105 = ret 7651% (highest ever)
- aR2vF2 100% StdA+ at ATR 0.10-0.13

This round: fine-tune SL, TP, and narrow ATR ranges around optima.

Directions:
1. aR2vF2 ATR0.11 SL fine-tune: SL{5,6,7,8,9,10,11,12,13,14,15} × TP{1,1.5,2} = 33 configs per exp
2. lt2dLow ATR fine sweep: ATR 0.100-0.115 step 0.0025 (7 values)
3. aR2vF2 ATR0.105-0.115 step 0.005 (3 values) × KDJ buy
4. lt2dLow + lt3dLow comparison at ATR0.105
"""

import subprocess, json, time, sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}

ES_MACD_RSI = 20989
ES_KDJ = 22581
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


def kdj_buy(atr_thresh=0.09):
    return [
        {"field": "KDJ_K", "params": {"k": 9, "d": 3, "smooth": 3}, "operator": ">",
         "compare_type": "value", "compare_value": 20},
        {"field": "KDJ_K", "params": {"k": 9, "d": 3, "smooth": 3}, "operator": "<",
         "compare_type": "value", "compare_value": 80},
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

SELL_LT3DLOW = [
    {"field": "close", "params": {}, "compare_type": "lookback_min",
     "operator": "<", "lookback_n": 3, "label": "lt3dLow"},
]


def grid_sl_fine(mhd=5):
    """Fine SL grid: SL{5-15} × TP{1.0,1.5,2.0} = 33 configs."""
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
    print("Round 551: Fine-grained Optimization")
    print("=" * 60)

    # D1: aR2vF2 ATR0.11 SL fine-tune (the lowest-dd config)
    print("\n── D1: aR2vF2 ATR0.11 SL fine-tune ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI aR2vF2 ATR0.11 SL-fine MHD{mhd}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=0.11), SELL_AR2VF2,
                     grid_sl_fine(mhd=mhd), f"RSI_aR2vF2_ATR011_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # Also ATR0.105 and ATR0.115 SL fine-tune
    for atr in [0.105, 0.115]:
        eid = submit(f"RSI aR2vF2 ATR{atr} SL-fine", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_sl_fine(mhd=5), f"RSI_aR2vF2_ATR{atr}_SLfine")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: lt2dLow ATR fine sweep 0.100-0.115 step ~0.003
    print("\n── D2: lt2dLow ATR fine sweep ──")
    for atr_thousandths in [100, 103, 105, 107, 110, 113, 115]:
        atr = atr_thousandths / 1000.0
        eid = submit(f"RSI lt2dLow ATR{atr:.3f}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd=5), f"RSI_lt2dLow_ATR{atr:.3f}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D3: KDJ + aR2vF2 at ATR extreme with SL fine-tune
    print("\n── D3: KDJ aR2vF2 ATR extreme SL-fine ──")
    for atr in [0.10, 0.105, 0.11]:
        eid = submit(f"KDJ aR2vF2 ATR{atr} SL-fine", ES_KDJ,
                     kdj_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_sl_fine(mhd=5), f"KDJ_aR2vF2_ATR{atr}_SLfine")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D4: lt2dLow vs lt3dLow at ATR0.105 (optimal ATR)
    print("\n── D4: lt2dLow vs lt3dLow at ATR0.105 ──")
    for sell_name, sell_conds in [("lt2dLow", SELL_LT2DLOW), ("lt3dLow", SELL_LT3DLOW)]:
        for family_name, source_id, buy_fn in [
            ("RSI", ES_MACD_RSI, rsi_atr_buy),
            ("KDJ", ES_KDJ, kdj_buy),
            ("EMA", ES_EMA_ATR, ema_atr_buy),
        ]:
            eid = submit(f"{family_name} {sell_name} ATR0.105", source_id,
                         buy_fn(atr_thresh=0.105), sell_conds,
                         grid_18(mhd=5), f"{family_name}_{sell_name}_ATR0105")
            if eid: experiment_ids.append(eid)
            time.sleep(2)

    # D5: EMA + aR2vF2 ATR extreme SL-fine
    print("\n── D5: EMA aR2vF2 ATR extreme ──")
    for atr in [0.10, 0.11, 0.12]:
        eid = submit(f"EMA aR2vF2 ATR{atr} SL-fine", ES_EMA_ATR,
                     ema_atr_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_sl_fine(mhd=5), f"EMA_aR2vF2_ATR{atr}_SLfine")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: MACD+RSI aR2vF2 ATR0.09 (proven best score) with fine SL
    print("\n── D6: RSI aR2vF2 ATR0.09 SL-fine ──")
    eid = submit("RSI aR2vF2 ATR0.09 SL-fine", ES_MACD_RSI,
                 rsi_atr_buy(atr_thresh=0.09), SELL_AR2VF2,
                 grid_sl_fine(mhd=5), "RSI_aR2vF2_ATR009_SLfine")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    # Also MHD3 for ATR0.09
    eid = submit("RSI aR2vF2 ATR0.09 SL-fine MHD3", ES_MACD_RSI,
                 rsi_atr_buy(atr_thresh=0.09), SELL_AR2VF2,
                 grid_sl_fine(mhd=3), "RSI_aR2vF2_ATR009_SLfine_MHD3")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    # D7: KDJ + lt2dLow ATR0.105-0.115
    print("\n── D7: KDJ lt2dLow ATR fine sweep ──")
    for atr_thousandths in [100, 105, 110, 115]:
        eid = submit(f"KDJ lt2dLow ATR{atr_thousandths/1000:.3f}", ES_KDJ,
                     kdj_buy(atr_thresh=atr_thousandths/1000.0), SELL_LT2DLOW,
                     grid_18(mhd=5), f"KDJ_lt2dLow_ATR{atr_thousandths}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")
    print(f"Total strategies: ~{sum(33 if 'SLfine' in f else 18 for f in ['SLfine']*8 + ['std']*27)}")

    with open("/tmp/r551_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r551_experiments.json")


if __name__ == "__main__":
    main()
