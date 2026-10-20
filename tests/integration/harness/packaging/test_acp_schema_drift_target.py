"""Category: 可选安装 / optional install — TARGET: the ACP schema the closure carries.

**This file is expected to fail today.** It is the install-side twin of
`tests/integration/harness/access/acp_passthrough_target.test.mjs`: the access tests say what the run
chain must do with an ACP frame; this says that the *bytes the optional installer
puts on disk* must actually be the schema version the adapter declares it speaks.
Baseline packaging facts stay green in `test_packaging_boundaries.py`, so a red here
is a real gap and never a lost baseline.

What is measured, read from `plugins/harness/*/tooling/npm/package.json` (`overrides`) and
`plugins/harness/*/tooling/npm/package-lock.json`:

    brand   root `overrides` the ACP sdk?   a closure member declares   lock resolves   verdict
    codex   yes → 1.3.0                     ^1.3.0 (codex-acp)          1.3.0           satisfied
    pi      yes → 1.3.0                     1.4.0    (pi-acp)           1.3.0           NOT satisfied
    claude  no                              —                            1.4.0 (flat)   n/a
    dsh     no                              —                            1.4.0 (flat)   n/a
    kilo    no                              —                            none present   n/a
    qwen    no                              —                            none present   n/a

Pi is the failure this file exists to report. Its root adds an `overrides` entry for
a package the root does not even depend on; npm applies overrides silently, so it
rewrites `@automatalabs/pi-acp@0.5.0`'s exact `"@agentclientprotocol/sdk": "1.4.0"`
down to `1.3.0`, `npm ci` exits 0, and the offline install hands the adapter a
protocol schema older than the one it was built against. Two findings are reported —
`acp_schema_pin_problems` from the lock (the symptom, what actually lands on disk)
and `acp_override_problems` from the manifest (the cause, which entry forced it) —
because fixing one without the other is exactly how this class of bug returns.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[4] / "plugins" / "harness"
LOCK_INPUTS = ('plugins/harness/qwen/tooling/npm/package-lock.json', 'plugins/harness/claude-code/tooling/npm-legacy/package-lock.json', 'plugins/harness/claude-code/tooling/npm/package-lock.json', 'plugins/harness/kilo/tooling/npm/package-lock.json', 'plugins/harness/pi/tooling/npm/package-lock.json', 'plugins/harness/codex/tooling/npm/package-lock.json', 'plugins/harness/opencode/tooling/npm/package-lock.json', 'plugins/harness/dsh/tooling/npm/package-lock.json')

#: The ACP schema package every adapter in this plugin ultimately depends on.
ACP_SDK = "@agentclientprotocol/sdk"

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.+-]+)?$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(text or "")
    return None if match is None else tuple(int(part) for part in match.groups())


def satisfies(version: str, declared_range: str) -> bool | None:
    """`True`/`False`, or `None` when this range form is not modelled here.

    Only the three forms the ACP schema dependency actually uses are implemented.
    Anything else is reported as unmodelled rather than guessed at, because a
    guessed "satisfied" is exactly how an unsatisfiable lock keeps shipping.
    """
    resolved, wanted = parse_version(version), None
    exact = _VERSION.match(declared_range or "")
    caret = re.fullmatch(r"\^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.+-]+)?", declared_range or "")
    tilde = re.fullmatch(r"~(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.+-]+)?", declared_range or "")
    if exact:
        wanted = tuple(int(part) for part in exact.groups())
    elif caret:
        major, minor, patch = (int(part) for part in caret.groups())
        if resolved is None:
            return None
        if major == 0:
            return resolved[:2] == (0, minor) and resolved >= (0, minor, patch)
        return resolved[0] == major and resolved >= (major, minor, patch)
    elif tilde:
        major, minor, patch = (int(part) for part in tilde.groups())
        if resolved is None:
            return None
        return resolved[:2] == (major, minor) and resolved >= (major, minor, patch)
    if wanted is None or resolved is None:
        return None
    return resolved == wanted


def _ancestor_paths(key: str) -> list[str]:
    """`a/node_modules/b/node_modules/c` -> [`a/node_modules/b`, `a`], npm's nesting order."""
    out: list[str] = []
    current = key
    while "/node_modules/" in current:
        current = current[: current.rindex("/node_modules/")]
        out.append(current)
    return out


def resolve_package(packages: dict[str, dict], name: str, from_key: str) -> tuple[str, dict] | None:
    """The entry npm would install for `name` as seen from `from_key`.

    npm resolves a dependency out of the declaring package's *own* nested install
    directory first, then each ancestor's, then the flat root — so that order is
    what has to be searched, or a correctly nested lock reads as unresolvable.
    """
    for prefix in [from_key, *_ancestor_paths(from_key)]:
        candidate = f"{prefix}/node_modules/{name}"
        if candidate in packages:
            return candidate, packages[candidate]
    root = f"node_modules/{name}"
    return (root, packages[root]) if root in packages else None


def acp_schema_pin_problems(brand_dir: Path) -> list[str]:
    """Every package in one closure that declares an ACP schema the lock cannot satisfy.

    The root manifest is not walked here: `test_packaging_boundaries.py` already
    compares the root's declared versions to the lock. What that comparison cannot
    see is a *transitive* exact pin, several levels down, whose resolution sits in a
    different nesting directory.
    """
    lock = json.loads((brand_dir / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    problems: list[str] = []
    for key, entry in sorted(packages.items()):
        if key == "":
            continue
        who = key[len("node_modules/"):] if key.startswith("node_modules/") else key.rsplit("/node_modules/", 1)[-1]
        for declared_name, declared_range in sorted((entry.get("dependencies") or {}).items()):
            if declared_name != ACP_SDK:
                continue
            resolved = resolve_package(packages, ACP_SDK, key)
            if resolved is None:
                problems.append(f"{who}: declares {ACP_SDK}@{declared_range} and the lock resolves none")
                continue
            where, resolved_entry = resolved
            verdict = satisfies(resolved_entry.get("version", ""), declared_range)
            if verdict is None:
                problems.append(f"{who}: the {ACP_SDK} range {declared_range!r} is not modelled here")
            elif verdict is False:
                problems.append(f"{who}: declares {ACP_SDK}@{declared_range} but the lock resolves "
                                f"{resolved_entry.get('version')} at {where}")
    return problems


def acp_declarations_in_closure(packages: dict[str, dict]) -> list[tuple[str, str]]:
    """Every `(who, range)` that asks for the ACP schema inside one lock closure.

    The root manifest counts too: an override rewrites what the root itself resolves,
    so a root declaration is as much a victim of a forced version as a transitive one.
    """
    found: list[tuple[str, str]] = []
    for key, entry in sorted(packages.items()):
        who = "<root>" if key == "" else (
            key[len("node_modules/"):] if key.startswith("node_modules/")
            else key.rsplit("/node_modules/", 1)[-1])
        declared = (entry.get("dependencies") or {}).get(ACP_SDK)
        if isinstance(declared, str):
            found.append((who, declared))
    return found


def acp_override_problems(brand_dir: Path) -> list[str]:
    """A root `overrides` entry that forces an ACP schema the closure cannot accept.

    `overrides` is a build input like the lock, and npm applies it silently: an entry
    for a package the root does not even depend on rewrites every declaration of it,
    `npm ci` still exits 0, and the adapter runs against a schema it never asked for.
    """
    manifest = json.loads((brand_dir / "package.json").read_text(encoding="utf-8"))
    forced = (manifest.get("overrides") or {}).get(ACP_SDK)
    if not isinstance(forced, str):
        return []
    lock = json.loads((brand_dir / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    resolved = packages.get(f"node_modules/{ACP_SDK}", {}).get("version") \
        or next((entry.get("version") for key, entry in packages.items()
                 if key.endswith(f"/{ACP_SDK}")), None)
    if resolved is None:
        return [f"overrides {ACP_SDK}@{forced} but the lock resolves the schema nowhere"]
    problems: list[str] = []
    for who, declared in acp_declarations_in_closure(packages):
        verdict = satisfies(resolved, declared)
        if verdict is None:
            problems.append(f"{who}: declares {ACP_SDK}@{declared}, not modelled against the forced {resolved}")
        elif verdict is False:
            problems.append(f"overrides forces {ACP_SDK}@{forced} (resolved {resolved}), "
                            f"which violates {who}'s declaration {ACP_SDK}@{declared}")
    return problems


def brands_with_a_lock() -> list[Path]:
    roots = [Path(__file__).resolve().parents[4] / name for name in LOCK_INPUTS]
    assert all(path.is_file() for path in roots), "every explicit selected npm lock must be present"
    return sorted(path.parent for path in roots)


def test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it():
    """No adapter may be installed against an ACP schema older than the one it declares.

    The counterexample this refuses is invisible to every other check in this
    directory: `lock_drift` compares the *root* manifest to the root's own entries,
    and a nested resolution that violates a transitive exact pin satisfies both of
    them. `npm ci` exits 0. The adapter then runs on a schema it never asked for.
    """
    roots = brands_with_a_lock()
    assert roots, "no packaging roots found; the check would pass vacuously"
    findings = {str(root.relative_to(PLUGIN)): acp_schema_pin_problems(root) for root in roots}
    assert all(isinstance(v, list) for v in findings.values())
    broken = {brand: problems for brand, problems in sorted(findings.items()) if problems}
    assert broken == {}, json.dumps(broken, indent=2)


def test_the_schema_pin_detector_reports_a_planted_unsatisfiable_lock(tmp_path):
    brand = tmp_path / "planted"
    brand.mkdir()
    (brand / "package.json").write_text(json.dumps({"name": "planted", "dependencies": {"@acme/adapter": "1.0.0"}}),
                                        encoding="utf-8")
    (brand / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "planted"},
        "node_modules/@acme/adapter": {"version": "1.0.0", "dependencies": {ACP_SDK: "1.4.0"}},
        "node_modules/@acme/adapter/node_modules/" + ACP_SDK: {"version": "1.3.0"},
    }}), encoding="utf-8")
    assert acp_schema_pin_problems(brand) == [
        "@acme/adapter: declares @agentclientprotocol/sdk@1.4.0 but the lock resolves 1.3.0 "
        "at node_modules/@acme/adapter/node_modules/@agentclientprotocol/sdk"], "the planted drift must be reported"


def test_the_schema_pin_detector_accepts_a_range_the_lock_can_satisfy(tmp_path):
    # The other direction, so the check above cannot pass by reporting everything.
    brand = tmp_path / "ok"
    brand.mkdir()
    (brand / "package.json").write_text(json.dumps({"name": "ok", "dependencies": {"@acme/adapter": "1.0.0"}}),
                                        encoding="utf-8")
    (brand / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "ok"},
        "node_modules/@acme/adapter": {"version": "1.0.0", "dependencies": {ACP_SDK: "^1.3.0"}},
        "node_modules/@acme/adapter/node_modules/" + ACP_SDK: {"version": "1.3.0"},
    }}), encoding="utf-8")
    assert acp_schema_pin_problems(brand) == []


def test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure():
    """Name the *cause*, not just the symptom.

    Four of the six roots override only their own direct dependency, which is a
    re-export of a pin they already hold. Codex and Pi additionally override
    `@agentclientprotocol/sdk`, a package the root does not depend on at all — an
    `overrides` entry is applied silently, so it rewrites every declaration of that
    name in the closure. Codex's forced `1.3.0` happens to satisfy its adapter's
    `^1.3.0`; Pi's forced `1.3.0` contradicts `@automatalabs/pi-acp@0.5.0`'s exact
    `1.4.0`.
    """
    roots = brands_with_a_lock()
    assert roots, "no packaging roots found; the check would pass vacuously"
    broken = {root.name: acp_override_problems(root) for root in roots}
    broken = {brand: problems for brand, problems in sorted(broken.items()) if problems}
    assert broken == {}, json.dumps(broken, indent=2)


def _brand_with(tmp_path, *, overrides, declarations):
    """A throwaway closure: one adapter declaring `declarations`, schema forced to `overrides`."""
    brand = tmp_path / "brand"
    brand.mkdir()
    packages: dict[str, dict] = {"": {"name": "brand"}}
    if overrides is not None:
        packages[f"node_modules/{ACP_SDK}"] = {"version": overrides}
    for who, declared in declarations.items():
        packages[f"node_modules/{who}"] = {"version": "9.9.9", "dependencies": {ACP_SDK: declared}}
        if overrides is not None:
            packages[f"node_modules/{who}/node_modules/{ACP_SDK}"] = {"version": overrides}
    manifest = {"name": "brand", "dependencies": {"@acme/adapter": "1.0.0"}}
    if overrides is not None:
        manifest["overrides"] = {ACP_SDK: overrides}
    (brand / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (brand / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": packages}), encoding="utf-8")
    return brand


def test_the_override_detector_reports_a_forced_schema_that_breaks_a_declaration(tmp_path):
    brand = _brand_with(tmp_path, overrides="1.3.0", declarations={"@acme/adapter": "1.4.0"})
    problems = acp_override_problems(brand)
    assert len(problems) == 1, problems
    assert "overrides forces" in problems[0] and "@acme/adapter" in problems[0], problems


def test_the_override_detector_accepts_a_forced_schema_every_declaration_allows(tmp_path):
    brand = _brand_with(tmp_path, overrides="1.3.0", declarations={"@acme/adapter": "^1.3.0"})
    assert acp_override_problems(brand) == [], "the check must not pass by reporting every override"


def test_the_override_detector_is_quiet_without_an_override(tmp_path):
    brand = _brand_with(tmp_path, overrides=None, declarations={"@acme/adapter": "1.4.0"})
    assert acp_override_problems(brand) == [], "no forced schema, no override finding"


@pytest.mark.parametrize("version,declared,expected", [
    ("1.4.0", "1.4.0", True),
    ("1.3.0", "1.4.0", False),
    ("1.3.0", "^1.3.0", True),
    ("1.4.0", "^1.3.0", True),
    ("2.0.0", "^1.3.0", False),
    ("0.2.9", "^0.2.5", True),
    ("0.3.0", "^0.2.5", False),
    ("1.2.9", "~1.2.5", True),
    ("1.3.0", "~1.2.5", False),
    ("1.2.3", "workspace:*", None),
])
def test_the_range_model_only_claims_what_it_implements(version, declared, expected):
    assert satisfies(version, declared) is expected
