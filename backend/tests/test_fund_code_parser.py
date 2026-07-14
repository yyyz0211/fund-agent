"""Fund code parser tests."""
import pytest

from backend.services.fund.fund_code_parser import (
    extract_fund_codes,
    extract_primary_fund_code,
)


@pytest.mark.parametrize(("text", "expected"), [
    ("110011", ["110011"]),
    ("帮我看看 110011 怎么样", ["110011"]),
    ("比较 110011 和 000001", ["110011", "000001"]),
    ("没有代码", []),
    ("abc110011xyz", ["110011"]),
    ("110011 再看 110011", ["110011"]),
])
def test_extract_fund_codes(text, expected):
    assert extract_fund_codes(text) == expected


def test_extract_primary_fund_code_returns_first():
    assert extract_primary_fund_code("比较 110011 和 000001") == "110011"


def test_extract_primary_fund_code_returns_none_when_missing():
    assert extract_primary_fund_code("这只基金怎么样") is None
