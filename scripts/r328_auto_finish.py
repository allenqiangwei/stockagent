#!/usr/bin/env python3
"""R328 Auto-Finish: Poll E4422, promote StdA+, update exploration round."""
import subprocess, json, time, urllib.parse
from datetime import datetime

EXPERIMENT_ID = 4422
ROUND_NUMBER = 328
STARTED_AT = "2026-03-07T02:00:00"

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True,
                       env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def api_post(path, data):
    r = subprocess.run(['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/{path}',
                        '-H','Content-Type: application/json','-d',json.dumps(data)],
                       capture_output=True, text=True,
                       env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def promote(sid, label):
    encoded_label = urllib.parse.quote(label)
    cat = urllib.parse.quote({'[AI]':'全能'}.get(label, ''))
    r = subprocess.run(['curl','-s','-X','POST',
                        f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label={encoded_label}&category={cat}'],
                       capture_output=True, text=True,
                       env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def main():
    print(f"Polling E{EXPERIMENT_ID}...")
    for i in range(120):
        exp = api(f'lab/experiments/{EXPERIMENT_ID}')
        strats = exp.get('strategies', [])
        done = sum(1 for s in strats if s.get('status') in ('done','invalid','failed'))
        total = len(strats)
        print(f"  {done}/{total} done")
        if done == total:
            break
        time.sleep(60)

    exp = api(f'lab/experiments/{EXPERIMENT_ID}')
    strats = [s for s in exp.get('strategies', []) if s.get('status') == 'done']

    stda_count = 0
    best_score = 0
    best_name = ""
    best_ret = 0
    best_dd = 0
    promoted_list = []

    for s in strats:
        sc = s.get('score',0) or 0
        ret = s.get('total_return_pct',0) or 0
        dd = abs(s.get('max_drawdown_pct',100) or 100)
        tr = s.get('total_trades',0) or 0
        wr = s.get('win_rate',0) or 0

        if sc > best_score:
            best_score = sc
            best_name = s.get('name','')[:60]
            best_ret = ret
            best_dd = dd

        if sc >= 0.75 and ret > 60 and dd < 18 and tr >= 50 and wr > 60:
            stda_count += 1
            result = promote(s['id'], '[AI]')
            msg = result.get('message','')
            if msg != 'Already promoted':
                promoted_list.append({"id": s['id'], "name": s.get('name','')[:40], "label": "[AI]", "score": sc})
                print(f"  PROMOTED: ES{s['id']} sc={sc:.4f} wr={wr:.1f}%")

    valid = len(strats)
    print(f"\nResults: {valid} done, {stda_count} StdA+, best={best_score:.4f}")

    round_data = {
        "round_number": ROUND_NUMBER,
        "mode": "time",
        "started_at": STARTED_AT,
        "finished_at": datetime.now().isoformat(),
        "experiment_ids": [EXPERIMENT_ID],
        "total_experiments": 1,
        "total_strategies": valid,
        "profitable_count": stda_count,
        "profitability_pct": stda_count / valid * 100 if valid else 0,
        "std_a_count": stda_count,
        "best_strategy_name": best_name,
        "best_strategy_score": best_score,
        "best_strategy_return": best_ret,
        "best_strategy_dd": best_dd,
        "insights": ["R328 auto-finished by background script"],
        "promoted": promoted_list[:5],
        "issues_resolved": [],
        "next_suggestions": [],
        "summary": f"R328 (auto-finish): {valid} strategies, {stda_count} StdA+, best={best_score:.4f}",
        "memory_synced": False,
        "pinecone_synced": False,
    }
    result = api_post('lab/exploration-rounds', round_data)
    print(f"Round saved: {json.dumps(result)[:200]}")

if __name__ == '__main__':
    main()
