#!/usr/bin/env python3
"""R1189 auto_finish: Monitor backtests, promote StdA+, update exploration round.

Usage: nohup python3 scripts/r1189_auto_finish.py > /tmp/r1189_auto_finish.log 2>&1 &
"""

import subprocess
import json
import time
import urllib.parse
from datetime import datetime

API_BASE = "http://127.0.0.1:8050/api"


def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'{API_BASE}/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {}


def api_post(path, data=None):
    cmd = ['curl', '-s', '-X', 'POST', f'{API_BASE}/{path}']
    if data:
        cmd += ['-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {'error': r.stdout[:200]}


def api_put(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'PUT', f'{API_BASE}/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {'error': r.stdout[:200]}


def promote(sid, label):
    encoded_label = urllib.parse.quote(label)
    cat_map = {'[AI]': '全能', '[AI-牛市]': '牛市', '[AI-熊市]': '熊市', '[AI-震荡]': '震荡'}
    cat = urllib.parse.quote(cat_map.get(label, ''))
    return api_post(f'lab/strategies/{sid}/promote?label={encoded_label}&category={cat}')


def check_progress(experiment_ids):
    """Check overall progress of all experiments."""
    total_strats = 0
    done_strats = 0
    stda_count = 0
    best_score = 0
    best_name = ""
    best_return = 0

    for eid in experiment_ids:
        exp = api_get(f'lab/experiments/{eid}')
        for s in exp.get('strategies', []):
            total_strats += 1
            if s.get('status') in ('done', 'invalid', 'failed'):
                done_strats += 1
            if s.get('status') == 'done':
                score = s.get('score', 0) or 0
                ret = s.get('total_return_pct', 0) or 0
                dd = abs(s.get('max_drawdown_pct', 100) or 100)
                trades = s.get('total_trades', 0) or 0
                wr = s.get('win_rate', 0) or 0
                if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                    stda_count += 1
                if score > best_score:
                    best_score = score
                    best_name = s.get('name', '')[:80]
                    best_return = ret

    return {
        'total': total_strats,
        'done': done_strats,
        'stda': stda_count,
        'best_score': best_score,
        'best_name': best_name,
        'best_return': best_return,
        'pct': round(done_strats / max(total_strats, 1) * 100, 1),
    }


def promote_all(experiment_ids):
    """Promote all qualifying strategies."""
    promoted = []
    for eid in experiment_ids:
        exp = api_get(f'lab/experiments/{eid}')
        for s in exp.get('strategies', []):
            if s.get('status') != 'done':
                continue
            if s.get('promoted'):
                continue
            score = s.get('score', 0) or 0
            ret = s.get('total_return_pct', 0) or 0
            dd = abs(s.get('max_drawdown_pct', 100) or 100)
            trades = s.get('total_trades', 0) or 0
            wr = s.get('win_rate', 0) or 0
            if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                result = promote(s['id'], '[AI]')
                msg = result.get('message', '')
                if msg != 'Already promoted':
                    promoted.append({
                        'id': s['id'],
                        'name': s.get('name', '')[:80],
                        'label': '[AI]',
                        'score': score,
                    })
    return promoted


def main():
    # Load experiment IDs
    try:
        with open('/tmp/r1189_experiment_ids.json') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("ERROR: /tmp/r1189_experiment_ids.json not found. Run r1189_batch.py first.")
        return

    experiment_ids = data['experiment_ids']
    start_time = data['start_time']
    total_experiments = len(experiment_ids)

    print(f"R1189 Auto-Finish — {datetime.now()}")
    print(f"Monitoring {total_experiments} experiments")
    print()

    # Poll until all done
    poll_interval = 120  # 2 minutes
    max_polls = 600  # 600 × 2min = 20 hours max

    for poll in range(max_polls):
        progress = check_progress(experiment_ids)
        elapsed_min = poll * poll_interval / 60
        print(f"[{datetime.now().strftime('%H:%M')}] [{elapsed_min:.0f}m] "
              f"{progress['done']}/{progress['total']} ({progress['pct']}%) "
              f"StdA+={progress['stda']} best={progress['best_score']:.4f}")

        if progress['done'] >= progress['total']:
            print(f"\n=== All strategies complete! ===")
            break

        time.sleep(poll_interval)
    else:
        print(f"\n=== Timeout after {max_polls * poll_interval / 3600:.1f}h ===")

    # Final analysis
    print(f"\nFinal analysis...")
    final = check_progress(experiment_ids)

    # Promote all qualifying strategies
    print(f"Promoting StdA+ strategies...")
    promoted = promote_all(experiment_ids)
    print(f"  Promoted {len(promoted)} new strategies")

    # Rebalance pool
    print(f"Rebalancing pool...")
    result = api_post('strategies/pool/rebalance?max_per_family=15')
    print(f"  Archived {result.get('archived_count', 0)} redundant strategies")

    # Create/update exploration round
    round_data = {
        "round_number": 1189,
        "mode": "auto",
        "started_at": start_time,
        "finished_at": datetime.now().isoformat(),
        "experiment_ids": experiment_ids,
        "total_experiments": total_experiments,
        "total_strategies": final['total'],
        "profitable_count": final['stda'],
        "profitability_pct": round(final['stda'] / max(final['done'], 1) * 100, 1),
        "std_a_count": final['stda'],
        "best_strategy_name": final['best_name'],
        "best_strategy_score": final['best_score'],
        "best_strategy_return": final['best_return'],
        "best_strategy_dd": 0,
        "insights": [
            f"{total_experiments} experiments, {final['done']} done, {final['stda']} StdA+ ({final['stda']/max(final['done'],1)*100:.1f}%)",
            f"Best: {final['best_name'][:60]} score={final['best_score']:.4f}",
            f"Skeletons: MACD+RSI(200), 三指標(80), VPT+PSAR(60), RSI+KDJ(80), 全指標(80)",
        ],
        "promoted": promoted[:50],
        "issues_resolved": [],
        "next_suggestions": [
            "Analyze which skeleton produced highest StdA+ rate",
            "Focus on best-performing buy condition combos for next round",
            "Fill remaining skeleton gaps based on R1189 results",
        ],
        "summary": f"R1189: {total_experiments} experiments, {final['total']} strategies, {final['stda']} StdA+ ({final['stda']/max(final['done'],1)*100:.1f}%). Best: {final['best_name'][:60]} score={final['best_score']:.4f}",
        "memory_synced": False,
        "pinecone_synced": False,
    }

    result = api_post('lab/exploration-rounds', round_data)
    round_id = result.get('id')
    print(f"Exploration round saved: id={round_id}")

    # Save summary
    summary = {
        'round': 1189,
        'experiments': total_experiments,
        'strategies': final['total'],
        'done': final['done'],
        'stda_count': final['stda'],
        'best_score': final['best_score'],
        'best_name': final['best_name'],
        'best_return': final['best_return'],
        'promoted_count': len(promoted),
        'promoted': promoted[:20],
    }
    with open('/tmp/r1189_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nSummary saved to /tmp/r1189_summary.json")
    print(f"\n{'='*60}")
    print(f"R1189 COMPLETE")
    print(f"  Experiments: {total_experiments}")
    print(f"  Strategies: {final['done']}/{final['total']}")
    print(f"  StdA+: {final['stda']}")
    print(f"  Best: {final['best_name'][:60]} score={final['best_score']:.4f}")
    print(f"  Promoted: {len(promoted)} new strategies")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
