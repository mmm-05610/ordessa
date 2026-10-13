"""Production local Unit owner over real access, store, catalog and ACP process."""
from dataclasses import replace
import copy
import os
import pickle
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_execution_agents.harness.definitions.runtime_providers import RUNTIME_PROVIDER_VERSION
from ordessa_execution_agents.harness.transport import LaunchSpec
from ordessa_execution_agents.preparation import (
    ConfigurationResources,
    PreparedHarness,
    SessionBootstrap,
)
from ordessa_execution_agents.profiles import ProfileRevisionRef, ProfileService
from ordessa_execution_api.environment import EnvironmentId, GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import safe_json
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
    VerifiedPrincipal,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationIssuer
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.admission.owner_ports import AgentOwnerPorts, AgentProviderView
from ordessa_units.admission.owner_selection import AgentOwnerUnavailable, bind_unit_manager
from ordessa_units.admission.run_permission import RUN_ACTIONS, UnitRunPermission
from ordessa_units.api.errors import UnitApiRefused
from ordessa_units.definitions import UnitSpec
from ordessa_units.management import UnitManager as OriginalUnitManager
from ordessa_units.persistence.sqlite.store import SqliteUnitStore
from ordessa_units.records import OperationJournal, UnitRecords
from ordessa_execution_agents.harness.providers.registry import (
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
)
from ordessa_interfaces.system_access.contracts.transport import AccessError


CAPABILITIES = tuple(f"execution.units.{action}" for action in (
    "prepare", "start", "interaction", "stop", "release"
))
SCOPE = Scope("env", "project")
PRINCIPAL_ID = "fixture-principal"
BEARER = "fixturebearer"


# The child is a real local subprocess speaking ACP JSON-RPC. It is a protocol
# peer fixture only; authorization and environment execution remain real.
ACP_PEER = r'''
import json, sys
options=[{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low','options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
session_id='local-owner-'+__import__('os').path.basename(__import__('os').path.dirname(__import__('os').getcwd()))
for line in sys.stdin:
    q=json.loads(line); method=q['method']; p=q.get('params',{})
    if method=='initialize': r={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method=='session/new': r={'sessionId':session_id,'configOptions':options}
    elif method=='session/load': r={}
    elif method=='_ordessa/session/configuration': r={'sessionId':session_id,'configOptions':options}
    elif method=='session/prompt': r={'stopReason':'end_turn','observedPrompt':p.get('prompt'),'runtimeOptions':options}
    elif method=='session/cancel': continue
    else: r={}
    print(json.dumps({'jsonrpc':'2.0','id':q.get('id'),'result':r}),flush=True)
'''

ACP_PEER_REVERSE_WRITE = r'''
import json, os, sys
options=[{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low','options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
session_id='local-owner-'+os.path.basename(os.path.dirname(os.getcwd()))
for line in sys.stdin:
    q=json.loads(line); method=q['method']; p=q.get('params',{})
    if method=='initialize': r={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method=='session/new': r={'sessionId':session_id,'configOptions':options}
    elif method=='session/load': r={}
    elif method=='_ordessa/session/configuration': r={'sessionId':session_id,'configOptions':options}
    elif method=='session/prompt':
        path=os.path.join(os.getcwd(),'callback-proof.txt')
        print(json.dumps({'jsonrpc':'2.0','id':'reverse-write','method':'fs/write_text_file','params':{'sessionId':p.get('sessionId'),'path':path,'content':'written-once'}}),flush=True)
        reply=json.loads(sys.stdin.readline())
        r={'stopReason':'end_turn','observedPrompt':p.get('prompt'),'callbackReply':reply}
    elif method=='session/cancel': continue
    else: r={}
    print(json.dumps({'jsonrpc':'2.0','id':q.get('id'),'result':r}),flush=True)
'''


class Preparation:
    harness_id = "local-acp"

    def __init__(self, peer=None):
        self.peer = ACP_PEER if peer is None else peer

    def prepare(self, roots):
        return PreparedHarness(
            self.harness_id,
            LaunchSpec.build(
                [sys.executable, "-u", "-c", self.peer],
                home=roots["home"],
                cwd=roots["cwd"],
            ),
            SessionBootstrap("fresh", roots["cwd"]),
            ConfigurationResources("profile-dir", roots["profile"], False),
            {
                "identity": self.harness_id,
                "version": "fixture-1",
                "protocol": "acp/v1",
                "configurationReadMethod": "_ordessa/session/configuration",
            },
        )


class ProfileSetupPolicy:
    """Permit only fixture Profile setup and read-only Profile/Harness lookup."""

    def admit_invoke(self, principal, surface, guarantee):
        return (
            principal == PRINCIPAL_ID
            and guarantee == "reliable"
            and surface == "pacthold.agents.profiles.create"
        )

    def admit_object_access(self, principal, object_ref, mode):
        if principal != PRINCIPAL_ID or mode not in {"read", "write"}:
            return False
        return (
            object_ref.startswith("env:agents.profile:")
            or object_ref == "env:agents.runtime" and mode == "read"
        )


def _materializer(agent, environment, facts, snapshot):
    assert facts["action"] == "prepare"
    relative = os.path.relpath(agent.harness.resources.location, environment.files.root())
    directory = environment.files.ensure(relative)
    settings = {"materialized": snapshot["manifest"].get("metadata", {})}
    Path(directory, "settings.json").write_text(safe_json(settings), encoding="utf-8")
    return ConfigurationResources(agent.harness.resources.kind, directory, True)


def _access_authority(*, capabilities=CAPABILITIES, token=BEARER):
    scope = SCOPE
    return InstanceAccessAuthority(
        lambda: token,
        principal_id=PRINCIPAL_ID,
        grants=(AccessGrant(scope, tuple(capabilities)),),
        legacy_principal=None,
    )


def _run_permission(authority, principal, root, *, scope=SCOPE, profile_ref=None,
                    environment_identity="environment/fixture", expires_at=100.0,
                    actions=RUN_ACTIONS):
    root.mkdir(parents=True, exist_ok=True)
    return UnitRunPermission(
        access_authority=authority,
        principal=principal,
        scope=scope,
        agent_id="local-agent",
        profile_revision=profile_ref or ProfileRevisionRef(
            "env", "profile", 1, "sha256:" + "a" * 64
        ),
        environment_identity=environment_identity,
        root_directory=str(root),
        actions=frozenset(actions),
        expires_at=expires_at,
    )


@pytest.fixture
def live_owner(tmp_path, request):
    fixture_options = getattr(request, 'param', {})
    if type(fixture_options) is not dict:
        fixture_options = {}
    acp_turn_opt_in = fixture_options.get('acp_turn_opt_in', False)
    effect_write_guard_factory = fixture_options.get('effect_write_guard_factory')
    callback_approval = fixture_options.get('callback_approval')
    preparation_peer = fixture_options.get('preparation_peer')
    now = [10.0]
    access = _access_authority()
    principal = access.authenticate(f"Bearer {BEARER}")

    store = SqliteUnitStore(tmp_path / "unit-store.sqlite")
    policy = ProfileSetupPolicy()
    namespace = "env"
    from threading import RLock

    lock = RLock()
    context_ref = {}
    catalog = HarnessCatalog(
        namespace,
        policy=policy,
        principal_scope=PRINCIPAL_ID,
        admission_lock=lock,
        retirement_guard=lambda owner_id, generation: context_ref["context"].provider_retirement_guard(
            owner_id, generation
        ),
    )
    materials = MaterialCatalog(namespace, admission_lock=lock)
    admission = UnitAdmissionContext(
        namespace,
        store=store,
        policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {"fixture": b"local-unit-owner-profile-fixture"}, active_key_id="fixture"
        ),
        harness_catalog=catalog,
        material_catalog=materials,
        principal_scope=PRINCIPAL_ID,
        admission_lock=lock,
    )
    context_ref["context"] = admission

    definition = HarnessDefinitionDescriptor(
        "local-acp",
        {"environmentNamespace": namespace, "definitionId": "local-acp", "revision": "1"},
        "sha256:" + "b" * 64,
        "acp/v1",
        "local-process-fixture/1",
    )
    declaration = HarnessDefinitionDeclaration(definition, lambda _installation: None)
    catalog.stage("local-acp-owner", 1, "local-installation", "c" * 64, (declaration,)).commit()

    profile_service = ProfileService(admission)
    profile = profile_service.create(
        profile_id="profile",
        name="Local Unit fixture",
        content={
            "schemaVersion": "1",
            "harnessDefinitionRef": dict(definition.definition_ref),
            "declarations": [],
            "metadata": {"fixture": "local-process"},
        },
        request=profile_service.request_key("create-local-profile"),
    )

    environment_root = tmp_path / "environment-root"
    environment_root.mkdir()
    root = environment_root / "units"
    root.mkdir()
    environment_provider = LocalEnvironmentResourceProvider(default_root=str(environment_root))
    environment_manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / "environment-store.sqlite"),
        providers={"local": environment_provider},
    )
    environment = environment_manager.create(
        "local", {"isolation": "none", "root": str(environment_root)}
    )

    permission = _run_permission(
        access,
        principal,
        root,
        profile_ref=profile.current_revision,
        environment_identity=environment.identity,
    )
    preparation = Preparation(preparation_peer)
    from ordessa_units.assembly.local_owner import build_local_unit_owner

    owner = build_local_unit_owner(
        admission_context=admission,
        permission=permission,
        environment_instance=environment,
        preparation=preparation,
        materializer=_materializer,
        environment_sharing=True,
        timeout=5,
        effect_write_guard_factory=effect_write_guard_factory,
        acp_turn_opt_in=acp_turn_opt_in,
        callback_approval=callback_approval,
        clock=lambda: now[0],
    )
    assert owner.owner_inputs.acp_turn_opt_in is acp_turn_opt_in

    issuer = InvocationIssuer(
        store, owner.owner_inputs.authority, owner.owner_inputs.current_state,
        clock=lambda: now[0],
    )
    verifier = issuer.verifier()
    journal_path = tmp_path / "operation-journal.sqlite"
    journal_fd = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(journal_fd)
    journal = OperationJournal(journal_path, acp_turn_opt_in=acp_turn_opt_in)
    records = UnitRecords(
        journal,
        scope_authority=owner.owner_inputs.scope_authority,
        native_evidence=owner.owner_inputs.native_session_evidence,
        verifier=verifier,
        epoch_port=owner.owner_inputs.management_epoch,
        configuration_evidence=owner.owner_inputs.configuration_evidence,
        termination_evidence=owner.owner_inputs.termination_evidence,
        acp_turn_opt_in=acp_turn_opt_in,
    )
    assert journal._initial_file_pristine
    assert journal.preopened_file_identity_valid
    assert records.configuration_evidence is owner.owner_inputs.configuration_evidence
    owner.owner_inputs.native_session_evidence.attach_owner(records)
    view = AgentProviderView(records, verifier)
    original_manager = bind_unit_manager(
        owner.owner_inputs, environment_id=EnvironmentId(namespace), provider_view=view
    )
    ports = AgentOwnerPorts(
        issuer=issuer,
        provider_view=view,
        preparation_context_port=owner,
        unit_manager=original_manager,
    )
    public_manager = owner.bind(ports)
    assert type(original_manager) is OriginalUnitManager
    assert public_manager is owner.manager

    world = SimpleNamespace(
        access=access,
        principal=principal,
        scope=SCOPE,
        now=now,
        owner=owner,
        permission=permission,
        public_manager=public_manager,
        original_manager=original_manager,
        issuer=issuer,
        verifier=verifier,
        records=records,
        journal=journal,
        store=store,
        admission=admission,
        catalog=catalog,
        materials=materials,
        definition=definition,
        profile=profile,
        environment=environment,
        environment_manager=environment_manager,
        leave_unknown=False,
        unknown_release_completed=False,
        access_revoked_cleanup=False,
    )
    try:
        yield world
    finally:
        # Restore the injected test clock solely to settle this fixture's own
        # live process and original records after expiry assertions.
        now[0] = 10.0
        if world.leave_unknown:
            # Preserve the original UNKNOWN claim and live Manager handle. The
            # controlled release-lost-receipt case has already stopped the
            # exact child and released its process handle; only its original
            # EnvironmentUse remains to be explicitly settled here.
            assert world.unknown_release_completed
            for instance, _identity in tuple(original_manager._units.values()):
                factory = instance.channel_factory
                if factory.owned_record is not None and factory.environment is not None:
                    factory.release_environment()
            owner.revoke()
            issuer.close()
        elif world.access_revoked_cleanup:
            # Revoke is permanent for this fixture. Clean only the exact
            # original temporary process/use without manufacturing lifecycle
            # completion in UnitRecords or restoring access authority.
            for instance, _identity in tuple(original_manager._units.values()):
                factory = instance.channel_factory
                record = factory.owned_record
                if record is None:
                    continue
                observation = record.process.observe()
                if observation.state != "exited":
                    code = factory.close(record.entry)
                    observation = record.process.observe()
                    assert observation.state == "exited" and observation.exit_code == code
                record.process.release()
                if hasattr(record.entry, "detach"):
                    record.entry.detach()
                if factory.environment is not None:
                    factory.release_environment()
            owner.revoke()
            issuer.close()
        else:
            try:
                if owner.manager is not None:
                    owner.manager.close(owner.authorization())
            finally:
                owner.revoke()
                issuer.close()
                try:
                    catalog.drain("local-acp-owner", 1)
                    catalog.retire("local-acp-owner", 1)
                finally:
                    try:
                        admission.close()
                    finally:
                        catalog.close()
                        materials.close()
                        store.close()


def test_public_local_unit_executes_and_records_through_original_owners(live_owner):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    assert dict(unit.snapshot())["state"] == "confirmed"
    assert unit.snapshot()["sessionId"].startswith("local-owner-")

    interaction = unit.interaction(world.owner.authorization())
    prompt = [{"type": "text", "text": "local ACP lifecycle"}]
    response = interaction.prompt({"prompt": prompt}, timeout=5)
    assert response["observedPrompt"] == prompt
    assert response["stopReason"] == "end_turn"
    interaction.cancel()

    world.now[0] = world.permission.expires_at + 1
    from ordessa_units.admission.invocation import InvocationAuthorityRefused

    with pytest.raises(InvocationAuthorityRefused):
        interaction.prompt({"prompt": prompt}, timeout=5)
    assert unit.close(world.owner.authorization())["state"] == "refused"
    world.now[0] = 10.0
    interaction.disconnect()

    closed = unit.close(world.owner.authorization())
    assert closed["state"] == "confirmed"
    assert world.public_manager.close(world.owner.authorization())["state"] == "confirmed"

    operations = tuple(world.owner._operations.values())
    assert {entry[3] for entry in operations} == {"prepare", "start", "stop", "release"}
    for _invocation, request, _digest, action in operations:
        operation = world.store.read_operation(request)
        step = world.store.read_operation_step(request, action)
        assert operation is not None and operation.status == "published"
        assert step is not None and step.outcome == "concluded"

    snapshot = world.environment.snapshot
    assert snapshot.active_uses == 0
    assert snapshot.observation.state == "running"


def test_run_permission_refuses_missing_capability_forged_principal_copycap_and_revoke(tmp_path):
    root = tmp_path / "permission-root"
    root.mkdir()
    partial = tuple(item for item in CAPABILITIES if item != "execution.units.prepare")
    restricted = _access_authority(capabilities=partial)
    principal = restricted.authenticate(f"Bearer {BEARER}")
    permission = _run_permission(restricted, principal, root)
    with pytest.raises(AccessError):
        with permission.guard("prepare", clock=lambda: 10.0):
            pytest.fail("missing prepare capability was admitted")

    forged = VerifiedPrincipal(
        principal_id=PRINCIPAL_ID,
        kind="machine",
        grants=(AccessGrant(SCOPE, CAPABILITIES),),
        credential_epoch=principal.credential_epoch,
        legacy_principal=None,
    )
    with pytest.raises(AccessError):
        _run_permission(restricted, forged, root / "forged")

    widened_principal = replace(principal, grants=(AccessGrant(SCOPE, CAPABILITIES),))
    widened = _run_permission(restricted, widened_principal, root / "widened")
    with pytest.raises(AccessError):
        with widened.guard("prepare", clock=lambda: 10.0):
            pytest.fail("copied principal capabilities widened the authority's real grant")

    complete = _access_authority()
    live_principal = complete.authenticate(f"Bearer {BEARER}")
    revocable = _run_permission(complete, live_principal, root / "revoked")
    complete.revoke()
    with pytest.raises(AccessError):
        with revocable.guard("prepare", clock=lambda: 10.0):
            pytest.fail("revoked bearer remained authorized")


def test_run_permission_refuses_expired_and_wrong_environment_scope(tmp_path):
    root = tmp_path / "permission-root"
    root.mkdir()
    authority = _access_authority()
    principal = authority.authenticate(f"Bearer {BEARER}")
    expired = _run_permission(authority, principal, root, expires_at=10.0)
    with pytest.raises(InvocationAuthorityRefused):
        with expired.guard("prepare", clock=lambda: 10.0):
            pytest.fail("expired permission was admitted")

    with pytest.raises(InvocationAuthorityRefused):
        _run_permission(authority, principal, root / "foreign-scope", scope=Scope("other", "project"))


def test_local_authorization_handle_is_opaque_and_bound_to_its_owner(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    with pytest.raises(TypeError):
        copy.copy(authorization)
    with pytest.raises(TypeError):
        copy.deepcopy(authorization)
    with pytest.raises(TypeError):
        pickle.dumps(authorization)

    from ordessa_units.assembly.local_owner import build_local_unit_owner

    other_owner = build_local_unit_owner(
        admission_context=world.admission,
        permission=world.permission,
        environment_instance=world.environment,
        preparation=Preparation(),
        materializer=_materializer,
        environment_sharing=True,
        timeout=5,
        clock=lambda: world.now[0],
    )
    try:
        with pytest.raises(InvocationAuthorityRefused):
            world.public_manager.create(world.owner.spec, other_owner.authorization())
    finally:
        other_owner.revoke()


def test_access_authority_revoke_fences_existing_unit_interaction(live_owner):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    interaction = unit.interaction(world.owner.authorization())
    world.access.revoke()
    with pytest.raises(AccessError):
        interaction.prompt({"prompt": [{"type": "text", "text": "revoked"}]}, timeout=5)
    world.access_revoked_cleanup = True


def test_local_owner_refuses_foreign_profile_environment_and_cross_unit_session(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    foreign_profile = ProfileRevisionRef(
        "env", "other-profile", 1, "sha256:" + "d" * 64
    )
    foreign_spec = UnitSpec(
        world.owner.permission.agent_id,
        foreign_profile,
        {"environmentId": world.environment.identity},
    )
    with pytest.raises(AgentOwnerUnavailable):
        world.public_manager.create(foreign_spec, authorization)

    foreign_environment_permission = replace(
        world.permission, environment_identity="environment/foreign"
    )
    from ordessa_units.assembly.local_owner import build_local_unit_owner

    with pytest.raises(AgentOwnerUnavailable):
        build_local_unit_owner(
            admission_context=world.admission,
            permission=foreign_environment_permission,
            environment_instance=world.environment,
            preparation=Preparation(),
            materializer=_materializer,
            environment_sharing=True,
            timeout=5,
        )

    first = world.public_manager.create(world.owner.spec, authorization)
    second = world.public_manager.create(world.owner.spec, authorization)
    interaction = first.interaction(authorization)
    first_session = first.snapshot()["sessionId"]
    second_session = second.snapshot()["sessionId"]
    assert first_session != second_session
    with pytest.raises(UnitApiRefused):
        interaction.prompt(
            {"sessionId": second_session, "prompt": [{"type": "text", "text": "foreign"}]},
            timeout=5,
        )


def test_unknown_release_is_not_replayed_by_public_unit_close(live_owner, monkeypatch):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    instance = unit._instance
    release = instance.channel_factory.release
    attempts = []
    exited_before_release = []

    def lose_release_receipt(entry):
        attempts.append(entry)
        record = instance.channel_factory.record(entry)
        exited_before_release.append(record.process.observe().state)
        release(entry)
        raise RuntimeError("controlled lost release receipt")

    with monkeypatch.context() as scoped:
        scoped.setattr(instance.channel_factory, "release", lose_release_receipt)
        first = unit.close(world.owner.authorization())
        second = unit.close(world.owner.authorization())

    assert exited_before_release == ["exited"]
    assert first["state"] in {"unknown", "partial", "refused"}
    assert second["state"] in {"unknown", "partial", "refused"}
    assert len(attempts) == 1
    assert world.public_manager.get(unit.identity) is unit
    termination = world.records.owner_read_termination(unit.identity["unitId"], "release")
    assert termination is not None and termination["state"] == "unknown"
    assert world.environment.snapshot.active_uses == 1
    with pytest.raises(GuaranteeUnavailableError):
        world.admission.close()
    assert world.admission.pending()["operationRefs"]
    world.unknown_release_completed = True
    world.leave_unknown = True
