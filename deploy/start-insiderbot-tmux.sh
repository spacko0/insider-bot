#!/usr/bin/env bash
# Start InsiderBot in its own detached tmux session.
# Usage (from repo root):  ./deploy/start-insiderbot-tmux.sh
# Env overrides:
#   INSIDERBOT_SESSION   tmux session name (default: insider-bot)
#   INSIDERBOT_ROOT      path to repo root (default: parent of deploy/)

set -euo pipefail

INSIDERBOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${INSIDERBOT_SESSION:-insider-bot}"
PY="${INSIDERBOT_ROOT}/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "Missing venv Python: $PY"
  echo "Create it from repo root: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' already exists."
  echo "  Attach:    tmux attach -t $SESSION"
  echo "  Kill:      tmux kill-session -t $SESSION"
  exit 1
fi

mkdir -p "${INSIDERBOT_ROOT}/logs"
INNER="${INSIDERBOT_ROOT}/deploy/run-bot-inner.sh"
if [[ ! -f "$INNER" ]]; then
  echo "Missing $INNER"
  exit 1
fi
chmod +x "$INNER" 2>/dev/null || true

tmux new-session -d -s "$SESSION" -c "$INSIDERBOT_ROOT" "$INNER"

echo "Started InsiderBot in tmux session '$SESSION' (cwd: $INSIDERBOT_ROOT)"
echo "  Attach:    tmux attach -t $SESSION"
echo "  Detach:    Ctrl-b then d"
echo "  Logs:      tail -f logs/tmux-bot.log"
echo "  Stop:      tmux kill-session -t $SESSION"
