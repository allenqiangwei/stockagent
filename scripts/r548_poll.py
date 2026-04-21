#!/usr/bin/env python3
"""Poll Round 548 experiment completion status."""
import subprocess, json, time, sys

API = "http://127.0.0.1:8050/api"
ENV = {'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'}


def api_get(path):
    r = subprocess.run(
        ['curl', '-s', f'{API}/{path}'],
        capture_output=True, text=True, env=ENV, timeout=30)
    return json.loads(r.stdout)


def check_all(exp_ids):
    done_count = 0
    running_count = 0
    total_strats = 0
    done_strats = 0
    best_score = 0
    best_info = ""
    stda_count = 0

    for eid in exp_ids:
        try:
            exp = api_get(f'lab/experiments/{eid}')
            status = exp.get('status', '?')
            strats = exp.get('strategies', [])
            d = sum(1 for s in strats if s.get('status') in ('done', 'invalid', 'failed'))
            total_strats += len(strats)
            done_strats += d

            if status == 'done':
                done_count += 1
            elif status in ('backtesting', 'generating'):
                running_count += 1

            for s in strats:
                if s.get('status') != 'done':
                    continue
                sc = s.get('score', 0) or 0
                ret = s.get('total_return_pct', 0) or 0
                dd = abs(s.get('max_drawdown_pct', 100) or 100)
                tr = s.get('total_trades', 0) or 0
                wr = s.get('win_rate', 0) or 0
                is_stda = sc >= 0.80 and ret > 60 and dd < 18 and tr >= 50 and wr > 60
                if is_stda:
                    stda_count += 1
                if sc > best_score:
                    best_score = sc
                    best_info = f"ES{s['id']} (E{eid}): sc={sc:.4f} ret={ret:.0f}% wr={wr:.1f}% dd={dd:.1f}%"
        except Exception as e:
            pass

    return {
        "done_exps": done_count,
        "running_exps": running_count,
        "total_strats": total_strats,
        "done_strats": done_strats,
        "stda_count": stda_count,
        "best_score": best_score,
        "best_info": best_info,
    }


def main():
    with open("/tmp/r548_experiments.json") as f:
        data = json.load(f)
    exp_ids = data["experiment_ids"]
    start = data["start_time"]

    print(f"Monitoring {len(exp_ids)} experiments...")
    total = len(exp_ids)

    while True:
        status = check_all(exp_ids)
        elapsed = time.time() - start
        elapsed_m = elapsed / 60

        pct = status["done_strats"] / max(status["total_strats"], 1) * 100
        print(
            f"[{elapsed_m:.0f}m] "
            f"Exp: {status['done_exps']}/{total} done, {status['running_exps']} running | "
            f"Strat: {status['done_strats']}/{status['total_strats']} ({pct:.0f}%) | "
            f"StdA+: {status['stda_count']} | "
            f"Best: {status['best_score']:.4f}"
        )

        if status["done_exps"] >= total:
            print(f"\nAll {total} experiments completed!")
            print(f"Total StdA+: {status['stda_count']}")
            print(f"Best: {status['best_info']}")
            break

        if status["best_info"]:
            print(f"  → {status['best_info']}")

        time.sleep(60)


if __name__ == "__main__":
    main()
