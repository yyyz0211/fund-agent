"""Private HTML and URL helpers for market-evidence integrations."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin


def absolute_url(base: str, href: str) -> str | None:
    """Resolve a relative HTTP URL against a base URL."""
    if not href:
        return None
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def is_plausible_title(
    text: str,
    *,
    min_len: int = 4,
    max_len: int = 80,
) -> bool:
    """Return whether text looks like a human-readable title."""
    if not text:
        return False
    stripped = text.strip()
    if not (min_len <= len(stripped) <= max_len):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", stripped))


def looks_like_news_link(href: str, keywords: Iterable[str]) -> bool:
    """Return whether an href contains any configured keyword."""
    if not href:
        return False
    lower = href.lower()
    return any(keyword.lower() in lower for keyword in keywords)
