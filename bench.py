"""Sweep game speed for each player and record wins, latency and cost.

    python3 bench.py --players autopilot,always-fire --speeds 1 --seeds 0-19
    python3 bench.py --players jev,decision-1 --speeds 0.04,0.07,0.1 --seeds 0-2 --workers 4
    python3 bench.py --players gemma --speeds 0.1,0.2,0.3 --seeds 0-2 --workers 1

Results are appended to results.jsonl (one line per game, so an interrupted run loses nothing) and
every paid call is written to cost-ledger.json; paid calls stop at $1.90 of the $2.00 budget.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import statistics
import threading
import time

from invaders.agents import AlwaysFire, Autopilot, DecisionModel, LocalModel, RandomAgent
from invaders.budget import BudgetExceeded, Ledger
from invaders.harness import play

LEDGER = Ledger()
PLAYERS = {
    "autopilot": lambda seed: Autopilot(),
    "always-fire": lambda seed: AlwaysFire(),
    "random": lambda seed: RandomAgent(seed),
    "jev": lambda seed: DecisionModel("~typesafe/jev-latest", LEDGER, label="Jev (TypeSafe)"),
    "decision-1": lambda seed: DecisionModel("microsoft/microsoft-decision-1", LEDGER, label="Microsoft-Decision-1"),
    "gemma": lambda seed: LocalModel("gemma4:e2b", label="Gemma 4 E2B (local GPU)"),
}
_write = threading.Lock()


def seeds_arg(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",")]


def run_one(player: str, speed: float, seed: int, out: str) -> dict | None:
    agent = PLAYERS[player](seed)
    try:
        result = play(agent, seed=seed, speed=speed)
    except BudgetExceeded as exc:
        print(f"  budget stop: {exc}", flush=True)
        return None
    lat = getattr(agent, "latencies", [])
    result.update(player=player, latency_median_s=round(statistics.median(lat), 3) if lat else 0.0,
                  latency_p90_s=round(sorted(lat)[int(0.9 * (len(lat) - 1))], 3) if lat else 0.0,
                  errors=getattr(agent, "errors", 0), finished_at=time.strftime("%H:%M:%S"))
    with _write:
        with open(out, "a") as f:
            f.write(json.dumps(result) + "\n")
    LEDGER.save()
    print(f"  {player:11} speed {speed:<5} seed {seed:<3} {'WIN ' if result['won'] else 'lose'} kills {result['kills']:2d}/"
          f"{result['total']} {result['reason']:18} {result['decisions']:4d} decisions, latency {result['latency_median_s']}s, "
          f"{result['wall_seconds']:.0f}s wall | spent ${LEDGER.spent:.4f}", flush=True)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True)
    ap.add_argument("--speeds", required=True)
    ap.add_argument("--seeds", default="0-2")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", default="results.jsonl")
    args = ap.parse_args()
    jobs = [(p, float(s), seed) for p in args.players.split(",") for s in args.speeds.split(",") for seed in seeds_arg(args.seeds)]
    print(f"{len(jobs)} games; spent so far ${LEDGER.spent:.4f} of ${LEDGER.limit:.2f}", flush=True)
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda j: run_one(*j, args.out), jobs))
    LEDGER.save()
    print(f"done; spent ${LEDGER.spent:.4f}; by model {json.dumps(LEDGER.by_model())}", flush=True)


if __name__ == "__main__":
    main()
