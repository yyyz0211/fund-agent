from backend.graph import policy


def test_policy_blocks_investment_advice_questions():
    blocked = [
        "110011 可以买入吗?",
        "现在要不要卖出这只基金?",
        "我应该继续持有还是减仓?",
        "推荐一只基金给我",
        "下个月收益大概多少?",
        "帮我申购 110011",
    ]
    for text in blocked:
        result = policy.check_question(text)
        assert result.allowed is False
        assert result.reason


def test_policy_allows_information_questions():
    allowed = [
        "110011 最新净值是多少?",
        "110011 近一个月最大回撤是多少?",
        "沪深300今天怎么样?",
        "列出我的自选基金",
    ]
    for text in allowed:
        assert policy.check_question(text).allowed is True


def test_policy_replaces_unsafe_answer():
    unsafe = "建议你买入 110011,未来收益会更高。"
    assert policy.check_answer(unsafe) == policy.REFUSAL_MESSAGE


def test_policy_keeps_safe_answer():
    safe = "110011 的最新净值来自 akshare, as_of=2026-06-30。"
    assert policy.check_answer(safe) == safe
