#!/usr/bin/env python3
"""R49 auto-finish script — cross-family hybrid exploration."""
import subprocess, json, time, urllib.parse
from datetime import datetime

ROUND = 49
EXP_IDS = list(range(3368, 3380))  # E3368-E3379 (12 experiments)
STARTED_AT = "2026-03-01T12:50:00"
POLL_INTERVAL = 120
MIN_SCORE, MIN_RETURN, MAX_DD, MIN_TRADES = 0.75, 60.0, 18.0, 50
LOG_FILE = "/tmp/r49_auto_finish.log"

def log(msg):
    line = f"[{datetime.now()}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def api_post(path, data=None):
    cmd = ['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/{path}']
    if data: cmd += ['-H','Content-Type: application/json','-d',json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def promote(sid):
    label = urllib.parse.quote('[AI]')
    cat = urllib.parse.quote('全能')
    return api_post(f'lab/strategies/{sid}/promote?label={label}&category={cat}')

def main():
    log(f"R49 monitor started ({len(EXP_IDS)} experiments)")

    while True:
        all_done = True
        total_done = total_total = 0
        for eid in EXP_IDS:
            exp = api(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            total = len(strats)
            done = sum(1 for s in strats if s.get('status') in ('done','invalid','failed'))
            total_done += done
            total_total += total
            if exp.get('status') not in ('done','failed'):
                all_done = False
        log(f"Progress: {total_done}/{total_total} strategies done")
        if all_done:
            break
        time.sleep(POLL_INTERVAL)

    log("All done. Analyzing...")

    total_done = total_stda = new_promoted = total_invalid = 0
    best_score = 0; best_name = ""; best_ret = 0; best_dd = 0
    exp_results = {}

    for eid in EXP_IDS:
        exp = api(f'lab/experiments/{eid}')
        strats = exp.get('strategies', [])
        theme = exp.get('theme', '?')[:50]
        ed = ei = es = 0

        for s in strats:
            if s.get('status') == 'invalid':
                total_invalid += 1; ei += 1
                continue
            if s.get('status') != 'done':
                continue

            sc = s.get('score',0) or 0
            rt = s.get('total_return_pct',0) or 0
            dd = abs(s.get('max_drawdown_pct',0) or 0)
            tr = s.get('total_trades',0) or 0
            ed += 1; total_done += 1

            if sc >= MIN_SCORE and rt > MIN_RETURN and dd < MAX_DD and tr >= MIN_TRADES:
                es += 1; total_stda += 1
                r = promote(s['id'])
                if r.get('message','') != 'Already promoted':
                    new_promoted += 1

            if sc > best_score:
                best_score = sc; best_name = s.get('name','?'); best_ret = rt; best_dd = dd

        exp_results[eid] = {'theme': theme, 'done': ed, 'invalid': ei, 'stda': es}

    finished_at = datetime.now().isoformat()
    for eid, info in exp_results.items():
        rate = f"{info['stda']/max(info['done'],1)*100:.0f}%" if info['done'] > 0 else "N/A"
        log(f"  E{eid} {info['theme']}: {info['done']}done {info['invalid']}inv {info['stda']}StdA+ ({rate})")

    log(f"Total: {total_done} done, {total_invalid} invalid, {total_stda} StdA+ ({new_promoted} new)")
    log(f"Best: {best_name} (score={best_score:.3f}, ret={best_ret:+.1f}%)")

    summary = f"R49 (CROSS-FAMILY): {total_done} done, {total_invalid} invalid, {total_stda} StdA+. Best: {best_name} (score={best_score:.3f})"

    api_post('lab/exploration-rounds', {
        "round_number": ROUND, "mode": "auto",
        "started_at": STARTED_AT, "finished_at": finished_at,
        "experiment_ids": EXP_IDS, "total_experiments": len(EXP_IDS),
        "total_strategies": total_done, "profitable_count": total_stda,
        "profitability_pct": total_stda/max(total_done,1)*100,
        "std_a_count": total_stda,
        "best_strategy_name": best_name, "best_strategy_score": best_score,
        "best_strategy_return": best_ret, "best_strategy_dd": best_dd,
        "insights": [summary],
        "promoted": [], "issues_resolved": [],
        "next_suggestions": ["Grid search any StdA+ combos from R49"],
        "summary": summary, "memory_synced": False, "pinecone_synced": False,
    })

    with open('/tmp/r49_summary.json','w') as f:
        json.dump({
            'round': ROUND, 'total_done': total_done, 'total_invalid': total_invalid,
            'stda': total_stda, 'best_score': best_score, 'best_name': best_name,
            'experiments': exp_results
        }, f, ensure_ascii=False)

    log(f"R49 complete. Summary: /tmp/r49_summary.json")

if __name__ == '__main__':
    main()
