#!/usr/bin/env bash
# Invoked by start-insiderbot-tmux.sh — avoids fragile nested quoting in tmux.
set +e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

PY="${ROOT}/.venv/bin/python"
mkdir -p logs
# Start with a clean environment so a parent shell cannot supply another bot's settings.
env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  USER="${USER:-}" \
  LOGNAME="${LOGNAME:-${USER:-}}" \
  LANG="${LANG:-C.UTF-8}" \
  TERM="${TERM:-dumb}" \
  TMPDIR="${TMPDIR:-/tmp}" \
  "$PY" main.py 2>&1 | tee -a logs/tmux-bot.log
ec=${PIPESTATUS[0]}
echo ""
echo "InsiderBot exited with code ${ec}. Scroll up, or: tail -80 logs/tmux-bot.log"
echo "Shell left open — type exit when done."
exec bash --noprofile --norc
