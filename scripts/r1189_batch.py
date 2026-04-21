#!/usr/bin/env python3
"""R1189: 500-experiment batch exploration script.

Skeleton-driven allocation:
- MACD+RSI (source ES75014): 200 experiments — buy_conditions variations (RSI range, ATR, AbvMin, sell conditions)
- 三指標 (source ES75293): 80 experiments — MFI/ROC/ATR/BOLL thresholds × exit params
- VPT+PSAR (source ES75063): 60 experiments — VPT/BOLL_wband thresholds × exit params
- RSI+KDJ激進版B (source ES36540): 80 experiments — KDJ_K range, ATR threshold × exit params
- 全指標 (source ES75014, buy override): 80 experiments — close>EMA, ATR filter, sell conditions

Each experiment = 8 strategies via batch-clone-backtest.
Total: 500 experiments × 8 = 4000 strategies.
Serial backtest ~4min/strategy = ~267h. Run as background auto_finish.
"""

import subprocess
import json
import time
import itertools
import sys
from datetime import datetime

API_BASE = "http://127.0.0.1:8050/api"
START_TIME = datetime.now().isoformat()

def api_post(path, data):
    """POST JSON to API."""
    r = subprocess.run(
        ['curl', '-s', '--max-time', '30', '-X', 'POST', f'{API_BASE}/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {'error': r.stdout[:200]}


def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'{API_BASE}/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {}


def submit_batch(source_es_id, exit_configs):
    """Submit batch-clone-backtest and return experiment ID."""
    result = api_post(f'lab/strategies/{source_es_id}/batch-clone-backtest', {
        "source_strategy_id": source_es_id,
        "exit_configs": exit_configs,
    })
    exp_id = result.get('experiment_id')
    if exp_id:
        return exp_id
    else:
        print(f"  ERROR: {json.dumps(result)[:200]}")
        return None


# ─── Define parameter grids ───

# Sell condition variants
SELL_LT2DLOW = [{"field": "close", "operator": "<", "compare_type": "lookback_min", "lookback_n": 2}]
SELL_AR2VF2 = [
    {"field": "ATR", "params": {"period": 14}, "operator": ">", "compare_type": "consecutive", "consecutive_type": "rising", "lookback_n": 2},
    {"field": "volume", "operator": ">", "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
]
SELL_FALL2D = [{"field": "close", "operator": "<", "compare_type": "consecutive", "consecutive_n": 2, "direction": "falling"}]
SELL_GT10DH = [{"field": "close", "operator": ">", "compare_type": "lookback_max", "lookback_n": 10}]
SELL_RISE4D = [{"field": "close", "operator": ">", "compare_type": "consecutive", "consecutive_n": 4, "direction": "rising"}]

SELL_VARIANTS = {
    "lt2dLow": SELL_LT2DLOW,
    "aR2vF2": SELL_AR2VF2,
    "fall2d": SELL_FALL2D,
    "gt10dH": SELL_GT10DH,
    "rise4d": SELL_RISE4D,
}

# Exit param presets (8 per experiment)
EXIT_GRIDS = {
    "tight": [
        {"stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 2},
        {"stop_loss_pct": -20, "take_profit_pct": 1.5, "max_hold_days": 2},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 3},
        {"stop_loss_pct": -20, "take_profit_pct": 2.5, "max_hold_days": 3},
        {"stop_loss_pct": -30, "take_profit_pct": 1.0, "max_hold_days": 2},
        {"stop_loss_pct": -30, "take_profit_pct": 1.5, "max_hold_days": 3},
        {"stop_loss_pct": -30, "take_profit_pct": 2.0, "max_hold_days": 5},
        {"stop_loss_pct": -30, "take_profit_pct": 3.0, "max_hold_days": 5},
    ],
    "wide": [
        {"stop_loss_pct": -20, "take_profit_pct": 3.0, "max_hold_days": 3},
        {"stop_loss_pct": -20, "take_profit_pct": 4.0, "max_hold_days": 5},
        {"stop_loss_pct": -20, "take_profit_pct": 5.0, "max_hold_days": 5},
        {"stop_loss_pct": -30, "take_profit_pct": 3.0, "max_hold_days": 5},
        {"stop_loss_pct": -30, "take_profit_pct": 4.0, "max_hold_days": 7},
        {"stop_loss_pct": -30, "take_profit_pct": 5.0, "max_hold_days": 7},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 2},
        {"stop_loss_pct": -30, "take_profit_pct": 2.0, "max_hold_days": 3},
    ],
    "ultra_tight": [
        {"stop_loss_pct": -20, "take_profit_pct": 0.5, "max_hold_days": 1},
        {"stop_loss_pct": -20, "take_profit_pct": 0.8, "max_hold_days": 1},
        {"stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 1},
        {"stop_loss_pct": -20, "take_profit_pct": 1.2, "max_hold_days": 2},
        {"stop_loss_pct": -30, "take_profit_pct": 0.5, "max_hold_days": 1},
        {"stop_loss_pct": -30, "take_profit_pct": 0.8, "max_hold_days": 2},
        {"stop_loss_pct": -30, "take_profit_pct": 1.0, "max_hold_days": 2},
        {"stop_loss_pct": -30, "take_profit_pct": 1.5, "max_hold_days": 3},
    ],
    "mhd_sweep": [
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 1},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 2},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 3},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 5},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 7},
        {"stop_loss_pct": -20, "take_profit_pct": 2.0, "max_hold_days": 10},
        {"stop_loss_pct": -20, "take_profit_pct": 3.0, "max_hold_days": 2},
        {"stop_loss_pct": -20, "take_profit_pct": 3.0, "max_hold_days": 5},
    ],
}


def make_exit_configs(exit_grid_name, sell_name):
    """Create exit_configs list from a grid preset + sell condition."""
    sell_conds = SELL_VARIANTS[sell_name]
    configs = []
    for ec in EXIT_GRIDS[exit_grid_name]:
        tp = ec["take_profit_pct"]
        mhd = ec["max_hold_days"]
        sl = abs(ec["stop_loss_pct"])
        suffix = f"_{sell_name}_TP{tp}_MHD{mhd}_SL{sl}"
        configs.append({
            "name_suffix": suffix,
            "exit_config": ec,
            "sell_conditions": sell_conds,
        })
    return configs


def make_exit_configs_with_buy(exit_grid_name, sell_name, buy_conditions):
    """Create exit_configs list with buy_conditions override."""
    sell_conds = SELL_VARIANTS[sell_name]
    configs = []
    for ec in EXIT_GRIDS[exit_grid_name]:
        tp = ec["take_profit_pct"]
        mhd = ec["max_hold_days"]
        sl = abs(ec["stop_loss_pct"])
        suffix = f"_{sell_name}_TP{tp}_MHD{mhd}_SL{sl}"
        configs.append({
            "name_suffix": suffix,
            "exit_config": ec,
            "buy_conditions": buy_conditions,
            "sell_conditions": sell_conds,
        })
    return configs


# ─── Generate experiments ───

def gen_macd_rsi_experiments():
    """200 experiments: MACD+RSI skeleton variations.
    Source: ES75014 (RSI47-67, ATR<0.12, AbvMin10+BelMax10, ATRcalm7d3pct, lt2dLow)
    Vary: RSI period, RSI range, ATR threshold, AbvMin, sell conditions.
    """
    experiments = []

    # RSI period × RSI range × ATR threshold combinations
    rsi_periods = [14, 16, 18, 20]
    rsi_lows = [47, 48, 50, 52, 55]
    rsi_highs = [65, 67, 70, 72, 75]
    atr_thresholds = [0.0875, 0.09, 0.095, 0.10, 0.105, 0.11, 0.12]
    abvmin_values = [3, 5, 8, 10, 13, 15, 20, 25]

    count = 0
    for rsi_p in rsi_periods:
        for rsi_lo in rsi_lows:
            for rsi_hi in rsi_highs:
                if rsi_lo >= rsi_hi - 5:
                    continue  # skip invalid ranges
                for atr_t in atr_thresholds:
                    for abvmin in abvmin_values:
                        for sell_name in SELL_VARIANTS:
                            for grid_name in EXIT_GRIDS:
                                buy = [
                                    {"field": "RSI", "params": {"period": rsi_p}, "operator": ">", "compare_type": "value", "compare_value": rsi_lo},
                                    {"field": "RSI", "params": {"period": rsi_p}, "operator": "<", "compare_type": "value", "compare_value": rsi_hi},
                                    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr_t},
                                    {"field": "close", "operator": ">", "compare_type": "lookback_min", "lookback_n": abvmin},
                                    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "pct_change", "lookback_n": 7, "compare_value": 3},
                                ]
                                configs = make_exit_configs_with_buy(grid_name, sell_name, buy)
                                experiments.append((75014, configs))
                                count += 1
                                if count >= 200:
                                    return experiments
    return experiments


def gen_san_zhibiao_experiments():
    """80 experiments: 三指標 skeleton variations.
    Source: ES75293 (close>BOLL_middle, MFI>40, ROC>0.5, ATR<0.06)
    Vary: MFI threshold, ROC threshold, ATR threshold, sell conditions.
    """
    experiments = []

    mfi_values = [30, 35, 40, 45, 50]
    roc_values = [0.3, 0.5, 0.8, 1.0, 1.5]
    atr_values = [0.04, 0.05, 0.06, 0.07, 0.08]

    count = 0
    for mfi in mfi_values:
        for roc in roc_values:
            for atr in atr_values:
                for sell_name in ["lt2dLow", "aR2vF2", "fall2d", "gt10dH"]:
                    buy = [
                        {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "BOLL_middle", "compare_params": {"length": 20, "std": 2.0}},
                        {"field": "MFI", "params": {"length": 14}, "operator": ">", "compare_type": "value", "compare_value": mfi},
                        {"field": "ROC", "params": {"length": 12}, "operator": ">", "compare_type": "value", "compare_value": roc},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                    ]
                    grid_name = "tight" if count % 4 == 0 else ("wide" if count % 4 == 1 else ("ultra_tight" if count % 4 == 2 else "mhd_sweep"))
                    configs = make_exit_configs_with_buy(grid_name, sell_name, buy)
                    experiments.append((75293, configs))
                    count += 1
                    if count >= 80:
                        return experiments
    return experiments


def gen_vpt_psar_experiments():
    """60 experiments: VPT+PSAR skeleton variations.
    Source: ES75063 (VPT>-1000, close>PSAR, BOLL_wband<5.0)
    Vary: VPT threshold, BOLL_wband threshold, sell conditions.
    """
    experiments = []

    vpt_values = [-2000, -1500, -1000, -500, 0]
    boll_wband_values = [3.0, 4.0, 5.0, 6.0, 8.0]

    count = 0
    for vpt in vpt_values:
        for bw in boll_wband_values:
            for sell_name in SELL_VARIANTS:
                buy = [
                    {"field": "VPT", "params": {}, "operator": ">", "compare_type": "value", "compare_value": vpt},
                    {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "PSAR", "compare_params": {"step": 0.02, "max_step": 0.2}},
                    {"field": "BOLL_wband", "params": {"length": 20, "std": 2.0}, "operator": "<", "compare_type": "value", "compare_value": bw},
                ]
                grid_name = ["tight", "wide", "ultra_tight", "mhd_sweep"][count % 4]
                configs = make_exit_configs_with_buy(grid_name, sell_name, buy)
                experiments.append((75063, configs))
                count += 1
                if count >= 60:
                    return experiments
    return experiments


def gen_rsi_kdj_experiments():
    """80 experiments: RSI+KDJ激進版B skeleton variations.
    Source: ES36540 (KDJ_K 40-80, ATR<0.091)
    Vary: KDJ_K range, ATR threshold, sell conditions.
    """
    experiments = []

    kdj_lows = [20, 30, 35, 40, 45, 50]
    kdj_highs = [70, 75, 80, 85, 90]
    atr_values = [0.07, 0.08, 0.09, 0.091, 0.10, 0.11]

    count = 0
    for kl in kdj_lows:
        for kh in kdj_highs:
            if kl >= kh - 10:
                continue
            for atr in atr_values:
                for sell_name in ["lt2dLow", "aR2vF2", "fall2d", "gt10dH"]:
                    buy = [
                        {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": ">", "compare_type": "value", "compare_value": kl},
                        {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": "<", "compare_type": "value", "compare_value": kh},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                    ]
                    grid_name = ["tight", "wide", "ultra_tight", "mhd_sweep"][count % 4]
                    configs = make_exit_configs_with_buy(grid_name, sell_name, buy)
                    experiments.append((36540, configs))
                    count += 1
                    if count >= 80:
                        return experiments
    return experiments


def gen_quanzhibiao_experiments():
    """80 experiments: 全指標 skeleton variations.
    Override buy_conditions to close>EMA + ATR filter + various conditions.
    Source: ES75014 (reuse).
    """
    experiments = []

    ema_lengths = [8, 10, 12, 15, 20]
    atr_values = [0.06, 0.08, 0.10, 0.12, 0.15]

    count = 0
    for ema in ema_lengths:
        for atr in atr_values:
            for sell_name in SELL_VARIANTS:
                # 全指標 pattern: close > EMA + ATR filter + additional indicator
                buy_variants = [
                    # close > EMA + ATR calm
                    [
                        {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "EMA", "compare_params": {"length": ema}},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "pct_change", "lookback_n": 7, "compare_value": 3},
                    ],
                    # close > EMA + RSI filter
                    [
                        {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "EMA", "compare_params": {"length": ema}},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                        {"field": "RSI", "params": {"period": 14}, "operator": ">", "compare_type": "value", "compare_value": 45},
                        {"field": "RSI", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 70},
                    ],
                ]
                for buy in buy_variants:
                    grid_name = ["tight", "wide", "ultra_tight", "mhd_sweep"][count % 4]
                    configs = make_exit_configs_with_buy(grid_name, sell_name, buy)
                    experiments.append((75014, configs))
                    count += 1
                    if count >= 80:
                        return experiments
    return experiments


def main():
    print(f"R1189 Batch Exploration — {datetime.now()}")
    print(f"Target: 500 experiments × 8 strategies = 4000 strategies")
    print()

    # Generate all experiments
    all_experiments = []

    print("Generating MACD+RSI experiments...")
    macd_rsi = gen_macd_rsi_experiments()
    print(f"  → {len(macd_rsi)} experiments")
    all_experiments.extend(macd_rsi)

    print("Generating 三指標 experiments...")
    san = gen_san_zhibiao_experiments()
    print(f"  → {len(san)} experiments")
    all_experiments.extend(san)

    print("Generating VPT+PSAR experiments...")
    vpt = gen_vpt_psar_experiments()
    print(f"  → {len(vpt)} experiments")
    all_experiments.extend(vpt)

    print("Generating RSI+KDJ experiments...")
    kdj = gen_rsi_kdj_experiments()
    print(f"  → {len(kdj)} experiments")
    all_experiments.extend(kdj)

    print("Generating 全指標 experiments...")
    qzb = gen_quanzhibiao_experiments()
    print(f"  → {len(qzb)} experiments")
    all_experiments.extend(qzb)

    total = len(all_experiments)
    print(f"\nTotal: {total} experiments, {total * 8} strategies")
    print()

    # Submit experiments
    experiment_ids = []
    failed = 0

    for i, (source_id, configs) in enumerate(all_experiments, 1):
        result = submit_batch(source_id, configs)
        if result:
            experiment_ids.append(result)
            if i % 50 == 0 or i == total:
                print(f"[{i}/{total}] Submitted {len(experiment_ids)} experiments ({failed} failed)")
        else:
            failed += 1
            if failed > 20:
                print(f"Too many failures ({failed}), stopping submission")
                break

        # Small delay every 10 experiments to avoid overwhelming the server
        if i % 10 == 0:
            time.sleep(0.5)

    print(f"\n=== Submission Complete ===")
    print(f"Submitted: {len(experiment_ids)} experiments")
    print(f"Failed: {failed}")
    print(f"Expected strategies: {len(experiment_ids) * 8}")
    print(f"Experiment IDs: {experiment_ids[:10]}...{experiment_ids[-3:] if len(experiment_ids) > 10 else ''}")

    # Save experiment IDs for auto_finish
    with open('/tmp/r1189_experiment_ids.json', 'w') as f:
        json.dump({
            'round': 1189,
            'start_time': START_TIME,
            'experiment_ids': experiment_ids,
            'total_experiments': len(experiment_ids),
            'expected_strategies': len(experiment_ids) * 8,
        }, f, indent=2)

    print(f"\nExperiment IDs saved to /tmp/r1189_experiment_ids.json")
    print(f"Run auto_finish script to monitor: python3 scripts/r1189_auto_finish.py")


if __name__ == "__main__":
    main()
