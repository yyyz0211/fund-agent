from backend.services.shared.diagnosis_rules import (
    choose_decision_label,
    confidence_for,
    level_for_drawdown,
    level_for_period_return,
    level_for_volatility,
)


def test_drawdown_levels_equity():
    assert level_for_drawdown(-0.31, category="偏股混合") == "red"
    assert level_for_drawdown(-0.20, category="偏股混合") == "yellow"
    assert level_for_drawdown(-0.10, category="偏股混合") == "green"
    assert level_for_drawdown(None, category="偏股混合") == "gray"


def test_drawdown_levels_bond():
    assert level_for_drawdown(-0.11, category="债券型") == "red"
    assert level_for_drawdown(-0.06, category="债券型") == "yellow"
    assert level_for_drawdown(-0.03, category="债券型") == "green"


def test_volatility_levels_equity():
    assert level_for_volatility(0.26, category="偏股混合") == "red"
    assert level_for_volatility(0.16, category="偏股混合") == "yellow"
    assert level_for_volatility(0.08, category="偏股混合") == "green"
    assert level_for_volatility(None, category="偏股混合") == "gray"


def test_period_return_marks_large_loss_and_surge():
    assert level_for_period_return(-0.16, category="偏股混合") == "red"
    assert level_for_period_return(-0.08, category="偏股混合") == "yellow"
    assert level_for_period_return(0.55, category="偏股混合") == "red"
    assert level_for_period_return(0.30, category="偏股混合") == "yellow"
    assert level_for_period_return(0.04, category="偏股混合") == "green"
    assert level_for_period_return(None, category="偏股混合") == "gray"


def test_decision_label_gray_does_not_count():
    lights = [
        {"key": "max_drawdown", "level": "gray", "core": True},
        {"key": "volatility", "level": "yellow", "core": True},
    ]
    assert choose_decision_label(lights, missing_data=["scale"]) == "小仓试验"


def test_decision_label_many_yellow():
    lights = [
        {"key": "max_drawdown", "level": "yellow", "core": True},
        {"key": "volatility", "level": "yellow", "core": True},
    ]
    assert choose_decision_label(lights, missing_data=[]) == "观察"


def test_decision_label_red_blocks():
    lights = [
        {"key": "max_drawdown", "level": "red", "core": True},
        {"key": "volatility", "level": "green", "core": True},
    ]
    assert choose_decision_label(lights, missing_data=[]) == "暂不碰"


def test_confidence_levels():
    assert confidence_for(core_complete=True, profile_complete=True, peers_count=3) == "high"
    assert confidence_for(core_complete=True, profile_complete=False, peers_count=0) == "medium"
    assert confidence_for(core_complete=False, profile_complete=False, peers_count=0) == "low"
