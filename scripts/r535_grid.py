#!/usr/bin/env python3
"""R535: RSI18 deep exploration — aR3vF2, fine RSI period (15-17), ULCER<9 combo, sell H2H, DIP sweep."""
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

# === Sell conditions ===
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

def dip_buy(dip, rsi_lb, rsi_ub, rsi_period=14, atr_thresh=0.09):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
    ]

def dip_buy_ulcer(dip, rsi_lb, rsi_ub, rsi_period=14, atr_thresh=0.09, ulcer_thresh=9):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
        {'field':'ULCER','params':{'length':14},'operator':'<','compare_type':'value','compare_value':ulcer_thresh},
    ]

all_results = {}

# ============================================================
# GRID 1: RSI18 + aR3vF2 Deep Grid (best period + best sell)
# ============================================================
print("\n" + "="*60)
print("GRID 1: RSI18 + aR3vF2 Deep Grid")
print("="*60)
results = []
for dip in [-2.6, -2.7, -2.8, -2.9, -3.0, -3.1]:
    for tp in [1.5, 2.0, 2.3, 2.5]:
        for mhd in [5, 7]:
            buy = dip_buy(dip, 50, 75, rsi_period=18)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'RSI18_aR3vF2_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR3vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI18 + aR3vF2 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
all_results['rsi18_ar3vf2'] = results

# ============================================================
# GRID 2: Fine RSI Period Sweep (15, 16, 17) vs 14 and 18
# ============================================================
print("\n" + "="*60)
print("GRID 2: Fine RSI Period Sweep (15, 16, 17) vs 14, 18")
print("="*60)
results = []
for rsi_p in [14, 15, 16, 17, 18]:
    for dip in [-2.8, -2.9, -3.0]:
        for tp in [2.0, 2.3]:
            for mhd in [5, 7]:
                buy = dip_buy(dip, 50, 75, rsi_period=rsi_p)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'RSI{rsi_p}_B5075_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Fine RSI Period Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for rsi_p in [14, 15, 16, 17, 18]:
    rp = [r for r in results if r['name'].startswith(f'RSI{rsi_p}_')]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        avg_dd = sum(r['dd'] for r in rp)/len(rp)
        avg_wr = sum(r['wr'] for r in rp)/len(rp)
        print(f"  RSI{rsi_p}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, avg dd={avg_dd:.1f}%, avg wr={avg_wr:.1f}%")
all_results['fine_rsi_period'] = results

# ============================================================
# GRID 3: RSI18 + ULCER<9 Combo
# ============================================================
print("\n" + "="*60)
print("GRID 3: RSI18 + ULCER<9 Combo")
print("="*60)
results = []
for ulcer_t in [7, 9, 11]:
    for dip in [-2.7, -2.8, -2.9, -3.0]:
        for tp in [1.5, 2.0, 2.3]:
            for mhd in [5, 7]:
                buy = dip_buy_ulcer(dip, 50, 75, rsi_period=18, ulcer_thresh=ulcer_t)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'RSI18_ULCER{ulcer_t}_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")
                else:
                    print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI18 + ULCER Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for ut in [7, 9, 11]:
    u_results = [r for r in results if f'ULCER{ut}_' in r['name']]
    if u_results:
        u_stda = sum(1 for r in u_results if r['stda'])
        best_u = max(u_results, key=lambda x: x['score'])
        avg_dd = sum(r['dd'] for r in u_results)/len(u_results)
        print(f"  ULCER<{ut}: {len(u_results)} valid, {u_stda} StdA+, best sc={best_u['score']}, avg dd={avg_dd:.1f}%")
all_results['rsi18_ulcer'] = results

# ============================================================
# GRID 4: RSI18 + 3-Sell H2H (wider parameter space)
# ============================================================
print("\n" + "="*60)
print("GRID 4: RSI18 + 3-Sell Head-to-Head")
print("="*60)
results = []
sell_map = {'aR2vF2': aR2vF2, 'aR3vF2': aR3vF2, 'vF2only': vF2only}
for sell_name, sell_conds in sell_map.items():
    for dip in [-2.7, -2.8, -2.9, -3.0]:
        for tp in [1.5, 2.0, 2.3, 2.5]:
            buy = dip_buy(dip, 50, 75, rsi_period=18)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
            name = f'{sell_name}_RSI18_DIP{dip}_TP{tp}'
            r = run_bt(name, buy, sell_conds, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI18 3-Sell H2H Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for sell_name in ['aR2vF2', 'aR3vF2', 'vF2only']:
    s_results = [r for r in results if r['name'].startswith(f'{sell_name}_')]
    if s_results:
        s_stda = sum(1 for r in s_results if r['stda'])
        best_s = max(s_results, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in s_results)/len(s_results)
        print(f"  {sell_name}: {len(s_results)} valid, {s_stda} StdA+, best sc={best_s['score']}, avg wr={avg_wr:.1f}%")
all_results['rsi18_sell_h2h'] = results

# ============================================================
# GRID 5: RSI18 DIP Fine Sweep (-2.5 to -3.3, step 0.1)
# ============================================================
print("\n" + "="*60)
print("GRID 5: RSI18 DIP Fine Sweep (-2.5 to -3.3)")
print("="*60)
results = []
for dip_x10 in range(-25, -34, -1):  # -2.5 to -3.3
    dip = dip_x10 / 10.0
    for tp in [2.0, 2.3]:
        for mhd in [5, 7]:
            buy = dip_buy(dip, 50, 75, rsi_period=18)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'RSI18_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI18 DIP Fine Sweep Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for dip_x10 in range(-25, -34, -1):
    dip = dip_x10 / 10.0
    d_results = [r for r in results if f'DIP{dip}_' in r['name']]
    if d_results:
        d_stda = sum(1 for r in d_results if r['stda'])
        best_d = max(d_results, key=lambda x: x['score'])
        print(f"  DIP{dip}: {len(d_results)} valid, {d_stda} StdA+, best sc={best_d['score']} ret={best_d['ret']}%")
all_results['rsi18_dip_sweep'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R535 FINAL SUMMARY")
print("="*60)
total_configs = sum(len(v) for v in all_results.values())
total_stda = sum(sum(1 for r in v if r['stda']) for v in all_results.values())
print(f"Total valid configs: {total_configs}")
print(f"Total StdA+: {total_stda}")

all_flat = []
for v in all_results.values():
    all_flat.extend(v)
if all_flat:
    top15 = sorted(all_flat, key=lambda x: x['score'], reverse=True)[:15]
    print("\nOverall Top 15:")
    for i, r in enumerate(top15, 1):
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {i}. {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")

with open('/tmp/r535_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r535_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
