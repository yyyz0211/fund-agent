"""Briefing composer characterization tests."""

from backend.services.briefing import composer


class TestComposeBriefing:
    """简报合成:mock LLM,验证 prompt 和解析逻辑。"""

    def test_compose_returns_markdown_and_sections(self):
        """LLM 返回合法 JSON 时正确解析 markdown + sections。"""
        from langchain_core.messages import AIMessage

        llm_content = '{"markdown": "# 今日简报\\n\\n沪深300+0.5%", "sections": {"market_snapshot": [], "watchlist_changes": []}}'

        class FakeModel:
            def invoke(self, _prompt):
                return AIMessage(content=llm_content)

        result = composer.compose_briefing(
            {"market_snapshot": [], "watchlist_changes": []},
            model=FakeModel(),
        )

        assert "markdown" in result
        assert "# 今日简报" in result["markdown"]
        assert "sections" in result
        assert "llm_model" in result
        assert result["warnings"] == []

    def test_compose_handles_invalid_llm_json(self):
        """LLM 返回非 JSON 纯文本时:markdown=原文本,warnings 追加 non_json。"""
        from langchain_core.messages import AIMessage

        raw_text = "今日沪深300上涨,自选池表现平稳。"

        class FakeModel:
            def invoke(self, _prompt):
                return AIMessage(content=raw_text)

        result = composer.compose_briefing({}, model=FakeModel())

        # V2: 即使 LLM 返回非 JSON, V2 模块结构仍由后端构建
        assert result["markdown"] == raw_text
        assert "sections" in result
        # warnings 应包含 non_json 提示
        assert any("non_json" in w or "invalid" in w for w in result["warnings"])

    def test_compose_prompt_excludes_policy_blocks(self):
        """prompt 中出现「不构成投资建议」,不出现 policy 红线词。"""
        from langchain_core.messages import AIMessage

        prompt_captured = []

        class FakeModel:
            def invoke(self, prompt):
                prompt_captured.append(str(prompt))
                return AIMessage(content='{"markdown":"ok","sections":{}}')

        composer.compose_briefing({}, model=FakeModel())

        full_prompt = "\n".join(prompt_captured)
        # 正面:必须有简报约束
        assert "不构成投资建议" in full_prompt
        # 负面:不能有"建议加仓"作为肯定性指导语气出现 —— 在禁止清单里
        # 出现是允许的(把它列为禁止词),但不允许在正面的"应当"语境中出现。
        # 检查不能出现"应当加仓 / 请加仓 / 必须加仓"之类的肯定语气。
        for forbidden in ["应当加仓", "请加仓", "必须加仓", "应当减仓", "请减仓", "必须减仓"]:
            assert forbidden not in full_prompt
        # 且 prompt 里要明确出现"禁止"章节(负面词表的上下文是禁止)
        assert "禁止" in full_prompt

    def test_compose_handles_doubled_braces_json(self):
        """Regression: LLM 返回 `{{"markdown": "...", "sections": {...}}}` (outer
        doubled braces) 时, compose_briefing 必须剥外层 braces 后解析, 不能
        落到 raw_content 分支把整串 JSON 当 markdown。

        历史 bug: BRIEFING_PROMPT_TEMPLATE 末尾 JSON 模板用了 `{{...}}`,
        string.Template 不解析 `{`, prompt 原样传到 LLM, LLM 复刻出
        `{{...}}` JSON, frontend ReactMarkdown 把 outer JSON 当 markdown
        渲染成 `<pre><code class="language-json">`。
        """
        from langchain_core.messages import AIMessage

        inner_json = (
            '{"markdown": "# 今日简报\\n\\n沪深300+0.5%",'
            ' "sections": {"market_snapshot": [], "watchlist_changes": []}}'
        )
        # 模拟 LLM 复刻了 prompt 模板里 `{{...}}` 输出的 outer doubled braces
        doubled = "{{" + inner_json + "}}"

        class FakeModel:
            def invoke(self, _prompt):
                return AIMessage(content=doubled)

        result = composer.compose_briefing(
            {"market_snapshot": [], "watchlist_changes": []},
            model=FakeModel(),
        )

        # markdown 必须是 inner markdown 字符串, 不能是 outer doubled JSON
        assert "# 今日简报" in result["markdown"], (
            f"markdown 字段应剥掉 outer braces 后取 inner markdown, "
            f"实际得到: {result['markdown']!r}"
        )
        assert '"sections"' not in result["markdown"], (
            "markdown 字段不应残留 outer JSON 的 `\"sections\":` 字面量"
        )
        # V2: sections 仍是后端构建的 V2 模块结构,与 LLM 输出的 markdown 无关
        assert "sections" in result
        assert "modules" in result["sections"] or "module_order" in result["sections"]
        assert any(
            "wrapped_json" in w or "wrapped" in w for w in result["warnings"]
        ), f"warnings 应记录 wrapped_json fallback, 实际: {result['warnings']}"

    def test_compose_briefing_passes_evidence_to_prompt(self):
        """evidence 参数应被拼入 prompt,LLM 可引用财联社快讯内容。"""
        from langchain_core.messages import AIMessage

        evidence = [
            {
                "id": 1,
                "trade_date": "2026-07-08",
                "category": "policy",
                "title": "央行降准0.25个百分点",
                "summary": "央行宣布下调存款准备金率0.25个百分点",
                "source": "财联社",
                "source_url": "https://example.com/news/1",
                "published_at": "2026-07-08T09:30:00",
                "reliability": 0.9,
            },
            {
                "id": 2,
                "trade_date": "2026-07-08",
                "category": "announcement",
                "title": "宁德时代发布超充电池",
                "summary": "宁德时代发布4C超充电池新品",
                "source": "财联社",
                "source_url": "https://example.com/news/2",
                "published_at": "2026-07-08T10:00:00",
                "reliability": 0.85,
            },
        ]
        prompt_captured = []

        class FakeModel:
            def invoke(self, prompt):
                prompt_captured.append(prompt)
                return AIMessage(content='{"markdown": "test", "sections": {}}')

        composer.compose_briefing(
            {"market_snapshot": []},
            evidence=evidence,
            model=FakeModel(),
        )

        assert len(prompt_captured) == 1, "应恰好调用一次 LLM"
        prompt_text = prompt_captured[0]
        assert "央行降准0.25个百分点" in prompt_text, "evidence.title 应出现在 prompt 中"
        assert "财联社" in prompt_text, "evidence.source 应出现在 prompt 中"
        assert "test_compose_briefing_passes_evidence_to_prompt" not in prompt_text, (
            "测试函数名不应出现在 prompt 中"
        )


def test_composer_owns_both_functions_without_legacy_reexport():
    import inspect

    from backend.services.briefing import composer

    source = inspect.getsource(composer)
    assert "briefing_service" not in source
    assert "module_briefing" not in source
    assert composer.compose_briefing.__module__ == composer.__name__
    assert composer.compose_briefing_v2.__module__ == composer.__name__


def test_compose_briefing_requires_injected_model():
    import pytest

    from backend.services.briefing.composer import compose_briefing

    with pytest.raises(RuntimeError, match="requires `model`"):
        compose_briefing({})
