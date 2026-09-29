"""T014 guards: ``backend/errors.py`` is the ONE closed code vocabulary.

Constitution III (契约先行) consolidation guards:

* the frozenset ``ALL_CODES`` is exactly the set of code constants the
  module defines — a code defined but unregistered, or registered but
  undefined, is red here;
* **duplicate values are red**: two names carrying one string are a
  registration collision (the wire cannot tell them apart);
* no module may re-define a code constant any more — the owning modules
  import from ``errors.py`` and re-export (their consumer-facing names are
  proven to be the very same strings);
* every published row of ``backend/plugin.MCP_ERROR_FAMILIES`` is a
  vocabulary code (the wire table can only speak domain words);
* every code is raised or referenced from production; the codes with no
  production reference are the *registered orphans* (reserved FR-10
  vocabulary, ``specs/011-q4-mcp/reports/t012-t014.md``) — the guard pins
  that the orphan set does not silently grow; deleting an orphan is not
  forced, growing it unannounced is.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from backend import errors
from backend.errors import (
    ALL_CODES,
    CODE_BY_NAME,
    LEGACY_CARRIED_CODES,
    LEGACY_CARRIED_MCP_STORE_CODES,
    LEGACY_CARRIED_PROBE_CODES,
)

PACKAGE_ROOT = Path(errors.__file__).resolve().parents[1]

_CODE_VALUE = re.compile(r"[A-Z][A-Z0-9_]{2,}")
# a module-level (or indented) constant assigning an uppercase string: the
# shape the per-module registration blocks used before the T014 converge.
_LOCAL_DEFINITION = re.compile(
    r"^\s*[A-Z][A-Z0-9_]{2,}\s*=\s*\"[A-Z][A-Z0-9_]{2,}\"\s*(#.*)?$")

#: reserved FR-10 vocabulary with no production raise/reference yet
#: (registered in specs/011-q4-mcp/reports/t012-t014.md; growth is red)
REGISTERED_ORPHANS = frozenset({
    "DEFINITION_INVALID",
    "OWNER_CONFLICT",
    "ISOLATION_UNPROVEN",
})


def _production_sources() -> "list[Path]":
    return [
        path for folder in ("backend", "adapters")
        for path in (PACKAGE_ROOT / folder).rglob("*.py")
        if "__pycache__" not in path.parts and path.name != "errors.py"
    ]


def _error_module_code_constants() -> "dict[str, str]":
    """Every code-shaped string constant the vocabulary module defines."""
    return {
        name: value for name, value in vars(errors).items()
        if not name.startswith("_") and isinstance(value, str)
        and _CODE_VALUE.fullmatch(value) and name.isupper()
    }


# -- the vocabulary is closed ---------------------------------------------------

def test_all_codes_is_exactly_the_defined_constant_set():
    constants = _error_module_code_constants()
    assert frozenset(constants.values()) == ALL_CODES, (
        "errors.py defines a code that ALL_CODES does not register, or "
        "ALL_CODES lists a name the module does not define")


def test_code_name_and_value_agree():
    for name, value in _error_module_code_constants().items():
        assert name == value, (
            f"{name} = {value!r}: a code constant must carry its own name as "
            "the value (the wire shape is `{code}: {message}`)")


def test_duplicate_value_definitions_are_red():
    constants = _error_module_code_constants()
    values = list(constants.values())
    duplicates = sorted({v for v in values if values.count(v) > 1})
    assert not duplicates, f"codes registered twice under different names: {duplicates}"
    assert len(ALL_CODES) == len(CODE_BY_NAME) == len(values)


def test_code_by_name_maps_every_registered_code():
    constants = _error_module_code_constants()
    assert set(CODE_BY_NAME) == set(constants)
    assert all(CODE_BY_NAME[name] == value for name, value in constants.items())
    assert frozenset(CODE_BY_NAME.values()) == ALL_CODES


# -- modules re-export, they do not re-register ---------------------------------

def test_no_production_module_defines_a_code_constant():
    offenders = [
        f"{path.relative_to(PACKAGE_ROOT)}:{line_no + 1}: {line}"
        for path in _production_sources()
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines())
        if _LOCAL_DEFINITION.match(line) and not line.lstrip().startswith("from")
    ]
    assert not offenders, (
        "module-local code registrations survived the T014 converge; import "
        "from backend/errors.py instead:\n" + "\n".join(offenders))


_MODULE_FAMILIES = {
    "backend.probe": (
        "PROBE_COMMAND_INVALID", "PROBE_SPAWN_FAILED", "PROBE_TIMEOUT",
        "PROBE_FORMAT_INVALID", "PROBE_RESPONSE_TOO_LARGE",
        "PROBE_AUTH_REQUIRED", "PROBE_CONNECTION_FAILED", "PROBE_CANCELLED",
        "PROBE_PROTOCOL_MISMATCH", "PROBE_REDIRECT_REFUSED",
        "PROBE_URL_NOT_ALLOWED"),
    "backend.permissions": (
        "PERMISSION_AUTHORITY_ABSENT", "PERMISSION_ENFORCEMENT_UNPROVEN",
        "PERMISSION_ARGS_DIGEST_REQUIRED", "PERMISSION_REFUSED"),
    "backend.secret": ("PLAN_STALE", "MCP_PLAN_BINDING_INVALID",
                       "SECRET_UNRESOLVED"),
    "backend.service": (
        "APPLICATION_PORT_ABSENT", "SUBMISSION_PERMIT_REQUIRED",
        "EXPECTED_REVISION_REQUIRED", "SUBMISSION_GATE_AMBIGUOUS"),
    "backend.managed.lease": (
        "MCP_STATE_TRANSITION_INVALID", "MCP_LEASE_MISSING", "MCP_LEASE_BUSY",
        "MCP_RECONCILE_REQUIRED", "MCP_NOT_CONNECTED",
        "MCP_TOOL_NOT_APPROVED"),
    "backend.managed.catalog": ("MCP_CATALOG_UNOBSERVABLE",),
    "backend.managed.session_manager": ("MCP_CLIENT_FACTORY_MISSING",),
    "backend.managed.client_stdio": (
        "MCP_CLIENT_NOT_STARTED", "MCP_CLIENT_NOT_CONNECTED",
        "MCP_CLIENT_CLOSED", "MCP_CLIENT_SPAWN_FAILED",
        "MCP_CLIENT_RESPONSE_INVALID", "MCP_CLIENT_CLEANUP_FAILED"),
    "backend.managed.client_http": (
        "MCP_HTTP_URL_NOT_ALLOWED", "MCP_HTTP_REDIRECT_REFUSED",
        "MCP_HTTP_REQUEST_REFUSED", "MCP_HTTP_HOST_ORIGIN_MISMATCH",
        "MCP_HTTP_TRANSPORT_DOWN"),
    "backend.native_intents": (
        "MCP_NATIVE_NAME_CONFLICT", "MCP_CREDENTIAL_PROVENANCE_UNPROVEN",
        "MCP_NATIVE_TARGET_UNSUPPORTED",
        "MCP_PERMISSION_ENFORCEMENT_UNPROVEN"),
    "backend.native_binding": (
        "MCP_GATE_CAPABILITY_UNSUPPORTED", "MCP_GATE_FRAGMENT_INVALID",
        "MCP_GATE_BUSY", "MCP_GATE_RESUME_UNAVAILABLE",
        "MCP_VERIFICATION_MISMATCH", "MCP_ISOLATION_UNPROVEN",
        "MCP_GATE_REFUSED", "NATIVE_PLANNER_ABSENT"),
    # the managed umbrella keeps re-exporting its families' names
    "backend.managed": (
        "MCP_CATALOG_UNOBSERVABLE", "MCP_CLIENT_FACTORY_MISSING",
        "MCP_LEASE_BUSY", "MCP_LEASE_MISSING", "MCP_NOT_CONNECTED",
        "MCP_RECONCILE_REQUIRED", "MCP_STATE_TRANSITION_INVALID",
        "MCP_TOOL_NOT_APPROVED"),
}


def test_owning_modules_re_export_the_vocabulary_strings():
    """Consumer imports (``from backend.permissions import PERMISSION_*`` and
    friends) keep resolving, and every re-exported name is byte-identical to
    the registered code — the converge moved definitions, never values."""
    for module_name, family in _MODULE_FAMILIES.items():
        module = importlib.import_module(module_name)
        for name in family:
            value = getattr(module, name)
            assert value == getattr(errors, name), f"{module_name}.{name}"
            assert value in ALL_CODES, f"{module_name}.{name}"


def test_family_table_rows_are_vocabulary_codes():
    from backend.plugin import MCP_ERROR_FAMILIES
    unknown = sorted(set(MCP_ERROR_FAMILIES) - ALL_CODES)
    assert not unknown, (
        f"the wire contribution publishes non-domain codes: {unknown}")


# -- carried-over groups ---------------------------------------------------------

def test_carried_over_groups_are_disjoint_and_registered():
    assert len(LEGACY_CARRIED_MCP_STORE_CODES) == 6
    assert len(LEGACY_CARRIED_PROBE_CODES) == 5
    assert not (LEGACY_CARRIED_MCP_STORE_CODES & LEGACY_CARRIED_PROBE_CODES)
    assert LEGACY_CARRIED_CODES == (
        LEGACY_CARRIED_MCP_STORE_CODES | LEGACY_CARRIED_PROBE_CODES)
    assert LEGACY_CARRIED_CODES <= ALL_CODES


# -- orphan register ---------------------------------------------------------------

def test_every_code_is_raised_or_referenced_or_a_registered_orphan():
    sources = [path.read_text(encoding="utf-8")
               for path in _production_sources()]
    # ``(?<![A-Z0-9_.])`` keeps another namespace's member (e.g. the harness
    # API's ``ErrorCode.ISOLATION_UNPROVEN``) from posing as a domain use.
    orphans = [
        code for code in sorted(ALL_CODES)
        if not any(re.search(r"(?<![A-Z0-9_.])" + code + r"(?![A-Z0-9_])", text)
                   for text in sources)
    ]
    assert frozenset(orphans) == REGISTERED_ORPHANS, (
        f"unregistered orphan growth: {sorted(set(orphans) - REGISTERED_ORPHANS)}; "
        f"silently retired: {sorted(REGISTERED_ORPHANS - set(orphans))}")
