#!/usr/bin/env python3
"""R48 auto-finish script — new indicator exploration round."""
import subprocess, json, time, urllib.parse
from datetime import datetime

ROUND = 48
EXP_IDS = list(range(3352, 3368))  # E3352-E3367 (16 experiments)
STARTED_AT = "2026-03-01T11:35:00"
POLL_INTERVAL = 120  # 2 min polls (128 strategies, serial)
MIN_SCORE, MIN_RETURN, MAX_DD, MIN_TRADES = 0.75, 60.0, 18.0, 50
LOG_FILE = "/tmp/r48_auto_finish.log"

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
    log(f"R48 monitor started ({len(EXP_IDS)} experiments)")

    while True:
        all_done = True
        total_done = total_total = 0
        parts = []
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

    # Analyze results per indicator family
    indicator_results = {
        'MFI': {'eids': [3352,3353,3354,3355], 'done': 0, 'stda': 0, 'invalid': 0, 'best_score': 0, 'best_name': ''},
        'WR':  {'eids': [3356,3357,3358,3359], 'done': 0, 'stda': 0, 'invalid': 0, 'best_score': 0, 'best_name': ''},
        'ROC': {'eids': [3360,3361,3362,3363], 'done': 0, 'stda': 0, 'invalid': 0, 'best_score': 0, 'best_name': ''},
        'STC': {'eids': [3364,3365,3366,3367], 'done': 0, 'stda': 0, 'invalid': 0, 'best_score': 0, 'best_name': ''},
    }

    total_done = total_stda = new_promoted = total_invalid = 0
    best_score = 0; best_name = ""; best_ret = 0; best_dd = 0

    for eid in EXP_IDS:
        exp = api(f'lab/experiments/{eid}')
        strats = exp.get('strategies', [])
        theme = exp.get('theme', '?')

        # Determine indicator family
        ind_family = None
        for ind, info in indicator_results.items():
            if eid in info['eids']:
                ind_family = ind
                break

        for s in strats:
            if s.get('status') == 'invalid':
                total_invalid += 1
                if ind_family:
                    indicator_results[ind_family]['invalid'] += 1
                continue
            if s.get('status') != 'done':
                continue

            sc = s.get('score',0) or 0
            rt = s.get('total_return_pct',0) or 0
            dd = abs(s.get('max_drawdown_pct',0) or 0)
            tr = s.get('total_trades',0) or 0

            if ind_family:
                indicator_results[ind_family]['done'] += 1
            total_done += 1

            if sc >= MIN_SCORE and rt > MIN_RETURN and dd < MAX_DD and tr >= MIN_TRADES:
                total_stda += 1
                if ind_family:
                    indicator_results[ind_family]['stda'] += 1
                r = promote(s['id'])
                if r.get('message','') != 'Already promoted':
                    new_promoted += 1

            if sc > best_score:
                best_score = sc; best_name = s.get('name','?'); best_ret = rt; best_dd = dd
            if ind_family and sc > indicator_results[ind_family]['best_score']:
                indicator_results[ind_family]['best_score'] = sc
                indicator_results[ind_family]['best_name'] = s.get('name','?')[:50]

    finished_at = datetime.now().isoformat()

    # Log per-indicator results
    for ind, info in indicator_results.items():
        total_gen = info['done'] + info['invalid']
        rate = f"{info['stda']/max(info['done'],1)*100:.0f}%" if info['done'] > 0 else "N/A"
        log(f"  {ind}: {info['done']} done, {info['invalid']} invalid, {info['stda']} StdA+ ({rate}), best={info['best_score']:.3f}")

    log(f"Total: {total_done} done, {total_invalid} invalid, {total_stda} StdA+ ({new_promoted} new)")
    log(f"Best: {best_name} (score={best_score:.3f}, ret={best_ret:+.1f}%)")

    summary = f"R48 (NEW INDICATORS): {total_done} strategies done, {total_invalid} invalid, {total_stda} StdA+. Best: {best_name} (score={best_score:.3f})"

    api_post('lab/exploration-rounds', {
        "round_number": ROUND, "mode": "auto",
        "started_at": STARTED_AT, "finished_at": finished_at,
        "experiment_ids": EXP_IDS, "total_experiments": len(EXP_IDS),
        "total_strategies": total_done, "profitable_count": total_stda,
        "profitability_pct": total_stda/max(total_done,1)*100,
        "std_a_count": total_stda,
        "best_strategy_name": best_name, "best_strategy_score": best_score,
        "best_strategy_return": best_ret, "best_strategy_dd": best_dd,
        "insights": [
            summary,
            f"MFI: {indicator_results['MFI']['stda']} StdA+",
            f"WR: {indicator_results['WR']['stda']} StdA+",
            f"ROC: {indicator_results['ROC']['stda']} StdA+",
            f"STC: {indicator_results['STC']['stda']} StdA+",
        ],
        "promoted": [], "issues_resolved": [],
        "next_suggestions": ["Grid search on any StdA+ indicator combos from R48"],
        "summary": summary, "memory_synced": False, "pinecone_synced": False,
    })

    with open('/tmp/r48_summary.json','w') as f:
        json.dump({
            'round': ROUND, 'total_done': total_done, 'total_invalid': total_invalid,
            'stda': total_stda, 'best_score': best_score, 'best_name': best_name,
            'indicators': {k: {'done': v['done'], 'invalid': v['invalid'], 'stda': v['stda'],
                              'best_score': v['best_score'], 'best_name': v['best_name']}
                          for k, v in indicator_results.items()}
        }, f, ensure_ascii=False)

    log(f"R48 complete. Summary: /tmp/r48_summary.json")

if __name__ == '__main__':
    main()
