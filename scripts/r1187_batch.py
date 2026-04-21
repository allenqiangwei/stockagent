"""R1187 batch exploration: 50 experiments filling skeleton gaps.

30 × _slipN (gap=71), 12 × noSlip (gap=39), 3 × RSI+KDJ (gap=19), 5 × MACD+RSI optimization
"""

import subprocess
import json
import time
import sys
import copy
from datetime import datetime

def api_post(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'http://127.0.0.1:8050/api/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)

def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)

# ── Exit config sweep (8 variants per experiment) ──
EXIT_SWEEP = [
    {"name_suffix": "TP1.0_MHD2", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 2}},
    {"name_suffix": "TP1.5_MHD3", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 1.5, "max_hold_days": 3}},
    {"name_suffix": "TP2.0_MHD5", "exit_config": {"stop_loss_pct": -15, "take_profit_pct": 2.0, "max_hold_days": 5}},
    {"name_suffix": "TP2.5_MHD5", "exit_config": {"stop_loss_pct": -15, "take_profit_pct": 2.5, "max_hold_days": 5}},
    {"name_suffix": "TP2.8_MHD7", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 2.8, "max_hold_days": 7}},
    {"name_suffix": "TP3.0_MHD7", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 3.0, "max_hold_days": 7}},
    {"name_suffix": "TP3.5_MHD10", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 3.5, "max_hold_days": 10}},
    {"name_suffix": "TP4.0_MHD10", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 4.0, "max_hold_days": 10}},
]

# ── Source strategy base conditions ──

# S18787: _slipN champion (RSI18, ATR0.0875, DIP-2.9, AbvMin13, aR2vF2 sell)
SLIP_BUY_BASE = [
    {"field": "RSI", "params": {"period": 18}, "operator": ">", "compare_type": "value", "compare_value": 50},
    {"field": "RSI", "params": {"period": 18}, "operator": "<", "compare_type": "value", "compare_value": 75},
    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.0875},
    {"field": "close", "params": {}, "compare_type": "pct_change", "operator": "<", "compare_value": -2.9, "lookback_n": 1},
    {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
]
SLIP_SELL_BASE = [
    {"field": "ATR", "params": {"period": 14}, "operator": ">", "compare_type": "consecutive", "consecutive_type": "rising", "lookback_n": 2},
    {"field": "volume", "operator": ">", "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
]
SLIP_SOURCE = 18787

# S18799: noSlip champion (RSI16, same structure without slippage)
NOSLIP_BUY_BASE = [
    {"field": "RSI", "params": {"period": 16}, "operator": ">", "compare_type": "value", "compare_value": 50},
    {"field": "RSI", "params": {"period": 16}, "operator": "<", "compare_type": "value", "compare_value": 75},
    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.0875},
    {"field": "close", "params": {}, "compare_type": "pct_change", "operator": "<", "compare_value": -2.9, "lookback_n": 1},
    {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
]
NOSLIP_SOURCE = 18799

# ── Helper: modify a specific condition in the buy list ──
def modify_buy(base, **changes):
    """Create modified buy conditions. Supported changes:
    rsi_period, rsi_low, rsi_high, atr_thresh, dip_val, abvmin_n
    """
    bc = copy.deepcopy(base)
    for c in bc:
        if c["field"] == "RSI" and c["operator"] == ">":
            if "rsi_low" in changes:
                c["compare_value"] = changes["rsi_low"]
            if "rsi_period" in changes:
                c["params"]["period"] = changes["rsi_period"]
        if c["field"] == "RSI" and c["operator"] == "<":
            if "rsi_high" in changes:
                c["compare_value"] = changes["rsi_high"]
            if "rsi_period" in changes:
                c["params"]["period"] = changes["rsi_period"]
        if c["field"] == "ATR" and c.get("compare_type") == "value":
            if "atr_thresh" in changes:
                c["compare_value"] = changes["atr_thresh"]
        if c["field"] == "close" and c.get("compare_type") == "pct_change":
            if "dip_val" in changes:
                c["compare_value"] = changes["dip_val"]
        if c["field"] == "close" and c.get("compare_type") == "lookback_min":
            if "abvmin_n" in changes:
                c["lookback_n"] = changes["abvmin_n"]
    return bc

def make_exit_configs(buy_conds=None, sell_conds=None, suffix_prefix=""):
    """Create 8 exit config entries with optional buy/sell overrides."""
    configs = []
    for ec in EXIT_SWEEP:
        entry = copy.deepcopy(ec)
        if suffix_prefix:
            entry["name_suffix"] = f"{suffix_prefix}_{entry['name_suffix']}"
        if buy_conds is not None:
            entry["buy_conditions"] = buy_conds
        if sell_conds is not None:
            entry["sell_conditions"] = sell_conds
        configs.append(entry)
    return configs


def submit_experiment(source_id, exit_configs, label):
    """Submit batch-clone-backtest and return experiment info."""
    data = {
        "source_strategy_id": source_id,
        "exit_configs": exit_configs,
    }
    result = api_post(f'lab/strategies/{source_id}/batch-clone-backtest', data)
    eid = result.get('experiment_id', '?')
    count = result.get('count', 0)
    print(f"  E{eid}: {count} strategies — {label}")
    return {"experiment_id": eid, "count": count, "label": label}


def main():
    started = datetime.now()
    print(f"=== R1187 Batch Start: {started.isoformat()} ===")
    print(f"50 experiments, ~400 strategies")
    print()

    all_experiments = []

    # ════════════════════════════════════════════════
    # TIER 1: _slipN skeleton fill (30 experiments)
    # ════════════════════════════════════════════════
    print("── _slipN skeleton fill (30 experiments) ──")

    # Group A: AbvMin variations (10 experiments) — highest priority per memory
    for abvmin in [1, 2, 3, 5, 8, 10, 16, 18, 20, 25]:
        bc = modify_buy(SLIP_BUY_BASE, abvmin_n=abvmin)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"AM{abvmin}")
        exp = submit_experiment(SLIP_SOURCE, configs, f"slipN_AbvMin{abvmin}")
        all_experiments.append(exp)
        time.sleep(1)

    # Group B: RSI period variations (4 experiments)
    for rsi_p in [14, 16, 20, 22]:
        bc = modify_buy(SLIP_BUY_BASE, rsi_period=rsi_p)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"RSI{rsi_p}")
        exp = submit_experiment(SLIP_SOURCE, configs, f"slipN_RSI{rsi_p}")
        all_experiments.append(exp)
        time.sleep(1)

    # Group C: ATR threshold variations (6 experiments)
    for atr in [0.08, 0.09, 0.10, 0.11, 0.12, 0.15]:
        bc = modify_buy(SLIP_BUY_BASE, atr_thresh=atr)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"ATR{atr}")
        exp = submit_experiment(SLIP_SOURCE, configs, f"slipN_ATR{atr}")
        all_experiments.append(exp)
        time.sleep(1)

    # Group D: DIP variations (5 experiments)
    for dip in [-1.5, -2.0, -2.5, -3.5, -4.0]:
        bc = modify_buy(SLIP_BUY_BASE, dip_val=dip)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"DIP{abs(dip)}")
        exp = submit_experiment(SLIP_SOURCE, configs, f"slipN_DIP{dip}")
        all_experiments.append(exp)
        time.sleep(1)

    # Group E: RSI range variations (3 experiments)
    for rsi_low, rsi_high, label in [(50, 60, "R5060"), (45, 70, "R4570"), (55, 80, "R5580")]:
        bc = modify_buy(SLIP_BUY_BASE, rsi_low=rsi_low, rsi_high=rsi_high)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=label)
        exp = submit_experiment(SLIP_SOURCE, configs, f"slipN_{label}")
        all_experiments.append(exp)
        time.sleep(1)

    # Group F: Combined variations (2 experiments)
    bc1 = modify_buy(SLIP_BUY_BASE, rsi_period=20, abvmin_n=3)
    configs1 = make_exit_configs(buy_conds=bc1, suffix_prefix="RSI20_AM3")
    exp1 = submit_experiment(SLIP_SOURCE, configs1, "slipN_RSI20_AbvMin3")
    all_experiments.append(exp1)
    time.sleep(1)

    bc2 = modify_buy(SLIP_BUY_BASE, rsi_period=14, abvmin_n=5)
    configs2 = make_exit_configs(buy_conds=bc2, suffix_prefix="RSI14_AM5")
    exp2 = submit_experiment(SLIP_SOURCE, configs2, "slipN_RSI14_AbvMin5")
    all_experiments.append(exp2)
    time.sleep(1)

    # ════════════════════════════════════════════════
    # TIER 2: noSlip skeleton fill (12 experiments)
    # ════════════════════════════════════════════════
    print()
    print("── noSlip skeleton fill (12 experiments) ──")

    # AbvMin variations (6 experiments)
    for abvmin in [1, 2, 3, 5, 8, 10]:
        bc = modify_buy(NOSLIP_BUY_BASE, abvmin_n=abvmin)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"ns_AM{abvmin}")
        exp = submit_experiment(NOSLIP_SOURCE, configs, f"noSlip_AbvMin{abvmin}")
        all_experiments.append(exp)
        time.sleep(1)

    # RSI period variations (4 experiments)
    for rsi_p in [14, 18, 20, 22]:
        bc = modify_buy(NOSLIP_BUY_BASE, rsi_period=rsi_p)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"ns_RSI{rsi_p}")
        exp = submit_experiment(NOSLIP_SOURCE, configs, f"noSlip_RSI{rsi_p}")
        all_experiments.append(exp)
        time.sleep(1)

    # ATR variations (2 experiments)
    for atr in [0.10, 0.12]:
        bc = modify_buy(NOSLIP_BUY_BASE, atr_thresh=atr)
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"ns_ATR{atr}")
        exp = submit_experiment(NOSLIP_SOURCE, configs, f"noSlip_ATR{atr}")
        all_experiments.append(exp)
        time.sleep(1)

    # ════════════════════════════════════════════════
    # TIER 3: RSI+KDJ fill (3 experiments)
    # ════════════════════════════════════════════════
    print()
    print("── RSI+KDJ skeleton fill (3 experiments) ──")

    KDJ_SOURCE = 26662
    # Experiment 1: wider KDJ range (30-90) with exit sweep
    kdj_bc1 = [
        {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": ">", "compare_type": "value", "compare_value": 30},
        {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": "<", "compare_type": "value", "compare_value": 90},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.091},
    ]
    configs_k1 = make_exit_configs(buy_conds=kdj_bc1, suffix_prefix="KDJ3090")
    exp_k1 = submit_experiment(KDJ_SOURCE, configs_k1, "KDJ_K30-90")
    all_experiments.append(exp_k1)
    time.sleep(1)

    # Experiment 2: tighter KDJ (20-60) + DIP
    kdj_bc2 = [
        {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": ">", "compare_type": "value", "compare_value": 20},
        {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": "<", "compare_type": "value", "compare_value": 60},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.10},
        {"field": "close", "params": {}, "compare_type": "pct_change", "operator": "<", "compare_value": -2.0, "lookback_n": 1},
    ]
    configs_k2 = make_exit_configs(buy_conds=kdj_bc2, suffix_prefix="KDJ2060_DIP")
    exp_k2 = submit_experiment(KDJ_SOURCE, configs_k2, "KDJ_K20-60_DIP")
    all_experiments.append(exp_k2)
    time.sleep(1)

    # Experiment 3: KDJ short period (6,3,3) + AbvMin
    kdj_bc3 = [
        {"field": "KDJ_K", "params": {"fastk": 6, "slowk": 3, "slowd": 3}, "operator": ">", "compare_type": "value", "compare_value": 30},
        {"field": "KDJ_K", "params": {"fastk": 6, "slowk": 3, "slowd": 3}, "operator": "<", "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.091},
        {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_min", "lookback_n": 8},
    ]
    configs_k3 = make_exit_configs(buy_conds=kdj_bc3, suffix_prefix="KDJ633_AM8")
    exp_k3 = submit_experiment(KDJ_SOURCE, configs_k3, "KDJ633_AbvMin8")
    all_experiments.append(exp_k3)
    time.sleep(1)

    # ════════════════════════════════════════════════
    # TIER 4: MACD+RSI optimization (5 experiments)
    # ════════════════════════════════════════════════
    print()
    print("── MACD+RSI optimization (5 experiments) ──")

    MACD_SOURCE = 31068
    MACD_BUY_BASE = [
        {"field": "RSI", "params": {"period": 14}, "operator": ">", "compare_type": "value", "compare_value": 50},
        {"field": "RSI", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.12},
        {"field": "close", "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
        {"field": "close", "operator": "<", "compare_type": "lookback_max", "lookback_n": 10},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "pct_change", "lookback_n": 7, "compare_value": 3},
        {"field": "volume", "operator": ">", "compare_type": "field", "compare_field": "volume_ma", "compare_params": {"period": 3}},
    ]

    # Vary RSI range (narrower = higher quality)
    for rsi_low, rsi_high, label in [(47, 67, "R4767"), (50, 65, "R5065"), (45, 60, "R4560"), (50, 75, "R5075"), (55, 70, "R5570")]:
        bc = copy.deepcopy(MACD_BUY_BASE)
        bc[0]["compare_value"] = rsi_low
        bc[1]["compare_value"] = rsi_high
        configs = make_exit_configs(buy_conds=bc, suffix_prefix=f"macd_{label}")
        exp = submit_experiment(MACD_SOURCE, configs, f"MACD+RSI_{label}")
        all_experiments.append(exp)
        time.sleep(1)

    # ══════════════ Summary ══════════════
    print()
    print(f"=== All {len(all_experiments)} experiments submitted ===")
    total_strategies = sum(e['count'] for e in all_experiments)
    exp_ids = [e['experiment_id'] for e in all_experiments]
    print(f"Total strategies: {total_strategies}")
    print(f"Experiment IDs: {exp_ids[:10]}...{exp_ids[-5:]}")

    # Save experiment list for auto_finish
    with open('/tmp/r1187_experiments.json', 'w') as f:
        json.dump({
            'started_at': started.isoformat(),
            'experiments': all_experiments,
            'experiment_ids': exp_ids,
        }, f, indent=2)

    print(f"\nExperiment list saved to /tmp/r1187_experiments.json")
    print(f"Estimated backtest time: ~{total_strategies * 4 // 60}h {(total_strategies * 4) % 60}m")
    print(f"Use r1187_auto_finish.py to poll and analyze results.")


if __name__ == "__main__":
    main()
