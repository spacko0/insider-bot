"""Minimal mIRC formatting for list lines."""
from __future__ import annotations

import re

IRC_COLUMN_PAD = "\u00a0"


def irc_strip_mirc(text: str) -> str:
    text = (text or "").replace("\x11", "").replace("\x0f", "")
    return re.sub(r"\x03(?:\d{1,2})?(?:,\d{1,2})?", "", text)


def irc_monospace(text: str) -> str:
    if not text or text.startswith("\x11"):
        return text
    return f"\x11{text}\x11"


def irc_pad_visible(text: str, width: int) -> str:
    need = max(0, width - len(irc_strip_mirc(text)))
    return text + IRC_COLUMN_PAD * need


def irc_mirc_color(text: str, code: str, enabled: bool) -> str:
    if not enabled or not (code or "").strip():
        return text
    c = str(code).strip()
    if len(c) == 1:
        c = f"0{c}"
    return f"\x03{c}{text}\x03"
