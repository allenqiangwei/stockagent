"""R1187 auto-finish: Poll experiments, analyze results, promote StdA+ strategies.

Run in background: nohup python3 scripts/r1187_auto_finish.py > /tmp/r1187.log 2>&1 &
"""

import subprocess
import json
import time
import sys
import urllib.parse
from datetime import datetime

EXPERIMENT_IDS = list(range(8950, 9000))  # E8950-E8999 (v2 batch with correct source ES20989)
ROUND_NUMBER = 1187
STARTED_AT = "2026-03-18T07:50:05"

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


def poll_until_done(max_wait_minutes=1800):
    """Poll all experiments until done. Returns when all complete or timeout."""
    start = time.time()
    while time.time() - start < max_wait_minutes * 60:
        total = 0
        done = 0
        for eid in EXPERIMENT_IDS:
            exp = api_get(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            for s in strats:
                total += 1
                if s.get('status') in ('done', 'invalid', 'failed'):
                    done += 1

        pct = done / total * 100 if total else 0
        elapsed = (time.time() - start) / 60
        print(f"[{elapsed:.0f}m] {done}/{total} strategies complete ({pct:.1f}%)")

        if done >= total and total > 0:
            print("All strategies complete!")
            return True

        time.sleep(120)  # Check every 2 minutes

    print(f"Timeout after {max_wait_minutes}m")
    return False


def analyze_and_promote():
    """Analyze results and promote StdA+ strategies."""
    LABEL_TO_CATEGORY = {'[AI]': '全能'}

    total_strats = 0
    done_strats = 0
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
            if s.get('status') != 'done':
                continue
            done_strats += 1

            score = s.get('score', 0) or 0
            ret = s.get('total_return_pct', 0) or 0
            dd = abs(s.get('max_drawdown_pct', 100) or 100)
            trades = s.get('total_trades', 0) or 0
            wr = s.get('win_rate', 0) or 0

            # Track best
            if score > best_score:
                best_score = score
                best_name = s.get('name', '?')[:60]
                best_return = ret
                best_dd = dd

            # StdA+ criteria
            if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                stda_count += 1
                # Promote
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
                    print(f"  PROMOTED: S{sid} {s.get('name','?')[:50]} score={score:.4f} ret={ret:.1f}% wr={wr:.1f}%")

    stda_pct = stda_count / done_strats * 100 if done_strats else 0

    print(f"\n=== R{ROUND_NUMBER} Analysis ===")
    print(f"Total: {total_strats}, Done: {done_strats}, StdA+: {stda_count} ({stda_pct:.1f}%)")
    print(f"Best: {best_name} score={best_score:.4f} ret={best_return:.1f}% dd={best_dd:.1f}%")
    print(f"Promoted: {len(promoted_list)} new strategies")

    # Rebalance pool
    dry = api_post('strategies/pool/rebalance', None)
    print(f"Pool rebalance: {dry}")

    # Save exploration round
    finished_at = datetime.now().isoformat()
    round_data = {
        "round_number": ROUND_NUMBER,
        "mode": "auto",
        "started_at": STARTED_AT,
        "finished_at": finished_at,
        "experiment_ids": EXPERIMENT_IDS,
        "total_experiments": len(EXPERIMENT_IDS),
        "total_strategies": done_strats,
        "profitable_count": stda_count,
        "profitability_pct": stda_pct,
        "std_a_count": stda_count,
        "best_strategy_name": best_name,
        "best_strategy_score": best_score,
        "best_strategy_return": best_return,
        "best_strategy_dd": best_dd,
        "insights": [
            f"50 experiments, {done_strats} strategies, {stda_count} StdA+ ({stda_pct:.1f}%)",
            f"Best: {best_name} score={best_score:.4f}",
        ],
        "promoted": promoted_list[:20],
        "issues_resolved": [],
        "next_suggestions": [
            "Continue filling _slipN skeleton (gap was 71)",
            "Try RSI period 24/26 if RSI20/22 work well",
            "Explore sell condition variations (lt2dLow, gt10dH, fall2d)",
        ],
        "summary": f"R{ROUND_NUMBER}: {len(EXPERIMENT_IDS)} exps, {done_strats} strats, {stda_count} StdA+ ({stda_pct:.1f}%). Best={best_name} score={best_score:.4f}",
        "memory_synced": False,
        "pinecone_synced": False,
    }
    result = api_post('lab/exploration-rounds', round_data)
    print(f"Exploration round saved: {result.get('id', '?')}")

    # Save summary for next session
    with open('/tmp/r1187_summary.json', 'w') as f:
        json.dump({
            'round_number': ROUND_NUMBER,
            'total': total_strats,
            'done': done_strats,
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
    print(f"=== R{ROUND_NUMBER} Auto-Finish Started: {datetime.now().isoformat()} ===")
    print(f"Monitoring {len(EXPERIMENT_IDS)} experiments (E{EXPERIMENT_IDS[0]}-E{EXPERIMENT_IDS[-1]})")

    # Poll until done
    poll_until_done()

    # Analyze and promote
    stda = analyze_and_promote()

    print(f"\n=== R{ROUND_NUMBER} Complete: {datetime.now().isoformat()} ===")
    print(f"StdA+ promoted: {stda}")


if __name__ == "__main__":
    main()
