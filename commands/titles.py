"""Read a page heading for a news link."""
from __future__ import annotations

import html
import json
import logging
import re
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from commands.urls import classify_url
from version import __version__

logger = logging.getLogger(__name__)

_USER_AGENT = f"insider-bot/{__version__} (news titles)"
_READ_LIMIT = 65536
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]*content=["\'](.*?)["\']'
    r'|content=["\'](.*?)["\'][^>]*(?:property|name)=["\']og:title["\']',
    re.IGNORECASE | re.DOTALL,
)
_PLACEHOLDER_TITLES = {
    "reddit",
    "reddit.com",
    "www.reddit.com",
    "welcome to reddit",
    "just a moment",
    "just a moment...",
    "attention required",
}


def fetch_page_title(url: str) -> str | None:
    if classify_url(url) == "reddit":
        for reader in (_reddit_oembed_title, _reddit_json_title):
            title = _try(reader, url)
            if title:
                return title
    return _try(_html_title, url)


def is_placeholder_title(title: str | None) -> bool:
    text = " ".join((title or "").split()).casefold().strip(" .")
    return not text or text in _PLACEHOLDER_TITLES


def title_from_html(page: str) -> str | None:
    og = _OG_TITLE.search(page or "")
    if og:
        raw = og.group(1) or og.group(2) or ""
        cleaned = _clean_title(raw)
        if cleaned:
            return cleaned
    match = _TITLE_TAG.search(page or "")
    if not match:
        return None
    return _clean_title(match.group(1))


def title_from_reddit_json(payload) -> str | None:
    if isinstance(payload, dict) and payload.get("title"):
        return _clean_title(str(payload["title"]))
    listings = payload if isinstance(payload, list) else [payload]
    for listing in listings:
        children = ((listing or {}).get("data") or {}).get("children") or []
        for child in children:
            data = (child or {}).get("data") or {}
            for key in ("title", "link_title"):
                if data.get(key):
                    return _clean_title(str(data[key]))
    return None


def _reddit_oembed_title(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path or "/"
    canonical = "https://www.reddit.com" + path
    body = _fetch("https://www.reddit.com/oembed?url=" + quote(canonical, safe=""))
    if not body:
        return None
    return title_from_reddit_json(json.loads(body.decode("utf-8", errors="replace")))


def _reddit_json_title(url: str) -> str | None:
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/")
    if path.endswith(".json"):
        path = path[: -len(".json")]
    if not path:
        return None
    body = _fetch(f"https://www.reddit.com{path}.json")
    if not body:
        return None
    return title_from_reddit_json(json.loads(body.decode("utf-8", errors="replace")))


def _html_title(url: str) -> str | None:
    body = _fetch(url)
    if not body:
        return None
    return title_from_html(body.decode("utf-8", errors="replace"))


def _try(reader, url: str) -> str | None:
    try:
        return reader(url)
    except Exception as exc:
        logger.info("Could not read a page title for %s: %s", url.split("?", 1)[0], exc)
        return None


def _fetch(url: str) -> bytes | None:
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json,text/html"})
    with urlopen(request, timeout=8) as response:
        return response.read(_READ_LIMIT)


def _clean_title(raw: str) -> str | None:
    text = " ".join(html.unescape(raw or "").split())
    text = re.sub(r"<[^>]+>", "", text).strip()
    if is_placeholder_title(text):
        return None
    if len(text) > 200:
        return text[:199] + "…"
    return text
