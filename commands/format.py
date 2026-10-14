"""IRC lines for the registered, banned, and news lists."""
from __future__ import annotations

from utils.irc_format import irc_mirc_color, irc_monospace, irc_pad_visible

_NICK_WIDTH = 16


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_registered(rows: list[dict], *, colors: bool) -> list[str]:
    if not rows:
        return ["No registered users."]
    lines = [irc_mirc_color(f"Registered ({len(rows)})", "07", colors)]
    lines.append(
        irc_monospace(
            f"{irc_pad_visible('Date', 10)} | {irc_pad_visible('Site', 16)} | "
            f"{irc_pad_visible('User', _NICK_WIDTH)} | Position"
        )
    )
    for row in rows:
        date = _ban_date(row.get("registered_at"))
        site = irc_pad_visible(_clip(row.get("site") or "?", 16), 16)
        nick = irc_pad_visible(_clip(row.get("display_nick") or "?", _NICK_WIDTH), _NICK_WIDTH)
        position = _clip(row.get("position") or "", 80)
        lines.append(irc_monospace(f"{date} | {site} | {nick} | {position}"))
    return lines


def format_banned(rows: list[dict], *, colors: bool) -> list[str]:
    if not rows:
        return ["No banned users."]
    lines = [irc_mirc_color(f"Banned ({len(rows)})", "04", colors)]
    lines.append(
        irc_monospace(
            f"{irc_pad_visible('Date', 10)} | {irc_pad_visible('Site', 16)} | "
            f"{irc_pad_visible('User', _NICK_WIDTH)} | Reason"
        )
    )
    for row in rows:
        when = _clip(_ban_date(row.get("added_at")), 10)
        site = _clip(row.get("site") or "?", 16)
        nick = _clip(row.get("display_nick") or "?", _NICK_WIDTH)
        reason = _clip(row.get("reason") or "", 180)
        lines.append(
            irc_monospace(
                f"{irc_pad_visible(when, 10)} | {irc_pad_visible(site, 16)} | "
                f"{irc_pad_visible(nick, _NICK_WIDTH)} | {reason}"
            )
        )
    return lines


def _ban_date(stamp: str | None) -> str:
    text = (stamp or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text or "?"


def format_news(rows: list[dict], *, colors: bool, prefix: str = ".") -> list[str]:
    if not rows:
        return [f"No news yet. Add a link with {prefix}addnews <url>"]
    lines = [irc_mirc_color(f"News ({len(rows)})", "07", colors)]
    for row in rows:
        kind = "reddit" if row.get("kind") == "reddit" else "article"
        note = _clip(row.get("note") or "", 80)
        url = _clip(row.get("url") or "", 300)
        label = irc_mirc_color(f"[{kind}]", "12" if kind == "reddit" else "03", colors)
        if note:
            lines.append(f"#{row.get('id')} {label} {note} — {url}")
        else:
            lines.append(f"#{row.get('id')} {label} {url}")
    return lines
