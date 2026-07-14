"""PolicyPageAdapter: 解析官方政策/披露页的 <a href> 列表, 转成 evidence rows。

策略:
- 优先用 selectolax 解析 HTML (快、CSS 选择器)。
- selectolax 不可用时回退到 stdlib `html.parser` + 正则 (零额外依赖,
  保证在任何 venv 环境都能跑过测试 + 真实数据源)。
- 网络异常或解析异常 → 返回 [], 不抛出。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin

from backend.config.settings import get_settings
from backend.services.market_sources._utils import (
    absolute_url,
    is_plausible_title,
    looks_like_news_link,
)


_DEFAULT_KEYWORDS = ("news", "policy", "notice", "detail", "zcfg", "xwfb")


class _StdlibLinkParser(HTMLParser):
    """Stdlib 回退解析器: 收集 <a href=...>link text</a>。"""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._current_href = None
            self._current_text = []
            for k, v in attrs:
                if k.lower() == "href":
                    self._current_href = v or ""
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
    """先试 selectolax，回退到 stdlib html.parser。"""
    links = _parse_with_selectolax(html)
    if links:
        return links
    return _parse_with_stdlib(html)


class PolicyPageAdapter:
    """解析政府/交易所公开页面, 输出 policy 类 evidence。"""

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
        self.keyword_filter = tuple(keyword_filter) if keyword_filter else _DEFAULT_KEYWORDS
        self.max_rows = max(1, int(max_rows))

    def fetch(self, *, client, trade_date: str, brief_type: str = "post_market") -> list[dict]:
        """拉取并解析页面, 返回 evidence 列表。失败返回 []。"""
        try:
            resp = client.get(
                self.url,
                timeout=get_settings().market_policy_page_timeout_seconds,
            )
            status = getattr(resp, "status_code", 200)
            if status and status >= 400:
                return []
            text = getattr(resp, "text", "") or ""
            if not text:
                return []
            return self._parse(text, trade_date=trade_date, brief_type=brief_type)
        except Exception:
            return []

    def _parse(self, html: str, *, trade_date: str, brief_type: str) -> list[dict]:
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
    """从标题中粗略抽取主题关键词 (中文 2-8 字片段)。"""
    candidates = ("创新药", "新能源", "半导体", "人工智能", "光伏", "医药",
                  "汽车", "金融", "房地产", "消费", "军工", "教育")
    return [c for c in candidates if c in title]  # noqa: E501