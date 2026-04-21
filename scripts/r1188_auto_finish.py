"""R1188 auto-finish: Poll E9007-E9528 (522 experiments, 4176 strategies).

Run: nohup python3 scripts/r1188_auto_finish.py > /tmp/r1188_finish.log 2>&1 &
"""

import subprocess
import json
import time
import urllib.parse
from datetime import datetime

EXPERIMENT_IDS = list(range(9007, 9529))
ROUND_NUMBER = 1188
STARTED_AT = "2026-03-18T22:46:00"


def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def api_post(path, data=None):
    cmd = ['curl', '-s', '-X', 'POST', f'http://127.0.0.1:8050/api/{path}']
    if data:
        cmd += ['-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def api_put(path, data):
    for attempt in range(3):
        r = subprocess.run(
            ['curl', '-s', '-X', 'PUT', f'http://127.0.0.1:8050/api/{path}',
             '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
            capture_output=True, text=True,
            env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
        try:
            result = json.loads(r.stdout)
            if 'error' not in str(result).lower():
                return result
        except json.JSONDecodeError:
            pass
        time.sleep(2)
    return {}


def poll_until_done(max_wait_minutes=20000):
    """Poll experiments. At ~4min/strategy × 4176 = ~278h."""
    start = time.time()
    while time.time() - start < max_wait_minutes * 60:
        # Sample every 10th experiment to avoid excessive API calls
        total = 0
        done = 0
        sample_ids = EXPERIMENT_IDS[::10]  # Every 10th
        for eid in sample_ids:
            exp = api_get(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            for s in strats:
                total += 1
                if s.get('status') in ('done', 'invalid', 'failed'):
                    done += 1

        # Scale up to estimate total
        scale = len(EXPERIMENT_IDS) / len(sample_ids)
        est_total = int(total * scale)
        est_done = int(done * scale)
        pct = est_done / est_total * 100 if est_total else 0
        elapsed = (time.time() - start) / 3600

        print(f"[{elapsed:.1f}h] ~{est_done}/{est_total} ({pct:.1f}%) [sampled {len(sample_ids)} exps]", flush=True)

        if pct >= 99:
            # Full count for final check
            total = done = 0
            for eid in EXPERIMENT_IDS:
                exp = api_get(f'lab/experiments/{eid}')
                for s in exp.get('strategies', []):
                    total += 1
                    if s.get('status') in ('done', 'invalid', 'failed'):
                        done += 1
            if done >= total and total > 0:
                print(f"All {total} strategies complete!", flush=True)
                return True

        time.sleep(300)  # Check every 5 minutes

    print(f"Timeout after {max_wait_minutes}m", flush=True)
    return False


def analyze_and_promote():
    """Analyze results and promote StdA+ strategies."""
    total_strats = 0
    done_strats = 0
    invalid_strats = 0
    stda_count = 0
    promoted_list = []
    best_score = 0
    best_name = ""
    best_return = 0
    best_dd = 0

    for eid in EXPERIMENT_IDS:
        exp = api_get(f'lab/experiments/{eid}')
        for s in exp.get('strategies', []):
            total_strats += 1
            if s.get('status') == 'invalid':
                invalid_strats += 1
                continue
            if s.get('status') != 'done':
                continue
            done_strats += 1

            score = s.get('score', 0) or 0
            ret = s.get('total_return_pct', 0) or 0
            dd = abs(s.get('max_drawdown_pct', 100) or 100)
            trades = s.get('total_trades', 0) or 0
            wr = s.get('win_rate', 0) or 0

            if score > best_score:
                best_score = score
                best_name = s.get('name', '?')[:60]
                best_return = ret
                best_dd = dd

            if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                stda_count += 1
                sid = s['id']
                encoded_label = urllib.parse.quote('[AI]')
                cat = urllib.parse.quote('全能')
                result = api_post(f'lab/strategies/{sid}/promote?label={encoded_label}&category={cat}')
                msg = result.get('message', '')
                if msg != 'Already promoted':
                    promoted_list.append({
                        'id': sid,
                        'name': s.get('name', '?')[:60],
                        'label': '[AI]',
                        'score': score,
                    })
                    print(f"  PROMOTED: S{sid} score={score:.4f} ret={ret:.1f}% wr={wr:.1f}%", flush=True)

    stda_pct = stda_count / done_strats * 100 if done_strats else 0

    print(f"\n=== R{ROUND_NUMBER} Analysis ===", flush=True)
    print(f"Total: {total_strats}, Done: {done_strats}, Invalid: {invalid_strats}", flush=True)
    print(f"StdA+: {stda_count} ({stda_pct:.1f}%)", flush=True)
    print(f"Best: {best_name} score={best_score:.4f} ret={best_return:.1f}% dd={best_dd:.1f}%", flush=True)
    print(f"Promoted: {len(promoted_list)} new strategies", flush=True)

    # Rebalance pool
    dry = api_post('strategies/pool/rebalance', None)
    print(f"Pool rebalance: {dry}", flush=True)

    # Save exploration round
    finished_at = datetime.now().isoformat()
    round_data = {
        "round_number": ROUND_NUMBER,
        "mode": "auto",
        "started_at": STARTED_AT,
        "finished_at": finished_at,
        "experiment_ids": list(EXPERIMENT_IDS),
        "total_experiments": len(EXPERIMENT_IDS),
        "total_strategies": done_strats + invalid_strats,
        "profitable_count": stda_count,
        "profitability_pct": stda_pct,
        "std_a_count": stda_count,
        "best_strategy_name": best_name,
        "best_strategy_score": best_score,
        "best_strategy_return": best_return,
        "best_strategy_dd": best_dd,
        "insights": [
            f"522 experiments, {done_strats} done, {invalid_strats} invalid, {stda_count} StdA+ ({stda_pct:.1f}%)",
            f"Best: {best_name} score={best_score:.4f}",
            "Parameter space: RSI(14/16/18/20) × ATR(0.0875/0.09/0.10) × AbvMin(3-25) × 5 sell conditions",
        ],
        "promoted": promoted_list[:50],
        "issues_resolved": [],
        "next_suggestions": [
            "Analyze which parameter combos produce highest StdA+ rate",
            "Focus on best-performing sell conditions for next round",
            "Optimize MACD+RSI skeleton if it produces StdA+",
        ],
        "summary": f"R{ROUND_NUMBER}: 522 exps ({done_strats}+{invalid_strats} strats), {stda_count} StdA+ ({stda_pct:.1f}%). Best={best_name} score={best_score:.4f}",
        "memory_synced": False,
        "pinecone_synced": False,
    }
    result = api_post('lab/exploration-rounds', round_data)
    print(f"Exploration round saved: {result.get('id', '?')}", flush=True)

    # Save summary
    with open('/tmp/r1188_summary.json', 'w') as f:
        json.dump({
            'round_number': ROUND_NUMBER,
            'total': total_strats,
            'done': done_strats,
            'invalid': invalid_strats,
            'stda': stda_count,
            'stda_pct': stda_pct,
            'best_name': best_name,
            'best_score': best_score,
            'best_return': best_return,
            'best_dd': best_dd,
            'promoted': promoted_list,
        }, f, indent=2)

    return stda_count


def main():
    print(f"=== R{ROUND_NUMBER} Auto-Finish Started: {datetime.now().isoformat()} ===", flush=True)
    print(f"Monitoring {len(EXPERIMENT_IDS)} experiments (E{EXPERIMENT_IDS[0]}-E{EXPERIMENT_IDS[-1]})", flush=True)

    poll_until_done()
    stda = analyze_and_promote()

    print(f"\n=== R{ROUND_NUMBER} Complete: {datetime.now().isoformat()} ===", flush=True)
    print(f"StdA+ promoted: {stda}", flush=True)


if __name__ == "__main__":
    main()
