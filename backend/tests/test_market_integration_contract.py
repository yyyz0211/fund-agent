"""Market evidence integrations hard-cut contracts."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

PROVIDER_MODULES = ("cls", "cninfo", "fred", "policy", "sector")


def _python_sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_legacy_market_sources_package_is_removed() -> None:
    assert not Path("backend/services/market_sources").exists()


@pytest.mark.parametrize("path", _python_sources(Path("backend")), ids=str)
def test_python_sources_do_not_import_legacy_market_sources(path: Path) -> None:
    assert all(
        not module.startswith("backend.services.market_sources")
        for module in _imported_modules(path)
    ), path


@pytest.mark.parametrize(
    "path",
    _python_sources(Path("backend/integrations")),
    ids=str,
)
def test_integrations_do_not_import_services(path: Path) -> None:
    assert all(
        not module.startswith("backend.services")
        for module in _imported_modules(path)
    ), path


@pytest.mark.parametrize("provider", PROVIDER_MODULES)
def test_provider_package_imports(provider: str) -> None:
    __import__(f"backend.integrations.{provider}")


def test_market_evidence_factory_imports() -> None:
    __import__("backend.integrations.market_evidence")
