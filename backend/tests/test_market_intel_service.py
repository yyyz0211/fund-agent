"""market_intel_service 集成测试。"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from backend.db.models import Briefing  # noqa: F401  注册入 Base.metadata
from backend.services.market import market_intel_service


@pytest.fixture
def in_memory_session(db_session):
    """复用当前 worker 的 PostgreSQL 事务 fixture。"""
    return db_session


def _mock_all_dc_calls():
    """Return a dict of mocks for all data_collector and market_service calls."""
    return {
        "fetch_market_breadth": MagicMock(
            return_value={"up": 100, "down": 50, "limit_up": 5, "limit_down": 1,
                          "volume": 0.0, "amount": 0.0, "total": 150, "source": "akshare",
                          "as_of": "2026-07-07"}
        ),
        "fetch_sector_snapshot": MagicMock(return_value=[]),
        "fetch_concept_sectors": MagicMock(return_value=[]),
        "fetch_industry_flows": MagicMock(return_value=[]),
        "fetch_concept_flows": MagicMock(return_value=[]),
        "fetch_theme_boards": MagicMock(return_value=[]),
        "fetch_breadth_indicators": MagicMock(return_value={}),
        "fetch_overseas_markets": MagicMock(return_value=[]),
        "fetch_announcements": MagicMock(return_value=[]),
    }


def test_market_snapshot_model_import():
    from backend.db.models import MarketSnapshot
    assert MarketSnapshot.__tablename__ == "market_snapshots"


@pytest.mark.db
def test_upsert_market_snapshot_idempotent(in_memory_session):
    from backend.db.models import MarketSnapshot
    from backend.db.repositories.market import upsert_market_snapshot

    payload = {
        "trade_date": "2026-07-07",
        "snapshot_type": "post_market",
        "indices": [{"symbol": "000001", "name": "上证指数", "close": 4094.4, "change_pct": 0.5}],
        "breadth": {"up": 669, "down": 4494, "limit_up": 34, "limit_down": 25},
        "industry_sectors": [{"name": "游戏", "change_pct": 2.39}],
        "concept_sectors": [],
        "industry_flows": [],
        "concept_flows": [],
        "themes": [],
        "breadth_indicators": {},
        "overseas": [],
        "announcements": [],
        "as_of": "2026-07-07",
    }

    row1 = upsert_market_snapshot(in_memory_session, "2026-07-07", "post_market", payload)
    in_memory_session.commit()
    row2 = upsert_market_snapshot(in_memory_session, "2026-07-07", "post_market", payload)
    assert row1.id == row2.id  # idempotent


def test_collect_market_intel_returns_all_keys():
    from backend.services.market import market_intel_service
    mocks = _mock_all_dc_calls()
    with patch.object(market_intel_service.dc, "fetch_market_breadth", mocks["fetch_market_breadth"]), \
         patch.object(market_intel_service.dc, "fetch_sector_snapshot", mocks["fetch_sector_snapshot"]), \
         patch.object(market_intel_service.dc, "fetch_industry_flows", mocks["fetch_industry_flows"]), \
         patch.object(market_intel_service.dc, "fetch_concept_sectors", mocks["fetch_concept_sectors"]), \
         patch.object(market_intel_service.dc, "fetch_concept_flows", mocks["fetch_concept_flows"]), \
         patch.object(market_intel_service.dc, "fetch_theme_boards", mocks["fetch_theme_boards"]), \
         patch.object(market_intel_service.dc, "fetch_breadth_indicators", mocks["fetch_breadth_indicators"]), \
         patch.object(market_intel_service.dc, "fetch_overseas_markets", mocks["fetch_overseas_markets"]), \
         patch.object(market_intel_service.dc, "fetch_announcements", mocks["fetch_announcements"]), \
         patch.object(market_intel_service.market_service, "get_indices",
                      return_value={"indices": [], "source": "akshare", "as_of": "2026-07-07"}):
        result = market_intel_service.collect_market_intel("2026-07-07", "post_market")
    expected_keys = {
        "trade_date", "snapshot_type", "indices", "breadth",
        "industry_sectors", "concept_sectors", "industry_flows",
        "concept_flows", "themes", "breadth_indicators",
        "overseas", "announcements", "as_of", "errors",
    }
    assert expected_keys.issubset(result.keys())


def test_collect_market_intel_partial_failure_continues():
    """单项 akshare 失败时其他字段仍返回，不抛整体异常。"""
    from backend.services.market import market_intel_service
    mocks = _mock_all_dc_calls()
    mocks["fetch_concept_sectors"] = MagicMock(side_effect=RuntimeError("network"))
    with patch.object(market_intel_service.dc, "fetch_market_breadth", mocks["fetch_market_breadth"]), \
         patch.object(market_intel_service.dc, "fetch_sector_snapshot", mocks["fetch_sector_snapshot"]), \
         patch.object(market_intel_service.dc, "fetch_industry_flows", mocks["fetch_industry_flows"]), \
         patch.object(market_intel_service.dc, "fetch_concept_sectors", mocks["fetch_concept_sectors"]), \
         patch.object(market_intel_service.dc, "fetch_concept_flows", mocks["fetch_concept_flows"]), \
         patch.object(market_intel_service.dc, "fetch_theme_boards", mocks["fetch_theme_boards"]), \
         patch.object(market_intel_service.dc, "fetch_breadth_indicators", mocks["fetch_breadth_indicators"]), \
         patch.object(market_intel_service.dc, "fetch_overseas_markets", mocks["fetch_overseas_markets"]), \
         patch.object(market_intel_service.dc, "fetch_announcements", mocks["fetch_announcements"]), \
         patch.object(market_intel_service.market_service, "get_indices",
                      return_value={"indices": [], "source": "akshare", "as_of": "2026-07-07"}):
        result = market_intel_service.collect_market_intel("2026-07-07", "post_market")
    assert "errors" in result
    assert any(e["field"] == "concept_sectors" for e in result["errors"])


def test_refresh_async_uses_target_date():
    """refresh_market_intel_async(target_date='2026-07-07') 后,任务用该日采集,
    而不是默认的今天。防止 UI 选"昨日"+刷新仍抓今天导致的"刷了看不到"bug。
    """
    from backend.services.market import market_intel_service
    import time

    captured = {}

    def fake_collect(trade_date, snapshot_type, session=None):
        captured["trade_date"] = trade_date
        return {"trade_date": trade_date, "snapshot_type": snapshot_type}

    class SyncExecutor:
        def submit(self, fn, *args, **kwargs):
            fn()
            return None

    with patch.object(market_intel_service, "_async_executor", SyncExecutor()), \
         patch.object(market_intel_service, "collect_market_intel", side_effect=fake_collect):
        result = market_intel_service.refresh_market_intel_async(trigger="manual", target_date="2026-07-07")

    assert result["target_date"] == "2026-07-07"
    # 同步 executor 已跑完,直接验证
    assert str(captured.get("trade_date")) == "2026-07-07", f"expected 2026-07-07, got {captured}"


def test_refresh_async_invalid_date_falls_back_to_today():
    """target_date 解析失败时,降级为今天(向后兼容 + 防爆)。"""
    from backend.services.market import market_intel_service

    def fake_collect(trade_date, snapshot_type, session=None):
        return {}

    class SyncExecutor:
        def submit(self, fn, *args, **kwargs):
            fn()
            return None

    with patch.object(market_intel_service, "_async_executor", SyncExecutor()), \
         patch.object(market_intel_service, "collect_market_intel", side_effect=fake_collect):
        result = market_intel_service.refresh_market_intel_async(trigger="manual", target_date="not-a-date")

    assert result["status"] == "started"
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}", result["target_date"]), result["target_date"]


def test_collect_market_intel_uses_serial_executor():
    """Regression: collect_market_intel 的 ThreadPoolExecutor 必须 max_workers=1。
    防止有人未来把它改回 6 路并发, 触发 libmini_racer worker pool race。
    """
    import ast
    import inspect
    from backend.services.market.market_intel_service import collect_market_intel
    src = inspect.getsource(collect_market_intel)
    tree = ast.parse(src)
    found_workers: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_tpe = (isinstance(func, ast.Name) and func.id == "ThreadPoolExecutor") or \
                     (isinstance(func, ast.Attribute) and func.attr == "ThreadPoolExecutor")
            if not is_tpe:
                continue
            for kw in node.keywords:
                if kw.arg == "max_workers" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, int):
                    found_workers.append(kw.value.value)
    assert found_workers, "collect_market_intel 没有 ThreadPoolExecutor(max_workers=...)"
    assert all(w == 1 for w in found_workers), (
        f"collect_market_intel ThreadPoolExecutor max_workers={found_workers}, "
        f"必须全为 1 才能防 libmini_racer race。"
    )


def test_refresh_api_rejects_historical_date():
    """API 守卫: refresh 传历史日(date < today)必须 400 拒绝。

    akshare 的涨跌家数/板块接口只返回最新交易日, 抓历史日会把今天的数据写进
    历史行, 覆盖当时的真实数据。守护: refresh_market 路由拒绝 date < today。
    """
    from fastapi.testclient import TestClient
    from backend.api.app import app
    from datetime import date, timedelta

    client = TestClient(app)
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    r = client.post(
        f"/api/market/refresh?date={yesterday}",
        headers={"X-Local-Trigger": "1"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "historical" in detail.lower() or "akshare" in detail.lower(), detail


def test_refresh_api_allows_today():
    """API 守卫: refresh 传今天/不传 必须通过(向后兼容)。"""
    from fastapi.testclient import TestClient
    from backend.api.app import app
    from datetime import date

    client = TestClient(app)
    today = date.today().isoformat()

    # 今天
    r1 = client.post(
        f"/api/market/refresh?date={today}",
        headers={"X-Local-Trigger": "1"},
    )
    assert r1.status_code == 200, f"today: {r1.status_code} {r1.text}"

    # 不传
    r2 = client.post(
        "/api/market/refresh",
        headers={"X-Local-Trigger": "1"},
    )
    assert r2.status_code == 200, f"none: {r2.status_code} {r2.text}"


def test_refresh_api_rejects_invalid_date_format():
    """API 守卫: date 解析失败 → 400 而非 500(已存在;回归保护)。"""
    from fastapi.testclient import TestClient
    from backend.api.app import app

    client = TestClient(app)
    r = client.post(
        "/api/market/refresh?date=not-a-date",
        headers={"X-Local-Trigger": "1"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
