#!/usr/bin/env python3
"""Auto-finish for R610 (E5210-E5212)."""
import subprocess, json, time, urllib.parse
from datetime import datetime

def api(path):
    r = subprocess.run(['curl','-s',f'http://127.0.0.1:8050/api/{path}'], capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)
def api_post(path, data=None):
    cmd = ['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/{path}']
    if data: cmd += ['-H','Content-Type: application/json','-d',json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)
def promote(sid):
    r = subprocess.run(['curl','-s','-X','POST',f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label=%5BAI%5D&category=%E5%85%A8%E8%83%BD'], capture_output=True, text=True, env={'NO_PROXY':'localhost,127.0.0.1','PATH':'/usr/bin:/bin'})
    return json.loads(r.stdout)

def main():
    started_at = datetime.now().isoformat()
    eids = [5210, 5211, 5212]
    while True:
        all_done = True
        for eid in eids:
            exp = api(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            done = sum(1 for s in strats if s.get('status') in ('done','invalid','failed'))
            print(f'{datetime.now():%H:%M} E{eid}: {done}/{len(strats)}')
            if done < len(strats) or len(strats) == 0: all_done = False
        if all_done: break
        time.sleep(60)

    all_strats = []
    for eid in eids:
        all_strats.extend([s for s in api(f'lab/experiments/{eid}').get('strategies',[]) if s.get('status')=='done'])

    stda = best_sc = best_ret = best_dd = 0; best_name = ""
    for s in all_strats:
        sc=s.get('score',0)or 0; ret=s.get('total_return_pct',0)or 0; dd=abs(s.get('max_drawdown_pct',100)or 100); tr=s.get('total_trades',0)or 0; wr=s.get('win_rate',0)or 0
        if sc>=0.80 and ret>60 and dd<18 and tr>=50 and wr>60: stda+=1; promote(s['id'])
        if sc>best_sc: best_sc=sc; best_name=s.get('name','')[:60]; best_ret=ret; best_dd=dd

    api_post('strategies/pool/rebalance', {"max_per_family": 3})
    valid = len(all_strats)
    summary = f"R610: {valid} strats, {stda} StdA+ ({stda*100//max(valid,1)}%). Best: {best_name} sc={best_sc:.4f}"
    print(summary)
    api_post('lab/exploration-rounds', {"round_number":610,"mode":"time","started_at":started_at,"finished_at":datetime.now().isoformat(),"experiment_ids":eids,"total_experiments":len(eids),"total_strategies":valid,"profitable_count":stda,"profitability_pct":stda/max(valid,1)*100,"std_a_count":stda,"best_strategy_name":best_name,"best_strategy_score":best_sc,"best_strategy_return":best_ret,"best_strategy_dd":best_dd,"insights":[],"promoted":[],"issues_resolved":[],"next_suggestions":[],"summary":summary,"memory_synced":False,"pinecone_synced":False})

if __name__ == '__main__': main()
