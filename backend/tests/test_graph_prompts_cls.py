"""CLS prompt guidance tests."""
from __future__ import annotations


def test_system_prompt_mentions_news_category_and_cls_search():
    from backend.graph.prompts import get_system_prompt

    prompt = get_system_prompt()

    assert 'category="news"' in prompt
    assert "search_cls_telegraph" in prompt
    assert "财联社" in prompt
    assert "事实整理" in prompt
