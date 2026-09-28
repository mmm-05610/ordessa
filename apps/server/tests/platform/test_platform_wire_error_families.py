"""T014-S2a: the wire/1 error-family table is split by owner, not copied.
T014-S2a-R: the contributed half is COMPOSITION state, not module state.

`ordessa_server.wire.errors` keeps the host's own vocabulary and the closed
twelve-family set; the business rows live with the plugin that raises them —
31+1 in `ordessa_server_compat.error_families` (compat-only codes plus
PROFILE_NOT_FOUND) and 10 in `ordessa_workspace.error_families` (environment,
local-path, sandbox and connector-absence codes) — and arrive at the host's
wire/1 surface through the open `wire.error-families` contribution point.
S2a-R moved the aggregate itself: every `ServerPluginHost` owns one
`ErrorFamilyAggregate` (built at host construction), the point's handler
mutates only that host's state, and consumers resolve through the composition
they were built for — the composition root hands `host.wire_error_families.
family_for` to the transport at construction, the `harness_resolver` shape.
The module-level `family_for` answers the static table only. These gates pin
the promises the slices trade behaviour money on:

1. **Byte-identical golden answers, proven through a real composition.**
   Every row of the pre-split table (the literal below, recovered from the
   unmodified base with `git show 42f747c2de:apps/server/src/ordessa_server/
   wire/errors.py`) still answers the same family through the composed
   default product's OWN aggregate — the split moved storage, not behaviour.
2. **Plugin-absent honesty, per composition.** With a composition holding
   neither producing plugin, its codes answer the documented `UNAVAILABLE`
   fall-through — and a second composition in the same process cannot leak
   rows into it (the asymmetry gate). The host carries no hidden copy — the
   partition test asserts the tables tile the historical table exactly, so
   a row cannot live in both.
3. **Multi-owner aggregation without activation-order picks.** Same code +
   same family coalesces and survives either owner's retirement; same code +
   different families — across owners, against a host row, or inside one
   still-staging round — refuses the batch loudly at stage time, and the
   host's round rollback leaves nothing behind (validate-or-undo, FR-005).

The bare-host gates use `contribution_fakes.new_host()`, which since S2a
pre-declares exactly one real point — the host's own wire/1 seam — because
the handler under test is the production one (now per-host, so two hosts
built in one test never share a row).
"""
from __future__ import annotations

import pytest

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
)

from contribution_fakes import ContribPlugin, new_host

from ordessa_server.bootstrap import build_runtime
from ordessa_server.wire.errors import (
    STATIC_ERROR_FAMILIES,
    ErrorFamilyContributionRefused,
)
# T014-S2c: the static half of the table is the published contract's, which the
# host re-exports; this gate reads the contract object itself.
from server_plugin_api import FAMILIES, family_for
from ordessa_server_compat.error_families import COMPAT_ERROR_FAMILIES
from ordessa_workspace.error_families import WORKSPACE_ERROR_FAMILIES


# The full `STATIC_ERROR_FAMILIES` of the pre-split host table, recovered verbatim from the
# unmodified base (git show 42f747c2de:apps/server/src/ordessa_server/wire/
# errors.py). This literal is the golden: the slice may re-home rows and add
# machinery, but no code below may answer a different family than it did
# here on the composed default product.
HISTORICAL_BY_CODE: dict[str, str] = {
    "IDEMPOTENCY_CONFLICT": "CONFLICT_REQUEST",
    "ENTERPRISE_STATE_CONFLICT": "CONFLICT_REQUEST",
    "PROFILE_REVISION_CONFLICT": "CONFLICT_VERSION",
    "RECORD_VERSION_CONFLICT": "CONFLICT_VERSION",
    "QUEUE_VERSION_CONFLICT": "CONFLICT_VERSION",
    "APPROVAL_VERSION_CONFLICT": "CONFLICT_VERSION",
    "REFERENCE_CONFLICT": "CONFLICT_REFERENCE",
    "APPROVAL_INVALID": "APPROVAL_INVALID",
    "APPROVAL_STALE": "APPROVAL_INVALID",
    "APPROVAL_EXPIRED": "APPROVAL_INVALID",
    "WORKSPACE_NOT_FOUND": "NOT_FOUND",
    "PROFILE_NOT_FOUND": "NOT_FOUND",
    "SESSION_NOT_FOUND": "NOT_FOUND",
    "TURN_NOT_FOUND": "NOT_FOUND",
    "QUEUE_ITEM_NOT_FOUND": "NOT_FOUND",
    "APPROVAL_NOT_FOUND": "NOT_FOUND",
    "CREDENTIAL_NOT_FOUND": "NOT_FOUND",
    "PROVIDER_MODEL_NOT_FOUND": "NOT_FOUND",
    "REQUEST_INVALID": "INVALID_REQUEST",
    "REQUEST_TOO_LARGE": "INVALID_REQUEST",
    "SECRET_FIELD_FORBIDDEN": "INVALID_REQUEST",
    "PROFILE_CONFIGURATION_INVALID": "INVALID_REQUEST",
    "TURN_OVERRIDES_INVALID": "INVALID_REQUEST",
    "ENVIRONMENT_INVALID": "INVALID_REQUEST",
    "LOCAL_PATH_INVALID": "INVALID_REQUEST",
    "LOCAL_PATH_NOT_DIRECTORY": "INVALID_REQUEST",
    "LOCAL_PATH_MISSING": "NOT_FOUND",
    "LOCAL_PATH_NOT_READABLE": "FORBIDDEN",
    "LOCAL_PATH_FORBIDDEN": "FORBIDDEN",
    "SSH_TARGET_INVALID": "INVALID_REQUEST",
    "SSH_IDENTITY_INVALID": "INVALID_REQUEST",
    "ATTACHMENT_INVALID": "INVALID_REQUEST",
    "AUTHENTICATION_REQUIRED": "UNAUTHENTICATED",
    "LOOPBACK_POLICY_REJECTED": "FORBIDDEN",
    "CAPABILITY_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "HARNESS_UNAVAILABLE": "CAPABILITY_UNSUPPORTED",
    "EXECUTION_CAPABILITY_UNAVAILABLE": "UNAVAILABLE",
    "WSL_CONNECTOR_UNAVAILABLE": "UNAVAILABLE",
    "SSH_CONNECTOR_UNAVAILABLE": "UNAVAILABLE",
    "SSH_WORKER_UNAVAILABLE": "UNAVAILABLE",
    "SSH_WORKER_DIGEST_MISMATCH": "UNAVAILABLE",
    "SSH_UNREACHABLE": "WORKER_UNREACHABLE",
    "LOCAL_SANDBOX_UNAVAILABLE": "UNAVAILABLE",
    "LOCAL_PATH_UNAVAILABLE": "UNAVAILABLE",
    "CREDENTIAL_SOURCE_NOT_AUTHORIZED": "UNAVAILABLE",
    "SERVICE_UNAVAILABLE": "UNAVAILABLE",
    "WORKER_DISCONNECTED": "WORKER_UNREACHABLE",
    "WORKER_UNREACHABLE": "WORKER_UNREACHABLE",
    "DISPATCH_AMBIGUOUS": "OUTCOME_UNKNOWN",
    "OUTCOME_UNKNOWN": "OUTCOME_UNKNOWN",
    "QUEUE_ITEM_TOO_LATE": "CONFLICT_REQUEST",
    "PROFILE_RECOVERY_REQUIRED": "CONFLICT_REQUEST",
    "PROFILE_ARCHIVED": "CONFLICT_REQUEST",
    "SESSION_ARCHIVED": "CONFLICT_REQUEST",
    "WORKSPACE_ARCHIVED": "CONFLICT_REQUEST",
    "TURN_CONCURRENCY_CONFLICT": "CONFLICT_REQUEST",
    "PROFILE_HARNESS_MISMATCH": "CONFLICT_REQUEST",
    "SESSION_STORE_GUARD_UNAVAILABLE": "CONFLICT_REQUEST",
    "SESSION_STORE_CREDENTIALS_PRESENT": "CONFLICT_REQUEST",
    "SESSION_STORE_GUARD_STRUCTURE": "CONFLICT_REQUEST",
    "SESSION_BUSY": "CONFLICT_REQUEST",
    "EVENT_CURSOR_AHEAD": "INVALID_REQUEST",
    "EVENT_CURSOR_EXPIRED": "INVALID_REQUEST",
    "CATALOG_INVALID": "INVALID_REQUEST",
    "CATALOG_SOURCE_MISSING": "INVALID_REQUEST",
    "CATALOG_ORIGIN_MISSING": "INVALID_REQUEST",
    "CATALOG_ENTRY_UNKNOWN": "INVALID_REQUEST",
}

# The rows S2a/S2a-R moved out of the host table, by producing plugin:
# 31 compat-only codes plus PROFILE_NOT_FOUND (compat-produced, harness-
# named), the 10 rows S2a-R re-homed to the workspace domain after the
# raise-site audit, and — since T014-S2b — the two SSH connector target/
# identity rows, which moved with the connector CONSTRUCTION into the
# workspace plugin (see workspace's error_families module docstring for
# the line-number proof).
MOVED_FROM_COMPAT = set(COMPAT_ERROR_FAMILIES)
MOVED_FROM_WORKSPACE = set(WORKSPACE_ERROR_FAMILIES)
MOVED_CODES = MOVED_FROM_COMPAT | MOVED_FROM_WORKSPACE


def _wire_point(payload) -> Contribution:
    return Contribution(point_id=WIRE_ERROR_FAMILIES_POINT_ID,
                        api_version=WIRE_ERROR_FAMILIES_API_VERSION,
                        payload=payload)


# -- 1. byte-identical golden answers on the composed product ----------------


def test_every_historical_row_still_answers_its_family_on_the_default_product(tmp_path):
    """The table-driven golden: 67 codes, one composed product, zero drift.

    Asserted through the composition's OWN aggregate accessor (the object
    the transport was handed at construction), not through a module-level
    lookup — S2a-R made the contributed half per-host state, and the golden
    must be proven where the behaviour actually lives. Asserted as a
    mismatch list so one moved row names itself and its two answers, instead
    of sixty-six passing tests hiding a sixty-seventh.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        assert runtime.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp",
            "ordessa.sandbox", "ordessa.sandbox-adapters",
            "ordessa.permissions-adapters")
        composed = runtime.plugin_host.wire_error_families.family_for
        drifted = {
            code: (expected, composed(code))
            for code, expected in HISTORICAL_BY_CODE.items()
            if composed(code) != expected
        }
        assert drifted == {}
    finally:
        runtime.stop()


def test_the_tables_tile_the_historical_rows_exactly():
    """No row lost, no row invented, and no row living in both places.

    The host table plus the two plugin contributions, keyed-merged, must
    equal the golden literal — and no contributed code may still sit in the
    host table. This is the structural half of "byte-identical": the
    live-composition test above cannot tell a host copy from a contribution,
    this one can.
    """
    merged = {**STATIC_ERROR_FAMILIES, **dict(COMPAT_ERROR_FAMILIES), **dict(WORKSPACE_ERROR_FAMILIES)}
    assert merged == HISTORICAL_BY_CODE
    overlap = set(STATIC_ERROR_FAMILIES) & MOVED_CODES
    assert overlap == set()
    # The two plugin tables never claim one code twice (S2a-R's move kept
    # them disjoint; a future co-publish would be legal aggregation — same
    # family, two owners — but the tile test tracks it deliberately).
    assert MOVED_FROM_COMPAT & MOVED_FROM_WORKSPACE == set()
    # The compat table is exactly the moved set: 31 compat-only codes plus
    # PROFILE_NOT_FOUND (compat-produced, harness-named).
    assert len(COMPAT_ERROR_FAMILIES) == 32
    assert "PROFILE_NOT_FOUND" in MOVED_FROM_COMPAT
    assert "SECRET_FIELD_FORBIDDEN" not in MOVED_FROM_COMPAT
    assert "CAPABILITY_UNSUPPORTED" not in MOVED_FROM_COMPAT
    # S2a-R: the workspace rows. T014-S2b moved the two SSH connector
    # target/identity rows here with the connector construction (the host
    # builds no connector any more), leaving the worker-failure rows
    # (`SSH_WORKER_*`, `SSH_UNREACHABLE`) static: they name the connector
    # implementation's remote-worker vocabulary, not a workspace decision.
    assert len(WORKSPACE_ERROR_FAMILIES) == 12
    assert "ENVIRONMENT_INVALID" in MOVED_FROM_WORKSPACE
    assert "WSL_CONNECTOR_UNAVAILABLE" in MOVED_FROM_WORKSPACE
    assert "SSH_TARGET_INVALID" in MOVED_FROM_WORKSPACE
    assert "SSH_IDENTITY_INVALID" in MOVED_FROM_WORKSPACE
    assert "SSH_TARGET_INVALID" not in STATIC_ERROR_FAMILIES
    assert "SSH_IDENTITY_INVALID" not in STATIC_ERROR_FAMILIES


# -- 2. plugin-absent honesty ------------------------------------------------


def test_without_the_plugins_their_codes_answer_the_typed_fallthrough(tmp_path):
    """No hidden copy in the host: strip the producers and their rows are gone.

    Every moved code then answers `UNAVAILABLE` through the bare
    composition's accessor — the documented fall-through for an unregistered
    code, which is the honest typed absence a product without the producer
    must give (and the reason codes never travel to a plugin that does not
    raise them).
    """
    runtime = build_runtime(tmp_path / "data", server_plugins=())
    try:
        assert runtime.plugin_host.active_ids() == ()
        composed = runtime.plugin_host.wire_error_families
        assert composed.contributed_families() == {}
        # One moved row (OUTCOME_UNKNOWN) is also a family NAME, so the
        # family-name lookup rule answers it identically with or without the
        # contribution — the golden answer is preserved by a different rule,
        # which is still honest absence (no row, no host copy).
        family_named = {c for c in MOVED_CODES if c in FAMILIES}
        assert family_named == {"OUTCOME_UNKNOWN"}
        unanswered = sorted(
            code for code in MOVED_CODES - family_named
            if composed.family_for(code) != "UNAVAILABLE")
        assert unanswered == []
        # Host-owned rows are untouched by the composition: they are the
        # transport/kernel vocabulary, not contributions.
        assert composed.family_for("REQUEST_INVALID") == "INVALID_REQUEST"
    finally:
        runtime.stop()


def test_retiring_the_owner_takes_its_rows_out_of_that_composition(tmp_path):
    """Published rows live and die with their owner inside one composition.

    `runtime.stop()` deactivates compat; the C2 rollback path must remove
    exactly its mapping from THAT host's aggregate. After the stop the moved
    codes answer the same fall-through the no-compat composition answers — a
    retired round leaves no residue behind.
    """
    runtime = build_runtime(tmp_path / "data")
    composed = runtime.plugin_host.wire_error_families
    assert composed.family_for("SESSION_NOT_FOUND") == "NOT_FOUND"
    assert "SESSION_NOT_FOUND" in composed.contributed_families()
    runtime.stop()
    assert composed.contributed_families() == {}
    assert composed.family_for("SESSION_NOT_FOUND") == "UNAVAILABLE"


def test_two_live_compositions_answer_each_other_nothing(tmp_path):
    """S2a-R's defect, gated: the aggregate is per-host, never process state.

    Host A composes the default product; host B is composed bare (`server_
    plugins=()`) WHILE A is live. B has zero active plugins and zero
    producers, so B's accessor must answer A's business rows through the
    fall-through — and the module-level `family_for`, which now reads only
    the static table, must never answer a contributed family for anybody.
    The asymmetry (B composed second, A publishing identical rows to nothing
    shared) is exactly what the first cut got wrong.
    """
    a = build_runtime(tmp_path / "full")
    b = build_runtime(tmp_path / "bare-while-a-live", server_plugins=())
    try:
        assert a.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp",
            "ordessa.sandbox", "ordessa.sandbox-adapters",
            "ordessa.permissions-adapters")
        assert b.plugin_host.active_ids() == ()
        assert b.plugin_host.wire_error_families is not a.plugin_host.wire_error_families
        # A resolves its own rows...
        assert a.plugin_host.wire_error_families.family_for("SESSION_NOT_FOUND") == "NOT_FOUND"
        assert a.plugin_host.wire_error_families.family_for("LOCAL_PATH_MISSING") == "NOT_FOUND"
        # ...B resolves nothing of A's: typed fall-through, both plugins' rows.
        for code in ("SESSION_NOT_FOUND", "LOCAL_PATH_MISSING", "ENVIRONMENT_INVALID",
                     "CATALOG_INVALID", "WSL_CONNECTOR_UNAVAILABLE"):
            assert b.plugin_host.wire_error_families.family_for(code) == "UNAVAILABLE", code
        assert b.plugin_host.wire_error_families.contributed_families() == {}
        # And the module-level lookup answers the static table only — even
        # for a code A has published, and even in a process with no
        # composition at all.
        assert family_for("SESSION_NOT_FOUND") == "UNAVAILABLE"
        assert family_for("REQUEST_INVALID") == "INVALID_REQUEST"
        # The transports were each handed their OWN composition's accessor:
        # B's dispatch of a host-row code still converges, and B converts a
        # contributed code exactly as a producer-less composition must.
        from ordessa_server.errors import ServerError
        from ordessa_server.wire.errors import WireError
        converted = WireError.from_server_error(
            ServerError("SESSION_NOT_FOUND", "gone", status=404),
            b.plugin_host.wire_error_families.family_for)
        assert converted.family == "UNAVAILABLE"
        converted_a = WireError.from_server_error(
            ServerError("SESSION_NOT_FOUND", "gone", status=404),
            a.plugin_host.wire_error_families.family_for)
        assert converted_a.family == "NOT_FOUND"
    finally:
        b.stop()
        a.stop()


def test_the_fallthrough_and_family_names_keep_answering_as_before():
    """The two lookup rules that are not rows: unknown codes and family names.

    `family_for` on an unregistered code is `UNAVAILABLE`, and a code that IS
    a family name answers itself (the historical table relied on both; the
    split must not have nudged either). Both rules are the static module
    lookup's own behaviour, independent of any composition.
    """
    assert family_for("SOMETHING_UNREGISTERED") == "UNAVAILABLE"
    self_answering = {f for f in FAMILIES if family_for(f) != f}
    assert self_answering == set()
    # S2a-R: the module lookup reads NO contributed state, ever — a static
    # table is a static table even while the producer is published elsewhere.
    assert family_for("SESSION_NOT_FOUND") == "UNAVAILABLE"
    assert family_for("ENVIRONMENT_INVALID") == "UNAVAILABLE"


# -- 3. multi-owner aggregation on the bare host -----------------------------


def test_two_owners_publishing_the_same_family_coalesce_and_retire_apart():
    """Same code + same family is agreement, not conflict.

    Both owners answer the shared code; retiring one leaves the answer intact
    through the other; retiring both falls through. Aggregation is per-host:
    the assertions all run on THIS host's aggregate.
    """
    shared = {"TEST_SHARED_CODE": "NOT_FOUND"}
    host = new_host()
    host.activate_all([
        ContribPlugin("fake.coalesce.a", contributions=(_wire_point({
            **shared, "TEST_A_ONLY": "FORBIDDEN"}),)),
        ContribPlugin("fake.coalesce.b", contributions=(_wire_point(dict(shared)),)),
    ])
    try:
        assert host.wire_error_families.family_for("TEST_SHARED_CODE") == "NOT_FOUND"
        assert host.wire_error_families.family_for("TEST_A_ONLY") == "FORBIDDEN"
        assert host.wire_error_families.contributed_families()["TEST_SHARED_CODE"] == (
            "fake.coalesce.a", "fake.coalesce.b")
        host.deactivate("fake.coalesce.a")
        assert host.wire_error_families.family_for("TEST_SHARED_CODE") == "NOT_FOUND"
        assert host.wire_error_families.contributed_families() == {
            "TEST_SHARED_CODE": ("fake.coalesce.b",)}
        host.deactivate("fake.coalesce.b")
        assert host.wire_error_families.contributed_families() == {}
        assert host.wire_error_families.family_for("TEST_SHARED_CODE") == "UNAVAILABLE"
        assert host.wire_error_families.family_for("TEST_A_ONLY") == "UNAVAILABLE"
    finally:
        host.shutdown()


def test_a_second_host_shares_not_even_the_same_payload(tmp_path):
    """Two hosts publishing the IDENTICAL mapping stay independent.

    The retirement/coalesce gates above cannot see the process-global defect
    because both hosts' rows were the same object answering the same dict;
    this one retires one host and asserts the other still answers.
    """
    host_a = new_host()
    host_b = new_host()
    plugin_args = dict(contributions=(_wire_point({"TEST_SHARED_CODE": "NOT_FOUND"}),))
    host_a.activate_all([ContribPlugin("fake.shared", **plugin_args)])
    host_b.activate_all([ContribPlugin("fake.shared", **plugin_args)])
    try:
        host_a.shutdown()
        assert host_a.wire_error_families.contributed_families() == {}
        assert host_a.wire_error_families.family_for("TEST_SHARED_CODE") == "UNAVAILABLE"
        # B was never touched by A's teardown — the payload object is shared,
        # the state is not.
        assert host_b.wire_error_families.family_for("TEST_SHARED_CODE") == "NOT_FOUND"
    finally:
        host_b.shutdown()


def test_one_code_two_families_refuses_the_round_and_leaves_nothing_published():
    """Never a pick by activation order: disagreement kills the round, whole.

    The second owner's stage raises; the host's round rollback then undoes
    the FIRST owner's already-committed work too — its private row must be
    gone as loudly as the conflicting one, and both plugins must be out.
    """
    host = new_host()
    with pytest.raises(ErrorFamilyContributionRefused) as refusal:
        host.activate_all([
            ContribPlugin("fake.conflict.a", contributions=(_wire_point({
                "TEST_FIGHTING_CODE": "NOT_FOUND", "TEST_A_PRIVATE": "FORBIDDEN"}),)),
            ContribPlugin("fake.conflict.b", contributions=(_wire_point({
                "TEST_FIGHTING_CODE": "FORBIDDEN"}),)),
        ])
    assert "TEST_FIGHTING_CODE" in str(refusal.value)
    assert refusal.value.other_owner == "fake.conflict.a"
    assert host.active_ids() == ()
    assert host.wire_error_families.contributed_families() == {}
    assert host.wire_error_families.family_for("TEST_FIGHTING_CODE") == "UNAVAILABLE"
    assert host.wire_error_families.family_for("TEST_A_PRIVATE") == "UNAVAILABLE"


def test_a_staged_row_already_refuses_a_later_owner_even_though_consumers_cannot_see_it():
    """Half a round is not a value — but it IS a conflict witness.

    Plugin B builds while A's mapping is staged-unpublished: at that moment
    the composition's lookup must still fall through (no half-round
    visibility, asserted from inside the round against THIS host's
    aggregate), while B's own conflicting batch is refused against the
    staged row. The refusal message names A as the other owner.
    """
    seen_midround: list[str] = []
    host = new_host()

    def observe(_context):
        seen_midround.append(host.wire_error_families.family_for("TEST_ROUND_CODE"))

    with pytest.raises(ErrorFamilyContributionRefused) as refusal:
        host.activate_all([
            ContribPlugin("fake.stage.a", contributions=(_wire_point({
                "TEST_ROUND_CODE": "NOT_FOUND"}),)),
            ContribPlugin("fake.stage.b", observe=observe, contributions=(_wire_point({
                "TEST_ROUND_CODE": "INVALID_REQUEST"}),)),
        ])
    assert seen_midround == ["UNAVAILABLE"]
    assert refusal.value.other_owner == "fake.stage.a"
    assert host.wire_error_families.contributed_families() == {}
    assert host.wire_error_families.family_for("TEST_ROUND_CODE") == "UNAVAILABLE"


def test_contributing_a_family_the_host_row_already_owns_coalesces_but_contradicting_it_refuses():
    """Host rows join the same agreement rule: equal family coalesces, a
    different family is a refused batch, never a host-table override."""
    host = new_host()
    host.activate_all([ContribPlugin(
        "fake.agree", contributions=(_wire_point({"REQUEST_INVALID": "INVALID_REQUEST"}),))])
    try:
        assert host.wire_error_families.family_for("REQUEST_INVALID") == "INVALID_REQUEST"
        assert host.wire_error_families.contributed_families()["REQUEST_INVALID"] == ("fake.agree",)
    finally:
        host.shutdown()
    assert host.wire_error_families.contributed_families() == {}

    host = new_host()
    with pytest.raises(ErrorFamilyContributionRefused) as refusal:
        host.activate_all([ContribPlugin(
            "fake.contradict", contributions=(_wire_point(
                {"REQUEST_INVALID": "FORBIDDEN"}),))])
    assert refusal.value.other_owner is None  # the other source is a host row
    assert host.wire_error_families.family_for("REQUEST_INVALID") == "INVALID_REQUEST"  # host row intact
    assert "REQUEST_INVALID" not in host.wire_error_families.contributed_families()


@pytest.mark.parametrize("payload", [
    pytest.param({"TEST_GHOST": "NOT_A_WIRE_FAMILY"}, id="family-outside-closed-set"),
    pytest.param({"TEST_GHOST": 7}, id="family-not-a-string"),
    pytest.param({"": "NOT_FOUND"}, id="empty-code"),
    pytest.param({}, id="empty-payload"),
    pytest.param(["not", "a", "mapping"], id="payload-not-a-mapping"),
])
def test_a_malformed_error_family_payload_refuses_the_plugin_atomically(tmp_path, payload):
    """Shape checks fire at stage, so the whole activation is undone.

    A refused batch is not a warning: the plugin never becomes active, its
    methods never bind, and nothing of its partial mapping survives — the
    same validate-or-undo rule as the conflict gates, applied to garbage.
    """
    host = new_host()
    with pytest.raises(ErrorFamilyContributionRefused):
        host.activate_all([ContribPlugin(
            "fake.malformed", methods=("fake.malformed.method",),
            contributions=(_wire_point(payload),))])
    assert host.active_ids() == ()
    assert host.methods.lookup("fake.malformed.method") is None
    assert host.wire_error_families.contributed_families() == {}
    assert host.wire_error_families.family_for("TEST_GHOST") == "UNAVAILABLE"
    # And through the real composition root the same refusal is fatal to
    # startup, leaving no half-activated runtime behind.
    with pytest.raises(ErrorFamilyContributionRefused):
        build_runtime(tmp_path / "data", server_plugins=[ContribPlugin(
            "fake.malformed", contributions=(_wire_point(payload),))])


def test_the_point_is_open_and_carries_the_frozen_id_and_version():
    """The seam's public contract, pinned at the declaration, not in prose.

    `wire.error-families` v1 (spelled with the hyphen the frozen point-id
    grammar admits) is declared non-exclusive: several owners may hold it at
    once — that is the whole reason S2a does not use the scoped single-owner
    `contribution(consumer=)` path, whose ambiguity refusal would make two
    producers of one code a startup crash instead of a coalesce.
    """
    assert WIRE_ERROR_FAMILIES_POINT_ID == "wire.error-families"
    assert WIRE_ERROR_FAMILIES_API_VERSION == "v1"
    host = new_host()
    point = host.contribution_points.point(WIRE_ERROR_FAMILIES_POINT_ID)
    assert point is not None and point.exclusive is False
    # An open point held by nobody is honest absence, not an error: the
    # published view is empty and lookups answer the fall-through.
    assert host.contribution_points.published(WIRE_ERROR_FAMILIES_POINT_ID) == ()
    assert host.wire_error_families.family_for("SESSION_NOT_FOUND") == "UNAVAILABLE"
