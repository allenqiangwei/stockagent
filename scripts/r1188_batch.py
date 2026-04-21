"""R1188 batch: 500 experiments (4000 strategies) filling skeleton gaps.

Source: ES20989 (MACD+RSI base with RSI, ATR, MFI, close indicators)

Allocation:
- 300 × _slipN fill (gap=71): RSI period × ATR threshold × AbvMin × sell condition combos
- 120 × noSlip fill (gap=39): RSI16 base × AbvMin × sell × ATR variations
- 30 × RSI+KDJ fill (gap=19): RSI+KDJ激進版B parameter sweeps
- 50 × MACD+RSI optimization: Varied exit configs targeting weakest members

Run: nohup python3 scripts/r1188_batch.py > /tmp/r1188.log 2>&1 &
"""

import subprocess
import json
import time
import copy
from datetime import datetime

ES_SOURCE = 20989

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

# ── Exit config templates ──
# Standard 8-variant sweep
EXIT_8 = [
    {"name_suffix": "TP1.0_MHD2", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 2}},
    {"name_suffix": "TP1.5_MHD3", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 1.5, "max_hold_days": 3}},
    {"name_suffix": "TP2.0_MHD5", "exit_config": {"stop_loss_pct": -15, "take_profit_pct": 2.0, "max_hold_days": 5}},
    {"name_suffix": "TP2.5_MHD5", "exit_config": {"stop_loss_pct": -15, "take_profit_pct": 2.5, "max_hold_days": 5}},
    {"name_suffix": "TP2.8_MHD7", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 2.8, "max_hold_days": 7}},
    {"name_suffix": "TP3.0_MHD7", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 3.0, "max_hold_days": 7}},
    {"name_suffix": "TP3.5_MHD10", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 3.5, "max_hold_days": 10}},
    {"name_suffix": "TP4.0_MHD10", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 4.0, "max_hold_days": 10}},
]

# Aggressive low TP (proven best for return)
EXIT_LOW_TP = [
    {"name_suffix": "TP0.5_MHD2", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 0.5, "max_hold_days": 2}},
    {"name_suffix": "TP0.8_MHD2", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 0.8, "max_hold_days": 2}},
    {"name_suffix": "TP0.8_MHD3", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 0.8, "max_hold_days": 3}},
    {"name_suffix": "TP1.0_MHD3", "exit_config": {"stop_loss_pct": -20, "take_profit_pct": 1.0, "max_hold_days": 3}},
    {"name_suffix": "TP1.0_MHD5", "exit_config": {"stop_loss_pct": -15, "take_profit_pct": 1.0, "max_hold_days": 5}},
    {"name_suffix": "TP1.5_MHD5", "exit_config": {"stop_loss_pct": -15, "take_profit_pct": 1.5, "max_hold_days": 5}},
    {"name_suffix": "TP2.0_MHD7", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 2.0, "max_hold_days": 7}},
    {"name_suffix": "TP2.8_MHD10", "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 2.8, "max_hold_days": 10}},
]

# ── Sell conditions ──
SELL_AR2VF2 = [
    {"field": "ATR", "params": {"period": 14}, "operator": ">", "compare_type": "consecutive", "consecutive_type": "rising", "lookback_n": 2},
    {"field": "volume", "operator": ">", "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
]
SELL_LT2DLOW = [
    {"field": "close", "params": {}, "operator": "<", "compare_type": "lookback_min", "lookback_n": 2},
]
SELL_GT10DH = [
    {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_max", "lookback_n": 10},
]
SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive", "operator": ">", "consecutive_type": "falling", "lookback_n": 2},
]
SELL_RISE4D = [
    {"field": "close", "params": {}, "compare_type": "consecutive", "operator": ">", "consecutive_type": "rising", "lookback_n": 4},
]

SELL_CONDITIONS = {
    "aR2vF2": SELL_AR2VF2,
    "lt2dLow": SELL_LT2DLOW,
    "gt10dH": SELL_GT10DH,
    "fall2d": SELL_FALL2D,
    "rise4d": SELL_RISE4D,
}


def make_slip_buy(rsi_period=18, rsi_low=50, rsi_high=75, atr_thresh=0.0875, dip_val=-2.9, abvmin_n=13):
    """Create _slipN buy conditions with parameterized values."""
    return [
        {"field": "RSI", "params": {"period": rsi_period}, "operator": ">", "compare_type": "value", "compare_value": rsi_low},
        {"field": "RSI", "params": {"period": rsi_period}, "operator": "<", "compare_type": "value", "compare_value": rsi_high},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr_thresh},
        {"field": "close", "params": {}, "compare_type": "pct_change", "operator": "<", "compare_value": dip_val, "lookback_n": 1},
        {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_min", "lookback_n": abvmin_n},
    ]


def make_configs(buy_conds, sell_conds, suffix_prefix, exit_template=None):
    """Create exit config entries with buy/sell overrides."""
    if exit_template is None:
        exit_template = EXIT_8
    configs = []
    for ec in exit_template:
        entry = copy.deepcopy(ec)
        entry["name_suffix"] = f"{suffix_prefix}_{entry['name_suffix']}"
        entry["buy_conditions"] = buy_conds
        entry["sell_conditions"] = sell_conds
        configs.append(entry)
    return configs


def submit(source_id, configs, label):
    """Submit batch-clone-backtest."""
    data = {"source_strategy_id": source_id, "exit_configs": configs}
    result = api_post(f'lab/strategies/{source_id}/batch-clone-backtest', data)
    eid = result.get('experiment_id', '?')
    count = result.get('count', 0)
    err = result.get('error', result.get('detail', ''))
    if err and not eid:
        print(f"  ERROR: {label} — {err}")
        return None
    print(f"  E{eid}: {count} strats — {label}")
    return eid


def main():
    started = datetime.now()
    print(f"=== R1188 Batch Start: {started.isoformat()} ===")
    print(f"Source: ES{ES_SOURCE}")

    all_ids = []

    # ════════════════════════════════════════════════════════════════
    # TIER 1: _slipN skeleton fill (300 experiments = 2400 strategies)
    # ════════════════════════════════════════════════════════════════
    print("\n══ _slipN skeleton fill (300 experiments) ══")

    # ── Group A: RSI period × ATR threshold × AbvMin cross (120 experiments) ──
    # Best combos from R1187: RSI16, ATR 0.09-0.10, AbvMin 8-20
    print("\n── A: RSI × ATR × AbvMin cross (120 experiments) ──")
    count = 0
    for rsi_p in [14, 16, 18, 20]:
        for atr in [0.0875, 0.09, 0.10]:
            for abvmin in [3, 5, 8, 10, 13, 16, 18, 20, 22, 25]:
                bc = make_slip_buy(rsi_period=rsi_p, atr_thresh=atr, abvmin_n=abvmin)
                suffix = f"R{rsi_p}_A{atr}_AM{abvmin}"
                configs = make_configs(bc, SELL_AR2VF2, suffix)
                eid = submit(ES_SOURCE, configs, f"slipN {suffix}")
                if eid: all_ids.append(eid)
                count += 1
                time.sleep(0.5)
    print(f"  Group A: {count} submitted")

    # ── Group B: Sell condition diversity × best RSI/ATR combos (80 experiments) ──
    print("\n── B: Sell condition diversity (80 experiments) ──")
    count = 0
    for sell_name, sell_conds in SELL_CONDITIONS.items():
        if sell_name == "aR2vF2":
            continue  # Already covered in Group A
        for rsi_p in [14, 16, 18, 20]:
            for atr in [0.0875, 0.10]:
                for abvmin in [8, 13, 18, 25]:
                    bc = make_slip_buy(rsi_period=rsi_p, atr_thresh=atr, abvmin_n=abvmin)
                    suffix = f"R{rsi_p}_A{atr}_AM{abvmin}_{sell_name}"
                    configs = make_configs(bc, sell_conds, suffix)
                    eid = submit(ES_SOURCE, configs, f"slipN {suffix}")
                    if eid: all_ids.append(eid)
                    count += 1
                    time.sleep(0.5)
    print(f"  Group B: {count} submitted")

    # ── Group C: RSI range variations with best params (50 experiments) ──
    print("\n── C: RSI range variations (50 experiments) ──")
    count = 0
    rsi_ranges = [
        (50, 60, "R5060"), (50, 70, "R5070"), (50, 75, "R5075"),
        (47, 67, "R4767"), (55, 80, "R5580"),
    ]
    for rsi_low, rsi_high, rlabel in rsi_ranges:
        for atr in [0.0875, 0.10]:
            for abvmin in [8, 13, 18, 25]:
                for sell_name in ["aR2vF2", "lt2dLow"]:
                    bc = make_slip_buy(rsi_period=18, rsi_low=rsi_low, rsi_high=rsi_high,
                                       atr_thresh=atr, abvmin_n=abvmin)
                    sell_conds = SELL_CONDITIONS[sell_name]
                    suffix = f"{rlabel}_A{atr}_AM{abvmin}_{sell_name}"
                    configs = make_configs(bc, sell_conds, suffix)
                    eid = submit(ES_SOURCE, configs, f"slipN {suffix}")
                    if eid: all_ids.append(eid)
                    count += 1
                    time.sleep(0.5)
                    if count >= 50:
                        break
                if count >= 50:
                    break
            if count >= 50:
                break
        if count >= 50:
            break
    print(f"  Group C: {count} submitted")

    # ── Group D: Low TP aggressive exit configs (50 experiments) ──
    print("\n── D: Low TP aggressive configs (50 experiments) ──")
    count = 0
    for rsi_p in [14, 16, 18]:
        for atr in [0.0875, 0.10]:
            for abvmin in [8, 13, 18]:
                bc = make_slip_buy(rsi_period=rsi_p, atr_thresh=atr, abvmin_n=abvmin)
                for sell_name in ["lt2dLow", "aR2vF2"]:
                    sell_conds = SELL_CONDITIONS[sell_name]
                    suffix = f"lowTP_R{rsi_p}_A{atr}_AM{abvmin}_{sell_name}"
                    configs = make_configs(bc, sell_conds, suffix, EXIT_LOW_TP)
                    eid = submit(ES_SOURCE, configs, f"slipN {suffix}")
                    if eid: all_ids.append(eid)
                    count += 1
                    time.sleep(0.5)
                    if count >= 50:
                        break
                if count >= 50:
                    break
            if count >= 50:
                break
        if count >= 50:
            break
    print(f"  Group D: {count} submitted")

    # ════════════════════════════════════════════════════════════════
    # TIER 2: noSlip skeleton fill (120 experiments = 960 strategies)
    # ════════════════════════════════════════════════════════════════
    print("\n══ noSlip skeleton fill (120 experiments) ══")

    # noSlip = RSI16 base (no DIP condition)
    def make_noslip_buy(rsi_period=16, rsi_low=50, rsi_high=75, atr_thresh=0.0875, abvmin_n=13):
        return [
            {"field": "RSI", "params": {"period": rsi_period}, "operator": ">", "compare_type": "value", "compare_value": rsi_low},
            {"field": "RSI", "params": {"period": rsi_period}, "operator": "<", "compare_type": "value", "compare_value": rsi_high},
            {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr_thresh},
            {"field": "close", "params": {}, "operator": ">", "compare_type": "lookback_min", "lookback_n": abvmin_n},
        ]

    # ── Group E: noSlip RSI × ATR × AbvMin cross (60 experiments) ──
    print("\n── E: noSlip RSI × ATR × AbvMin cross (60 experiments) ──")
    count = 0
    for rsi_p in [14, 16, 18]:
        for atr in [0.0875, 0.09, 0.10]:
            for abvmin in [3, 5, 8, 10, 13, 18, 25]:
                bc = make_noslip_buy(rsi_period=rsi_p, atr_thresh=atr, abvmin_n=abvmin)
                suffix = f"ns_R{rsi_p}_A{atr}_AM{abvmin}"
                configs = make_configs(bc, SELL_AR2VF2, suffix)
                eid = submit(ES_SOURCE, configs, f"noSlip {suffix}")
                if eid: all_ids.append(eid)
                count += 1
                time.sleep(0.5)
                if count >= 60:
                    break
            if count >= 60:
                break
        if count >= 60:
            break
    print(f"  Group E: {count} submitted")

    # ── Group F: noSlip sell condition diversity (40 experiments) ──
    print("\n── F: noSlip sell diversity (40 experiments) ──")
    count = 0
    for sell_name in ["lt2dLow", "gt10dH", "fall2d", "rise4d"]:
        sell_conds = SELL_CONDITIONS[sell_name]
        for rsi_p in [14, 16]:
            for atr in [0.0875, 0.10]:
                for abvmin in [8, 13, 18, 25]:
                    bc = make_noslip_buy(rsi_period=rsi_p, atr_thresh=atr, abvmin_n=abvmin)
                    suffix = f"ns_R{rsi_p}_A{atr}_AM{abvmin}_{sell_name}"
                    configs = make_configs(bc, sell_conds, suffix)
                    eid = submit(ES_SOURCE, configs, f"noSlip {suffix}")
                    if eid: all_ids.append(eid)
                    count += 1
                    time.sleep(0.5)
                    if count >= 40:
                        break
                if count >= 40:
                    break
            if count >= 40:
                break
        if count >= 40:
            break
    print(f"  Group F: {count} submitted")

    # ── Group G: noSlip low TP (20 experiments) ──
    print("\n── G: noSlip low TP (20 experiments) ──")
    count = 0
    for rsi_p in [14, 16]:
        for atr in [0.0875, 0.10]:
            for abvmin in [8, 13, 18]:
                bc = make_noslip_buy(rsi_period=rsi_p, atr_thresh=atr, abvmin_n=abvmin)
                for sell_name in ["lt2dLow", "aR2vF2"]:
                    sell_conds = SELL_CONDITIONS[sell_name]
                    suffix = f"ns_lowTP_R{rsi_p}_A{atr}_AM{abvmin}_{sell_name}"
                    configs = make_configs(bc, sell_conds, suffix, EXIT_LOW_TP)
                    eid = submit(ES_SOURCE, configs, f"noSlip {suffix}")
                    if eid: all_ids.append(eid)
                    count += 1
                    time.sleep(0.5)
                    if count >= 20:
                        break
                if count >= 20:
                    break
            if count >= 20:
                break
        if count >= 20:
            break
    print(f"  Group G: {count} submitted")

    # ════════════════════════════════════════════════════════════════
    # TIER 3: RSI+KDJ skeleton fill (30 experiments = 240 strategies)
    # ════════════════════════════════════════════════════════════════
    print("\n══ RSI+KDJ skeleton fill (30 experiments) ══")

    # RSI+KDJ uses similar conditions but with added KDJ-like trigger
    # Since source ES20989 only has RSI/ATR/MFI/close, we approximate
    # by varying buy conditions more aggressively
    count = 0
    for rsi_p in [14, 16, 18]:
        for rsi_low, rsi_high in [(30, 50), (25, 45), (35, 55)]:
            for atr in [0.10, 0.12]:
                bc = [
                    {"field": "RSI", "params": {"period": rsi_p}, "operator": ">", "compare_type": "value", "compare_value": rsi_low},
                    {"field": "RSI", "params": {"period": rsi_p}, "operator": "<", "compare_type": "value", "compare_value": rsi_high},
                    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                    {"field": "close", "params": {}, "compare_type": "pct_change", "operator": "<", "compare_value": -2.0, "lookback_n": 1},
                ]
                suffix = f"kjr_R{rsi_p}_{rsi_low}_{rsi_high}_A{atr}"
                configs = make_configs(bc, SELL_AR2VF2, suffix)
                eid = submit(ES_SOURCE, configs, f"RSI+KDJ {suffix}")
                if eid: all_ids.append(eid)
                count += 1
                time.sleep(0.5)
                if count >= 30:
                    break
            if count >= 30:
                break
        if count >= 30:
            break
    print(f"  RSI+KDJ: {count} submitted")

    # ════════════════════════════════════════════════════════════════
    # TIER 4: MACD+RSI optimization (50 experiments = 400 strategies)
    # ════════════════════════════════════════════════════════════════
    print("\n══ MACD+RSI optimization (50 experiments) ══")

    MACD_BUY = [
        {"field": "RSI", "params": {"period": 14}, "operator": ">", "compare_type": "value", "compare_value": 50},
        {"field": "RSI", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 70},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": 0.12},
        {"field": "close", "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
        {"field": "close", "operator": "<", "compare_type": "lookback_max", "lookback_n": 10},
        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "pct_change", "lookback_n": 7, "compare_value": 3},
        {"field": "volume", "operator": ">", "compare_type": "field", "compare_field": "volume_ma", "compare_params": {"period": 3}},
    ]
    MACD_SELL = SELL_LT2DLOW

    count = 0
    rsi_combos = [
        (47, 67), (50, 65), (45, 60), (50, 75), (55, 70),
        (48, 68), (50, 60), (52, 72), (45, 70), (55, 75),
    ]
    for rsi_low, rsi_high in rsi_combos:
        for sell_name in ["lt2dLow", "aR2vF2", "gt10dH", "fall2d", "rise4d"]:
            bc = copy.deepcopy(MACD_BUY)
            bc[0]["compare_value"] = rsi_low
            bc[1]["compare_value"] = rsi_high
            sell_conds = SELL_CONDITIONS[sell_name]
            suffix = f"macd_R{rsi_low}_{rsi_high}_{sell_name}"
            configs = make_configs(bc, sell_conds, suffix)
            eid = submit(ES_SOURCE, configs, f"MACD+RSI {suffix}")
            if eid: all_ids.append(eid)
            count += 1
            time.sleep(0.5)
            if count >= 50:
                break
        if count >= 50:
            break
    print(f"  MACD+RSI: {count} submitted")

    # ══════════════════ Summary ══════════════════
    elapsed = (datetime.now() - started).total_seconds()
    est_strategies = len(all_ids) * 8
    est_hours = est_strategies * 4 / 60

    print(f"\n=== R1188 Batch Complete ===")
    print(f"Submitted: {len(all_ids)} experiments ({est_strategies} estimated strategies)")
    print(f"Submission time: {elapsed:.0f}s")
    print(f"Estimated backtest time: ~{est_hours:.0f}h ({est_hours/24:.1f} days)")
    print(f"First experiment: E{all_ids[0] if all_ids else '?'}")
    print(f"Last experiment: E{all_ids[-1] if all_ids else '?'}")

    with open('/tmp/r1188_experiments.json', 'w') as f:
        json.dump({
            'started_at': started.isoformat(),
            'experiment_ids': all_ids,
            'count': len(all_ids),
        }, f, indent=2)

    print(f"Saved to /tmp/r1188_experiments.json")


if __name__ == "__main__":
    main()
