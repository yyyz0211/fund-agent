"""Policy 模块离线测试:覆盖合规拦截与放行问题。"""
import pytest
from backend.graph.policy import (
    check_question,
    check_answer,
    REFUSAL_MESSAGE,
)


class TestCheckQuestion:
    """Question pre-check:高风险问题应在进入 LLM 前被拦截。"""

    @pytest.mark.parametrize("text", [
        "现在应该买哪只基金",
        "帮我推荐一只基金",
        "这只基金明天涨还是跌",
        "你能告诉我明天净值吗",
        "现在该买还是卖",
        "要不要清仓",
        "帮我分析下应该加仓还是减仓",
        "现在可以申购这个基金吗",
        "帮我买100块",
        "现在进场合适吗",
        "明天基金净值预测",
        "给我推荐个高收益基金",
        "我应该买多少",
        "持有多久能赚钱",
        "赎回后多久到账，能帮我操作吗",
    ])
    def test_blocked(self, text):
        assert check_question(text) is False, f"should block: {text}"

    @pytest.mark.parametrize("text", [
        "易方达蓝筹最新净值",
        "基金 110011 近一个月最大回撤",
        "帮我查一下沪深300指数",
        "我的自选基金有哪些",
        "把 110011 加入自选",
        "删除我的自选基金 000001",
        "汇添富的这只基金是主动还是被动",
        "基金经理是谁",
        "管理费多少",
        "过去一年收益最高的基金是哪只",
        "帮我分析一下 110011",
        "更新一下市场数据",
    ])
    def test_allowed(self, text):
        assert check_question(text) is True, f"should allow: {text}"

    @pytest.mark.parametrize("text", [
        "110011能买吗",
        "110011怎么样",
        "帮我体检一下 110011",
        "这只基金适合我吗",
        "110011 有什么风险",
    ])
    def test_diagnosis_questions_allowed(self, text):
        assert check_question(text) is True, f"diagnosis question should allow: {text}"

    @pytest.mark.parametrize("text", [
        "帮我买1000块110011",
        "现在买入110011",
        "110011下个月收益多少",
        "明天涨跌预测",
        "110011 跌太多了我想止损",
        "我能不能现在加仓 110011",
    ])
    def test_operation_prediction_and_action_intent_blocked(self, text):
        assert check_question(text) is False, f"action intent should block: {text}"


class TestCheckAnswer:
    """Answer post-check:模型生成的回答若触及禁区,应被替换。"""

    @pytest.mark.parametrize("text", [
        "建议您现在买入该基金",
        "明天净值预测会涨",
        "我建议您加仓",
        "可以满仓操作",
        "收益可达 20%",
        "现在清仓是最佳选择",
        "建议持有 3 个月后卖出",
        "赶紧申购这只基金",
        "现在就是最佳买点",
    ])
    def test_blocked(self, text):
        assert check_answer(text) is False, f"answer should block: {text}"

    @pytest.mark.parametrize("text", [
        "截至 2026-06-30，易方达蓝筹净值为 1.25 元，来自 akshare",
        "该基金近一个月最大回撤为 -5.3%，仅供参考",
        "数据来源：akshare as_of 2026-06-30",
        "目前暂无该基金净值数据，请先调用 refresh_fund",
        "自选池中没有基金 000001",
        "已为您添加 110011 到自选池",
        "注意：过往业绩不代表未来表现，投资有风险",
    ])
    def test_allowed(self, text):
        assert check_answer(text) is True, f"answer should allow: {text}"


def test_refusal_message_is_nonempty():
    assert isinstance(REFUSAL_MESSAGE, str)
    assert len(REFUSAL_MESSAGE) > 0
