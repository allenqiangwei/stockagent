"""R1187 batch v2: Corrected source ES_ID = 20989 (MACD+RSI base with RSI+ATR+close indicators).

50 experiments filling skeleton gaps.
30 × _slipN (gap=71), 12 × noSlip (gap=39), 3 × RSI+KDJ, 5 × MACD+RSI optimization
"""

import subprocess
import json
import time
import copy
from datetime import datetime

ES_SOURCE = 20989  # MACD+RSI base (has MACD, RSI, MFI, ATR, close indicators)

def api_post(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'http://127.0.0.1:8050/api/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {"error": r.stdout[:200]}

def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {}

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

# ── Buy condition templates ──
# _slipN base: RSI(18) 50-75, ATR(14)<0.0875, DIP-2.9(1d), AbvMin(13d)
SLIP_BUY_BASE = [
    {"field": "RSI", "params": {"period": 18}, "operator": ">", "compare_type": "value", "compare_value": 50},
    {"field": "RSI", "params": {"period": 18}, "operator": "<", "compare_type": "value", "compare_value": 75},
    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.0875},
    {"field": "close", "params": {}, "compare_type": "pct_change", "operator": "<", "compare_value": -2.9, "lookback_n": 1},
    {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
]

# aR2vF2 sell conditions
SELL_AR2VF2 = [
    {"field": "ATR", "params": {"period": 14}, "operator": ">", "compare_type": "consecutive", "consecutive_type": "rising", "lookback_n": 2},
    {"field": "volume", "operator": ">", "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
]

# lt2dLow sell condition
SELL_LT2DLOW = [
    {"field": "close", "params": {}, "operator": "<", "compare_type": "lookback_min", "lookback_n": 2},
]

# gt10dH sell condition
SELL_GT10DH = [
    {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_max", "lookback_n": 10},
]

# fall2d sell condition
SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive", "operator": ">", "consecutive_type": "falling", "lookback_n": 2},
]


def modify_buy(base, **changes):
    """Create modified buy conditions."""
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


def make_configs(buy_conds, sell_conds, suffix_prefix):
    """Create 8 exit config entries with buy/sell overrides."""
    configs = []
    for ec in EXIT_SWEEP:
        entry = copy.deepcopy(ec)
        entry["name_suffix"] = f"{suffix_prefix}_{entry['name_suffix']}"
        entry["buy_conditions"] = buy_conds
        entry["sell_conditions"] = sell_conds
        configs.append(entry)
    return configs


def submit(source_id, configs, label):
    """Submit batch-clone-backtest. Returns experiment ID."""
    data = {
        "source_strategy_id": source_id,
        "exit_configs": configs,
    }
    result = api_post(f'lab/strategies/{source_id}/batch-clone-backtest', data)
    eid = result.get('experiment_id', '?')
    count = result.get('count', 0)
    err = result.get('error', result.get('detail', ''))
    if err and not eid:
        print(f"  ERROR: {label} — {err}")
        return None
    print(f"  E{eid}: {count} strategies — {label}")
    return eid


def wait_for_queue_clear():
    """Wait until the backtest queue is mostly clear."""
    print("Waiting for queue to clear...", flush=True)
    while True:
        pending = 0
        for eid in range(8899, 8949):
            exp = api_get(f'lab/experiments/{eid}')
            for s in exp.get('strategies', []):
                if s.get('status') in ('pending', 'backtesting'):
                    pending += 1
        if pending <= 10:
            print(f"Queue nearly clear: {pending} pending")
            return
        print(f"  {pending} still pending, waiting 2 min...", flush=True)
        time.sleep(120)


def main():
    started = datetime.now()
    print(f"=== R1187 v2 Batch Start: {started.isoformat()} ===")

    # Skip wait — v1 invalids will clear fast, v2 queues behind them
    print("Submitting immediately (v1 invalids will clear fast in the queue)")

    print(f"\nUsing source ES{ES_SOURCE} (MACD+RSI base with RSI+ATR+close indicators)")
    all_exp_ids = []

    # ════════════════════════════════════════════════
    # TIER 1: _slipN skeleton fill (30 experiments)
    # ════════════════════════════════════════════════
    print("\n── _slipN skeleton fill (30 experiments) ──")

    # Group A: AbvMin variations (10 experiments) — highest priority per memory
    for abvmin in [1, 2, 3, 5, 8, 10, 16, 18, 20, 25]:
        bc = modify_buy(SLIP_BUY_BASE, abvmin_n=abvmin)
        configs = make_configs(bc, SELL_AR2VF2, f"AM{abvmin}")
        eid = submit(ES_SOURCE, configs, f"slipN_AbvMin{abvmin}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # Group B: RSI period variations (4 experiments)
    for rsi_p in [14, 16, 20, 22]:
        bc = modify_buy(SLIP_BUY_BASE, rsi_period=rsi_p)
        configs = make_configs(bc, SELL_AR2VF2, f"RSI{rsi_p}")
        eid = submit(ES_SOURCE, configs, f"slipN_RSI{rsi_p}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # Group C: ATR threshold variations (6 experiments)
    for atr in [0.08, 0.09, 0.10, 0.11, 0.12, 0.15]:
        bc = modify_buy(SLIP_BUY_BASE, atr_thresh=atr)
        configs = make_configs(bc, SELL_AR2VF2, f"ATR{atr}")
        eid = submit(ES_SOURCE, configs, f"slipN_ATR{atr}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # Group D: DIP variations (5 experiments)
    for dip in [-1.5, -2.0, -2.5, -3.5, -4.0]:
        bc = modify_buy(SLIP_BUY_BASE, dip_val=dip)
        configs = make_configs(bc, SELL_AR2VF2, f"DIP{abs(dip)}")
        eid = submit(ES_SOURCE, configs, f"slipN_DIP{dip}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # Group E: RSI range variations (3 experiments)
    for rsi_low, rsi_high, label in [(50, 60, "R5060"), (45, 70, "R4570"), (55, 80, "R5580")]:
        bc = modify_buy(SLIP_BUY_BASE, rsi_low=rsi_low, rsi_high=rsi_high)
        configs = make_configs(bc, SELL_AR2VF2, label)
        eid = submit(ES_SOURCE, configs, f"slipN_{label}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # Group F: Combined variations (2 experiments)
    bc1 = modify_buy(SLIP_BUY_BASE, rsi_period=20, abvmin_n=3)
    eid = submit(ES_SOURCE, make_configs(bc1, SELL_AR2VF2, "RSI20_AM3"), "slipN_RSI20_AbvMin3")
    if eid: all_exp_ids.append(eid)
    time.sleep(1)

    bc2 = modify_buy(SLIP_BUY_BASE, rsi_period=14, abvmin_n=5)
    eid = submit(ES_SOURCE, make_configs(bc2, SELL_AR2VF2, "RSI14_AM5"), "slipN_RSI14_AbvMin5")
    if eid: all_exp_ids.append(eid)
    time.sleep(1)

    # ════════════════════════════════════════════════
    # TIER 2: noSlip skeleton fill (12 experiments)
    # ════════════════════════════════════════════════
    print("\n── noSlip skeleton fill (12 experiments) ──")

    NOSLIP_BUY = copy.deepcopy(SLIP_BUY_BASE)
    # Change RSI period from 18 to 16 for noSlip skeleton
    for c in NOSLIP_BUY:
        if c["field"] == "RSI":
            c["params"]["period"] = 16

    for abvmin in [1, 2, 3, 5, 8, 10]:
        bc = modify_buy(NOSLIP_BUY, abvmin_n=abvmin)
        configs = make_configs(bc, SELL_AR2VF2, f"ns_AM{abvmin}")
        eid = submit(ES_SOURCE, configs, f"noSlip_AbvMin{abvmin}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    for rsi_p in [14, 18, 20, 22]:
        bc = modify_buy(NOSLIP_BUY, rsi_period=rsi_p)
        configs = make_configs(bc, SELL_AR2VF2, f"ns_RSI{rsi_p}")
        eid = submit(ES_SOURCE, configs, f"noSlip_RSI{rsi_p}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    for atr in [0.10, 0.12]:
        bc = modify_buy(NOSLIP_BUY, atr_thresh=atr)
        configs = make_configs(bc, SELL_AR2VF2, f"ns_ATR{atr}")
        eid = submit(ES_SOURCE, configs, f"noSlip_ATR{atr}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # ════════════════════════════════════════════════
    # TIER 3: Sell condition diversity (3 experiments)
    # These create new fingerprints by changing sell conditions
    # ════════════════════════════════════════════════
    print("\n── Sell condition diversity (3 experiments) ──")

    # lt2dLow sell with base buy
    eid = submit(ES_SOURCE, make_configs(SLIP_BUY_BASE, SELL_LT2DLOW, "lt2dLow"), "slipN_lt2dLow_sell")
    if eid: all_exp_ids.append(eid)
    time.sleep(1)

    # gt10dH sell with base buy
    eid = submit(ES_SOURCE, make_configs(SLIP_BUY_BASE, SELL_GT10DH, "gt10dH"), "slipN_gt10dH_sell")
    if eid: all_exp_ids.append(eid)
    time.sleep(1)

    # fall2d sell with base buy
    eid = submit(ES_SOURCE, make_configs(SLIP_BUY_BASE, SELL_FALL2D, "fall2d"), "slipN_fall2d_sell")
    if eid: all_exp_ids.append(eid)
    time.sleep(1)

    # ════════════════════════════════════════════════
    # TIER 4: MACD+RSI optimization (5 experiments)
    # ════════════════════════════════════════════════
    print("\n── MACD+RSI optimization (5 experiments) ──")

    MACD_BUY = [
        {"field": "RSI", "params": {"period": 14}, "operator": ">", "compare_type": "value", "compare_value": 50},
        {"field": "RSI", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.12},
        {"field": "close", "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
        {"field": "close", "operator": "<", "compare_type": "lookback_max", "lookback_n": 10},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "pct_change", "lookback_n": 7, "compare_value": 3},
        {"field": "volume", "operator": ">", "compare_type": "field", "compare_field": "volume_ma", "compare_params": {"period": 3}},
    ]
    MACD_SELL = [
        {"field": "close", "operator": "<", "compare_type": "lookback_min", "lookback_n": 2},
    ]

    for rsi_low, rsi_high, label in [(47, 67, "R4767"), (50, 65, "R5065"), (45, 60, "R4560"), (50, 75, "R5075"), (55, 70, "R5570")]:
        bc = copy.deepcopy(MACD_BUY)
        bc[0]["compare_value"] = rsi_low
        bc[1]["compare_value"] = rsi_high
        configs = make_configs(bc, MACD_SELL, f"macd_{label}")
        eid = submit(ES_SOURCE, configs, f"MACD+RSI_{label}")
        if eid: all_exp_ids.append(eid)
        time.sleep(1)

    # ══════════════ Summary ══════════════
    print(f"\n=== {len(all_exp_ids)} experiments submitted ===")
    print(f"Experiment IDs: {all_exp_ids}")

    with open('/tmp/r1187_v2_experiments.json', 'w') as f:
        json.dump({
            'started_at': started.isoformat(),
            'experiment_ids': all_exp_ids,
        }, f, indent=2)

    print(f"Saved to /tmp/r1187_v2_experiments.json")
    est_strategies = len(all_exp_ids) * 8
    print(f"Estimated: {est_strategies} strategies, ~{est_strategies * 4 // 60}h backtest time")


if __name__ == "__main__":
    main()
