#!/usr/bin/env python3
"""R40 auto-finish script.

Monitors experiments 3319-3323, promotes qualifying strategies when done,
and updates exploration round API record.

Usage: NO_PROXY=localhost,127.0.0.1 nohup python3 scripts/r40_auto_finish.py &
"""
import subprocess
import json
import time
import urllib.parse
from datetime import datetime

ROUND = 40
EXP_IDS = [3319, 3320, 3321, 3322, 3323]
STARTED_AT = "2026-03-01T08:38:38"
POLL_INTERVAL = 60  # seconds

# New StdA+ criteria
MIN_SCORE = 0.75
MIN_RETURN = 60.0
MAX_DD = 18.0
MIN_TRADES = 50


def api(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}
    )
    return json.loads(r.stdout)


def api_post(path, data=None):
    cmd = ['curl', '-s', '-X', 'POST', f'http://127.0.0.1:8050/api/{path}']
    if data:
        cmd += ['-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}
    )
    return json.loads(r.stdout)


def api_put(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'PUT', f'http://127.0.0.1:8050/api/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}
    )
    return json.loads(r.stdout)


def promote(sid, label='[AI]'):
    encoded_label = urllib.parse.quote(label)
    cat_map = {'[AI]': '全能', '[AI-牛市]': '牛市', '[AI-熊市]': '熊市', '[AI-震荡]': '震荡'}
    cat = urllib.parse.quote(cat_map.get(label, ''))
    return api_post(f'lab/strategies/{sid}/promote?label={encoded_label}&category={cat}')


def check_all_done():
    """Check if all experiments are completed."""
    for eid in EXP_IDS:
        exp = api(f'lab/experiments/{eid}')
        strats = exp.get('strategies', [])
        not_done = [s for s in strats if s.get('status') not in ('done', 'invalid', 'failed')]
        if not_done:
            return False
    return True


def analyze_and_promote():
    """Analyze all experiments and promote qualifying strategies."""
    total_strats = 0
    done_count = 0
    stda_count = 0
    promoted_list = []
    best_score = 0
    best_name = ""
    best_return = 0
    best_dd = 0

    family_results = {}

    for eid in EXP_IDS:
        exp = api(f'lab/experiments/{eid}')
        theme = exp.get('theme', '?')
        strats = exp.get('strategies', [])
        total_strats += len(strats)

        fam_done = 0
        fam_stda = 0

        for s in strats:
            if s.get('status') != 'done':
                continue
            done_count += 1
            fam_done += 1

            score = s.get('score', 0) or 0
            ret = s.get('total_return_pct', 0) or 0
            dd = abs(s.get('max_drawdown_pct', 100) or 100)
            trades = s.get('total_trades', 0) or 0

            if score >= MIN_SCORE and ret > MIN_RETURN and dd < MAX_DD and trades >= MIN_TRADES:
                stda_count += 1
                fam_stda += 1
                result = promote(s['id'])
                msg = result.get('message', '')
                if msg != 'Already promoted':
                    promoted_list.append({
                        'id': s['id'],
                        'name': s.get('name', '?'),
                        'label': '[AI]',
                        'score': score
                    })

                if score > best_score:
                    best_score = score
                    best_name = s.get('name', '?')
                    best_return = ret
                    best_dd = dd

        family_results[theme[:40]] = {'done': fam_done, 'stda': fam_stda}

    return {
        'total': total_strats,
        'done': done_count,
        'stda': stda_count,
        'promoted': promoted_list,
        'best_name': best_name,
        'best_score': best_score,
        'best_return': best_return,
        'best_dd': best_dd,
        'families': family_results,
    }


def main():
    print(f"[{datetime.now()}] R40 auto-finish started. Monitoring experiments {EXP_IDS}")

    # Poll until all done
    while True:
        all_done = True
        status_parts = []
        for eid in EXP_IDS:
            exp = api(f'lab/experiments/{eid}')
            strats = exp.get('strategies', [])
            done = sum(1 for s in strats if s.get('status') in ('done', 'invalid', 'failed'))
            total = len(strats)
            status_parts.append(f"E{eid}:{done}/{total}")
            if done < total:
                all_done = False

        print(f"[{datetime.now()}] Status: {' | '.join(status_parts)}")

        if all_done:
            print(f"[{datetime.now()}] All experiments complete!")
            break

        time.sleep(POLL_INTERVAL)

    # Analyze and promote
    print(f"\n[{datetime.now()}] Analyzing results...")
    results = analyze_and_promote()

    finished_at = datetime.now().isoformat()

    # Print summary
    summary_lines = [
        f"## R40 探索结果",
        f"",
        f"**实验**: 5 个主题 (474 configs), {results['done']} 个策略完成",
        f"**StdA+**: {results['stda']} 个 ({results['stda']/max(results['done'],1)*100:.1f}%)",
        f"**最佳策略**: {results['best_name']} — score={results['best_score']:.3f}, ret={results['best_return']:+.1f}%, dd={results['best_dd']:.1f}%",
        f"",
        f"**Per-family results:**",
    ]
    for fam, data in results['families'].items():
        summary_lines.append(f"- {fam}: {data['done']} done, {data['stda']} StdA+ ({data['stda']/max(data['done'],1)*100:.0f}%)")

    summary_lines.append(f"\n**Promoted**: {len(results['promoted'])} strategies")

    summary = "\n".join(summary_lines)
    print(summary)

    # Save summary to file
    with open('/tmp/r40_summary.json', 'w') as f:
        json.dump({
            'round': ROUND,
            'started_at': STARTED_AT,
            'finished_at': finished_at,
            'results': results,
            'summary': summary,
        }, f, ensure_ascii=False, indent=2)

    # Create exploration round record
    round_data = {
        "round_number": ROUND,
        "mode": "auto",
        "started_at": STARTED_AT,
        "finished_at": finished_at,
        "experiment_ids": EXP_IDS,
        "total_experiments": 5,
        "total_strategies": results['done'],
        "profitable_count": results['stda'],
        "profitability_pct": results['stda'] / max(results['done'], 1) * 100,
        "std_a_count": results['stda'],
        "best_strategy_name": results['best_name'],
        "best_strategy_score": results['best_score'],
        "best_strategy_return": results['best_return'],
        "best_strategy_dd": results['best_dd'],
        "insights": [
            f"R40: 5-family grid search with new StdA+ (s>=0.75, r>60, dd<18)",
            f"{results['stda']}/{results['done']} StdA+ ({results['stda']/max(results['done'],1)*100:.1f}%)",
        ],
        "promoted": results['promoted'][:20],  # Limit to first 20 for API
        "issues_resolved": [],
        "next_suggestions": ["Continue deep grid search on top families"],
        "summary": summary,
        "memory_synced": False,
        "pinecone_synced": False,
    }

    round_result = api_post('lab/exploration-rounds', round_data)
    round_id = round_result.get('id')
    print(f"\n[{datetime.now()}] Exploration round saved: id={round_id}")
    print(f"[{datetime.now()}] R40 auto-finish complete. Summary at /tmp/r40_summary.json")


if __name__ == '__main__':
    main()
