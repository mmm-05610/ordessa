"""Public Unit API contracts over the original SQLite and local ACP owners.

These tests use only a controlled local child process. They do not call a model,
mint production authority, or treat caller-held Unit handles as permission.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_unit_instance import Authority, Preparation, Provider
from test_unit_manager import DistinctScopes
from ordessa_execution_agents.harness.definitions.runtime_providers import (
    RUNTIME_PROVIDER_VERSION,
    RuntimeProviderDescriptor,
)
from ordessa_execution_agents.preparation import ConfigurationResources
from ordessa_execution_agents.profiles import (
    ProfileRevisionRef,
    canonical_content,
    content_digest,
    encode_revision_ref,
)
from ordessa_units.assembly import build_unit_manager
from ordessa_units.api import UnitApiRefused, UnitInteraction, UnitReconnectUnavailable
from ordessa_units.definitions import UnitSpec
from ordessa_units.management import UnitInstance, UnitManager as OriginalUnitManager
from ordessa_units.records import OperationJournal, UnitRecords
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.admission.connection import ConnectionLeasePort


class Authorization:
    """Controlled request identity; bindings turn it into original-owner facts."""

    def __init__(self, name):
        self.name = name


class Bindings:
    def __init__(self, *, authority, records, original, revision, manifest, root, environment):
        self.authority = authority
        self.records = records
        self.original = original
        self.revision = revision
        self.manifest = manifest
        self.root = root
        self.environment = environment

    def resolve_plan(self, spec, authorization):
        node = {
            "environmentNamespace": "env",
            "nodeId": authorization.name,
            "generation": 1,
        }
        roots = {
            part: str(self.root / authorization.name / part)
            for part in ("home", "cwd", "profile")
        }
        return {
            "profileSnapshot": {
                "ref": encode_revision_ref(spec.profile_revision),
                "manifest": self.manifest,
            },
            "context": {"nodeRef": node, "privateRootFacts": roots},
        }

    def authorize(self, action, subject, authorization):
        if action == "interaction":
            identity = subject.identity
            instance = self.original.find(identity)
            return instance.lease_port.grant(identity)
        identity = subject.identity if hasattr(subject, "identity") else None
        name = authorization.name
        if identity is not None:
            unit = self.records.owner_read_unit(identity["unitId"])
            name = unit.facts["nodeRef"]["nodeId"]
        plan_node = {
            "environmentNamespace": "env",
            "nodeId": name,
            "generation": 1,
        }
        self.authority.node = plan_node
        context = self.authority.issue(action)
        context.facts["request"]["requestId"] = name + "." + action
        context.facts["operationRef"] = name + ".original-operation"
        return context

    def authorize_manager_close(self, authorization):
        if (type(authorization) is not Authorization
                or not isinstance(authorization.name, str)
                or not authorization.name.strip()):
            raise UnitApiRefused("Exact controlled manager authorization required")
        return True


@pytest.fixture
def public_units(tmp_path):
    events = []
    root = tmp_path / "environment"
    descriptor = RuntimeProviderDescriptor(
        "controlled",
        RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": "env", "definitionId": "controlled", "revision": "1"},
        "sha256:" + "a" * 64,
        ("plan_preparation", "prepare", "start", "connect", "describe_access", "stop", "release"),
    )
    provider_ref = {
        "environmentNamespace": "env",
        "providerId": "controlled",
        "generation": 1,
        "contractVersion": RUNTIME_PROVIDER_VERSION,
        "implementationDigest": descriptor.implementation_digest,
    }
    authority = Authority(provider_ref, None)
    evidence = AcpUnitEvidence(
        preparation_authority=lambda plan, facts: plan["context"]["privateRootFacts"],
        start_authority=authority.continuation,
        configuration_authority=authority.continuation,
    )
    records = UnitRecords(
        OperationJournal(tmp_path / "original.sqlite"),
        scope_authority=DistinctScopes(),
        native_evidence=evidence,
        verifier=authority,
        epoch_port=SimpleNamespace(current_epoch=lambda node: 0),
        termination_evidence=evidence,
        configuration_evidence=evidence,
    )
    evidence.attach_owner(records)
    environments = Provider(root, events)
    manifest = {
        "schemaVersion": "1",
        "harnessDefinitionRef": dict(descriptor.definition_ref),
        "declarations": [],
        "metadata": {"marker": "public-unit-profile"},
    }
    revision = ProfileRevisionRef(
        "env", "profile", 1, content_digest(canonical_content(manifest, "env"))
    )
    instances = []

    def materialize(agent, env, facts, snapshot):
        directory = env.files.ensure(
            str(Path(agent.harness.resources.location).relative_to(root))
        )
        Path(directory, "settings.json").write_text(
            json.dumps(dict(snapshot["manifest"]["metadata"]))
        )
        return ConfigurationResources("profile-dir", directory, True)

    def factory(plan):
        instance = UnitInstance(
            descriptor=descriptor,
            agent_id="agent",
            profile_revision=revision,
            environment_instance=environments,
            environment_sharing=True,
            environment_reference={"environmentId": environments.identity},
            preparation=Preparation(events),
            materializer=materialize,
            records=records,
            projection=evidence,
            verifier=authority,
            lease_port=ConnectionLeasePort(),
            termination_evidence=evidence,
            timeout=2,
        )
        instances.append(instance)
        return instance

    original = OriginalUnitManager(create_instance=factory, records=records, verifier=authority)
    bindings = Bindings(
        authority=authority,
        records=records,
        original=original,
        revision=revision,
        manifest=manifest,
        root=root,
        environment=environments,
    )
    bindings.manager = None
    manager = build_unit_manager(original, bindings)
    bindings.manager = manager
    bindings.revision = revision
    spec = UnitSpec(
        agent_id="agent",
        profile_revision=revision,
        environment_reference={"environmentId": environments.identity},
    )
    result = SimpleNamespace(
        manager=manager,
        original=original,
        bindings=bindings,
        spec=spec,
        authorization=Authorization,
        instances=instances,
        extra_uses=[],
        environments=environments,
        events=events,
        records=records,
        revision=revision,
    )
    yield result

    for use in result.extra_uses:
        try:
            use.release()
        except Exception:
            pass
    for instance in instances:
        record = instance.channel_factory.owned_record
        use = instance.channel_factory.environment
        if use is not None and use.identity not in environments.release_receipts:
            if record is not None:
                if record.process.observe().state != "exited":
                    if record.channel is not None:
                        record.entry.run_process_operation(
                            record.channel.close_async(timeout=2), timeout=10
                        )
                    else:
                        async def terminate():
                            await record.process.cancel(force=True)
                            await record.process.wait_exit(timeout=5)
                        asyncio.run(terminate())
                record.process.release()
            try:
                use.release()
            except Exception:
                pass
        if record is not None and hasattr(record.entry, "detach"):
            record.entry.detach()


def test_public_identity_snapshot_lookup_and_fixed_profile(public_units):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("one"))
    identity = unit.identity
    snapshot = unit.snapshot()

    assert f.manager.get(identity) is unit
    assert f.manager.list() == (unit,)
    assert snapshot["identity"] == identity
    assert snapshot["definition"]["agentId"] == "agent"
    assert snapshot["definition"]["profileRevision"] == encode_revision_ref(f.revision)
    assert unit.snapshot() == snapshot
    assert f.events.count("spawn") == 1
    assert f.records.owner_read_session(identity["unitId"]).state == "confirmed"


def test_foreign_or_mismatched_spec_refuses_before_acquire_or_spawn(public_units):
    f = public_units
    foreign = dict(f.spec.environment_reference)
    foreign["environmentId"] = "foreign-environment"
    wrong_environment = UnitSpec(
        agent_id=f.spec.agent_id,
        profile_revision=f.spec.profile_revision,
        environment_reference=foreign,
    )
    wrong_revision = UnitSpec(
        agent_id=f.spec.agent_id,
        profile_revision=ProfileRevisionRef(
            "env", "other-profile", 1, f.revision.digest
        ),
        environment_reference=dict(f.spec.environment_reference),
    )

    with pytest.raises(UnitApiRefused):
        f.manager.create(wrong_environment, f.authorization("bad-environment"))
    with pytest.raises(UnitApiRefused):
        f.manager.create(wrong_revision, f.authorization("bad-profile"))
    with pytest.raises(UnitApiRefused):
        f.manager.get({"environmentNamespace": "env", "unitId": "foreign"})
    assert f.environments.opens == 0
    assert f.events.count("spawn") == 0
    assert f.manager.list() == ()


def test_one_session_per_unit_and_close_releases_only_its_shared_use(public_units):
    f = public_units
    first = f.manager.create(f.spec, f.authorization("first"))
    second = f.manager.create(f.spec, f.authorization("second"))
    first_session = f.records.owner_read_session(first.identity["unitId"])
    second_session = f.records.owner_read_session(second.identity["unitId"])
    first_record = f.instances[0].channel_factory.owned_record
    second_record = f.instances[1].channel_factory.owned_record
    assert first_record.process.identity != second_record.process.identity
    assert first_record.entry is not second_record.entry
    assert first_record.entry.sdk_connection is not second_record.entry.sdk_connection
    assert first_session.creation_correlation != second_session.creation_correlation
    assert f.environments.instance.snapshot.active_uses == 2

    result = first.close(f.authorization("close-first"))
    assert result["state"] == "confirmed"
    assert first not in f.manager.list()
    assert f.manager.get(second.identity) is second
    assert f.environments.instance.snapshot.active_uses == 1
    assert f.instances[1].channel_factory.owned_record.process.observe().state == "running"

    result = second.close(f.authorization("close-second"))
    assert result["state"] == "confirmed"
    assert f.manager.list() == ()
    assert f.environments.instance.snapshot.active_uses == 0
    shared = f.environments.instance.acquire("after-units", sharing=True)
    assert shared.environment_id == f.environments.identity
    assert shared.release()["resourcePreserved"] is True


def test_cancel_and_disconnect_do_not_stop_or_release_the_unit_process(public_units):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("interact"))
    interaction = unit.interaction(f.authorization("interact"))
    result = interaction.prompt({"prompt": [{"type": "text", "text": "controlled"}], "timeout": 2})
    assert result["observedConfiguration"] == {"marker": "public-unit-profile"}

    with pytest.raises(UnitApiRefused):
        interaction.request("session/new", {})
    interaction.cancel()
    interaction.disconnect()
    with pytest.raises(UnitReconnectUnavailable):
        interaction.request("session/prompt", {"prompt": []})
    with pytest.raises(UnitReconnectUnavailable):
        unit.interaction(f.authorization("interact-again"))
    record = f.instances[0].channel_factory.owned_record
    assert record.process.observe().state == "running"
    assert f.records.owner_read_session(unit.identity["unitId"]).state == "confirmed"
    assert f.environments.instance.snapshot.active_uses == 1
    assert unit.close(f.authorization("close-after-disconnect"))["state"] == "confirmed"


def test_interaction_rejects_unowned_connection_and_keeps_assembly_connection(public_units):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("connection-owner"))
    retained = unit.interaction(f.authorization("connection-owner"))
    assert retained.prompt({"prompt": [{"type": "text", "text": "owned"}], "timeout": 2})[
        "observedConfiguration"
    ] == {"marker": "public-unit-profile"}

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def request(self, *args, **kwargs):
            self.calls.append(("request", args, kwargs))
            return {"spoofed": True}

        def cancel(self, *args, **kwargs):
            self.calls.append(("cancel", args, kwargs))
            return {"spoofed": True}

    fake = FakeConnection()
    unowned = UnitInteraction(unit, fake)
    with pytest.raises(UnitApiRefused):
        unowned.request("session/prompt", {"prompt": []})
    with pytest.raises(UnitApiRefused):
        unowned.cancel()
    assert fake.calls == []
    assert unit.close(f.authorization("close-connection-owner"))["state"] == "confirmed"


def test_close_authorization_refusal_before_termination_has_no_effect(public_units, monkeypatch):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("refused-before-stop"))
    instance = f.instances[0]
    authorize = f.bindings.authorize

    def refuse_stop(action, subject, authorization):
        if action == "stop":
            raise UnitApiRefused("controlled stop authorization refusal")
        return authorize(action, subject, authorization)

    monkeypatch.setattr(f.bindings, "authorize", refuse_stop)
    result = unit.close(f.authorization("refused-close"))

    assert result["state"] == "refused"
    assert f.records.owner_read_termination(unit.identity["unitId"], "stop") is None
    assert f.records.owner_read_termination(unit.identity["unitId"], "release") is None
    assert f.manager.get(unit.identity) is unit
    assert instance.channel_factory.owned_record.process.observe().state == "running"
    assert f.environments.instance.snapshot.active_uses == 1


def test_close_release_authorization_refusal_preserves_stopped_handles(public_units, monkeypatch):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("refused-after-stop"))
    instance = f.instances[0]
    authorize = f.bindings.authorize

    def refuse_release(action, subject, authorization):
        if action == "release":
            raise UnitApiRefused("controlled release authorization refusal")
        return authorize(action, subject, authorization)

    monkeypatch.setattr(f.bindings, "authorize", refuse_release)
    result = unit.close(f.authorization("partial-close"))

    stop = f.records.owner_read_termination(unit.identity["unitId"], "stop")
    release = f.records.owner_read_termination(unit.identity["unitId"], "release")
    assert result["state"] == "partial"
    assert stop["state"] == "confirmed"
    assert release is None
    assert f.manager.get(unit.identity) is unit
    assert f.original.find(unit.identity) is instance
    assert instance.channel_factory.owned_record.process.observe().state == "exited"
    assert f.environments.instance.snapshot.active_uses == 1


def test_unknown_stop_is_not_replayed_and_unit_remains_owned(public_units, monkeypatch):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("unknown-stop"))
    instance = f.instances[0]
    attempts = []

    def unknown_close(entry):
        attempts.append(entry)
        raise RuntimeError("controlled lost stop receipt")

    monkeypatch.setattr(instance.channel_factory, "close", unknown_close)
    first = unit.close(f.authorization("close-unknown"))
    second = unit.close(f.authorization("close-unknown"))

    assert first["state"] in {"unknown", "partial", "refused"}
    assert second["state"] in {"unknown", "partial", "refused"}
    assert len(attempts) == 1
    assert f.manager.get(unit.identity) is unit


def test_unknown_release_is_not_replayed_and_unit_remains_owned(public_units, monkeypatch):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("unknown-release"))
    instance = f.instances[0]
    attempts = []

    def unknown_release(entry):
        attempts.append(entry)
        raise RuntimeError("controlled lost release receipt")

    monkeypatch.setattr(instance.channel_factory, "release", unknown_release)
    first = unit.close(f.authorization("close-unknown-release"))
    second = unit.close(f.authorization("close-unknown-release"))

    assert first["state"] in {"unknown", "partial", "refused"}
    assert second["state"] in {"unknown", "partial", "refused"}
    assert len(attempts) == 1
    assert f.manager.get(unit.identity) is unit


def test_manager_close_reports_partial_and_retains_failed_unit(public_units, monkeypatch):
    f = public_units
    first = f.manager.create(f.spec, f.authorization("partial-a"))
    second = f.manager.create(f.spec, f.authorization("partial-b"))
    first_instance = f.instances[0]
    original_close = first_instance.channel_factory.close
    attempts = []

    def unknown_close(entry):
        attempts.append(entry)
        raise RuntimeError("controlled lost stop receipt")

    monkeypatch.setattr(first_instance.channel_factory, "close", unknown_close)
    result = f.manager.close(f.authorization("close-all"))

    assert result["state"] == "partial"
    assert f.manager.get(first.identity) is first
    assert second not in f.manager.list()
    assert len(attempts) == 1

    # A later drain revalidates the damaged Unit, does not replay its unknown
    # stop, and remains safe to close any healthy sibling still owned.
    retry = f.manager.close(f.authorization("close-all-retry"))
    assert retry["state"] == "partial"
    assert f.manager.get(first.identity) is first
    with pytest.raises(UnitApiRefused):
        f.manager.get(second.identity)
    assert len(attempts) == 1


def test_manager_close_fences_new_create_before_resolving_plan(public_units, monkeypatch):
    f = public_units
    unit = f.manager.create(f.spec, f.authorization("close-then-create"))
    result = f.manager.close(f.authorization("close-before-create"))
    assert result["state"] == "confirmed"
    assert f.manager.list() == ()
    with pytest.raises(UnitApiRefused):
        f.manager.get(unit.identity)

    resolutions = []
    original_resolve = f.bindings.resolve_plan

    def resolve_after_drain(spec, authorization):
        resolutions.append((spec, authorization))
        return original_resolve(spec, authorization)

    monkeypatch.setattr(f.bindings, "resolve_plan", resolve_after_drain)
    with pytest.raises(UnitApiRefused):
        f.manager.create(f.spec, f.authorization("create-after-close"))
    assert resolutions == []


def test_manager_close_does_not_invent_unresolved_for_pre_effect_plan_failure(public_units, monkeypatch):
    f = public_units

    def opaque_plan_failure(spec, authorization):
        raise RuntimeError("controlled opaque preparation failure")

    monkeypatch.setattr(f.bindings, "resolve_plan", opaque_plan_failure)
    with pytest.raises(RuntimeError, match="controlled opaque preparation failure"):
        f.manager.create(f.spec, f.authorization("opaque"))

    result = f.manager.close(f.authorization("close-opaque"))
    assert result["state"] == "confirmed"
    assert f.manager.list() == ()


def test_manager_close_keeps_opaque_factory_attempt_unresolved(public_units, monkeypatch):
    f = public_units
    uses = []

    def fail_after_acquire(plan):
        use = f.environments.instance.acquire("opaque-factory-attempt", sharing=True)
        uses.append(use)
        f.extra_uses.append(use)
        raise RuntimeError("controlled opaque factory failure")

    monkeypatch.setattr(f.original, "_factory", fail_after_acquire)
    with pytest.raises(RuntimeError, match="controlled opaque factory failure"):
        f.manager.create(f.spec, f.authorization("opaque-factory"))

    result = f.manager.close(f.authorization("close-opaque-factory"))
    assert result["state"] == "partial"
    assert result["unresolved"]
    assert f.manager.list() == ()
    for use in uses:
        use.release()
