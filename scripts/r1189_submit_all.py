#!/usr/bin/env python3
"""R1189: Submit 500 experiments via batch-clone-backtest.
Run: NO_PROXY=localhost,127.0.0.1 nohup python3 scripts/r1189_submit_all.py > /tmp/r1189_submit.log 2>&1 &
"""
import subprocess
import json
import time
import sys
from datetime import datetime

API_BASE = "http://127.0.0.1:8050/api"
START_TIME = datetime.now().isoformat()

def api_post(path, data):
    r = subprocess.run(
        ['curl', '-s', '--max-time', '30', '-X', 'POST', f'{API_BASE}/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {'error': r.stdout[:200]}

# ─── Sell condition variants ───
SELLS = {
    "lt2dLow": [{"field": "close", "operator": "<", "compare_type": "lookback_min", "lookback_n": 2}],
    "aR2vF2": [
        {"field": "ATR", "params": {"period": 14}, "operator": ">", "compare_type": "consecutive", "consecutive_type": "rising", "lookback_n": 2},
        {"field": "volume", "operator": ">", "compare_type": "consecutive", "consecutive_type": "falling", "lookback_n": 2},
    ],
    "fall2d": [{"field": "close", "operator": "<", "compare_type": "consecutive", "consecutive_n": 2, "direction": "falling"}],
    "gt10dH": [{"field": "close", "operator": ">", "compare_type": "lookback_max", "lookback_n": 10}],
    "rise4d": [{"field": "close", "operator": ">", "compare_type": "consecutive", "consecutive_n": 4, "direction": "rising"}],
}
SELL_NAMES = list(SELLS.keys())

# ─── Exit param sets (8 configs per experiment) ───
EXIT_SETS = [
    [(1.0,2), (1.5,2), (2.0,3), (2.5,3), (3.0,3), (3.0,5), (4.0,5), (5.0,7)],
    [(0.5,1), (0.8,1), (1.0,1), (1.2,2), (1.5,2), (2.0,3), (2.5,3), (3.0,5)],
    [(2.0,1), (2.0,2), (2.0,3), (2.0,5), (2.0,7), (3.0,2), (3.0,5), (3.0,7)],
    [(1.0,3), (1.5,3), (2.0,5), (2.5,5), (3.0,7), (4.0,7), (5.0,10), (3.0,3)],
]

def submit(source_id, buy, sell_name, exit_idx, label):
    sell_conds = SELLS[sell_name]
    exits = EXIT_SETS[exit_idx % 4]
    configs = []
    for tp, mhd in exits:
        configs.append({
            "name_suffix": f"_{label}_{sell_name}_TP{tp}_MHD{mhd}",
            "exit_config": {"stop_loss_pct": -20, "take_profit_pct": tp, "max_hold_days": mhd},
            "buy_conditions": buy,
            "sell_conditions": sell_conds,
        })
    result = api_post(f'lab/strategies/{source_id}/batch-clone-backtest', {
        "source_strategy_id": source_id,
        "exit_configs": configs,
    })
    return result.get('experiment_id')


def main():
    print(f"R1189 Batch Submission — {datetime.now()}", flush=True)
    print(f"Target: ~500 experiments × 8 = ~4000 strategies", flush=True)

    all_ids = []
    count = 0
    failed = 0

    # ─── 1. MACD+RSI: 200 experiments ───
    print(f"\n[{datetime.now().strftime('%H:%M')}] === MACD+RSI (target: 200) ===", flush=True)
    target_1 = 200
    base = count
    for rsi_p in [14, 16, 18, 20]:
        for rsi_lo in [47, 48, 50, 52, 55]:
            for rsi_hi in [65, 67, 70, 72, 75]:
                if rsi_lo >= rsi_hi - 8:
                    continue
                for atr_t in [0.0875, 0.09, 0.095, 0.10, 0.105, 0.11, 0.12]:
                    sell_name = SELL_NAMES[count % 5]
                    buy = [
                        {"field": "RSI", "params": {"period": rsi_p}, "operator": ">", "compare_type": "value", "compare_value": rsi_lo},
                        {"field": "RSI", "params": {"period": rsi_p}, "operator": "<", "compare_type": "value", "compare_value": rsi_hi},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr_t},
                        {"field": "close", "operator": ">", "compare_type": "lookback_min", "lookback_n": 13},
                        {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "pct_change", "lookback_n": 7, "compare_value": 3},
                    ]
                    label = f"RSI{rsi_p}_{rsi_lo}to{rsi_hi}_ATR{atr_t}_AM13"
                    eid = submit(75014, buy, sell_name, count, label)
                    if eid:
                        all_ids.append(eid)
                    else:
                        failed += 1
                    count += 1
                    if (count - base) % 50 == 0:
                        print(f"  [{count-base}/{target_1}] {len(all_ids)} ok, {failed} failed", flush=True)
                    if count - base >= target_1:
                        break
                if count - base >= target_1: break
            if count - base >= target_1: break
        if count - base >= target_1: break
    print(f"  MACD+RSI done: {count-base} attempted, {len(all_ids)} successful", flush=True)

    # ─── 2. 三指標: 80 experiments ───
    print(f"\n[{datetime.now().strftime('%H:%M')}] === 三指標 (target: 80) ===", flush=True)
    target_2 = 80
    base = count
    for mfi in [30, 35, 40, 45, 50]:
        for roc in [0.3, 0.5, 0.8, 1.0]:
            for atr in [0.04, 0.05, 0.06, 0.07, 0.08]:
                sell_name = SELL_NAMES[(count - base) % 5]
                buy = [
                    {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "BOLL_middle", "compare_params": {"length": 20, "std": 2.0}},
                    {"field": "MFI", "params": {"length": 14}, "operator": ">", "compare_type": "value", "compare_value": mfi},
                    {"field": "ROC", "params": {"length": 12}, "operator": ">", "compare_type": "value", "compare_value": roc},
                    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                ]
                label = f"MFI{mfi}_ROC{roc}_ATR{atr}"
                eid = submit(75293, buy, sell_name, count, label)
                if eid:
                    all_ids.append(eid)
                else:
                    failed += 1
                count += 1
                if count - base >= target_2: break
            if count - base >= target_2: break
        if count - base >= target_2: break
    print(f"  三指標 done: {count-base} attempted", flush=True)

    # ─── 3. VPT+PSAR: 60 experiments ───
    print(f"\n[{datetime.now().strftime('%H:%M')}] === VPT+PSAR (target: 60) ===", flush=True)
    target_3 = 60
    base = count
    for vpt in [-2000, -1500, -1000, -500, 0]:
        for bw in [3.0, 4.0, 5.0, 6.0, 8.0]:
            for sell_name in SELL_NAMES:
                buy = [
                    {"field": "VPT", "params": {}, "operator": ">", "compare_type": "value", "compare_value": vpt},
                    {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "PSAR", "compare_params": {"step": 0.02, "max_step": 0.2}},
                    {"field": "BOLL_wband", "params": {"length": 20, "std": 2.0}, "operator": "<", "compare_type": "value", "compare_value": bw},
                ]
                label = f"VPT{vpt}_BW{bw}"
                eid = submit(75063, buy, sell_name, count, label)
                if eid:
                    all_ids.append(eid)
                else:
                    failed += 1
                count += 1
                if count - base >= target_3: break
            if count - base >= target_3: break
        if count - base >= target_3: break
    print(f"  VPT+PSAR done: {count-base} attempted", flush=True)

    # ─── 4. RSI+KDJ: 80 experiments ───
    print(f"\n[{datetime.now().strftime('%H:%M')}] === RSI+KDJ (target: 80) ===", flush=True)
    target_4 = 80
    base = count
    for kl in [20, 30, 35, 40, 45, 50]:
        for kh in [70, 75, 80, 85, 90]:
            if kl >= kh - 15:
                continue
            for atr in [0.07, 0.08, 0.09, 0.091, 0.10, 0.11]:
                sell_name = SELL_NAMES[(count - base) % 5]
                buy = [
                    {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": ">", "compare_type": "value", "compare_value": kl},
                    {"field": "KDJ_K", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "operator": "<", "compare_type": "value", "compare_value": kh},
                    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                ]
                label = f"KDJ{kl}to{kh}_ATR{atr}"
                eid = submit(36540, buy, sell_name, count, label)
                if eid:
                    all_ids.append(eid)
                else:
                    failed += 1
                count += 1
                if count - base >= target_4: break
            if count - base >= target_4: break
        if count - base >= target_4: break
    print(f"  RSI+KDJ done: {count-base} attempted", flush=True)

    # ─── 5. 全指標: 80 experiments ───
    print(f"\n[{datetime.now().strftime('%H:%M')}] === 全指標 (target: 80) ===", flush=True)
    target_5 = 80
    base = count
    for ema in [8, 10, 12, 15, 20]:
        for atr in [0.06, 0.08, 0.10, 0.12]:
            for rsi_lo, rsi_hi in [(45, 70), (50, 75), (40, 65), (55, 80)]:
                sell_name = SELL_NAMES[(count - base) % 5]
                buy = [
                    {"field": "close", "params": {}, "operator": ">", "compare_type": "field", "compare_field": "EMA", "compare_params": {"length": ema}},
                    {"field": "ATR", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": atr},
                    {"field": "RSI", "params": {"period": 14}, "operator": ">", "compare_type": "value", "compare_value": rsi_lo},
                    {"field": "RSI", "params": {"period": 14}, "operator": "<", "compare_type": "value", "compare_value": rsi_hi},
                ]
                label = f"EMA{ema}_ATR{atr}_RSI{rsi_lo}to{rsi_hi}"
                eid = submit(75014, buy, sell_name, count, label)
                if eid:
                    all_ids.append(eid)
                else:
                    failed += 1
                count += 1
                if count - base >= target_5: break
            if count - base >= target_5: break
        if count - base >= target_5: break
    print(f"  全指標 done: {count-base} attempted", flush=True)

    # ─── Summary ───
    total_ok = len(all_ids)
    print(f"\n{'='*60}", flush=True)
    print(f"R1189 SUBMISSION COMPLETE — {datetime.now()}", flush=True)
    print(f"Total attempted: {count}", flush=True)
    print(f"Successful: {total_ok}", flush=True)
    print(f"Failed: {failed}", flush=True)
    print(f"Expected strategies: {total_ok * 8}", flush=True)
    print(f"{'='*60}", flush=True)

    # Save IDs
    with open('/tmp/r1189_experiment_ids.json', 'w') as f:
        json.dump({
            'round': 1189,
            'start_time': START_TIME,
            'experiment_ids': all_ids,
            'total_experiments': total_ok,
            'expected_strategies': total_ok * 8,
        }, f, indent=2)
    print(f"\nSaved to /tmp/r1189_experiment_ids.json", flush=True)
    print(f"Next: NO_PROXY=localhost,127.0.0.1 nohup python3 scripts/r1189_auto_finish.py > /tmp/r1189_auto_finish.log 2>&1 &", flush=True)


if __name__ == "__main__":
    main()
