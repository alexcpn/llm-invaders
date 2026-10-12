"""Render a game to an animated GIF, drawn the way the terminal game (play.py) looks.

    python3 docs/make_gif.py                     # docs/gameplay.gif: the autopilot, one hit, then the wave cleared
    python3 docs/make_gif.py --seed 3 --interval 0.09 --out out.gif
    python3 docs/make_gif.py --player decision-1 --speed 0.2 --out docs/decision-1.gif   # a live model game (paid)

A model plays as in the benchmark: the game freezes while it decides, then runs on for its measured
latency times the speed before the move lands.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from invaders.agents import Autopilot  # noqa: E402
from invaders.engine import Game  # noqa: E402

BG, BORDER, TEXT, DIM = (16, 20, 24), (90, 100, 110), (225, 230, 232), (140, 150, 156)
COLOURS = {"W": (80, 220, 100), "!": (240, 70, 70), "|": (245, 210, 60), "A": (70, 210, 230)}
POP = ("*", "✱", "✸", "✸", "·")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
CW, CH = 11, 21


def frame(g: Game, font, pop: str | None = None, status: str = "", who: str = "autopilot") -> Image.Image:
    p = g.params
    rows = p.height + 4
    img = Image.new("RGB", (p.width * CW + 2 * CW, rows * CH + 6), BG)
    d = ImageDraw.Draw(img)
    put = lambda col, row, text, colour: d.text((CW + col * CW, 3 + row * CH), text, font=font, fill=colour)  # noqa: E731
    put(0, 0, f"LLM Invaders · aliens {g.total - len(g.aliens):2d}/{g.total}", TEXT)
    put(p.width - 1 - g.params.lives, 0, "♥" * g.lives, COLOURS["!"])
    top = 2
    put(0, top - 1, "+" + "-" * (p.width - 2) + "+", BORDER)
    put(0, top + p.height, "+" + "-" * (p.width - 2) + "+", BORDER)
    for x, y in g.aliens:
        put(x, top + y, "W", COLOURS["W"])
    for x, y in g.bombs:
        if 0 <= y < p.height:
            put(x, top + y, "!", COLOURS["!"])
    if g.bullet:
        put(g.bullet[0], top + g.bullet[1], "|", COLOURS["|"])
    put(g.x, top + p.height - 1, pop or "A", COLOURS["!"] if pop else COLOURS["A"])
    put(0, top + p.height + 1, status or f"{who} · time {g.t:5.1f}s", DIM)
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=32)
    ap.add_argument("--interval", type=float, default=0.08, help="game seconds between the autopilot's decisions")
    ap.add_argument("--frame", type=float, default=0.05, help="game seconds per GIF frame")
    ap.add_argument("--ms", type=int, default=50, help="milliseconds per GIF frame (frame / ms = 1: real game speed)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gameplay.gif"))
    ap.add_argument("--player", default="autopilot", help="autopilot, or a benchmark player such as decision-1, jev, gemma")
    ap.add_argument("--speed", type=float, default=0.2, help="game speed for a model player (its latency is charged)")
    args = ap.parse_args()
    font = ImageFont.truetype(FONT, 17)
    g = Game(seed=args.seed)
    if args.player == "autopilot":
        pilot, who = Autopilot(), "autopilot"
    else:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import bench                                       # the benchmark's players, with its cost ledger
        pilot = bench.PLAYERS[args.player](args.seed)
        who = f"{pilot.name.split(' (')[0]} · {args.speed * 100:g}% speed"
    frames, durations, next_frame, hits = [], [], 0.0, 0
    status, picks = "", []
    while not g.over:                                      # as in the benchmark: decide, the world moves, then the move lands
        t0 = time.monotonic()
        action = pilot.act(g)
        took = time.monotonic() - t0
        picks.append(action)
        dt = args.interval if args.player == "autopilot" else max(0.01, took * args.speed)
        if args.player != "autopilot":
            status = f"{who.split(' ·')[0]}: {action} · {took:.2f}s"
        remaining = dt
        while remaining > 1e-9 and not g.over:             # move the world in small steps so frames can be taken
            step = min(remaining, 0.05)
            g.advance(step)
            remaining -= step
            if g.t >= next_frame:
                frames.append(frame(g, font, status=status, who=who))
                durations.append(args.ms)
                next_frame += args.frame
        g.act(action)
        if g.hits_taken > hits:                            # a bomb landed: the cannon bursts
            hits = g.hits_taken
            for f in POP:
                frames.append(frame(g, font, pop=f, status="Hit!", who=who))
                durations.append(140)
    end = "CLEARED THE WAVE!" if g.won else f"GAME OVER: {g.reason}"
    frames.append(frame(g, font, status=end, who=who))
    if args.player != "autopilot":
        bench.LEDGER.save()
        counts = {a: picks.count(a) for a in sorted(set(picks))}
        print(f"{len(picks)} decisions: {counts}; spent so far ${bench.LEDGER.spent:.4f}")
    durations.append(2500)
    frames[0].save(args.out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"{args.out}: {len(frames)} frames, {sum(durations) / 1000:.1f}s, {os.path.getsize(args.out) / 1e6:.2f} MB, {end}")


if __name__ == "__main__":
    main()
