"""Players. Baselines decide instantly; model players are charged their real latency by the harness.

- AlwaysFire, Random, Autopilot: coded references.
- DecisionModel: a System-1 decision model (Microsoft-Decision-1, Jev) through OpenRouter's
  /api/alpha/decisions endpoint: the board as text, one choice question, a probability per action.
- LocalModel: a small model on the local GPU through Ollama's OpenAI-compatible chat API, thinking
  switched off, answering {"action": ...}.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.request

from .budget import Ledger
from .engine import ACTIONS, Game

CRITERIA = {"left": "move the cannon one column left", "right": "move the cannon one column right",
            "fire": "shoot straight up (only if the shot is ready)", "wait": "stay still"}
QUESTION = ("You control the cannon. Shoot the aliens before they land and avoid the bombs. "
            "Which single action is best right now?")


def load_key() -> str | None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    for path in (".config/openrouter.env", os.path.expanduser("~/.config/llm-invaders/openrouter.env")):
        try:
            for line in open(path):
                k, _, v = line.strip().partition("=")
                if k.strip() == "OPENROUTER_API_KEY" and v.strip():
                    return v.strip().strip("'\"")
        except OSError:
            continue
    return None


class Agent:
    name = "agent"
    charged = False            # True: the harness charges real decision latency in game time

    def act(self, game: Game) -> str:
        raise NotImplementedError


class AlwaysFire(Agent):
    name = "always fire"

    def act(self, game: Game) -> str:
        return "fire"


class RandomAgent(Agent):
    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def act(self, game: Game) -> str:
        return self.rng.choice(ACTIONS)


class Autopilot(Agent):
    """Dodge a bomb about to land, else line up under the nearest column and fire."""
    name = "autopilot"

    def act(self, game: Game) -> str:
        bottom = game.params.height - 1
        danger = lambda x: any(b[0] == x and bottom - b[1] <= 3 for b in game.bombs)  # noqa: E731
        if danger(game.x):                                # step aside, to a column that is clear
            if game.x > 1 and not danger(game.x - 1):
                return "left"
            return "right" if game.x < game.params.width - 2 and not danger(game.x + 1) else "wait"
        cols = game.lowest_by_column()
        if not cols:
            return "wait"
        target = min(cols, key=lambda c: (abs(c - game.x), c))
        if target == game.x:
            return "fire" if game.bullet is None else "wait"
        step = 1 if target > game.x else -1
        return ("right" if step > 0 else "left") if not danger(game.x + step) else "wait"   # never into a bomb


class DecisionModel(Agent):
    """A System-1 decision model: one call, a probability per action, the most likely one played."""
    charged = True

    def __init__(self, model: str, ledger: Ledger, label: str | None = None, timeout: float = 30.0) -> None:
        self.model, self.ledger, self.timeout = model, ledger, timeout
        self.name = label or model
        self.key = load_key()
        self.latencies: list[float] = []
        self.errors = 0

    def act(self, game: Game) -> str:
        self.ledger.check()
        body = {"model": self.model, "state": game.describe(),
                "questions": {"action": {"type": "choice", "instructions": QUESTION, "criteria": CRITERIA}}}
        req = urllib.request.Request("https://openrouter.ai/api/alpha/decisions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read())
            choice = d["answers"]["action"]["choice"]
            cost = float(d.get("usage", {}).get("cost") or 0.0)
        except Exception:
            choice, cost = "wait", 0.0
            self.errors += 1
        seconds = time.monotonic() - started
        self.latencies.append(seconds)
        self.ledger.record(self.model, cost, seconds)
        return choice if choice in ACTIONS else "wait"


class LocalModel(Agent):
    """A small local model (Ollama, OpenAI-compatible), thinking off, strict JSON {"action": ...}."""
    charged = True

    def __init__(self, model: str = "gemma4:e2b", base_url: str = "http://localhost:11434/v1",
                 label: str | None = None) -> None:
        self.model, self.base_url = model, base_url
        self.name = label or f"{model} (local GPU)"
        self.latencies: list[float] = []
        self.errors = 0

    def act(self, game: Game) -> str:
        body = {"model": self.model, "max_tokens": 30, "temperature": 0, "reasoning": {"effort": "none"},
                "messages": [{"role": "system", "content": QUESTION + " Answer with JSON."},
                             {"role": "user", "content": game.describe()}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "action", "strict": True, "schema": {
                    "type": "object", "properties": {"action": {"type": "string", "enum": list(ACTIONS)}},
                    "required": ["action"], "additionalProperties": False}}}}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
            choice = json.loads(d["choices"][0]["message"]["content"]).get("action")
        except Exception:
            choice = "wait"
            self.errors += 1
        self.latencies.append(time.monotonic() - started)
        return choice if choice in ACTIONS else "wait"
