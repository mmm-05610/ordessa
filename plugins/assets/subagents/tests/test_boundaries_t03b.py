"""T03b — import-boundary guards for `plugins/assets/subagents`.

Requirement rows: `specs/011-q3-subagents/tasks.md` **T03b**, `AGENTS.md` rule 3
(import boundaries are load-bearing) and rule 4 (no binaries in git), and
`specs/011-q3-subagents/integration-request.md` I-1 as **superseded by SR-13**
("runtime dependencies: stdlib only" could not survive the `harness-api`
checkpoint: emitting real intents means importing the published contract
packages — see `specs/011-q3-subagents/api-requests.md` §SR-13).

Evidence level: L1 — static AST analysis plus real import isolation. Nothing
here needs the harness runtime, the server or a model.

Six locks:

1. No module under this package imports a forbidden host / product / compat
   prefix (AST scan, exact list below) — `ordessa_harness` *internals* stay on
   that list while the published `ordessa_harness_api` does not.
2. Every runtime import is stdlib, this package, or a **published contract
   package from the explicit allow-list** (the replacement for the old
   "stdlib only" machine check). The allow-list is deliberately narrow and each
   entry must be really imported, so it cannot quietly grow into "any third-party
   module": no host private, no sibling-plugin private, and no sibling plugin's
   implementation package. **Two scopes, one scanner** (§SR-13b row 4 / §SR-15):
   `src/**` is held to the contract packages and nothing else, while `tests/**`
   additionally names the sibling implementation packages it uses as real test
   doubles — with the reason written next to the entry, the public-top-level
   depth rule still applied, the dead-entry rule still applied, and the
   production scope still red on the same import.
3. The reverse direction: importing all of `pacthold` never reaches this
   package (`sys.meta_path` blocker, the technique of
   `apps/server/tests/test_dependency_direction.py:128`).
4. Nothing in `products/`, `apps/server/src/`, `packages/` or
   `plugins/server-compat/` references this package yet — composition is C0's
   exclusive job (I-1), so any hit is Q3 wiring itself in.
5. The package directory carries no binary or build artifact (AGENTS.md rule 4).
6. Suite integrity: no `xfail` and no unconditional `pytest.skip` in any test
   file of this package (verification.md G23: "skip/xfail 藏新红" is a FAIL).

Precedent for the allow-list shape (a plugin declaring only published contracts
as runtime deps): `plugins/assets/sandbox/adapters/tests/test_purity_no_fake_apply.py:37`
and `plugins/assets/sandbox/adapters/pyproject.toml`.

Every guard ships with a capability probe: the same predicate is run over a
synthetic defective input and must report it, so a green guard is never a
blind one.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import os
import pkgutil
import re
import stat
import sys
from pathlib import Path
from typing import Mapping

import pytest

real_open = builtins.open

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TESTS_DIR.parent
SRC_DIR = PACKAGE_DIR / "src"
PKG_DIR = SRC_DIR / "ordessa_assets_subagents"
REPO_ROOT = PACKAGE_DIR.parents[2]
PACKAGE_NAME = "ordessa_assets_subagents"

if str(SRC_DIR) not in sys.path:  # this file owns no conftest.py
    sys.path.insert(0, str(SRC_DIR))

#: The host / compat / product prefixes this domain may never import
#: (AGENTS.md rule 3; contracts.md §C1 keeps the definition service free of
#: wire, harness and product knowledge). Explicit, so a reviewer can diff it
#: against `apps/server/tests/test_server_compat_boundary.py:140`.
FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "ordessa_server_compat",
    "ordessa_harness",
    "ordessa_server_product",
    "ordessa_server.bootstrap",
    "ordessa_server.plugin_host",
    "ordessa_server.execution",
    "ordessa_server.profiles",
    "ordessa_server.assets",
    "packages",
    "products",
)

#: The published contract packages this plugin may import at runtime (SR-13).
#: Each value is the import root; the pyproject guard below requires the
#: matching distribution to be declared, and the dead-entry guard requires the
#: root to be *really imported* — so the list stays exactly as wide as the code.
PUBLISHED_CONTRACT_PACKAGES: dict[str, str] = {
    #: C0's `harness-api` checkpoint: the intent vocabulary this facet emits.
    "ordessa_harness_api": "ordessa-harness-api",
    #: Q5's `permissions-api` checkpoint: the ceiling adjudication DTOs.
    "ordessa_permissions_api": "ordessa-permissions-api",
    #: Foundation's server plugin API: the descriptor `plugin.py`/`wire.py`
    #: register through (SR-7). Same allowance Q5's sandbox carries.
    "server_plugin_api": "ordessa-server-plugin-api",
}

#: Sibling-plugin *implementation* packages tolerated at their public top level
#: in **production** code (`src/**`): **empty, and it stays empty** —
#: `ordessa_permissions_backend` is Q5's provider package, so importing it from
#: `src/**` is the plugin→plugin private edge AGENTS.md rule 3 forbids
#: (`api-requests.md` §SR-13b row 4). The seam now takes the port name and the
#: conflict types as host-injected wiring inputs (§SR-15 option 3), which is
#: what let this entry be emptied; the entry exists as a documented escape hatch
#: only (a root here must be *really imported*, and never read below its top
#: level), so a future tolerance has to name its reason instead of quietly
#: widening a forbidden-list comment.
PUBLISHED_PLUGIN_PACKAGES: dict[str, str] = {}

#: The sibling *implementation* packages the **test scope** may import, at their
#: public top level only. ONE named reason, test doubles only:
#: `tests/test_permissions_seam_t04.py` adjudicates against Q5's real
#: `Authorizer` / `ApprovalFacts` (and its two conflict classes), because the
#: only faithful double of an authority is that authority — a hand-rolled
#: stand-in would test this package's guess of Q5's semantics, not the real
#: ruling. This is a TEST allowance and nothing else: `src/**` importing any
#: root on this list is red, and so is an entry nothing imports. Delete this
#: entry (and the dev-extra line in `pyproject.toml`) when §SR-15 re-exports
#: `AUTHORIZER_PORT` / `CorrelationConflict` / `VersionConflict` from
#: `ordessa_permissions_api`.
TEST_ONLY_SIBLING_PACKAGES: dict[str, str] = {
    "ordessa_permissions_backend": "ordessa-permissions-backend",
}

#: Another plugin's own namespace that a *test* of this package binds directly,
#: with the owner named so the test-scope scan below is not silently blinded to
#: it: `tests/test_profile_facet_t10.py` consumes the real Profile v2 surface
#: (T10 lane) instead of a local look-alike. Same rule as above — test scope
#: only, `src/**` stays red on it, and an unused entry is red here. One
#: deliberate difference from the sibling-package entry: that one is additionally
#: **depth**-restricted (public top level only), while this test binds a
#: declared sub-module surface of the Profile plugin (`ordessa_profile.plugin`),
#: which is that lane's own contract consumption — registered here in words
#: rather than tolerated silently, and reported to the T10 owner.
TEST_ONLY_FOREIGN_PACKAGES: dict[str, str] = {
    "ordessa_profile": "ordessa-profile (T10 facet test binds the real core, "
                       "including its declared .plugin surface)",
}

#: Test-scope roots that are neither this package nor a sibling plugin: the
#: runner, the suite's shared fixtures, and the suite's own modules importing
#: each other.
TEST_HARNESS_TOP_LEVEL: frozenset[str] = frozenset({"pytest", "conftest"})

#: I-1 as amended by SR-13, **production scope**: stdlib + this package + the
#: published contracts. Nothing else — no sibling implementation package.
PRODUCTION_ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    {PACKAGE_NAME}
    | set(PUBLISHED_CONTRACT_PACKAGES)
    | set(PUBLISHED_PLUGIN_PACKAGES)
)
#: The same list widened by the two named test-scope allowances above. Built
#: from the dicts, never a copy, so a deleted entry deletes its licence.
TEST_ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    PRODUCTION_ALLOWED_TOP_LEVEL
    | set(TEST_ONLY_SIBLING_PACKAGES)
    | set(TEST_ONLY_FOREIGN_PACKAGES)
    | TEST_HARNESS_TOP_LEVEL
)
#: Back-compat name for the predicates below that keep a single default scope:
#: the production one, which is the promise being guarded.
ALLOWED_NON_STDLIB_TOP_LEVEL: frozenset[str] = PRODUCTION_ALLOWED_TOP_LEVEL

#: Roots that may never appear at all, allow-list or not (the load-bearing
#: half of the old promise, kept in full). `ordessa_permissions_backend` is on
#: this list: the test scope's licence for it is carried by the entry below, not
#: by removing it here.
ALWAYS_FORBIDDEN_TOP_LEVEL: frozenset[str] = frozenset({
    "ordessa_harness",          # the harness package itself, not its api
    "ordessa_server", "ordessa_server_compat", "ordessa_server_product",
    "pacthold", "ordessa_workspace", "ordessa_profile",
    "ordessa_profile_api", "ordessa_chat_api", "ordessa_sandbox_api",
    "ordessa_sandbox_backend", "ordessa_permissions", "ordessa_permissions_adapters",
    "ordessa_permissions_backend", "ordessa_harness_api_contrib",
    "sqlite3", "fastapi", "pydantic", "httpx", "uvicorn",
})
#: A stdlib root the **test scope** is allowed to name even though it sits on
#: the never-allowed list, with its one reason: the seam suite stands the real
#: authority up over a real injected sqlite database
#: (`test_permissions_seam_t04.py::TempDatabase`) — the storage seam is the
#: product's own, so the double is not a stub. `src/**` may not name it: this
#: domain's store is file-backed (CAS rows + receipts), and a direct sqlite
#: reach there would be a second, unmanaged persistence path. The per-scope
#: dead-entry rule keeps the exemption honest — if the tests stop importing it,
#: the entry goes red.
TEST_ONLY_STDLIB_EXEMPTIONS: dict[str, str] = {
    "sqlite3": "tests stand the real authority up over a real injected database",
}

#: What each scope may not import even with its own allowance. For tests the two
#: named allowances above are subtracted — *only* those, and the dead-entry rule
#: in `IMPORT_SCOPES` keeps each of them earning its place every run.
PRODUCTION_FORBIDDEN_TOP_LEVEL: frozenset[str] = ALWAYS_FORBIDDEN_TOP_LEVEL
TEST_FORBIDDEN_TOP_LEVEL: frozenset[str] = (
    ALWAYS_FORBIDDEN_TOP_LEVEL
    - set(TEST_ONLY_SIBLING_PACKAGES)
    - set(TEST_ONLY_FOREIGN_PACKAGES)
    - set(TEST_ONLY_STDLIB_EXEMPTIONS)
)

#: The two import scopes, one entry each, scanned by the same predicates.
#: `allowed`/`forbidden`/`sibling_roots` differ; every other clause is shared,
#: and the `dead`-entry rule is applied per scope so an allowance that stops
#: being used goes red in the scope that granted it.
_TEST_MODULE_ROOTS: frozenset[str] = frozenset(
    path.stem for path in TESTS_DIR.glob("*.py")
)
#: Local test modules importing each other (`from test_ceiling_t04 import …`)
#: are the suite talking to itself, not a foreign root.
IMPORT_SCOPES: tuple[dict[str, object], ...] = (
    {
        "name": "src",
        "root": PKG_DIR,
        "allowed": PRODUCTION_ALLOWED_TOP_LEVEL,
        "forbidden": PRODUCTION_FORBIDDEN_TOP_LEVEL,
        "sibling_roots": frozenset(PUBLISHED_PLUGIN_PACKAGES),
        "local_roots": frozenset(),
        "tolerances": frozenset(),
        "declared_from": "dependencies",
    },
    {
        "name": "tests",
        "root": TESTS_DIR,
        "allowed": TEST_ALLOWED_TOP_LEVEL,
        "forbidden": TEST_FORBIDDEN_TOP_LEVEL,
        "sibling_roots": frozenset(TEST_ONLY_SIBLING_PACKAGES)
                          | TEST_HARNESS_TOP_LEVEL,
        # `TEST_ONLY_FOREIGN_PACKAGES` is deliberately NOT here: its depth
        # exception is named in that dict's comment, not hidden in this one.
        "local_roots": _TEST_MODULE_ROOTS,
        "tolerances": frozenset(TEST_ONLY_STDLIB_EXEMPTIONS),
        "declared_from": "optional-dependencies.dev",
    },
)

#: Roots that may not name this package until C0 composes it (I-1).
COMPOSITION_ROOTS: tuple[str, ...] = (
    "products",
    os.path.join("apps", "server", "src"),
    "packages",
    os.path.join("plugins", "server-compat"),
)
PACKAGE_IDENTIFIERS: tuple[str, ...] = (
    "ordessa_assets_subagents",
    "ordessa-assets-subagents",
    "assets/subagents",
)
SCANNED_SUFFIXES: frozenset[str] = frozenset({".py", ".toml", ".json"})

#: Interpreter bytecode caches are a byproduct of running this very suite, not
#: a shipped artifact: they are excluded from the artifact walk, and the walk
#: still refuses an artifact of the same kind anywhere else.
BYPRODUCT_DIRS: frozenset[str] = frozenset({"__pycache__"})

FORBIDDEN_ARTIFACT_NAMES: frozenset[str] = frozenset({
    "node_modules", "target", "dist", "build", ".venv", ".eggs",
})
FORBIDDEN_ARTIFACT_SUFFIXES: frozenset[str] = frozenset({
    ".so", ".dll", ".dylib", ".pyd", ".o", ".a", ".lib", ".obj", ".exe",
    ".elf", ".bin", ".pyc", ".pyo", ".class", ".jar", ".wasm",
})
BINARY_MAGICS: tuple[bytes, ...] = (b"\x7fELF", b"MZ", b"\xfe\xca\xba\xbe",
                                    b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")

#: A string counts as an xfail *marker* only in marker position, so prose that
#: discusses this rule (including in these very test files) is not a violation.
XFAIL_MARKER_RE = re.compile(r"\A\s*(?:strict_)?xfail(?:\(|[:=])")

# -- shared scanners --------------------------------------------------------


def _source_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py")
        if not BYPRODUCT_DIRS.intersection(path.parts)
    )


def _absolute_imports(source: str) -> set[str]:
    """Every absolute dotted name an import statement can resolve to.

    Relative imports (`from . import x`, level > 0) are the package talking to
    itself and are deliberately not collected.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _forbidden_import_hits(source: str) -> list[str]:
    hits: list[str] = []
    for name in sorted(_absolute_imports(source)):
        for prefix in FORBIDDEN_IMPORT_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                hits.append(name)
                break
    return hits


def _non_stdlib_top_levels(source: str, *,
                           allowed: frozenset[str] = ALLOWED_NON_STDLIB_TOP_LEVEL,
                           local_roots: frozenset[str] = frozenset()
                           ) -> set[str]:
    """Third-party roots outside the allow-list — the SR-13 machine check.

    `allowed` is the scope's own list (see `IMPORT_SCOPES`); `local_roots` names
    roots the scope treats as itself (the test modules importing each other).
    """
    return {
        top for top in (_name.split(".")[0] for _name in _absolute_imports(source))
        if top not in sys.stdlib_module_names and top not in allowed
        and top not in local_roots
    }


def _forbidden_root_hits(source: str, *,
                         forbidden: frozenset[str] = ALWAYS_FORBIDDEN_TOP_LEVEL
                         ) -> list[str]:
    """A never-allowed root, allow-list or not (the harness package, compat,
    the product, the kernel, another plugin's own namespace)."""
    names = _absolute_imports(source)
    return sorted(
        {name for name in names if name.split(".")[0] in forbidden}
        | {name for name in names
           if name == "ordessa_harness" or name.startswith("ordessa_harness.")})


def _scope_view(scope: Mapping[str, object]) -> tuple[
        Path, frozenset[str], frozenset[str], frozenset[str], frozenset[str],
        frozenset[str]]:
    """One `IMPORT_SCOPES` entry, typed: (root, allowed, forbidden, sibling
    roots, roots the scope treats as itself, named stdlib tolerances)."""
    root, allowed = scope["root"], scope["allowed"]
    forbidden, siblings = scope["forbidden"], scope["sibling_roots"]
    local, tolerances = scope["local_roots"], scope["tolerances"]
    assert isinstance(root, Path) and isinstance(allowed, frozenset)
    assert isinstance(forbidden, frozenset) and isinstance(siblings, frozenset)
    assert isinstance(local, frozenset) and isinstance(tolerances, frozenset)
    return root, allowed, forbidden, siblings, local, tolerances


def _import_module_paths(source: str) -> set[str]:
    """Only the module paths an import loads (`from pkg import name` counts as
    `pkg`, not `pkg.name`), so depth rules read the module, not the symbol."""
    paths: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            paths.add(node.module)
    return paths


def _sibling_privacy_hits(source: str, *,
                          sibling_roots: frozenset[str] = frozenset(
                              PUBLISHED_PLUGIN_PACKAGES)) -> list[str]:
    """Depth rule for a tolerated sibling *implementation* package.

    Its public top level is the contract that plugin ships; anything below it is
    that plugin's internal layout, which this package must not depend on. The
    roots are a parameter so the rule stays testable while the allow-list is
    empty (an unprobed rule is a decorative one).
    """
    return sorted(
        f"{path} (sibling implementation package imported below its top level)"
        for path in _import_module_paths(source)
        if path.split(".")[0] in sibling_roots and "." in path)


def _private_name_hits(source: str) -> list[str]:
    """No underscore-private module or symbol crosses into this package from a
    foreign root; a package's own privates are its own business."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            candidates = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        for name in candidates:
            top = name.split(".")[0]
            if top in {PACKAGE_NAME, "__future__"}:
                continue
            if any(part.startswith("_") for part in name.split(".")):
                hits.append(name)
    return sorted(set(hits))


def _text_hits(root: Path, patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    if not root.is_dir():
        return hits
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if BYPRODUCT_DIRS.intersection(path.parts) or "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in patterns:
            if pattern in text:
                hits.append(f"{path.relative_to(REPO_ROOT)}: {pattern}")
    return hits


def _is_git_ignored(path: Path) -> bool:
    """True when the repository already keeps this path out of git."""
    import subprocess

    try:
        return subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)],
            cwd=str(REPO_ROOT), capture_output=True,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _artifact_findings(root: Path, *, ignore_gitignored: bool = True
                       ) -> tuple[list[str], list[str]]:
    """(unignoreable artifacts, gitignored byproducts) under one directory.

    AGENTS.md rule 4 is about repository *content*: a developer-run
    `npm install` / interpreter bytecode cache inside the package is an
    environment byproduct as long as git already ignores it. The two cases are
    reported apart, so a byproduct is visible without being mistaken for a
    committed artifact.
    """
    findings: list[str] = []
    ignored: list[str] = []
    pruned: list[Path] = []
    for path in sorted(root.rglob("*")):
        if BYPRODUCT_DIRS.intersection(path.parts) or any(
                str(path).startswith(str(skip) + os.sep) for skip in pruned):
            continue
        rel = str(path.relative_to(root))
        if path.is_dir():
            if path.name in FORBIDDEN_ARTIFACT_NAMES:
                if ignore_gitignored and _is_git_ignored(path):
                    ignored.append(f"{rel}: gitignored artifact directory")
                    pruned.append(path)
                    continue
                findings.append(f"{rel}: forbidden artifact directory")
            continue
        if path.suffix in FORBIDDEN_ARTIFACT_SUFFIXES:
            findings.append(f"{rel}: build artifact ({path.suffix})")
            continue
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            findings.append(f"{rel}: executable bit set (0o{mode & 0o7777:o})")
        with real_open(path, "rb") as handle:
            head = handle.read(4)
        if head in BINARY_MAGICS or head.startswith(b"\x7fELF"):
            findings.append(f"{rel}: binary magic {head!r}")
    if ignore_gitignored and findings:
        keep: list[str] = []
        for entry in findings:
            target = root / entry.split(": ", 1)[0]
            if _is_git_ignored(target):
                ignored.append(f"{entry} (gitignored byproduct)")
            else:
                keep.append(entry)
        findings = keep
    return findings, ignored


class _ImportBlocker:
    """Refuses every (transitive) import of a forbidden top-level package."""

    MARKER = "T03B_IMPORT_BOUNDARY"

    def __init__(self, forbidden: tuple[str, ...]) -> None:
        self.forbidden = forbidden
        self.hits: list[str] = []

    def _wanted(self, fullname: str) -> bool:
        return any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in self.forbidden
        )

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if self._wanted(fullname):
            self.hits.append(fullname)
            raise ImportError(
                f"{self.MARKER}: {fullname!r} is forbidden in this isolation")
        return None


class _isolation:
    """Install a blocker, evict cached modules, restore everything after."""

    def __init__(self, forbidden: tuple[str, ...], *, keep: tuple[str, ...] = ()) -> None:
        self.forbidden = forbidden
        self.keep = keep
        self.blocker: _ImportBlocker | None = None
        self._snapshot: dict[str, object] = {}

    def __enter__(self) -> _ImportBlocker:
        self.blocker = _ImportBlocker(self.forbidden)
        self._snapshot = dict(sys.modules)
        prefixes = tuple(self.forbidden) + tuple(self.keep)
        for name in list(sys.modules):
            if any(name == p or name.startswith(p + ".") for p in prefixes):
                sys.modules.pop(name, None)
        sys.meta_path.insert(0, self.blocker)
        return self.blocker

    def __exit__(self, *exc_info) -> bool:  # noqa: ANN002
        if self.blocker in sys.meta_path:
            sys.meta_path.remove(self.blocker)
        sys.modules.clear()
        sys.modules.update(self._snapshot)
        return False


# -- 1 + 2: what this package may import ------------------------------------


def test_no_module_of_the_domain_imports_a_forbidden_host_or_product_prefix():
    files = _source_files(PKG_DIR)
    assert files, f"no source found under {PKG_DIR} — the guard would be blind"
    violations = [
        f"{path.relative_to(REPO_ROOT)}: {name}"
        for path in files
        for name in _forbidden_import_hits(path.read_text(encoding="utf-8"))
    ]
    assert violations == [], (
        "AGENTS.md rule 3 / contracts.md §C1: the definition domain may not "
        "reach the compat core, the harness, the product or host privates:\n"
        + "\n".join(violations)
    )


def test_the_forbidden_prefix_scan_reports_every_listed_prefix():
    blind: list[str] = []
    for prefix in FORBIDDEN_IMPORT_PREFIXES:
        for source in (
            f"import {prefix}.thing\n",
            f"import {prefix}.thing as t\n",
            f"from {prefix}.thing import x\n",
            f"from {prefix} import thing\n",
        ):
            if not _forbidden_import_hits(source):
                blind.append(f"{prefix} <- {source.strip()}")
    assert blind == [], "the forbidden list is decorative for: " + ", ".join(blind)
    # negative control: legitimate imports must not be reported
    assert _forbidden_import_hits("import json\nfrom .dto import AgentDefinition\n") == []
    assert _forbidden_import_hits("import ordessa_server.errors\n") == [], (
        "the host's documented generic vocabulary is not forbidden")
    # the distinction the SR-13 change turns on: the *published* harness API is
    # allowed, the harness package's own modules are not
    assert _forbidden_import_hits("from ordessa_harness_api import IntentSet\n") == []
    assert _forbidden_import_hits("from ordessa_harness import registry\n"), (
        "harness internals would read as the published API")


def test_the_domain_runtime_imports_are_stdlib_its_own_or_published_contracts():
    offenders: dict[str, list[str]] = {}
    for path in _source_files(PKG_DIR):
        for top in sorted(_non_stdlib_top_levels(path.read_text(encoding="utf-8"))):
            offenders.setdefault(top, []).append(
                str(path.relative_to(REPO_ROOT)))
    assert offenders == {}, (
        "SR-13 (amending I-1): runtime imports are stdlib, this package and the "
        "published contract packages on the allow-list — nothing else. These "
        "roots are outside it and would need a policy decision plus a declared "
        f"dependency: {offenders}"
    )


def test_the_runtime_import_allow_list_is_exactly_what_the_code_uses():
    """The allow-list is only load-bearing if it stays narrow and honest.

    Four machine checks, all from the real source: (1) no never-allowed root is
    imported (harness package, compat, product, kernel, another plugin's
    namespace, a third-party runtime lib); (2) every allow-listed root is
    genuinely imported, so the list cannot keep a courtesy entry after the code
    stopped needing it — and cannot grow one before; (3) the one tolerated
    sibling implementation package is never read below its public top level;
    (4) nothing underscore-private crosses the boundary from a foreign root.
    """
    files = _source_files(PKG_DIR)
    assert files, f"no source found under {PKG_DIR} — the guard would be blind"
    imported_roots: dict[str, list[str]] = {}
    root_hits: list[str] = []
    depth_hits: list[str] = []
    private_hits: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        where = str(path.relative_to(REPO_ROOT))
        for name in _forbidden_root_hits(source):
            root_hits.append(f"{where}: {name}")
        for name in _sibling_privacy_hits(source):
            depth_hits.append(f"{where}: {name}")
        for name in _private_name_hits(source):
            private_hits.append(f"{where}: {name}")
        for name in _absolute_imports(source):
            top = name.split(".")[0]
            if (top not in sys.stdlib_module_names and top != PACKAGE_NAME):
                imported_roots.setdefault(top, []).append(where)

    assert root_hits == [], (
        "AGENTS.md rule 3 / contracts.md §C1: these imports are never allowed "
        "from this domain, published-contract allow-list or not:\n"
        + "\n".join(sorted(set(root_hits))))
    assert depth_hits == [], "\n".join(sorted(set(depth_hits)))
    assert private_hits == [], (
        "plugin-to-plugin private import:\n" + "\n".join(sorted(set(private_hits))))

    sanctioned = set(PUBLISHED_CONTRACT_PACKAGES) | set(PUBLISHED_PLUGIN_PACKAGES)
    unlisted = {root: sorted(set(where)) for root, where in imported_roots.items()
                if root not in sanctioned}
    assert not unlisted, f"imported but not on the allow-list: {unlisted}"
    dead = sorted(root for root in sanctioned if root not in imported_roots)
    assert dead == [], (
        f"the allow-list carries entries nothing imports: {dead}. Delete them (or "
        "declare the dependency honestly) instead of leaving a list wider than "
        "the code — a stale allowance is how a boundary erodes.")

    # capability: each of the four predicates does report a defect
    assert _forbidden_root_hits("import ordessa_harness.contributions\n")
    assert _forbidden_root_hits("from pacthold.storage import database\n")
    assert _forbidden_root_hits("import ordessa_profile\n")
    assert _non_stdlib_top_levels("import requests\n") == {"requests"}
    assert _non_stdlib_top_levels("from ordessa_harness_api import IntentSet\n") == set()
    # the depth rule is real even while the sibling allow-list is empty: point
    # it at the root it exists for and it reports a below-top-level import
    assert _sibling_privacy_hits(
        "from ordessa_permissions_backend.store import rows\n",
        sibling_roots=frozenset({"ordessa_permissions_backend"}))
    assert _sibling_privacy_hits(
        "from ordessa_permissions_backend import AUTHORIZER_PORT\n",
        sibling_roots=frozenset({"ordessa_permissions_backend"})) == []
    # ... and today the backend is simply forbidden, which is the stricter rule
    assert _forbidden_root_hits("from ordessa_permissions_backend import AUTHORIZER_PORT\n")
    assert _private_name_hits("from ordessa_harness_api._internals import x\n")
    assert _private_name_hits("from ordessa_harness_api import _hidden\n")
    assert _private_name_hits(
        "from __future__ import annotations\nfrom . import _local\n") == []


def test_each_import_scope_is_scanned_by_the_same_predicates():
    """The split this package's boundary ruling turns on: **one scanner, two scopes**.

    `src/**` may import exactly stdlib + this package + the three published
    contract packages, and `ordessa_permissions_backend` is *forbidden* there
    (§SR-13b row 4 — no sibling plugin's implementation package in production
    code). `tests/**` may additionally import the roots named in
    `TEST_ONLY_SIBLING_PACKAGES` / `TEST_ONLY_FOREIGN_PACKAGES`, at their public
    top level only, for the reasons written next to those entries: Q5's own
    authorizer is the only faithful double of Q5's authorizer, and rewriting the
    seam suite to a hand-rolled stand-in would test this package's guess of the
    authority instead of the authority.

    Everything else is shared and re-run per scope: the never-allowed roots, the
    depth rule, the underscore-private rule, and the dead-entry rule (an
    allowance nothing in that scope imports is red, so the test scope's
    tolerance cannot outlive its reason).
    """
    assert {scope["name"] for scope in IMPORT_SCOPES} == {"src", "tests"}
    for scope in IMPORT_SCOPES:
        root, allowed, forbidden, siblings, local, tolerances = _scope_view(scope)
        name = str(scope["name"])
        files = _source_files(root)
        assert files, f"no source found under {root} — the {name} guard is blind"
        forbidden_hits: list[str] = []
        unlisted: dict[str, list[str]] = {}
        depth_hits: list[str] = []
        private_hits: list[str] = []
        imported: set[str] = set()
        for path in files:
            source = path.read_text(encoding="utf-8")
            where = str(path.relative_to(REPO_ROOT))
            for hit in _forbidden_root_hits(source, forbidden=forbidden):
                forbidden_hits.append(f"{where}: {hit}")
            for top in sorted(_non_stdlib_top_levels(source, allowed=allowed,
                                                     local_roots=local)):
                unlisted.setdefault(top, []).append(where)
            for hit in _sibling_privacy_hits(source, sibling_roots=siblings):
                depth_hits.append(f"{where}: {hit}")
            for hit in _private_name_hits(source):
                private_hits.append(f"{where}: {hit}")
            for imp in _absolute_imports(source):
                imported.add(imp.split(".")[0])

        assert forbidden_hits == [], (
            f"{name}: a root that is never allowed, allow-list or not "
            "(AGENTS.md rule 3):\n" + "\n".join(sorted(set(forbidden_hits))))
        assert not unlisted, (
            f"{name}: imported outside that scope's allow-list "
            f"{sorted(allowed)}: {unlisted}")
        assert depth_hits == [], (
            f"{name}: a tolerated sibling package read below its public top "
            "level is that plugin's internal layout:\n"
            + "\n".join(sorted(set(depth_hits))))
        assert private_hits == [], f"{name}: private import across the boundary"

        # Dead-entry rule, per scope: every sanctioned third-party root must be
        # really imported *in this scope*, so a licence cannot outlive its use.
        sanctioned = {root_name for root_name in (allowed | tolerances)
                      if root_name != PACKAGE_NAME and root_name not in local
                      and (root_name not in sys.stdlib_module_names
                           or root_name in tolerances)}
        dead = sorted(root_name for root_name in sanctioned
                      if root_name not in imported)
        assert dead == [], (
            f"the {name} scope allows roots nothing there imports: {dead}. "
            "Delete the entry (and its declared distribution) instead of "
            "leaving a list wider than the code.")

    # capability, and the actual teeth of the split, on synthetic sources:
    backend_import = "from ordessa_permissions_backend import AUTHORIZER_PORT\n"
    src, tests = IMPORT_SCOPES
    assert _forbidden_root_hits(backend_import, forbidden=src["forbidden"]), (
        "the src scope would let a sibling implementation package back in")
    assert _non_stdlib_top_levels(backend_import, allowed=src["allowed"]) == {
        "ordessa_permissions_backend"}
    assert not _forbidden_root_hits(backend_import, forbidden=tests["forbidden"]), (
        "the test scope's named tolerance is decorative")
    assert _non_stdlib_top_levels(backend_import, allowed=tests["allowed"],
                                 local_roots=_TEST_MODULE_ROOTS) == set()
    # ... and it stops at the public top level in the test scope too
    assert _sibling_privacy_hits(
        "from ordessa_permissions_backend.facts import ApprovalFacts\n",
        sibling_roots=tests["sibling_roots"])
    assert _sibling_privacy_hits(backend_import, sibling_roots=tests["sibling_roots"]) == []
    # the always-forbidden half is not lost by the widening, in either scope
    for source in ("import pacthold.storage\n", "from ordessa_server.bootstrap import x\n"):
        assert _forbidden_root_hits(source, forbidden=src["forbidden"])
        assert _forbidden_root_hits(source, forbidden=tests["forbidden"])


def test_the_stdlib_allow_list_scan_is_capable():
    for source in (
        "import requests\n",
        "import yaml\n",
        "from pacthold.storage import database\n",
        "import numpy as np\n",
        "import ordessa_server.errors\n",
        "import ordessa_harness\n",
        "from ordessa_harness.application import configuration_service\n",
        "import ordessa_workspace\n",
        "from ordessa_profile import plugin\n",
    ):
        assert _non_stdlib_top_levels(source), f"blind for: {source.strip()}"
    assert _non_stdlib_top_levels("import hashlib\nfrom pathlib import Path\n"
                                 "from . import limits\n") == set()
    # the published contracts are the *only* third-party roots allowed, and
    # naming them is not a licence for anything else from the same producer
    assert _non_stdlib_top_levels("from ordessa_harness_api.schema import x\n") == set()
    assert _non_stdlib_top_levels("from ordessa_harness_api_contrib import x\n") == {
        "ordessa_harness_api_contrib"}


def _scope_imported_roots(root: Path, *, local: frozenset[str] = frozenset()) -> set[str]:
    """Every non-stdlib, non-local import root a scope actually uses."""
    files = _source_files(root)
    assert files, f"no source found under {root} — the guard would be blind"
    roots: set[str] = set()
    for path in files:
        for name in _absolute_imports(path.read_text(encoding="utf-8")):
            top = name.split(".")[0]
            if top not in sys.stdlib_module_names and top != PACKAGE_NAME:
                roots.add(top)
    return roots - {PACKAGE_NAME} - local


def _distribution(entry: str) -> str:
    """`ordessa-harness-api>=1.0,<2` -> `ordessa-harness-api`."""
    return re.split(r"[<>=!~;\[]", entry, maxsplit=1)[0].strip().lower() \
        .replace("_", "-")


def test_the_package_declares_exactly_the_published_contract_dependencies():
    """SR-13 / §SR-13b: the manifest must name the runtime closure of `src/**`
    and the test closure of `tests/**` **separately**.

    Two scopes, two lists, both derived from the imports rather than typed by
    hand: a dep without an import, an import without a dep, or the sibling
    implementation package slipping from `dev` into `dependencies`, is red here.
    """
    try:
        import tomllib
    except ImportError as exc:  # pragma: no cover - requires python < 3.11
        pytest.skip(f"tomllib is unavailable on this interpreter ({exc}); "
                    "the package floor is >=3.11 per its own pyproject.toml")
    pyproject = PACKAGE_DIR / "pyproject.toml"
    assert pyproject.is_file(), f"{pyproject} is missing"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    dependencies = [str(entry) for entry in project.get("dependencies", [])]

    # -- runtime scope: src/** ------------------------------------------------
    imported_roots = _scope_imported_roots(PKG_DIR)
    expected = {
        PUBLISHED_CONTRACT_PACKAGES[root]
        for root in sorted(imported_roots)
        if root in PUBLISHED_CONTRACT_PACKAGES
    } | {
        PUBLISHED_PLUGIN_PACKAGES[root]
        for root in sorted(imported_roots)
        if root in PUBLISHED_PLUGIN_PACKAGES
    }
    declared = {_distribution(entry) for entry in dependencies}
    assert declared == expected, (
        f"pyproject declares {sorted(declared)} but the code imports "
        f"{sorted(imported_roots)} → the honest set is {sorted(expected)}")
    sibling_distributions = set(TEST_ONLY_SIBLING_PACKAGES.values())
    assert not declared & sibling_distributions, (
        f"a sibling-plugin implementation package is in the runtime closure: "
        f"{sorted(declared & sibling_distributions)} (§SR-13b row 4)")
    assert project.get("name") == "ordessa-assets-subagents", project.get("name")
    # untouched by the contract change: the floors and identity stay as baselined
    assert project.get("requires-python") == ">=3.11", project.get("requires-python")
    assert project.get("version") == "2.0.0a1", project.get("version")
    assert project.get("license") == {"text": "MIT"}, project.get("license")

    # -- test scope: tests/** -------------------------------------------------
    dev_entries = [str(entry) for entry in
                   project.get("optional-dependencies", {}).get("dev", [])]
    declared_dev = {_distribution(entry) for entry in dev_entries}
    test_roots = _scope_imported_roots(TESTS_DIR, local=_TEST_MODULE_ROOTS)
    expected_dev = {
        TEST_ONLY_SIBLING_PACKAGES[root]
        for root in sorted(test_roots)
        if root in TEST_ONLY_SIBLING_PACKAGES
    }
    if "pytest" in test_roots:
        expected_dev.add("pytest")
    assert declared_dev == expected_dev, (
        f"the dev extra declares {sorted(declared_dev)} but tests/** imports "
        f"{sorted(test_roots)} → the honest test-only set is {sorted(expected_dev)}. "
        "An entry nothing imports must be deleted; an import with no entry means "
        "the extra (or the environment) is lying about what the suite needs.")
    assert "pytest>=7" in dev_entries, (
        "the pre-existing pytest pin is preserved: " + repr(dev_entries))
    # A tolerated test root this package does NOT declare is out-of-band (it
    # arrives from another lane's checkpoint); said out loud, because a licence
    # with no declaration anywhere is how a suite starts passing by accident.
    out_of_band = sorted(set(TEST_ONLY_FOREIGN_PACKAGES) & test_roots)
    assert out_of_band == ["ordessa_profile"], out_of_band
    assert "ordessa-profile" not in declared_dev and "ordessa-profile" not in declared

    # capability: the same predicate names an undeclared dep and a dead one
    assert re.split(r"[<>=!~;\[]", "ordessa-harness-api>=1.0.0a1,<2", maxsplit=1)[0] == (
        "ordessa-harness-api")
    assert _distribution("ordessa_permissions_backend;python_version>='3.11'") == (
        "ordessa-permissions-backend")
    assert declared != {"requests"}, "the comparison would pass on anything"
    # and it really would refuse the runtime/dev swap this split exists to stop
    assert "ordessa-permissions-backend" not in declared
    assert "ordessa-permissions-backend" in declared_dev


def test_every_domain_module_imports_under_the_published_contract_blocker():
    """Real import isolation: every module loads with the host, the harness
    package, the kernel and every non-allow-listed third-party root blocked,
    while the published contract packages stay reachable (SR-13 — emitting real
    intents requires them, so a stdlib-only blocker would now be wrong)."""
    forbidden = tuple(sorted(ALWAYS_FORBIDDEN_TOP_LEVEL | _non_stdlib_top_levels_of_tree()))
    module_names = [PACKAGE_NAME] + [
        PACKAGE_NAME + "." + path.relative_to(PKG_DIR).with_suffix("").as_posix().replace("/", ".")
        for path in _source_files(PKG_DIR)
        if path.name != "__init__.py"
    ]
    direction_failures: list[str] = []
    other_failures: list[str] = []
    with _isolation(forbidden, keep=(PACKAGE_NAME,)) as blocker:
        for name in module_names:
            try:
                importlib.import_module(name)
            except ImportError as exc:
                if _ImportBlocker.MARKER in str(exc):
                    direction_failures.append(f"{name}: {exc}")
                else:
                    other_failures.append(f"{name}: ImportError {exc}")
            except Exception as exc:
                other_failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert direction_failures == [], "\n".join(direction_failures)
    assert other_failures == [], (
        "modules that do not import for a NON-boundary reason are still red "
        "(collection errors are a FAIL, verification.md):\n"
        + "\n".join(other_failures)
    )
    assert blocker.hits == [] or set(blocker.hits) <= set(forbidden)
    # capability: the blocker is live, not a decorative finder
    with _isolation((PACKAGE_NAME,)) as probe:
        with pytest.raises(ImportError) as info:
            importlib.import_module(PACKAGE_NAME)
        assert _ImportBlocker.MARKER in str(info.value)
        assert probe.hits == [PACKAGE_NAME], probe.hits
    # and it fires on the harness package specifically, not on its api twin
    with _isolation(("ordessa_harness",)) as harness_probe:
        with pytest.raises(ImportError) as harness_info:
            importlib.import_module("ordessa_harness")
        assert _ImportBlocker.MARKER in str(harness_info.value)
        assert harness_probe.hits == ["ordessa_harness"], harness_probe.hits
    # while the published contract remains importable inside this isolation
    with _isolation(forbidden, keep=("ordessa_harness_api",)):
        importlib.import_module("ordessa_harness_api")


def _non_stdlib_top_levels_of_tree() -> set[str]:
    """Every third-party root the source imports, allow-listed or not."""
    roots: set[str] = set()
    for path in _source_files(PKG_DIR):
        for name in _absolute_imports(path.read_text(encoding="utf-8")):
            top = name.split(".")[0]
            if top not in sys.stdlib_module_names and top != PACKAGE_NAME:
                roots.add(top)
    return roots - ALLOWED_NON_STDLIB_TOP_LEVEL


# -- 3: the reverse direction ----------------------------------------------


def test_importing_pacthold_never_reaches_this_package():
    """AGENTS.md rule 3: `pacthold` must not import a plugin or product.

    The blocker is installed *first*, so a cached module cannot satisfy the
    import through `sys.modules` (the blind-gate lesson recorded in
    `apps/server/tests/test_dependency_direction.py:128`).
    """
    with _isolation((PACKAGE_NAME,), keep=("pacthold",)) as blocker:
        with pytest.raises(ImportError) as live:
            importlib.import_module(PACKAGE_NAME)
        assert _ImportBlocker.MARKER in str(live.value), (
            "the blocker did not fire — this test would pass on any code")

        kernel = importlib.import_module("pacthold")
        names = ["pacthold"] + [
            name for _finder, name, _ispkg in pkgutil.walk_packages(
                kernel.__path__, prefix="pacthold.")
        ]
        assert len(names) > 10, f"suspiciously small pacthold walk: {names}"
        unrelated: list[str] = []
        for name in names:
            try:
                importlib.import_module(name)
            except ImportError as exc:
                if _ImportBlocker.MARKER in str(exc):
                    raise AssertionError(
                        f"pacthold module {name} imports the subagents plugin: {exc}") from exc
                unrelated.append(f"{name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                unrelated.append(f"{name}: {type(exc).__name__}: {exc}")
        assert blocker.hits == [PACKAGE_NAME], (
            "the only allowed hit is the deliberate live-probe above; anything "
            "else means pacthold reached this package: " + str(blocker.hits))
    assert unrelated == [], (
        "pacthold modules failed to import in this isolation (not a boundary "
        "violation, but it must not be silently eaten):\n" + "\n".join(unrelated))


# -- 4: nothing composes this package yet -----------------------------------


def test_no_composition_or_server_source_references_this_package_yet():
    missing = [root for root in COMPOSITION_ROOTS if not (REPO_ROOT / root).is_dir()]
    assert missing == [], f"watched roots vanished: {missing}"
    hits: list[str] = []
    for root in COMPOSITION_ROOTS:
        hits.extend(_text_hits(REPO_ROOT / root, PACKAGE_IDENTIFIERS))
    assert hits == [], (
        "integration-request.md I-1 gives product composition to C0 alone; "
        "Q3 must not wire itself into the product, the server, the kernel or "
        "the compat plugin:\n" + "\n".join(hits))


def test_the_reference_scan_is_capable():
    synthetic = {
        "composition.py": "from ordessa_assets_subagents.plugin import Plugin\n",
        "pyproject.toml": 'name = "ordessa-assets-subagents"\n',
        "manifest.json": '{"path": "plugins/assets/subagents"}\n',
    }
    for name, text in synthetic.items():
        assert any(pattern in text for pattern in PACKAGE_IDENTIFIERS), (
            f"the pattern list would miss {name}")
    assert _text_hits(Path(__file__).resolve().parent, ("pytest",)), (
        "_text_hits found nothing in a directory that certainly holds these "
        "bytes — the scan is blind")


# -- 5: no binary or build artifact -----------------------------------------


def test_the_package_directory_holds_no_binary_or_build_artifact():
    assert PACKAGE_DIR.is_dir(), PACKAGE_DIR
    findings, ignored = _artifact_findings(PACKAGE_DIR)
    assert findings == [], (
        "AGENTS.md rule 4 (no binaries in git; build artifacts come from the "
        "packaging script):\n" + "\n".join(findings))
    if ignored:
        # visible, not silent: git keeps these out, so they are a workspace
        # byproduct of running the tooling, not package content.
        print("gitignored build byproducts present under the package:\n"
              + "\n".join(ignored))


def test_running_the_domain_produces_no_artifact(tmp_path):
    """AGENTS.md rule 4 also covers *produced* artefacts: importing and writing
    through this package may not build anything into the source tree except
    interpreter bytecode caches."""
    def listing() -> dict[str, tuple[int, int]]:
        entries: dict[str, tuple[int, int]] = {}
        for path in PACKAGE_DIR.rglob("*"):
            if BYPRODUCT_DIRS.intersection(path.parts) or not path.is_file():
                continue
            stamp = path.stat()
            entries[str(path.relative_to(PACKAGE_DIR))] = (stamp.st_size, stamp.st_mode)
        return entries

    before = listing()
    store_module = importlib.import_module(PACKAGE_NAME + ".store")
    service_module = importlib.import_module(PACKAGE_NAME + ".service")

    class _Authority:
        def verify_principal(self, principal, *, server_scope):  # noqa: ANN001
            return True

        def permission_ceiling(self, principal, server_scope):  # noqa: ANN001
            return frozenset()

    service = service_module.DefinitionService(
        store_module.DefinitionStore(tmp_path / "run"), authority=_Authority())
    created = service.create_definition(
        "u:boundary", server_scope="server:test", slug="probe", display_name="Probe",
        description="Probe row.", origin_scope="public", origin_owner="local",
        operation_key="u:boundary-probe")
    assert (tmp_path / "run" / "definitions" / created.definition_id).is_dir(), (
        "the domain wrote nowhere, so this probe proved nothing")
    after = listing()
    added = sorted(set(after) - set(before))
    assert added == [], f"running the domain produced files inside the package: {added}"
    changed = sorted(key for key in set(before) & set(after)
                     if before[key] != after[key])
    assert changed == [], f"running the domain rewrote package files: {changed}"


def test_the_artifact_walk_catches_every_forbidden_shape(tmp_path):
    fake = tmp_path / "pkg"
    (fake / "src").mkdir(parents=True)
    (fake / "src" / "keep.py").write_text("import json\n", encoding="utf-8")
    (fake / "node_modules").mkdir()
    (fake / "node_modules" / "index.js").write_text("//x\n", encoding="utf-8")
    (fake / "binary.so").write_bytes(b"\x7fELF\x02\x01")
    (fake / "payload.dat").write_bytes(b"\x7fELF\x02\x01")
    (fake / "blob.pyc").write_bytes(b"whatever")
    (fake / "tool").write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(fake / "tool", 0o755)
    findings, ignored = _artifact_findings(fake, ignore_gitignored=False)
    joined = "\n".join(findings)
    assert ignored == [], ignored
    assert "node_modules: forbidden artifact directory" in joined, findings
    assert "binary.so: build artifact (.so)" in joined, findings
    assert "payload.dat: binary magic" in joined, findings
    assert "blob.pyc: build artifact (.pyc)" in joined, findings
    assert "tool: executable bit set" in joined, findings
    assert _artifact_findings(fake / "src", ignore_gitignored=False) == ([], [])


# -- 6: suite integrity (no skips to hide a failure) ------------------------


def _skip_violations(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def _call_name(node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        return ""

    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.Attribute) and sub.attr in {"skip", "xfail"}:
                        problems.append(f"{name}: @{sub.attr} marker on '{node.name}'")
        if isinstance(node, (ast.Attribute, ast.Name)):
            token = getattr(node, "id", None) or getattr(node, "attr", "") or ""
            if "xfail" in token:
                problems.append(f"{name}: xfail reference '{token}'")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if XFAIL_MARKER_RE.match(node.value):
                problems.append(f"{name}: xfail marker string")
        elif isinstance(node, ast.Call) and _call_name(node) in {"skip", "skipif"}:
            if _call_name(node) == "skipif":
                # `skipif(<constant True>)` is a skip with the branch folded
                # away; a real predicate is legitimate and stays allowed.
                if any(isinstance(arg, ast.Constant) and arg.value is True
                       for arg in node.args):
                    problems.append(f"{name}: skipif(True)")
                continue
            ancestor = parents.get(id(node))
            inside_branch = False
            while ancestor is not None:
                if isinstance(ancestor, (ast.If, ast.Try, ast.ExceptHandler, ast.With)):
                    inside_branch = True
                    break
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    break
                ancestor = parents.get(id(ancestor))
            if not inside_branch:
                problems.append(f"{name}: unconditional pytest.skip()")
    return problems


def test_no_test_file_of_this_package_uses_xfail_or_an_unconditional_skip():
    test_files = _source_files(TESTS_DIR)
    assert test_files, "no test files found — the guard would be blind"
    problems: list[str] = []
    for path in test_files:
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            # A file that cannot parse is a collection error, and a collection
            # error is a FAIL (verification.md): it is reported here rather
            # than allowed to surface as a silently missing test.
            problems.append(f"{path.name}: SyntaxError at line {exc.lineno} ({exc.msg})")
            continue
        problems.extend(_skip_violations(source, path.name))
    assert problems == [], (
        "verification.md G23 / AGENTS.md rule 9: a skip or xfail must never "
        "hide a failure, and an unparsable test file hides every test in it; "
        f"every skip in this package has to be conditional and reported:\n"
        + "\n".join(problems))


def test_the_skip_scan_is_capable():
    assert _skip_violations("import pytest\n\n@pytest.mark.xfail\ndef test_a(): ...\n",
                            "a.py"), "blind to xfail"
    assert _skip_violations("import pytest\npytest.skip('nope')\n", "b.py"), (
        "blind to a module-level skip")
    assert _skip_violations("def test_c():\n    pytest.skip('nope')\n", "c.py"), (
        "blind to an unconditional in-function skip")
    assert _skip_violations("import pytest\n"
                            "\n"
                            "def test_d():\n"
                            "    if not _MODULE:\n"
                            "        pytest.skip('named reason')\n", "d.py") == [], (
        "the scan refuses a legitimate reported skip, so writers would be "
        "pushed towards hiding the gap instead of naming it")
    assert _skip_violations("import pytest\n\n@pytest.mark.skip(reason='x')\n"
                            "def test_i(): ...\n", "i.py"), (
        "blind to an unconditional @pytest.mark.skip marker")
    assert _skip_violations("import pytest\n\n@pytest.mark.skipif(True, reason='x')\n"
                            "def test_f(): ...\n", "f.py"), (
        "blind to skipif(True), an unconditional skip wearing a marker")
    assert _skip_violations("import pytest\n\n"
                            "@pytest.mark.skipif(sys.version_info > (3,), reason='x')\n"
                            "def test_j(): ...\n", "j.py") == [], (
        "a conditional skipif predicate must stay legal")
    assert _skip_violations("import pytest\n\n"
                            "@pytest.mark.parametrize('case', ['xfail: hidden red'])\n"
                            "def test_g(case): ...\n", "g.py"), (
        "blind to an xfail marker carried as a string")
    assert _skip_violations("def test_h():\n"
                            "    '''xfail is forbidden in this package'''\n", "h.py") == [], (
        "prose discussing the rule must not read as a marker")
