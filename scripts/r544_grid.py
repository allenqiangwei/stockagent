#!/usr/bin/env python3
"""R544: Non-DIP paradigms — Volume breakout, consecutive patterns, ATR-only, momentum."""
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

all_results = {}

# ============================================================
# GRID 1: RSI + ATR + No DIP (Does DIP actually help, or does RSI+ATR alone work?)
# ============================================================
print("\n=== GRID 1: RSI + ATR without DIP ===")
grid1 = []
for atr in [0.085, 0.087, 0.09]:
    for rsi_ub in [70, 75]:
        for tp in [2.0, 2.5, 2.7]:
            name = f"RSI18_B50-{rsi_ub}_ATR{atr}_noDIP_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':rsi_ub},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid1.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 1: {len(grid1)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid1):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 1 done")

# ============================================================
# GRID 2: Volume Breakout — Buy when volume spikes + RSI in band + ATR filter
# ============================================================
print("\n=== GRID 2: Volume Breakout ===")
grid2 = []
for vol_mult in [1.5, 2.0, 2.5, 3.0]:
    for tp in [2.0, 2.5]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_ATR0.087_VOLx{vol_mult}_DIP{dip}_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.087},
                {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                {'field':'volume','params':{},'compare_type':'pct_diff','operator':'>','compare_value':vol_mult*100-100,
                 'compare_field':'volume_ma_5'},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid2.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 2: {len(grid2)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid2):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 2 done")

# ============================================================
# GRID 3: Consecutive Falling Days (alternative to pct_change DIP)
# Buy after 2-3 consecutive red candles + RSI + ATR
# ============================================================
print("\n=== GRID 3: Consecutive Falling ===")
grid3 = []
for n_days in [2, 3]:
    for tp in [2.0, 2.5, 2.7]:
        for atr in [0.087, 0.09]:
            name = f"RSI18_ATR{atr}_ConsF{n_days}_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr},
                {'field':'close','params':{},'operator':'<','compare_type':'consecutive','consecutive_type':'falling','lookback_n':n_days},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid3.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 3: {len(grid3)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid3):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 3 done")

# ============================================================
# GRID 4: ATR Lookback Min (buy when ATR at N-day low, indicating calm before breakout)
# ============================================================
print("\n=== GRID 4: ATR at N-day Low ===")
grid4 = []
for lookback in [5, 10, 20]:
    for tp in [2.0, 2.5]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_ATRmin{lookback}_DIP{dip}_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'lookback_min','lookback_n':lookback},
                {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid4.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 4: {len(grid4)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid4):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 4 done")

# ============================================================
# GRID 5: RSI at N-day Low (buy when RSI at multi-day low, momentum reversal)
# ============================================================
print("\n=== GRID 5: RSI at N-day Low ===")
grid5 = []
for lookback in [3, 5, 10]:
    for tp in [2.0, 2.5]:
        for atr in [0.087, 0.09]:
            name = f"RSI18min{lookback}_ATR{atr}_DIP-2.9_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'lookback_min','lookback_n':lookback},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr},
                {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':-2.9,'lookback_n':1},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid5.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 5: {len(grid5)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid5):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 5 done")

# ============================================================
# GRID 6: DIP Intensity Variants (use pct_change with different comparison)
# Buy when close drops more than X% in 1 day AND close is above lookback_min
# ============================================================
print("\n=== GRID 6: Close Above N-day Low + DIP ===")
grid6 = []
for lookback in [5, 10, 20]:
    for tp in [2.0, 2.5]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_ATR0.087_DIP{dip}_closeAbvMin{lookback}_TP{tp}_MHD7"
            buy = [
                {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
                {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
                {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.087},
                {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
                {'field':'close','params':{},'operator':'>','compare_type':'lookback_min','lookback_n':lookback},
            ]
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid6.append((name, buy, aR2vF2, exit_cfg))

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
print(f"R544 COMPLETE: {valid} valid configs, {stda} StdA+ ({100*stda/max(valid,1):.1f}%)")
print(f"Total time: {total_time/60:.1f} min")

# Top 10
top10 = sorted(all_results.values(), key=lambda x: x['score'], reverse=True)[:10]
print(f"\nTop 10:")
for i, r in enumerate(top10):
    flag = "★" if r['stda'] else " "
    print(f"  {i+1}. {flag} {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, trades={r['trades']}")

# Grid summaries
for grid_name in ['noDIP', 'VOLx', 'ConsF', 'ATRmin', 'RSI18min', 'closeAbvMin']:
    matches = [r for r in all_results.values() if grid_name in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        print(f"\n{grid_name}: {stda_count}/{len(matches)} StdA+, avg wr={avg_wr:.1f}%, best={best['score']} ({best['name'][:70]})")

with open('/tmp/r544_results.json', 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/r544_results.json")
