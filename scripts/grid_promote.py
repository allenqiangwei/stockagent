"""Shared utility for auto-promoting portfolio-mode StdA+ strategies to the strategy library.

Usage in grid scripts:
    from grid_promote import auto_promote_stda

    result = run_bt(name, buy_conds, sell_conds, exit_cfg)
    if result:
        auto_promote_stda(
            name=result['name'],
            buy_conditions=buy_conds,
            sell_conditions=sell_conds,
            exit_config=exit_cfg,
            metrics=result,
            portfolio_config={'max_positions': 10, 'max_position_pct': 30},
        )
"""

import json
import subprocess


def _api(method, path, data=None):
    """Call local API, return parsed JSON."""
    cmd = ['curl', '-s', '-X', method, f'http://127.0.0.1:8050/api/{path}']
    if data:
        cmd += ['-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {'error': r.stdout or r.stderr}


def is_stda_plus(metrics):
    """Check if metrics meet StdA+ criteria."""
    return (
        metrics.get('score', 0) >= 0.80
        and metrics.get('ret', 0) > 60
        and metrics.get('dd', 100) < 18
        and metrics.get('trades', 0) >= 50
        and metrics.get('wr', 0) > 60
        and metrics.get('plr', 0) >= 1.2
    )


def auto_promote_stda(name, buy_conditions, sell_conditions, exit_config,
                      metrics, portfolio_config=None, category='全能',
                      slippage_pct=0.1, description=''):
    """Promote a portfolio-mode strategy to the strategy library if it meets StdA+.

    Two-step process: POST to create, then PUT to add backtest_summary.

    Returns:
        dict with 'promoted' (bool) and 'detail' (API response or reason)
    """
    if not is_stda_plus(metrics):
        return {'promoted': False, 'detail': 'Does not meet StdA+ criteria'}

    # Prefix with [P] for portfolio-mode, add slippage if non-standard and not already in name
    display_name = f"[P]{name}"
    if slippage_pct != 0.1 and 'slip' not in name:
        display_name += f"_slip{slippage_pct}"

    if not description:
        description = (
            f"Portfolio-mode strategy. "
            f"Score={metrics['score']}, Return={metrics['ret']}%, "
            f"DD={metrics['dd']}%, WR={metrics['wr']}%, "
            f"Trades={metrics['trades']}, Sharpe={metrics.get('sharpe', 'N/A')}"
        )

    backtest_summary = {
        'score': metrics['score'],
        'total_return_pct': metrics['ret'],
        'max_drawdown_pct': -metrics['dd'],  # Store as negative (convention)
        'win_rate': metrics['wr'],
        'total_trades': metrics['trades'],
        'sharpe_ratio': metrics.get('sharpe', 0),
        'profit_loss_ratio': metrics.get('plr', 0),
        'slippage_pct': slippage_pct,
        'mode': 'portfolio',
        'initial_capital': 100000,
    }

    # Step 1: Create strategy
    payload = {
        'name': display_name,
        'description': description,
        'buy_conditions': buy_conditions,
        'sell_conditions': sell_conditions,
        'exit_config': {
            'stop_loss_pct': exit_config.get('stop_loss_pct', -10),
            'take_profit_pct': exit_config.get('take_profit_pct', 2.8),
            'max_hold_days': exit_config.get('max_hold_days', 7),
        },
        'weight': 0.5,
        'enabled': True,
        'portfolio_config': portfolio_config or {'max_positions': 10, 'max_position_pct': 30},
        'category': category,
        'backtest_summary': backtest_summary,
    }

    result = _api('POST', 'strategies', payload)

    if 'id' in result:
        sid = result['id']
        # Step 2: PUT backtest_summary (works even if StrategyCreate ignores it)
        if not result.get('backtest_summary'):
            _api('PUT', f'strategies/{sid}', {'backtest_summary': backtest_summary})
        print(f"  PROMOTED: S{sid} {display_name} "
              f"(score={metrics['score']}, ret={metrics['ret']}%, wr={metrics['wr']}%)")
        return {'promoted': True, 'detail': result}
    elif 'detail' in result and 'already exists' in str(result['detail']):
        print(f"  SKIP (exists): {display_name}")
        return {'promoted': False, 'detail': 'Already exists'}
    else:
        print(f"  ERROR promoting {display_name}: {result}")
        return {'promoted': False, 'detail': result}


def batch_promote(results, buy_conds_map, sell_conds_map, exit_cfg_map,
                  portfolio_config=None, slippage_pct=0.1):
    """Batch promote all StdA+ results from a grid search.

    Args:
        results: Dict of {name: metrics_dict}
        buy_conds_map: Dict of {name: buy_conditions_list}
        sell_conds_map: Dict of {name: sell_conditions_list}
        exit_cfg_map: Dict of {name: exit_config_dict}
        portfolio_config: Shared portfolio config
        slippage_pct: Default slippage (overridden if name contains 'slip')

    Returns:
        Summary dict with counts
    """
    promoted = 0
    skipped = 0
    failed = 0

    for name, metrics in results.items():
        if not is_stda_plus(metrics):
            continue

        slip = slippage_pct
        if 'slip0.08' in name:
            slip = 0.08
        elif 'slip0.05' in name:
            slip = 0.05

        buy = buy_conds_map.get(name, [])
        sell = sell_conds_map.get(name, [])
        exit_cfg = exit_cfg_map.get(name, {})

        r = auto_promote_stda(
            name=name,
            buy_conditions=buy,
            sell_conditions=sell,
            exit_config=exit_cfg,
            metrics=metrics,
            portfolio_config=portfolio_config,
            slippage_pct=slip,
        )

        if r['promoted']:
            promoted += 1
        elif r['detail'] == 'Already exists':
            skipped += 1
        else:
            failed += 1

    total_stda = sum(1 for m in results.values() if is_stda_plus(m))
    print(f"\nAuto-Promote Summary: {total_stda} StdA+ found, "
          f"{promoted} promoted, {skipped} already exist, {failed} failed")
    return {'total_stda': total_stda, 'promoted': promoted,
            'skipped': skipped, 'failed': failed}
