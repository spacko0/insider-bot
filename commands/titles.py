"""Read a page heading for a news link."""
from __future__ import annotations

import html
import json
import logging
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from commands.urls import classify_url

logger = logging.getLogger(__name__)

_USER_AGENT = "InsiderBot/0.1"
_READ_LIMIT = 65536
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]*content=["\'](.*?)["\']'
    r'|content=["\'](.*?)["\'][^>]*(?:property|name)=["\']og:title["\']',
    re.IGNORECASE | re.DOTALL,
)


def fetch_page_title(url: str) -> str | None:
    try:
        if classify_url(url) == "reddit":
            title = _reddit_title(url)
            if title:
                return title
        body = _fetch(url)
        if not body:
            return None
        return title_from_html(body.decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.info("Could not read a page title for %s: %s", url.split("?", 1)[0], exc)
        return None


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
    listings = payload if isinstance(payload, list) else [payload]
    for listing in listings:
        children = ((listing or {}).get("data") or {}).get("children") or []
        for child in children:
            data = (child or {}).get("data") or {}
            if data.get("title"):
                return _clean_title(str(data["title"]))
    return None


def _reddit_title(url: str) -> str | None:
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


def _fetch(url: str) -> bytes | None:
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=6) as response:
        return response.read(_READ_LIMIT)


def _clean_title(raw: str) -> str | None:
    text = " ".join(html.unescape(raw or "").split())
    text = re.sub(r"<[^>]+>", "", text).strip()
    if not text:
        return None
    if len(text) > 200:
        return text[:199] + "…"
    return text
