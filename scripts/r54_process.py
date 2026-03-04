#!/usr/bin/env python3
"""R54 Extended Grid Search Processing Script.

Processes experiments E3421-E3431 (294 strategies) using standalone backtest engine.
Groups by family, loads stock data once, calls prepare_data once per family.

Based on mass_rebacktest.py pattern — uses DataCollector for stock data loading
and PortfolioBacktestEngine for prepare_data/run_with_prepared.

Usage:
    NO_PROXY=localhost,127.0.0.1 venv/bin/python scripts/r54_process.py > /tmp/r54_process.log 2>&1 &
"""

import os
import sys
import json
import math
import time
import logging
import threading
import subprocess
from datetime import datetime

# Configuration
ROUND_NAME = os.environ.get("ROUND_NAME", "R54")
MIN_EXP_ID = int(os.environ.get("ROUND_MIN_ID", "3421"))
MAX_EXP_ID = int(os.environ.get("ROUND_MAX_ID", "3431"))
STDA_PLUS_SCORE = 0.75
STDA_PLUS_RET = 60
STDA_PLUS_DD = 18
STDA_PLUS_TRADES = 50

START_DATE = "2023-02-14"
END_DATE = "2026-02-14"

# Setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def sigmoid(x, center=0, scale=1):
    z = (x - center) / scale
    return 1 / (1 + math.exp(-z))


def compute_score(result) -> float:
    """Compute composite score matching ai_lab_engine._compute_score."""
    w_ret, w_dd, w_sharpe, w_plr = 0.30, 0.25, 0.25, 0.20
    ret_score = sigmoid(result.total_return_pct, center=0, scale=30)
    dd = abs(result.max_drawdown_pct) if result.max_drawdown_pct else 0
    dd_score = 1 - sigmoid(dd, center=30, scale=15)
    sharpe = result.sharpe_ratio if result.sharpe_ratio else 0
    sharpe_score = sigmoid(sharpe, center=0, scale=1.5)
    plr = result.profit_loss_ratio if result.profit_loss_ratio else 0
    plr_score = sigmoid(plr, center=1.0, scale=1.5)
    score = w_ret * ret_score + w_dd * dd_score + w_sharpe * sharpe_score + w_plr * plr_score
    if dd > 80:
        score *= 0.5
    return round(score, 4)


def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)


def api_put(path, data):
    for attempt in range(3):
        r = subprocess.run(
            ['curl', '-s', '-X', 'PUT', f'http://127.0.0.1:8050/api/{path}',
             '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
            capture_output=True, text=True,
            env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
        try:
            return json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            if attempt < 2:
                time.sleep(2)
            else:
                logger.warning(f"api_put failed after 3 attempts: {path}")
                return {"error": "JSON decode failed"}


def api_post_promote(sid, label):
    import urllib.parse
    encoded_label = urllib.parse.quote(label)
    cat_map = {'[AI]': '全能'}
    cat = urllib.parse.quote(cat_map.get(label, ''))
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label={encoded_label}&category={cat}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)


def load_stock_data(session):
    """Load all stock data for the backtest period."""
    from api.services.data_collector import DataCollector
    collector = DataCollector(session)
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    logger.info(f"Found {len(stock_codes)} stocks with sufficient data")

    stock_data = {}
    for i, code in enumerate(stock_codes):
        df = collector.get_daily_df(code, START_DATE, END_DATE, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df
        if (i + 1) % 500 == 0:
            logger.info(f"  Loaded {i+1}/{len(stock_codes)} stocks...")

    logger.info(f"Loaded {len(stock_data)} stocks with valid data")
    return stock_data


def load_regime_map(session):
    """Load market regime map."""
    from api.services.regime_service import ensure_regimes, get_regime_map
    ensure_regimes(session, START_DATE, END_DATE)
    return get_regime_map(session, START_DATE, END_DATE)


def main():
    started_at = datetime.now().isoformat()
    logger.info(f"=== {ROUND_NAME} Processing Started ===")
    logger.info(f"Experiments: E{MIN_EXP_ID} - E{MAX_EXP_ID}")

    from api.models.base import SessionLocal
    from src.backtest.portfolio_engine import (
        PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError,
    )

    session = SessionLocal()

    # Step 1: Load stock data (once, shared across all families)
    logger.info("Loading stock data...")
    t0 = time.time()
    stock_data = load_stock_data(session)
    logger.info(f"Stock data loaded in {time.time()-t0:.1f}s")

    # Step 2: Load regime map
    logger.info("Loading regime map...")
    regime_map = load_regime_map(session)
    logger.info(f"Regime map: {len(regime_map) if regime_map else 0} dates")

    # Step 3: Collect all strategies grouped by family from API
    families = {}  # family_name -> list of (strategy_api_data, experiment_id)
    exp_ids = list(range(MIN_EXP_ID, MAX_EXP_ID + 1))

    for eid in exp_ids:
        exp = api_get(f'lab/experiments/{eid}')
        strats = exp.get('strategies', [])
        logger.info(f"E{eid}: {exp.get('status', '?')}, {len(strats)} strategies, theme={exp.get('theme', '?')[:50]}")

        for s in strats:
            if s.get('status') in ('done', 'invalid', 'failed'):
                continue
            name = s.get('name', '')
            if '全指标综合' in name:
                family = '全指标综合'
            elif 'VPT' in name or 'vpt' in name.lower():
                family = 'VPT+PSAR'
            elif 'MACD+RSI' in name or 'MACD' in name:
                family = 'MACD+RSI'
            elif '三指标共振' in name:
                family = '三指标共振'
            elif 'PSAR趋势' in name or 'PSAR趋势动量' in name:
                family = 'PSAR趋势动量'
            elif 'KAMA' in name:
                family = 'KAMA突破'
            else:
                family = 'other'

            if family not in families:
                families[family] = []
            families[family].append((s, eid))

    total_strategies = sum(len(v) for v in families.values())
    logger.info(f"Total strategies to process: {total_strategies} across {len(families)} families")

    # Step 4: Process each family
    total_done = 0
    total_invalid = 0
    total_stda_plus = 0
    stda_names = []
    best_score = 0
    best_name = ""
    best_ret = 0
    best_dd = 0

    for family_name, strat_list in families.items():
        logger.info(f"\n--- Processing family: {family_name} ({len(strat_list)} strategies) ---")

        try:
            # Get buy/sell conditions from the first strategy
            first_strat, first_eid = strat_list[0]
            buy_conditions = first_strat.get('buy_conditions', [])
            sell_conditions = first_strat.get('sell_conditions', [])

            if not buy_conditions:
                logger.warning(f"No buy_conditions for {family_name}, skipping")
                continue

            # Create engine and prepare data once for this family
            pe = PortfolioBacktestEngine(
                initial_capital=100000,
                max_positions=10,
                max_position_pct=30,
                slippage_pct=0.1,
            )

            strategy_dict = {
                "buy_conditions": buy_conditions,
                "sell_conditions": sell_conditions,
            }

            t0 = time.time()
            precomputed = pe.prepare_data(strategy_dict, stock_data)
            prep_time = time.time() - t0

            if not precomputed.get("prepared"):
                logger.warning(f"  No prepared data for {family_name}, skipping")
                continue

            logger.info(f"  prepare_data: {prep_time:.1f}s, {len(precomputed['prepared'])} stocks, {len(precomputed['sorted_dates'])} dates")

            # Run each strategy variant
            for strat_data, eid in strat_list:
                sid = strat_data['id']
                sname = strat_data.get('name', f'S{sid}')[:60]

                exit_config = strat_data.get('exit_config', {})
                if not exit_config:
                    exit_config = {'stop_loss_pct': -10, 'take_profit_pct': 15, 'max_hold_days': 30}

                try:
                    cancel_event = threading.Event()
                    timer = threading.Timer(600, cancel_event.set)  # 10 min timeout
                    timer.daemon = True
                    timer.start()

                    try:
                        result = pe.run_with_prepared(
                            strategy_name=sname,
                            exit_config=exit_config,
                            precomputed=precomputed,
                            regime_map=regime_map,
                            cancel_event=cancel_event,
                        )
                    except (SignalExplosionError, BacktestTimeoutError) as e:
                        logger.warning(f"  S{sid} {sname}: {str(e)[:100]}")
                        api_put(f'lab/strategies/{sid}', {'status': 'invalid'})
                        total_invalid += 1
                        continue
                    finally:
                        timer.cancel()

                    if result.total_trades == 0:
                        api_put(f'lab/strategies/{sid}', {'status': 'invalid'})
                        total_invalid += 1
                        logger.info(f"  ✗ S{sid} {sname} -> invalid (0 trades)")
                        continue

                    score = compute_score(result)
                    ret = round(result.total_return_pct, 2)
                    dd = round(abs(result.max_drawdown_pct), 2)
                    trades = result.total_trades

                    # Update via API
                    api_put(f'lab/strategies/{sid}', {
                        'status': 'done',
                        'score': score,
                        'total_return_pct': ret,
                        'max_drawdown_pct': round(result.max_drawdown_pct, 2),
                        'total_trades': trades,
                        'win_rate': round(result.win_rate, 2),
                        'sharpe_ratio': round(result.sharpe_ratio, 4),
                        'regime_stats': result.regime_stats or {},
                    })

                    total_done += 1
                    is_stda = (score >= STDA_PLUS_SCORE and ret > STDA_PLUS_RET
                               and dd < STDA_PLUS_DD and trades >= STDA_PLUS_TRADES)

                    if score > best_score:
                        best_score = score
                        best_name = sname
                        best_ret = ret
                        best_dd = dd

                    if is_stda:
                        total_stda_plus += 1
                        stda_names.append(sname)
                        promote_result = api_post_promote(sid, '[AI]')
                        logger.info(f"  ★ S{sid} {sname} PROMOTED: score={score:.3f} ret={ret:.1f}% dd={dd:.1f}% -> {promote_result.get('message','')}")
                    else:
                        marker = "✓" if score >= 0.70 else "✗"
                        logger.info(f"  {marker} S{sid} score={score:.3f} ret={ret:.1f}% dd={dd:.1f}% trades={trades}")

                except Exception as e:
                    api_put(f'lab/strategies/{sid}', {'status': 'invalid'})
                    total_invalid += 1
                    logger.warning(f"  ✗ S{sid} {sname} -> error: {e}")

        except Exception as family_err:
            logger.error(f"Family {family_name} failed: {family_err}")
            import traceback
            traceback.print_exc()
            continue

    # Mark experiments as done
    for eid in exp_ids:
        api_put(f'lab/experiments/{eid}', {'status': 'done'})

    # Summary
    logger.info(f"\n=== {ROUND_NAME} COMPLETE ===")
    logger.info(f"Total done: {total_done}")
    logger.info(f"Total invalid: {total_invalid}")
    logger.info(f"Total StdA+: {total_stda_plus}")
    logger.info(f"Best: {best_name} score={best_score:.3f} ret={best_ret:.1f}% dd={best_dd:.1f}%")
    if stda_names:
        logger.info(f"StdA+ names: {stda_names}")

    # Save summary
    summary = {
        'round': ROUND_NAME,
        'experiment_ids': list(range(MIN_EXP_ID, MAX_EXP_ID + 1)),
        'total_done': total_done,
        'total_invalid': total_invalid,
        'total_stda': total_stda_plus,
        'stda_names': stda_names,
        'best_name': best_name,
        'best_score': best_score,
        'best_return': best_ret,
        'best_dd': best_dd,
        'timestamp': datetime.now().isoformat()
    }

    with open(f'/tmp/{ROUND_NAME.lower()}_summary.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"Summary saved to /tmp/{ROUND_NAME.lower()}_summary.json")
    session.close()


if __name__ == '__main__':
    main()
