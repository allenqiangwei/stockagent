#!/usr/bin/env python3
"""R531: DIP-BUY sensitivity analysis — slippage, MHD fine-grain, RSI period, capital."""
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

# === Common conditions ===
aR2vF2 = [
    {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':2},
    {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
]

def dip_buy(dip, rsi_lb, rsi_ub, rsi_period=14):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.09},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
    ]

all_results = {}

# ============================================================
# GRID 1: Slippage Sensitivity (champion config with varying slippage)
# ============================================================
print("\n" + "="*60)
print("GRID 1: Slippage Sensitivity")
print("="*60)
results = []
# Test champion (DIP-2.9 RSI50-70 TP2.3 MHD7) + top configs at different slippage levels
configs = [
    (-2.9, 50, 70, 2.3, 7),
    (-2.9, 50, 70, 2.0, 7),
    (-2.9, 50, 70, 1.5, 7),
    (-3.0, 50, 70, 2.0, 7),
    (-2.6, 50, 70, 2.0, 3),
    (-2.8, 50, 70, 2.0, 7),
]
for slip_pct in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3]:
    for dip, rsi_lb, rsi_ub, tp, mhd in configs:
        buy = dip_buy(dip, rsi_lb, rsi_ub)
        exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
        name = f'SLIP{slip_pct:.2f}_DIP{dip}_TP{tp}_MHD{mhd}'
        r = run_bt(name, buy, aR2vF2, exit_cfg, slippage_pct=slip_pct)
        if r:
            results.append(r)
            tag = ' *** StdA+ ***' if r['stda'] else ''
            print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

print(f"\n--- Slippage Summary ---")
print(f"Total: {len(results)} valid")
for slip_pct in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3]:
    slip_results = [r for r in results if r['name'].startswith(f'SLIP{slip_pct:.2f}')]
    stda = sum(1 for r in slip_results if r['stda'])
    if slip_results:
        best = max(slip_results, key=lambda x: x['score'])
        print(f"  Slippage {slip_pct:.2f}%: {stda}/6 StdA+, best={best['name']} sc={best['score']} wr={best['wr']}%")
all_results['slippage'] = results

# ============================================================
# GRID 2: MHD Fine-Grain
# ============================================================
print("\n" + "="*60)
print("GRID 2: MHD Fine-Grain (MHD 1-10)")
print("="*60)
results = []
for dip in [-2.9, -3.0]:
    for tp in [1.5, 2.0, 2.3]:
        for mhd in [1, 2, 3, 4, 5, 6, 7, 8, 10]:
            buy = dip_buy(dip, 50, 70)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- MHD Fine-Grain Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    for mhd in [1, 2, 3, 4, 5, 6, 7, 8, 10]:
        mhd_results = [r for r in results if f'_MHD{mhd}' in r['name'] and not r['name'].endswith(f'MHD{mhd}0')]
        if mhd_results:
            mhd_stda = sum(1 for r in mhd_results if r['stda'])
            best_mhd = max(mhd_results, key=lambda x: x['score'])
            print(f"  MHD{mhd}: {mhd_stda} StdA+, best sc={best_mhd['score']} wr={best_mhd['wr']}%")
all_results['mhd'] = results

# ============================================================
# GRID 3: RSI Period Variants
# ============================================================
print("\n" + "="*60)
print("GRID 3: RSI Period Variants")
print("="*60)
results = []
for rsi_p in [7, 10, 14, 21, 28]:
    for dip in [-2.9, -3.0]:
        for tp in [1.5, 2.0, 2.3]:
            for mhd in [5, 7]:
                buy = dip_buy(dip, 50, 70, rsi_period=rsi_p)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'RSI{rsi_p}_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")
                else:
                    print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI Period Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for rsi_p in [7, 10, 14, 21, 28]:
    rp = [r for r in results if r['name'].startswith(f'RSI{rsi_p}_')]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        print(f"  RSI{rsi_p}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']} wr={best_rp['wr']}%")
all_results['rsi_period'] = results

# ============================================================
# GRID 4: Capital Sensitivity
# ============================================================
print("\n" + "="*60)
print("GRID 4: Capital Sensitivity")
print("="*60)
results = []
for capital in [50000, 100000, 200000, 500000, 1000000]:
    for dip, tp, mhd in [(-2.9, 2.3, 7), (-2.9, 2.0, 7), (-3.0, 2.0, 7)]:
        buy = dip_buy(dip, 50, 70)
        exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
        name = f'CAP{capital//1000}k_DIP{dip}_TP{tp}_MHD{mhd}'
        r = run_bt(name, buy, aR2vF2, exit_cfg, initial_capital=capital)
        if r:
            results.append(r)
            tag = ' *** StdA+ ***' if r['stda'] else ''
            print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

print(f"\n--- Capital Summary ---")
print(f"Total: {len(results)} valid")
for cap in [50000, 100000, 200000, 500000, 1000000]:
    cap_results = [r for r in results if r['name'].startswith(f'CAP{cap//1000}k_')]
    if cap_results:
        cap_stda = sum(1 for r in cap_results if r['stda'])
        best_cap = max(cap_results, key=lambda x: x['score'])
        print(f"  {cap//1000}k: {cap_stda}/3 StdA+, best sc={best_cap['score']} wr={best_cap['wr']}%")
all_results['capital'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R531 FINAL SUMMARY")
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

with open('/tmp/r531_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r531_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
