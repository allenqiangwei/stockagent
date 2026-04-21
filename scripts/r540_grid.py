#!/usr/bin/env python3
"""R540: TP extension (2.55-2.7), MHD10 deep, sell variants at TP2.5, RSI at TP2.5, ultra-fine ATR around 0.087."""
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
# GRID 1: TP Extension (2.50-2.70 step 0.05)
# R539: TP2.5=0.8647 champion, score still rising. Where does it stop?
# 5 TPs x 3 dips x 2 sells = 30 configs
# ============================================================
print("\n" + "="*60)
print("GRID 1: TP Extension (2.50-2.70)")
print("="*60)
results = []
for tp in [2.50, 2.55, 2.60, 2.65, 2.70]:
    for dip in [-2.8, -2.9, -3.0]:
        for sell, sell_name in [(aR2vF2,'aR2vF2'), (aR3vF2,'aR3vF2')]:
            buy = dip_buy(dip)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
            name = f'RSI18_ATR0.087_{sell_name}_DIP{dip}_TP{tp}_MHD7'
            r = run_bt(name, buy, sell, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- TP Extension Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for tp in [2.50, 2.55, 2.60, 2.65, 2.70]:
    rp = [r for r in results if f'_TP{tp}_' in r['name']]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in rp)/len(rp)
        print(f"  TP{tp}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, avg wr={avg_wr:.1f}%")
all_results['tp_extension'] = results

# ============================================================
# GRID 2: MHD10 Deep at TP2.5
# R539: MHD10=0.8632 at TP2.4. What about TP2.5?
# 4 MHD x 3 dips x 2 TPs = 24 configs
# ============================================================
print("\n" + "="*60)
print("GRID 2: MHD Sweep at TP2.5")
print("="*60)
results = []
for mhd in [3, 5, 7, 10]:
    for dip in [-2.8, -2.9, -3.0]:
        for tp in [2.4, 2.5]:
            buy = dip_buy(dip)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':mhd}
            name = f'RSI18_ATR0.087_DIP{dip}_TP{tp}_MHD{mhd}'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- MHD at TP2.5 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for mhd in [3, 5, 7, 10]:
    rp = [r for r in results if f'_MHD{mhd}' in r['name']]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        print(f"  MHD{mhd}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}")
all_results['mhd_tp25'] = results

# ============================================================
# GRID 3: Sell Variants at TP2.5 Champion Setting
# Does aR3vF2 or vF2only beat aR2vF2 at TP2.5?
# 3 sells x 5 dips x 2 MHDs = 30 configs
# ============================================================
print("\n" + "="*60)
print("GRID 3: Sell Variants at TP2.5")
print("="*60)
results = []
for sell, sell_name in [(aR2vF2,'aR2vF2'), (aR3vF2,'aR3vF2'), (vF2only,'vF2only')]:
    for dip in [-2.7, -2.8, -2.9, -3.0, -3.1]:
        for mhd in [7, 10]:
            buy = dip_buy(dip)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':2.5, 'max_hold_days':mhd}
            name = f'RSI18_ATR0.087_{sell_name}_DIP{dip}_TP2.5_MHD{mhd}'
            r = run_bt(name, buy, sell, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Sell Variants at TP2.5 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for sell_name in ['aR2vF2','aR3vF2','vF2only']:
    rp = [r for r in results if f'_{sell_name}_' in r['name']]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in rp)/len(rp)
        print(f"  {sell_name}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, avg wr={avg_wr:.1f}%")
all_results['sell_tp25'] = results

# ============================================================
# GRID 4: RSI Period at ATR0.087 TP2.5
# R539: RSI15-20 all 100% at TP2.4. Does TP2.5 change this?
# 6 RSI x 2 dips x 1 TP = 12 configs
# ============================================================
print("\n" + "="*60)
print("GRID 4: RSI Period at ATR0.087 TP2.5")
print("="*60)
results = []
for rsi_p in [15, 16, 17, 18, 19, 20]:
    for dip in [-2.9, -3.0]:
        buy = dip_buy(dip, rsi_period=rsi_p)
        exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':2.5, 'max_hold_days':7}
        name = f'RSI{rsi_p}_ATR0.087_DIP{dip}_TP2.5_MHD7'
        r = run_bt(name, buy, aR2vF2, exit_cfg)
        if r:
            results.append(r)
            tag = ' *** StdA+ ***' if r['stda'] else ''
            print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- RSI Period at TP2.5 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for rsi_p in [15, 16, 17, 18, 19, 20]:
    rp = [r for r in results if f'RSI{rsi_p}_' in r['name']]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        print(f"  RSI{rsi_p}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, wr={best_rp['wr']}%")
all_results['rsi_tp25'] = results

# ============================================================
# GRID 5: Ultra-Fine ATR around 0.087 (0.0865-0.0875 step 0.0005)
# + Also test 0.086 and 0.088 at TP2.5
# 5 ATR x 2 dips x 2 TPs = 20 configs
# ============================================================
print("\n" + "="*60)
print("GRID 5: Ultra-Fine ATR at TP2.5 (0.086-0.089)")
print("="*60)
results = []
for atr_t in [0.086, 0.0865, 0.087, 0.0875, 0.088, 0.089]:
    for dip in [-2.9, -3.0]:
        for tp in [2.4, 2.5]:
            buy = dip_buy(dip, atr_thresh=atr_t)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':tp, 'max_hold_days':7}
            name = f'RSI18_ATR{atr_t:.4f}_DIP{dip}_TP{tp}_MHD7'
            r = run_bt(name, buy, aR2vF2, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- Ultra-Fine ATR at TP2.5 Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for atr_t in [0.086, 0.0865, 0.087, 0.0875, 0.088, 0.089]:
    rp = [r for r in results if f'_ATR{atr_t:.4f}_' in r['name']]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        avg_ret = sum(r['ret'] for r in rp)/len(rp)
        print(f"  ATR{atr_t:.4f}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}, avg ret={avg_ret:.1f}%")
all_results['atr_ultra_fine_tp25'] = results

# ============================================================
# GRID 6: TP2.5 + MHD10 Combined Champion Test
# Top from each previous grid combined
# 4 dips x 3 sells x 2 MHDs = 24 configs
# ============================================================
print("\n" + "="*60)
print("GRID 6: TP2.5 + MHD10 Combined Test")
print("="*60)
results = []
for dip in [-2.8, -2.9, -3.0, -3.1]:
    for sell, sell_name in [(aR2vF2,'aR2vF2'), (aR3vF2,'aR3vF2'), (vF2only,'vF2only')]:
        for mhd in [7, 10]:
            buy = dip_buy(dip)
            exit_cfg = {'stop_loss_pct':-20, 'take_profit_pct':2.5, 'max_hold_days':mhd}
            name = f'RSI18_ATR0.087_{sell_name}_DIP{dip}_TP2.5_MHD{mhd}'
            r = run_bt(name, buy, sell, exit_cfg)
            if r:
                results.append(r)
                tag = ' *** StdA+ ***' if r['stda'] else ''
                print(f"  {name}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%{tag}")

stda_count = sum(1 for r in results if r['stda'])
print(f"\n--- TP2.5 + MHD10 Combined Summary ---")
print(f"Total: {len(results)} valid, StdA+: {stda_count}")
for mhd in [7, 10]:
    rp = [r for r in results if f'_MHD{mhd}' in r['name']]
    if rp:
        rp_stda = sum(1 for r in rp if r['stda'])
        best_rp = max(rp, key=lambda x: x['score'])
        print(f"  MHD{mhd}: {len(rp)} valid, {rp_stda} StdA+, best sc={best_rp['score']}")
all_results['tp25_mhd10_combined'] = results

# ============================================================
# FINAL SUMMARY
# ============================================================
total_time = time.time() - t0
print(f"\n{'='*60}")
print(f"R540 COMPLETE — Total time: {total_time:.0f}s ({total_time/60:.1f}min)")
print(f"{'='*60}")

all_flat = []
for grid_name, res_list in all_results.items():
    all_flat.extend(res_list)

total_valid = len(all_flat)
total_stda = sum(1 for r in all_flat if r['stda'])
if all_flat:
    best = max(all_flat, key=lambda x: x['score'])
    best_stda = max([r for r in all_flat if r['stda']], key=lambda x: x['score']) if total_stda else None
    print(f"Total valid: {total_valid}")
    print(f"Total StdA+: {total_stda} ({total_stda/total_valid*100:.1f}%)")
    print(f"Best overall: {best['name']} sc={best['score']} ret={best['ret']}% dd={best['dd']}% wr={best['wr']}%")
    if best_stda:
        print(f"Best StdA+:   {best_stda['name']} sc={best_stda['score']} ret={best_stda['ret']}% dd={best_stda['dd']}% wr={best_stda['wr']}%")

with open('/tmp/r540_results.json','w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/r540_results.json")
