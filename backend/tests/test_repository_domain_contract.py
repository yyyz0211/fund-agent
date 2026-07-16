"""Repository 领域硬切换的结构契约。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

REPOSITORY_MODULES = (
    "briefing",
    "fund",
    "jobs",
    "knowledge",
    "market",
    "watchlist",
)


def _python_sources() -> list[Path]:
    return sorted(Path("backend").rglob("*.py"))


def test_legacy_repository_module_is_removed() -> None:
    assert not Path("backend/db/repository.py").exists()


@pytest.mark.parametrize("path", _python_sources(), ids=str)
def test_python_sources_do_not_import_legacy_repository(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "backend.db.repository", path
            assert not (
                node.module == "backend.db"
                and any(alias.name == "repository" for alias in node.names)
            ), path
        elif isinstance(node, ast.Import):
            assert all(
                alias.name != "backend.db.repository" for alias in node.names
            ), path


@pytest.mark.parametrize("module_name", REPOSITORY_MODULES)
def test_domain_repository_imports(module_name: str) -> None:
    __import__(f"backend.db.repositories.{module_name}")
