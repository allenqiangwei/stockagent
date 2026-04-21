#!/usr/bin/env python3
"""Round 549: aR2vF2 sell across buy families + lt2dLow ATR sweep.

Key insight from R548: aR2vF2 sell = 100% StdA+, lt2dLow sell = 5060% max return.
Test these top sell conditions across KDJ and EMA+ATR buy families.

Directions:
1. KDJ buy + aR2vF2 sell — 12 experiments (ATR 0.08-0.095 × MHD 3,5,7)
2. KDJ buy + lt2dLow sell — 6 experiments (ATR 0.08-0.095)
3. EMA+ATR buy + aR2vF2 sell — 8 experiments (ATR 0.08-0.095 × MHD 3,5)
4. EMA+ATR buy + lt2dLow sell — 6 experiments (ATR 0.08-0.095)
5. MACD+RSI + lt2dLow ATR fine sweep — 10 experiments (ATR 0.070-0.100 step 0.005)
6. MACD+RSI + aR2vF2 MHD sweep — 8 experiments (MHD 1,2,4,6,8,10 + extreme SL)
"""

import subprocess
import json
import time
import sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}

# Source ES IDs
ES_KDJ = 22581       # KDJ+RSI (has KDJ_K, RSI, ATR, close, ROC)
ES_MACD_RSI = 20989  # MACD+RSI (has MACD, RSI, MFI, ATR, close)
ES_EMA_ATR = 20980   # EMA+ATR (has EMA, ATR, close)


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


# ── Buy condition templates ──

def kdj_buy(kdj_lo=30, kdj_hi=70, atr_thresh=0.09):
    return [
        {"field": "KDJ_K", "params": {"k": 9, "d": 3, "smooth": 3}, "operator": ">",
         "compare_type": "value", "compare_value": kdj_lo},
        {"field": "KDJ_K", "params": {"k": 9, "d": 3, "smooth": 3}, "operator": "<",
         "compare_type": "value", "compare_value": kdj_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def rsi_atr_buy(atr_thresh=0.09, rsi_lo=50, rsi_hi=70):
    return [
        {"field": "RSI", "params": {"period": 14}, "operator": ">",
         "compare_type": "value", "compare_value": rsi_lo},
        {"field": "RSI", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": rsi_hi},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
    ]


def ema_atr_buy(atr_thresh=0.09):
    """EMA+ATR buy: close > EMA12 + ATR filter."""
    return [
        {"field": "close", "params": {}, "operator": ">",
         "compare_type": "field", "compare_field": "EMA",
         "compare_params": {"length": 12}, "label": "close>EMA12"},
        {"field": "ATR", "params": {"period": 14}, "operator": "<",
         "compare_type": "value", "compare_value": atr_thresh},
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


# ── Exit config grids ──

def grid_18(mhd_fixed=3):
    """SL{10,12,15,20,25,99} × TP{1.0,1.5,2.0}."""
    configs = []
    for sl in [10, 12, 15, 20, 25, 99]:
        for tp in [1.0, 1.5, 2.0]:
            configs.append({
                "stop_loss_pct": -sl,
                "take_profit_pct": tp,
                "max_hold_days": mhd_fixed,
            })
    return configs


def grid_mhd_sweep():
    """MHD{1,2,4,6,8,10} × SL{10,15,99} — 18 configs."""
    configs = []
    for mhd in [1, 2, 4, 6, 8, 10]:
        for sl in [10, 15, 99]:
            configs.append({
                "stop_loss_pct": -sl,
                "take_profit_pct": 1.5,
                "max_hold_days": mhd,
            })
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

    return {
        "source_strategy_id": source_id,
        "exit_configs": configs,
        "initial_capital": 100000,
        "max_positions": 10,
        "max_position_pct": 30,
    }


def submit(label, source_id, buy, sell, grid, suffix):
    data = make_batch(source_id, buy, sell, grid, suffix)
    n = len(data["exit_configs"])
    print(f"  [{label}] ES{source_id} × {n} configs...", end=" ", flush=True)
    result = api_post(f"lab/strategies/{source_id}/batch-clone-backtest", data)
    eid = result.get("experiment_id")
    if eid:
        print(f"E{eid} ({n} strats)")
    else:
        print(f"FAILED: {result}")
    return eid


def main():
    start_time = time.time()
    experiment_ids = []

    print("=" * 60)
    print("Round 549: aR2vF2/lt2dLow × Buy Family Grid")
    print("=" * 60)

    # ── Direction 1: KDJ buy + aR2vF2 sell ──
    print("\n── Direction 1: KDJ buy + aR2vF2 sell ──")
    for atr in [0.08, 0.085, 0.09, 0.095]:
        for mhd in [3, 5, 7]:
            eid = submit(
                f"KDJ aR2vF2 ATR{atr} MHD{mhd}",
                ES_KDJ,
                kdj_buy(atr_thresh=atr),
                SELL_AR2VF2,
                grid_18(mhd_fixed=mhd),
                f"KDJ_aR2vF2_ATR{atr}_MHD{mhd}",
            )
            if eid:
                experiment_ids.append(eid)
            time.sleep(2)

    # ── Direction 2: KDJ buy + lt2dLow sell ──
    print("\n── Direction 2: KDJ buy + lt2dLow sell ──")
    for atr in [0.08, 0.085, 0.09, 0.095, 0.10, 0.105]:
        eid = submit(
            f"KDJ lt2dLow ATR{atr}",
            ES_KDJ,
            kdj_buy(atr_thresh=atr),
            SELL_LT2DLOW,
            grid_18(mhd_fixed=5),
            f"KDJ_lt2dLow_ATR{atr}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # ── Direction 3: EMA+ATR buy + aR2vF2 sell ──
    print("\n── Direction 3: EMA+ATR buy + aR2vF2 sell ──")
    for atr in [0.08, 0.085, 0.09, 0.095]:
        for mhd in [3, 5]:
            eid = submit(
                f"EMA+ATR aR2vF2 ATR{atr} MHD{mhd}",
                ES_EMA_ATR,
                ema_atr_buy(atr_thresh=atr),
                SELL_AR2VF2,
                grid_18(mhd_fixed=mhd),
                f"EMA_aR2vF2_ATR{atr}_MHD{mhd}",
            )
            if eid:
                experiment_ids.append(eid)
            time.sleep(2)

    # ── Direction 4: EMA+ATR buy + lt2dLow sell ──
    print("\n── Direction 4: EMA+ATR buy + lt2dLow sell ──")
    for atr in [0.08, 0.085, 0.09, 0.095, 0.10, 0.105]:
        eid = submit(
            f"EMA+ATR lt2dLow ATR{atr}",
            ES_EMA_ATR,
            ema_atr_buy(atr_thresh=atr),
            SELL_LT2DLOW,
            grid_18(mhd_fixed=5),
            f"EMA_lt2dLow_ATR{atr}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # ── Direction 5: MACD+RSI + lt2dLow ATR fine sweep ──
    print("\n── Direction 5: MACD+RSI lt2dLow ATR fine sweep ──")
    for atr_int in range(70, 105, 5):  # 0.070 to 0.100
        atr = atr_int / 1000.0
        eid = submit(
            f"RSI lt2dLow ATR{atr:.3f}",
            ES_MACD_RSI,
            rsi_atr_buy(atr_thresh=atr),
            SELL_LT2DLOW,
            grid_18(mhd_fixed=5),
            f"RSI_lt2dLow_ATR{atr:.3f}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # ── Direction 6: MACD+RSI + aR2vF2 MHD sweep ──
    print("\n── Direction 6: MACD+RSI aR2vF2 MHD sweep ──")
    for atr in [0.085, 0.09]:
        eid = submit(
            f"RSI aR2vF2 ATR{atr} MHD-sweep",
            ES_MACD_RSI,
            rsi_atr_buy(atr_thresh=atr),
            SELL_AR2VF2,
            grid_mhd_sweep(),
            f"RSI_aR2vF2_ATR{atr}_MHDswp",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    # Also test lt3dLow vs lt2dLow
    for sell_name, sell_conds in [("lt3dLow", SELL_LT3DLOW)]:
        for atr in [0.085, 0.09, 0.095]:
            eid = submit(
                f"RSI {sell_name} ATR{atr}",
                ES_MACD_RSI,
                rsi_atr_buy(atr_thresh=atr),
                sell_conds,
                grid_18(mhd_fixed=5),
                f"RSI_{sell_name}_ATR{atr}",
            )
            if eid:
                experiment_ids.append(eid)
            time.sleep(2)

    # Also EMA+ATR with lt3dLow
    for atr in [0.085, 0.09]:
        eid = submit(
            f"EMA lt3dLow ATR{atr}",
            ES_EMA_ATR,
            ema_atr_buy(atr_thresh=atr),
            SELL_LT3DLOW,
            grid_18(mhd_fixed=5),
            f"EMA_lt3dLow_ATR{atr}",
        )
        if eid:
            experiment_ids.append(eid)
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Submitted {len(experiment_ids)} experiments in {elapsed:.0f}s")
    print(f"Experiment IDs: {experiment_ids}")
    print(f"Total strategies: ~{len(experiment_ids) * 18}")

    with open("/tmp/r549_experiments.json", "w") as f:
        json.dump({"experiment_ids": experiment_ids, "start_time": start_time}, f)
    print(f"\nSaved to /tmp/r549_experiments.json")
    print("Poll with: python3 scripts/r549_poll.py")


if __name__ == "__main__":
    main()
