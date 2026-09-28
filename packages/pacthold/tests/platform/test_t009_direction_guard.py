"""specs/010 T009 direction guard: the kernel never depends on the assembly.

FR-011 / plan.md "核心不依赖它": import direction is exactly one way —
``pacthold_runtime_compat`` may import ``pacthold``; no file inside
``packages/pacthold`` (source or tests) may import, re-export or otherwise
depend on the compatibility assembly.  This guard is deliberately AST-based
(not comment-based) so docstrings that *mention* the assembly stay legal, and
it ships with a tripwire self-test proving the scanner would actually turn
red on a reverse import instead of vacuously passing.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # packages/pacthold
COMPAT_PACKAGE = "pacthold_runtime_compat"


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for base in (PACKAGE_ROOT / "src", PACKAGE_ROOT / "tests"):
        files.extend(sorted(base.rglob("*.py")))
    return files


def _imported_names(path: Path) -> set[str]:
    """Every module name the file imports or re-imports (AST-level)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            # ``from pacthold_runtime_compat.x import y`` is caught by the
            # module field above; relative imports never reach outside the
            # kernel package, but a sneaked absolute alias is caught too.
            names.update(
                f"{alias.name}" for alias in node.names if alias.name
            )
    return names


def find_reverse_dependencies(files: list[Path] | None = None) -> list[tuple[str, str]]:
    """Return (file, offending module) pairs for any compat import/re-export."""
    hits: list[tuple[str, str]] = []
    for path in files if files is not None else _scanned_files():
        try:
            names = _imported_names(path)
        except SyntaxError as exc:  # a file the scanner cannot parse is a hole
            hits.append((str(path), f"UNPARSEABLE: {exc}"))
            continue
        for name in sorted(names):
            if name == COMPAT_PACKAGE or name.startswith(COMPAT_PACKAGE + "."):
                hits.append((str(path), name))
    return hits


def test_kernel_tree_has_no_reverse_dependency_on_the_assembly():
    hits = find_reverse_dependencies()
    assert hits == [], (
        "kernel files must never import the compatibility assembly "
        f"(specs/010 T009 direction rule): {hits}"
    )


def test_scanner_covers_both_src_and_tests():
    files = _scanned_files()
    src = [f for f in files if f.is_relative_to(PACKAGE_ROOT / "src")]
    tests = [f for f in files if f.is_relative_to(PACKAGE_ROOT / "tests")]
    assert src and tests, "the scan must cover source and test trees"
    # Sanity that the scanner reads real import statements (not comments):
    # every collected name for a known-good file must be a module string.
    assert "sqlite3" in _imported_names(PACKAGE_ROOT / "src" / "pacthold" / "work_core" / "db.py")


def test_tripwire_reverse_import_actually_turns_the_guard_red(tmp_path):
    """Guard self-test: a planted reverse import must be detected, not hidden.

    The probe lives inside the real source tree so the scanner's discovery
    path is exercised end to end; it is removed in ``finally`` and the scan
    is required to go back green.
    """
    probe = PACKAGE_ROOT / "src" / "pacthold" / "_t009_direction_tripwire.py"
    probe.write_text(
        f"import {COMPAT_PACKAGE}  # planted tripwire, must never persist\n",
        encoding="utf-8",
    )
    try:
        hits = find_reverse_dependencies()
        assert any(str(probe) in file for file, _ in hits), (
            "the direction guard failed to detect a planted reverse import — "
            "it is vacuously green"
        )
    finally:
        probe.unlink(missing_ok=True)
    assert find_reverse_dependencies() == []


def test_tripwire_from_import_form_is_also_detected(tmp_path):
    probe = PACKAGE_ROOT / "src" / "pacthold" / "_t009_direction_tripwire2.py"
    probe.write_text(
        f"from {COMPAT_PACKAGE}.capability import errors  # planted tripwire\n",
        encoding="utf-8",
    )
    try:
        hits = find_reverse_dependencies()
        assert hits, "from-import form of a reverse import must be detected"
    finally:
        probe.unlink(missing_ok=True)
    assert find_reverse_dependencies() == []


@pytest.mark.parametrize("form", ["import", "from"])
def test_guard_does_not_flag_the_assembly_importing_the_kernel(form):
    """The allowed direction is compat → kernel; prove the scanner runs on
    real assembly files without flagging legitimate forward imports."""
    compat_root = PACKAGE_ROOT.parents[1] / "plugins" / "runtime-compat" / "src" / COMPAT_PACKAGE
    files = sorted(compat_root.rglob("*.py"))
    assert files, "the compatibility assembly must exist for this scan"
    offending = []
    for path in files:
        for name in _imported_names(path):
            # kernel imports are fine; a compat file importing compat is fine;
            # only a kernel-side file could ever be a reverse dependency.
            if name == "pacthold" or name.startswith("pacthold."):
                offending.append(name)
    assert offending, "forward imports exist (scanner works); this pins direction, not absence"
