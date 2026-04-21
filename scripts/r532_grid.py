#!/usr/bin/env python3
"""R532: RSI21 DIP-BUY deep grid + PSAR strict ATR + DIP threshold fine-tuning."""
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
# GRID 1: RSI21 Deep DIP-BUY Grid
# ============================================================
print("\n" + "="*60)
print("GRID 1: RSI21 Deep DIP-BUY Grid")
print("="*60)
results = []
for dip in [-2.5, -2.6, -2.7, -2.8, -2.9, -3.0, -3.1, -3.2]:
    for tp in [1.5, 2.0, 2.3, 2.5]:
        for mhd in [3, 5, 6, 7]:
            buy = dip_buy(dip, 50, 70, rsi_period=21)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'RSI21_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI21 DIP-BUY Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    for dip in [-2.5, -2.6, -2.7, -2.8, -2.9, -3.0, -3.1, -3.2]:
        dip_results = [r for r in results if f'DIP{dip}_' in r['name']]
        if dip_results:
            dip_stda = sum(1 for r in dip_results if r['stda'])
            best_dip = max(dip_results, key=lambda x: x['score'])
            print(f"  DIP{dip}: {dip_stda} StdA+, best sc={best_dip['score']} wr={best_dip['wr']}%")
all_results['rsi21_dip'] = results

# ============================================================
# GRID 2: RSI21 vs RSI14 Head-to-Head (matched configs)
# ============================================================
print("\n" + "="*60)
print("GRID 2: RSI21 vs RSI14 Head-to-Head")
print("="*60)
results = []
for rsi_p in [14, 21]:
    for dip in [-2.7, -2.8, -2.9, -3.0]:
        for rsi_lb, rsi_ub in [(45, 70), (50, 70), (50, 75), (55, 70)]:
            for tp in [2.0, 2.3]:
                buy = dip_buy(dip, rsi_lb, rsi_ub, rsi_period=rsi_p)
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
                name = f'RSI{rsi_p}_DIP{dip}_B{rsi_lb}-{rsi_ub}_TP{tp}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI21 vs RSI14 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for rsi_p in [14, 21]:
    rp = [r for r in results if r['name'].startswith(f'RSI{rsi_p}_')]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        avg_dd = sum(r['dd'] for r in rp)/len(rp)
        print(f"  RSI{rsi_p}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, avg dd={avg_dd:.1f}%")
all_results['rsi_head2head'] = results

# ============================================================
# GRID 3: PSAR Strict ATR Configs (trying to tame the return monster)
# ============================================================
print("\n" + "="*60)
print("GRID 3: PSAR Strict ATR (lower ATR = lower risk)")
print("="*60)
results = []

psar_buy = [
    {'field':'PSAR','params':{'af':0.02,'max_af':0.2},'operator':'<','compare_type':'field','compare_field':'close'},
    {'field':'MACD_hist','params':{'fast':12,'slow':26,'signal':9},'operator':'>','compare_type':'value','compare_value':0},
    {'field':'KDJ_K','params':{'k':9,'d':3,'smooth':3},'operator':'>','compare_type':'field','compare_field':'KDJ_D','compare_field_params':{'k':9,'d':3,'smooth':3}},
]
psar_sell = [
    {'field':'PSAR','params':{'af':0.02,'max_af':0.2},'operator':'>','compare_type':'field','compare_field':'close'},
]

for atr_thresh in [0.04, 0.05, 0.06, 0.07]:
    for tp in [0.5, 1.0, 1.5, 2.0]:
        for mhd in [3, 5]:
            buy = psar_buy + [{'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh}]
            exit_cfg = {'stop_loss_pct':-10, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'PSAR_ATR{atr_thresh}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, psar_sell, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")
            else:
                print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- PSAR Strict ATR Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for atr in [0.04, 0.05, 0.06, 0.07]:
    atr_results = [r for r in results if f'ATR{atr}' in r['name']]
    if atr_results:
        atr_stda = sum(1 for r in atr_results if r['stda'])
        best_atr = max(atr_results, key=lambda x: x['score'])
        print(f"  ATR{atr}: {len(atr_results)} valid, {atr_stda} StdA+, best sc={best_atr['score']} ret={best_atr['ret']}% dd={best_atr['dd']}%")
all_results['psar_strict'] = results

# ============================================================
# GRID 4: DIP-BUY ATR Threshold Optimization
# ============================================================
print("\n" + "="*60)
print("GRID 4: DIP-BUY ATR Threshold (0.06-0.12)")
print("="*60)
results = []
for atr_thresh in [0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12]:
    for dip in [-2.9, -3.0]:
        for tp in [2.0, 2.3]:
            buy = dip_buy(dip, 50, 70, rsi_period=14, atr_thresh=atr_thresh)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
            name = f'ATR{atr_thresh}_DIP{dip}_TP{tp}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']}{tag}")
            else:
                print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- ATR Threshold Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for atr in [0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12]:
    atr_results = [r for r in results if r['name'].startswith(f'ATR{atr}_')]
    if atr_results:
        atr_stda = sum(1 for r in atr_results if r['stda'])
        best_atr = max(atr_results, key=lambda x: x['score'])
        print(f"  ATR{atr}: {len(atr_results)} valid, {atr_stda} StdA+, best sc={best_atr['score']} ret={best_atr['ret']}% tr={best_atr['trades']}")
all_results['atr_threshold'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R532 FINAL SUMMARY")
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

with open('/tmp/r532_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r532_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
