#!/usr/bin/env python3
"""R529: Portfolio-mode grid search — DIP-BUY, Families, Volume momentum."""
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
    df = dc.get_daily_df(code, '2021-01-01', '2026-03-08', local_only=True)
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

# === Common sell conditions ===
aR2vF2 = [
    {'field':'ATR','params':{'period':14},'operator':'>','compare_type':'consecutive','consecutive_type':'rising','lookback_n':2},
    {'field':'volume','operator':'>','compare_type':'consecutive','consecutive_type':'falling','lookback_n':2}
]

all_results = {}

# ============================================================
# GRID 1: DIP-BUY
# ============================================================
print("\n" + "="*60)
print("GRID 1: DIP-BUY (dip threshold × RSI × TP × MHD)")
print("="*60)
results = []
count = 0
for dip in [-1.5, -2.0, -2.5, -3.0, -3.5, -4.0]:
    for rsi_lb, rsi_ub in [(50, 66), (50, 70), (48, 68), (45, 70)]:
        for tp in [1.5, 2.0, 2.5, 3.0]:
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
                    if count % 20 == 0 or r['stda']:
                        print(f"  [{count}/288] {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- DIP-BUY Summary ---")
print(f"Total: {len(results)} valid / 288 total, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    top10 = sorted(results, key=lambda x: x['score'], reverse=True)[:10]
    print("Top 10:")
    for r in top10:
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")
all_results['dip_buy'] = results

# ============================================================
# GRID 2: Portfolio Family Test
# ============================================================
print("\n" + "="*60)
print("GRID 2: Portfolio Family Test")
print("="*60)

psar_macd_kdj_buy = [
    {'field':'close','params':{},'operator':'>','compare_type':'field','compare_field':'PSAR','compare_params':{'af':0.02,'max_af':0.2}},
    {'field':'MACD','params':{'fast':12,'slow':26,'signal':9},'operator':'>','compare_type':'field','compare_field':'MACD_signal','compare_params':{'fast':12,'slow':26,'signal':9}},
    {'field':'KDJ_K','params':{'k':9,'d':3,'smooth':3},'operator':'<','compare_type':'value','compare_value':80},
]
min3_buy = [
    {'field':'MACD','params':{'fast':12,'slow':26,'signal':9},'operator':'>','compare_type':'field','compare_field':'MACD_signal','compare_params':{'fast':12,'slow':26,'signal':9}},
    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':50},
    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.08},
]
ema_atr_buy = [
    {'field':'EMA','params':{'period':12},'operator':'>','compare_type':'field','compare_field':'EMA','compare_params':{'period':26}},
    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.06},
]
san_zhi_buy = [
    {'field':'MACD','params':{'fast':12,'slow':26,'signal':9},'operator':'>','compare_type':'field','compare_field':'MACD_signal','compare_params':{'fast':12,'slow':26,'signal':9}},
    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':50},
    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.06},
    {'field':'MFI','params':{'length':14},'operator':'>','compare_type':'value','compare_value':40},
]

families = {
    'PSAR+MACD+KDJ': psar_macd_kdj_buy,
    'Min3': min3_buy,
    'EMA+ATR': ema_atr_buy,
    '三指標': san_zhi_buy,
}
sell_types = {'aR2vF2': aR2vF2, 'noSell': []}

results = []
for fname, buy in families.items():
    for sname, sell in sell_types.items():
        for tp in [1.0, 1.5, 2.0]:
            for mhd in [3, 5]:
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'{fname}_{sname}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, sell, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")
                else:
                    print(f"  SKIP {name}: <10 trades or error")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Family Test Summary ---")
print(f"Total: {len(results)} valid / 48 total, StdA+: {stda_count}")
for fname in families:
    fam_results = [r for r in results if r['name'].startswith(fname)]
    fam_stda = sum(1 for r in fam_results if r['stda'])
    if fam_results:
        best = max(fam_results, key=lambda x: x['score'])
        print(f"  {fname}: {len(fam_results)} configs, {fam_stda} StdA+, best={best['name']} sc={best['score']} ret={best['ret']}% wr={best['wr']}%")
all_results['family'] = results

# ============================================================
# GRID 3: Volume Momentum
# ============================================================
print("\n" + "="*60)
print("GRID 3: Volume Momentum")
print("="*60)
results = []
count = 0
for rsi_lb, rsi_ub in [(50, 66), (52, 66), (50, 70), (48, 68)]:
    for vol_thresh in [0.5, 1.0, 1.5, 2.0]:
        for tp in [1.0, 1.3, 1.5, 1.8, 2.0]:
            for mhd in [3, 5]:
                count += 1
                buy = [
                    {'field':'RSI','params':{'period':14},'operator':'>','compare_type':'value','compare_value':rsi_lb},
                    {'field':'RSI','params':{'period':14},'operator':'<','compare_type':'value','compare_value':rsi_ub},
                    {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.0912},
                    {'field':'volume','params':{},'compare_type':'pct_change','operator':'>','compare_value':vol_thresh*100,'lookback_n':1},
                ]
                exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
                name = f'VOL{vol_thresh}_RSI{rsi_lb}-{rsi_ub}_TP{tp}_MHD{mhd}'
                r = run_bt(name, buy, aR2vF2, exit_cfg)
                if r:
                    results.append(r)
                    tag = ' *** StdA+ ***' if r['stda'] else ''
                    if count % 20 == 0 or r['stda']:
                        print(f"  [{count}/160] {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Volume Momentum Summary ---")
print(f"Total: {len(results)} valid / 160 total, StdA+: {stda_count}")
if results:
    best = max(results, key=lambda x: x['score'])
    print(f"Best: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    top5 = sorted(results, key=lambda x: x['score'], reverse=True)[:5]
    print("Top 5:")
    for r in top5:
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")
all_results['volume'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "="*60)
print("R529 FINAL SUMMARY")
print("="*60)
total_configs = sum(len(v) for v in all_results.values())
total_stda = sum(sum(1 for r in v if r['stda']) for v in all_results.values())
print(f"Total valid configs: {total_configs}")
print(f"Total StdA+: {total_stda}")

# Overall top 15
all_flat = []
for v in all_results.values():
    all_flat.extend(v)
if all_flat:
    top15 = sorted(all_flat, key=lambda x: x['score'], reverse=True)[:15]
    print("\nOverall Top 15:")
    for i, r in enumerate(top15, 1):
        tag = 'StdA+' if r['stda'] else ''
        print(f"  {i}. {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, tr={r['trades']} {tag}")

# Save full results to JSON
with open('/tmp/r529_results.json', 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nFull results saved to /tmp/r529_results.json")
print(f"Total time: {time.time()-t0:.1f}s")
