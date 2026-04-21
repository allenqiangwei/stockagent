#!/usr/bin/env python3
"""R541: TP boundary hunt (2.70-2.85), TP2.7 sell/MHD/RSI optimization, ATR×TP cross."""
import sys, json, math, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services.data_collector import DataCollector
from api.models.base import SessionLocal
from src.backtest.portfolio_engine import PortfolioBacktestEngine
from api.models.stock import Stock

print("Loading stock data...")
t0 = time.time()
db = SessionLocal()
dc = DataCollector(db)
stock_codes = [s[0] for s in db.query(Stock.code).all()]
stock_data = {}
for code in stock_codes:
    df = dc.get_daily_df(code, '2021-01-01', '2026-03-09', local_only=True)
    if df is not None and not df.empty and len(df) >= 60:
        stock_data[code] = df
db.close()
print(f"Loaded {len(stock_data)} stocks in {time.time()-t0:.1f}s")

def sigmoid(x, c, s):
    try: return 1.0/(1.0+math.exp(-(x-c)/max(s,0.001)))
    except: return 0.5

def calc_score(r):
    ret = getattr(r,'total_return_pct',0) or 0
    dd = abs(getattr(r,'max_drawdown_pct',100) or 100)
    sh = getattr(r,'sharpe_ratio',0) or 0
    pl = getattr(r,'profit_loss_ratio',0) or 0
    return 0.30*sigmoid(ret,50,30)+0.25*(1-sigmoid(dd,15,5))+0.25*sigmoid(sh,1.0,0.5)+0.20*sigmoid(pl,1.5,0.5)

def run_bt(name, buy_conds, sell_conds, exit_cfg, max_pos=10, initial_capital=100000, slippage_pct=0.1):
    strat = {'name':name,'buy_conditions':buy_conds,'sell_conditions':sell_conds,'exit_config':exit_cfg,
             'portfolio_config':{'max_positions':max_pos,'max_position_pct':30}}
    eng = PortfolioBacktestEngine(initial_capital=initial_capital,max_positions=max_pos,max_position_pct=30,
                                  slippage_pct=slippage_pct)
    try:
        r = eng.run(strat, stock_data)
    except Exception as e:
        print(f"  ERROR {name}: {e}")
        return None
    tr = getattr(r,'total_trades',0) or 0
    if tr < 10: return None
    sc = calc_score(r)
    wr = getattr(r,'win_rate',0) or 0
    ret = getattr(r,'total_return_pct',0) or 0
    dd = abs(getattr(r,'max_drawdown_pct',100) or 100)
    sh = getattr(r,'sharpe_ratio',0) or 0
    pl = getattr(r,'profit_loss_ratio',0) or 0
    stda = sc>=0.80 and ret>60 and dd<18 and tr>=50 and wr>60
    return {'name':name,'score':round(sc,4),'ret':round(ret,1),'dd':round(dd,1),
            'wr':round(wr,1),'trades':tr,'stda':stda,'sharpe':round(sh,2),'plr':round(pl,2)}

aR2vF2 = [
    {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':2},
    {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
]
aR3vF2 = [
    {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':3},
    {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
]
vF2only = [
    {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
]

def dip_buy(dip, rsi_lb=50, rsi_ub=75, rsi_period=18, atr_thresh=0.087):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
    ]

all_results = {}

# ============================================================
# GRID 1: TP Ultra-Fine Boundary (2.70-2.85 step 0.05)
# Goal: Find the exact TP where wr drops below 60% (TP cliff)
# ============================================================
print("\n=== GRID 1: TP Boundary Hunt 2.70-2.85 ===")
grid1 = []
for tp in [2.70, 2.75, 2.80, 2.85]:
    for dip in [-2.9, -3.0, -3.1]:
        for sell_name, sell_conds in [('aR2vF2', aR2vF2), ('aR3vF2', aR3vF2)]:
            name = f"RSI18_ATR0.087_{sell_name}_DIP{dip}_TP{tp}_MHD7"
            buy = dip_buy(dip)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid1.append((name, buy, sell_conds, exit_cfg))

print(f"Grid 1: {len(grid1)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid1):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
    if (i+1) % 6 == 0: print(f"  Progress: {i+1}/{len(grid1)}")
print(f"Grid 1 done: {sum(1 for r in all_results.values() if 'TP2.7' in r['name'] or 'TP2.75' in r['name'] or 'TP2.8' in r['name'] or 'TP2.85' in r['name'])} results")

# ============================================================
# GRID 2: TP2.7 + Sell Variants + DIP sweep
# Goal: Can different sells extend TP2.7 further?
# ============================================================
print("\n=== GRID 2: TP2.7 Sell Variants ===")
grid2 = []
for sell_name, sell_conds in [('aR2vF2', aR2vF2), ('aR3vF2', aR3vF2), ('vF2only', vF2only)]:
    for dip in [-2.8, -2.9, -3.0, -3.1]:
        for mhd in [7, 10]:
            name = f"RSI18_ATR0.087_{sell_name}_DIP{dip}_TP2.7_MHD{mhd}"
            buy = dip_buy(dip)
            exit_cfg = {'take_profit_pct':2.7, 'stop_loss_pct':-10, 'max_hold_days':mhd}
            grid2.append((name, buy, sell_conds, exit_cfg))

print(f"Grid 2: {len(grid2)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid2):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
    if (i+1) % 6 == 0: print(f"  Progress: {i+1}/{len(grid2)}")
print(f"Grid 2 done")

# ============================================================
# GRID 3: TP2.7 + MHD sweep (3,5,7,10,14)
# Goal: Does longer hold help at TP2.7?
# ============================================================
print("\n=== GRID 3: TP2.7 MHD Sweep ===")
grid3 = []
for mhd in [3, 5, 7, 10, 14]:
    for dip in [-2.9, -3.0, -3.1]:
        for sell_name, sell_conds in [('aR2vF2', aR2vF2)]:
            name = f"RSI18_ATR0.087_{sell_name}_DIP{dip}_TP2.7_MHD{mhd}"
            buy = dip_buy(dip)
            exit_cfg = {'take_profit_pct':2.7, 'stop_loss_pct':-10, 'max_hold_days':mhd}
            grid3.append((name, buy, sell_conds, exit_cfg))

print(f"Grid 3: {len(grid3)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid3):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 3 done")

# ============================================================
# GRID 4: TP2.7 + RSI Period (15-20)
# Goal: Confirm RSI18 optimal at TP2.7
# ============================================================
print("\n=== GRID 4: TP2.7 RSI Period ===")
grid4 = []
for rsi in [15, 16, 17, 18, 19, 20]:
    for dip in [-2.9, -3.0]:
        for tp in [2.65, 2.7]:
            name = f"RSI{rsi}_ATR0.087_aR2vF2_DIP{dip}_TP{tp}_MHD7"
            buy = dip_buy(dip, rsi_period=rsi)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid4.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 4: {len(grid4)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid4):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 4 done")

# ============================================================
# GRID 5: ATR × TP Cross (0.086-0.088 × TP 2.65-2.80)
# Goal: Is there an ATR variant that pushes TP beyond 2.7?
# ============================================================
print("\n=== GRID 5: ATR × TP Cross ===")
grid5 = []
for atr in [0.086, 0.0865, 0.087, 0.0875, 0.088]:
    for tp in [2.65, 2.7, 2.75, 2.8]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_ATR{atr}_{dip}_TP{tp}_MHD7"
            buy = dip_buy(dip, atr_thresh=atr)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid5.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 5: {len(grid5)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid5):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
    if (i+1) % 10 == 0: print(f"  Progress: {i+1}/{len(grid5)}")
print(f"Grid 5 done")

# ============================================================
# GRID 6: Champion Fine-Tune (ATR0.087, TP2.7, DIP+MHD variants)
# Goal: Optimize the champion neighborhood
# ============================================================
print("\n=== GRID 6: Champion Fine-Tune ===")
grid6 = []
for dip in [-2.8, -2.9, -3.0, -3.1]:
    for mhd in [5, 7, 10]:
        for sell_name, sell_conds in [('aR2vF2', aR2vF2), ('aR3vF2', aR3vF2)]:
            name = f"RSI18_ATR0.087_{sell_name}_DIP{dip}_TP2.7_MHD{mhd}_champion"
            buy = dip_buy(dip)
            exit_cfg = {'take_profit_pct':2.7, 'stop_loss_pct':-10, 'max_hold_days':mhd}
            grid6.append((name, buy, sell_conds, exit_cfg))

print(f"Grid 6: {len(grid6)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid6):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 6 done")

# ============================================================
# SUMMARY
# ============================================================
total_time = time.time() - t0
valid = len(all_results)
stda = sum(1 for r in all_results.values() if r['stda'])
print(f"\n{'='*60}")
print(f"R541 COMPLETE: {valid} valid configs, {stda} StdA+ ({100*stda/max(valid,1):.1f}%)")
print(f"Total time: {total_time/60:.1f} min")

# Top 10 by score
top10 = sorted(all_results.values(), key=lambda x: x['score'], reverse=True)[:10]
print(f"\nTop 10:")
for i, r in enumerate(top10):
    flag = "★" if r['stda'] else " "
    print(f"  {i+1}. {flag} {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, trades={r['trades']}")

# TP boundary analysis
print(f"\n--- TP Boundary Analysis ---")
for tp in [2.65, 2.7, 2.75, 2.8, 2.85]:
    tp_str = str(tp)
    matches = [r for r in all_results.values() if f'_TP{tp_str}_' in r['name'] or r['name'].endswith(f'_TP{tp_str}')]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        best = max(matches, key=lambda x: x['score'])
        print(f"  TP{tp}: {stda_count}/{len(matches)} StdA+, avg wr={avg_wr:.1f}%, best={best['score']} ({best['name'][:60]})")

# Sell analysis at TP2.7
print(f"\n--- Sell Analysis at TP2.7 ---")
for sell_name in ['aR2vF2', 'aR3vF2', 'vF2only']:
    matches = [r for r in all_results.values() if sell_name in r['name'] and '_TP2.7_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  {sell_name}: {stda_count}/{len(matches)} StdA+, best={best['score']} ({best['name'][:60]})")

# MHD analysis at TP2.7
print(f"\n--- MHD Analysis at TP2.7 ---")
for mhd in [3, 5, 7, 10, 14]:
    matches = [r for r in all_results.values() if f'_MHD{mhd}' in r['name'] and '_TP2.7_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  MHD{mhd}: {stda_count}/{len(matches)} StdA+, best={best['score']}")

# RSI analysis at TP2.7
print(f"\n--- RSI Analysis at TP2.7 ---")
for rsi in [15, 16, 17, 18, 19, 20]:
    matches = [r for r in all_results.values() if f'RSI{rsi}_' in r['name'] and '_TP2.7_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  RSI{rsi}: {stda_count}/{len(matches)} StdA+, best={best['score']}")

# ATR×TP cross analysis
print(f"\n--- ATR × TP Cross ---")
for atr in [0.086, 0.0865, 0.087, 0.0875, 0.088]:
    matches = [r for r in all_results.values() if f'ATR{atr}_' in r['name'] and 'RSI18_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  ATR{atr}: {stda_count}/{len(matches)} StdA+, best={best['score']}")

# Save results
with open('/tmp/r541_results.json', 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/r541_results.json")
