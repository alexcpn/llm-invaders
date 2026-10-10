"""Build report.html from results.jsonl, ceiling.json and cost-ledger.json.

    python3 report.py            # writes report.html and summary.json
"""

from __future__ import annotations

import collections
import json
import math
import statistics
import time

MODELS = {  # player key -> (label, series class, kind)
    "jev": ("Jev (TypeSafe)", "s-jev", "System-1 decision model, cloud"),
    "decision-1": ("Microsoft-Decision-1", "s-d1", "System-1 decision model, cloud"),
    "gemma": ("Gemma 4 E2B", "s-gemma", "small chat model, local GPU (RTX 3060 laptop)"),
}
LEDGER_MODEL = {"jev": "~typesafe/jev-latest", "decision-1": "microsoft/microsoft-decision-1"}


def load(path: str) -> list[dict]:
    try:
        return [json.loads(line) for line in open(path) if line.strip()]
    except OSError:
        return []


def summarise(results: list[dict], ceiling: dict, ledger: dict) -> dict:
    out = {}
    calls = collections.defaultdict(list)
    for c in ledger.get("calls", []):
        calls[c["model"]].append(c)
    d50 = interpolate_d50(ceiling["autopilot_by_interval"])
    for key, (label, cls, kind) in MODELS.items():
        rows = [r for r in results if r.get("player") == key]
        if not rows:
            continue
        by_speed = collections.defaultdict(list)
        for r in rows:
            by_speed[r["speed"]].append(r)
        points = []
        for speed in sorted(by_speed):
            g = by_speed[speed]
            points.append({"speed": speed, "games": len(g), "wins": sum(r["won"] for r in g),
                           "kills": round(sum(r["kills"] for r in g) / len(g), 1),
                           "d": round(statistics.mean(r["mean_game_s_per_decision"] for r in g), 4),
                           "decisions": sum(r["decisions"] for r in g)})
        lat = [r["latency_median_s"] for r in rows]
        lat90 = [r["latency_p90_s"] for r in rows]
        model_calls = calls.get(LEDGER_MODEL.get(key, ""), [])
        cost = sum(c["cost"] for c in model_calls)
        won = [p for p in points if p["wins"] * 2 > p["games"]]
        med = statistics.median(lat)
        out[key] = {"label": label, "cls": cls, "kind": kind, "points": points,
                    "latency_median_s": round(med, 3), "latency_p90_s": round(statistics.median(lat90), 3),
                    "decisions": sum(r["decisions"] for r in rows), "games": len(rows),
                    "wins": sum(r["won"] for r in rows),
                    "cost_usd": round(cost, 4), "paid_calls": len(model_calls),
                    "usd_per_decision": round(cost / len(model_calls), 7) if model_calls else 0.0,
                    "fastest_winning_speed": max((p["speed"] for p in won), default=None),
                    "fastest_any_win": max(((p["speed"], f'{p["wins"]}/{p["games"]}') for p in points if p["wins"]), default=None),
                    "best_possible_speed": round(d50 / med, 3) if med else None}
    return {"models": out, "ceiling_d50": round(d50, 3)}


def interpolate_d50(rows: list[dict]) -> float:
    """Game seconds per decision at which the autopilot wins half its games."""
    pts = [(r["game_s_per_decision"], r["wins"] / r["games"]) for r in rows]
    for (d1, w1), (d2, w2) in zip(pts, pts[1:]):
        if w1 >= 0.5 > w2:
            return d1 + (w1 - 0.5) / (w1 - w2) * (d2 - d1)
    return pts[-1][0]


# ---------------------------------------------------------------------- charts (inline SVG)

W, H, L, R, T, B = 720, 360, 64, 24, 24, 52


def xlog(v: float, lo: float, hi: float) -> float:
    return L + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (W - L - R)


def yv(v: float) -> float:
    return T + (1 - v) * (H - T - B)


def axes(lo: float, hi: float, ticks: list[float], fmt, xlabel: str) -> str:
    s = []
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        y = yv(v)
        s.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>'
                 f'<text class="tick" x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    for t in ticks:
        x = xlog(t, lo, hi)
        s.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{H - B}"/>'
                 f'<text class="tick" x="{x:.1f}" y="{H - B + 18}" text-anchor="middle">{fmt(t)}</text>')
    s.append(f'<text class="axis" x="{(L + W - R) / 2:.0f}" y="{H - 10}" text-anchor="middle">{xlabel}</text>'
             f'<text class="axis" x="16" y="{(T + H - B) / 2:.0f}" text-anchor="middle" '
             f'transform="rotate(-90 16 {(T + H - B) / 2:.0f})">games won</text>')
    return "".join(s)


def series(points: list[tuple[float, float, str]], cls: str, lo: float, hi: float) -> str:
    pts = [(xlog(x, lo, hi), yv(y), label) for x, y, label in points]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y, _) in enumerate(pts))
    dots = "".join(f'<circle class="{cls} dot" cx="{x:.1f}" cy="{y:.1f}" r="4.5"><title>{label}</title></circle>'
                   for x, y, label in pts)
    return f'<path class="{cls} line" d="{path}"/>' + dots


def chart_speed(summary: dict) -> str:
    lo, hi = 0.02, 1.0
    s = [axes(lo, hi, [0.02, 0.05, 0.1, 0.2, 0.5, 1.0], lambda t: f"{t * 100:g}%", "game speed (100% = full arcade speed), log scale")]
    for key, m in summary["models"].items():
        pts = [(p["speed"], p["wins"] / p["games"], f'{m["label"]}: {p["wins"]}/{p["games"]} wins at {p["speed"] * 100:g}% speed')
               for p in m["points"]]
        s.append(series(pts, m["cls"], lo, hi))
        if m["best_possible_speed"] and lo <= m["best_possible_speed"] <= hi:
            x = xlog(m["best_possible_speed"], lo, hi)
            s.append(f'<line class="{m["cls"]} ceil" x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{H - B}"/>')
    x = xlog(1.0, lo, hi)
    s.append(f'<circle class="s-auto dot" cx="{x:.1f}" cy="{yv(1):.1f}" r="5"><title>Coded autopilot: 20/20 wins at full speed</title></circle>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Win rate against game speed">{"".join(s)}</svg>'


def chart_interval(summary: dict, ceiling: dict) -> str:
    lo, hi = 0.01, 1.0
    s = [axes(lo, hi, [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0], lambda t: f"{t:g} s", "game seconds per decision (latency × speed), log scale")]
    auto = [(r["game_s_per_decision"], r["wins"] / r["games"], f'Autopilot: {r["wins"]}/{r["games"]} at {r["game_s_per_decision"]} s')
            for r in ceiling["autopilot_by_interval"] if lo <= r["game_s_per_decision"] <= hi]
    s.append(series(auto, "s-auto", lo, hi))
    for key, m in summary["models"].items():
        pts = sorted((p["d"], p["wins"] / p["games"], f'{m["label"]}: {p["wins"]}/{p["games"]} at {p["d"]} s per decision')
                     for p in m["points"] if lo <= p["d"] <= hi)
        if pts:
            s.append(series(pts, m["cls"], lo, hi))
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Win rate against game time per decision">{"".join(s)}</svg>'


def pct(v: float | None) -> str:
    return "none" if v is None else f"{v * 100:g}%"


def chart_quality(quality: list[dict]) -> str:
    """Good moves by kind of situation, one bar per model per kind, to scale (0-100%)."""
    kinds = [("aligned", "lined up under an alien"), ("approach", "alien column to one side"), ("dodge", "bomb about to land")]
    order = [k for k in MODELS if any(q["player"] == k for q in quality)]
    rows = {q["player"]: q for q in quality}
    w, left, right, bar, gap, group = 720, 190, 70, 14, 4, 22
    height = 24 + len(kinds) * (len(order) * (bar + gap) + group) + 34
    s, y = [], 20
    x0, x1 = left, w - right
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        x = x0 + v * (x1 - x0)
        s.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="12" y2="{height - 30}"/>'
                 f'<text class="tick" x="{x:.1f}" y="{height - 12}" text-anchor="middle">{int(v * 100)}%</text>')
    for kind, label in kinds:
        s.append(f'<text class="axis" x="8" y="{y + 12}">{label}</text>')
        for key in order:
            k = rows[key]["by_kind"].get(kind, {"good": 0, "of": 1})
            frac = k["good"] / max(1, k["of"])
            s.append(f'<rect class="{MODELS[key][1]} bar" x="{x0}" y="{y}" width="{max(1.5, frac * (x1 - x0)):.1f}" height="{bar}">'
                     f'<title>{MODELS[key][0]}: {k["good"]}/{k["of"]} good</title></rect>'
                     f'<text class="tick" x="{x0 + frac * (x1 - x0) + 6:.1f}" y="{y + bar - 3}">{k["good"]}/{k["of"]}</text>')
            y += bar + gap
        y += group
    return f'<svg viewBox="0 0 {w} {height}" role="img" aria-label="Good moves by situation">{"".join(s)}</svg>'


def build(summary: dict, ceiling: dict, ledger: dict, results: list[dict]) -> str:
    rows = []
    for key, m in summary["models"].items():
        rows.append(f"<tr><th scope=\"row\"><span class=\"key {m['cls']}\"></span>{m['label']}<small>{m['kind']}</small></th>"
                    f"<td>{m['latency_median_s']:.2f} s</td><td>{m['latency_p90_s']:.2f} s</td>"
                    f"<td>{(m['fastest_any_win'][1] + ' at ' + pct(m['fastest_any_win'][0])) if m['fastest_any_win'] else 'never won'}</td><td>{pct(m['best_possible_speed'])}</td>"
                    f"<td>{m['wins']}/{m['games']}</td><td>{m['decisions']:,}</td>"
                    f"<td>{'$' + format(m['usd_per_decision'], '.6f') if m['paid_calls'] else 'free'}</td>"
                    f"<td>{'$' + format(m['cost_usd'], '.3f') if m['paid_calls'] else 'free'}</td></tr>")
    detail = []
    for key, m in summary["models"].items():
        for p in m["points"]:
            detail.append(f"<tr><td>{m['label']}</td><td>{p['speed'] * 100:g}%</td><td>{p['wins']}/{p['games']}</td>"
                          f"<td>{p['kills']}/18</td><td>{p['d']:.3f} s</td><td>{p['decisions']:,}</td></tr>")
    spent = sum(c["cost"] for c in ledger.get("calls", []))
    quality = summary.get("quality", [])
    qrows = "".join(
        f"<tr><th scope=\"row\"><span class=\"key {MODELS[q['player']][1]}\"></span>{MODELS[q['player']][0]}</th>"
        f"<td>{q['good_moves']}/{q['situations']}</td><td>{q['latency_median_s']:.2f} s</td><td>{q['latency_p90_s']:.2f} s</td>"
        f"<td>{q['latency_min_s']:.2f} s</td><td>{', '.join(f'{k} {v}' for k, v in sorted(q['picks'].items(), key=lambda kv: -kv[1]))}</td></tr>"
        for q in quality if q["player"] in MODELS)
    base = ceiling["baselines_wins_of_20"]
    return TEMPLATE.format(
        chart_speed=chart_speed(summary), chart_interval=chart_interval(summary, ceiling),
        chart_quality=chart_quality(quality), qrows=qrows,
        rows="".join(rows), detail="".join(detail), spent=f"${spent:.3f}",
        d50=summary["ceiling_d50"], auto=base.get("autopilot (0.05 s reflex)", 0),
        fire=base.get("always fire", 0), rnd=base.get("random", 0),
        games=len(results), generated=time.strftime("%d %B %Y, %H:%M"),
        **FINDINGS)


FINDINGS = {"headline": "", "finding_1": "", "finding_2": "", "finding_3": ""}   # filled in after the sweep

TEMPLATE = open("report_template.html").read() if __name__ == "__main__" else ""


def main() -> None:
    global TEMPLATE
    TEMPLATE = open("report_template.html").read()
    results = load("results.jsonl") + load("pilot.jsonl")
    ceiling = json.load(open("ceiling.json"))
    ledger = json.load(open("cost-ledger.json"))
    summary = summarise(results, ceiling, ledger)
    try:
        summary["quality"] = json.load(open("quality.json"))
    except OSError:
        summary["quality"] = []
    try:
        FINDINGS.update(json.load(open("findings.json")))
    except OSError:
        pass
    json.dump(summary, open("summary.json", "w"), indent=1)
    open("report.html", "w").write(build(summary, ceiling, ledger, results))
    print(json.dumps(summary, indent=1)[:3000])


if __name__ == "__main__":
    main()
