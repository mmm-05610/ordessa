"""C: explicit production assembly of the Claude family provider.

Real temporary SQLite ledger + real core claims; every port is injected
explicitly and every missing or foreign port is a typed assembly refusal.
Capability advertisement is checked against the exact composed ports. The
start bridge here is a controlled effect owner (no async SDK bridge exists in
this tree); the SDK session assembly consumes a controlled native capture.
No installed SDK, Claude binary, model call or credential is involved.
"""
import contextlib
import json

import pytest

import claude_production_fixture as fx
from claude_production_fixture import safe_json

from ordessa_harness_claude_code.assembly import (
    ClaudeAssemblyRefused, assemble_claude_provider, assemble_sdk_session,
)
from ordessa_harness_claude_code.provider import ClaudeProviderUnavailable
from ordessa_harness_claude_code.sdk import (
    ClaudeSdkSession, FencedSdkTransport, SdkRuntimeUnavailable,
)
from ordessa_harness_records.unit_records import UnitRecords, UnitRecordsRefused


def _gate():
    from contextlib import asynccontextmanager

    class Gate:
        @asynccontextmanager
        async def dispatch_guard(self, payload):
            yield
    return Gate()


class NativeCapture:
    def __init__(self):
        self.writes = []

    async def connect(self):
        pass

    async def write(self, data):
        self.writes.append(data)

    async def read_messages(self):
        return
        yield  # pragma: no cover

    async def close(self):
        pass

    def is_ready(self):
        return True

    async def end_input(self):
        pass


class MinimalSessionOwner:
    def __init__(self):
        self.model = "seed-model"

    def session_apply_model(self, unit, action, payload, context):
        return {"outcome": "unknown", "confirmation": "ackOnly"}

    def observe_model(self, unit):
        return {"model": self.model}

    def observe_session(self, unit):
        return "native-observed-id"


def _provenance_ref(unit, name):
    return {"environmentNamespace": "env", "ownerProviderRef": unit.facts["providerRef"],
            "sourceRevision": "fixture-generation-1", "ref": name}


class BridgeEffects:
    """Controlled start bridge: the production shape stays on the deployment."""

    def __init__(self, parts):
        self.records, self.verifier = parts["records"], parts["records"].verifier
        self.native_evidence = parts["records"].native_unit_evidence
        self.handles = []

    def dispatch_guard(self, unit, context, phase):
        return contextlib.nullcontext()

    def open_owned(self, unit, context):
        handle = object()
        self.handles.append(handle)
        return handle

    def initialize_owned(self, unit, handle, context):
        correlation = safe_json({"request": context.facts["request"],
                                 "operationRef": context.facts["operationRef"],
                                 "stepId": context.facts["stepId"]})
        return self.native_evidence.observe_binding(
            unit, correlation, session_id="init-native-1",
            process_ref=_provenance_ref(unit, "owned-process"),
            transport_ref=_provenance_ref(unit, "same-pipe"),
            initialization_ref=_provenance_ref(unit, "original-initialize-success"))


class BridgeObservations:
    def __init__(self, parts):
        self.records, self.verifier = parts["records"], parts["records"].verifier
        self.native_evidence = parts["records"].native_unit_evidence
        self.evidence_ref = None

    def query_original_unit(self, unit, correlation, context):
        return self.evidence_ref


class PreparationAuthority:
    def verify_preparation(self, plan, facts):
        return True


def wire(parts, **overrides):
    kwargs = dict(
        definition_ref={"environmentNamespace": "env", "definitionId": "claude", "revision": "1"},
        implementation_digest=fx.FAMILY_DIGEST,
        records=parts["records"], verifier=parts["records"].verifier,
        publication_owner=parts["projection"]._publication_owner,
        owned_channels=parts["ports"].channels,
        session_owner=MinimalSessionOwner(),
        preparation_authority=PreparationAuthority(),
    )
    kwargs.update(overrides)
    return assemble_claude_provider(**kwargs)


def base_wiring(tmp_path, *, with_session=False, **overrides):
    tmp_path.mkdir(parents=True, exist_ok=True)
    parts = fx.family_core_parts(tmp_path, with_session=with_session)
    return parts, wire(parts, **overrides)


def test_production_assembly_advertises_exactly_the_composed_surface(tmp_path):
    parts, wiring = base_wiring(tmp_path)
    methods = wiring.provider.descriptor.supported_methods
    assert set(methods) == {"describe_definition", "inspect_installation", "assess_configuration",
                            "plan_preparation", "prepare", "inspect_unit", "describe_access",
                            "describe_configuration", "inspect_configuration",
                            "apply_configuration", "query_change", "stop", "release"}
    assert "start" not in methods and "query_step" not in methods and "connect" not in methods
    assert "recover" not in methods
    assert wiring.provider._records is parts["records"]
    assert wiring.provider._verifier is parts["records"].verifier


def test_start_bridge_ports_complete_the_surface_and_confirm_through_owner_ports(tmp_path):
    parts = fx.family_core_parts(tmp_path)
    effects = BridgeEffects(parts)
    observations = BridgeObservations(parts)
    wiring = wire(parts, native_unit_effects=effects, native_unit_observations=observations)
    methods = wiring.provider.descriptor.supported_methods
    assert "start" in methods and "query_step" in methods
    context = parts["issued"]("start")
    reply = wiring.provider.start({"unitRef": parts["unit"].public_ref}, context)
    assert reply["state"] == "confirmed" and "evidenceRef" in reply
    assert len(effects.handles) == 1
    with parts["journal"]._connect() as db:
        assert db.execute("SELECT state FROM harness_unit_confirmations").fetchone()["state"] == "confirmed"
        assert db.execute("SELECT state FROM harness_unit_sessions").fetchone()["state"] == "notCreated"
    # The projection registered the observed start for original-creation queries.
    query = parts["issuer"].issue_query(parts["request"], "flow-digest", "start")
    observed = wiring.provider.query_step("start-correlation", query)
    assert observed["state"] == "confirmed"
    assert parts["issuer"].verified_observation(query) is True


def test_stop_release_routes_through_the_coordinated_termination_face(tmp_path):
    parts, wiring = base_wiring(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channels = parts["ports"].channels
    channels.register(parts["unit"].public_ref, _DeadChannel())
    reply = wiring.provider.stop(parts["unit"].public_ref, stop["issued"]())
    assert reply["state"] == "confirmed" and reply["action"] == "stop"
    release = fx.cleanup_operation(parts, "release")
    assert wiring.provider.release(parts["unit"].public_ref, release["issued"]())["state"] == "confirmed"
    assert not channels.is_owned(parts["unit"].public_ref)


class _DeadChannel:
    def is_alive(self):
        return False

    def close(self, *, timeout=5.0):
        return 0


def test_management_face_reads_actual_observed_model(tmp_path):
    parts, wiring = base_wiring(tmp_path, with_session=True)
    descriptions = wiring.provider.describe_configuration(parts["unit"].public_ref)
    assert descriptions[0].configuration_kind == "claude.model"
    assert descriptions[0].confirmation == "readback" and descriptions[0].scope == "session"
    snapshot = wiring.provider.inspect_configuration(parts["unit"].public_ref)
    assert snapshot.configuration["model"] == "seed-model"
    assert snapshot.source_revision is not None
    assert snapshot.comparison_guarantee == "ownerSerialized"


def test_missing_or_foreign_ports_are_typed_assembly_refusals(tmp_path):
    parts = fx.family_core_parts(tmp_path)
    records, verifier = parts["records"], parts["records"].verifier
    common = dict(definition_ref={"environmentNamespace": "env", "definitionId": "claude", "revision": "1"},
                  implementation_digest=fx.FAMILY_DIGEST, records=records, verifier=verifier,
                  publication_owner=lambda *a: {}, owned_channels=parts["ports"].channels,
                  session_owner=MinimalSessionOwner())
    with pytest.raises(ClaudeAssemblyRefused, match="same verifier"):
        assemble_claude_provider(**dict(common, verifier=object()))
    with pytest.raises(ClaudeAssemblyRefused, match="records"):
        assemble_claude_provider(**dict(common, records=object()))
    without_termination = UnitRecords(parts["journal"], scope_authority=records.scope_authority,
                                      native_evidence=records.native_evidence, verifier=verifier,
                                      epoch_port=records.epoch_port,
                                      native_unit_evidence=records.native_unit_evidence)
    with pytest.raises(ClaudeAssemblyRefused, match="termination_evidence"):
        assemble_claude_provider(**dict(common, records=without_termination))
    without_configuration = UnitRecords(parts["journal"], scope_authority=records.scope_authority,
                                        native_evidence=records.native_evidence, verifier=verifier,
                                        epoch_port=records.epoch_port,
                                        termination_evidence=records.termination_evidence)
    with pytest.raises(ClaudeAssemblyRefused, match="configuration_evidence"):
        assemble_claude_provider(**dict(common, records=without_configuration))
    with pytest.raises(ClaudeAssemblyRefused, match="registry"):
        assemble_claude_provider(**dict(common, owned_channels=object()))
    with pytest.raises(ClaudeAssemblyRefused, match="session owner"):
        assemble_claude_provider(**dict(common, session_owner=object()))
    with pytest.raises(ClaudeAssemblyRefused, match="publication owner"):
        assemble_claude_provider(**dict(common, publication_owner=None))


def test_start_bridge_demands_the_native_unit_evidence_owner(tmp_path):
    parts = fx.family_core_parts(tmp_path)
    records = parts["records"]
    bare = UnitRecords(parts["journal"], scope_authority=records.scope_authority,
                       native_evidence=records.native_evidence, verifier=records.verifier,
                       epoch_port=records.epoch_port, termination_evidence=records.termination_evidence,
                       configuration_evidence=records.configuration_evidence)
    with pytest.raises(ClaudeAssemblyRefused, match="native_unit_evidence"):
        assemble_claude_provider(
            definition_ref={"environmentNamespace": "env", "definitionId": "claude", "revision": "1"},
            implementation_digest=fx.FAMILY_DIGEST, records=bare, verifier=records.verifier,
            publication_owner=lambda *a: {}, owned_channels=parts["ports"].channels,
            session_owner=MinimalSessionOwner(), native_unit_effects=BridgeEffects(parts))


def test_access_owner_refuses_unconfirmed_and_reports_confirmed(tmp_path):
    parts, wiring = base_wiring(tmp_path)
    (tmp_path / "second").mkdir()
    with_session = fx.family_core_parts(tmp_path / "second", with_session=True)
    confirmed_wiring = assemble_claude_provider(
        definition_ref={"environmentNamespace": "env", "definitionId": "claude", "revision": "1"},
        implementation_digest=fx.FAMILY_DIGEST, records=with_session["records"],
        verifier=with_session["records"].verifier,
        publication_owner=with_session["projection"]._publication_owner,
        owned_channels=with_session["ports"].channels, session_owner=MinimalSessionOwner(),
        preparation_authority=lambda plan, facts: True)
    with pytest.raises(ClaudeAssemblyRefused, match="confirmed"):
        wiring.provider.describe_access(parts["unit"].public_ref)
    access = confirmed_wiring.provider.describe_access(with_session["unit"].public_ref)
    assert access["protocol"] == "claude-agent-sdk" and access["leaseRequired"] is True
    inspection = confirmed_wiring.provider.inspect_unit(with_session["unit"].public_ref)
    assert inspection.ownership == "owned"
    assert inspection.management_epoch == 0


def test_sdk_session_assembly_wires_the_fenced_transport(tmp_path):
    native, gate = NativeCapture(), _gate()
    session = assemble_sdk_session(native, gate, options={"can_use_tool": lambda *a, **k: None},
                                   sdk_factory=lambda: (object, lambda **kw: kw))
    assert isinstance(session, ClaudeSdkSession)
    with pytest.raises(SdkRuntimeUnavailable):
        assemble_sdk_session(object(), gate)
    transport = FencedSdkTransport(native, gate)
    with pytest.raises(SdkRuntimeUnavailable):
        assemble_sdk_session(native, gate, dispatch_listener="not-callable",
                             sdk_factory=lambda: (object, lambda **kw: kw))
    del transport
