"""IRC lines for the registered, banned, and news lists."""
from __future__ import annotations

from utils.irc_format import irc_mirc_color, irc_monospace, irc_pad_visible

_DATE_WIDTH = 10
_SITE_WIDTH = 16
_NICK_WIDTH = 16
_LAST_WIDTH = 24


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_registered(rows: list[dict], *, colors: bool) -> list[str]:
    if not rows:
        return ["No registered users."]
    lines = [irc_mirc_color(f"Registered ({len(rows)})", "07", colors)]
    lines.extend(
        _table(
            ("Date", "Site", "User", "Position"),
            [
                [
                    _ban_date(row.get("registered_at")),
                    row.get("site") or "?",
                    row.get("display_nick") or "?",
                    row.get("position") or "",
                ]
                for row in rows
            ],
        )
    )
    return lines


def format_banned(rows: list[dict], *, colors: bool) -> list[str]:
    if not rows:
        return ["No banned users."]
    lines = [irc_mirc_color(f"Banned ({len(rows)})", "04", colors)]
    lines.extend(
        _table(
            ("Date", "Site", "User", "Reason"),
            [
                [
                    _ban_date(row.get("added_at")),
                    row.get("site") or "?",
                    row.get("display_nick") or "?",
                    row.get("reason") or "",
                ]
                for row in rows
            ],
        )
    )
    return lines


def _table(headers: tuple[str, ...], rows: list[list[str]]) -> list[str]:
    widths = (_DATE_WIDTH, _SITE_WIDTH, _NICK_WIDTH, _LAST_WIDTH)
    lines = [_table_row(list(headers), widths)]
    lines.extend(_table_row(cells, widths) for cells in rows)
    return lines


def _table_row(cells: list[str], widths: tuple[int, ...]) -> str:
    padded = [
        irc_pad_visible(_clip(cell, width), width) for cell, width in zip(cells, widths)
    ]
    return irc_monospace(" | ".join(padded))


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
