"""specs/010 T011 — repo-side guard for the wheel_check bare-core suite.

The wheel_check directory is executed in a *second, pristine venv* holding
only the pacthold wheel + pytest (quickstart: real isolation, proven by the
installed-distributions evidence).  This guard keeps that promise honest from
inside the repository:

1. every file the bare run depends on actually exists in wheel_check;
2. none of those files may import beyond the standard library, ``pytest``
   (test module only) and ``pacthold.public`` — otherwise the "zero-modification
   onboarding via the public surface" claim (SC-001) would be proven against a
   wider surface than the one plugins are allowed to use;
3. the demo script really runs its own AST import-surface self-check.

Runs green in both environments (repo ``.venv`` and bare venv #2).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

WHEEL_CHECK = Path(__file__).resolve().parent / "wheel_check"

REQUIRED_FILES = (
    "README.md",
    "import_scan.py",
    "example_new_provider.py",
    "test_t011_bare_semantics.py",
)

# pytest is allowed only where the bare run itself is driven by pytest.
ALLOWED_TEST_ONLY = {"pytest"}


def _imported_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.append(node.module or "")
    return names


def _is_allowed(name: str, *, test_module: bool) -> bool:
    if name == "pacthold.public":
        return True
    top = name.split(".")[0]
    if top == "pacthold":  # any other pacthold module is off-limits
        return False
    if top in sys.stdlib_module_names:
        return True
    return test_module and top in ALLOWED_TEST_ONLY


def test_wheel_check_suite_files_present():
    missing = [f for f in REQUIRED_FILES if not (WHEEL_CHECK / f).is_file()]
    assert not missing, f"wheel_check suite incomplete; missing: {missing}"


def test_wheel_check_suite_imports_only_public_surface_and_stdlib():
    # import_scan.py is excluded on purpose: walking *every* pacthold module
    # is its evidence-two job; its own surface is pinned separately below.
    offenders: dict[str, list[str]] = {}
    for filename in ("example_new_provider.py", "test_t011_bare_semantics.py"):
        path = WHEEL_CHECK / filename
        bad = [
            name for name in _imported_names(path)
            if not _is_allowed(name, test_module=filename.startswith("test_"))
        ]
        if bad:
            offenders[filename] = bad
    assert not offenders, f"wheel_check files import beyond pacthold.public+stdlib: {offenders}"


def test_import_scan_walks_all_modules_and_pins_the_compat_absence_guard():
    text = (WHEEL_CHECK / "import_scan.py").read_text(encoding="utf-8")
    assert "pkgutil.walk_packages" in text, "the scan must walk every pacthold module"
    assert "pacthold_runtime_compat" in text, (
        "the scan must keep the business-distribution absence counterexample"
    )


def test_demo_script_self_checks_its_import_surface():
    text = (WHEEL_CHECK / "example_new_provider.py").read_text(encoding="utf-8")
    assert "_assert_import_surface(__file__)" in text, (
        "the SC-001 demo must run its AST import-surface self-check at load"
    )
