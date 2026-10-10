"""Decision quality and speed, without playing whole games.

A fixed set of real game situations (sampled from autopilot and random games) is put to each model
once. A move counts as good when it is one of the sound moves for that situation:

  bomb about to land on the cannon  -> step aside to a clear column
  lined up under an alien            -> fire (or wait, if the shot is already in flight)
  otherwise                          -> move toward the nearest alien column (fire too, if an alien is above)

Latency is measured separately, one call at a time, so it is not inflated by parallel requests.

    python3 quality.py --players jev,decision-1 --states 200 --workers 10
    python3 quality.py --players gemma --states 200 --workers 1
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import copy
import json
import random
import statistics
import time

from bench import LEDGER, PLAYERS
from invaders.agents import Autopilot, RandomAgent
from invaders.engine import Game


def good_moves(g: Game) -> tuple[str, set[str]]:
    bottom = g.params.height - 1
    danger = lambda x: any(b[0] == x and bottom - b[1] <= 3 for b in g.bombs)  # noqa: E731
    if danger(g.x):
        safe = {m for m, x in (("left", g.x - 1), ("right", g.x + 1)) if 1 <= x <= g.params.width - 2 and not danger(x)}
        return "dodge", safe or {"wait"}
    cols = g.lowest_by_column()
    target = min(cols, key=lambda c: (abs(c - g.x), c))
    if target == g.x:
        return "aligned", {"fire"} if g.bullet is None else {"fire", "wait"}
    step = "right" if target > g.x else "left"
    return "approach", {step} if not danger(g.x + (1 if step == "right" else -1)) else {"wait"}


def sample_states(n: int, seed: int = 0) -> list[Game]:
    """Situations from real play: autopilot and random games, every few decisions, mixed."""
    rng, states = random.Random(seed), []
    s = 0
    while len(states) < n * 3 or sum(good_moves(g)[0] == "dodge" for g in states) < n // 4:
        g = Game(seed=1000 + s)
        player = Autopilot() if s % 2 == 0 else RandomAgent(s)
        while not g.over:
            g.advance(0.05)
            g.act(player.act(g))
            if not g.over and rng.random() < (0.6 if good_moves(g)[0] == "dodge" else 0.08):
                states.append(copy.deepcopy(g))
        s += 1
    # balance: as many dodge and aligned situations as the data has, the rest approach
    by_kind = collections.defaultdict(list)
    for g in states:
        by_kind[good_moves(g)[0]].append(g)
    picked = by_kind["dodge"][: n // 4] + by_kind["aligned"][: n // 4]
    picked += by_kind["approach"][: n - len(picked)]
    rng.shuffle(picked)
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True)
    ap.add_argument("--states", type=int, default=200)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--latency-calls", type=int, default=30)
    args = ap.parse_args()
    states = sample_states(args.states)
    kinds = collections.Counter(good_moves(g)[0] for g in states)
    print(f"{len(states)} situations: {dict(kinds)}; spent so far ${LEDGER.spent:.4f}", flush=True)
    out = []
    for name in args.players.split(","):
        agent = PLAYERS[name](0)
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            moves = list(pool.map(agent.act, states))
        per_kind = collections.defaultdict(lambda: [0, 0])
        picks = collections.Counter(moves)
        for g, m in zip(states, moves):
            kind, good = good_moves(g)
            per_kind[kind][0] += m in good
            per_kind[kind][1] += 1
        agent.latencies.clear()
        for g in states[: args.latency_calls]:          # one at a time: clean latency
            agent.act(g)
        lat = sorted(agent.latencies)
        row = {"player": name, "label": agent.name, "situations": len(states),
               "good_moves": sum(v[0] for v in per_kind.values()),
               "by_kind": {k: {"good": v[0], "of": v[1]} for k, v in per_kind.items()},
               "picks": dict(picks), "errors": agent.errors,
               "latency_calls": len(lat), "latency_median_s": round(statistics.median(lat), 3),
               "latency_p90_s": round(lat[int(0.9 * (len(lat) - 1))], 3), "latency_min_s": round(lat[0], 3),
               "measured_at": time.strftime("%Y-%m-%d %H:%M")}
        out.append(row)
        LEDGER.save()
        kinds_txt = ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(per_kind.items()))
        print(f"{agent.name:26} good {row['good_moves']}/{len(states)} ({kinds_txt}) picks {dict(picks)} | "
              f"latency median {row['latency_median_s']}s p90 {row['latency_p90_s']}s | spent ${LEDGER.spent:.4f}", flush=True)
    try:
        prev = json.load(open("quality.json"))
    except (OSError, ValueError):
        prev = []
    keep = [r for r in prev if r["player"] not in {r2["player"] for r2 in out}]
    json.dump(keep + out, open("quality.json", "w"), indent=1)


if __name__ == "__main__":
    main()
