#!/usr/bin/env python3
"""R1190 auto_finish — monitor experiments, promote StdA+, rebalance pool."""
import subprocess, json, time, logging, urllib.parse
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('/tmp/r1190_auto_finish.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def api(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {}

def api_post(path, data=None):
    cmd = ['curl', '-s', '-X', 'POST', f'http://127.0.0.1:8050/api/{path}']
    if data:
        cmd += ['-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {}

def api_put(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'PUT', f'http://127.0.0.1:8050/api/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    try:
        return json.loads(r.stdout)
    except:
        return {}

def promote(sid, label='[AI]'):
    encoded_label = urllib.parse.quote(label)
    cat = urllib.parse.quote({'[AI]': '全能'}.get(label, ''))
    return api_post(f'lab/strategies/{sid}/promote?label={encoded_label}&category={cat}')

def main():
    started_at = datetime.now().isoformat()
    
    # Get all experiments from E11855 onwards
    all_exps = api('lab/experiments?page=1&size=50')
    items = all_exps.get('items', [])
    exp_ids = [e['id'] for e in items if e['id'] >= 11855]
    log.info(f"Monitoring {len(exp_ids)} experiments (E{min(exp_ids)}-E{max(exp_ids)})")
    
    # Poll until all done
    max_polls = 360  # 6 hours max
    for poll in range(max_polls):
        pending = []
        done_count = 0
        for eid in exp_ids:
            exp = api(f'lab/experiments/{eid}')
            status = exp.get('status', '?')
            if status in ('done', 'failed'):
                done_count += 1
            else:
                pending.append(eid)
        
        log.info(f"Poll {poll+1}: {done_count}/{len(exp_ids)} done, {len(pending)} pending")
        
        if not pending:
            break
        
        time.sleep(60)
    
    # Analyze and promote
    log.info("All experiments done. Analyzing...")
    total_strats = 0
    stda_count = 0
    promoted_count = 0
    best_score = 0
    best_name = ""
    best_ret = 0
    best_dd = 0
    
    for eid in exp_ids:
        exp = api(f'lab/experiments/{eid}')
        for s in exp.get('strategies', []):
            if s.get('status') != 'done':
                continue
            total_strats += 1
            score = s.get('score', 0) or 0
            ret = s.get('total_return_pct', 0) or 0
            dd = abs(s.get('max_drawdown_pct', 100) or 100)
            trades = s.get('total_trades', 0) or 0
            wr = s.get('win_rate', 0) or 0
            
            if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                stda_count += 1
                result = promote(s['id'])
                if result.get('message', '') != 'Already promoted':
                    promoted_count += 1
            
            if score > best_score:
                best_score = score
                best_name = s.get('name', '')[:80]
                best_ret = ret
                best_dd = dd
    
    log.info(f"Results: {total_strats} strategies, {stda_count} StdA+, {promoted_count} new promotes")
    log.info(f"Best: {best_name} score={best_score:.4f} ret={best_ret:.1f}%")
    
    # Rebalance pool
    result = api_post('strategies/pool/rebalance?max_per_family=15')
    log.info(f"Rebalance: {result}")
    
    # Update exploration round
    api_put('lab/exploration-rounds/934', {  # Will need correct ID
        "round_number": 1190,
        "mode": "auto",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
        "experiment_ids": exp_ids,
        "total_experiments": len(exp_ids),
        "total_strategies": total_strats,
        "profitable_count": stda_count,
        "profitability_pct": round(stda_count / max(total_strats, 1) * 100, 1),
        "std_a_count": stda_count,
        "best_strategy_name": best_name,
        "best_strategy_score": best_score,
        "best_strategy_return": best_ret,
        "best_strategy_dd": best_dd,
        "insights": [f"{stda_count} StdA+ from {total_strats} strategies"],
        "promoted": [],
        "issues_resolved": [],
        "next_suggestions": ["Analyze W_ weekly indicator results", "Deep-dive best new skeletons"],
        "summary": f"R1190: {len(exp_ids)} exp, {total_strats} strats, {stda_count} StdA+ ({round(stda_count/max(total_strats,1)*100,1)}%), best {best_score:.4f}",
        "memory_synced": False,
        "pinecone_synced": False
    })
    
    log.info("R1190 auto_finish complete!")

if __name__ == '__main__':
    main()
