#!/usr/bin/env python3
"""Round 548: Comprehensive grid search across families and sell conditions.

Targets ~50 experiments × 18 configs = ~900 strategies.
Uses batch-clone-backtest for efficiency (data loaded once per experiment).

Directions:
1. RSI+ATR buy + aR2vF2 sell (ATR0.08-0.10) — 12 experiments
2. RSI+ATR buy + lt2dLow/lt3dLow sell — 8 experiments
3. DIP-BUY (pct_change dip buy) — 15 experiments
4. VPT+PSAR buy + new sells — 8 experiments
5. 三指標 buy + new sells — 7 experiments
"""

import subprocess
import json
import time
import sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}

# Source ES IDs
ES_MACD_RSI = 20989   # MACD+RSI base (has MACD, RSI, MFI, ATR, close indicators)
ES_QUANZHIBIAO = 20980  # 全指标综合 (has EMA, ATR, close)
ES_VPT_PSAR = 21054     # VPT+PSAR (has VPT, PSAR, BOLL_wband)
ES_SANZHIBIAO = 21079   # 三指標 (has BOLL, MFI, ROC)


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


def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'{API}/{path}'],
        capture_output=True, text=True, env=ENV, timeout=30)
    return json.loads(r.stdout)


# ── Buy condition templates ──

def rsi_atr_buy(atr_thresh=0.09, rsi_lo=50, rsi_hi=70):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def dip_buy(dip_pct=-2.5, atr_thresh=0.091, rsi_lo=48, rsi_hi=66):
    """DIP-BUY: buy on panic dips."""
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
        {"field": "close", "params": {}, "compare_type": "pct_change",
         "operator": "<", "compare_value": dip_pct, "lookback_n": 1,
         "label": f"dip{dip_pct}%"},
    ]


# ── Sell condition templates ──

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

SELL_FALL2D = [
    {"field": "close", "params": {}, "compare_type": "consecutive",
     "operator": ">", "consecutive_n": 2, "direction": "falling", "label": "fall2d"},
]

SELL_GT10DHIGH = [
    {"field": "close", "params": {}, "compare_type": "lookback_max",
     "operator": ">", "lookback_n": 10, "label": "gt10dHigh"},
]


# ── Exit config grid generators ──

def grid_18(mhd_fixed=3):
    """Generate 18 exit configs: SL{10,12,15,20,25,99} × TP{1.0,1.5,2.0}."""
    configs = []
    for sl in [10, 12, 15, 20, 25, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({
                "stop_loss_pct": -sl,
                "take_profit_pct": tp,
                "max_hold_days": mhd_fixed,
            })
    return configs


def grid_dip_18(mhd_fixed=5):
    """Generate 18 exit configs for DIP-BUY: SL{15,20,99} × TP{1.5,2.0,2.5,3.0,3.5,4.0}."""
    configs = []
    for sl in [15, 20, 99]:
        for tp in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
            configs.append({
                "stop_loss_pct": -sl,
                "take_profit_pct": tp,
                "max_hold_days": mhd_fixed,
            })
    return configs


def make_batch(source_id, buy_conds, sell_conds, exit_grid, suffix_base):
    """Create a batch-clone-backtest request."""
    configs = []
    for ec in exit_grid:
        sl = abs(ec["stop_loss_pct"])
        tp = ec["take_profit_pct"]
        mhd = ec["max_hold_days"]
        suffix = f"{suffix_base}_SL{sl}_TP{tp}_MHD{mhd}"
        cfg = {
            "name_suffix": suffix,
            "exit_config": ec,
        }
        if buy_conds is not None:
            cfg["buy_conditions"] = buy_conds
        if sell_conds is not None:
            cfg["sell_conditions"] = sell_conds
        configs.append(cfg)

    return {
        "source_strategy_id": source_id,
        "exit_configs": configs,
        "initial_capital": 100000,
        "max_positions": 10,
        "max_position_pct": 30,
    }


def submit(label, source_id, buy, sell, grid, suffix):
    """Submit a batch-clone experiment and return experiment_id."""
    data = make_batch(source_id, buy, sell, grid, suffix)
    n = len(data["exit_configs"])
    print(f"  [{label}] Submitting ES{source_id} × {n} configs...", end=" ", flush=True)
    result = api_post(f"lab/strategies/{source_id}/batch-clone-backtest", data)
    eid = result.get("experiment_id")
    if eid:
        print(f"E{eid} created ({n} strategies)")
    else:
        print(f"FAILED: {result}")
    return eid


def main():
    start_time = time.time()
    experiment_ids = []

    print("=" * 60)
    print("Round 548: Comprehensive Grid Search")
    print("=" * 60)

    # ── Direction 1: RSI+ATR buy + aR2vF2 sell ──
    print("\n── Direction 1: RSI+ATR buy + aR2vF2 sell ──")
    for atr in [0.08, 0.085, 0.09, 0.095]:
        eid = submit(
            f"aR2vF2 ATR{atr}",
            ES_MACD_RSI,
            rsi_atr_buy(atr_thresh=atr),
            SELL_AR2VF2,
            grid_18(mhd_fixed=3),
            f"aR2vF2_ATR{atr}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)  # avoid overwhelming API

    # Also test MHD5 and MHD7 for best ATR
    for mhd in [5, 7]:
        eid = submit(
            f"aR2vF2 ATR0.09 MHD{mhd}",
            ES_MACD_RSI,
            rsi_atr_buy(atr_thresh=0.09),
            SELL_AR2VF2,
            grid_18(mhd_fixed=mhd),
            f"aR2vF2_ATR0.09_MHD{mhd}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # ── Direction 2: RSI+ATR buy + lt2dLow/lt3dLow sell ──
    print("\n── Direction 2: RSI+ATR buy + lt2dLow/lt3dLow sell ──")
    for sell_name, sell_conds in [("lt2dLow", SELL_LT2DLOW), ("lt3dLow", SELL_LT3DLOW)]:
        for atr in [0.08, 0.09]:
            eid = submit(
                f"{sell_name} ATR{atr}",
                ES_MACD_RSI,
                rsi_atr_buy(atr_thresh=atr),
                sell_conds,
                grid_18(mhd_fixed=5),  # ltNdLow needs wider SL, longer MHD
                f"{sell_name}_ATR{atr}",
            )
            if eid:
                experiment_ids.append(eid)
            time.sleep(2)

    # Also test fall2d sell
    for atr in [0.08, 0.09]:
        eid = submit(
            f"fall2d ATR{atr}",
            ES_MACD_RSI,
            rsi_atr_buy(atr_thresh=atr),
            SELL_FALL2D,
            grid_18(mhd_fixed=5),
            f"fall2d_ATR{atr}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # ── Direction 3: DIP-BUY ──
    print("\n── Direction 3: DIP-BUY ──")
    for dip in [-1.5, -2.0, -2.5, -3.0, -3.5]:
        for sell_name, sell_conds in [("aR2vF2", SELL_AR2VF2), ("lt2dLow", SELL_LT2DLOW), ("fall2d", SELL_FALL2D)]:
            eid = submit(
                f"DIP{dip} {sell_name}",
                ES_MACD_RSI,
                dip_buy(dip_pct=dip),
                sell_conds,
                grid_dip_18(mhd_fixed=5),
                f"DIP{abs(dip)}_{sell_name}",
            )
            if eid:
                experiment_ids.append(eid)
            time.sleep(2)

    # ── Direction 4: VPT+PSAR buy + new sells ──
    print("\n── Direction 4: VPT+PSAR buy + new sells ──")
    # VPT+PSAR source has: VPT, PSAR, BOLL_wband
    # Override sell conditions with aR2vF2, lt2dLow, fall2d, gt10dHigh
    # Note: aR2vF2 needs ATR which VPT+PSAR source doesn't have -> skip
    # VPT+PSAR can use: lookback, consecutive on close/volume, gt10dHigh
    for sell_name, sell_conds in [
        ("lt2dLow", SELL_LT2DLOW),
        ("lt3dLow", SELL_LT3DLOW),
        ("fall2d", SELL_FALL2D),
        ("gt10dH", SELL_GT10DHIGH),
    ]:
        eid = submit(
            f"VPT+PSAR {sell_name}",
            ES_VPT_PSAR,
            None,  # use source buy conditions
            sell_conds,
            grid_18(mhd_fixed=5),
            f"VPTPSAR_{sell_name}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # VPT+PSAR with ATR filter added to buy
    for sell_name, sell_conds in [("lt2dLow", SELL_LT2DLOW), ("fall2d", SELL_FALL2D)]:
        # Override buy with ATR filter added
        vpt_buy_with_atr = [
            {"field": "VPT", "params": {}, "operator": ">",
             "compare_type": "value", "compare_value": -1500, "label": "VPT>-1500"},
            {"field": "close", "params": {}, "operator": ">",
             "compare_type": "field", "compare_field": "PSAR",
             "compare_params": {"step": 0.02, "max_step": 0.2}, "label": "close>PSAR"},
            {"field": "BOLL_wband", "params": {"length": 20, "std": 2.0}, "operator": "<",
             "compare_type": "value", "compare_value": 5.0, "label": "BWB<5"},
        ]
        eid = submit(
            f"VPT+PSAR+ATR {sell_name}",
            ES_VPT_PSAR,
            vpt_buy_with_atr,
            sell_conds,
            grid_18(mhd_fixed=5),
            f"VPTPSAR_ATR_{sell_name}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # ── Direction 5: 三指標 buy + new sells ──
    print("\n── Direction 5: 三指標 buy + new sells ──")
    for sell_name, sell_conds in [
        ("lt2dLow", SELL_LT2DLOW),
        ("lt3dLow", SELL_LT3DLOW),
        ("fall2d", SELL_FALL2D),
        ("gt10dH", SELL_GT10DHIGH),
    ]:
        eid = submit(
            f"三指標 {sell_name}",
            ES_SANZHIBIAO,
            None,  # use source buy conditions
            sell_conds,
            grid_18(mhd_fixed=5),
            f"SanZhi_{sell_name}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # Also test with different MHD
    for mhd in [3, 7]:
        eid = submit(
            f"三指標 lt2dLow MHD{mhd}",
            ES_SANZHIBIAO,
            None,
            SELL_LT2DLOW,
            grid_18(mhd_fixed=mhd),
            f"SanZhi_lt2dLow_MHD{mhd}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # Also test 全指标综合 (ES20980) with new sells
    print("\n── Bonus: 全指標 buy + new sells ──")
    for sell_name, sell_conds in [
        ("aR2vF2", SELL_AR2VF2),
        ("lt2dLow", SELL_LT2DLOW),
        ("fall2d", SELL_FALL2D),
    ]:
        eid = submit(
            f"全指標 {sell_name}",
            ES_QUANZHIBIAO,
            rsi_atr_buy(atr_thresh=0.09),  # override with RSI+ATR buy
            sell_conds,
            grid_18(mhd_fixed=3),
            f"QuanZhi_{sell_name}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")
    print(f"Experiment IDs: {experiment_ids}")
    print(f"Total strategies: ~{len(experiment_ids) * 18}")

    # Save experiment IDs for polling
    with open("/tmp/r548_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)

    print(f"\nSaved to /tmp/r548_experiments.json")
    print("Run polling with: python3 scripts/r548_poll.py")


if __name__ == "__main__":
    main()
