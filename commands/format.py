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
    grouped = _group_bans(rows)
    if not grouped:
        return ["No banned users."]
    lines = [irc_mirc_color(f"Banned ({len(grouped)})", "04", colors)]
    lines.extend(_table(("Date", "Site", "User", "Reason"), grouped, limits=(10, 48, 16, 80)))
    return lines


def _group_bans(rows: list[dict]) -> list[list[str]]:
    """One row per nick. Sites and reasons stay in the same order."""
    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        nick = (row.get("nick") or row.get("display_nick") or "?").casefold()
        if nick not in grouped:
            grouped[nick] = []
            order.append(nick)
        grouped[nick].append(row)
    table: list[list[str]] = []
    for nick in order:
        items = sorted(grouped[nick], key=lambda item: (item.get("added_at") or "", item.get("site") or ""))
        main = _ban_date(items[0].get("added_at"))
        sites: list[str] = []
        reasons: list[str] = []
        for item in items:
            site = item.get("site") or "?"
            when = _ban_date(item.get("added_at"))
            if when != main and len(when) >= 10:
                site = f"{site} ({when[5:10]})"
            sites.append(site)
            reasons.append(item.get("reason") or "")
        display = items[0].get("display_nick") or nick
        table.append([main, ", ".join(sites), display, ", ".join(reasons)])
    return table


def _table(
    headers: tuple[str, ...],
    rows: list[list[str]],
    limits: tuple[int, ...] = (10, 16, 16, 24),
) -> list[str]:
    minimums = (_DATE_WIDTH, _SITE_WIDTH, _NICK_WIDTH, _LAST_WIDTH)
    widths = []
    for index, minimum in enumerate(minimums):
        longest = len(headers[index])
        limit = limits[index]
        for cells in rows:
            longest = max(longest, len(_clip(cells[index], limit)))
        widths.append(min(limit, max(minimum, longest)))
    width_tuple = tuple(widths)
    lines = [_table_row(list(headers), width_tuple)]
    lines.extend(_table_row(cells, width_tuple) for cells in rows)
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
