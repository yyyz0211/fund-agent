"""Scheduler hard-cut structure and dependency contracts."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

ROOT = Path("backend")
LEGACY_MODULES = {
    "backend.scheduler.scheduler",
    "backend.scheduler.jobs",
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
            if node.module == "backend.scheduler":
                modules.extend(
                    f"{node.module}.{alias.name}" for alias in node.names
                )
    return modules


def test_legacy_scheduler_modules_are_deleted() -> None:
    assert not Path("backend/scheduler/scheduler.py").exists()
    assert not Path("backend/scheduler/jobs.py").exists()


@pytest.mark.parametrize("path", sorted(ROOT.rglob("*.py")), ids=str)
def test_python_sources_do_not_import_legacy_scheduler_modules(
    path: Path,
) -> None:
    assert LEGACY_MODULES.isdisjoint(_imports(path)), path


def test_runtime_does_not_import_domain_or_graph_modules() -> None:
    imports = _imports(Path("backend/scheduler/runtime.py"))
    assert not any(
        module.startswith(("backend.services", "backend.graph"))
        for module in imports
    )


def test_specs_are_framework_and_application_independent() -> None:
    imports = _imports(Path("backend/scheduler/specs.py"))
    assert not any(
        module.startswith(
            (
                "apscheduler",
                "backend.config",
                "backend.services",
                "backend.graph",
            )
        )
        for module in imports
    )


def test_scheduler_package_exports_only_lifecycle_api() -> None:
    import backend.scheduler as scheduler

    assert scheduler.__all__ == [
        "start_scheduler",
        "get_scheduler",
        "shutdown_scheduler",
    ]
