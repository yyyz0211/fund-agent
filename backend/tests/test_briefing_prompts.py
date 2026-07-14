"""Briefing 专属 prompt 模板测试。

历史 bug regression (`test_briefing_prompt_does_not_use_doubled_braces_for_json`):
BRIEFING_PROMPT_TEMPLATE 末尾 JSON 模板必须用单 `{ ... }`,
不能用 `{{ ... }}`。`Template.substitute()` 不解析 `{ }`,所以 `{{` 会原样
传给 LLM,导致 LLM 返回 `{{...}}` 形式, json.loads 解析失败落到 raw_content
分支, `briefing_service.compose_briefing` 把整串 outer doubled braces 当
markdown 返回,前端 ReactMarkdown 渲染成 `<pre><code class="language-json">`。
"""
from string import Template

from backend.services.briefing.prompts import (
    BRIEFING_PROMPT_TEMPLATE,
    BRIEFING_PROMPT_TEMPLATE_V2,
)


def test_briefing_prompts_are_exported():
    """两个 prompt 模板必须可从 briefing.prompts 直接导入。"""
    assert isinstance(BRIEFING_PROMPT_TEMPLATE, str)
    assert isinstance(BRIEFING_PROMPT_TEMPLATE_V2, Template)


def test_briefing_prompt_v2_requires_brief_type_placeholder():
    """V2 prompt 用 Template,必须包含 ${brief_type} / ${profile_json} 等占位符。"""
    rendered = BRIEFING_PROMPT_TEMPLATE_V2.template
    assert "${brief_type}" in rendered
    assert "${profile_json}" in rendered
    assert "${module_sections_json}" in rendered


def test_briefing_prompt_does_not_use_doubled_braces_for_json():
    """Regression: BRIEFING_PROMPT_TEMPLATE 末尾 JSON 模板必须用单 `{ ... }`。"""
    rendered = Template(BRIEFING_PROMPT_TEMPLATE).substitute(
        snapshot_json='{"market_snapshot": []}',
        evidence_json='[]',
    )
    assert "{{" not in rendered, (
        "BRIEFING_PROMPT_TEMPLATE substitute 后含 `{{` —— "
        "会原样传给 LLM, 导致返回 markdown 字段包成 JSON 字符串。"
    )
    assert '"markdown"' in rendered
    assert '"sections"' in rendered
    assert rendered.index("{") < rendered.index('"markdown"')


def test_briefing_prompt_v2_substitutes_all_placeholders():
    """V2 prompt 应能完整 substitute 不留占位符。"""
    rendered = BRIEFING_PROMPT_TEMPLATE_V2.substitute(
        brief_type="post_market",
        profile_json="{}",
        module_sections_json="{}",
        snapshot_json="{}",
        evidence_json="[]",
        max_markdown_words=1000,
    )
    assert "${" not in rendered, f"V2 prompt 有未替换占位符: {rendered}"