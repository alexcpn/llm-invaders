"""Play LLM Invaders in the terminal, or watch a player.

    python3 play.py                          # you play: ←/→ or A/D move, SPACE fires, P pauses, Q quits
    python3 play.py --speed 0.3              # the same game at 30% speed
    python3 play.py --player autopilot       # watch the coded autopilot (free)
    python3 play.py --player jev --speed 0.1 # watch Jev (paid; needs the key in .config/openrouter.env)
    python3 play.py --player gemma --speed 0.3   # watch the local model through Ollama

A model sees the board when it is asked; the game keeps running while it thinks, and its move lands
when the answer arrives (the same as the benchmark's latency charging).
"""

from __future__ import annotations

import argparse
import copy
import curses
import threading
import time

from invaders.engine import Game

FRAME = 1 / 30
KEYS = {curses.KEY_LEFT: "left", ord("a"): "left", ord("A"): "left",
        curses.KEY_RIGHT: "right", ord("d"): "right", ord("D"): "right", ord(" "): "fire"}


def draw(win, g: Game, title: str, status: str) -> None:
    win.erase()
    p = g.params
    h, w = win.getmaxyx()
    if h < p.height + 5 or w < p.width + 2:
        win.addstr(0, 0, f"Please enlarge the terminal to {p.width + 2} x {p.height + 5}."[: w - 1])
        win.refresh()
        return
    put = lambda y, x, s, a=0: win.addstr(y, x, s, a) if 0 <= y < h and 0 <= x < w - len(s) else None  # noqa: E731
    put(0, 0, f"{title}  aliens {g.total - len(g.aliens)}/{g.total}  lives {'♥' * g.lives}  time {g.t:5.1f}s", curses.A_BOLD)
    top = 2
    put(top - 1, 0, "+" + "-" * (p.width - 2) + "+")
    for x, y in g.aliens:
        put(top + y, x, "W", curses.color_pair(1) | curses.A_BOLD)
    for x, y in g.bombs:
        if 0 <= y < p.height:
            put(top + y, x, "!", curses.color_pair(2) | curses.A_BOLD)
    if g.bullet:
        put(top + g.bullet[1], g.bullet[0], "|", curses.color_pair(3) | curses.A_BOLD)
    put(top + p.height - 1, g.x, "A", curses.color_pair(4) | curses.A_BOLD)
    put(top + p.height, 0, "+" + "-" * (p.width - 2) + "+")
    put(top + p.height + 1, 0, status[: w - 1])
    win.refresh()


def make_player(name: str):
    import bench                                          # the same players as the benchmark (and its budget guard)
    return bench.PLAYERS[name](0)


def run(win, args) -> None:
    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    for i, col in enumerate((curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_CYAN), 1):
        curses.init_pair(i, col, bg)
    win.nodelay(True)
    win.keypad(True)
    g = Game(seed=args.seed)
    human = args.player == "human"
    agent = None if human else make_player(args.player)
    title = f"LLM Invaders · {'you' if human else agent.name} · speed {args.speed:g}"
    pending: dict = {}
    paused, last, decisions, waits = False, time.monotonic(), 0, []

    def think(view: Game) -> None:                        # a model decides on a copy of the board
        t0 = time.monotonic()
        try:
            pending["action"] = agent.act(view)
        except Exception as exc:                          # e.g. the budget guard: stop asking
            pending["action"], pending["error"] = "wait", str(exc)[:60]
        pending["took"] = time.monotonic() - t0

    while not g.over:
        key = win.getch()
        while key != -1:
            if key in (ord("q"), ord("Q")):
                return
            if key in (ord("p"), ord("P")):
                paused = not paused
            elif human and key in KEYS and not paused:
                g.act(KEYS[key])
            key = win.getch()
        now = time.monotonic()
        if not paused:
            g.advance((now - last) * args.speed)
            if agent is not None:
                if "action" in pending:                   # the answer arrived: its move lands now
                    g.act(pending.pop("action"))
                    waits.append(pending.pop("took"))
                    decisions += 1
                    pending.pop("thread", None)
                if "thread" not in pending and "error" not in pending:
                    pending["thread"] = threading.Thread(target=think, args=(copy.deepcopy(g),), daemon=True)
                    pending["thread"].start()
        last = now
        if human:
            status = "←/→ or A/D move · SPACE fire · P pause · Q quit" + ("   PAUSED" if paused else "")
        else:
            avg = sum(waits[-20:]) / len(waits[-20:]) if waits else 0
            status = f"{decisions} decisions · {avg:.2f}s per decision · P pause · Q quit" + ("   PAUSED" if paused else "")
            if "error" in pending:
                status = f"model stopped: {pending['error']}"
        draw(win, g, title, status)
        time.sleep(FRAME)
    draw(win, g, title, f"{'YOU WIN' if g.won else 'GAME OVER'}: {g.reason}. Press any key.")
    win.nodelay(False)
    win.getch()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--player", default="human", choices=["human", "autopilot", "always-fire", "random", "jev", "decision-1", "gemma"])
    ap.add_argument("--speed", type=float, default=1.0, help="game speed, 1 = full speed")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    curses.wrapper(lambda win: run(win, args))


if __name__ == "__main__":
    main()
