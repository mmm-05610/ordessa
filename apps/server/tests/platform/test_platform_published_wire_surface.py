"""T014-S2c: host and plugins resolve through ONE published implementation.

The slice moved the shared wire vocabulary out of the host
(`ordessa_server.errors`, `.records`, `.wire.errors`, `.wire.handlers`,
`.wire.projection`) into `server_plugin_api` and the plugin that owns each
behaviour. Two failure modes stay possible after a move like that, and both are
gated here rather than assumed away:

1. a *copy* instead of a move — the host keeps its own version of a helper, the
   plugin imports the published one, and the frozen strings drift apart; the
   identity assertions below fail on a copy;
2. the behaviour quietly disappearing — the domain projectors and validators
   are still reached over the real wire by
   `test_wire_seq_numbering_spaces_128`, `test_profiles_list_sendability_117`,
   `test_workspace_connection_reserved_145`, `test_typed_code_live_leg_135`,
   `test_terminal_reason_consumer_134` and the 147 asset gates, which now read
   the plugin homes; the string pins here cover the refusals those paths do
   not all by themselves.

The counterexamples are mechanical: re-bind a host name to a local copy, or
delete a published refusal, and the named gate goes red.
"""
from __future__ import annotations

import pytest

import ordessa_server.errors as host_errors
import ordessa_server.records as host_records
import ordessa_server.wire.errors as host_wire_errors
import ordessa_server.wire.handlers as host_wire_handlers
import ordessa_server_compat.wire_projection as compat_projection
import ordessa_server_compat.wire_validators as compat_validators
import ordessa_workspace.wire_projection as workspace_projection
import server_plugin_api as api
from ordessa_server.wire.errors import WireError


def test_the_host_and_the_contract_share_one_error_implementation():
    assert host_errors.ServerError is api.ServerError
    assert host_errors.unavailable is api.unavailable
    assert host_records.canonical is api.canonical
    assert host_records.digest is api.digest
    assert host_records.reject_sensitive_keys is api.reject_sensitive_keys
    assert host_wire_errors.WireError is api.WireError
    assert host_wire_errors.FAMILIES is api.FAMILIES
    assert host_wire_errors.STATIC_ERROR_FAMILIES is api.STATIC_ERROR_FAMILIES
    assert host_wire_errors.family_for is api.family_for
    assert host_wire_errors.converge_family is api.converge_family


def test_the_host_dispatch_wall_uses_the_published_shape_primitives():
    """A local re-implementation in `wire/handlers.py` would be a second truth
    for the frozen refusal bytes; the host imports the published callables."""
    assert host_wire_handlers._require is api.require
    assert host_wire_handlers._bounded is api.bounded
    assert host_wire_handlers._request_id is api.request_id
    for name in ("_models", "_assignments", "_overrides", "_positive", "_slug"):
        assert not hasattr(host_wire_handlers, name), (
            f"{name} is compat's own shape and must not live in the host")


def test_the_domain_validators_live_with_the_domain_that_raises_them():
    with pytest.raises(WireError) as caught:
        compat_validators.models("not-a-list")
    assert (caught.value.family, caught.value.message) == (
        "INVALID_REQUEST", "models must be a list")
    with pytest.raises(WireError) as caught:
        compat_validators.models([{"modelId": "m"}])
    assert caught.value.message == "each model has an invalid shape"
    with pytest.raises(WireError) as caught:
        compat_validators.models([{"modelId": "m", "displayName": "M",
                                   "availability": "sometimes",
                                   "unavailableReason": None}])
    assert caught.value.message == "model availability is invalid"
    with pytest.raises(WireError) as caught:
        compat_validators.models([{"modelId": "m", "displayName": "M",
                                   "availability": "unknown",
                                   "unavailableReason": 7}])
    assert caught.value.message == "unavailableReason must be a string or null"
    with pytest.raises(WireError) as caught:
        compat_validators.overrides({"overrides": "not-a-list"})
    assert caught.value.message == "overrides must be a list of control assignments"
    assert compat_validators.overrides({}) is None
    assert compat_validators.overrides({"overrides": None}) is None
    with pytest.raises(WireError) as caught:
        compat_validators.assignments("not-a-list", "values")
    assert caught.value.message == "values must be a list of control assignments"
    assert compat_validators.assignments([{"controlId": "model", "value": "m"}],
                                         "values") == [{"controlId": "model", "value": "m"}]
    with pytest.raises(WireError) as caught:
        compat_validators.positive(0, "limit")
    assert caught.value.message == "limit must be a positive integer"
    with pytest.raises(WireError) as caught:
        compat_validators.slug("Upper", "harness")
    assert caught.value.message == "harness must be a lowercase slug"
    # A published primitive still refuses the same way through the domain copy.
    assert compat_validators.models([{"modelId": "m", "displayName": "M",
                                      "availability": "unknown",
                                      "unavailableReason": None}])[0]["modelId"] == "m"


def test_the_projectors_are_at_home_in_the_domain_that_owns_the_row():
    class _Codec:
        def encode(self, session_id, seq):
            return f"cursor:{session_id}:{seq}"

    frame = compat_projection.event_frame({
        "event_id": "e1", "session_id": "s1", "seq": 3, "kind": "message.delta",
        "data_json": '{"text":"hi"}', "created_at": "t",
    }, codec=_Codec())
    assert frame["event"] == {"kind": "message.delta", "sessionId": "s1",
                              "messageId": "message", "text": "hi", "role": "assistant"}
    assert frame["cursor"] == "cursor:s1:3"
    assert compat_projection.execution_state({"state": "capturing"}) == {"state": "running"}
    # The set is the projection module's own fact (145's reservation included).
    assert len(compat_projection.WIRE_EVENT_KINDS) == 13
    assert "workspace.connection" in compat_projection.WIRE_EVENT_KINDS
    assert compat_projection._EVENT_KIND_MAP["turn.state"] == "execution.state"
    row = {
        "id": "w1", "version": 2, "display_name": "Proj", "normalized_path": "/p",
        "env_kind": "ssh", "env_host": "h", "remote_user": "u",
        "connection_state": "verified", "created_at": "c", "updated_at": "u",
    }
    assert workspace_projection.workspace_record(row)["environment"] == {
        "kind": "ssh", "host": "h", "user": "u"}
    assert workspace_projection.workspace_record(row)["accessibility"]["readable"] is True
    unverified = dict(row, connection_state="pending")
    assert workspace_projection.workspace_record(unverified)["accessibility"] == {
        "readable": False, "writable": False, "executableForRole": None,
        "reasons": ["connection_state_unverified"]}
    assert compat_projection.profile_record({
        "id": "p1", "harness_type": "alpha", "created_at": "c", "updated_at": "u",
    })["recoveryPending"] is None
    assert compat_projection._tri_state({"recovery_pending": 1}, "recovery_pending") is True


def test_a_standin_for_the_injected_resolver_is_visible_in_the_wire_answer(tmp_path):
    """The compat surface converts with a resolver it was *given* (S2c).

    Replacing the injected callable with the static one is the defect this
    pins away: a workspace-owned code would answer `UNAVAILABLE` again while
    the composition actually knows its family.
    """
    from ordessa_server.bootstrap import build_runtime

    runtime = build_runtime(tmp_path / "data")
    try:
        handlers = runtime.plugin_host.provided_port("compat.handlers")
        handlers._family_resolver = api.family_for
        assert handlers._family_for("LOCAL_PATH_MISSING") == "UNAVAILABLE"
        handlers._family_resolver = None
        assert handlers._family_for("CATALOG_INVALID") == "INVALID_REQUEST"
        assert handlers._family_for("LOCAL_PATH_MISSING") == "UNAVAILABLE"
    finally:
        runtime.stop()
        fresh = build_runtime(tmp_path / "data-2")
        try:
            composed = fresh.plugin_host.provided_port("compat.handlers")
            assert composed._family_for("LOCAL_PATH_MISSING") == "NOT_FOUND"
        finally:
            fresh.stop()
