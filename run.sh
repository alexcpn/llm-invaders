#!/bin/sh
# Run bench.py with the OpenRouter key from the environment, or from dk-game's config (never printed).
cd "$(dirname "$0")"
if [ -z "$OPENROUTER_API_KEY" ]; then
  for f in .config/openrouter.env ../dk-game/.config/opneroutere.env; do
    [ -f "$f" ] && OPENROUTER_API_KEY=$(sed -n 's/^[[:space:]]*OPENROUTER_API_KEY=//p' "$f" | head -1 | tr -d "'\" ") && break
  done
  export OPENROUTER_API_KEY
fi
exec python3 bench.py "$@"
