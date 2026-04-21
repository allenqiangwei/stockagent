#!/usr/bin/env python3
"""R1192 auto_finish."""
import subprocess, json, time, logging, urllib.parse
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler('/tmp/r1192_auto_finish.log'), logging.StreamHandler()])
log = logging.getLogger(__name__)

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    try: return json.loads(r.stdout)
    except: return {}

def api_post(path, data=None):
    cmd = ['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/{path}']
    if data: cmd += ['-H','Content-Type: application/json','-d',json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    try: return json.loads(r.stdout)
    except: return {}

def api_put(path, data):
    r = subprocess.run(['curl','-s','-X','PUT',f'http://127.0.0.1:8050/api/{path}',
        '-H','Content-Type: application/json','-d',json.dumps(data)],
        capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    try: return json.loads(r.stdout)
    except: return {}

def promote(sid):
    el = urllib.parse.quote('[AI]')
    return api_post(f'lab/strategies/{sid}/promote?label={el}&category=%E5%85%A8%E8%83%BD')

def main():
    started_at = datetime.now().isoformat()
    with open('/tmp/r1192_exp_ids.json') as f:
        exp_ids = json.load(f)
    log.info(f"Monitoring {len(exp_ids)} experiments")

    for poll in range(720):
        pending = [eid for eid in exp_ids if api(f'lab/experiments/{eid}').get('status') not in ('done','failed')]
        done_count = len(exp_ids) - len(pending)
        if poll % 10 == 0:
            log.info(f"Poll {poll+1}: {done_count}/{len(exp_ids)} done")
        if not pending: break
        time.sleep(60)

    log.info("Analyzing...")
    total, stda, promoted_new = 0, 0, 0
    best_score, best_name, best_ret, best_dd = 0, "", 0, 0

    for eid in exp_ids:
        for s in api(f'lab/experiments/{eid}').get('strategies', []):
            if s.get('status') != 'done': continue
            total += 1
            sc = s.get('score',0) or 0
            ret = s.get('total_return_pct',0) or 0
            dd = abs(s.get('max_drawdown_pct',100) or 100)
            trades = s.get('total_trades',0) or 0
            wr = s.get('win_rate',0) or 0
            if sc >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                stda += 1
                r = promote(s['id'])
                if r.get('message','') != 'Already promoted': promoted_new += 1
            if sc > best_score:
                best_score, best_name, best_ret, best_dd = sc, s.get('name','')[:80], ret, dd

    log.info(f"Results: {total} strats, {stda} StdA+, {promoted_new} new promotes, best {best_score:.4f}")
    api_post('strategies/pool/rebalance?max_per_family=15')
    
    api_put('lab/exploration-rounds/936', {
        "round_number": 1192, "mode": "auto",
        "started_at": started_at, "finished_at": datetime.now().isoformat(),
        "experiment_ids": exp_ids, "total_experiments": len(exp_ids),
        "total_strategies": total, "profitable_count": stda,
        "profitability_pct": round(stda/max(total,1)*100,1),
        "std_a_count": stda, "best_strategy_name": best_name,
        "best_strategy_score": best_score, "best_strategy_return": best_ret,
        "best_strategy_dd": best_dd,
        "insights": [f"{stda} StdA+ from targeted family filling"],
        "promoted": [], "issues_resolved": [],
        "next_suggestions": ["Check pool gap changes after rebalance"],
        "summary": f"R1192: {len(exp_ids)} exp, {total} strats, {stda} StdA+, best {best_score:.4f}",
        "memory_synced": False, "pinecone_synced": False
    })
    log.info("R1192 complete!")

if __name__ == '__main__':
    main()
