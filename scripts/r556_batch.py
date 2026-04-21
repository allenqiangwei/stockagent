#!/usr/bin/env python3
"""Round 556: Score optimization — TP expansion + MHD fine + ATR ultra-fine.

R555 confirmed:
- aR2vF2+fall2d MHD sweep = 0.8496 dd=6.9% (best StdA+)
- Triple sell wr<60% — NOT usable
- fall2d-only = 100% StdA+, 0.8396

This round: push for 0.85+ on StdA+-compliant strategies.
1. TP expansion 2.5-4.0 with aR2vF2+fall2d at ATR0.09
2. TP expansion with RSI4060 (shifted range)
3. MHD fine 2-8 with SLfine at ATR0.09
4. ATR ultra-fine 0.087-0.093 at SLfine
5. fall1d sell SLfine (faster exit)
6. fall1d+aR2vF2 combined sell
7. Higher TP (2.0-4.0) with wider SL (SL15-25)
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


def rsi_buy(rsi_lo=50, rsi_hi=70, atr_thresh=0.09):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
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

SELL_FALL1D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 1, "direction": "falling", "label": "fall1d"},
]

SELL_AR2VF2_FALL1D = [
    {"field": "ATR", "params": {"period": 14}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "rising", "label": "ATRrise2"},
    {"field": "volume", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "volFall2"},
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 1, "direction": "falling", "label": "fall1d"},
]

SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]


def grid_tp_expand(mhd=5):
    """TP 2.5-4.0 with SL 10-20."""
    configs = []
    for sl in [10, 12, 15, 20]:
        for tp in [2.5, 3.0, 3.5, 4.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_tp_wide(mhd=5):
    """TP 2.0-4.0 with wider SL 15-25."""
    configs = []
    for sl in [15, 18, 20, 25]:
        for tp in [2.0, 2.5, 3.0, 3.5, 4.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_sl_fine(mhd=5):
    configs = []
    for sl in [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd})
    return configs


def grid_mhd_fine(sl_list=[8, 10, 12], tp_list=[1.5, 2.0]):
    """MHD 2-8 with select SL/TP."""
    configs = []
    for mhd in [2, 3, 4, 5, 6, 7, 8]:
        for sl in sl_list:
            for tp in tp_list:
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
    print("Round 556: Score Optimization — TP Expansion + MHD Fine")
    print("=" * 60)

    # D1: TP expansion 2.5-4.0 with aR2vF2+fall2d RSI5070 ATR0.09
    print("\n── D1: TP expansion RSI5070 aR2vF2+fall2d ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI5070 aR2vF2+fall2d TPexp MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(50, 70, 0.09), SELL_AR2VF2_FALL2D,
                     grid_tp_expand(mhd=mhd), f"RSI5070_aR2vF2fall2d_TPexp_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: TP expansion with RSI4060
    print("\n── D2: TP expansion RSI4060 aR2vF2+fall2d ──")
    for mhd in [3, 5, 7]:
        eid = submit(f"RSI4060 aR2vF2+fall2d TPexp MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(40, 60, 0.09), SELL_AR2VF2_FALL2D,
                     grid_tp_expand(mhd=mhd), f"RSI4060_aR2vF2fall2d_TPexp_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D3: MHD fine 2-8 with aR2vF2+fall2d
    print("\n── D3: MHD fine 2-8 ──")
    eid = submit("RSI5070 aR2vF2+fall2d MHDfine", ES_MACD_RSI,
                 rsi_buy(50, 70, 0.09), SELL_AR2VF2_FALL2D,
                 grid_mhd_fine(), f"RSI5070_aR2vF2fall2d_MHDfine")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    eid = submit("RSI4060 aR2vF2+fall2d MHDfine", ES_MACD_RSI,
                 rsi_buy(40, 60, 0.09), SELL_AR2VF2_FALL2D,
                 grid_mhd_fine(), f"RSI4060_aR2vF2fall2d_MHDfine")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    # D4: ATR ultra-fine 0.087-0.093 with SLfine
    print("\n── D4: ATR ultra-fine 0.087-0.093 ──")
    for atr_m in [87, 88, 89, 90, 91, 92, 93]:
        atr = atr_m / 1000.0
        eid = submit(f"RSI5070 aR2vF2+fall2d ATR{atr:.3f} SLfine", ES_MACD_RSI,
                     rsi_buy(50, 70, atr), SELL_AR2VF2_FALL2D,
                     grid_sl_fine(mhd=5), f"RSI5070_aR2vF2fall2d_ATR{atr_m}_SLfine")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D5: fall1d sell SLfine (faster exit)
    print("\n── D5: fall1d SLfine ──")
    for mhd in [3, 5]:
        eid = submit(f"RSI5070 fall1d SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(50, 70, 0.09), SELL_FALL1D,
                     grid_sl_fine(mhd=mhd), f"RSI5070_fall1d_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: fall1d+aR2vF2 combined sell
    print("\n── D6: aR2vF2+fall1d combined ──")
    for mhd in [3, 5]:
        eid = submit(f"RSI5070 aR2vF2+fall1d SLfine MHD{mhd}", ES_MACD_RSI,
                     rsi_buy(50, 70, 0.09), SELL_AR2VF2_FALL1D,
                     grid_sl_fine(mhd=mhd), f"RSI5070_aR2vF2fall1d_SLfine_MHD{mhd}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D7: Higher TP (2.0-4.0) with wider SL (15-25)
    print("\n── D7: Wide SL + High TP ──")
    eid = submit("RSI5070 aR2vF2+fall2d wideSL highTP", ES_MACD_RSI,
                 rsi_buy(50, 70, 0.09), SELL_AR2VF2_FALL2D,
                 grid_tp_wide(mhd=5), f"RSI5070_aR2vF2fall2d_wideSL_highTP")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    eid = submit("RSI4060 aR2vF2+fall2d wideSL highTP", ES_MACD_RSI,
                 rsi_buy(40, 60, 0.09), SELL_AR2VF2_FALL2D,
                 grid_tp_wide(mhd=5), f"RSI4060_aR2vF2fall2d_wideSL_highTP")
    if eid: experiment_ids.append(eid)
    time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")

    with open("/tmp/r556_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r556_experiments.json")


if __name__ == "__main__":
    main()
