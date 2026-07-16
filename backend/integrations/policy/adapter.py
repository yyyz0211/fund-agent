"""Official policy-page links to market-evidence rows."""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Iterable

from backend.config.settings import get_settings
from backend.integrations._html import (
    absolute_url,
    is_plausible_title,
    looks_like_news_link,
)


_DEFAULT_KEYWORDS = ("news", "policy", "notice", "detail", "zcfg", "xwfb")


class _StdlibLinkParser(HTMLParser):
    """Collect anchor href and text using the standard-library parser."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._current_href = None
            self._current_text = []
            for key, value in attrs:
                if key.lower() == "href":
                    self._current_href = value or ""
                    break

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._current_href is not None:
            text = "".join(self._current_text).strip()
            self.links.append((self._current_href, text))
            self._current_href = None
            self._current_text = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._current_text.append(data)


def _parse_with_stdlib(html: str) -> list[tuple[str, str]]:
    parser = _StdlibLinkParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    return parser.links


def _parse_with_selectolax(html: str) -> list[tuple[str, str]]:
    try:
        from selectolax.parser import HTMLParser as SHTMLParser  # type: ignore
    except Exception:
        return []
    try:
        tree = SHTMLParser(html)
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for node in tree.css("a[href]"):
        href = node.attributes.get("href", "") or ""
        title = (node.text() or "").strip()
        out.append((href, title))
    return out


def _parse_links(html: str) -> list[tuple[str, str]]:
    links = _parse_with_selectolax(html)
    if links:
        return links
    return _parse_with_stdlib(html)


class PolicyPageAdapter:
    """Parse a public policy page into policy evidence."""

    def __init__(
        self,
        *,
        source: str,
        url: str,
        reliability: str = "official",
        keyword_filter: Iterable[str] | None = None,
        max_rows: int = 10,
    ):
        self.source = source
        self.url = url
        self.reliability = reliability
        self.keyword_filter = (
            tuple(keyword_filter) if keyword_filter else _DEFAULT_KEYWORDS
        )
        self.max_rows = max(1, int(max_rows))

    def fetch(
        self,
        *,
        client,
        trade_date: str,
        brief_type: str = "post_market",
    ) -> list[dict]:
        try:
            response = client.get(
                self.url,
                timeout=get_settings().market_policy_page_timeout_seconds,
            )
            status = getattr(response, "status_code", 200)
            if status and status >= 400:
                return []
            text = getattr(response, "text", "") or ""
            if not text:
                return []
            return self._parse(
                text,
                trade_date=trade_date,
                brief_type=brief_type,
            )
        except Exception:
            return []

    def _parse(
        self,
        html: str,
        *,
        trade_date: str,
        brief_type: str,
    ) -> list[dict]:
        links = _parse_links(html)
        out: list[dict] = []
        seen: set[str] = set()
        for href_raw, title in links:
            if not is_plausible_title(title):
                continue
            if not looks_like_news_link(href_raw, self.keyword_filter):
                continue
            url = absolute_url(self.url, href_raw)
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "trade_date": trade_date,
                "brief_type": brief_type,
                "category": "policy",
                "source": self.source,
                "source_url": url,
                "title": title,
                "summary": "",
                "symbols": _extract_symbols(title),
                "metrics": None,
                "published_at": trade_date,
                "reliability": self.reliability,
            })
            if len(out) >= self.max_rows:
                break
        return out


def _extract_symbols(title: str) -> list[str]:
    candidates = (
        "创新药",
        "新能源",
        "半导体",
        "人工智能",
        "光伏",
        "医药",
        "汽车",
        "金融",
        "房地产",
        "消费",
        "军工",
        "教育",
    )
    return [candidate for candidate in candidates if candidate in title]
