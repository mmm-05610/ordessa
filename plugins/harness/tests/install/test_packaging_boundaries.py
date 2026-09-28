"""Category: 可选安装 / optional install — the packaging boundary.

Everything here is about the *installable* half of the plugin: the per-brand npm
roots under `packaging/`, the vendored adapter tarballs, the SBOM each builder
publishes, and the ceilings those builders enforce. None of it is on the run
chain, and that separation is itself asserted (sections 1 and 2).

Each check is a detector written as a pure function over a directory, and each
detector is also run against a planted counterexample in a temp tree, so a
detector that stops matching anything is reported as dead rather than passing
quietly. Nothing here installs, builds, downloads, starts a service or reads a
credential.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[1]
RUNTIME = PLUGIN / "runtime"
BRIDGE = PLUGIN / "third_party" / "harness_remote" / "bridge"
SRC = PLUGIN / "src"
PACKAGING = PLUGIN / "packaging"
BUILDERS = PLUGIN / "packaging" / "builders"

#: Directories that never hold code worth scanning.
SKIP_DIRECTORY_NAMES = {".git", "__pycache__", "node_modules", ".venv"}


# --------------------------------------------------------------------------
# 1. the shipped run chain never names `packaging/`
# --------------------------------------------------------------------------

#: The two ways a file can point at the optional packaging directory: as a path
#: prefix, or as a quoted path component joined at runtime. A doc file name such as
#: `opencode-production-packaging.md` is a mention of a report, not a dependency.
PACKAGING_REFERENCE_TOKENS = ("packaging/", '"packaging"')

#: Executable sources only: `runtime/package.json` documents in prose that the pins
#: live in `packaging/` and that nothing here reads them, and prose is not a dependency.
SCAN_SUFFIXES = {".py", ".mjs", ".js", ".cjs"}


def lines_naming(root: Path, tokens: tuple[str, ...]) -> list[str]:
    """Every `file:line` under `root` whose text contains one of `tokens`."""
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or SKIP_DIRECTORY_NAMES.intersection(path.parts):
            continue
        if path.suffix not in SCAN_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(token in line for token in tokens):
                hits.append(f"{path.relative_to(root)}:{number}")
    return hits


def test_shipped_run_chain_names_no_packaging_path():
    """`runtime/` and the reused bridge are what the Worker actually executes.

    Counterexamples this refuses: a bridge file that resolves its npm root under
    `packaging/`, or a runtime module that imports a builder — either would make
    an optional packaging directory a run-time dependency.
    """
    for root in (RUNTIME, BRIDGE):
        assert lines_naming(root, PACKAGING_REFERENCE_TOKENS) == [], f"{root} must not name packaging"
    # Positive control: the installer scripts really do name packaging roots, so a
    # zero-hit result above is a fact about the run chain, not a dead detector.
    assert lines_naming(BUILDERS, PACKAGING_REFERENCE_TOKENS), "the detector itself needs a counterexample"


def test_packaging_reference_detector_reports_a_planted_file(tmp_path):
    planted = tmp_path / "runtime" / "planted.mjs"
    planted.parent.mkdir()
    planted.write_text('const npm = new URL("../packaging/codex/", import.meta.url)\n', encoding="utf-8")
    assert lines_naming(tmp_path, PACKAGING_REFERENCE_TOKENS) == ["runtime/planted.mjs:1"]


# --------------------------------------------------------------------------
# 2. Python run-chain code may name packaging paths only as inert evidence
# --------------------------------------------------------------------------

def _packaging_bound_names(directory: Path) -> dict[str, list[str]]:
    """Module-level names whose value is built from a `packaging` path component."""
    found: dict[str, list[str]] = {}
    for path in sorted(directory.rglob("*.py")):
        if SKIP_DIRECTORY_NAMES.intersection(path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            constants = {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if "packaging" not in constants:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    found.setdefault(target.id, []).append(f"{path.name}:{node.lineno}")
    return found


def _function_names_reading(directory: Path, names: set[str]) -> dict[str, list[str]]:
    """Functions in `directory` whose body loads one of `names`."""
    readers: dict[str, list[str]] = {}
    for path in sorted(directory.rglob("*.py")):
        if SKIP_DIRECTORY_NAMES.intersection(path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            loaded = {c.id for c in ast.walk(node) if isinstance(c, ast.Name) and isinstance(c.ctx, ast.Load)}
            if loaded & names:
                readers.setdefault(node.name, []).append(f"{path.name}:{node.lineno}")
    return readers


def _call_sites(directory: Path, names: set[str]) -> list[str]:
    """Places that call one of `names`, ignoring the definition itself."""
    sites: list[str] = []
    for path in sorted(directory.rglob("*.py")):
        if SKIP_DIRECTORY_NAMES.intersection(path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                callee = node.func
                name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
                if name in names:
                    sites.append(f"{path}:{node.lineno}")
    return sites


def test_python_packaging_reads_are_reachable_only_from_tests():
    """A `packaging` path in a Python module is allowed to be *evidence*, never read.

    The measured state: `codex/production.py` names the checked-in official install
    script as forensic evidence, and the only code that opens it is
    `official_script_metadata()`, whose only caller is a template test. If a run-chain
    module ever calls it, the optional packaging directory becomes a startup
    dependency of the product — that is the failure this pins.
    """
    bound = _packaging_bound_names(SRC)
    assert bound, "the detector needs at least the known evidence constants to find"
    readers = set(_function_names_reading(SRC, set(bound)))
    assert readers, "no function reads them; widen the check instead of deleting it"
    in_run_chain = [site for reader in readers for site in _call_sites(SRC, {reader})]
    assert in_run_chain == [], f"plugin code reads packaging: {in_run_chain}"
    kernel = REPO / "packages" / "pacthold" / "src" / "pacthold"
    in_kernel = [site for reader in readers for site in _call_sites(kernel, {reader})]
    assert in_kernel == [], f"the Server reads packaging through the plugin: {in_kernel}"


def test_packaging_read_detector_reports_a_planted_call(tmp_path):
    package = tmp_path / "agent_box"
    package.mkdir()
    (package / "evidence.py").write_text(
        "ROOT = __file__\nPACKAGING = ROOT / 'packaging' / 'x'\n\n\ndef read_evidence():\n"
        "    return PACKAGING.read_text()\n", encoding="utf-8")
    (package / "startup.py").write_text(
        "from evidence import read_evidence\n\n\ndef boot():\n    return read_evidence()\n", encoding="utf-8")
    bound = _packaging_bound_names(tmp_path)
    assert "PACKAGING" in bound
    readers = set(_function_names_reading(tmp_path, set(bound)))
    assert "read_evidence" in readers
    assert _call_sites(tmp_path, {"read_evidence"}), "a planted run-chain read must be reported"


# --------------------------------------------------------------------------
# 3. every brand's npm root exists, is mapped, and is mapped to itself
# --------------------------------------------------------------------------

def _install_set_npm_roots() -> dict[str, str]:
    text = (BUILDERS / "harness-install-set.py").read_text(encoding="utf-8")
    match = re.search(r"^NPM_ROOTS = \{(.*?)^\}", text, re.S | re.M)
    assert match, "NPM_ROOTS moved out of harness-install-set.py; update this check"
    return ast.literal_eval("{" + match.group(1) + "}")


def _npm_root_directories() -> list[str]:
    return sorted(p.name for p in PACKAGING.iterdir() if (p / "package-lock.json").is_file())


# The old upstream `claude` alias has its own 0.75.1 closure. It is built with
# --legacy-alias and provisioned as an explicit read-only mount, not as one of
# the install set's eight canonical families (whose `claude-code` pin is 0.81.2).
ALIAS_ONLY_NPM_ROOTS = {"claude-legacy": "build-claude-runtime-artifact.mjs"}


def test_every_packaging_npm_root_has_a_canonical_family_or_explicit_alias_builder():
    """The round-2 defect: a lock with neither a family nor an alias builder.

    A canonical unmapped root is silently skipped by `npm ci`, so its closure
    builder runs against missing dependencies. The legacy alias has a separate
    operator-provisioned closure and must retain its explicit builder.
    """
    roots = _install_set_npm_roots()
    mapped = set(roots.values())
    on_disk = _npm_root_directories()
    assert on_disk, "no npm roots found; the check would pass on an empty list"
    assert set(on_disk) <= mapped | set(ALIAS_ONLY_NPM_ROOTS), (
        f"packaging roots with no canonical or alias builder: {sorted(set(on_disk) - mapped - set(ALIAS_ONLY_NPM_ROOTS))}")
    for directory, builder_name in ALIAS_ONLY_NPM_ROOTS.items():
        builder = BUILDERS / builder_name
        source = builder.read_text(encoding="utf-8")
        assert (PACKAGING / directory / "package-lock.json").is_file()
        assert f'"{directory}"' in source and "--legacy-alias" in source
    for family, directory in roots.items():
        root = PACKAGING / directory
        assert (root / "package.json").is_file(), f"{family} -> packaging/{directory} has no package.json"
        assert (root / "package-lock.json").is_file(), f"{family} -> packaging/{directory} has no lock"
        assert json.loads((root / "package.json").read_text(encoding="utf-8"))["name"].endswith(directory), (
            f"{family}: package name and npm root disagree")


# --------------------------------------------------------------------------
# 4. build inputs agree with each other: declared == resolved == vendored
# --------------------------------------------------------------------------

def _lock(brand: str) -> dict:
    return json.loads((PACKAGING / brand / "package-lock.json").read_text(encoding="utf-8"))


def _vendored_tarballs(brand_dir: Path) -> list[Path]:
    directory = brand_dir / "vendor"
    return sorted(directory.glob("*.tgz")) if directory.is_dir() else []


def lock_bridge_closure(brand: str) -> set[str]:
    """Every package name the brand's own lock resolves.

    `lock_drift_from` already proves declared == resolved; what is left as a
    separate fact is the round-2 defect — one lock carrying another brand's bridge,
    which is invisible to a version comparison because both versions are correct.
    """
    return {key[len("node_modules/"):] for key in _lock(brand).get("packages", {})
            if key.startswith("node_modules/")}


def test_codex_and_pi_own_separate_bridge_closures():
    """The split the consolidation produced: Codex and Pi no longer share a closure."""
    codex, pi = lock_bridge_closure("codex"), lock_bridge_closure("pi")
    assert "@agentclientprotocol/codex-acp" in codex, "Codex's own bridge left its lock"
    assert "@automatalabs/pi-acp" in pi, "Pi's own bridge left its lock"
    assert "@automatalabs/pi-acp" not in codex, "Codex's lock still carries the Pi bridge"
    assert "@agentclientprotocol/codex-acp" not in pi, "Pi's lock still carries the Codex bridge"
    for brand in ("codex", "pi"):
        assert _lock(brand)["lockfileVersion"] == 3
        assert _lock(brand)["packages"][""]["name"] == f"agent-box-harness-runtime-{brand}"


#: npm writes a scoped dependency `@acme/bridge` into a tarball name as
#: `acme-bridge-1.2.3.tgz` — the at-sign is dropped and the slash becomes a dash.
_TARBALL = re.compile(r"(?P<name>.+?)-(?P<version>\d+\.\d+\.\d+(?:[-+][\w.]+)?)\.tgz")


def _tarball_identity(path: Path) -> tuple[str, str] | None:
    match = _TARBALL.fullmatch(path.name)
    if not match:
        return None
    return match.group("name"), match.group("version")


def _lock_key_as_tarball_name(key: str) -> str:
    """`node_modules/@agentclientprotocol/codex-acp` -> `agentclientprotocol-codex-acp`."""
    return key.removeprefix("node_modules/").lstrip("@").replace("/", "-")


def lock_drift_from(brand_dir: Path) -> list[str]:
    """Declared top-level dependencies that the checked-in lock does not resolve exactly.

    This is the packaging-side twin of what `build-codex-runtime-artifact.test.mjs`
    calls `CODEX_LOCK_VERSION_MISMATCH`, applied to the inputs rather than to a built
    closure: the drift is caught before anything is installed.
    """
    manifest = json.loads((brand_dir / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((brand_dir / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    problems: list[str] = []
    for name, declared in sorted((manifest.get("dependencies") or {}).items()):
        entry = packages.get(f"node_modules/{name}")
        if entry is None:
            problems.append(f"{name}: declared but absent from the lock")
        elif entry.get("version") != declared:
            problems.append(f"{name}: declared {declared} but locked {entry.get('version')}")
    return problems


def vendor_drift_from(brand_dir: Path) -> list[str]:
    """Vendored tarballs that no longer carry the version the manifest declares.

    `vendor/*.tgz` is fetched once and installed offline; a stale tarball is the
    quietest possible drift, because `npm ci` against it still succeeds while
    installing something other than what the lock says.
    """
    manifest = json.loads((brand_dir / "package.json").read_text(encoding="utf-8"))
    declared = manifest.get("dependencies") or {}
    by_flattened_name = {name.replace("/", "-"): name for name in declared}
    problems: list[str] = []
    for ball in _vendored_tarballs(brand_dir):
        identity = _tarball_identity(ball)
        if identity is None:
            problems.append(f"{ball.name}: version is not encoded in the file name")
            continue
        name, version = identity
        hit = by_flattened_name.get(name) or by_flattened_name.get(f"@{name}")
        if hit is None:
            problems.append(f"{ball.name}: no declared dependency matches it")
        elif declared[hit] != version:
            problems.append(f"{ball.name}: vendored {version} but {hit} declares {declared[hit]}")
    return problems


def lock_drift(brand: str) -> list[str]:
    return lock_drift_from(PACKAGING / brand)


def vendor_drift(brand: str) -> list[str]:
    return vendor_drift_from(PACKAGING / brand)


@pytest.mark.parametrize("brand", ["claude", "codex", "dsh", "kilo", "pi", "qwen"])
def test_no_declared_dependency_has_drifted_from_its_lock(brand):
    assert lock_drift(brand) == [], f"packaging/{brand}: {lock_drift(brand)}"


@pytest.mark.parametrize("brand", ["codex", "pi"])
def test_a_vendored_adapter_tarball_carries_the_declared_version(brand):
    assert _vendored_tarballs(PACKAGING / brand), f"packaging/{brand}/vendor disappeared; the check would pass vacuously"
    assert vendor_drift(brand) == [], f"packaging/{brand}: {vendor_drift(brand)}"


def test_the_lock_drift_detector_reports_a_planted_mismatch(tmp_path):
    brand = tmp_path / "alpha"
    brand.mkdir()
    (brand / "package.json").write_text(json.dumps(
        {"name": "alpha", "dependencies": {"thing": "1.2.3"}}), encoding="utf-8")
    (brand / "package-lock.json").write_text(json.dumps(
        {"lockfileVersion": 3, "packages": {"node_modules/thing": {"version": "1.2.9"}}}), encoding="utf-8")
    assert lock_drift_from(brand) == ["thing: declared 1.2.3 but locked 1.2.9"], "drift must be reported"


def test_the_vendor_drift_detector_reports_a_planted_stale_tarball(tmp_path):
    brand = tmp_path / "beta"
    (brand / "vendor").mkdir(parents=True)
    (brand / "package.json").write_text(json.dumps(
        {"name": "beta", "dependencies": {"@acme/bridge": "2.0.0"}}), encoding="utf-8")
    (brand / "vendor" / "acme-bridge-1.9.0.tgz").write_bytes(b"")
    assert vendor_drift_from(brand) == ["acme-bridge-1.9.0.tgz: vendored 1.9.0 but @acme/bridge declares 2.0.0"]


def vendor_vs_lock_from(brand_dir: Path) -> list[str]:
    """Vendored tarballs against what the *lock* resolved, not what the manifest says.

    The builder reads two inputs — the lock and `vendor/` — and `npm ci --offline`
    succeeds against either one. A tarball that agrees with the manifest but not
    with the lock builds an artifact whose SBOM describes a closure nobody installed.
    """
    lock = json.loads((brand_dir / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    by_tarball_name = {_lock_key_as_tarball_name(k): v for k, v in packages.items()
                       if k.startswith("node_modules/")}
    problems: list[str] = []
    for ball in _vendored_tarballs(brand_dir):
        identity = _tarball_identity(ball)
        if identity is None:
            problems.append(f"{ball.name}: version is not encoded in the file name")
            continue
        name, version = identity
        entry = by_tarball_name.get(name)
        if entry is None:
            problems.append(f"{ball.name}: nothing in the lock closure is named {name}")
        elif entry.get("version") != version:
            problems.append(f"{ball.name}: vendored {version} but the lock resolved {entry.get('version')}")
    return problems


def sbom_vs_lock_from(brand_dir: Path) -> list[str]:
    """The published inventory against the lock that produced it.

    An SBOM entry the lock does not resolve describes a build that no longer exists;
    a lock package missing from the SBOM is an unpublished component that shipped.
    A matching path with a different version or integrity is the drift a re-label
    would hide.
    """
    inventory = brand_dir / "artifacts" / "SBOM.json"
    if not inventory.is_file():
        return []
    lock = json.loads((brand_dir / "package-lock.json").read_text(encoding="utf-8"))
    packages = {k: v for k, v in lock.get("packages", {}).items() if k.startswith("node_modules/")}
    listed = json.loads(inventory.read_text(encoding="utf-8")).get("packages") or []
    problems: list[str] = []
    by_path = {}
    for entry in listed:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not path:
            problems.append(f"{json.dumps(entry)[:60]}: SBOM entry has no path")
            continue
        if path in by_path:
            problems.append(f"{path}: listed twice in the SBOM")
        by_path[path] = entry
    for path in sorted(set(by_path) - set(packages)):
        problems.append(f"{path}: in the SBOM but not resolved by the lock")
    for path in sorted(set(packages) - set(by_path)):
        problems.append(f"{path}: resolved by the lock but missing from the SBOM")
    for path in sorted(set(by_path) & set(packages)):
        for field in ("version", "integrity"):
            if by_path[path].get(field) != packages[path].get(field):
                problems.append(f"{path}: SBOM {field} does not match the lock")
    return problems


def sbom_present(brand: str) -> bool:
    return (PACKAGING / brand / "artifacts" / "SBOM.json").is_file()


@pytest.mark.parametrize("brand", ["codex", "pi"])
def test_a_vendored_tarball_is_inside_the_lock_it_ships_with(brand):
    assert _vendored_tarballs(PACKAGING / brand), f"packaging/{brand}/vendor disappeared; the check would pass vacuously"
    assert vendor_vs_lock_from(PACKAGING / brand) == [], f"packaging/{brand}: {vendor_vs_lock_from(PACKAGING / brand)}"


@pytest.mark.parametrize("brand", ["codex", "pi"])
def test_the_published_sbom_is_the_lock_closure_exactly(brand):
    assert sbom_present(brand), f"packaging/{brand} lost its SBOM; the check would pass vacuously"
    assert sbom_vs_lock_from(PACKAGING / brand) == [], f"packaging/{brand}: {sbom_vs_lock_from(PACKAGING / brand)}"


def transitively_overridden_names(brand_dir: Path) -> list[str]:
    """Names an `overrides` entry rewrites that the root does not itself depend on.

    Overriding your own direct dependency is a restatement of a pin you already hold.
    Overriding anything else is a silent rewrite of a transitive constraint the root
    never measured — legal, and worth knowing exists before someone adds a third.
    """
    manifest = json.loads((brand_dir / "package.json").read_text(encoding="utf-8"))
    declared = set(manifest.get("dependencies") or {})
    return sorted(name for name in (manifest.get("overrides") or {}) if name not in declared)


def test_only_the_two_expected_roots_override_a_package_they_do_not_depend_on():
    found = {root.name: transitively_overridden_names(root)
             for root in sorted(PACKAGING.iterdir()) if (root / "package.json").is_file()}
    assert found == {
        "claude": [], "claude-legacy": [], "codex": ["@agentclientprotocol/sdk"], "dsh": [], "kilo": [],
        "pi": ["@agentclientprotocol/sdk"], "qwen": [],
    }, json.dumps(found, indent=2)


def test_the_transitive_override_detector_reports_a_planted_third_one(tmp_path):
    brand = tmp_path / "gamma"
    brand.mkdir()
    (brand / "package.json").write_text(json.dumps(
        {"name": "gamma", "dependencies": {"@acme/adapter": "1.0.0"},
         "overrides": {"@acme/adapter": "1.0.0", "@acme/sneaky": "0.1.0"}}), encoding="utf-8")
    assert transitively_overridden_names(brand) == ["@acme/sneaky"]


def _planted_brand(tmp_path, *, declared, locked, tarballs=(), sbom_entries=None):
    brand = tmp_path / "planted"
    (brand / "vendor").mkdir(parents=True)
    (brand / "artifacts").mkdir()
    (brand / "package.json").write_text(json.dumps(
        {"name": "planted", "dependencies": declared}), encoding="utf-8")
    (brand / "package-lock.json").write_text(json.dumps(
        {"lockfileVersion": 3, "packages": {f"node_modules/{k}": v for k, v in locked.items()}}), encoding="utf-8")
    for name in tarballs:
        (brand / "vendor" / name).write_bytes(b"")
    if sbom_entries is not None:
        (brand / "artifacts" / "SBOM.json").write_text(json.dumps({"packages": sbom_entries}), encoding="utf-8")
    return brand


def test_the_drift_detectors_report_planted_disagreements(tmp_path):
    """One fixture, three kinds of drift, so no detector is quietly dead.

    `@acme/bridge` is declared and locked at 2.0.0; the vendor tarball and the SBOM
    are each made to disagree with it in a different way.
    """
    declared = {"@acme/bridge": "2.0.0"}
    locked = {"@acme/bridge": {"version": "2.0.0", "integrity": "sha512-real"}}
    on_time = _planted_brand(tmp_path / "a", declared=declared, locked=locked,
                             tarballs=["acme-bridge-2.0.0.tgz"],
                             sbom_entries=[{"path": "node_modules/@acme/bridge",
                                            "version": "2.0.0", "integrity": "sha512-real"}])
    assert vendor_vs_lock_from(on_time) == [] and sbom_vs_lock_from(on_time) == []

    stale = _planted_brand(tmp_path / "b", declared=declared, locked=locked,
                           tarballs=["acme-bridge-1.9.0.tgz"],
                           sbom_entries=[{"path": "node_modules/@acme/bridge",
                                          "version": "2.0.0", "integrity": "sha512-real"}])
    assert vendor_vs_lock_from(stale) == [
        "acme-bridge-1.9.0.tgz: vendored 1.9.0 but the lock resolved 2.0.0"]

    relabelled = _planted_brand(tmp_path / "c", declared=declared, locked=locked,
                                sbom_entries=[{"path": "node_modules/@acme/bridge",
                                               "version": "2.0.0", "integrity": "sha512-other"}])
    assert sbom_vs_lock_from(relabelled) == [
        "node_modules/@acme/bridge: SBOM integrity does not match the lock"]

    missing = _planted_brand(tmp_path / "d", declared=declared,
                             locked={**locked, "@acme/left-out": {"version": "1.0.0", "integrity": "sha512-x"}},
                             sbom_entries=[{"path": "node_modules/@acme/bridge",
                                            "version": "2.0.0", "integrity": "sha512-real"}])
    assert sbom_vs_lock_from(missing) == [
        "node_modules/@acme/left-out: resolved by the lock but missing from the SBOM"]

    invented = _planted_brand(tmp_path / "e", declared=declared, locked=locked,
                              sbom_entries=[{"path": "node_modules/@acme/bridge",
                                             "version": "2.0.0", "integrity": "sha512-real"},
                                            {"path": "node_modules/@acme/never-installed",
                                             "version": "9.9.9", "integrity": "sha512-y"}])
    assert sbom_vs_lock_from(invented) == [
        "node_modules/@acme/never-installed: in the SBOM but not resolved by the lock"]


# --------------------------------------------------------------------------
# 5. the build/download bound is one agreed number, not seven drifting ones
# --------------------------------------------------------------------------

#: Measured, not assumed: every `build-<brand>-runtime-artifact.mjs` declares the
#: same two ceilings.
MAX_ENTRIES = 32_768
MAX_BYTES = 1024 * 1024 * 1024

#: `export const MAX_BYTES = 1024 * 1024` in a builder — read as text, because these
#: are JavaScript files and a Python parser has no business pretending to understand
#: them. A builder that writes anything other than a product of integers does not
#: match, and the count assertion below reports it loudly rather than reading it as
#: a smaller number.
_JS_PRODUCT = re.compile(r"^export const (?P<name>MAX_ENTRIES|MAX_BYTES) = (?P<value>[\d_][\d_ ]*(?:\*[\d_ ]+)*)$", re.M)


def builder_bounds(directory: Path) -> dict[str, dict[str, int]]:
    found: dict[str, dict[str, int]] = {}
    for path in sorted(directory.glob("build-*-runtime-artifact.mjs")):
        values = {}
        for match in _JS_PRODUCT.finditer(path.read_text(encoding="utf-8")):
            product = 1
            for factor in match.group("value").split("*"):
                product *= int(factor.strip().replace("_", ""))
            values[match.group("name")] = product
        if values:
            found[path.name] = values
    return found


def test_every_runtime_artifact_builder_shares_one_bound():
    """One ceiling for the whole family, so a brand cannot silently widen its own.

    This is the bound the reviewer described as a download size limit. What is
    actually in the tree is `32768` entries / `1 GiB` per closure, identical in all
    seven builders, and it bounds the *artifact the builder assembles* — not a
    download. `TEST-REVIEW.md` records the search that establishes that no 100 MB
    figure exists anywhere in the plugin, the scripts or the Server.
    """
    bounds = builder_bounds(BUILDERS)
    assert len(bounds) == 7, f"expected one builder per brand, found {sorted(bounds)}"
    assert all({"MAX_ENTRIES", "MAX_BYTES"} <= set(value) for value in bounds.values()), bounds
    assert {tuple(sorted(v.items())) for v in bounds.values()} == {
        (("MAX_BYTES", MAX_BYTES), ("MAX_ENTRIES", MAX_ENTRIES))}, bounds


def test_the_bound_detector_reports_a_planted_divergent_builder(tmp_path):
    (tmp_path / "build-alpha-runtime-artifact.mjs").write_text(
        "export const MAX_ENTRIES = 32768\nexport const MAX_BYTES = 2 * 1024 * 1024 * 1024\n", encoding="utf-8")
    found = builder_bounds(tmp_path)
    assert found["build-alpha-runtime-artifact.mjs"]["MAX_BYTES"] == 2 * MAX_BYTES, (
        "a doubled ceiling must be visible to the check, not averaged away")


def test_the_run_chain_declares_no_byte_ceiling_of_its_own():
    """Nothing on the run chain bounds a transfer in bytes.

    The honest form of the reviewer's item: the only bound the reused bridge puts on
    an Agent's first-use download is a wall-clock one (`START_TIMEOUT_MS`, pinned in
    `tests/access/test_acp_boundaries.py`). The one `MAX_ENTRIES` the run chain used
    to hold belonged to the transcript cache, and the cache retired with the envelope
    that read it, so the name is now simply absent here — asserted as absent rather
    than filtered, because an empty match over a `all(...)` would pass silently if a
    future cache reappeared under the same name.
    """
    hits = [line for root in (RUNTIME, BRIDGE) for line in lines_naming(root, ("MAX_BYTES",))]
    assert hits == [], f"the run chain gained a byte ceiling: {hits}"
    entry_caps = [line for root in (RUNTIME, BRIDGE) for line in lines_naming(root, ("MAX_ENTRIES",))]
    assert entry_caps == [], f"the run chain gained an entry ceiling: {entry_caps}"
