"""N4-R1 (spec 021) core-inventory guard: the kernel knows nothing above it.

`specs/021-nightly-product-closeout/core-boundaries-small-refactor.md` §判断
states the rule this file mechanises: *Server 必须消费 Pacthold 治理能力，
Pacthold 不得认识 HTTP/WS、Ordessa 产品或插件* — and §验收 asks for a
counterexample that turns red on a reverse dependency while the **legal**
Server → Pacthold direction stays green.

The sibling `test_t009_direction_guard.py` guards the kernel against the
compatibility assembly (`pacthold_runtime_compat`) only; this guard covers the
wider surface the inventory found: `apps/server` (`ordessa_server*`),
`apps/server`'s product composition (`ordessa_server_product`), the harness
plugin (`ordessa_harness`) and every domain plugin package
(`ordessa_profile`, `ordessa_model_provider`, …).

It is AST-based, not comment-based, so a docstring that *names* the Server
(`packages/pacthold/src/pacthold/execution/__init__.py:9` does) stays legal
while a real `import ordessa_server` turns the suite red. The tripwire
self-tests prove the scanner has that discriminating power instead of passing
vacuously.
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # packages/backend/pacthold
REPO_ROOT = PACKAGE_ROOT.parents[2]  # repository root

# Every top-level module name that belongs to something ABOVE the kernel. The
# rule is the prefix form: any `ordessa_*` distribution is a product/app/plugin
# package, and `plugins` is the source directory itself. Nothing in the kernel
# may reach any of them in either import form.
#
# The one deliberate exception (spec 026/002): `ordessa_environment_api` is
# the FROZEN CONTRACT package that sits BELOW the kernel — stdlib-only, zero
# product dependencies, gated by its own zero-host-import suite. The kernel
# consuming it is the intended direction (one wire vocabulary, no second copy
# of the DTOs); every other `ordessa_*` prefix stays forbidden.
FORBIDDEN_PREFIXES = ("ordessa_", "plugins")
ALLOWED_MODULES = frozenset({"ordessa_environment_api"})


def _scanned_files() -> list[Path]:
    """Every kernel source and kernel test file (source and tests are both
    scoped: a kernel test may not need the product tree either)."""
    files: list[Path] = []
    for base in (PACKAGE_ROOT / "src", PACKAGE_ROOT / "tests"):
        files.extend(sorted(base.rglob("*.py")))
    return [path for path in files if "egg-info" not in path.parts]


def _imported_modules(path: Path) -> set[str]:
    """Dotted module names this file imports at AST level.

    Relative imports (``from . import x``) are excluded on purpose: a relative
    import inside `pacthold/**` cannot leave the kernel package, so treating it
    as a violation would only add noise. Absolute imports and their module
    field are what cross a layer.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def find_product_imports(files: list[Path] | None = None) -> list[tuple[str, str]]:
    """Return (file, offending module) for any import of an above-the-kernel package."""
    hits: list[tuple[str, str]] = []
    for path in files if files is not None else _scanned_files():
        try:
            modules = _imported_modules(path)
        except SyntaxError as exc:  # a file the scanner cannot parse is a hole
            hits.append((str(path), f"UNPARSEABLE: {exc}"))
            continue
        for module in sorted(modules):
            top = module.split(".", 1)[0]
            if top.startswith(FORBIDDEN_PREFIXES) and top not in ALLOWED_MODULES:
                hits.append((str(path), module))
    return hits


def test_kernel_tree_has_no_import_of_server_harness_or_product() -> None:
    hits = find_product_imports()
    assert hits == [], (
        "the governance kernel must not import the app, the product composition "
        f"or any plugin (core-boundaries-small-refactor.md §判断): {hits}"
    )


def test_scanner_covers_src_and_tests_and_reads_real_imports() -> None:
    """Presence discipline: an empty or shrunken scan would make the guard above
    pass without proving anything."""
    files = _scanned_files()
    src = [path for path in files if path.is_relative_to(PACKAGE_ROOT / "src")]
    tests = [path for path in files if path.is_relative_to(PACKAGE_ROOT / "tests")]
    assert src and tests, "the scan must cover both the kernel source and its tests"
    assert len(src) >= 40, f"unexpectedly small kernel module walk: {len(src)}"
    # Sanity that the scanner reads real import statements, not comments.
    known = PACKAGE_ROOT / "src" / "pacthold" / "storage" / "object_store.py"
    if not known.exists():  # keep the probe honest if the file is ever renamed
        known = next(path for path in src if path.name != "__init__.py")
    modules = _imported_modules(known)
    assert modules, f"{known} has no import statements — the scanner regex drifted"
    assert all("ordessa" not in module for module in modules), modules


def test_tripwire_planted_server_import_turns_the_guard_red() -> None:
    """Counterexample self-test: a kernel module importing the Server must be
    detected, and the scan must go back green once the probe is removed."""
    probe = PACKAGE_ROOT / "src" / "pacthold" / "_n4r1_direction_tripwire.py"
    probe.write_text(
        "import ordessa_server  # planted tripwire, must never persist\n",
        encoding="utf-8",
    )
    try:
        hits = find_product_imports()
        assert any(str(probe) in file for file, _ in hits), (
            "the N4-R1 kernel direction guard did not detect a planted "
            "`import ordessa_server` — it is vacuously green"
        )
    finally:
        probe.unlink(missing_ok=True)
    assert find_product_imports() == []


def test_tripwire_from_import_form_is_detected_too() -> None:
    probe = PACKAGE_ROOT / "tests" / "platform" / "_n4r1_direction_tripwire2.py"
    probe.write_text(
        "from ordessa_harness.launch import ClaudeLaunchAdapter  # planted tripwire\n",
        encoding="utf-8",
    )
    try:
        hits = find_product_imports()
        assert hits, "the from-import form of a reverse import must be detected"
        assert any(module == "ordessa_harness.launch" for _, module in hits), hits
    finally:
        probe.unlink(missing_ok=True)
    assert find_product_imports() == []


def test_tripwire_on_a_real_kernel_file_would_be_reported() -> None:
    """Same detection, proven on a temporary copy so no repo file is touched:
    a product import appended to a genuine kernel module must surface."""
    real = PACKAGE_ROOT / "src" / "pacthold" / "work_core" / "db.py"
    if not real.exists():
        real = next(
            path for path in _scanned_files()
            if path.is_relative_to(PACKAGE_ROOT / "src") and path.suffix == ".py"
        )
    assert find_product_imports([real]) == []
    poisoned = real.read_text(encoding="utf-8") + "\nfrom ordessa_model_provider import x\n"
    staged = PACKAGE_ROOT / "tests" / "platform" / "_n4r1_direction_staged.py"
    staged.write_text(poisoned, encoding="utf-8")
    try:
        hits = find_product_imports([staged])
        assert hits and hits[0][1] == "ordessa_model_provider", hits
    finally:
        staged.unlink(missing_ok=True)


def test_allowed_direction_is_actually_present_server_and_harness_import_pacthold() -> None:
    """Positive half: `Server → Pacthold` is normal use, not an ownership
    breach, and the guard above must not be green because both sides are
    unimportable. This pins the direction instead of pinning absence."""
    consumers = {
        "apps/server": REPO_ROOT / "apps" / "server" / "src",
        "plugins/harness": REPO_ROOT / "plugins" / "harness" / "src",
    }
    for label, root in consumers.items():
        files = sorted(root.rglob("*.py"))
        assert files, f"{label} must exist for this direction check to mean anything"
        kernel_imports = {
            module
            for path in files
            if "egg-info" not in path.parts
            for module in _imported_modules(path)
            if module.split(".", 1)[0] == "pacthold"
        }
        assert kernel_imports, (
            f"{label} does not import pacthold at all — the direction pin would "
            "be vacuous, and the guard above could not be discriminating"
        )