"""Phase 1.1 验收: service 不得反向导入 `backend.graph.*`。

按重构设计规格书 4.1 步骤 1,这一组测试是循环依赖回归保护:

- service 层（`backend.services.*`）只能向下依赖 repository / integrations,
  不得跨层导入 graph / agent 的实现细节。
- `backend.graph.*` 和 `backend.agent.*` 才是模型与图的实现位置;
  graph/agent 反过来依赖 service 是允许的（顶层 composition root 会做注入）。
- 如果未来需要 service 复用 graph 的能力,只能:
  1) 通过 `compose_*` 函数的显式参数注入(已经为 model 留好了接口);
  2) 把共用的纯函数/类型挪到 `backend.services.briefing.types` 这类稳定端口。

历史背景: 之前 `briefing_service.compose_briefing()` 在内部
`from backend.graph import model as _model_module` 形成反向依赖;
测试这条规则确保 Phase 1 完成度不退化。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


# 反向导入白名单（service 因为合理原因确实需要 graph 内部符号时,在此登记）。
# 当前为空 — Phase 1.1 完成时,briefing_service / module_briefing 都已不再
# 直接 import backend.graph。
_ALLOWED_OFFENDERS: dict[str, str] = {
    # 例: "backend/services/foo/foo_service.py:13: from backend.graph.x import Y — see ADR-xxx"
}


def _disallowed_imports_in(path: Path) -> list[tuple[int, str]]:
    """在给定 .py 中找出所有 `from backend.graph` / `from backend.agent` 顶层 import。

    用 AST 而不是正则,可以容忍字符串字面量、注释、docstring 里的字样。
    """
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # 只看顶层模块:`backend.graph` 或 `backend.agent`,
            # 子模块如 `backend.graph.prompts` 也算在内。
            if module == "backend.graph" or module.startswith("backend.graph."):
                line = node.lineno
                offending = ast.unparse(node) if hasattr(ast, "unparse") else f"from {module} import ..."
                offenders.append((line, offending))
            if module == "backend.agent" or module.startswith("backend.agent."):
                line = node.lineno
                offending = ast.unparse(node) if hasattr(ast, "unparse") else f"from {module} import ..."
                offenders.append((line, offending))
    return offenders


def test_service_layer_does_not_import_graph_or_agent():
    """所有 service 模块不得 `from backend.graph` 或 `from backend.agent`。

    扫描根目录: `backend/services/`。
    """
    repo_root = Path(__file__).resolve().parents[2]
    services_root = repo_root / "backend" / "services"
    offenders: list[tuple[Path, int, str]] = []
    for path in services_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for line, stmt in _disallowed_imports_in(path):
            key = f"{path}:{line}:{stmt}"
            if key in _ALLOWED_OFFENDERS:
                continue
            offenders.append((path, line, stmt))

    assert offenders == [], (
        "Service layer must not import backend.graph or backend.agent.\n"
        "Found reverse imports:\n"
        + "\n".join(f"  {p.relative_to(repo_root)}:{l}: {s}" for p, l, s in offenders)
        + "\n\nFix: inject the capability via parameter (e.g. `model=...` on "
        "compose_briefing) and build it in the composition root (API / scheduler / CLI)."
    )


def test_run_daily_briefing_accepts_model_kwarg():
    """`run_daily_briefing` 必须接受 `model` 参数以便上层注入。"""
    import inspect

    from backend.services.briefing import briefing_service

    sig = inspect.signature(briefing_service.run_daily_briefing)
    assert "model" in sig.parameters, (
        "run_daily_briefing() must accept a `model` parameter so the "
        "composition root can inject the chat model explicitly."
    )


def test_compose_briefing_accepts_model_kwarg():
    """`compose_briefing` 必须接受 `model` 参数。"""
    import inspect

    from backend.services.briefing import briefing_service

    sig = inspect.signature(briefing_service.compose_briefing)
    assert "model" in sig.parameters


def test_compose_briefing_v2_accepts_model_kwarg():
    """`compose_briefing_v2` 必须接受 `model` 参数。"""
    import inspect

    from backend.services.briefing import module_briefing

    sig = inspect.signature(module_briefing.compose_briefing_v2)
    assert "model" in sig.parameters


def test_chat_model_protocol_is_importable():
    """`ChatModel` Protocol 必须可从 `backend.services.briefing.types` 导入。"""
    from backend.services.briefing.types import ChatModel

    # Protocol 类的 __call__ 不存在,但它有 invoke 抽象定义。
    assert hasattr(ChatModel, "invoke")