"""Product-host reopening admits a fresh Unit without reviving old claims.

All native ACP traffic in this file is served by a controlled local peer. The
real Server root lock, root binding, Environment store, permission issuer,
original Unit records and public Unit Manager remain in the exercised path.
"""
from dataclasses import replace
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from ordessa_units.public import AgentOwnerUnavailable
from ordessa_units.assembly import UnitRunPermission
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_agents.profiles import ProfileService
from ordessa_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
)
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_agents.harness.definitions import ApplicationTarget
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_units.records.operation_journal import FenceObservation, JournalError, Plan
from ordessa_units.records.unit_records import UnitRecordsRefused
from ordessa_server.composition.configuration.product_selection import create_host_product_composition
from ordessa_server.composition.pi_selection import PiExecutionPorts, PiExecutionSelection
from ordessa_server.composition.product_runtime import build_product_runtime


_CAPABILITIES = tuple('execution.units.' + action for action in (
    'prepare', 'start', 'interaction', 'stop', 'release'))

_ACP_PEER = r'''
import json, sys, uuid
options=[{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low','options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
session_id='reopen-controlled-peer-' + uuid.uuid4().hex
for line in sys.stdin:
    q=json.loads(line); method=q['method']; p=q.get('params',{})
    if method=='initialize': r={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method=='session/new': r={'sessionId':session_id,'configOptions':options}
    elif method=='session/load': r={}
    elif method=='_ordessa/session/configuration': r={'sessionId':session_id,'configOptions':options}
    elif method=='session/prompt':
        prompt=' '.join(part.get('text','') for part in p.get('prompt',[]) if isinstance(part,dict))
        if 'reopen-timeout-unknown' in prompt: continue
        r={'stopReason':'end_turn','observedPrompt':p.get('prompt'),'runtimeOptions':options}
    elif method=='session/cancel': continue
    else: r={}
    print(json.dumps({'jsonrpc':'2.0','id':q.get('id'),'result':r}),flush=True)
'''


@asynccontextmanager
async def _allow_controlled_prompt(_identity, _deadline):
    yield


def _effect_write_guard_factory(unit_ref, operation_ref, input_digest, params):
    from ordessa_agents.harness.transport import EffectWriteGuard
    return EffectWriteGuard(unit_ref, operation_ref, input_digest, params, _allow_controlled_prompt)


class _ControlledPiPreparation:
    """Subprocess fixture only; does not supply or bypass execution authority."""

    harness_id = 'pi'

    def __init__(self, **_fixed_launch):
        self.provider = _fixed_launch['provider']
        self.model = _fixed_launch['model']

    def prepare(self, roots):
        from ordessa_agents.harness.transport import LaunchSpec
        from ordessa_agents.preparation import (
            ConfigurationResources, PreparedHarness, SessionBootstrap,
        )
        return PreparedHarness(
            self.harness_id,
            LaunchSpec.build([sys.executable, '-u', '-c', _ACP_PEER,
                             '--pi-provider', self.provider, '--pi-model', self.model],
                             home=roots['home'], cwd=roots['cwd'],
                             extra_env={'PI_CODING_AGENT_DIR':roots['profile'],
                                        'TMPDIR':roots['tmp']}),
            SessionBootstrap('fresh', roots['cwd']),
            ConfigurationResources('pi-agent-dir', roots['profile'], False),
            {'identity': self.harness_id, 'version': 'fixture-1', 'protocol': 'acp/v1',
             'configurationReadMethod': '_ordessa/session/configuration'},
        )


class _ControlledExistingOpenCodeInput:
    """Test-only credential source that never reads a host file or environment."""

    def __init__(self, source, *, variable_name):
        self.source = source
        self.variable = variable_name

    def read(self):
        return bytearray(b'controlled-test-only-value')


@pytest.fixture
def product_case(tmp_path, monkeypatch):
    """Reproduce the documented product selection fixture without cross-test imports."""
    from ordessa_server.composition import pi_selection as pi_selection_module

    monkeypatch.setattr(pi_selection_module, 'PiAcpHarnessPreparation', _ControlledPiPreparation)
    monkeypatch.setattr(pi_selection_module, 'ExistingOpenCodeInput', _ControlledExistingOpenCodeInput)

    server_root = tmp_path / 'server-root'
    fingerprint = ProtectedFingerprintHmac(
        {'controlled': b'controlled-fingerprint-value-32!!'}, active_key_id='controlled')
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(server_root)
    try:
        context = setup.unit_runtime.context
        namespace = context.environment_namespace
        definition_ref = {'environmentNamespace': namespace,
                          'definitionId': 'pi', 'revision': '1'}
        profiles = ProfileService(UnitProfileAdmission(context))
        profile = profiles.create(
            profile_id='reopen-profile', name='Controlled reopen Profile',
            content={'schemaVersion': '1', 'harnessDefinitionRef': definition_ref,
                     'declarations': [{'declarationId': 'reopen-model',
                       'configurationKind': 'assets.model-provider', 'schemaVersion': '1',
                       'action': 'value', 'requirement': 'required',
                       'payload': {'provider': 'opencode', 'model': 'controlled-model',
                                   'protocol': 'openai-chat', 'endpoint': 'https://opencode.ai/zen/v1'}}]},
            request=profiles.request_key('create-reopen-profile'))
        profile_revision = profiles.get_revision(profile.current_revision).ref
    finally:
        setup.stop()

    local_root = tmp_path / 'local-environment'
    local_root.mkdir()
    environment_store = SQLiteEnvironmentStore(tmp_path / 'environments.sqlite')
    environments = EnvironmentManager(
        store=environment_store,
        providers={'local': LocalEnvironmentResourceProvider(default_root=str(local_root))})
    instance = environments.register('local', str(local_root))
    descriptor = HarnessDefinitionDescriptor(
        'pi', definition_ref, 'sha256:' + 'a' * 64,
        'acp/v1', 'controlled', 'controlled',
        ('prepare', 'start', 'interaction', 'stop', 'release'))
    declaration = HarnessDefinitionDeclaration(
        descriptor, lambda *_args: HarnessInstallationObservation(
            'present', True, 'controlled', 'controlled-installation'))
    selection = PiExecutionSelection(
        'reopen-agent', profile_revision, instance.identity, 'local', 'none', True,
        'reopen-model', 'opencode', 'controlled-model', '/bin/true', 'a' * 64,
        '/bin/true', '/controlled/test/credential-source')
    permission_calls = []

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        permission_calls.append((runtime, admission_context, environment_instance))
        authority = runtime.wire.identity_authority
        scope = Scope(selection.profile_revision.environment_namespace, 'controlled-project')
        authority.replace_grants((AccessGrant(scope, _CAPABILITIES),))
        principal = authority.authenticate('Bearer ' + runtime.token)
        return UnitRunPermission(
            access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(local_root),
            actions=frozenset({'prepare', 'start', 'interaction', 'stop', 'release'}),
            expires_at=datetime.now(timezone.utc).timestamp() + 300)

    ports = PiExecutionPorts(
        environments, declaration, fingerprint, permission_factory,
        ('controlled-model',), None,
        effect_write_guard_factory=_effect_write_guard_factory,
        acp_turn_opt_in=True,
        credential_environment_variable='ORDESSA_REOPEN_TEST_CREDENTIAL')
    return SimpleNamespace(root=server_root, selection=selection, ports=ports,
                           environments=environments, environment_store=environment_store,
                           instance=instance, local_root=local_root,
                           permission_calls=permission_calls)


def _build(case, reopen=None, *, permission_factory=None):
    ports = replace(case.ports,
        agent_journal_reopen=reopen,
        permission_factory=case.ports.permission_factory if permission_factory is None else permission_factory)
    return build_product_runtime(case.root, pi_selection=case.selection, pi_ports=ports)


def _pins(runtime, case):
    from ordessa_server.composition.agent_owner import AgentJournalReopen
    core = Path(runtime.unit_runtime.context.store_path)
    journal = runtime.unit_execution_owner.records.journal.path
    core_info, journal_info = core.stat(), journal.stat()
    return AgentJournalReopen(
        expected_namespace=runtime.unit_runtime.context.environment_namespace,
        root_path=str(case.root),
        root_identity=(case.root.stat().st_dev, case.root.stat().st_ino),
        core_identity=(core_info.st_dev, core_info.st_ino),
        journal_identity=(journal_info.st_dev, journal_info.st_ino))


def _seed_unknown(journal):
    now = datetime.now(timezone.utc)
    plan = Plan(
        'reopen-old-plan',
        ApplicationTarget('old-server', 'old-session', 'old-channel', 1),
        hashlib.sha256(b'old unknown operation').hexdigest(),
        'before-old', 'native-old', 1, 'authorization-old', 'secret-old',
        (now + timedelta(minutes=10)).isoformat())
    journal.register_plan('historical-principal', plan)
    record, created = journal.reserve_new(
        'historical-principal', plan.plan_id, 'historical-operation-key',
        FenceObservation.from_plan(plan), now=now)
    assert created is True and record.result.kind == 'unknown'
    return plan, record


def _operation_bytes(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return db.execute(
            "SELECT state,result_json,fingerprint,plan_id FROM operations WHERE operation_key=?",
            ('historical-operation-key',)).fetchone()


def _journal_content(path):
    # SQLite may checkpoint an already-committed WAL while another connection
    # closes. Compare every schema/row value, including stored JSON bytes,
    # rather than treating page-header bookkeeping as a historical mutation.
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return tuple(connection.iterdump())
    finally:
        connection.close()


def _turn_bytes(path, operation_ref):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return db.execute(
            "SELECT state,body_json,body_digest FROM harness_acp_turn_attempts WHERE operation_ref=?",
            (operation_ref,)).fetchone()


def test_product_reopen_rejects_a_second_live_owner(product_case):
    case = product_case
    runtime = _build(case)
    try:
        reopen = _pins(runtime, case)
        with pytest.raises(RuntimeError, match='^DATA_ROOT_IN_USE$'):
            _build(case, reopen)
        assert runtime.owner.acquired is True
    finally:
        runtime.stop()


@pytest.mark.parametrize('pin_change', ['namespace', 'root-path', 'root-inode', 'core-inode', 'journal-inode'])
def test_product_reopen_rejects_mismatched_expected_identity(product_case, pin_change):
    from ordessa_server.composition.agent_owner import AgentJournalReopen

    case = product_case
    first = _build(case)
    reopen = _pins(first, case)
    first.stop()
    if pin_change == 'namespace':
        bad = replace(reopen, expected_namespace='foreign-environment')
    elif pin_change == 'root-path':
        bad = replace(reopen, root_path=str(case.root.parent/'foreign-root'))
    elif pin_change == 'root-inode':
        bad = replace(reopen, root_identity=(reopen.root_identity[0], reopen.root_identity[1] + 1))
    elif pin_change == 'core-inode':
        bad = replace(reopen, core_identity=(reopen.core_identity[0], reopen.core_identity[1] + 1))
    else:
        bad = replace(reopen, journal_identity=(reopen.journal_identity[0], reopen.journal_identity[1] + 1))
    with pytest.raises(AgentOwnerUnavailable):
        _build(case, bad)
    assert AgentJournalReopen is type(reopen)


@pytest.mark.parametrize('damage', ['extra-schema', 'plan-digest'])
def test_product_reopen_refuses_damaged_or_unsupported_journal_without_repair(product_case, damage):
    from ordessa_server.composition.agent_owner import AgentJournalReopen

    case = product_case
    first = _build(case)
    journal = first.unit_execution_owner.records.journal
    _seed_unknown(journal)
    reopen = _pins(first, case)
    path = journal.path
    first.stop()
    with sqlite3.connect(path) as db:
        if damage == 'extra-schema':
            db.execute('CREATE TABLE foreign_extension(value TEXT)')
        else:
            db.execute("UPDATE plans SET fingerprint=? WHERE plan_id=?", ('0' * 64, 'reopen-old-plan'))
    before = _journal_content(path)
    with pytest.raises(AgentOwnerUnavailable):
        _build(case, reopen)
    assert _journal_content(path) == before
    assert isinstance(reopen, AgentJournalReopen)


def test_product_reopen_refuses_a_hardlinked_journal(product_case):
    case = product_case
    first = _build(case)
    reopen = _pins(first, case)
    path = first.unit_execution_owner.records.journal.path
    first.stop()
    alias = case.root.parent/'journal-alias.sqlite'
    alias.hardlink_to(path)
    before = _journal_content(path)
    with pytest.raises(AgentOwnerUnavailable, match='file identity differs'):
        _build(case, reopen)
    assert _journal_content(path) == before
    assert path.stat().st_nlink == 2


def test_product_reopen_rechecks_current_runtime_permission_before_any_unit_claim(product_case):
    from ordessa_interfaces.system_access.contracts.transport import AccessError

    case = product_case
    first = _build(case)
    reopen = _pins(first, case)
    first.stop()

    def no_current_grant(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        scope = Scope(selection.profile_revision.environment_namespace, 'controlled-project')
        authority.replace_grants(())
        principal = authority.authenticate('Bearer ' + runtime.token)
        return UnitRunPermission(
            access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(case.local_root),
            actions=frozenset({'prepare', 'start', 'interaction', 'stop', 'release'}),
            expires_at=datetime.now(timezone.utc).timestamp() + 300)

    path = case.root / 'state/agent-owner/operations.sqlite'
    before = _journal_content(path)
    with pytest.raises(AccessError, match='ACCESS_DENIED'):
        _build(case, reopen, permission_factory=no_current_grant)
    assert _journal_content(path) == before
    assert case.instance.snapshot.active_uses == 0


def test_reopened_journal_preserves_legacy_unknown_fence(product_case):
    from ordessa_server.composition.runtime import RuntimeCompositionUnavailable
    case = product_case
    first = _build(case)
    journal = first.unit_execution_owner.records.journal
    _plan, _record = _seed_unknown(journal)
    before = _operation_bytes(journal.path)
    reopen = _pins(first, case)
    first.stop()

    reopened = _build(case, reopen)
    try:
        owner = reopened.unit_execution_owner
        with pytest.raises(UnitRecordsRefused, match='legacy unresolved operation retains configuration fence'):
            reopened.units.create(owner.spec, owner.authorization())
        assert reopened.units.list() == ()
        assert case.instance.snapshot.active_uses == 0
    finally:
        # The failed prepare is deliberately retained by the original manager;
        # do not turn this negative fixture into a fabricated clean shutdown.
        with pytest.raises(RuntimeCompositionUnavailable, match='Unit close is unknown'):
            reopened.stop()
        assert reopened.owner.acquired is True
    assert _operation_bytes(journal.path) == before


def test_valid_reopen_admits_fresh_unit_preserving_real_acp_unknown_and_shared_use(product_case, monkeypatch):
    from ordessa_units.records.unit_records import UnitRecords
    from ordessa_agents.harness.transport import RequestTimeout

    case = product_case
    first = _build(case)
    original_owner = first.unit_execution_owner
    original_records = original_owner.records
    journal = original_records.journal
    turn_ref = 'historical-acp-timeout'

    captured = []
    original_begin_session = UnitRecords.begin_session

    def capture_begin_session(records, *args, **kwargs):
        ticket = original_begin_session(records, *args, **kwargs)
        if records is original_records:
            captured.append(('session', ticket))
        return ticket

    monkeypatch.setattr(UnitRecords, 'begin_session', capture_begin_session)
    old_authorization = original_owner.authorization()
    old_unit = first.units.create(original_owner.spec, old_authorization)
    old_unit_id = old_unit.identity['unitId']
    old_session_id = old_unit.snapshot()['sessionId']
    old_tickets = dict(captured)
    # The actual Unit lifecycle issues a session RecordTicket; begin_unit is
    # not part of this public path, so retain only the real ticket.
    assert set(old_tickets) == {'session'}
    native = original_owner.native_unit(old_unit, old_authorization)
    interaction_lease = original_owner.authorize('interaction', old_unit, old_authorization)
    with pytest.raises(RequestTimeout):
        native.prompt(old_unit.identity, interaction_lease, operation_ref=turn_ref, timeout=0.1,
                      prompt=[{'type': 'text', 'text': 'reopen-timeout-unknown'}])
    turn_before = _turn_bytes(journal.path, turn_ref)
    assert turn_before is not None and turn_before[0] == 'unknown'
    assert first.units.close(old_authorization)['state'] == 'confirmed'

    old_journal_path = journal.path
    reopen = _pins(first, case)
    first.stop()

    # Keep one real, shared Environment Use alive across the reopen.
    historical_use = case.instance.acquire('historical-owner', sharing=True)
    try:
        use_id = historical_use.identity
        with case.environment_store.transaction() as connection:
            use_before = tuple(connection.execute(
                'SELECT identity,environment_id,generation,owner_id,sharing,phase,pending '
                'FROM environment_uses WHERE identity=?', (use_id,)).fetchone())
        assert use_before[5] == 'active' and use_before[4] == 1

        reopened = _build(case, reopen)
        try:
            owner = reopened.unit_execution_owner
            records = owner.records
            with pytest.raises(UnitRecordsRefused, match='historical Unit stays fenced'):
                records.owner_read_unit(old_unit_id)
            with pytest.raises(UnitRecordsRefused, match='not owned by this journal'):
                records.record_session(old_tickets['session'], expected_source_revision=2, state='unknown')
            with pytest.raises(JournalError, match='fresh Unit claims'):
                records.journal.register_plan('new-principal', Plan(
                    'reopen-forbidden-plan', ApplicationTarget(
                        'new-server', 'new-session', 'new-channel', 2),
                    hashlib.sha256(b'new operation').hexdigest(), 'before', 'native', 2,
                    'authorization', 'secret', (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()))

            fresh = reopened.units.create(owner.spec, owner.authorization())
            assert fresh.identity['unitId'] != old_unit_id
            assert fresh.snapshot()['sessionId'] != old_session_id
            assert reopened.units.close(owner.authorization())['state'] == 'confirmed'
            assert _turn_bytes(old_journal_path, turn_ref) == turn_before
            assert case.instance.snapshot.active_uses == 1
        finally:
            reopened.stop()

        with case.environment_store.transaction() as connection:
            use_after = tuple(connection.execute(
                'SELECT identity,environment_id,generation,owner_id,sharing,phase,pending '
                'FROM environment_uses WHERE identity=?', (use_id,)).fetchone())
        assert use_after == use_before
    finally:
        historical_use.release()
