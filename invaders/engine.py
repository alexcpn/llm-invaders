"""A small, deterministic Space Invaders, timed in game seconds.

The wave marches sideways, drops a row at each edge and speeds up as it thins. Aliens drop bombs.
The cannon moves one column per action and has one shot in flight at a time. Clear the wave to win;
lose when the aliens reach the cannon's row or the cannon runs out of lives.

Time only moves when advance(dt) is called, so a harness can freeze the game while a model thinks
and then charge the model its real latency in game time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

ACTIONS = ("left", "right", "fire", "wait")
TICK = 0.01


@dataclass(frozen=True)
class Params:
    width: int = 36
    height: int = 18
    alien_rows: int = 3
    alien_cols: int = 6
    alien_dx: int = 4                 # columns between aliens
    alien_dy: int = 2                 # rows between alien rows
    alien_top: int = 2
    alien_step_s: float = 0.6         # a full wave steps once per this; a thinned wave steps faster
    alien_step_min_frac: float = 0.35  # step time with one alien left, as a fraction of alien_step_s
    bomb_step_s: float = 0.25         # bombs fall one row per this
    bomb_chance: float = 0.25         # chance a bomb drops on each wave step
    bullet_step_s: float = 0.02       # the cannon's shot rises one row per this
    lives: int = 3


@dataclass
class Game:
    params: Params = field(default_factory=Params)
    seed: int = 0

    def __post_init__(self) -> None:
        p = self.params
        self.rng = random.Random(self.seed)
        self.t = 0.0
        self.aliens = {(4 + c * p.alien_dx, p.alien_top + r * p.alien_dy)
                       for r in range(p.alien_rows) for c in range(p.alien_cols)}
        self.total = len(self.aliens)
        self.direction = 1
        self.x = p.width // 2
        self.bullet: tuple[int, int] | None = None
        self.bombs: list[list[int]] = []
        self.lives = p.lives
        self.kills = self.shots = self.hits_taken = 0
        self.over, self.won, self.reason = False, False, ""
        self._next = {"alien": self._alien_interval(), "bomb": p.bomb_step_s, "bullet": p.bullet_step_s}

    # ------------------------------------------------------------------ timing

    def _alien_interval(self) -> float:
        p = self.params
        frac = p.alien_step_min_frac + (1 - p.alien_step_min_frac) * (len(self.aliens) - 1) / max(1, self.total - 1)
        return p.alien_step_s * frac

    def advance(self, dt: float) -> None:
        """Run the world for dt game seconds (the cannon does nothing meanwhile)."""
        end = self.t + dt
        while self.t < end - 1e-9 and not self.over:
            self.t = min(end, self.t + TICK)
            if self.t >= self._next["bullet"]:
                self._next["bullet"] += self.params.bullet_step_s
                self._move_bullet()
            if self.t >= self._next["bomb"] and not self.over:
                self._next["bomb"] += self.params.bomb_step_s
                self._move_bombs()
            if self.t >= self._next["alien"] and not self.over:
                self._next["alien"] = self.t + self._alien_interval()
                self._move_aliens()

    # ------------------------------------------------------------------ the cannon

    def act(self, action: str) -> None:
        if self.over:
            return
        p = self.params
        if action == "left":
            self.x = max(1, self.x - 1)
        elif action == "right":
            self.x = min(p.width - 2, self.x + 1)
        elif action == "fire" and self.bullet is None:
            self.bullet = (self.x, p.height - 2)
            self.shots += 1
            self._bullet_hit()
        self._bomb_hit()

    # ------------------------------------------------------------------ the world

    def _move_bullet(self) -> None:
        if self.bullet is None:
            return
        x, y = self.bullet
        self.bullet = (x, y - 1) if y > 0 else None
        self._bullet_hit()

    def _bullet_hit(self) -> None:
        if self.bullet in self.aliens:
            self.aliens.discard(self.bullet)
            self.bullet = None
            self.kills += 1
            if not self.aliens:
                self.over, self.won, self.reason = True, True, "cleared the wave"

    def _move_bombs(self) -> None:
        for b in self.bombs:
            b[1] += 1
        self.bombs = [b for b in self.bombs if b[1] <= self.params.height - 1]
        self._bomb_hit()

    def _bomb_hit(self) -> None:
        bottom = self.params.height - 1
        if any(b[0] == self.x and b[1] == bottom for b in self.bombs):
            self.lives -= 1
            self.hits_taken += 1
            self.bombs.clear()
            if self.lives <= 0:
                self.over, self.reason = True, "out of lives"

    def _move_aliens(self) -> None:
        p = self.params
        xs = [x for x, _ in self.aliens]
        if min(xs) + self.direction < 1 or max(xs) + self.direction > p.width - 2:
            self.aliens = {(x, y + 1) for x, y in self.aliens}
            self.direction = -self.direction
        else:
            self.aliens = {(x + self.direction, y) for x, y in self.aliens}
        self._bullet_hit()
        if self.over:
            return
        if max(y for _, y in self.aliens) >= p.height - 2:
            self.over, self.reason = True, "the aliens landed"
            return
        if self.rng.random() < p.bomb_chance:
            col = self.rng.choice(sorted({x for x, _ in self.aliens}))
            low = max(y for x, y in self.aliens if x == col)
            self.bombs.append([col, low + 1])

    # ------------------------------------------------------------------ what a player sees

    def lowest_by_column(self) -> dict[int, int]:
        cols: dict[int, int] = {}
        for x, y in self.aliens:
            cols[x] = max(cols.get(x, -1), y)
        return dict(sorted(cols.items()))

    def describe(self) -> str:
        """The board as text, the same facts the coded autopilot uses."""
        p, bottom = self.params, self.params.height - 1
        cols = self.lowest_by_column()
        above = cols.get(self.x)
        nearest = min(cols, key=lambda c: (abs(c - self.x), c)) if cols else None
        danger = sorted((b[0], bottom - b[1]) for b in self.bombs if abs(b[0] - self.x) <= 2)
        parts = [
            f"Space Invaders. Your cannon is on the bottom row at x={self.x} (board x from 1 to {p.width - 2}).",
            f"Your shot: {'in flight' if self.bullet else 'ready to fire'}.",
            f"Alien directly above you: {'yes, ' + str(bottom - above) + ' rows up' if above is not None else 'no'}.",
            f"Nearest alien column: x={nearest} ({'left' if nearest < self.x else 'right' if nearest > self.x else 'here'})." if nearest is not None else "",
            f"The wave is moving {'right' if self.direction > 0 else 'left'}; {len(self.aliens)} aliens left; "
            f"the lowest is {bottom - max(cols.values()) if cols else 0} rows above you.",
            "Bombs near you: " + (", ".join(f"x={x} {up} rows up" for x, up in danger) if danger else "none") + ".",
            f"Lives: {self.lives}.",
        ]
        return " ".join(s for s in parts if s)

    def rows(self) -> list[str]:
        """A plain text picture (for the terminal viewer and tests)."""
        p = self.params
        grid = [[" "] * p.width for _ in range(p.height)]
        for x, y in self.aliens:
            grid[y][x] = "W"
        for x, y in self.bombs:
            if 0 <= y < p.height:
                grid[y][x] = "!"
        if self.bullet:
            grid[self.bullet[1]][self.bullet[0]] = "|"
        grid[p.height - 1][self.x] = "A"
        return ["".join(r) for r in grid]
