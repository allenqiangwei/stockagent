#!/usr/bin/env python3
"""R546: closeAbvMin RSI16 + hybrid tests — can RSI16 push closeAbvMin past 0.8647?"""
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

def closeAbvMin_buy(dip, lookback=10, rsi_period=18, atr_thresh=0.087):
    return [
        {'field':'RSI','params':{'period':rsi_period},'operator':'>','compare_type':'value','compare_value':50},
        {'field':'RSI','params':{'period':rsi_period},'operator':'<','compare_type':'value','compare_value':75},
        {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':atr_thresh},
        {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':dip,'lookback_n':1},
        {'field':'close','params':{},'operator':'>','compare_type':'lookback_min','lookback_n':lookback},
    ]

all_results = {}

# ============================================================
# GRID 1: closeAbvMin RSI16 at ATR0.0875 (R542 showed RSI16 optimal)
# ============================================================
print("\n=== GRID 1: closeAbvMin RSI16 @ ATR0.0875 ===")
grid1 = []
for rsi in [16, 17, 18]:
    for tp in [2.5, 2.7, 2.8]:
        for lb in [10, 15, 20]:
            name = f"RSI{rsi}_ATR0.0875_aR2vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7"
            buy = closeAbvMin_buy(-2.9, lookback=lb, rsi_period=rsi, atr_thresh=0.0875)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid1.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 1: {len(grid1)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid1):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 1 done")

# ============================================================
# GRID 2: closeAbvMin RSI16 + aR3vF2 (most reliable sell)
# ============================================================
print("\n=== GRID 2: closeAbvMin RSI16 + aR3vF2 ===")
grid2 = []
for rsi in [16, 17, 18]:
    for tp in [2.5, 2.7]:
        for lb in [15, 20]:
            name = f"RSI{rsi}_ATR0.0875_aR3vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7"
            buy = closeAbvMin_buy(-2.9, lookback=lb, rsi_period=rsi, atr_thresh=0.0875)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid2.append((name, buy, aR3vF2, exit_cfg))

print(f"Grid 2: {len(grid2)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid2):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 2 done")

# ============================================================
# GRID 3: closeAbvMin AbvMin15 deep (R545 showed 100% StdA+)
# ============================================================
print("\n=== GRID 3: closeAbvMin AbvMin15 Deep ===")
grid3 = []
for atr in [0.087, 0.0875]:
    for tp in [2.0, 2.3, 2.5, 2.7, 2.8]:
        for dip in [-2.9, -3.0]:
            name = f"RSI18_ATR{atr}_aR2vF2_DIP{dip}_AbvMin15_TP{tp}_MHD7_lb15"
            buy = closeAbvMin_buy(dip, lookback=15, atr_thresh=atr)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid3.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 3: {len(grid3)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid3):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 3 done")

# ============================================================
# GRID 4: Standard 4-cond champion vs closeAbvMin 5-cond head-to-head
# with slippage 0.08% (the achievable improvement)
# ============================================================
print("\n=== GRID 4: Slippage 0.08% — 4-cond vs 5-cond ===")
grid4 = []
for slip in [0.08, 0.10]:
    # 4-cond standard (no closeAbvMin)
    for tp in [2.5, 2.7]:
        name = f"4cond_RSI18_ATR0.087_DIP-2.9_TP{tp}_MHD7_slip{slip}"
        buy = [
            {'field':'RSI','params':{'period':18},'operator':'>','compare_type':'value','compare_value':50},
            {'field':'RSI','params':{'period':18},'operator':'<','compare_type':'value','compare_value':75},
            {'field':'ATR','params':{'period':14},'operator':'<','compare_type':'value','compare_value':0.087},
            {'field':'close','params':{},'compare_type':'pct_change','operator':'<','compare_value':-2.9,'lookback_n':1},
        ]
        exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
        grid4.append((name, buy, aR2vF2, exit_cfg, slip))

    # 5-cond closeAbvMin
    for tp in [2.5, 2.7]:
        for lb in [15, 20]:
            name = f"5cond_RSI18_ATR0.087_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7_slip{slip}"
            buy = closeAbvMin_buy(-2.9, lookback=lb)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid4.append((name, buy, aR2vF2, exit_cfg, slip))

print(f"Grid 4: {len(grid4)} configs")
for i, (name, buy, sell, exit_cfg, slip) in enumerate(grid4):
    r = run_bt(name, buy, sell, exit_cfg, slippage_pct=slip)
    if r: all_results[name] = r
print(f"Grid 4 done")

# ============================================================
# GRID 5: closeAbvMin RSI16 fine-tune at ATR0.087
# ============================================================
print("\n=== GRID 5: closeAbvMin RSI16 @ ATR0.087 ===")
grid5 = []
for rsi in [15, 16, 17]:
    for tp in [2.5, 2.7]:
        for lb in [15, 20]:
            name = f"RSI{rsi}_ATR0.087_aR2vF2_DIP-2.9_AbvMin{lb}_TP{tp}_MHD7_r16ft"
            buy = closeAbvMin_buy(-2.9, lookback=lb, rsi_period=rsi, atr_thresh=0.087)
            exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
            grid5.append((name, buy, aR2vF2, exit_cfg))

print(f"Grid 5: {len(grid5)} configs")
for i, (name, buy, sell, exit_cfg) in enumerate(grid5):
    r = run_bt(name, buy, sell, exit_cfg)
    if r: all_results[name] = r
print(f"Grid 5 done")

# ============================================================
# GRID 6: closeAbvMin DIP-3.0 at AbvMin15/20 (R545 showed -3.0 viable)
# ============================================================
print("\n=== GRID 6: closeAbvMin DIP-3.0 Focus ===")
grid6 = []
for atr in [0.087, 0.0875]:
    for tp in [2.5, 2.7]:
        for lb in [15, 20]:
            for sell_name, sell_conds in [('aR2vF2', aR2vF2), ('aR3vF2', aR3vF2)]:
                name = f"RSI18_ATR{atr}_{sell_name}_DIP-3.0_AbvMin{lb}_TP{tp}_MHD7_d30"
                buy = closeAbvMin_buy(-3.0, lookback=lb, atr_thresh=atr)
                exit_cfg = {'take_profit_pct':tp, 'stop_loss_pct':-10, 'max_hold_days':7}
                grid6.append((name, buy, sell_conds, exit_cfg))

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
print(f"R546 COMPLETE: {valid} valid configs, {stda} StdA+ ({100*stda/max(valid,1):.1f}%)")
print(f"Total time: {total_time/60:.1f} min")

top10 = sorted(all_results.values(), key=lambda x: x['score'], reverse=True)[:10]
print(f"\nTop 10:")
for i, r in enumerate(top10):
    flag = "★" if r['stda'] else " "
    print(f"  {i+1}. {flag} {r['name']}: sc={r['score']}, ret={r['ret']}%, dd={r['dd']}%, wr={r['wr']}%, trades={r['trades']}")

# RSI period analysis
print(f"\n--- RSI Period Analysis ---")
for rsi in [15, 16, 17, 18]:
    matches = [r for r in all_results.values() if f'RSI{rsi}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        print(f"  RSI{rsi}: {stda_count}/{len(matches)} StdA+, avg wr={avg_wr:.1f}%, best={best['score']}")

# 4-cond vs 5-cond
print(f"\n--- 4-cond vs 5-cond ---")
for prefix in ['4cond', '5cond']:
    matches = [r for r in all_results.values() if r['name'].startswith(prefix)]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        avg_wr = sum(r['wr'] for r in matches) / len(matches)
        print(f"  {prefix}: {stda_count}/{len(matches)} StdA+, avg wr={avg_wr:.1f}%, best={best['score']} ({best['name'][:60]})")

# Slippage comparison
print(f"\n--- Slippage Analysis ---")
for slip in [0.08, 0.10]:
    matches = [r for r in all_results.values() if f'slip{slip}' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  slip{slip}: {stda_count}/{len(matches)} StdA+, best={best['score']} ({best['name'][:60]})")

# AbvMin lookback
print(f"\n--- Lookback Analysis ---")
for lb in [10, 15, 20]:
    matches = [r for r in all_results.values() if f'AbvMin{lb}_' in r['name']]
    if matches:
        stda_count = sum(1 for r in matches if r['stda'])
        best = max(matches, key=lambda x: x['score'])
        print(f"  AbvMin{lb}: {stda_count}/{len(matches)} StdA+, best={best['score']}")

with open('/tmp/r546_results.json', 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/r546_results.json")
