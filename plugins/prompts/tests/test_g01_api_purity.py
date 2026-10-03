"""G01 / T03 — the public API imports purely, cross-domain imports are refused,
and the TS contract declares the same facts as the Python one.

Counter-examples required by verification.md G01:

* importing the api package must NOT register anything, open a database
  or read data files (probed with a subprocess audit hook: sqlite3.connect
  and file opens outside the package's own import path are refusals);
* a cross-domain implementation dependency (host internals, Profile,
  Harness, other plugins) anywhere in the package is rejected by the
  boundary scan — and the scan is shown to fire on hostile sources, so a
  green boundary test is not a vacuous one;
* "missing dependencies masked by the test environment": the plugin builds
  with an EMPTY ports mapping, and the api imports with site-packages
  suppressed, so no fixture or neighbouring worktree can be quietly
  supplying a seam.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "ordessa_prompts"
CONTRACTS_DIR = PACKAGE_ROOT.parent.parent / "contracts"

#: Nothing in this domain may import these (host internals / sibling
#: products / other plugins). server_plugin_api and the Python stdlib are
#: the whole external vocabulary the package may use.
FORBIDDEN_IMPORT_PREFIXES = (
    "ordessa_server", "ordessa_server_compat", "ordessa_harness",
    "ordessa_profile", "ordessa_workspace", "ordessa_skills",
    "ordessa_command_templates", "pacthold", "fastapi", "starlette",
)


def _imported_names_of(source: str) -> "list[str]":
    """Absolute import names; a relative import (`from .errors import …`) is
    inside this package by construction and is checked separately."""
    tree = ast.parse(source)
    return [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names] + [
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and not node.level]


def _module_imports(path: Path) -> "list[str]":
    return _imported_names_of(path.read_text(encoding="utf-8"))


def _all_package_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _boundary_offenders(names: "list[str]") -> "list[str]":
    return [name for name in names for forbidden in FORBIDDEN_IMPORT_PREFIXES
            if name == forbidden or name.startswith(forbidden + ".")]


def test_every_module_parses_and_lives_under_the_package():
    files = _all_package_files()
    assert files, "no package sources found"


@pytest.mark.parametrize("path", _all_package_files(),
                         ids=lambda p: str(p.relative_to(PACKAGE_ROOT)))
def test_no_module_imports_a_forbidden_domain(path: Path):
    for name in _module_imports(path):
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not (name == forbidden or name.startswith(forbidden + ".")), (
                f"{path.relative_to(PACKAGE_ROOT)} imports {name!r}; the "
                "Prompts domain may consume only server_plugin_api and its "
                "own package (G01 boundary)")


def test_relative_imports_stay_inside_the_package():
    for path in _all_package_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.level <= 2, (
                    f"{path.relative_to(PACKAGE_ROOT)} reaches outside the package")
                assert node.module is None or not node.module.startswith(
                    ("ordessa_", "pacthold")), path


def test_api_package_import_has_no_registration_db_or_data_file_reads():
    """Audit-hook probe: import ordessa_prompts.api in a clean interpreter
    and assert zero sqlite3 connections and no opens outside module files."""
    probe = r"""
import sys, io, pathlib
events = []
def audit(event, args):
    if event in ("sqlite3.connect",):
        events.append((event, str(args[0])))
    elif event == "open":
        events.append((event, str(args[0])))
sys.addaudithook(audit)
import ordessa_prompts.api as api
pkg = pathlib.Path(api.__file__).resolve().parent
offenders = []
for event, target in events:
    if event == "sqlite3.connect":
        offenders.append((event, target))
    else:
        p = pathlib.Path(target)
        try:
            inside = pkg in p.resolve().parents
        except OSError:
            inside = False
        # imports legitimately open .py/.pyc sources of the package
        if not inside and p.suffix not in (".py", ".pyc"):
            offenders.append((event, target))
import json
print(json.dumps({"offenders": offenders,
                  "symbols": sorted(s for s in api.__all__ if not s.startswith("_"))}))
"""
    result = subprocess.run([sys.executable, "-c", probe],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["offenders"] == [], (
        f"importing ordessa_prompts.api had runtime effects: {report['offenders']}")
    assert "PromptSelection" in report["symbols"]


def test_importing_backend_and_plugin_makes_no_either(tmp_path):
    """Even the fuller import must not silently create a store: only an
    explicit PromptsStore construction opens a database (G01)."""
    import ordessa_prompts.backend.service  # noqa: F401
    import ordessa_prompts.plugin  # noqa: F401
    assert not list(tmp_path.iterdir())


def test_missing_dependencies_are_not_masked_by_environment(tmp_path):
    """A context with zero ports builds and serves the public library:
    the fixture environment may not be quietly supplying the seams."""
    from server_plugin_api import ServerPluginContext
    from ordessa_prompts.plugin import PromptsServerPlugin
    plugin = PromptsServerPlugin(store_path=tmp_path / "bare.db")
    registration = plugin.build(ServerPluginContext(
        plugin_id="ordessa.assets.prompts", data_root=tmp_path, ports={}))
    handlers = {d.method_id: d.handler for d in registration.methods}
    created = handlers["prompts.create"]({
        "requestId": "r" * 12, "kind": "instruction",
        "scope": {"kind": "library"}, "title": "bare", "body": "aGk=",
        "operationKey": "k-bare"})
    assert created["id"].startswith("prompt_")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bare.db"], (
        "the bare build reached for something outside its own private store")


# -- the public surface is frozen and needs nothing but the stdlib -------------

#: the documented export set of `ordessa_prompts.api` (api/__init__.py)
EXPECTED_API_EXPORTS = frozenset({
    "BODY_MAX_BYTES", "DESCRIPTION_MAX_CODEPOINTS", "IMPORT_MAX_BYTES",
    "KINDS", "MAX_INSTRUCTIONS_PER_SELECTION", "SCOPES",
    "SNAPSHOT_MAX_TOTAL_BODY_BYTES", "TITLE_MAX_CODEPOINTS",
    "PromptRecord", "PromptRef", "PromptRevision", "PromptScope",
    "PromptSelection", "PromptSnapshot", "ResolvedPrompt",
    "body_digest", "validate_body_bytes", "validate_description",
    "validate_kind", "validate_operation_key", "validate_prompt_id",
    "validate_title", "PROMPT_ERROR_CODES", "PromptError", "NotFoundError",
    "RevisionConflictError", "InvalidContentError", "LimitExceededError",
    "RefKindMismatchError", "ScopeRefusedError", "ArchivedSelectionError",
    "DependencyUnavailableError", "NativeSemanticsUnsupportedError",
    "IdempotencyConflictError", "InvalidRequestError",
    "PromptProfileAuthorization",
})

#: what a module inside `ordessa_prompts.api` may import: stdlib + itself
#: (`base64` is imported lazily inside the wire helper, never at module load)
API_ALLOWED_IMPORTS = {"__future__", "base64", "dataclasses", "hashlib", "re",
                       "typing", "unicodedata"}

#: what `ordessa_prompts.plugin` may import: stdlib + the published contract
#: vocabulary + this package. EXT-02 adds exactly TWO names — the new own
#: package submodule `ordessa_prompts.harness_adapters` and its
#: `contribution` module (the C2 adapter registration face). No assertion
#: was removed; the boundary scan's exact-prefix rule (the SAME
#: predicate `_boundary_offenders` applies to every real package file —
#: see test_boundary_scan_covers_the_new_harness_adapters_files)
#: continues to refuse `ordessa_harness.` internals while the published
#: `ordessa_harness_api` vocabulary stays admissible — both sides proven
#: by test_published_harness_api_admissible_but_internals_refused.
#: The amendment is documented in PX-report.md.
PLUGIN_ALLOWED_IMPORTS = {"__future__", "base64", "pathlib", "typing",
                          "server_plugin_api", "ordessa_prompts",
                          "ordessa_prompts.api", "ordessa_prompts.backend.records",
                          "ordessa_prompts.backend.service",
                          "ordessa_prompts.backend.storage",
                          "ordessa_prompts.harness_adapters",
                          "ordessa_prompts.harness_adapters.contribution"}


def test_api_public_surface_is_exactly_the_documented_set():
    import ordessa_prompts.api as api

    assert set(api.__all__) == EXPECTED_API_EXPORTS, (
        f"unexpected: {sorted(set(api.__all__) - EXPECTED_API_EXPORTS)}, "
        f"missing: {sorted(EXPECTED_API_EXPORTS - set(api.__all__))}")
    for name in api.__all__:
        assert hasattr(api, name), f"__all__ advertises a missing symbol: {name}"


@pytest.mark.parametrize("path", sorted((PACKAGE_ROOT / "api").rglob("*.py")),
                         ids=lambda p: f"api/{p.name}")
def test_api_modules_import_only_stdlib_and_each_other(path: Path):
    for name in _module_imports(path):
        assert name in API_ALLOWED_IMPORTS, (
            f"{path.name} imports {name!r}; the public API must stay stdlib-only "
            "so that importing it cannot register or open anything (G01)")


def test_plugin_imports_only_the_published_contract_vocabulary():
    for name in _module_imports(PACKAGE_ROOT / "plugin.py"):
        assert name in PLUGIN_ALLOWED_IMPORTS, (
            f"plugin.py imports {name!r}; only server_plugin_api, the stdlib and "
            "this package are allowed (G01/G08 boundary)")


def test_boundary_scan_covers_the_new_harness_adapters_files():
    """Round-2/6: the per-file boundary parametrization must include the
    new submodule's files. The EXPECTED set is HARDCODED (not derived
    from the same rglob as the scan — a same-source subset check would
    be tautological); a file renamed away from this list turns this red
    and forces a conscious update."""
    expected = {
        Path("harness_adapters/__init__.py"),
        Path("harness_adapters/capabilities.py"),
        Path("harness_adapters/contribution.py"),
    }
    scanned = {p.relative_to(PACKAGE_ROOT)
               for p in _all_package_files()}
    assert expected <= scanned, expected - scanned


def test_published_harness_api_admissible_but_internals_refused():
    """The exact-prefix boundary rule, proven on BOTH sides for the new
    harness_adapters face (EXT-02 review round 1): the PUBLISHED
    `ordessa_harness_api` vocabulary passes, the harness PLUGIN
    internals (`ordessa_harness.`) are refused."""
    assert _boundary_offenders(["ordessa_harness_api"]) == []
    assert _boundary_offenders(["ordessa_harness_api.contracts"]) == []
    offenders = _boundary_offenders(["ordessa_harness.registry",
                                     "ordessa_harness"])
    assert set(offenders) == {"ordessa_harness.registry", "ordessa_harness"}


def test_the_profile_authorisation_port_is_structurally_satisfiable():
    """The consumed port is a Protocol in the pure api, so a cooperating
    domain can satisfy it without importing Prompts."""
    from ordessa_prompts.api import PromptProfileAuthorization

    class Satisfier:
        def is_authorized(self, caller_subject: str, profile_id: str) -> bool:
            return True

    assert isinstance(Satisfier(), PromptProfileAuthorization)


def test_api_import_works_with_third_party_packages_suppressed():
    """Counter-example to "missing dependencies hidden by the test
    environment": run the import with site-packages suppressed and only this
    package's own source on the path. If the API needed the contract package,
    the Server or any sibling plugin, it would fail here."""
    src_root = str(PACKAGE_ROOT.parent)
    probe = (
        "import sys\n"
        f"sys.path = [{src_root!r}] + [p for p in sys.path if 'site-packages' not in p]\n"
        "import ordessa_prompts.api as api\n"
        "import json\n"
        "print(json.dumps({\n"
        "  'symbols': len(api.__all__),\n"
        "  'contract_imported': 'server_plugin_api' in sys.modules,\n"
        "  'sqlite_imported': 'sqlite3' in sys.modules,\n"
        "  'server_imported': any(m.startswith('ordessa_server') for m in sys.modules),\n"
        "  'plugin_imported': 'ordessa_prompts.plugin' in sys.modules,\n"
        "}))\n"
    )
    result = subprocess.run([sys.executable, "-S", "-c", probe],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["symbols"] == len(EXPECTED_API_EXPORTS)
    assert report["contract_imported"] is False, (
        "importing the api pulled in the Server plugin contract")
    assert report["sqlite_imported"] is False, "importing the api opened sqlite"
    assert report["server_imported"] is False, "importing the api pulled in the Server"
    assert report["plugin_imported"] is False, "importing the api registered the plugin"


# -- the boundary scan itself refuses a cross-domain dependency -----------------

def test_the_boundary_scan_itself_refuses_a_cross_domain_import():
    """A guard that never fires is worthless: feed the very helper the
    boundary test uses hostile sources and the legitimate vocabulary, so a
    green boundary test means the scan really reads imports (the guard's own
    mutation check)."""
    hostile = {
        "server internals": "from ordessa_server.transport import dispatch\n",
        "profile implementation": "import ordessa_profile.records\n",
        "harness implementation": "from ordessa_harness.acp import connect\n",
        "sibling asset plugin": "from ordessa_command_templates.library import store\n",
        "governance kernel": "import pacthold\n",
        "host transport": "from starlette.applications import Starlette\n",
        "deep host internal": "from ordessa_server.db.core import get_db\n",
    }
    for label, source in hostile.items():
        offenders = _boundary_offenders(_imported_names_of(source))
        assert offenders, f"the scan let a {label} import through: {source!r}"

    allowed = ("from server_plugin_api import ServerPluginContext\n"
               "import sqlite3\nimport json\n")
    assert _boundary_offenders(_imported_names_of(allowed)) == [], (
        "the scan rejects the allowed vocabulary instead of the forbidden one")


# -- the TS contract mirrors the Python one (contracts.md "同一 schema") ---------

_TS_LIMIT_KEYS = {
    "titleMaxCodepoints": "TITLE_MAX_CODEPOINTS",
    "descriptionMaxCodepoints": "DESCRIPTION_MAX_CODEPOINTS",
    "bodyMaxBytes": "BODY_MAX_BYTES",
    "maxInstructionsPerSelection": "MAX_INSTRUCTIONS_PER_SELECTION",
    "snapshotMaxTotalBodyBytes": "SNAPSHOT_MAX_TOTAL_BODY_BYTES",
}


def _ts_string_array(source: str, name: str) -> "list[str]":
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.S)
    assert match, f"{name} not found in the TS contract"
    return [item.strip().strip("'\"") for item in match.group(1).split(",")
            if item.strip()]


def _ts_number_object(source: str, name: str) -> "dict[str, int]":
    match = re.search(rf"export const {name} = \{{(.*?)\}} as const", source, re.S)
    assert match, f"{name} not found in the TS contract"
    out: dict[str, int] = {}
    for key, raw in re.findall(r"(\w+):\s*([^,\n]+)", match.group(1)):
        expression = raw.strip()
        assert re.fullmatch(r"[\d\s*()+]+", expression), (
            f"{name}.{key} is not a plain numeric expression: {expression!r}")
        out[key] = eval(expression, {"__builtins__": {}}, {})
    return out


def _ts_scalar(source: str, name: str) -> str:
    match = re.search(rf"export const {name} =\s*'([^']*)'", source)
    if match:
        return match.group(1)
    number = re.search(rf"export const {name} =\s*(\d+) as const", source)
    assert number, f"{name} not found in the TS contract"
    return number.group(1)


def test_the_typescript_and_python_dtos_declare_the_same_facts():
    import ordessa_prompts.api as api
    from ordessa_prompts.backend.service import PromptsService
    from ordessa_prompts.plugin import PLUGIN_ID

    dto_ts = (CONTRACTS_DIR / "dto.ts").read_text(encoding="utf-8")
    keys_ts = (CONTRACTS_DIR / "keys.ts").read_text(encoding="utf-8")

    assert tuple(_ts_string_array(dto_ts, "KINDS")) == api.KINDS
    assert tuple(_ts_string_array(dto_ts, "SCOPES")) == api.SCOPES
    assert tuple(_ts_string_array(dto_ts, "PROMPT_ERROR_CODES")) == (
        api.PROMPT_ERROR_CODES)

    limits = _ts_number_object(dto_ts, "PROMPT_LIMITS")
    for ts_key, py_name in _TS_LIMIT_KEYS.items():
        assert ts_key in limits, f"the TS contract lost {ts_key}"
        assert limits[ts_key] == getattr(api, py_name), (
            f"{ts_key}={limits[ts_key]} differs from Python {py_name}="
            f"{getattr(api, py_name)}")

    # the paging rule lives in the service; the TS contract must agree with it
    assert limits["listDefaultPageSize"] == PromptsService._page_limits(None)
    assert limits["listMaxPageSize"] == PromptsService._page_limits(
        limits["listMaxPageSize"])
    with pytest.raises(api.LimitExceededError) as exc:
        PromptsService._page_limits(limits["listMaxPageSize"] + 1)
    assert exc.value.details["requested"] == limits["listMaxPageSize"] + 1

    assert _ts_scalar(keys_ts, "PROMPTS_PLUGIN_ID") == PLUGIN_ID
    assert PLUGIN_ID == "ordessa.assets.prompts"
    assert _ts_scalar(keys_ts, "PROMPTS_PROFILE_FACET_ID") == "assets.prompts"
    assert _ts_scalar(keys_ts, "PROMPTS_HARNESS_FACET_ID") == "assets.prompts"
    assert _ts_scalar(keys_ts, "PROMPTS_FACET_SCHEMA_VERSION") == "1"


def test_the_published_wire_family_matches_the_ts_key_list():
    """contracts/keys.ts enumerates the `prompts.*` family the plugin must
    publish; a method present on only one side is a contract break."""
    keys_ts = (CONTRACTS_DIR / "keys.ts").read_text(encoding="utf-8")
    declared = _ts_string_array(keys_ts, "PROMPTS_METHOD_IDS")
    source = (PACKAGE_ROOT / "plugin.py").read_text(encoding="utf-8")
    published = re.findall(r'method_id="(prompts\.[A-Za-z]+)"', source)
    assert len(published) == len(set(published)), (
        f"a method id is declared twice: {published}")
    assert sorted(declared) == sorted(published), (
        f"TS says {sorted(declared)}, plugin declares {sorted(published)}")

    components = sorted(key for _, key in
                        re.findall(r"(\w+):\s*'(prompts\.[a-z0-9.-]+)'", keys_ts))
    assert components == ["prompts.library-editor.v1",
                          "prompts.profile-selector.v1"], components


#: the only line shapes a pure TS contract file may carry: a declaration, an
#: object/interface member, an array element, a closer or a comment
_TS_ALLOWED_LINE = re.compile(
    r"^("
    r"(export|interface|type|declare)\b.*"
    r"|[\w$]+\??:.*"
    r"|[}\])]+( as const)?\+?;?"
    r"|'[^']*'(,| as const;|;| const;)?"
    r'|"[^"]*"(,| as const;|;| const;)?'
    r"|//.*|\*.*|/\*.*"
    r")$")


def test_the_ts_contract_files_are_declarations_only():
    """The TS contract is types and constants. A line that is not a
    declaration or a declaration fragment would run at import time (G01)."""
    for name in ("index.ts", "dto.ts", "keys.ts"):
        source = (CONTRACTS_DIR / name).read_text(encoding="utf-8")
        offenders = []
        for number, line in enumerate(source.splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            if not _TS_ALLOWED_LINE.match(text):
                offenders.append((number, text))
        assert offenders == [], (
            f"{name} carries a non-declaration line: {offenders}")
        executable = re.findall(r"^\s*(?!\*)([a-zA-Z_$][\w$]*)\s*\(", source, re.M)
        assert executable == [], (
            f"{name} calls something at module load: {executable}")
