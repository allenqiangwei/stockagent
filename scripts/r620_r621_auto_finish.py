#!/usr/bin/env python3
"""Auto-finish script for R620 (E5228), R621 (E5229)."""

import subprocess, json, time, urllib.parse
from datetime import datetime


def api(path):
    r = subprocess.run(['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
                       capture_output=True, text=True,
                       env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)


def api_post(path, data=None):
    cmd = ['curl', '-s', '-X', 'POST', f'http://127.0.0.1:8050/api/{path}']
    if data:
        cmd += ['-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)


def promote(sid):
    label = urllib.parse.quote('[AI]')
    cat = urllib.parse.quote('全能')
    r = subprocess.run(['curl', '-s', '-X', 'POST',
                        f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label={label}&category={cat}'],
                       capture_output=True, text=True,
                       env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)


def process_round(round_number, experiment_ids, started_at, insights):
    while True:
        all_done = True
        status_parts = []
        for eid in experiment_ids:
            exp = api(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            done = sum(1 for s in strats if s.get('status') in ('done', 'invalid', 'failed'))
            status_parts.append(f'E{eid}:{done}/{len(strats)}')
            if done < len(strats) or len(strats) == 0:
                all_done = False
        print(f'{datetime.now():%H:%M} R{round_number}: {" ".join(status_parts)}')
        if all_done:
            break
        time.sleep(60)

    all_strats = []
    for eid in experiment_ids:
        exp = api(f'lab/experiments/{eid}')
        all_strats.extend([s for s in exp.get('strategies', []) if s.get('status') == 'done'])

    stda_count = 0
    best_score = 0
    best_name = ""
    best_return = 0
    best_dd = 0

    for s in all_strats:
        sc = s.get('score', 0) or 0
        ret = s.get('total_return_pct', 0) or 0
        dd = abs(s.get('max_drawdown_pct', 100) or 100)
        tr = s.get('total_trades', 0) or 0
        wr = s.get('win_rate', 0) or 0
        if sc >= 0.80 and ret > 60 and dd < 18 and tr >= 50 and wr > 60:
            stda_count += 1
            promote(s['id'])
        if sc > best_score:
            best_score = sc
            best_name = s.get('name', '')[:60]
            best_return = ret
            best_dd = dd

    api_post('strategies/pool/rebalance', {"max_per_family": 3})

    valid = len(all_strats)
    summary = f"R{round_number}: {valid} strategies, {stda_count} StdA+ ({stda_count * 100 // max(valid, 1)}%). Best: {best_name} score={best_score:.4f} ret={best_return:.1f}%"
    print(summary)

    api_post('lab/exploration-rounds', {
        "round_number": round_number,
        "mode": "time",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
        "experiment_ids": experiment_ids,
        "total_experiments": len(experiment_ids),
        "total_strategies": valid,
        "profitable_count": stda_count,
        "profitability_pct": stda_count / max(valid, 1) * 100,
        "std_a_count": stda_count,
        "best_strategy_name": best_name,
        "best_strategy_score": best_score,
        "best_strategy_return": best_return,
        "best_strategy_dd": best_dd,
        "insights": insights,
        "promoted": [],
        "issues_resolved": [],
        "next_suggestions": [],
        "summary": summary,
        "memory_synced": False,
        "pinecone_synced": False,
    })
    return stda_count, valid


def main():
    now = datetime.now().isoformat()

    print("=== Processing R620 ===")
    stda620, valid620 = process_round(620, [5228], now, ["pct_change momentum filters on BelMax"])

    print("\n=== Processing R621 ===")
    stda621, valid621 = process_round(621, [5229], now, ["MACD/KDJ as 5th filter on BelMax"])

    print(f"\nTotal: R620={stda620}/{valid620}, R621={stda621}/{valid621}")


if __name__ == '__main__':
    main()
