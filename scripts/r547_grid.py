#!/usr/bin/env python3
"""R547: AbvMin fine-tune (12-13) + 0.08% slip all-time chase."""
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

def closeAbvMin_buy(dip, lookback=15, rsi_period=18, atr_thresh=0.087):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':50},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':75},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
        {'field':'close','params':{},'operator':'>','compare_type':'lookback_min','lookback_n':lookback},
    ]

all_results = {}

# ============================================================
# GRID 1: AbvMin fine-tune (11, 12, 13, 14) at standard 0.10%
# ============================================================
print("\n=== GRID 1: AbvMin Fine-Tune (11-14) ===")
grid1 = []
for lb in [11, 12, 13, 14]:
    for tp in [2.5, 2.7, 2.8]:
        for atr in [0.087, 0.0875]:
            name = f"RSI18_ATR{atr}_aR2vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7"
            buy = closeAbvMin_buy(-2.9, lookback=lb, atr_thresh=atr)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid1.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 1: {len(grid1)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid1):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 1 done")

# ============================================================
# GRID 2: All-time chase at 0.08% slippage — AbvMin11-15 × TP2.7
# ============================================================
print("\n=== GRID 2: 0.08% Slip All-Time Chase ===")
grid2 = []
for lb in [11, 12, 13, 14, 15]:
    for tp in [2.7, 2.8]:
        for atr in [0.087, 0.0875]:
            name = f"RSI18_ATR{atr}_aR2vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7_slip0.08"
            buy = closeAbvMin_buy(-2.9, lookback=lb, atr_thresh=atr)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid2.append((name, buy, aR2vF2, exit_cfg, 0.08))

print(f"Grid 2: {len(grid2)} configs")
for i, (name, buy, sell, exit_cfg, slip) in enumerate(grid2):
    r = run_bt(name, buy, sell, exit_cfg, slippage_pct=slip)
    if r: all_results[name] = r
print(f"Grid 2 done")

# ============================================================
# GRID 3: RSI16 + AbvMin12-15 at ATR0.0875
# ============================================================
print("\n=== GRID 3: RSI16 AbvMin Fine-Tune ===")
grid3 = []
for lb in [12, 13, 14, 15]:
    for tp in [2.7, 2.8]:
        name = f"RSI16_ATR0.0875_aR2vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7"
        buy = closeAbvMin_buy(-2.9, lookback=lb, rsi_period=16, atr_thresh=0.0875)
        exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
        grid3.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 3: {len(grid3)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid3):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 3 done")

# ============================================================
# GRID 4: aR3vF2 + AbvMin15/20 best combos
# ============================================================
print("\n=== GRID 4: aR3vF2 Best Combos ===")
grid4 = []
for rsi in [16, 18]:
    for lb in [13, 15, 20]:
        for tp in [2.5, 2.7]:
            for atr in [0.087, 0.0875]:
                name = f"RSI{rsi}_ATR{atr}_aR3vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7"
                buy = closeAbvMin_buy(-2.9, lookback=lb, rsi_period=rsi, atr_thresh=atr)
                exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
                grid4.append((name, buy, aR3vF2, exit_cfg))

print(f"Grid 4: {len(grid4)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid4):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 4 done")

# ============================================================
# GRID 5: DIP-3.0 + AbvMin13-15 (filling gaps)
# ============================================================
print("\n=== GRID 5: DIP-3.0 AbvMin Fine-Tune ===")
grid5 = []
for lb in [13, 15]:
    for tp in [2.5, 2.7]:
        for atr in [0.087, 0.0875]:
            name = f"RSI18_ATR{atr}_aR2vF2_DIP-3.0_AbvMin{lb}_TP{tp}_MHD7"
            buy = closeAbvMin_buy(-3.0, lookback=lb, atr_thresh=atr)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid5.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 5: {len(grid5)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid5):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 5 done")

# ============================================================
# SUMMARY
# ============================================================
total_time = time.time() - t0
valid = len(all_results)
stda = sum(1 for r in all_results.values() if r['stda'])
print(f"\n{'='*60}")
print(f"R547 COMPLETE: {valid} valid configs, {stda} StdA+ ({100*stda/max(valid,1):.1f}%)")
print(f"Total time: {total_time/60:.1f} min")

top15 = sorted(all_results.values(), key=lambda x: x['score'], reverse=True)[:15]
print(f"\nTop 15:")
for i, r in enumerate(top15):
    flag = "★" if r['stda'] else " "
    print(f"  {i+1}. {flag} {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, trades={r['trades']}")

# AbvMin lookback analysis
print(f"\n--- AbvMin Analysis ---")
for lb in [11, 12, 13, 14, 15, 20]:
    matches = [r for r in all_results.values() if f'AbvMin{lb}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        print(f"  AbvMin{lb}: {stda_count}/{len(matches)} StdA+, avg_wr={avg_wr:.1f}%, best={best['score']}")

# Slippage analysis
print(f"\n--- Slippage Analysis ---")
for slip_str in ['slip0.08', 'MHD7"']:  # MHD7" without slip suffix = 0.10%
    if slip_str == 'MHD7"':
        matches = [r for r in all_results.values() if 'slip' not in r['name']]
        label = "0.10%"
    else:
        matches = [r for r in all_results.values() if slip_str in r['name']]
        label = "0.08%"
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  {label}: {stda_count}/{len(matches)} StdA+, best={best['score']} ({best['name'][:60]})")

with open('/tmp/r547_results.json', 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/r547_results.json")
