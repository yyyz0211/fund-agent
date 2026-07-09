"""market_evidence_service tests — 重点是 silent failure 防护 + 循环 import 防护。"""
from __future__ import annotations

import ast
import logging
import threading
import time

import pytest


def test_import_graph_module_does_not_circular():
    """Regression: 之前因 backend.services.briefing_service 顶部 import
    backend.graph.model, 形成循环:
      graph.__init__ → qa_graph → model → tools → market_tools → briefing_service → model
    导致 langgraph dev 启动失败, 端口 2024 离线。
    修复: 把 build_model 的 import 延后到 compose_briefing() 函数体内。

    这个测试保证: 仅 import 行为不抛 ImportError, 即可证明循环已断开。
    """
    from backend.graph.qa_graph import graph  # noqa: F401
    from backend.graph.model import build_model  # noqa: F401
    from backend.services import briefing_service  # noqa: F401
    from backend.tools.fund_tools import ALL_TOOLS  # noqa: F401
    assert graph is not None
    assert callable(build_model)
    assert briefing_service is not None
    assert len(ALL_TOOLS) > 0


def test_briefing_service_does_not_module_import_model():
    """回归测试: briefing_service.py 的 module body 不能 import backend.graph.model,
    否则会和 graph.__init__ 的加载路径形成循环 import。
    修复后只允许在函数体内部 lazy import。
    """
    import inspect
    from backend.services import briefing_service
    src = inspect.getsource(briefing_service)
    # 抽出 module-level 代码 (函数体之外)
    tree = ast.parse(src)
    module_body_lines = set()
    for node in tree.body:
        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
            module_body_lines.update(range(node.lineno, node.end_lineno + 1))
    # 检查 module body 是否有 `from backend.graph.model import` 或类似
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module and "backend.graph.model" in node.module:
            pytest.fail(
                f"briefing_service.py 在 module 顶部 {node.lineno} 静态 import "
                f"{node.module}, 会和 backend.graph.__init__ 形成循环 import, "
                f"导致 langgraph dev 启动失败。"
            )


def test_refresh_market_evidence_async_task_logs_exceptions():
    """Regression: refresh_market_evidence_async 的后台 _task 失败时,
    不能再 silent-pass — 必须 logger.exception 记录到 stderr。
    防止 uvicorn 重启后, 排查时看不到 evidence 失败原因。

    通过静态扫描源码保证: 1) `_task` 内有 logger.exception/logger.error 调用;
    2) `_task` 内没有 `except Exception:\n        pass` 这种吞错模式。
    """
    import inspect
    from backend.services.market_intel_service import collect_market_intel  # noqa: F401
    from backend.services import market_evidence_service as mes

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
    from backend.services import market_evidence_service as mes
    assert hasattr(mes, "logger"), "缺模块级 logger"
    assert isinstance(mes.logger, logging.Logger)


def test_refresh_market_evidence_async_is_single_flight():
    """同 brief_type 二次触发必须返回 running, 不重复跑后台 task。"""
    from backend.services import market_evidence_service as mes
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
    from backend.services import market_evidence_service as mes
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
