"""IRC line batching so long lists do not trip Excess Flood."""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def send_lines_capped(
    send_fn: Callable[[str], None],
    lines: list,
    *,
    max_lines: int = 8,
    pause_sec: float = 10.0,
    truncate_tail: bool = False,
    overflow_template: Optional[str] = None,
) -> None:
    if not lines:
        return

    if truncate_tail and len(lines) > max_lines:
        overflow = len(lines) - max_lines
        total = len(lines)
        tail = lines[-max_lines:]
        for line in tail:
            send_fn(line)
        if overflow_template:
            send_fn(overflow_template.format(overflow=overflow, total=total))
        else:
            send_fn(f"… and {overflow} more ({total} total)")
        return

    for i in range(0, len(lines), max_lines):
        batch = lines[i : i + max_lines]
        for line in batch:
            send_fn(line)
        if i + max_lines < len(lines):
            time.sleep(pause_sec)


def send_via_connection(
    connection,
    target: str,
    lines: list,
    *,
    max_lines: int = 8,
    pause_sec: float = 10.0,
) -> None:
    if not target or not lines:
        return

    def _send(line: str) -> None:
        try:
            connection.send_message(target, line)
        except Exception as exc:
            logger.error("IRC burst send failed: %s", exc)

    send_lines_capped(_send, lines, max_lines=max_lines, pause_sec=pause_sec)
