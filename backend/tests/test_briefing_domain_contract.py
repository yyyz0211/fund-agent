"""Briefing domain hard-cut and dependency-direction contracts."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit
BRIEFING_ROOT = Path("backend/services/briefing")
LEGACY_NAMES = {"briefing_service", "module_briefing"}
LEGACY_PATHS = tuple(
    f"backend.services.briefing.{name}" for name in sorted(LEGACY_NAMES)
)


def _imports(path: Path) -> list[tuple[str, set[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package_parts: list[str] = []
    package_dir = path.resolve().parent
    while (package_dir / "__init__.py").is_file():
        package_parts.insert(0, package_dir.name)
        package_dir = package_dir.parent
    package = ".".join(package_parts)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parent_parts = package.split(".") if package else []
                keep = len(parent_parts) - (node.level - 1)
                if keep <= 0:
                    raise ValueError(f"relative import escapes package in {path}")
                module_parts = parent_parts[:keep]
                if module:
                    module_parts.extend(module.split("."))
                module = ".".join(module_parts)
            imports.append((module, {alias.name for alias in node.names}))
        elif isinstance(node, ast.Import):
            imports.extend((alias.name, set()) for alias in node.names)
    return imports


def _import_targets(module: str, names: set[str]) -> set[str]:
    targets = {module}
    if module:
        targets.update(f"{module}.{name}" for name in names)
    return targets


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (
            "from . import briefing_service",
            ("backend.services.briefing", {"briefing_service"}),
        ),
        (
            "from . import jobs",
            ("backend.services.briefing", {"jobs"}),
        ),
        (
            "from .jobs import start_run_async",
            ("backend.services.briefing.jobs", {"start_run_async"}),
        ),
    ],
)
def test_imports_resolves_relative_imports(
    tmp_path: Path,
    statement: str,
    expected: tuple[str, set[str]],
):
    package = tmp_path / "backend" / "services" / "briefing"
    package.mkdir(parents=True)
    for directory in (package.parents[1], package.parent, package):
        (directory / "__init__.py").write_text("", encoding="utf-8")
    path = package / "consumer.py"
    path.write_text(f"{statement}\n", encoding="utf-8")

    assert _imports(path) == [expected]
    module, names = _imports(path)[0]
    expected_target = (
        "backend.services.briefing.jobs"
        if "jobs" in statement
        else "backend.services.briefing.briefing_service"
    )
    assert expected_target in _import_targets(module, names)
    if "briefing_service" in statement:
        assert module == "backend.services.briefing" and names & LEGACY_NAMES


def test_legacy_briefing_modules_are_removed():
    assert not (BRIEFING_ROOT / "briefing_service.py").exists()
    assert not (BRIEFING_ROOT / "module_briefing.py").exists()


@pytest.mark.parametrize(
    "path",
    sorted(Path("backend").rglob("*.py")),
    ids=str,
)
def test_python_sources_do_not_reference_legacy_briefing_modules(path: Path):
    if path.name == "test_briefing_domain_contract.py":
        return
    source = path.read_text(encoding="utf-8")
    assert all(token not in source for token in LEGACY_PATHS), path
    for module, names in _imports(path):
        assert not (
            module == "backend.services.briefing" and names & LEGACY_NAMES
        ), path


@pytest.mark.parametrize(
    ("module_name", "forbidden"),
    [
        ("types.py", ("backend.services.briefing",)),
        ("collectors.py", (
            "backend.services.briefing.composer",
            "backend.services.briefing.workflow",
            "backend.services.briefing.jobs",
            "backend.api",
        )),
        ("composer.py", (
            "backend.services.briefing.workflow",
            "backend.services.briefing.jobs",
            "backend.api",
            "backend.graph",
            "backend.agent",
        )),
        ("workflow.py", ("backend.services.briefing.jobs",)),
        ("_state.py", ("backend.services.briefing",)),
    ],
)
def test_briefing_dependency_direction(module_name: str, forbidden: tuple[str, ...]):
    imports = _imports(BRIEFING_ROOT / module_name)
    imported_modules = [
        target
        for module, names in imports
        for target in _import_targets(module, names)
    ]
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in forbidden
    )


def test_package_initializer_is_not_a_facade():
    path = BRIEFING_ROOT / "__init__.py"
    imports = [
        module for module, _ in _imports(path)
        if module != "__future__"
    ]
    assert imports == []
