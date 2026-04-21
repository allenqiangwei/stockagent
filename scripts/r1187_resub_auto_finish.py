"""R1187 resubmit auto-finish: Monitor E9000-E9006 (AbvMin 1,2,3,5,8,10,16 v2).

Run: nohup python3 scripts/r1187_resub_auto_finish.py > /tmp/r1187_resub.log 2>&1 &
"""

import subprocess
import json
import time
import urllib.parse
from datetime import datetime

EXPERIMENT_IDS = list(range(9000, 9007))
ROUND_LABEL = "R1187-resub"

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


def poll_until_done(max_wait_minutes=600):
    start = time.time()
    while time.time() - start < max_wait_minutes * 60:
        total = done = 0
        for eid in EXPERIMENT_IDS:
            exp = api_get(f'lab/experiments/{eid}')
            for s in exp.get('strategies', []):
                total += 1
                if s.get('status') in ('done', 'invalid', 'failed'):
                    done += 1
        pct = done / total * 100 if total else 0
        elapsed = (time.time() - start) / 60
        print(f"[{elapsed:.0f}m] {done}/{total} ({pct:.1f}%)", flush=True)
        if done >= total and total > 0:
            print("All complete!")
            return True
        time.sleep(120)
    print(f"Timeout after {max_wait_minutes}m")
    return False


def promote_and_report():
    total = done = stda = 0
    promoted = []
    best_score = 0
    best_name = ""
    best_ret = 0
    best_dd = 0

    for eid in EXPERIMENT_IDS:
        exp = api_get(f'lab/experiments/{eid}')
        for s in exp.get('strategies', []):
            total += 1
            if s.get('status') != 'done':
                continue
            done += 1
            score = s.get('score', 0) or 0
            ret = s.get('total_return_pct', 0) or 0
            dd = abs(s.get('max_drawdown_pct', 100) or 100)
            trades = s.get('total_trades', 0) or 0
            wr = s.get('win_rate', 0) or 0

            if score > best_score:
                best_score = score
                best_name = s.get('name', '?')[:60]
                best_ret = ret
                best_dd = dd

            if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                stda += 1
                sid = s['id']
                encoded_label = urllib.parse.quote('[AI]')
                cat = urllib.parse.quote('全能')
                result = api_post(f'lab/strategies/{sid}/promote?label={encoded_label}&category={cat}')
                msg = result.get('message', '')
                if msg != 'Already promoted':
                    promoted.append({'id': sid, 'name': s.get('name', '?')[:60], 'score': score})
                    print(f"  PROMOTED: S{sid} score={score:.4f} ret={ret:.1f}% wr={wr:.1f}%")

    print(f"\n=== {ROUND_LABEL} Results ===")
    print(f"Total: {total}, Done: {done}, StdA+: {stda}")
    print(f"Best: {best_name} score={best_score:.4f} ret={best_ret:.1f}%")
    print(f"Promoted: {len(promoted)} new")

    # Rebalance pool
    api_post('strategies/pool/rebalance', None)

    # Save summary
    with open('/tmp/r1187_resub_summary.json', 'w') as f:
        json.dump({
            'experiments': list(EXPERIMENT_IDS),
            'total': total, 'done': done, 'stda': stda,
            'best_name': best_name, 'best_score': best_score,
            'best_ret': best_ret, 'promoted': promoted,
        }, f, indent=2)


def main():
    print(f"=== {ROUND_LABEL} Monitor Started: {datetime.now().isoformat()} ===")
    poll_until_done()
    promote_and_report()
    print(f"\n=== {ROUND_LABEL} Complete: {datetime.now().isoformat()} ===")


if __name__ == "__main__":
    main()
