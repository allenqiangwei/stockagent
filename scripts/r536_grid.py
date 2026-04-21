#!/usr/bin/env python3
"""R536: RSI19-22 period extension, ULCER<11+RSI18, TP fine sweep 2.1-2.6, aR2vF2 deep RSI18, MHD sweep."""
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

def dip_buy_ulcer(dip, rsi_lb, rsi_ub, rsi_period=14, atr_thresh=0.09, ulcer_thresh=7):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
        {'field':'ULCER','params':{'length':14},'operator':'<','compare_type':'value','compare_value':ulcer_thresh},
    ]

all_results = {}

# ============================================================
# GRID 1: RSI Period Extension (19, 20, 21, 22) — does score keep increasing?
# R535 showed RSI14→18 monotonically increases. Test RSI19-22.
# 4 periods x 3 dips x 2 TPs x 2 MHDs = 48 configs
# ============================================================
print("\n" + "="*60)
print("GRID 1: RSI Period Extension (19, 20, 21, 22)")
print("="*60)
results = []
for rsi_p in [19, 20, 21, 22]:
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
print(f"\n--- RSI Period Extension Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for rsi_p in [19, 20, 21, 22]:
    rp = [r for r in results if r['name'].startswith(f'RSI{rsi_p}_')]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        avg_dd = sum(r['dd'] for r in rp)/len(rp)
        print(f"  RSI{rsi_p}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, avg dd={avg_dd:.1f}%")
all_results['rsi_extension'] = results

# ============================================================
# GRID 2: ULCER<11 + RSI18 Combined Deep Grid
# R535 found ULCER<11 optimal. Combine with RSI18.
# 5 dips x 3 TPs x 2 MHDs = 30 configs
# ============================================================
print("\n" + "="*60)
print("GRID 2: ULCER<11 + RSI18 Combined Deep Grid")
print("="*60)
results = []
for dip in [-2.7, -2.8, -2.9, -3.0, -3.1]:
    for tp in [1.5, 2.0, 2.3]:
        for mhd in [5, 7]:
            buy = dip_buy_ulcer(dip, 50, 75, rsi_period=18, ulcer_thresh=11)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'ULCER11_RSI18_B5075_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")
            else:
                print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- ULCER<11 + RSI18 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
all_results['ulcer11_rsi18'] = results

# ============================================================
# GRID 3: TP Fine Sweep (2.1, 2.2, 2.3, 2.4, 2.5, 2.6) with RSI18
# TP2.3 is StdA+ optimal, TP2.5 crosses wr<60%. Find the exact boundary.
# 6 TPs x 3 dips x 2 sells x 2 MHDs = 72 configs
# ============================================================
print("\n" + "="*60)
print("GRID 3: TP Fine Sweep (2.1-2.6) with RSI18")
print("="*60)
results = []
sell_map = {'aR2vF2': aR2vF2, 'aR3vF2': aR3vF2}
for tp in [2.1, 2.2, 2.3, 2.4, 2.5, 2.6]:
    for dip in [-2.8, -2.9, -3.0]:
        for sell_name, sell_conds in sell_map.items():
            for mhd in [5, 7]:
                buy = dip_buy(dip, 50, 75, rsi_period=18)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'RSI18_{sell_name}_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, sell_conds, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- TP Fine Sweep Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for tp in [2.1, 2.2, 2.3, 2.4, 2.5, 2.6]:
    tp_results = [r for r in results if f'_TP{tp}_' in r['name']]
    if tp_results:
        tp_stda = sum(1 for r in tp_results if r['stda'])
        best_tp = max(tp_results, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in tp_results)/len(tp_results)
        print(f"  TP{tp}: {len(tp_results)} valid, {tp_stda} StdA+, best sc={best_tp['score']}, avg wr={avg_wr:.1f}%")
all_results['tp_fine_sweep'] = results

# ============================================================
# GRID 4: aR2vF2 Deep Grid with RSI18 (raw record holder)
# aR2vF2 + RSI18 = 0.8561 raw record. Explore wider parameter space.
# 6 dips x 4 TPs x 3 MHDs = 72 configs
# ============================================================
print("\n" + "="*60)
print("GRID 4: aR2vF2 Deep Grid with RSI18")
print("="*60)
results = []
for dip in [-2.6, -2.7, -2.8, -2.9, -3.0, -3.1]:
    for tp in [1.5, 2.0, 2.3, 2.5]:
        for mhd in [3, 5, 7]:
            buy = dip_buy(dip, 50, 75, rsi_period=18)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'aR2vF2_RSI18_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- aR2vF2 Deep RSI18 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for dip in [-2.6, -2.7, -2.8, -2.9, -3.0, -3.1]:
    d_results = [r for r in results if f'DIP{dip}_' in r['name']]
    if d_results:
        d_stda = sum(1 for r in d_results if r['stda'])
        best_d = max(d_results, key=lambda x: x['score'])
        print(f"  DIP{dip}: {len(d_results)} valid, {d_stda} StdA+, best sc={best_d['score']} ret={best_d['ret']}%")
for mhd in [3, 5, 7]:
    m_results = [r for r in results if r['name'].endswith(f'_MHD{mhd}')]
    if m_results:
        m_stda = sum(1 for r in m_results if r['stda'])
        best_m = max(m_results, key=lambda x: x['score'])
        avg_dd = sum(r['dd'] for r in m_results)/len(m_results)
        print(f"  MHD{mhd}: {len(m_results)} valid, {m_stda} StdA+, best sc={best_m['score']}, avg dd={avg_dd:.1f}%")
all_results['ar2vf2_deep_rsi18'] = results

# ============================================================
# GRID 5: RSI18 + RSI Band Variants (45-75, 50-80, 55-75)
# R532 found B50-75 >> B50-70. But what about B45-75 and B55-75 with RSI18?
# 3 bands x 3 dips x 2 TPs x 2 MHDs = 36 configs
# ============================================================
print("\n" + "="*60)
print("GRID 5: RSI18 Band Variants (45-75, 50-80, 55-75)")
print("="*60)
results = []
bands = [(45, 75), (50, 80), (55, 75)]
for lb, ub in bands:
    for dip in [-2.8, -2.9, -3.0]:
        for tp in [2.0, 2.3]:
            for mhd in [5, 7]:
                buy = dip_buy(dip, lb, ub, rsi_period=18)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'RSI18_B{lb}{ub}_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI Band Variants Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for lb, ub in bands:
    b_results = [r for r in results if f'B{lb}{ub}' in r['name']]
    if b_results:
        b_stda = sum(1 for r in b_results if r['stda'])
        best_b = max(b_results, key=lambda x: x['score'])
        avg_dd = sum(r['dd'] for r in b_results)/len(b_results)
        print(f"  B{lb}-{ub}: {len(b_results)} valid, {b_stda} StdA+, best sc={best_b['score']}, avg dd={avg_dd:.1f}%")
all_results['rsi18_bands'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R536 FINAL SUMMARY")
print("="*60)
total_configs = sum(len(v) for v in all_results.values())
total_stda = sum(sum(1 for r in v if r['stda']) for v in all_results.values())
print(f"Total valid configs: {total_configs}")
print(f"Total StdA+: {total_stda}")

all_flat = []
for v in all_results.values():
    all_flat.extend(v)
if all_flat:
    top20 = sorted(all_flat, key=lambda x: x['score'], reverse=True)[:20]
    print("\nOverall Top 20:")
    for i, r in enumerate(top20, 1):
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {i}. {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")

with open('/tmp/r536_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r536_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
