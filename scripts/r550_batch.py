#!/usr/bin/env python3
"""Round 550: ATR extreme sweep + RSI21 + wider TP grid.

Key insight from R549: Returns scale exponentially with ATR.
Test: ATR 0.10-0.13 for lt2dLow, RSI21 for aR2vF2, wider TP for high-return.

Directions:
1. MACD+RSI lt2dLow ATR extreme (0.10-0.13) — 8 experiments
2. MACD+RSI aR2vF2 with RSI21 — 8 experiments
3. KDJ aR2vF2 KDJ range variations — 8 experiments
4. MACD+RSI lt2dLow wider TP (2.5-5.0) — 6 experiments
5. MACD+RSI aR2vF2 ATR extreme (0.10-0.13) — 8 experiments
6. EMA+ATR lt2dLow ATR extreme — 6 experiments
7. KDJ lt2dLow ATR extreme — 6 experiments
"""

import subprocess, json, time, sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}

ES_KDJ = 22581
ES_MACD_RSI = 20989
ES_EMA_ATR = 20980


def api_post(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'{API}/{path}',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(data)],
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


def rsi21_atr_buy(atr_thresh=0.09, rsi_lo=50, rsi_hi=70):
    """RSI with period 21 instead of 14."""
    return [
        {"field": "RSI", "params": {"period": 21}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 21}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def kdj_buy(kdj_lo=30, kdj_hi=70, atr_thresh=0.09):
    return [
        {"field": "KDJ_K", "params": {"k": 9, "d": 3, "smooth": 3}, "operator": ">",
         "compare_type": "value", "compare_value": kdj_lo},
        {"field": "KDJ_K", "params": {"k": 9, "d": 3, "smooth": 3}, "operator": "<",
         "compare_type": "value", "compare_value": kdj_hi},
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


def grid_18(mhd_fixed=5):
    configs = []
    for sl in [10, 12, 15, 20, 25, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd_fixed})
    return configs


def grid_wide_tp(mhd_fixed=5):
    """Wider TP grid for high-return experiments: SL{15,20,99} × TP{2.0,2.5,3.0,3.5,4.0,5.0}."""
    configs = []
    for sl in [15, 20, 99]:
        for tp in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
            configs.append({"stop_loss_pct": -sl, "take_profit_pct": tp, "max_hold_days": mhd_fixed})
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
    print("Round 550: ATR Extreme + RSI21 + Wide TP")
    print("=" * 60)

    # D1: MACD+RSI lt2dLow ATR extreme (0.10-0.13)
    print("\n── D1: MACD+RSI lt2dLow ATR 0.10-0.13 ──")
    for atr_int in [100, 105, 110, 115, 120, 125, 130]:
        atr = atr_int / 1000.0
        eid = submit(f"RSI lt2dLow ATR{atr:.3f}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd_fixed=5), f"RSI_lt2dLow_ATR{atr:.3f}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # Also test MHD7 for ATR0.11/0.12
    for atr in [0.11, 0.12]:
        eid = submit(f"RSI lt2dLow ATR{atr} MHD7", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd_fixed=7), f"RSI_lt2dLow_ATR{atr}_MHD7")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D2: MACD+RSI aR2vF2 with RSI21 (lower dd expected)
    print("\n── D2: RSI21 + aR2vF2 sell ──")
    for atr in [0.08, 0.085, 0.09, 0.095]:
        for mhd in [3, 5]:
            eid = submit(f"RSI21 aR2vF2 ATR{atr} MHD{mhd}", ES_MACD_RSI,
                         rsi21_atr_buy(atr_thresh=atr), SELL_AR2VF2,
                         grid_18(mhd_fixed=mhd), f"RSI21_aR2vF2_ATR{atr}_MHD{mhd}")
            if eid: experiment_ids.append(eid)
            time.sleep(2)

    # D3: KDJ aR2vF2 K range variations (find optimal KDJ range)
    print("\n── D3: KDJ aR2vF2 K range variations ──")
    for klo, khi in [(20, 60), (25, 65), (35, 75), (40, 80), (20, 80), (30, 80), (25, 70), (35, 70)]:
        eid = submit(f"KDJ K{klo}-{khi} aR2vF2", ES_KDJ,
                     kdj_buy(kdj_lo=klo, kdj_hi=khi, atr_thresh=0.09), SELL_AR2VF2,
                     grid_18(mhd_fixed=5), f"KDJ_K{klo}_{khi}_aR2vF2")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D4: MACD+RSI lt2dLow wider TP grid (for ATR 0.09-0.11)
    print("\n── D4: lt2dLow wide TP grid ──")
    for atr in [0.09, 0.095, 0.10, 0.105, 0.11, 0.115]:
        eid = submit(f"RSI lt2dLow wTP ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_wide_tp(mhd_fixed=5), f"RSI_lt2dLow_wTP_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D5: MACD+RSI aR2vF2 ATR extreme
    print("\n── D5: MACD+RSI aR2vF2 ATR extreme ──")
    for atr in [0.10, 0.105, 0.11, 0.115, 0.12, 0.125, 0.13]:
        eid = submit(f"RSI aR2vF2 ATR{atr}", ES_MACD_RSI,
                     rsi_atr_buy(atr_thresh=atr), SELL_AR2VF2,
                     grid_18(mhd_fixed=5), f"RSI_aR2vF2_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D6: EMA+ATR lt2dLow ATR extreme
    print("\n── D6: EMA lt2dLow ATR extreme ──")
    for atr in [0.10, 0.11, 0.12, 0.13]:
        eid = submit(f"EMA lt2dLow ATR{atr}", ES_EMA_ATR,
                     ema_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd_fixed=5), f"EMA_lt2dLow_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # D7: KDJ lt2dLow ATR extreme
    print("\n── D7: KDJ lt2dLow ATR extreme ──")
    for atr in [0.10, 0.11, 0.12, 0.13]:
        eid = submit(f"KDJ lt2dLow ATR{atr}", ES_KDJ,
                     kdj_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd_fixed=5), f"KDJ_lt2dLow_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    # RSI21 + lt2dLow (lower dd expected)
    print("\n── Bonus: RSI21 + lt2dLow ──")
    for atr in [0.09, 0.095, 0.10]:
        eid = submit(f"RSI21 lt2dLow ATR{atr}", ES_MACD_RSI,
                     rsi21_atr_buy(atr_thresh=atr), SELL_LT2DLOW,
                     grid_18(mhd_fixed=5), f"RSI21_lt2dLow_ATR{atr}")
        if eid: experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")
    print(f"Total strategies: ~{len(experiment_ids) * 18}")

    with open("/tmp/r550_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"Saved to /tmp/r550_experiments.json")


if __name__ == "__main__":
    main()
