"""共享工具: 解析 HTML、构造绝对 URL、清洗字符串。
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin


def absolute_url(base: str, href: str) -> str | None:
    """把相对 URL 解析成绝对 URL; href 为空/None/非 http(s) 时返回 None。"""
    if not href:
        return None
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def is_plausible_title(text: str, *, min_len: int = 4, max_len: int = 80) -> bool:
    """粗筛标题: 长度合适, 非纯数字/标点, 至少包含一个中文字符或英文字母。"""
    if not text:
        return False
    stripped = text.strip()
    if not (min_len <= len(stripped) <= max_len):
        return False
    # 必须有中文或英文
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", stripped):
        return False
    return True


def looks_like_news_link(href: str, keywords: Iterable[str]) -> bool:
    """href 是否包含任一关键词 (大小写不敏感)。"""
    if not href:
        return False
    lower = href.lower()
    return any(kw.lower() in lower for kw in keywords)