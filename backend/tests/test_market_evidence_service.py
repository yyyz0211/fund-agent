"""market_evidence_service tests — 重点是 silent failure 防护 + 循环 import 防护。"""
from __future__ import annotations

import ast
import logging
import threading
import time

import pytest


def test_briefing_modules_import_without_graph_cycle():
    from backend.services.briefing import composer, persistence, workflow

    assert composer is not None
    assert persistence is not None
    assert workflow is not None


@pytest.mark.parametrize("module", ["composer.py", "workflow.py"])
def test_briefing_composition_modules_do_not_import_graph_model(module):
    from pathlib import Path

    path = Path("backend/services/briefing") / module
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("backend.graph")
    ]
    assert offenders == []


def test_refresh_market_evidence_async_task_logs_exceptions():
    """Regression: refresh_market_evidence_async 的后台 _task 失败时,
    不能再 silent-pass — 必须 logger.exception 记录到 stderr。
    防止 uvicorn 重启后, 排查时看不到 evidence 失败原因。

    通过静态扫描源码保证: 1) `_task` 内有 logger.exception/logger.error 调用;
    2) `_task` 内没有 `except Exception:\n        pass` 这种吞错模式。
    """
    import inspect
    from backend.services.market.market_intel_service import collect_market_intel  # noqa: F401
    from backend.services.market import market_evidence_service as mes

    src = inspect.getsource(mes.refresh_market_evidence_async)
    tree = ast.parse(src)

    logger_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"exception", "error"}:
                logger_calls.append((node.func.attr, ast.unparse(node)))

    assert logger_calls, (
        "refresh_market_evidence_async 里没有 logger.exception/error 调用, "
        "后台 task 失败会被 silent-pass。"
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if (handler.type is None or
                    (isinstance(handler.type, ast.Name) and handler.type.id == "Exception")):
                    for stmt in handler.body:
                        if isinstance(stmt, ast.Pass):
                            pytest.fail(
                                "refresh_market_evidence_async 仍有 `except: pass` 吞错模式: "
                                f"{ast.unparse(handler)}"
                            )


def test_refresh_market_evidence_async_logger_module_level():
    """module 必须有 logger, 否则 log 调用无处发出。"""
    from backend.services.market import market_evidence_service as mes
    assert hasattr(mes, "logger"), "缺模块级 logger"
    assert isinstance(mes.logger, logging.Logger)


def test_refresh_market_evidence_async_is_single_flight():
    """同 brief_type 二次触发必须返回 running, 不重复跑后台 task。"""
    from backend.services.market import market_evidence_service as mes
    from unittest.mock import patch, MagicMock

    # 模拟 akshare 慢采集: 让第一次 task 仍在跑
    fake_dc = MagicMock()
    fake_dc.fetch_sector_snapshot = MagicMock(return_value=[])
    sleep_done = threading.Event()

    def slow_collect(*args, **kwargs):
        sleep_done.wait(timeout=1.0)
        return {}

    with patch.object(mes, "collect_and_run_for_brief_type", side_effect=slow_collect), \
         patch.dict("sys.modules", {"backend.services.data_collector": fake_dc}):
        r1 = mes.refresh_market_evidence_async(brief_type="pre_market_test_sf", trigger="manual")
        # 第一次 task 仍卡在 slow_collect, 第二次必须拿到 running
        r2 = mes.refresh_market_evidence_async(brief_type="pre_market_test_sf", trigger="manual")
        sleep_done.set()  # 让 task 收尾
    assert r1["status"] == "started"
    assert r2["status"] == "running"
    # 等 task 跑完
    ex = mes._async_executor
    for _ in range(50):
        if not [t for t in ex._threads if t.is_alive()]:
            break
        time.sleep(0.05)


def test_refresh_market_evidence_status_records_adapter_errors():
    from backend.services.market import market_evidence_service as mes
    from unittest.mock import patch, MagicMock

    fake_dc = MagicMock()
    fake_dc.fetch_sector_snapshot = MagicMock(return_value=[])
    brief_type = "post_market_status_test"
    result = {
        "inserted": 0,
        "fetched": 0,
        "errors": [{"adapter": "财联社", "error": "ConnectError: connect failed"}],
        "categories": {},
    }

    with patch.object(mes, "collect_and_run_for_brief_type", return_value=result), \
         patch.dict("sys.modules", {"backend.services.data_collector": fake_dc}):
        started = mes.refresh_market_evidence_async(brief_type=brief_type, trigger="manual")
        assert started["status"] == "started"
        for _ in range(50):
            status = mes.get_last_refresh_status(brief_type)
            if status["status"] != "running":
                break
            time.sleep(0.05)

    status = mes.get_last_refresh_status(brief_type)
    assert status["status"] == "failed"
    assert status["result"]["errors"][0]["adapter"] == "财联社"
    assert "connect failed" in status["result"]["errors"][0]["error"]


def test_collect_injects_service_owned_fetchers_and_closes_client():
    from unittest.mock import MagicMock, patch

    import httpx

    from backend.services.knowledge import cls_telegraph_client
    from backend.services.market import data_collector
    from backend.services.market import market_evidence_service as mes

    client = MagicMock()
    factory = MagicMock(return_value=[])
    ingest = MagicMock(return_value={"inserted": 0, "fetched": 0, "errors": []})

    with patch.object(httpx, "Client", return_value=client), \
         patch.object(mes, "build_default_adapters", factory), \
         patch.object(mes.ing, "ingest_market_evidence", ingest):
        result = mes.collect_and_run_for_brief_type(
            "post_market",
            trade_date="2026-07-16",
        )

    assert result == {"inserted": 0, "fetched": 0, "errors": []}
    assert factory.call_args.kwargs["fetch_cls_roll_list"] is (
        cls_telegraph_client.fetch_roll_list
    )
    assert factory.call_args.kwargs["fetch_announcements"] is (
        data_collector.fetch_announcements
    )
    client.close.assert_called_once_with()
