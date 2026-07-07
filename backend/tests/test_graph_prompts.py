"""Graph prompt 模块测试。

验证 system prompt:
- 是非空字符串
- 包含核心角色定义(本地决策辅助、规则结论边界)
- 包含工具调用约定(用什么工具回答哪类问题)
- 包含回答格式规范(数字 + source/as_of + 表格)
- 包含风险边界(不确定预测、不强制交易、不掩饰缺失)
- 包含 few-shot 至少一个示例
"""
from backend.graph.prompts import get_system_prompt, FEW_SHOT_EXAMPLES


def test_system_prompt_is_non_empty_string():
    prompt = get_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 200


def test_system_prompt_states_role():
    prompt = get_system_prompt()
    assert "基金" in prompt
    # 必须明确角色边界
    assert "规则结论" in prompt
    assert "强制" in prompt or "必须" in prompt


def test_system_prompt_states_compliance_constraints():
    prompt = get_system_prompt()
    # 必须强调不确定预测、不掩饰缺失
    assert "预测" in prompt or "保证" in prompt
    assert "缺失" in prompt or "缺" in prompt
    assert "建议买入" in prompt
    assert "不是强制交易指令" in prompt


def test_system_prompt_contains_tool_contract():
    prompt = get_system_prompt()
    # 必须告诉 LLM 何时用什么工具(至少出现一个工具名)
    assert any(tool in prompt for tool in [
        "diagnose_fund_auto",
        "lookup_fund_auto",
        "diagnose_fund",
        "get_latest_fund_nav",
        "calculate_fund_metrics",
    ])
    assert "lookup_fund_auto" in prompt
    assert "diagnose_fund_auto" in prompt


def test_system_prompt_requires_source_and_date():
    prompt = get_system_prompt()
    assert "source" in prompt.lower()
    assert "as_of" in prompt.lower()


def test_few_shot_examples_is_non_empty():
    """至少有一个示例对话,引导 LLM 学习期望的回答形态。"""
    assert isinstance(FEW_SHOT_EXAMPLES, list)
    assert len(FEW_SHOT_EXAMPLES) >= 1
    for ex in FEW_SHOT_EXAMPLES:
        assert "user" in ex
        assert "assistant" in ex


def test_few_shot_examples_use_rule_labels_not_direct_orders():
    """few-shot 可以出现建议标签,但必须示范"规则结论"而非强制交易命令。"""
    for ex in FEW_SHOT_EXAMPLES:
        assistant = ex["assistant"]
        forbidden = ["必须买", "必须卖", "立刻买", "立刻卖",
                     "赶紧买", "赶紧卖", "保证赚钱", "一定涨"]
        assert not any(f in assistant for f in forbidden), (
            f"few-shot 示例出现强制交易或确定性预测: {assistant!r}"
        )
    assert any("规则结论" in ex["assistant"] for ex in FEW_SHOT_EXAMPLES)


def test_few_shot_examples_contain_source_and_date():
    """含数据回答的 few-shot 必须示范"带 source + as_of 的引用"格式。

    合规拒答/反例类(assistant 不含具体数字的回答)豁免 —— 那些示例
    的目的正是演示"无数据时怎么回答",而不是示范数据引用格式。
    """
    for ex in FEW_SHOT_EXAMPLES:
        assistant = ex["assistant"]
        # 反例跳过:回答里没有百分号 / NAV / 净值 这类具体数字
        is_data_free = not any(token in assistant for token in [
            "%", "净值", "回撤", "波动率",
        ])
        if is_data_free:
            continue
        assert "source" in assistant.lower() or "来源" in assistant, (
            f"含数据 few-shot 未示范引用数据来源: {assistant!r}"
        )
