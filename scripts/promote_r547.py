#!/usr/bin/env python3
"""Promote all R547 StdA+ strategies to the strategy library."""
import json
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_promote import auto_promote_stda, is_stda_plus

# Load R547 results
with open('/tmp/r547_results.json') as f:
    all_results = json.load(f)

aR2vF2 = [
    {'field': 'ATR', 'params': {'period': 14}, 'operator': '>', 'compare_type': 'consecutive', 'consecutive_type': 'rising', 'lookback_n': 2},
    {'field': 'volume', 'operator': '>', 'compare_type': 'consecutive', 'consecutive_type': 'falling', 'lookback_n': 2},
]
aR3vF2 = [
    {'field': 'ATR', 'params': {'period': 14}, 'operator': '>', 'compare_type': 'consecutive', 'consecutive_type': 'rising', 'lookback_n': 3},
    {'field': 'volume', 'operator': '>', 'compare_type': 'consecutive', 'consecutive_type': 'falling', 'lookback_n': 2},
]


def parse_name(name):
    """Parse strategy name to reconstruct buy/sell conditions and exit config."""
    # Extract RSI period
    rsi_match = re.search(r'RSI(\d+)', name)
    rsi_period = int(rsi_match.group(1)) if rsi_match else 18

    # Extract ATR threshold
    atr_match = re.search(r'ATR([\d.]+)', name)
    atr_thresh = float(atr_match.group(1)) if atr_match else 0.087

    # Extract DIP value
    dip_match = re.search(r'DIP-([\d.]+)', name)
    dip = -float(dip_match.group(1)) if dip_match else -2.9

    # Extract AbvMin lookback
    abv_match = re.search(r'AbvMin(\d+)', name)
    lookback = int(abv_match.group(1)) if abv_match else 15

    # Extract TP
    tp_match = re.search(r'TP([\d.]+)', name)
    tp = float(tp_match.group(1)) if tp_match else 2.5

    # Extract MHD
    mhd_match = re.search(r'MHD(\d+)', name)
    mhd = int(mhd_match.group(1)) if mhd_match else 7

    # Determine sell conditions
    sell = aR3vF2 if 'aR3vF2' in name else aR2vF2

    # Extract slippage
    slip_match = re.search(r'slip([\d.]+)', name)
    slippage = float(slip_match.group(1)) if slip_match else 0.1

    buy = [
        {'field': 'RSI', 'params': {'period': rsi_period}, 'operator': '>', 'compare_type': 'value', 'compare_value': 50},
        {'field': 'RSI', 'params': {'period': rsi_period}, 'operator': '<', 'compare_type': 'value', 'compare_value': 75},
        {'field': 'ATR', 'params': {'period': 14}, 'operator': '<', 'compare_type': 'value', 'compare_value': atr_thresh},
        {'field': 'close', 'params': {}, 'compare_type': 'pct_change', 'operator': '<', 'compare_value': dip, 'lookback_n': 1},
        {'field': 'close', 'params': {}, 'operator': '>', 'compare_type': 'lookback_min', 'lookback_n': lookback},
    ]

    exit_cfg = {'take_profit_pct': tp, 'stop_loss_pct': -10, 'max_hold_days': mhd}

    return buy, sell, exit_cfg, slippage


# Promote all StdA+
promoted = 0
skipped = 0
failed = 0

stda_results = {k: v for k, v in all_results.items() if is_stda_plus(v)}
print(f"R547: {len(stda_results)} StdA+ strategies to promote\n")

for name, metrics in sorted(stda_results.items(), key=lambda x: x[1]['score'], reverse=True):
    buy, sell, exit_cfg, slippage = parse_name(name)

    r = auto_promote_stda(
        name=name,
        buy_conditions=buy,
        sell_conditions=sell,
        exit_config=exit_cfg,
        metrics=metrics,
        portfolio_config={'max_positions': 10, 'max_position_pct': 30},
        slippage_pct=slippage,
    )

    if r['promoted']:
        promoted += 1
    elif r['detail'] == 'Already exists':
        skipped += 1
    else:
        failed += 1

print(f"\nDone: {promoted} promoted, {skipped} already exist, {failed} failed")
