# LLM Invaders

How fast can a game run before a fast decision model stops winning it?

A small, deterministic Space Invaders where the player is a model: the System-1 decision models
**Jev** (TypeSafe) and **Microsoft-Decision-1**, which return a probability per fixed option instead
of writing text, and **Gemma 4 E2B** on a local laptop GPU for comparison. Each decision the game
freezes, the model picks one action (left, right, fire, wait), and the game then runs on for the
model's real latency times the game speed before the action lands. Sweeping the game speed gives
each model's speed limit.

The report with the results and timings is `report.html` (published as an artifact); the raw data is
in `results.jsonl`, `ceiling.json`, `summary.json` and `cost-ledger.json`.

## Run it

```bash
python3 -m unittest -v test_invaders                       # engine, harness, budget guard
./run.sh --players autopilot,always-fire,random --speeds 1 --seeds 0-19 --out baselines.jsonl
./run.sh --players jev,decision-1 --speeds 0.05,0.1,0.2 --seeds 0-2 --workers 3
./run.sh --players gemma --speeds 0.1,0.25,0.5 --seeds 0-2   # needs Ollama with gemma4:e2b
python3 report.py                                           # report.html + summary.json
```

`run.sh` reads `OPENROUTER_API_KEY` from the environment or `.config/openrouter.env` (git-ignored).
Every paid call is written to `cost-ledger.json`; paid calls stop at $1.90 (budget $2.00).

## Files

```
invaders/engine.py    the game, timed in game seconds (advance(dt) moves time; act() moves the cannon)
invaders/agents.py    coded baselines, DecisionModel (OpenRouter /api/alpha/decisions), LocalModel (Ollama)
invaders/harness.py   one game with latency charged in game time
invaders/budget.py    the cost ledger and hard stop, shared safely across processes
bench.py              the speed sweep; results.jsonl gets one line per game
report.py             summary.json and report.html (report_template.html)
```
