import math
import pytest
from backend.services.shared import metric_service as m


def test_cumulative_return():
    assert m.cumulative_return([1.0, 1.1, 1.21]) == pytest.approx(0.21)
    assert m.cumulative_return([2.0]) is None


def test_daily_returns():
    r = m.daily_returns([1.0, 1.1, 1.21])
    assert r == pytest.approx([0.1, 0.1])


def test_max_drawdown():
    # peak 1.2 then trough 0.9 => -0.25
    assert m.max_drawdown([1.0, 1.2, 0.9, 1.0]) == pytest.approx(-0.25)
    assert m.max_drawdown([1.0, 1.1, 1.2]) == pytest.approx(0.0)
    assert m.max_drawdown([1.0]) is None


def test_volatility():
    navs = [1.0, 1.1, 1.21, 1.331]  # constant 10% daily return -> 0 stdev
    assert m.volatility(navs) == pytest.approx(0.0, abs=1e-9)
    assert m.volatility([1.0, 1.1]) is None  # <3 navs -> <2 returns


def test_volatility_known_value():
    navs = [1.0, 1.1, 0.99]
    dr = m.daily_returns(navs)
    mean = sum(dr) / len(dr)
    expected_std = (sum((x - mean) ** 2 for x in dr) / (len(dr) - 1)) ** 0.5
    assert m.volatility(navs, annualize=False) == pytest.approx(expected_std)
    assert m.volatility(navs) == pytest.approx(expected_std * math.sqrt(252))


def test_period_return():
    navs = [1.0 + i * 0.01 for i in range(0, 30)]  # 30 ascending points
    assert m.period_return(navs, "1w") == pytest.approx(navs[-1] / navs[-6] - 1)
    assert m.period_return(navs, "all") == pytest.approx(navs[-1] / navs[0] - 1)
    assert m.period_return(navs, "1y") is None  # needs 252+1
    from backend.exceptions import InputValidationError

    with pytest.raises(InputValidationError) as exc_info:
        m.period_return(navs, "2y")
    assert exc_info.value.field == "period"
