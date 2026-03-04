#!/usr/bin/env python3
"""R43 auto-finish script. Monitors, promotes, saves round record."""
import subprocess, json, time, urllib.parse
from datetime import datetime

ROUND = 43
EXP_IDS = [3333, 3334, 3335, 3336]
STARTED_AT = datetime.now().isoformat()
POLL_INTERVAL = 60
MIN_SCORE, MIN_RETURN, MAX_DD, MIN_TRADES = 0.75, 60.0, 18.0, 50

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
    print(f"[{datetime.now()}] R43 monitor started", flush=True)
    while True:
        all_done = True
        parts = []
        for eid in EXP_IDS:
            exp = api(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            done = sum(1 for s in strats if s.get('status') in ('done','invalid','failed'))
            parts.append(f"E{eid}:{done}/{len(strats)}")
            if done < len(strats): all_done = False
        print(f"[{datetime.now()}] {' | '.join(parts)}", flush=True)
        if all_done: break
        time.sleep(POLL_INTERVAL)

    print(f"[{datetime.now()}] All done. Analyzing...", flush=True)
    total_done = total_stda = new_promoted = 0
    best_score = 0; best_name = ""; best_ret = 0; best_dd = 0
    fam_results = {}

    for eid in EXP_IDS:
        exp = api(f'lab/experiments/{eid}')
        strats = exp.get('strategies', [])
        fd = fs = 0
        for s in strats:
            if s.get('status') != 'done': continue
            fd += 1
            sc = s.get('score',0) or 0
            rt = s.get('total_return_pct',0) or 0
            dd = abs(s.get('max_drawdown_pct',0) or 0)
            tr = s.get('total_trades',0) or 0
            if sc >= MIN_SCORE and rt > MIN_RETURN and dd < MAX_DD and tr >= MIN_TRADES:
                fs += 1
                r = promote(s['id'])
                if r.get('message','') != 'Already promoted': new_promoted += 1
            if sc > best_score:
                best_score=sc; best_name=s.get('name','?'); best_ret=rt; best_dd=dd
        total_done += fd; total_stda += fs
        fam_results[eid] = {'done':fd,'stda':fs,'theme':exp.get('theme','?')[:40]}

    finished_at = datetime.now().isoformat()
    for eid, f in fam_results.items():
        print(f"  E{eid} {f['theme']}: {f['done']} done, {f['stda']} StdA+", flush=True)
    print(f"Total: {total_done} done, {total_stda} StdA+ ({new_promoted} new)", flush=True)

    summary = f"R43: {total_done} strategies, {total_stda} StdA+ ({total_stda/max(total_done,1)*100:.1f}%). Best: {best_name} (score={best_score:.3f})"
    api_post('lab/exploration-rounds', {
        "round_number": ROUND, "mode": "auto",
        "started_at": STARTED_AT, "finished_at": finished_at,
        "experiment_ids": EXP_IDS, "total_experiments": 4,
        "total_strategies": total_done, "profitable_count": total_stda,
        "profitability_pct": total_stda/max(total_done,1)*100,
        "std_a_count": total_stda,
        "best_strategy_name": best_name, "best_strategy_score": best_score,
        "best_strategy_return": best_ret, "best_strategy_dd": best_dd,
        "insights": [summary], "promoted": [],
        "issues_resolved": [], "next_suggestions": [],
        "summary": summary, "memory_synced": False, "pinecone_synced": False,
    })
    with open('/tmp/r43_summary.json','w') as f:
        json.dump({'round':ROUND,'total':total_done,'stda':total_stda,'best_score':best_score,'best_name':best_name,'families':fam_results},f,ensure_ascii=False)
    print(f"[{datetime.now()}] R43 complete. Summary: /tmp/r43_summary.json", flush=True)

if __name__ == '__main__':
    main()
