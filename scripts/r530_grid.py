#!/usr/bin/env python3
"""R530: Fine-grain DIP-BUY optimization + PSAR+MACD+KDJ+ATR + DIP noSell variants."""
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

def run_bt(name, buy_conds, sell_conds, exit_cfg, max_pos=10):
    strat = {'name':name,'buy_conditions':buy_conds,'sell_conditions':sell_conds,'exit_config':exit_cfg,
             'portfolio_config':{'max_positions':max_pos,'max_position_pct':30}}
    eng = PortfolioBacktestEngine(initial_capital=100000,max_positions=max_pos,max_position_pct=30)
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

all_results = {}

# ============================================================
# GRID 1: Fine-grain DIP threshold (-2.5 to -3.5, 0.1 step)
# with best RSI band (50-70) and TP (1.5, 2.0, 2.5) × MHD (3,5,7)
# ============================================================
print("\n" + "="*60)
print("GRID 1: Fine-grain DIP threshold (-2.5 to -3.5)")
print("="*60)
results = []
count = 0
for dip_10x in range(-25, -36, -1):  # -2.5, -2.6, ..., -3.5
    dip = dip_10x / 10.0
    for rsi_lb, rsi_ub in [(50, 70), (50, 66)]:
        for tp in [1.5, 1.7, 2.0, 2.3, 2.5]:
            for mhd in [3, 5, 7]:
                count += 1
                buy = [
                    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':rsi_lb},
                    {'field':'RSI','params':{'period':14},'operator':'<','compare_type':'value','compare_value':rsi_ub},
                    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.09},
                    {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                ]
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'DIP{dip}_RSI{rsi_lb}-{rsi_ub}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    if count % 30 == 0 or r['stda']:
                        print(f"  [{count}] {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Fine DIP Grid Summary ---")
print(f"Total: {len(results)} valid / {count} total, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    # Best StdA+
    stda_results = [r for r in results if r['stda']]
    if stda_results:
        best_stda = max(stda_results, key=lambda x: x['score'])
        print(f"Best StdA+: {best_stda['name']} sc={best_stda['score']} ret={best_stda['ret']}% dd={best_stda['dd']}% wr={best_stda['wr']}%")
    top10 = sorted(results, key=lambda x: x['score'], reverse=True)[:10]
    print("Top 10:")
    for r in top10:
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")
all_results['fine_dip'] = results

# ============================================================
# GRID 2: DIP-BUY noSell variants (best DIP thresholds × noSell × TP × MHD)
# ============================================================
print("\n" + "="*60)
print("GRID 2: DIP-BUY noSell variants")
print("="*60)
results = []
count = 0
for dip in [-2.5, -2.8, -3.0, -3.2]:
    for rsi_lb, rsi_ub in [(50, 70), (50, 66)]:
        for tp in [0.5, 1.0, 1.5, 2.0, 2.5]:
            for mhd in [3, 5, 7]:
                count += 1
                buy = [
                    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':rsi_lb},
                    {'field':'RSI','params':{'period':14},'operator':'<','compare_type':'value','compare_value':rsi_ub},
                    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.09},
                    {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                ]
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'DIP{dip}_RSI{rsi_lb}-{rsi_ub}_noSell_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, [], exit_cfg)  # noSell = empty sell_conditions
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    if count % 30 == 0 or r['stda']:
                        print(f"  [{count}] {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- DIP noSell Summary ---")
print(f"Total: {len(results)} valid / {count} total, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    stda_results = [r for r in results if r['stda']]
    if stda_results:
        best_stda = max(stda_results, key=lambda x: x['score'])
        print(f"Best StdA+: {best_stda['name']} sc={best_stda['score']} ret={best_stda['ret']}% wr={best_stda['wr']}%")
    # Show highest wr
    best_wr = max(results, key=lambda x: x['wr'])
    print(f"Highest WR: {best_wr['name']} wr={best_wr['wr']}% sc={best_wr['score']}")
    top10 = sorted(results, key=lambda x: x['score'], reverse=True)[:10]
    print("Top 10:")
    for r in top10:
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")
all_results['nosell'] = results

# ============================================================
# GRID 3: PSAR+MACD+KDJ+ATR (fix signal explosion with ATR filter)
# ============================================================
print("\n" + "="*60)
print("GRID 3: PSAR+MACD+KDJ+ATR (fix signal explosion)")
print("="*60)
results = []
count = 0
for atr_thresh in [0.06, 0.08, 0.09, 0.10]:
    for tp in [1.0, 1.5, 2.0, 2.5]:
        for mhd in [3, 5]:
            for sell_type, sell_conds in [('aR2vF2', aR2vF2), ('noSell', [])]:
                count += 1
                buy = [
                    {'field':'close','params':{},'operator':'>','compare_type':'field','compare_field':'PSAR','compare_params':{'af':0.02,'max_af':0.2}},
                    {'field':'MACD','params':{'fast':12,'slow':26,'signal':9},'operator':'>','compare_type':'field','compare_field':'MACD_signal','compare_params':{'fast':12,'slow':26,'signal':9}},
                    {'field':'KDJ_K','params':{'k':9,'d':3,'smooth':3},'operator':'<','compare_type':'value','compare_value':80},
                    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
                ]
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'PSAR+MACD+KDJ_ATR{atr_thresh}_{sell_type}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, sell_conds, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")
                else:
                    if count <= 5:
                        print(f"  SKIP {name}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- PSAR+MACD+KDJ+ATR Summary ---")
print(f"Total: {len(results)} valid / {count} total, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
all_results['psar_fix'] = results

# ============================================================
# GRID 4: DIP-BUY + volume combo (double dip)
# ============================================================
print("\n" + "="*60)
print("GRID 4: DIP-BUY + Volume spike combo")
print("="*60)
results = []
count = 0
for dip in [-2.5, -3.0]:
    for vol_thresh in [30, 50, 80]:  # volume pct_change > X%
        for rsi_lb, rsi_ub in [(50, 70)]:
            for tp in [1.5, 2.0, 2.5]:
                for mhd in [3, 5, 7]:
                    count += 1
                    buy = [
                        {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':rsi_lb},
                        {'field':'RSI','params':{'period':14},'operator':'<','compare_type':'value','compare_value':rsi_ub},
                        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.09},
                        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                        {'field':'volume','params':{},'compare_type':'pct_change','operator':'>','compare_value':vol_thresh,'lookback_n':1},
                    ]
                    exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                    name = f'DIP{dip}_VOL{vol_thresh}_RSI{rsi_lb}-{rsi_ub}_TP{tp}_MHD{mhd}'
                    r = run_bt(name, buy, aR2vF2, exit_cfg)
                    if r:
                        results.append(r)
                        tag = ' *** StdA+ ***' if r['stda'] else ''
                        print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")
                    else:
                        if count <= 3:
                            print(f"  SKIP {name}: <10 trades")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- DIP+Volume Summary ---")
print(f"Total: {len(results)} valid / {count} total, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
all_results['dip_vol'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R530 FINAL SUMMARY")
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

    # Best StdA+
    stda_all = [r for r in all_flat if r['stda']]
    if stda_all:
        best_stda = max(stda_all, key=lambda x: x['score'])
        print(f"\nBest StdA+: {best_stda['name']} sc={best_stda['score']} ret={best_stda['ret']}% dd={best_stda['dd']}% wr={best_stda['wr']}%")

with open('/tmp/r530_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r530_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
