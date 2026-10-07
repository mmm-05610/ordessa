"""Q4/T10 wire-contract guard: the frontend `wire.ts`/`dto.ts` surface pinned
against the backend's live registration face and the real dispatch answers.

Three dimensions, each parsed from SOURCE (AST-lite text scan via
``contract_helpers``; descriptors read off the activated plugin, not a copy):

* WCG-01 method set: every ``MCP_WIRE_METHODS`` id resolves to a registered
  ``ServerMethodDescriptor.method_id``, and every descriptor is TS-covered or
  a registered unfronted row;
* WCG-02 request bodies: the fields ``createFetchMcpWireClient`` actually
  sends are checked against required ∪ optional in BOTH directions (the two
  checks mirror the host dispatch's own `missing`/`unexpected` wall — a TS
  body outside the descriptor shape would be refused at runtime, so pinning
  it statically pins what the browser would experience);
* WCG-03 response sampling: the TS-side answer contract (inline return types
  plus the dto.ts interfaces they name) against the result key sets of REAL
  round-trip dispatches over the live host (tests/service precedent; the
  probe leg samples ``backend.probe._handshake_facts``' own output shape, so
  nothing here transcribes the service keys by hand).

WHY THIS GUARD SHIPS WITH A LEDGER, AND WHY THE LEDGER IS NOW THE ALIGNED
SNAPSHOT: T08 wrote the original frontend table as a *拟定值*; T09 registered
`mcp.list/get/archive` per contracts.md §1 and never reconciled, so the guard
originally pinned a measured FULL drift (renames, undeclared params, missing
identity fields, response wrapper/field mismatches). The 012 branch
consolidation then started the registered fix-forward
(contract-guard.md §四) by rewriting `wire.ts` to the registered face —
method ids, identity injection, unwrap paths, scope kinds — but stopped
before updating this ledger, `dto.ts` and the UI, which turned every WCG
cell red exactly as designed ("前端任何一条落地时，本守卫会红并点名符号").
The 016 CMP reconciliation (specs/011-q4-mcp/reports/wire-alignment.md)
completed the move on the frontend contract side: `dto.ts` now mirrors the
live round-trip answers field-by-field, and the ledger below is the ALIGNED
snapshot — empty gap sets, identity injection parsed from source, unwrap
paths parsed from source. The protocol is unchanged: any future move on
either side that is not consciously reflected here turns this file red with
the drifting symbols named. The remaining UI-layer migration (settings/
status/chat consumers and their fakes) is registered in
specs/016-overnight-batch/reports/MCP-report.md — it is NOT silently faked
here.
"""
from __future__ import annotations

import re

import pytest

from contract_helpers import (
    DTO_TS,
    PACKAGE_ROOT,
    WIRE_TS,
    AllowProbeAuthority,
    RegisteredSurface,
    Stack,
    _interface_body,
    parse_backend_tuple,
    parse_binding_table,
    parse_identity_injection,
    parse_interface_field_names,
    parse_request_bodies,
    parse_result_paths,
    parse_response_types,
    parse_ts_union,
    seed,
    stdio_definition,
)

# -- the registered aligned snapshot (measured; adjudication in the module
# docstring; update ONLY together with wire-alignment.md / contract-guard.md
# when one side consciously moves).

TS_RENAMES: dict[str, str] = {}  # aligned: binding-table ids ARE the registered ids
BACKEND_UNFRONTED = frozenset({"mcp.planForSubmission"})

PARAM_EXTRA_GAPS: dict[str, frozenset[str]] = {}  # aligned (body = callsite ∪ injection)
PARAM_MISSING_REQUIRED: dict[str, frozenset[str]] = {}  # aligned

# ts key -> (answer path in the result ("" = top level), expected top-level
# keys, ts fields absent from the answer, answer keys the TS contract does not
# declare). ALIGNED: every sampled row pins the exact wrapper and ∅ gaps on
# both sides. Live-connection rows are NOT_SAMPLED: their answers need a real
# lease (proven in tests/integration T10-INT-01/05), and their drift is pinned
# at the return-interface level.
RESPONSE_LEDGER = {
    "probe": ("probe", {"definitionId", "revision", "probe"}, frozenset(),
              frozenset()),
    "listDefinitions": ("definitions[0]", {"definitions", "nextCursor"},
                        frozenset(), frozenset()),
    "getDefinition": ("latestRevision", {"definition", "latestRevision"},
                      frozenset(), frozenset()),
    "saveRevision": ("", {"definition", "replayed", "revision"},
                     frozenset(), frozenset()),
    "approveRevision": ("", {"approval", "definitionId", "revision"},
                        frozenset(), frozenset()),
    "archiveDefinition": ("definition", {"definition"}, frozenset(), frozenset()),
    "assign": ("assignment", {"assignment", "replayed"}, frozenset(), frozenset()),
    "unassign": ("assignment", {"assignment", "replayed"}, frozenset(), frozenset()),
    "resolvePreview": ("", {"nativePermissionPostures", "snapshot"},
                       frozenset(), frozenset()),
}
NOT_SAMPLED = {"inspectConnection": "McpConnectionFacts",
               "listTools": "McpListToolsResult"}

VALUE_DOMAINS = {  # scopeKind: TS union vs the backend's accepted kinds — aligned
    "ts": {"user-default", "project", "profile", "session"},
    "backend": {"user-default", "project", "profile", "session"},
}


# -- pure comparison layers (unit-twin-testable; the tests below feed SOURCE) --

def check_method_sets(ts_ids, descriptor_ids, renames, unfronted):
    """Drift strings for the binding-table vs registration-face sets."""
    drift = []
    resolved = {}
    for ts_id in sorted(ts_ids):
        target = renames.get(ts_id, ts_id)
        if target not in descriptor_ids:
            drift.append(f"{ts_id} resolves to {target!r}, not a registered "
                         "ServerMethodDescriptor.method_id")
        else:
            resolved[ts_id] = target
    for ts_id, target in sorted(renames.items()):
        if ts_id not in ts_ids:
            drift.append(f"registered rename {ts_id} -> {target} is stale: "
                         f"{ts_id} no longer in MCP_WIRE_METHODS")
        elif ts_id in resolved and resolved[ts_id] != target:
            drift.append(f"rename ledger conflict on {ts_id}")
    for mid in sorted(unfronted):
        if mid not in descriptor_ids:
            drift.append(f"registered unfronted method {mid} is no longer registered")
    for mid in sorted(descriptor_ids - set(resolved.values()) - set(unfronted)):
        drift.append(f"registered method {mid} has no MCP_WIRE_METHODS binding "
                     "and is not a registered unfronted row")
    return drift


def check_param_shapes(bodies, shapes, extra_gaps, missing_required):
    """Drift strings: ts body vs required∪optional, both directions."""
    drift = []
    for key, body in sorted(bodies.items()):
        if key not in shapes:
            drift.append(f"client method {key} has no resolved descriptor shape")
            continue
        required, optional = shapes[key]
        declared = required | optional
        extras = body - declared
        registered_extras = extra_gaps.get(key, frozenset())
        if extras != registered_extras:
            drift.append(f"{key}: undeclared body fields {sorted(extras)} "
                         f"differ from the registered gap {sorted(registered_extras)}")
        missing = required - body
        registered_missing = missing_required.get(key, frozenset())
        if missing != registered_missing:
            drift.append(f"{key}: required fields the client never sends "
                         f"{sorted(missing)} differ from the registered set "
                         f"{sorted(registered_missing)}")
    return drift


def resolve_path(result, path):
    current = result
    if not path:
        return current
    for segment in path.split("."):
        m = re.fullmatch(r"(\w+)\[(\d+)\]", segment)
        if m:
            current = current[m.group(1)][int(m.group(2))]
        else:
            current = current[segment]
    return current


def check_responses(ts_returns, dto_fields, results, ledger, not_sampled):
    """Drift strings: TS answer contract vs the real round-trip keys."""
    drift = []
    missing_ts = sorted(set(ts_returns) - set(ledger) - set(not_sampled))
    if missing_ts or set(ledger) | set(not_sampled) != set(ts_returns):
        drift.append("sampling coverage is not the registered partition: "
                     f"ledger {sorted(ledger)}, not-sampled {sorted(not_sampled)}, "
                     f"ts returns {sorted(ts_returns)}")
    for key, spec in sorted(ledger.items()):
        path, top_keys, ts_gaps, backend_extras = spec
        result = results[key]
        if set(result) != top_keys:
            drift.append(f"{key}: result top-level keys {sorted(result)} differ "
                         f"from the registered wrapper {sorted(top_keys)}")
        actual = set(resolve_path(result, path))
        ts_fields = (dto_fields[ts_returns[key]]
                     if isinstance(ts_returns[key], str) else ts_returns[key])
        observed_gaps = ts_fields - actual
        if observed_gaps != set(ts_gaps):
            drift.append(f"{key}: TS fields missing from the answer "
                         f"{sorted(observed_gaps)} differ from the registered "
                         f"gap {sorted(ts_gaps)} (answer keys {sorted(actual)})")
        observed_extras = actual - ts_fields
        if observed_extras != set(backend_extras):
            drift.append(f"{key}: answer keys outside the TS contract "
                         f"{sorted(observed_extras)} differ from the registered "
                         f"extras {sorted(backend_extras)}")
    for key, iface in sorted(not_sampled.items()):
        if key not in ts_returns:
            continue  # the partition line above already reports it
        if ts_returns[key] != iface:
            drift.append(f"{key}: TS return type moved to {ts_returns[key]!r}; "
                         f"the guard pins {iface!r} (re-sample it or update the ledger)")
    return drift


# -- the source fixtures ---------------------------------------------------------

@pytest.fixture(scope="module")
def wire_text():
    return WIRE_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dto_text():
    return DTO_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ts_tables(wire_text):
    table = parse_binding_table(wire_text)
    bodies = parse_request_bodies(wire_text)
    assert set(bodies) == set(table), "every client method must have a call site"
    return table, bodies


@pytest.fixture(scope="module")
def descriptor_shapes(tmp_path_factory):
    surface = RegisteredSurface(tmp_path_factory.mktemp("contract-surface"))
    return {mid: (req, opt) for mid, (req, opt) in surface.methods.items()}


@pytest.fixture(scope="module")
def ts_returns(wire_text, dto_text):
    """TS answer contracts, with named dto.ts interfaces resolved to fields.

    Non-vacuity: every named interface must exist in dto.ts — a deleted or
    renamed interface is itself drift.
    """
    out = {}
    for key, spec in parse_response_types(wire_text).items():
        if isinstance(spec, str):
            _interface_body(dto_text, spec)  # raises if the interface is gone
            out[key] = spec
        else:
            out[key] = spec
    return out


@pytest.fixture(scope="module")
def dto_fields(dto_text):
    names = set()
    for value in parse_response_types(WIRE_TS.read_text(encoding="utf-8")).values():
        if isinstance(value, str):
            names.add(value)
    names |= set(NOT_SAMPLED.values())
    return {name: parse_interface_field_names(dto_text, name) for name in sorted(names)}


@pytest.fixture
def roundtrip_results(tmp_path, dto_fields):
    """Real dispatches; the probe leg runs backend.probe's OWN fact builder."""
    from backend.probe import _handshake_facts

    facts = _handshake_facts(
        "stdio", {"serverInfo": {"name": "shape-only", "version": "0"}},
        {"requested": "2025-11-25", "supported": ["2025-11-25"],
         "negotiated": "2025-11-25"}, ["TOKEN"])
    stack = Stack(tmp_path, probe_runner=lambda canonical, **kwargs: dict(facts),
                  host_ports={"permission.probe_authority": AllowProbeAuthority()})
    seed(stack, definition=stdio_definition(name="demo"))
    save_result = stack.call(
        "mcp.saveRevision", serverScope="s1", principal="alice",
        definitionId="demo2", definition=stdio_definition(name="demo2"),
        expectedVersion=0, operationKey="op2")
    results = {
        "listDefinitions": stack.call("mcp.list", serverScope="s1", principal="alice"),
        "getDefinition": stack.call("mcp.get", serverScope="s1", principal="alice",
                                    definitionId="demo"),
        "saveRevision": save_result,
        "approveRevision": stack.call("mcp.approveRevision", serverScope="s1",
                                      principal="alice", definitionId="demo2",
                                      revision=1),
        "archiveDefinition": stack.call("mcp.archive", serverScope="s1",
                                        principal="alice", definitionId="demo2"),
        "probe": stack.call("mcp.probe", serverScope="s1", principal="alice",
                            definitionId="demo", revision=1),
        "assign": stack.call("mcp.assign", serverScope="s1", principal="alice",
                             scopeKind="user-default", scopeId="u1",
                             definitionId="demo", decision="disable",
                             expectedRowVersion=0, operationKey="op-a"),
        "unassign": stack.call("mcp.unassign", serverScope="s1", principal="alice",
                               scopeKind="user-default", scopeId="u1",
                               definitionId="demo", expectedRowVersion=1,
                               operationKey="op-u"),
        "resolvePreview": stack.call("mcp.resolvePreview", serverScope="s1",
                                     principal="alice"),
    }
    return results


# -- WCG cells --------------------------------------------------------------------

def test_wcg01_method_set_equality_against_registered_drift_ledger(ts_tables,
                                                                   descriptor_shapes):
    """WCG-01: the binding table and the registration face stay a registered set."""
    ts_ids = set(ts_tables[0].values())
    drift = check_method_sets(ts_ids, set(descriptor_shapes), TS_RENAMES,
                              BACKEND_UNFRONTED)
    assert drift == [], "\n".join(drift)


def test_wcg02_ts_request_bodies_within_registered_param_shapes(
        ts_tables, descriptor_shapes, ts_returns):
    """WCG-02: TS body fields vs required∪optional, both directions pinned."""
    table, bodies = ts_tables[0], ts_tables[1]
    shapes = {}
    for key, ts_id in table.items():
        shapes[key] = descriptor_shapes[TS_RENAMES.get(ts_id, ts_id)]
    drift = check_param_shapes(bodies, shapes, PARAM_EXTRA_GAPS,
                               PARAM_MISSING_REQUIRED)
    assert drift == [], "\n".join(drift)


def test_wcg03_ts_answer_contract_vs_real_roundtrip_keys(ts_returns, dto_fields,
                                                          roundtrip_results):
    """WCG-03: TS response fields sampled against live dispatch answers."""
    drift = check_responses(ts_returns, dto_fields, roundtrip_results,
                            RESPONSE_LEDGER, NOT_SAMPLED)
    assert drift == [], "\n".join(drift)


def test_wcg04_scope_kind_value_domains_are_the_aligned_pair(wire_text):
    """WCG-04: TS's scopeKind union equals the backend's accepted kinds.

    The 012 consolidation aligned the TS union to the backend vocabulary and
    the 016 CMP reconciliation pinned the ALIGNED pair here; any one-sided
    move re-breaks the equality and turns this cell red (the original drift
    pair and its live witness live in the git history of this ledger and in
    test_wcg04b, which keeps pinning the backend wall itself).
    """
    ts_union = parse_ts_union(wire_text, "scopeKind")
    backend_kinds = parse_backend_tuple(
        (PACKAGE_ROOT / "backend" / "assignment.py").read_text(encoding="utf-8"),
        "SCOPE_KINDS")
    assert ts_union == frozenset(VALUE_DOMAINS["ts"]), sorted(ts_union)
    assert backend_kinds == frozenset(VALUE_DOMAINS["backend"]), sorted(backend_kinds)
    assert ts_union == backend_kinds, \
        "scope kinds drifted apart — re-adjudicate the ledger"


def test_wcg04b_out_of_vocabulary_scope_kind_is_a_typed_live_refusal(tmp_path):
    """WCG-04b: the backend scope-kind wall, witnessed live. The TS union can
    no longer even spell `'user'` (type-level), so this cell pins the run-level
    wall for every non-TS caller that invents a value."""
    stack = Stack(tmp_path)
    seed(stack)
    stack.expect_refusal("mcp.assign", family="INVALID_REQUEST",
                         internal_code="MCP_ASSIGNMENT_INVALID",
                         serverScope="s1", principal="alice", scopeKind="user",
                         scopeId="u1", definitionId="demo", decision="disable",
                         expectedRowVersion=0, operationKey="op-x")


def test_wcg03b_unwrap_path_table_matches_the_sampled_ledger(wire_text):
    """WCG-03b: the wire.ts ``MCP_WIRE_RESULT_PATH`` table (parsed from source)
    equals the ledger's answer paths for every sampled row — a moved unwrap
    path on either side is named, not absorbed. (The ledger's sampling syntax
    may append an ``[i]`` element index the wire table does not carry; the
    comparison strips it.)"""
    paths = parse_result_paths(wire_text)
    for key, (path, _top, _gaps, _extras) in RESPONSE_LEDGER.items():
        table_path = re.sub(r"\[\d+\]$", "", path)
        assert paths.get(key) == table_path, \
            f"{key}: wire.ts unwraps {paths.get(key)!r}, ledger pins {table_path!r}"
    for key in NOT_SAMPLED:
        assert key in paths, f"{key}: no unwrap path pinned for a not-sampled row"


def test_wcg05_guard_is_not_vacuous_synthetic_drift_turns_each_layer_red(
        descriptor_shapes):
    """WCG-05 anti-vacuity twin: each layer names the symbol it detects."""
    # 1. a renamed ts id that neither matches a descriptor nor the ledger
    drift = check_method_sets({"mcp.list", "mcp.movedAway"},
                              {"mcp.list", "mcp.planForSubmission"},
                              TS_RENAMES, BACKEND_UNFRONTED)
    assert any("mcp.movedAway" in line for line in drift), drift
    # 2. a registered rename whose ts side has moved away is called stale
    drift = check_method_sets({"mcp.probe"},
                              {"mcp.probe", "mcp.planForSubmission"},
                              {"mcp.gone": "mcp.other"}, BACKEND_UNFRONTED)
    assert any("mcp.gone" in line and "stale" in line for line in drift), drift
    # 3. an unregistered extra body field and a newly required param
    shapes = {"probe": (frozenset({"serverScope", "principal", "definitionId",
                                   "revision"}), frozenset({"requestId"}))}
    drift = check_param_shapes({"probe": frozenset({"definitionId", "revision",
                                                    "serverScope", "principal",
                                                    "sneakyNew"})},
                               shapes, {"probe": frozenset()}, {"probe": frozenset()})
    assert any("sneakyNew" in line for line in drift), drift
    drift = check_param_shapes({"probe": frozenset({"definitionId", "revision",
                                                    "serverScope", "principal"})},
                               {"probe": (frozenset({"revision", "brandRequired",
                                                     "serverScope", "principal"}),
                                          frozenset())},
                               PARAM_EXTRA_GAPS, {"probe": frozenset()})
    assert any("brandRequired" in line for line in drift), drift
    # 4. a service-side rename of a sampled answer key moves both gap sides
    ledger = {"probe": ("probe", {"definitionId", "revision", "probe"},
                        frozenset(), {"negotiation"})}
    dto_map = {"McpProbeFacts": parse_interface_field_names(
        DTO_TS.read_text(encoding="utf-8"), "McpProbeFacts")}
    results = {"probe": {"definitionId": "d", "revision": 1,
                         "probe": {"status": "ok", "transport": "stdio",
                                   "evidence": "x", "serverInfo": {},
                                   "protocolVersion": "p", "negotiation": {},
                                   "credentialScope": "unproven",
                                   "credentialsExcluded": [], "proves": [],
                                   "doesNotProve": [], "renamedOnBackend": True}}}
    drift = check_responses({"probe": "McpProbeFacts"}, dto_map,
                            results, ledger, {})
    assert any("probe" in line and "renamedOnBackend" in line for line in drift), drift
    # 5. a TS method added outside the sampled/not-sampled partition
    drift = check_responses({"probe": "McpProbeFacts", "newThing": "McpNewDto"},
                            dto_map, {"probe": results["probe"], "newThing": {}},
                            ledger, NOT_SAMPLED)
    assert any("partition" in line and "newThing" in line for line in drift), drift
    # 6. a moved NOT_SAMPLED return type is named
    drift = check_responses({"probe": "McpProbeFacts",
                             "inspectConnection": "MovedAwayFacts",
                             "listTools": "McpCatalogFacts"},
                            dto_map, {"probe": results["probe"]}, ledger, NOT_SAMPLED)
    assert any("inspectConnection" in line for line in drift), drift


def test_wcg06_binding_table_row_count_and_ids_are_the_parsed_snapshot(ts_tables):
    """WCG-06: the parse itself is pinned (no silent table shrink/growth)."""
    table = ts_tables[0]
    assert sorted(table) == ["approveRevision", "archiveDefinition", "assign",
                             "getDefinition", "inspectConnection", "listDefinitions",
                             "listTools", "probe", "resolvePreview", "saveRevision",
                             "unassign"], sorted(table)
    assert all(ts_id.startswith("mcp.") for ts_id in table.values()), table
