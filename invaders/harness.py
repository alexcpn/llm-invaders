"""Run one game with latency charged in game time.

Each decision: the game is frozen, the player decides (taking L real seconds), then the world runs
for L x speed game seconds before the move lands, so a slow player acts on a stale view, as it would
in real play, but results do not depend on the machine running the game. Coded players get a fixed
reaction time instead (REFLEX game seconds per decision).
"""

from __future__ import annotations

import time

from .agents import Agent
from .engine import Game, Params

REFLEX = 0.05          # game seconds per decision for instant (coded) players
MIN_CHARGE = 0.01      # a model decision costs at least this much game time


def play(agent: Agent, seed: int, speed: float = 1.0, params: Params | None = None,
         fixed_latency: float | None = None, max_game_s: float = 600.0) -> dict:
    """speed = game seconds per real second. fixed_latency replaces the measured latency (seconds),
    e.g. to replay a coded player at a model's latency."""
    game = Game(params or Params(), seed=seed)
    decisions, charged = 0, []
    started = time.monotonic()
    while not game.over and game.t < max_game_s:
        t0 = time.monotonic()
        action = agent.act(game)
        latency = time.monotonic() - t0
        if fixed_latency is not None:
            dt = max(MIN_CHARGE, fixed_latency * speed)
        elif agent.charged:
            dt = max(MIN_CHARGE, latency * speed)
        else:
            dt = REFLEX
        charged.append(dt)
        game.advance(dt)
        game.act(action)
        decisions += 1
    if not game.over:
        game.over, game.reason = True, "time limit"
    return {"agent": agent.name, "seed": seed, "speed": speed, "won": game.won, "reason": game.reason,
            "kills": game.kills, "total": game.total, "shots": game.shots, "lives_left": game.lives,
            "game_seconds": round(game.t, 2), "decisions": decisions, "wall_seconds": round(time.monotonic() - started, 2),
            "mean_game_s_per_decision": round(sum(charged) / max(1, len(charged)), 4)}
