#!/usr/bin/env python3
"""Re-run all template experiments with repaired data.

Usage: NO_PROXY=localhost,127.0.0.1 python scripts/rerun_experiments.py
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

# Disable proxy for localhost
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

BASE = "http://localhost:8050"

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)

# Use a handler that ignores proxy
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api_get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with _opener.open(req, timeout=30) as resp:
        return json.loads(resp.read())


def api_post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with _opener.open(req, timeout=600) as resp:
        return resp.read().decode()


def api_delete(path):
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    with _opener.open(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    # Step 1: Health check
    try:
        h = api_get("/api/health")
        print(f"Server OK: {h}")
    except Exception as e:
        print(f"Server not reachable: {e}")
        sys.exit(1)

    # Step 2: Delete all existing experiments
    print("\n=== Deleting old experiments ===")
    exps = api_get("/api/lab/experiments?page=1&size=100")
    for item in exps["items"]:
        eid = item["id"]
        status = item["status"]
        if status in ("pending", "generating", "backtesting"):
            print(f"  Skipping running experiment {eid} ({item['theme']})")
            continue
        try:
            api_delete(f"/api/lab/experiments/{eid}")
            print(f"  Deleted experiment {eid}: {item['theme']}")
        except Exception as e:
            print(f"  Failed to delete {eid}: {e}")

    # Step 3: Get templates
    templates = api_get("/api/lab/templates")
    print(f"\n=== Running {len(templates)} templates ===")

    experiment_ids = []
    for tpl in templates:
        print(f"\nStarting: {tpl['name']} ({tpl['category']})...")
        try:
            # POST creates experiment and starts it, returns SSE stream
            # We just need to create and let it run, then poll status
            body = json.dumps({
                "theme": tpl["name"],
                "source_type": "template",
                "source_text": tpl["description"],
                "initial_capital": 100000,
                "max_positions": 10,
                "max_position_pct": 30,
            }).encode()
            req = urllib.request.Request(
                f"{BASE}/api/lab/experiments",
                data=body, method="POST",
            )
            req.add_header("Content-Type", "application/json")

            # Read the SSE stream to get the experiment ID and wait for completion
            with _opener.open(req, timeout=1200) as resp:
                exp_id = None
                last_msg = ""
                for line in resp:
                    line = line.decode().strip()
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    dtype = data.get("type", "")

                    if dtype == "strategies_ready":
                        exp_id = None  # we'll get the ID from listing
                        count = data.get("count", 0)
                        print(f"  Strategies generated: {count}")

                    elif dtype == "backtest_done":
                        name = data.get("name", "")
                        score = data.get("score", 0)
                        ret = data.get("total_return_pct", 0)
                        dd = data.get("max_drawdown_pct", 0)
                        trades = data.get("total_trades", 0)
                        last_msg = f"  {name}: score={score:.2f} ret={ret:.1f}% dd={dd:.1f}% trades={trades}"
                        print(last_msg)

                    elif dtype == "experiment_done":
                        best = data.get("best_name", "")
                        best_score = data.get("best_score", 0)
                        done = data.get("done_count", 0)
                        invalid = data.get("invalid_count", 0)
                        failed = data.get("failed_count", 0)
                        print(f"  DONE: best={best} score={best_score:.2f} done={done} invalid={invalid} failed={failed}")

                    elif dtype == "data_integrity_done":
                        print(f"  {data.get('message', '')}")

                    elif dtype == "error":
                        print(f"  ERROR: {data.get('message', '')}")

        except Exception as e:
            print(f"  Failed: {e}")

    # Step 4: Collect all results
    print("\n\n=== COLLECTING RESULTS ===\n")
    time.sleep(2)
    exps = api_get("/api/lab/experiments?page=1&size=100")

    all_strategies = []
    exp_summaries = []

    for item in exps["items"]:
        eid = item["id"]
        detail = api_get(f"/api/lab/experiments/{eid}")
        strategies = detail.get("strategies", [])

        done_strats = [s for s in strategies if s["status"] == "done"]
        invalid_strats = [s for s in strategies if s["status"] == "invalid"]
        failed_strats = [s for s in strategies if s["status"] == "failed"]

        profitable = [s for s in done_strats if s["total_return_pct"] > 0]

        exp_summaries.append({
            "theme": item["theme"],
            "total": len(strategies),
            "done": len(done_strats),
            "invalid": len(invalid_strats),
            "failed": len(failed_strats),
            "profitable": len(profitable),
            "best_return": max((s["total_return_pct"] for s in done_strats), default=0),
            "worst_return": min((s["total_return_pct"] for s in done_strats), default=0),
            "best_name": item.get("best_name", ""),
            "best_score": item.get("best_score", 0),
        })

        for s in strategies:
            s["experiment_theme"] = item["theme"]
            all_strategies.append(s)

    # Print summary
    total_strategies = len(all_strategies)
    done_strategies = [s for s in all_strategies if s["status"] == "done"]
    invalid_strategies = [s for s in all_strategies if s["status"] == "invalid"]
    profitable_strategies = [s for s in done_strategies if s["total_return_pct"] > 0]

    print(f"Total strategies: {total_strategies}")
    print(f"Done (with trades): {len(done_strategies)}")
    print(f"Invalid (zero trades): {len(invalid_strategies)}")
    print(f"Profitable: {len(profitable_strategies)}/{len(done_strategies)} ({len(profitable_strategies)/max(len(done_strategies),1)*100:.1f}%)")
    print(f"Zero trade rate: {len(invalid_strategies)}/{total_strategies} ({len(invalid_strategies)/max(total_strategies,1)*100:.1f}%)")

    if done_strategies:
        avg_dd = sum(s["max_drawdown_pct"] for s in done_strategies) / len(done_strategies)
        avg_wr = sum(s["win_rate"] for s in done_strategies) / len(done_strategies)
        best = max(done_strategies, key=lambda s: s["total_return_pct"])
        worst = min(done_strategies, key=lambda s: s["total_return_pct"])
        print(f"Avg max drawdown: {avg_dd:.1f}%")
        print(f"Avg win rate: {avg_wr:.1f}%")
        print(f"Best: {best['name']} ({best['experiment_theme']}) +{best['total_return_pct']:.1f}%")
        print(f"Worst: {worst['name']} ({worst['experiment_theme']}) {worst['total_return_pct']:.1f}%")

    # Print per-experiment table
    print("\n--- Per-experiment summary ---")
    print(f"{'Experiment':<20} {'P/D':>5} {'Best%':>8} {'Worst%':>8} {'Category'}")
    for e in sorted(exp_summaries, key=lambda x: -x["best_return"]):
        print(f"{e['theme']:<20} {e['profitable']}/{e['done']:>3} {e['best_return']:>+8.1f} {e['worst_return']:>+8.1f}")

    # Print top strategies
    print("\n--- Top 15 strategies by score ---")
    top = sorted(done_strategies, key=lambda s: -s["score"])[:15]
    print(f"{'Rank':>4} {'Name':<35} {'Score':>6} {'Ret%':>8} {'DD%':>8} {'WR%':>6} {'Trades':>6}")
    for i, s in enumerate(top, 1):
        print(f"{i:>4} {s['name']:<35} {s['score']:>6.2f} {s['total_return_pct']:>+8.1f} {s['max_drawdown_pct']:>8.1f} {s['win_rate']:>6.1f} {s['total_trades']:>6}")

    # Save full results to JSON for analysis
    output = {
        "run_date": time.strftime("%Y-%m-%d %H:%M"),
        "total_experiments": len(exp_summaries),
        "total_strategies": total_strategies,
        "done_count": len(done_strategies),
        "invalid_count": len(invalid_strategies),
        "profitable_count": len(profitable_strategies),
        "experiment_summaries": exp_summaries,
        "top_strategies": [{
            "name": s["name"],
            "theme": s["experiment_theme"],
            "score": s["score"],
            "total_return_pct": s["total_return_pct"],
            "max_drawdown_pct": s["max_drawdown_pct"],
            "win_rate": s["win_rate"],
            "total_trades": s["total_trades"],
            "avg_hold_days": s["avg_hold_days"],
            "avg_pnl_pct": s["avg_pnl_pct"],
            "buy_conditions_count": len(s.get("buy_conditions", [])),
        } for s in sorted(done_strategies, key=lambda x: -x["score"])],
    }

    with open("data/experiment_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nFull results saved to data/experiment_results.json")


if __name__ == "__main__":
    main()
