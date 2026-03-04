#!/usr/bin/env python3
"""R51 auto-finish: monitor experiments, promote StdA+, save round record."""
import subprocess, json, time, urllib.parse
from datetime import datetime

# R51 config
EXPERIMENT_IDS = [3381, 3382, 3383, 3384, 3385, 3386, 3387]
ROUND_NUMBER = 51
STARTED_AT = datetime.now().isoformat()
POLL_INTERVAL = 120  # seconds

# StdA+ criteria
MIN_SCORE = 0.75
MIN_RETURN = 60.0
MAX_DD = 18.0
MIN_TRADES = 50

def log(msg):
    print(f"[{datetime.now()}] {msg}", flush=True)

def api(path):
    r = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:8050/api/{path}'],
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

def api_put(path, data):
    r = subprocess.run(
        ['curl', '-s', '-X', 'PUT', f'http://127.0.0.1:8050/api/{path}',
         '-H', 'Content-Type: application/json', '-d', json.dumps(data)],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)

def promote(sid, label='[AI]'):
    encoded_label = urllib.parse.quote(label)
    cat_map = {'[AI]': '全能', '[AI-牛市]': '牛市', '[AI-熊市]': '熊市', '[AI-震荡]': '震荡'}
    cat = urllib.parse.quote(cat_map.get(label, ''))
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         f'http://127.0.0.1:8050/api/lab/strategies/{sid}/promote?label={encoded_label}&category={cat}'],
        capture_output=True, text=True,
        env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
    return json.loads(r.stdout)

def is_stda_plus(s):
    score = s.get('score', 0) or 0
    ret = s.get('total_return_pct', 0) or 0
    dd = abs(s.get('max_drawdown_pct', 100) or 100)
    trades = s.get('total_trades', 0) or 0
    return score >= MIN_SCORE and ret > MIN_RETURN and dd < MAX_DD and trades >= MIN_TRADES

def main():
    log(f"R51 monitor started ({len(EXPERIMENT_IDS)} experiments)")

    # Wait for all experiments to finish
    while True:
        all_done = True
        total_strats = 0
        done_strats = 0

        for eid in EXPERIMENT_IDS:
            try:
                exp = api(f'lab/experiments/{eid}')
                status = exp.get('status', 'unknown')
                strats = exp.get('strategies', [])
                total_strats += len(strats)
                for s in strats:
                    if s.get('status') in ('done', 'invalid', 'failed'):
                        done_strats += 1

                if status not in ('done', 'failed'):
                    all_done = False
            except Exception as e:
                log(f"Error checking E{eid}: {e}")
                all_done = False

        log(f"Progress: {done_strats}/{total_strats} strategies done")

        if all_done:
            break
        time.sleep(POLL_INTERVAL)

    log("All done. Analyzing...")

    # Analyze results
    total_done = 0
    total_invalid = 0
    stda_count = 0
    best_name = ""
    best_score = 0
    best_return = 0
    best_dd = 0
    promoted_list = []

    for eid in EXPERIMENT_IDS:
        exp = api(f'lab/experiments/{eid}')
        strats = exp.get('strategies', [])
        exp_done = sum(1 for s in strats if s.get('status') == 'done')
        exp_invalid = sum(1 for s in strats if s.get('status') == 'invalid')
        exp_stda = 0

        for s in strats:
            if s.get('status') != 'done':
                continue
            if is_stda_plus(s):
                exp_stda += 1
                result = promote(s['id'], '[AI]')
                msg = result.get('message', '')
                if msg != 'Already promoted':
                    promoted_list.append({
                        'id': s['id'],
                        'name': s.get('name', ''),
                        'label': '[AI]',
                        'score': s.get('score', 0)
                    })
                score = s.get('score', 0) or 0
                if score > best_score:
                    best_score = score
                    best_name = s.get('name', '')
                    best_return = s.get('total_return_pct', 0) or 0
                    best_dd = abs(s.get('max_drawdown_pct', 0) or 0)

        total_done += exp_done
        total_invalid += exp_invalid
        stda_count += exp_stda

        log(f"  E{eid} [{exp.get('theme', '')[:50]}]: {exp_done}done {exp_invalid}inv {exp_stda}StdA+")

    log(f"Total: {total_done} done, {total_invalid} invalid, {stda_count} StdA+ ({len(promoted_list)} new)")
    if best_name:
        log(f"Best: {best_name} (score={best_score:.3f}, ret={best_return:+.1f}%)")

    # Save exploration round
    summary = (
        f"## R51 结果\\n\\n"
        f"**实验**: 7个(2 grid + 5 DeepSeek), {total_done}done, {total_invalid}invalid\\n"
        f"**StdA+**: {stda_count}个 ({len(promoted_list)}个新promote)\\n"
        f"**最佳**: {best_name} (score={best_score:.3f}, ret={best_return:+.1f}%)\\n"
    )

    round_data = {
        "round_number": ROUND_NUMBER,
        "mode": "auto",
        "started_at": STARTED_AT,
        "finished_at": datetime.now().isoformat(),
        "experiment_ids": EXPERIMENT_IDS,
        "total_experiments": len(EXPERIMENT_IDS),
        "total_strategies": total_done + total_invalid,
        "profitable_count": stda_count,
        "profitability_pct": (stda_count / total_done * 100) if total_done > 0 else 0,
        "std_a_count": stda_count,
        "best_strategy_name": best_name,
        "best_strategy_score": best_score,
        "best_strategy_return": best_return,
        "best_strategy_dd": best_dd,
        "insights": [
            f"ULTOSC+PSAR TP12-20 extended grid: {stda_count} StdA+",
            f"Best: {best_name} score={best_score:.3f}",
        ],
        "promoted": promoted_list,
        "issues_resolved": [],
        "next_suggestions": ["Analyze TP distribution pattern for ULTOSC+PSAR TP10-30 range"],
        "summary": summary,
        "memory_synced": False,
        "pinecone_synced": False,
    }

    try:
        result = api_post('lab/exploration-rounds', round_data)
        log(f"Round saved: {result}")
    except Exception as e:
        log(f"Failed to save round: {e}")

    # Save summary to file
    with open('/tmp/r51_summary.json', 'w') as f:
        json.dump({
            'total_done': total_done,
            'total_invalid': total_invalid,
            'stda_count': stda_count,
            'best_name': best_name,
            'best_score': best_score,
            'best_return': best_return,
            'best_dd': best_dd,
            'promoted': promoted_list,
            'experiment_ids': EXPERIMENT_IDS,
        }, f, ensure_ascii=False, indent=2)

    log(f"R51 complete. Summary: /tmp/r51_summary.json")

if __name__ == '__main__':
    main()
