"""Classify news links as articles or reddit posts."""
from __future__ import annotations

from urllib.parse import urlparse

_REDDIT_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "new.reddit.com",
    "np.reddit.com",
    "redd.it",
    "www.redd.it",
}


def classify_url(raw: str) -> str | None:
    """Return ``reddit`` or ``article`` for an http(s) URL, else None."""
    text = (raw or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    host = parsed.netloc.lower().split(":")[0]
    if host in _REDDIT_HOSTS or host.endswith(".reddit.com") or host.endswith(".redd.it"):
        return "reddit"
    return "article"
