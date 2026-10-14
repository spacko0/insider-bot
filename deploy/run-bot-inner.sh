#!/usr/bin/env bash
# Invoked by start-insiderbot-tmux.sh — avoids fragile nested quoting in tmux.
set +e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

PY="${ROOT}/.venv/bin/python"
mkdir -p logs
"$PY" main.py 2>&1 | tee -a logs/tmux-bot.log
ec=${PIPESTATUS[0]}
echo ""
echo "InsiderBot exited with code ${ec}. Scroll up, or: tail -80 logs/tmux-bot.log"
echo "Shell left open — type exit when done."
exec bash --noprofile --norc
