"""Minimal mIRC formatting for list lines."""
from __future__ import annotations

import re

IRC_COLUMN_PAD = "\u00a0"

_ZNC_PLAYBACK = re.compile(
    r"^\[(?:\d{4}-\d{2}-\d{2}[ T])?\d{1,2}:\d{2}(?::\d{2})?\]\s*"
)


def is_znc_playback(text: str) -> bool:
    """True for bouncer buffer lines such as ``[20:09:16] .banned``."""
    return _ZNC_PLAYBACK.match((text or "").strip()) is not None


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
