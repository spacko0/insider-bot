"""SQLite lists for registered nicks, site bans, and news links."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from commands.titles import is_placeholder_title


class RegistryError(ValueError):
    """A list change was rejected. The message is safe to show on IRC."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _valid_nick(nick: str) -> bool:
    if not nick or len(nick) > 32:
        return False
    if nick[0] in "#&":
        return False
    bad = set(" ,\t@!+")
    return not any(ch in bad or ord(ch) < 33 for ch in nick)


def _clean_label(raw: str, *, field: str, limit: int) -> str:
    text = " ".join((raw or "").split())
    if not text:
        raise RegistryError(f"{field} is required.")
    if len(text) > limit:
        raise RegistryError(f"{field} is too long (max {limit} characters).")
    return text


class Registry:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS registered (
                    nick TEXT NOT NULL,
                    display_nick TEXT NOT NULL,
                    site_key TEXT NOT NULL,
                    site TEXT NOT NULL,
                    position TEXT NOT NULL,
                    registered_by TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    PRIMARY KEY (nick, site_key)
                );
                CREATE TABLE IF NOT EXISTS banned (
                    nick TEXT NOT NULL,
                    display_nick TEXT NOT NULL,
                    site_key TEXT NOT NULL,
                    site TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (nick, site_key)
                );
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    added_by TEXT NOT NULL,
                    added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_users (
                    nick TEXT PRIMARY KEY,
                    display_nick TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    added_at TEXT NOT NULL
                );
                """
            )
            self._migrate_registered(conn)
            self._pack_news_ids(conn)

    def _migrate_registered(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'registered'"
        ).fetchone()
        if row is None:
            return
        sql = " ".join((row["sql"] or "").split())
        if "PRIMARY KEY (nick, site_key)" in sql:
            return
        conn.execute("ALTER TABLE registered RENAME TO registered_old")
        conn.execute(
            """
            CREATE TABLE registered (
                nick TEXT NOT NULL,
                display_nick TEXT NOT NULL,
                site_key TEXT NOT NULL,
                site TEXT NOT NULL,
                position TEXT NOT NULL,
                registered_by TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                PRIMARY KEY (nick, site_key)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO registered
                (nick, display_nick, site_key, site, position, registered_by, registered_at)
            SELECT nick, display_nick, site_key, site, position, registered_by, registered_at
            FROM registered_old
            """
        )
        conn.execute("DROP TABLE registered_old")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def register(self, nick: str, site: str, position: str, by: str) -> str:
        nick_key, display = self._nick(nick)
        site_text = _clean_label(site, field="Site", limit=48)
        site_key = site_text.casefold()
        position_text = _clean_label(position, field="Position", limit=80)
        actor = (by or "unknown").strip().lower() or "unknown"
        stamp = _now()
        with self._db() as conn:
            existing = conn.execute(
                "SELECT nick FROM registered WHERE nick = ? AND site_key = ?",
                (nick_key, site_key),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO registered
                    (nick, display_nick, site_key, site, position, registered_by, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(nick, site_key) DO UPDATE SET
                    display_nick = excluded.display_nick,
                    site = excluded.site,
                    position = excluded.position,
                    registered_by = excluded.registered_by,
                    registered_at = excluded.registered_at
                """,
                (nick_key, display, site_key, site_text, position_text, actor, stamp),
            )
        return "updated" if existing else "created"

    def is_registered(self, nick: str) -> bool:
        return self.get_registered(nick) is not None

    def get_registered(self, nick: str, site: str | None = None) -> dict | None:
        rows = self.registrations_for(nick)
        if site and site.strip():
            site_key = " ".join(site.split()).casefold()
            for row in rows:
                if row.get("site_key") == site_key:
                    return row
            return None
        return rows[0] if rows else None

    def registrations_for(self, nick: str) -> list[dict]:
        try:
            nick_key, _display = self._nick(nick)
        except RegistryError:
            return []
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM registered WHERE nick = ? ORDER BY site_key",
                (nick_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_registered(self, site: str | None = None) -> list[dict]:
        sql = "SELECT * FROM registered"
        params: tuple = ()
        if site and site.strip():
            sql += " WHERE site_key = ?"
            params = (" ".join(site.split()).casefold(),)
        sql += " ORDER BY registered_at DESC, site_key, nick"
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def unregister(self, nick: str, site: str | None = None) -> bool:
        try:
            nick_key, _display = self._nick(nick)
        except RegistryError:
            return False
        with self._db() as conn:
            if site and site.strip():
                site_key = " ".join(site.split()).casefold()
                cur = conn.execute(
                    "DELETE FROM registered WHERE nick = ? AND site_key = ?",
                    (nick_key, site_key),
                )
            else:
                cur = conn.execute("DELETE FROM registered WHERE nick = ?", (nick_key,))
            return cur.rowcount > 0

    def ban(self, nick: str, site: str, reason: str, by: str) -> str:
        nick_key, display = self._nick(nick)
        site_text = _clean_label(site, field="Site", limit=48)
        site_key = site_text.casefold()
        reason_text = _clean_label(reason, field="Reason", limit=300)
        actor = (by or "unknown").strip().lower() or "unknown"
        stamp = _now()
        with self._db() as conn:
            existing = conn.execute(
                "SELECT nick FROM banned WHERE nick = ? AND site_key = ?",
                (nick_key, site_key),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO banned
                    (nick, display_nick, site_key, site, reason, added_by, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(nick, site_key) DO UPDATE SET
                    display_nick = excluded.display_nick,
                    site = excluded.site,
                    reason = excluded.reason,
                    added_by = excluded.added_by,
                    added_at = excluded.added_at
                """,
                (nick_key, display, site_key, site_text, reason_text, actor, stamp),
            )
        return "updated" if existing else "created"

    def list_banned(self, site: str | None = None) -> list[dict]:
        sql = "SELECT * FROM banned"
        params: tuple = ()
        if site and site.strip():
            sql += " WHERE site_key = ?"
            params = (" ".join(site.split()).casefold(),)
        sql += " ORDER BY added_at DESC, site_key, nick"
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def unban(self, nick: str, site: str | None = None) -> int:
        try:
            nick_key, _display = self._nick(nick)
        except RegistryError:
            return 0
        with self._db() as conn:
            if site and site.strip():
                site_key = " ".join(site.split()).casefold()
                cur = conn.execute(
                    "DELETE FROM banned WHERE nick = ? AND site_key = ?",
                    (nick_key, site_key),
                )
            else:
                cur = conn.execute("DELETE FROM banned WHERE nick = ?", (nick_key,))
            return int(cur.rowcount or 0)

    def add_news(self, url: str, kind: str, note: str, by: str) -> tuple[str, dict]:
        clean_url = (url or "").strip()
        if not clean_url or len(clean_url) > 500:
            raise RegistryError("URL is required and must be 500 characters or less.")
        if kind not in ("article", "reddit"):
            raise RegistryError("News kind must be article or reddit.")
        note_text = " ".join((note or "").split())
        if len(note_text) > 200:
            raise RegistryError("Note is too long (max 200 characters).")
        actor = (by or "unknown").strip().lower() or "unknown"
        stamp = _now()
        with self._db() as conn:
            existing = conn.execute(
                "SELECT * FROM news WHERE url = ?", (clean_url,)
            ).fetchone()
            if existing:
                row = dict(existing)
                if note_text and is_placeholder_title(row.get("note")) and not is_placeholder_title(note_text):
                    conn.execute("UPDATE news SET note = ? WHERE id = ?", (note_text, row["id"]))
                    row["note"] = note_text
                    return "refreshed", row
                return "duplicate", row
            news_id = self._next_news_id(conn)
            conn.execute(
                """
                INSERT INTO news (id, url, kind, note, added_by, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (news_id, clean_url, kind, note_text, actor, stamp),
            )
            row = conn.execute(
                "SELECT * FROM news WHERE url = ?", (clean_url,)
            ).fetchone()
        return "created", dict(row)

    def list_news(self, limit: int) -> list[dict]:
        cap = max(1, int(limit))
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM news ORDER BY id DESC LIMIT ?", (cap,)
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_news(self, news_id: int) -> bool:
        with self._db() as conn:
            cur = conn.execute("DELETE FROM news WHERE id = ?", (int(news_id),))
            return cur.rowcount > 0

    @staticmethod
    def _next_news_id(conn: sqlite3.Connection) -> int:
        """Lowest free news number, so a deleted slot is used by the next add."""
        expect = 1
        for (news_id,) in conn.execute("SELECT id FROM news ORDER BY id"):
            if news_id != expect:
                return expect
            expect += 1
        return expect

    @staticmethod
    def _pack_news_ids(conn: sqlite3.Connection) -> None:
        """Close holes left by the old autoincrement counter."""
        rows = list(conn.execute("SELECT id FROM news ORDER BY id"))
        expect = 1
        for (news_id,) in rows:
            if news_id != expect:
                conn.execute("UPDATE news SET id = ? WHERE id = ?", (expect, news_id))
            expect += 1
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
        ).fetchone():
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'news'")
            conn.execute(
                "INSERT INTO sqlite_sequence(name, seq) SELECT 'news', COALESCE(MAX(id), 0) FROM news"
            )

    def add_bot_user(self, nick: str, by: str) -> str:
        nick_key, display = self._nick(nick)
        actor = (by or "unknown").strip().lower() or "unknown"
        with self._db() as conn:
            existing = conn.execute(
                "SELECT nick FROM bot_users WHERE nick = ?", (nick_key,)
            ).fetchone()
            if existing:
                return "exists"
            conn.execute(
                """
                INSERT INTO bot_users (nick, display_nick, added_by, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (nick_key, display, actor, _now()),
            )
        return "created"

    def remove_bot_user(self, nick: str) -> bool:
        try:
            nick_key, _display = self._nick(nick)
        except RegistryError:
            return False
        with self._db() as conn:
            cur = conn.execute("DELETE FROM bot_users WHERE nick = ?", (nick_key,))
            return cur.rowcount > 0

    def is_bot_user(self, nick: str) -> bool:
        try:
            nick_key, _display = self._nick(nick)
        except RegistryError:
            return False
        with self._db() as conn:
            row = conn.execute(
                "SELECT nick FROM bot_users WHERE nick = ?", (nick_key,)
            ).fetchone()
        return row is not None

    @staticmethod
    def _nick(raw: str) -> tuple[str, str]:
        display = (raw or "").strip()
        if not _valid_nick(display):
            raise RegistryError("Nick must be a single IRC nickname (no spaces).")
        return display.lower(), display
