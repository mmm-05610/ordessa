"""Core Profile and configuration semantics for PJ01/PJ05/PJ08/PJ12.

These tests use the existing SQLite/core fixtures and controlled owner ports.
They do not start provider processes or make model calls.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from ordessa_environment_api import (
    AdmissionRefusedError,
    IdentityMismatchError,
    RequestKey,
    UnknownResultError,
)
from pacthold.agents.configuration import (
    ApplicationPolicy,
    ConfigurationConversionRefused,
    ConfigurationOmissionRefused,
    ConfigurationRevisionConflict,
    ConfigurationUnsupported,
)
from pacthold.agents.contracts import ProfileRef
from pacthold.agents.management import CONFIGURATION_ATTEMPTS
from pacthold.agents.nodes import decode_node_ref
from pacthold.agents.profiles import ProfileCatalog
from pacthold.public import EnvironmentClosedError

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "products/agent-tools/tests/integration"))
from test_node_publication import setup as node_fixture, Provider as ManagementProvider  # noqa: F401
from test_assembly import assembly
from test_apply_profile import DECLARATION, DEFINITION, _base_ref, _profile
from test_management import setup as management_setup
from pacthold.agents.runtime import RUNTIME_METHODS


@pytest.fixture(autouse=True)
def explicit_management_capabilities(monkeypatch):
    monkeypatch.setattr(ManagementProvider, "descriptor",
                        replace(ManagementProvider.descriptor, supported_methods=RUNTIME_METHODS))


def _inline_manifest(assembly_parts, *, marker="inline"):
    provider = assembly_parts[3]
    return {
        "harnessDefinitionRef": dict(provider.descriptor.definition_ref),
        "schemaVersion": "1",
        "declarations": [],
        "metadata": {"marker": marker},
    }


def test_inline_prepare_uses_uncommitted_normalized_snapshot_and_same_request_replays_as_ref(assembly):
    coordinator, request, _, provider, store, nodes, *_ = assembly
    manifest = _inline_manifest(assembly)
    catalog = coordinator._profiles
    named_before = catalog.list()

    operation = coordinator.prepare(request, None, {}, {}, manifest)

    assert operation.status == "published"
    snapshot_ref = ProfileRef.from_dict(dict(operation.intent.profile_snapshot_ref))
    assert snapshot_ref.profile_id.startswith("snap-")
    assert store.list_domain("env", "agents.profile-snapshots")
    assert catalog.list() == named_before
    assert nodes.read(decode_node_ref(operation.intent.node_ref))["lineage"]["profileSnapshotRef"] == snapshot_ref.to_dict()
    assert provider.calls == ["prepare", "start"]

    replay = coordinator.prepare(request, snapshot_ref, {}, {})
    assert replay == operation
    assert provider.calls == ["prepare", "start"]


def test_inline_snapshot_and_operation_reservation_roll_back_together(assembly):
    coordinator, request, _, provider, store, nodes, *_ = assembly
    store._conn.execute(
        "CREATE TRIGGER reject_profile_snapshot BEFORE INSERT ON env_domain_records "
        "WHEN NEW.namespace='agents.profile-snapshots' BEGIN SELECT RAISE(ABORT,'snapshot write rejected'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        coordinator.prepare(request, None, {}, {}, _inline_manifest(assembly, marker="rollback"))

    assert store.read_operation(request) is None
    assert store.list_domain("env", "agents.profile-snapshots") == ()
    assert nodes.list() == ()
    assert provider.calls == []


class SnapshotAccessPolicy:
    def __init__(self, *, snapshot_read=True, snapshot_write=True):
        self.snapshot_read = snapshot_read
        self.snapshot_write = snapshot_write

    def admit_invoke(self, principal, surface, guarantee):
        return True

    def admit_object_access(self, principal, object_ref, mode):
        if ":agents.profile-snapshot:" in object_ref:
            return self.snapshot_write if mode == "write" else self.snapshot_read
        return True


def test_inline_snapshot_has_its_own_object_permission_for_write_and_read(assembly):
    coordinator, request, _, provider, store, _, *rest = assembly
    env = rest[4]
    policy = SnapshotAccessPolicy(snapshot_write=False)
    env._policy = policy

    with pytest.raises(AdmissionRefusedError):
        coordinator.prepare(request, None, {}, {}, _inline_manifest(assembly, marker="denied-write"))
    assert store.read_operation(request) is None
    assert provider.calls == []

    policy.snapshot_write = True
    operation = coordinator.prepare(request, None, {}, {}, _inline_manifest(assembly, marker="allowed"))
    ref = ProfileRef.from_dict(dict(operation.intent.profile_snapshot_ref))
    assert store.list_domain("env", "agents.profile-snapshots")

    policy.snapshot_read = False
    with pytest.raises(AdmissionRefusedError):
        ProfileCatalog(env).read(ref)


def test_inline_snapshot_read_denial_is_rejected_before_operation_or_native_call(assembly):
    coordinator, request, _, provider, store, nodes, *rest = assembly
    env = rest[4]
    env._policy = SnapshotAccessPolicy(snapshot_read=False, snapshot_write=True)

    with pytest.raises(AdmissionRefusedError):
        coordinator.prepare(request, None, {}, {}, _inline_manifest(assembly, marker="read-denied"))

    assert store.read_operation(request) is None
    assert store.list_domain("env", "agents.profile-snapshots") == ()
    assert nodes.list() == ()
    assert provider.calls == []


def test_stage_snapshot_checks_environment_open(assembly):
    coordinator, _, _, _, _, _, *rest = assembly
    env = rest[4]
    catalog = ProfileCatalog(env)
    env.close()

    with pytest.raises(EnvironmentClosedError):
        catalog.stage_snapshot(_inline_manifest(assembly, marker="closed"))


def test_no_change_replay_returns_original_receipt_after_owner_revision_moves(management_setup):
    store, _, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    request = RequestKey("env", "principal", "no-change-replay")
    first = coordinator.apply_profile(request, node, base, "native-1", ApplicationPolicy(), base_profile_ref=base)
    assert first.status == "refused"
    assert state["calls"] == 0

    state["revision"] = "external-2"
    replay = coordinator.apply_profile(request, node, base, "native-1", ApplicationPolicy(), base_profile_ref=base)

    assert replay == first
    assert store.read_operation(request) == first
    assert state["calls"] == 0


def test_standing_no_change_domain_receipt_replays_without_rechecking_owner(management_setup, monkeypatch):
    store, env, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    _, profile = _profile(management_setup, declarations=(
        {**DECLARATION, "payload": {"modelId": "new"}},
    ), name="standing-domain-replay")
    applied = coordinator.apply_profile(RequestKey("env", "principal", "apply-standing-domain"),
        node, profile.current_manifest_ref, "native-1", ApplicationPolicy(), base_profile_ref=base)
    assert applied.status == "published"

    request = RequestKey("env", "principal", "standing-domain-replay")
    first = coordinator.apply_profile(request, node, profile.current_manifest_ref, "native-2",
        ApplicationPolicy(), base_profile_ref=profile.current_manifest_ref)
    assert first == applied
    with pytest.raises(UnknownResultError):
        store.read_operation(request)
    row = store._conn.execute(
        "SELECT receipt FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
        ("env", "principal", request.request_id),
    ).fetchone()
    assert json.loads(row["receipt"])["domain_result"]["verified"] == "standing-operation"

    binding = coordinator._nodes.read(node)["binding"]
    provider = env.agent_runtime_contribution(binding["harnessDefinitionRef"]).provider
    monkeypatch.setattr(provider, "inspect_unit", lambda *_args, **_kwargs: pytest.fail("replay rechecked owner"))
    monkeypatch.setattr(provider, "inspect_configuration", lambda *_args, **_kwargs: pytest.fail("replay rechecked owner"))
    state.update(revision="external-after-receipt", model="external")
    replay = coordinator.apply_profile(request, node, profile.current_manifest_ref, "native-2",
        ApplicationPolicy(), base_profile_ref=profile.current_manifest_ref)

    assert replay == first
    assert state["calls"] == 1


def test_new_no_change_request_does_not_reuse_historical_applied_as_current_actual(management_setup):
    store, _, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    _, applied_profile = _profile(management_setup, declarations=(
        {**DECLARATION, "payload": {"modelId": "new"}},
    ), name="new-current-profile")
    applied = coordinator.apply_profile(RequestKey("env", "principal", "apply-current-profile"),
        node, applied_profile.current_manifest_ref, "native-1", ApplicationPolicy(), base_profile_ref=base)
    assert applied.status == "published"

    # A writer outside this operation changes the actual value and owner revision.
    state.update(revision="external-3", model="external")
    request = RequestKey("env", "principal", "verify-current-profile")
    try:
        repeated = coordinator.apply_profile(request, node, applied_profile.current_manifest_ref,
            "external-3", ApplicationPolicy(), base_profile_ref=applied_profile.current_manifest_ref)
    except (ConfigurationRevisionConflict, ConfigurationUnsupported):
        # A fail-closed refusal is valid when the owner cannot prove current facts.
        repeated = None

    if repeated is not None:
        result = coordinator.operation_view(repeated)["configurationResult"]
        assert result is None or result["overallOutcome"] != "applied"
    assert state["calls"] == 1
    receipt = store.read_operation(request)
    assert receipt is None or receipt.status != "published" or (
        coordinator.operation_view(receipt)["configurationResult"]["overallOutcome"] != "applied")


@pytest.mark.parametrize("changed_fact", ["configuration", "unknown-items"])
def test_same_revision_changed_owner_facts_do_not_reuse_standing_applied(management_setup, changed_fact):
    _, env, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    _, profile = _profile(management_setup, declarations=(
        {**DECLARATION, "payload": {"modelId": "new"}},
    ), name=f"same-revision-{changed_fact}")
    applied = coordinator.apply_profile(RequestKey("env", "principal", f"apply-{changed_fact}"),
        node, profile.current_manifest_ref, "native-1", ApplicationPolicy(), base_profile_ref=base)
    assert applied.status == "published"

    # The owner leaves sourceRevision unchanged while its generic actual facts
    # diverge from the confirmation carried by the standing operation.
    if changed_fact == "configuration":
        state["model"] = "external"
    else:
        binding = coordinator._nodes.read(node)["binding"]
        provider = env.agent_runtime_contribution(binding["harnessDefinitionRef"]).provider
        inspect = provider.inspect_configuration

        def with_unknown_item(unit):
            return replace(inspect(unit), unknown_items=("unobserved",))

        provider.inspect_configuration = with_unknown_item

    request = RequestKey("env", "principal", f"verify-same-revision-{changed_fact}")
    result = coordinator.apply_profile(request, node, profile.current_manifest_ref,
        "native-2", ApplicationPolicy(), base_profile_ref=profile.current_manifest_ref)

    assert coordinator.operation_view(result)["configurationResult"]["overallOutcome"] != "applied"
    assert state["revision"] == "native-2"
    assert state["calls"] == 1


def test_unknown_operation_without_exact_domain_receipt_never_falls_back_to_unused(management_setup, monkeypatch):
    store, _, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)

    def unknown_operation(_request):
        raise UnknownResultError("controlled incomplete request lookup")

    monkeypatch.setattr(store, "read_operation", unknown_operation)
    monkeypatch.setattr(store, "read_domain_result", lambda _request, _digest: None)
    request = RequestKey("env", "principal", "unknown-without-domain-proof")

    with pytest.raises(UnknownResultError, match="controlled incomplete"):
        coordinator.apply_profile(request, node, None, "native-1", ApplicationPolicy(),
            base_profile_ref=base, profile_manifest=_omitted_manifest(marker="must-not-be-stored"))

    row = store._conn.execute(
        "SELECT 1 FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
        ("env", "principal", request.request_id),
    ).fetchone()
    assert row is None
    assert store.list_domain("env", "agents.profile-snapshots") == ()
    assert state["calls"] == 0


def test_no_change_same_request_with_different_manifest_conflicts_before_dispatch(management_setup):
    _, _, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    key = RequestKey("env", "principal", "no-change-body-conflict")
    first = coordinator.apply_profile(key, node, base, "native-1", ApplicationPolicy(), base_profile_ref=base)
    _, changed = _profile(management_setup, declarations=(
        {**DECLARATION, "payload": {"modelId": "different"}},
    ), name="different-body-profile")

    with pytest.raises(IdentityMismatchError):
        coordinator.apply_profile(key, node, changed.current_manifest_ref, "native-1", ApplicationPolicy(),
                                  base_profile_ref=base)
    assert first.status == "refused"
    assert state["calls"] == 0


def _omitted_manifest(*, marker="sensitive-inline-marker"):
    return {"harnessDefinitionRef": dict(DEFINITION), "schemaVersion": "1",
            "declarations": [], "metadata": {"marker": marker}}


def test_omission_refusal_spends_existing_request_row_without_payload_or_scope_fence(management_setup):
    store, _, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    request = RequestKey("env", "principal", "omission-spends-key")
    before_fence = store.list_domain("env", CONFIGURATION_ATTEMPTS)

    with pytest.raises(ConfigurationOmissionRefused) as refused:
        coordinator.apply_profile(request, node, None, "native-1", ApplicationPolicy(),
            base_profile_ref=base, profile_manifest=_omitted_manifest())

    assert refused.value.omitted == ("model",)
    with pytest.raises(UnknownResultError):
        store.read_operation(request)
    assert store.list_domain("env", "agents.profile-snapshots") == ()
    assert store.list_domain("env", CONFIGURATION_ATTEMPTS) == before_fence
    assert state["calls"] == 0
    row = store._conn.execute(
        "SELECT dispatch_state, receipt FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
        ("env", "principal", request.request_id),
    ).fetchone()
    assert row["dispatch_state"] == "concluded"
    receipt = json.loads(row["receipt"])["domain_result"]
    assert receipt == {"status": "refused", "code": ConfigurationOmissionRefused.code,
                       "omitted": ["model"]}
    assert "sensitive-inline-marker" not in row["receipt"]


def test_same_omission_request_replays_same_typed_refusal_without_owner_effect(management_setup):
    _, _, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    request = RequestKey("env", "principal", "omission-replay")
    first = _omitted_manifest(marker="replay-marker")

    for body in (first, _omitted_manifest(marker="replay-marker")):
        with pytest.raises(ConfigurationOmissionRefused) as refused:
            coordinator.apply_profile(request, node, None, "native-1", ApplicationPolicy(),
                base_profile_ref=base, profile_manifest=body)
        assert refused.value.omitted == ("model",)
    assert state["calls"] == 0


def test_correcting_omission_under_spent_request_id_conflicts_before_native_effect(management_setup):
    _, env, _, coordinator, node, _, _, state, *_ = management_setup
    base = _base_ref(management_setup)
    request = RequestKey("env", "principal", "omission-corrected-same-id")
    with pytest.raises(ConfigurationOmissionRefused):
        coordinator.apply_profile(request, node, None, "native-1", ApplicationPolicy(),
            base_profile_ref=base, profile_manifest=_omitted_manifest(marker="omitted"))

    binding = coordinator._nodes.read(node)["binding"]
    provider = env.agent_runtime_contribution(binding["harnessDefinitionRef"]).provider
    owner_calls = []

    def forbidden_owner_call(*args, **kwargs):
        owner_calls.append((args, kwargs))
        raise AssertionError("spent refusal must conflict before owner inspection")

    provider.inspect_unit = forbidden_owner_call
    provider.inspect_configuration = forbidden_owner_call
    provider.describe_configuration = forbidden_owner_call

    reset = {key: value for key, value in DECLARATION.items() if key != "payload"}
    reset["action"] = "reset"
    corrected = {"harnessDefinitionRef": dict(DEFINITION), "schemaVersion": "1",
                 "declarations": [reset]}
    with pytest.raises(IdentityMismatchError):
        coordinator.apply_profile(request, node, None, "native-1", ApplicationPolicy(),
            base_profile_ref=base, profile_manifest=corrected)
    assert owner_calls == []
    assert state["calls"] == 0


def test_typed_manifest_diff_errors_are_reexported_by_identity():
    from pacthold.agents import public
    from pacthold.agents.configuration import (
        ConfigurationConversionRefused as CoreConversionRefused,
        ConfigurationOmissionRefused as CoreOmissionRefused,
    )

    assert public.ConfigurationOmissionRefused is CoreOmissionRefused
    assert public.ConfigurationConversionRefused is CoreConversionRefused
    assert ConfigurationOmissionRefused(("omitted",)).omitted == ("omitted",)
    assert ConfigurationConversionRefused(("changed-kind",)).conflicts == ("changed-kind",)
