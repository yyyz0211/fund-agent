"""事务所有权契约:service / repository 函数体禁止 commit / rollback / close。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _method_bodies(tree: ast.AST) -> list[ast.stmt]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _has_forbidden_call(body: list[ast.stmt]) -> str | None:
    forbidden = {"commit", "rollback", "close"}
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in forbidden:
                if isinstance(func.value, ast.Name) and func.value.id in {
                    "session", "s", "db_session", "_session",
                }:
                    return f"{func.value.id}.{func.attr}()"
    return None


def test_forbidden_call_detector_scans_every_function_in_a_file() -> None:
    """例外必须精确到函数，不能因为同文件有合法事务入口而整文件跳过。"""
    tree = ast.parse(
        """
def allowed_function(session):
    session.flush()

def accidental_commit(session):
    session.commit()
"""
    )
    violations = {
        fn.name: _has_forbidden_call(fn.body)
        for fn in _method_bodies(tree)
    }
    assert violations == {
        "allowed_function": None,
        "accidental_commit": "session.commit()",
    }


@pytest.mark.parametrize(
    "service_path",
    sorted(Path("backend/services").rglob("*.py")),
    ids=lambda p: str(p),
)
def test_service_does_not_commit_or_close_session(service_path: Path) -> None:
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(service_path))
    for fn in _method_bodies(tree):
        if not fn.name.startswith("test_"):
            violation = _has_forbidden_call(fn.body)
            assert violation is None, (
                f"{service_path}:{fn.name}() calls {violation}; "
                f"service 函数体只能 flush(),不能 commit/rollback/close"
            )


def test_repository_does_not_commit_session() -> None:
    repo_path = Path("backend/db/repository.py")
    source = repo_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(repo_path))
    for fn in _method_bodies(tree):
        violation = _has_forbidden_call(fn.body)
        assert violation is None, (
            f"repository.{fn.name}() calls {violation}; repository 仅允许 flush"
        )
