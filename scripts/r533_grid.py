#!/usr/bin/env python3
"""R533: RSI21+B50-75, ATR0.10-0.11 wide band, DIP+B50-75, sell variants, RSI+BOLL%B, RSI+ULCER."""
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

# === Common sell conditions ===
aR2vF2 = [
    {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':2},
    {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
]

def dip_buy(dip, rsi_lb, rsi_ub, rsi_period=14, atr_thresh=0.09):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
    ]

all_results = {}

# ============================================================
# GRID 1: RSI21 + B50-75 (untested combo from R532 suggestion)
# ============================================================
print("\n" + "="*60)
print("GRID 1: RSI21 + B50-75 Sweep")
print("="*60)
results = []
for dip in [-2.7, -2.8, -2.9, -3.0]:
    for tp in [1.5, 2.0, 2.3, 2.5]:
        for mhd in [5, 7]:
            buy = dip_buy(dip, 50, 75, rsi_period=21)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'RSI21_B50-75_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI21 B50-75 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
all_results['rsi21_b5075'] = results

# ============================================================
# GRID 2: ATR0.10-0.11 + wider RSI bands (higher return targets)
# ============================================================
print("\n" + "="*60)
print("GRID 2: ATR0.10-0.11 Wide Band")
print("="*60)
results = []
for atr_thresh in [0.10, 0.11]:
    for rsi_lb, rsi_ub in [(45, 75), (50, 75), (50, 80), (55, 75)]:
        for dip in [-2.9, -3.0]:
            for tp in [2.0, 2.3]:
                buy = dip_buy(dip, rsi_lb, rsi_ub, rsi_period=14, atr_thresh=atr_thresh)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
                name = f'ATR{atr_thresh}_B{rsi_lb}-{rsi_ub}_DIP{dip}_TP{tp}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- ATR0.10-0.11 Wide Band Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
all_results['atr_wide'] = results

# ============================================================
# GRID 3: DIP sweep + RSI50-75 band (R530 used B50-70)
# ============================================================
print("\n" + "="*60)
print("GRID 3: DIP Sweep with B50-75")
print("="*60)
results = []
for dip in [-2.5, -2.6, -2.7, -2.8, -2.9, -3.0, -3.1, -3.2]:
    for tp in [2.0, 2.3]:
        for mhd in [5, 7]:
            buy = dip_buy(dip, 50, 75, rsi_period=14)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'B5075_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- B50-75 DIP Sweep Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    for dip in [-2.5, -2.6, -2.7, -2.8, -2.9, -3.0, -3.1, -3.2]:
        dr = [r for r in results if f'DIP{dip}_' in r['name']]
        if dr:
            ds = sum(1 for r in dr if r['stda'])
            db = max(dr, key=lambda x: x['score'])
            print(f"  DIP{dip}: {ds} StdA+, best sc={db['score']} wr={db['wr']}%")
all_results['b5075_dip'] = results

# ============================================================
# GRID 4: Sell Condition Variants
# ============================================================
print("\n" + "="*60)
print("GRID 4: Sell Condition Variants")
print("="*60)
results = []

# Different sell conditions to test
sell_variants = {
    'aR2vF2': aR2vF2,  # baseline
    'aR3vF2': [  # ATR rising 3 days (stricter sell)
        {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':3},
        {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
    ],
    'aR2vF3': [  # Volume falling 3 days (stricter sell)
        {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':2},
        {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':3}
    ],
    'aR2only': [  # ATR rising 2 only (no volume)
        {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':2},
    ],
    'vF2only': [  # Volume falling 2 only (no ATR)
        {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
    ],
    'closeF2': [  # Close falling 2 days
        {'field':'close','params':{},'operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
    ],
}

for sell_name, sell_conds in sell_variants.items():
    for dip in [-2.9, -3.0]:
        for tp in [2.0, 2.3]:
            for rsi_ub in [70, 75]:
                buy = dip_buy(dip, 50, rsi_ub, rsi_period=14)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
                name = f'SELL_{sell_name}_B50-{rsi_ub}_DIP{dip}_TP{tp}'
                r = run_bt(name, buy, sell_conds, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Sell Variants Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for sv in sell_variants:
    sv_results = [r for r in results if f'SELL_{sv}_' in r['name']]
    if sv_results:
        sv_stda = sum(1 for r in sv_results if r['stda'])
        sv_best = max(sv_results, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in sv_results)/len(sv_results)
        print(f"  {sv}: {len(sv_results)} valid, {sv_stda} StdA+, best sc={sv_best['score']}, avg wr={avg_wr:.1f}%")
all_results['sell_variants'] = results

# ============================================================
# GRID 5: RSI + BOLL%B Filter (cross-family portfolio test)
# ============================================================
print("\n" + "="*60)
print("GRID 5: RSI + BOLL%B Filter")
print("="*60)
results = []

for boll_pctb_thresh in [0.1, 0.2, 0.3]:
    for dip in [-2.9, -3.0]:
        for tp in [1.5, 2.0, 2.3, 2.5]:
            for mhd in [5, 7]:
                buy = [
                    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':50},
                    {'field':'RSI','params':{'period':14},'operator':'<','compare_type':'value','compare_value':75},
                    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.09},
                    {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                    {'field':'BOLL_pctb','params':{'length':20,'std':2},'operator':'<','compare_type':'value','compare_value':boll_pctb_thresh},
                ]
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'BOLL_pctb{boll_pctb_thresh}_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")
                else:
                    print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- BOLL%B Filter Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for pctb in [0.1, 0.2, 0.3]:
    pr = [r for r in results if f'pctb{pctb}_' in r['name']]
    if pr:
        ps = sum(1 for r in pr if r['stda'])
        pb = max(pr, key=lambda x: x['score'])
        print(f"  BOLL_pctb<{pctb}: {len(pr)} valid, {ps} StdA+, best sc={pb['score']} ret={pb['ret']}% wr={pb['wr']}%")
all_results['boll_pctb'] = results

# ============================================================
# GRID 6: RSI + ULCER Filter (cross-family portfolio test)
# ============================================================
print("\n" + "="*60)
print("GRID 6: RSI + ULCER Filter")
print("="*60)
results = []

for ulcer_thresh in [3, 5, 7]:
    for dip in [-2.9, -3.0]:
        for tp in [1.5, 2.0, 2.3, 2.5]:
            for mhd in [5, 7]:
                buy = [
                    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':50},
                    {'field':'RSI','params':{'period':14},'operator':'<','compare_type':'value','compare_value':75},
                    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.09},
                    {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                    {'field':'ULCER','params':{'length':14},'operator':'<','compare_type':'value','compare_value':ulcer_thresh},
                ]
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'ULCER{ulcer_thresh}_DIP{dip}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")
                else:
                    print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- ULCER Filter Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for ul in [3, 5, 7]:
    ur = [r for r in results if f'ULCER{ul}_' in r['name']]
    if ur:
        us = sum(1 for r in ur if r['stda'])
        ub = max(ur, key=lambda x: x['score'])
        print(f"  ULCER<{ul}: {len(ur)} valid, {us} StdA+, best sc={ub['score']} ret={ub['ret']}% wr={ub['wr']}%")
all_results['ulcer'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R533 FINAL SUMMARY")
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

with open('/tmp/r533_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r533_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
