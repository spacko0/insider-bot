"""Trust an IRC nick only while that connection is identified to NickServ.

A quit drops the nick immediately, so a later client that takes the name is
not treated as the previous user.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

_STATUS = re.compile(r"(?i)^status\s+(\S+)\s+([0-3])\b")
_ACC = re.compile(r"(?i)^(\S+)\s+acc\s+([0-3])\b")

Callback = Callable[[], None]


class NickIdentity:
    def __init__(self, ttl: float = 45.0, fail_hold: float = 15.0):
        self.ttl = ttl
        self.fail_hold = fail_hold
        self._lock = threading.Lock()
        self._ok_until: dict[str, float] = {}
        self._denied_until: dict[str, float] = {}
        self._waiting: dict[str, list[Callback]] = {}
        self._generation: dict[str, int] = {}
        self._status: dict[str, int] = {}
        self._whois_done: set[str] = set()
        self._account: set[str] = set()

    def is_identified(self, nick: str) -> bool:
        key = _key(nick)
        if not key:
            return False
        with self._lock:
            return self._ok_until.get(key, 0.0) > time.monotonic()

    def authorize(self, nick: str, callback: Callback) -> str:
        """Return ``run``, ``ask``, ``wait``, or ``drop``.

        ``run`` means the callback already ran. ``ask`` means the caller
        should query WHOIS and NickServ. ``drop`` means the command is ignored.
        """
        key = _key(nick)
        if not key:
            return "drop"
        with self._lock:
            now = time.monotonic()
            if self._ok_until.get(key, 0.0) > now:
                action = "run"
            elif self._denied_until.get(key, 0.0) > now:
                return "drop"
            elif key in self._waiting:
                self._waiting[key].append(callback)
                return "wait"
            else:
                self._waiting[key] = [callback]
                self._generation[key] = self._generation.get(key, 0) + 1
                self._status.pop(key, None)
                self._whois_done.discard(key)
                self._account.discard(key)
                action = "ask"
        if action == "run":
            callback()
        return action

    def generation(self, nick: str) -> int:
        with self._lock:
            return self._generation.get(_key(nick), 0)

    def note_account(self, nick: str, account: str) -> list[Callback]:
        key = _key(nick)
        if not key or not (account or "").strip():
            return []
        with self._lock:
            self._account.add(key)
            return self._succeed(key)

    def note_status(self, nick: str, code: int) -> list[Callback]:
        key = _key(nick)
        if not key:
            return []
        with self._lock:
            self._status[key] = int(code)
            if int(code) >= 3:
                return self._succeed(key)
            return self._maybe_fail(key)

    def note_whois_end(self, nick: str) -> list[Callback]:
        key = _key(nick)
        if not key:
            return []
        with self._lock:
            self._whois_done.add(key)
            if key in self._account:
                return self._succeed(key)
            return self._maybe_fail(key)

    def expire(self, nick: str, generation: int) -> list[Callback]:
        key = _key(nick)
        with self._lock:
            if self._generation.get(key) != generation or key not in self._waiting:
                return []
            return self._fail(key)

    def forget(self, nick: str) -> None:
        key = _key(nick)
        if not key:
            return
        with self._lock:
            self._ok_until.pop(key, None)
            self._denied_until.pop(key, None)
            self._waiting.pop(key, None)
            self._status.pop(key, None)
            self._whois_done.discard(key)
            self._account.discard(key)
            self._generation[key] = self._generation.get(key, 0) + 1

    def rename(self, old: str, new: str) -> None:
        source = _key(old)
        target = _key(new)
        if not source or not target or source == target:
            return
        with self._lock:
            until = self._ok_until.pop(source, None)
            if until is not None:
                self._ok_until[target] = until
            self._denied_until.pop(source, None)
            self._waiting.pop(source, None)
            self._status.pop(source, None)
            self._whois_done.discard(source)
            self._account.discard(source)
            self._generation[source] = self._generation.get(source, 0) + 1

    def clear(self) -> None:
        with self._lock:
            self._ok_until.clear()
            self._denied_until.clear()
            self._waiting.clear()
            self._status.clear()
            self._whois_done.clear()
            self._account.clear()
            self._generation.clear()

    def observe_services(self, source: str, text: str) -> list[Callback]:
        if (source or "").split("!")[0].casefold() != "nickserv":
            return []
        body = " ".join((text or "").split())
        status = _STATUS.match(body)
        if status:
            return self.note_status(status.group(1), int(status.group(2)))
        acc = _ACC.match(body)
        if acc:
            return self.note_status(acc.group(1), int(acc.group(2)))
        return []

    def _succeed(self, key: str) -> list[Callback]:
        self._ok_until[key] = time.monotonic() + self.ttl
        self._denied_until.pop(key, None)
        self._status.pop(key, None)
        self._whois_done.discard(key)
        self._account.discard(key)
        return self._waiting.pop(key, [])

    def _fail(self, key: str) -> list[Callback]:
        self._denied_until[key] = time.monotonic() + self.fail_hold
        self._status.pop(key, None)
        self._whois_done.discard(key)
        self._account.discard(key)
        self._waiting.pop(key, [])
        return []

    def _maybe_fail(self, key: str) -> list[Callback]:
        if key not in self._waiting:
            return []
        if key in self._account or self._status.get(key, 0) >= 3:
            return self._succeed(key)
        if key not in self._whois_done or key not in self._status:
            return []
        return self._fail(key)


def _key(nick: str) -> str:
    return (nick or "").split("!")[0].strip().casefold()
