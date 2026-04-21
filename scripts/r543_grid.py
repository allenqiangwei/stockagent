#!/usr/bin/env python3
"""R543: New angles — SL optimization, RSI band boundaries, multi-day DIP, RSI+BOLL+ATR hybrid."""
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

def dip_buy(dip, rsi_lb=50, rsi_ub=75, rsi_period=18, atr_thresh=0.087, dip_lookback=1):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':rsi_lb},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':rsi_ub},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':dip_lookback},
    ]

all_results = {}

# ============================================================
# GRID 1: SL Optimization at the Champion Config
# Current champion uses SL=-10. Test SL=-5,-8,-12,-15,-20,None
# ============================================================
print("\n=== GRID 1: SL Optimization ===")
grid1 = []
for sl in [-5, -8, -10, -12, -15, -20]:
    for tp in [2.5, 2.7]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_ATR0.087_aR2vF2_DIP{dip}_TP{tp}_MHD7_SL{sl}"
            buy = dip_buy(dip)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':sl, 'max_hold_days':7}
            grid1.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 1: {len(grid1)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid1):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 1 done")

# ============================================================
# GRID 2: RSI Band Boundaries
# Standard is 50-75. Test: 48-75, 52-75, 50-73, 50-77
# ============================================================
print("\n=== GRID 2: RSI Band Boundaries ===")
grid2 = []
for rsi_lb, rsi_ub in [(48,75), (50,75), (52,75), (50,73), (50,77), (48,77), (52,73)]:
    for tp in [2.5, 2.7]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_B{rsi_lb}-{rsi_ub}_ATR0.087_aR2vF2_DIP{dip}_TP{tp}_MHD7"
            buy = dip_buy(dip, rsi_lb=rsi_lb, rsi_ub=rsi_ub)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid2.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 2: {len(grid2)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid2):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 2 done")

# ============================================================
# GRID 3: Multi-day DIP (2-day and 3-day pct_change)
# Standard is 1-day. Hypothesis: 2-day dip captures deeper pullbacks
# ============================================================
print("\n=== GRID 3: Multi-day DIP ===")
grid3 = []
for lookback in [1, 2, 3]:
    for dip in [-2.9, -3.5, -4.0, -5.0, -6.0]:
        for tp in [2.5, 2.7]:
            name = f"RSI18_ATR0.087_aR2vF2_DIP{dip}_LB{lookback}_TP{tp}_MHD7"
            buy = dip_buy(dip, dip_lookback=lookback)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid3.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 3: {len(grid3)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid3):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
    if (i+1) % 10 == 0: print(f"  Progress: {i+1}/{len(grid3)}")
print(f"Grid 3 done")

# ============================================================
# GRID 4: RSI + BOLL%B + ATR (new hybrid)
# Hypothesis: BOLL%B < 0.2 (near lower band) + RSI confirms buy
# ============================================================
print("\n=== GRID 4: RSI + BOLL%B + ATR ===")
grid4 = []
for boll_thresh in [0.1, 0.15, 0.2, 0.25, 0.3]:
    for tp in [2.0, 2.5]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_BOLL{boll_thresh}_ATR0.087_aR2vF2_DIP{dip}_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.087},
                {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                {'field':'BOLL','params':{'period':20,'std_dev':2},'operator':'<','compare_type':'value','compare_value':boll_thresh,
                 'indicator_field':'pctb'},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid4.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 4: {len(grid4)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid4):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 4 done")

# ============================================================
# GRID 5: Position Size Optimization
# pos10 max30% is standard. Test other combos
# ============================================================
print("\n=== GRID 5: Position Size ===")
grid5 = []
for pos, pct in [(5, 30), (8, 30), (10, 30), (10, 20), (10, 40), (12, 30), (15, 30)]:
    for tp in [2.5, 2.7]:
        name = f"RSI18_ATR0.087_aR2vF2_DIP-2.9_TP{tp}_MHD7_pos{pos}_pct{pct}"
        buy = dip_buy(-2.9)
        exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
        strat = {'name':name,'buy_conditions':buy,'sell_conditions':aR2vF2,'exit_config':exit_cfg,
                 'portfolio_config':{'max_positions':pos,'max_position_pct':pct}}
        eng = PortfolioBacktestEngine(initial_capital=100000,max_positions=pos,max_position_pct=pct,
                                      slippage_pct=0.1)
        try:
            r = eng.run(strat, stock_data)
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            continue
        tr = getattr(r,'total_trades',0) or 0
        if tr < 10: continue
        sc = calc_score(r)
        wr = getattr(r,'win_rate',0) or 0
        ret = getattr(r,'total_return_pct',0) or 0
        dd = abs(getattr(r,'max_drawdown_pct',100) or 100)
        sh = getattr(r,'sharpe_ratio',0) or 0
        pl = getattr(r,'profit_loss_ratio',0) or 0
        stda = sc>=0.80 and ret>60 and dd<18 and tr>=50 and wr>60
        all_results[name] = {'name':name,'score':round(sc,4),'ret':round(ret,1),'dd':round(dd,1),
                'wr':round(wr,1),'trades':tr,'stda':stda,'sharpe':round(sh,2),'plr':round(pl,2)}

print(f"Grid 5: {len([r for r in all_results.values() if 'pos' in r['name']])} results")

# ============================================================
# GRID 6: Slippage Sensitivity at Champion
# Verify: What slippage levels can the champion tolerate?
# ============================================================
print("\n=== GRID 6: Slippage Sensitivity ===")
grid6 = []
for slip in [0.05, 0.08, 0.10, 0.12, 0.15]:
    for tp in [2.5, 2.7]:
        name = f"RSI18_ATR0.087_aR2vF2_DIP-2.9_TP{tp}_MHD7_slip{slip}"
        buy = dip_buy(-2.9)
        exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
        r = run_bt(name, buy, aR2vF2, exit_cfg, slippage_pct=slip)
        if r: all_results[name] = r

print(f"Grid 6 done")

# ============================================================
# SUMMARY
# ============================================================
total_time = time.time() - t0
valid = len(all_results)
stda = sum(1 for r in all_results.values() if r['stda'])
print(f"\n{'='*60}")
print(f"R543 COMPLETE: {valid} valid configs, {stda} StdA+ ({100*stda/max(valid,1):.1f}%)")
print(f"Total time: {total_time/60:.1f} min")

# Top 10 by score
top10 = sorted(all_results.values(), key=lambda x: x['score'], reverse=True)[:10]
print(f"\nTop 10:")
for i, r in enumerate(top10):
    flag = "★" if r['stda'] else " "
    print(f"  {i+1}. {flag} {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, trades={r['trades']}")

# SL analysis
print(f"\n--- SL Analysis ---")
for sl in [-5, -8, -10, -12, -15, -20]:
    matches = [r for r in all_results.values() if f'_SL{sl}' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        print(f"  SL{sl}: {stda_count}/{len(matches)} StdA+, avg wr={avg_wr:.1f}%, best={best['score']}")

# RSI band analysis
print(f"\n--- RSI Band Analysis ---")
for lb, ub in [(48,75), (50,75), (52,75), (50,73), (50,77), (48,77), (52,73)]:
    matches = [r for r in all_results.values() if f'_B{lb}-{ub}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  B{lb}-{ub}: {stda_count}/{len(matches)} StdA+, best={best['score']}")

# Multi-day DIP
print(f"\n--- Multi-day DIP Analysis ---")
for lb in [1, 2, 3]:
    matches = [r for r in all_results.values() if f'_LB{lb}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        print(f"  LB{lb}: {stda_count}/{len(matches)} StdA+, avg wr={avg_wr:.1f}%, best={best['score']}")

# BOLL%B analysis
print(f"\n--- BOLL%B Analysis ---")
for b in [0.1, 0.15, 0.2, 0.25, 0.3]:
    matches = [r for r in all_results.values() if f'BOLL{b}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  BOLL<{b}: {stda_count}/{len(matches)} StdA+, best={best['score']}, trades={best['trades']}")

# Position size analysis
print(f"\n--- Position Size Analysis ---")
for pos in [5, 8, 10, 12, 15]:
    matches = [r for r in all_results.values() if f'_pos{pos}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  pos{pos}: {stda_count}/{len(matches)} StdA+, best={best['score']}, wr={best['wr']}%, dd={best['dd']}%")

# Slippage analysis
print(f"\n--- Slippage Sensitivity ---")
for slip in [0.05, 0.08, 0.10, 0.12, 0.15]:
    matches = [r for r in all_results.values() if f'_slip{slip}' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  slip={slip}%: {stda_count}/{len(matches)} StdA+, best={best['score']}, wr={best['wr']}%")

# Save results
with open('/tmp/r543_results.json', 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/r543_results.json")
