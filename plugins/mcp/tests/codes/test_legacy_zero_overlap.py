"""T014 guard: the closed vocabulary vs the legacy compat surface.

Constitution III boundary: the MCP domain shares exactly **five + six**
codes with ``ordessa_server_compat`` by design (wire compatibility, the
V01/V03/V09 mutual proofs) — the six codes of the legacy MCP asset store
(``assets/mcp.py``) and the five codes of the legacy probe
(``assets/mcp_probe.py``). Everything outside that documented carried-over
set must overlap NOTHING the compatibility core, the workspace plugin or
the host's static wire table already owns; a collision would silently
re-home another plugin's word (the ``wire.error-families`` contributions
are per-composition state and conflict on duplicates).

The comparison reads the REAL compat modules (``ordessa_server_compat``
source and published tables), not a transcription.
"""
from __future__ import annotations

import inspect
import ordessa_server_compat
import re
from pathlib import Path

import ordessa_server_compat.assets.mcp as legacy_store
import ordessa_server_compat.assets.mcp_probe as legacy_probe
from ordessa_server_compat.error_families import COMPAT_ERROR_FAMILIES
from ordessa_workspace.error_families import WORKSPACE_ERROR_FAMILIES
from server_plugin_api.wire_errors import STATIC_ERROR_FAMILIES

from backend.errors import (
    ALL_CODES,
    LEGACY_CARRIED_CODES,
    LEGACY_CARRIED_MCP_STORE_CODES,
    LEGACY_CARRIED_PROBE_CODES,
)

_CODE_STRING = re.compile(r"\"([A-Z][A-Z0-9_]{3,})\"")


def _codes_in(source: str, *, prefix: str | None = None) -> "set[str]":
    found = set(_CODE_STRING.findall(source))
    return {c for c in found if prefix is None or c.startswith(prefix)}


def _package_sources(module) -> str:
    # namespace package: ``inspect.getfile`` refuses it, read ``__path__``
    root = Path(str(next(iter(module.__path__)))).resolve()
    return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                     for path in sorted(root.rglob("*.py"))
                     if "__pycache__" not in path.parts)


# -- the five + six are read from the real legacy modules -----------------------

def test_legacy_store_carries_exactly_six_codes():
    codes = _codes_in(inspect.getsource(legacy_store), prefix="MCP_")
    assert codes == set(LEGACY_CARRIED_MCP_STORE_CODES), codes
    assert len(codes) == 6


def test_legacy_probe_carries_exactly_five_codes():
    codes = _codes_in(inspect.getsource(legacy_probe), prefix="PROBE_")
    assert codes == set(LEGACY_CARRIED_PROBE_CODES), codes
    assert len(codes) == 5


def test_overlap_with_the_legacy_surface_is_exactly_the_carried_set():
    legacy = (
        _codes_in(inspect.getsource(legacy_store), prefix="MCP_")
        | _codes_in(inspect.getsource(legacy_probe), prefix="PROBE_"))
    assert ALL_CODES & legacy == LEGACY_CARRIED_CODES, (
        "the domain vocabulary drifted against the legacy five + six: the "
        "carried-over rows must stay byte-identical and nothing else may "
        "collide")


# -- zero overlap outside the carried rows ---------------------------------------

def test_no_new_code_names_a_compat_package_word():
    """Every raised/re-exported compat string in the whole package (asset
    stores, approvals, accounts, catalog, probe, wire) — a NEW domain code
    (anything outside the five + six) that collides with one would re-home
    another owner's word."""
    compat_strings = _codes_in(_package_sources(ordessa_server_compat))
    new_codes = ALL_CODES - LEGACY_CARRIED_CODES
    collisions = sorted(new_codes & compat_strings)
    assert not collisions, (
        f"new domain codes collide with compat vocabulary: {collisions}")


def test_published_family_tables_do_not_contain_domain_codes():
    """Zero overlap with every table the composition already publishes —
    including the carried rows: compat's MCP/PROBE refusals were answered by
    the host's fall-through, never by a published row, so the MCP plugin's
    contribution introduces no duplicate registration either."""
    for table, label in ((COMPAT_ERROR_FAMILIES, "compat"),
                         (WORKSPACE_ERROR_FAMILIES, "workspace"),
                         (STATIC_ERROR_FAMILIES, "host static")):
        overlap = sorted(ALL_CODES & set(table))
        assert not overlap, f"domain codes already in the {label} table: {overlap}"


def test_the_mcp_contribution_itself_stays_disjoint():
    """The exact conflict the aggregate would hit at composition time: rows
    published by this plugin against rows published by the other plugins and
    the host table."""
    from backend.plugin import MCP_ERROR_FAMILIES
    other_rows = (set(COMPAT_ERROR_FAMILIES) | set(WORKSPACE_ERROR_FAMILIES)
                  | set(STATIC_ERROR_FAMILIES))
    overlap = sorted(set(MCP_ERROR_FAMILIES) & other_rows)
    assert not overlap, (
        f"the wire.error-families contribution duplicates rows: {overlap}")
