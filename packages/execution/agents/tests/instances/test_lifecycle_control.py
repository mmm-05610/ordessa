"""T018 slice: instance-ref stop/detach through durable control and guarded seams."""
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from ordessa_agents.instances.contracts import InstanceControl
from ordessa_agents.sdk.endpoint import BoundEndpoint, EndpointValueError
from ordessa_agents.sdk.instances import AgentInstanceRef, EndpointRef
from ordessa_agents.sdk.manager import AgentManager, ManagerRefused, Records
from ordessa_agents.sdk.prepare import LaunchObservation, canonical_digest


class Authority:
    def guard_instance_lifecycle(self, invocation, control, *, action):
        from contextlib import nullcontext
        return nullcontext()  # explicit controlled authority fixture only

    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def principal_scope(self, invocation):
        return 'principal:alice'

    def check_read_instance(self, invocation, instance_id):
        if not self.ok:
            raise RuntimeError('read denied')

    def check_instance_lifecycle(self, invocation, control, *, action):
        self.calls.append(action)
        if not self.ok:
            raise RuntimeError('denied')


class Member:
    def __init__(self, *, guarded=True, status='accepted'):
        self.guarded, self.status, self.calls = guarded, status, []

    async def terminate_guarded(self, request_id, force, invocation, *, binding, guard):
        with guard():
            self.calls.append((request_id, force, binding['writerEpoch']))
        return LaunchObservation(operation_ref='endpoint-op/' + request_id, status=self.status)

    async def detach_guarded(self, request_id, invocation, *, binding, guard):
        with guard():
            self.calls.append((request_id, binding['writerEpoch']))
        return LaunchObservation(operation_ref='endpoint-op/' + request_id, status='completed',
                                 facts={'action':'detach','associationDetached': True, 'exitClaimed': False})

    async def terminate(self, *a, **k):
        raise AssertionError('unguarded fallback must never be used')


class Resolver:
    def __init__(self, member):
        self.member = member

    async def resolve(self, ref, invocation):
        return BoundEndpoint(ref, {}, terminate=self.member, detach=self.member)


class DenyAtCut(Authority):
    def __init__(self):
        super().__init__()
        self.count = 0

    def check_read_instance(self, invocation, instance_id):
        return None

    def check_instance_lifecycle(self, invocation, control, *, action):
        self.count += 1
        if self.count > 1:
            raise RuntimeError('revoked at cut')
        return super().check_instance_lifecycle(invocation, control, action=action)


class _NoGuarded(Member):
    terminate_guarded = None
    detach_guarded = None


def control_values(endpoint,instance_id='inst-1'):
    from ordessa_agents.instances.contracts import InstanceBindingMaterial
    from ordessa_agents.sdk.harness import HarnessDescriptor
    from ordessa_agents.profiles import ProfileRevisionRef,encode_revision_ref
    from ordessa_agents.sdk.interactions import BindingProvenance
    from ordessa_agents.sdk.prepare import canonical_digest
    digest='sha256:'+'a'*64
    profile=ProfileRevisionRef('ns-1','fixture-profile',1,digest)
    harness=HarnessDescriptor('fixture',{'environmentNamespace':'ns-1','definitionId':'fixture','revision':'1'},digest,None,(),())
    material=InstanceBindingMaterial(profile,harness,endpoint,digest,digest,None,None,'fixture-source')
    instance=AgentInstanceRef('ns-1',instance_id,material.digest)
    facts={'schemaVersion':'agent-binding-provenance/1','instanceRef':instance.projection(),
        'revision':1,'profileRef':encode_revision_ref(profile),'preparedPlanDigest':digest,
        'endpointRef':endpoint.projection(),'directoryBindingDigest':digest,'sourceRevision':'fixture-source',
        'configurationRefs':[],'capturedAt':'2026-10-19T00:00:00Z'}
    return instance,BindingProvenance.decode({**facts,'observationDigest':canonical_digest(facts)}),material


def graph(tmp_path, *, guarded=True, authority=None, status='accepted'):
    records = Records(tmp_path / 'agents.sqlite')
    endpoint = EndpointRef('issuer', 'endpoint-1', 'rev-1', 'sha256:' + 'd' * 64)
    instance,provenance,material=control_values(endpoint)
    start = SimpleNamespace(principal='principal:alice', operation_ref='agent-start/op-1')
    records.publish_instance_binding(provenance,None,principal_scope='principal:alice',protocol_id=None)
    records.publish_instance_control(provenance, start, 'principal:alice',binding_material=material)
    member = Member(guarded=guarded, status=status) if guarded else _NoGuarded(status=status)
    manager = AgentManager(Resolver(member), records,
                           lifecycle_authority=authority or Authority())
    return manager, records, instance, member


def test_endpoint_ref_is_not_an_online_instance_identity(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, type('I', (), {'owner_scope': None})()))
    assert refused.value.code == 'INVOCATION_PRINCIPAL_UNAVAILABLE'


def test_missing_control_refuses_instead_of_fabricating(tmp_path):
    records = Records(tmp_path / 'agents.sqlite')
    endpoint = EndpointRef('issuer', 'endpoint-1', 'rev-1', 'sha256:' + 'd' * 64)
    instance = AgentInstanceRef('ns-1', 'inst-1', 'sha256:' + 'b' * 64)
    manager = AgentManager(Resolver(Member()), records, lifecycle_authority=Authority())
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'INSTANCE_CONTROL_UNAVAILABLE'


@pytest.mark.parametrize('action',['stop','detach'])
def test_legacy_endpoint_identity_cannot_dispatch(tmp_path,action):
    manager,records,instance,member=graph(tmp_path)
    invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
    before=records._db.total_changes
    with pytest.raises(ManagerRefused,match='INSTANCE_REF_REQUIRED'):
        asyncio.run(getattr(manager,action)('legacy',EndpointRef('issuer','endpoint-1','rev-1','sha256:'+'d'*64),invocation))
    assert member.calls==[] and records._db.total_changes==before


@pytest.mark.parametrize('operation',['claim','mark','complete'])
def test_lifecycle_sqlite_contention_is_fail_fast_and_restores_timeout(tmp_path,operation):
    import time
    manager,records,instance,member=graph(tmp_path)
    arguments=dict(request_id='locked',principal_scope='principal:alice',request_digest='sha256:'+'c'*64,force=False)
    if operation!='claim':
        _,control,payload,record=records.claim_lifecycle(instance,'stop',**arguments)
    original=records._db.execute('PRAGMA busy_timeout').fetchone()[0]
    with sqlite3.connect(records.path,isolation_level=None) as other:
        other.execute('BEGIN IMMEDIATE')
        start= time.monotonic()
        with pytest.raises(ManagerRefused) as refused:
            if operation=='claim':records.claim_lifecycle(instance,'stop',**arguments)
            elif operation=='mark':records.mark_possibly_effected(control,record)
            else:records.complete_lifecycle(control,payload,record,status='unknown',payload={})
        assert refused.value.code=='RECORDS_UNAVAILABLE'
        assert time.monotonic()-start<.5
        assert not records._db.in_transaction
        assert records._db.execute('PRAGMA busy_timeout').fetchone()[0]==original
        other.execute('ROLLBACK')


def test_original_sqlite_commit_failure_rolls_back_claim_and_epoch_before_effect(tmp_path):
    manager,records,instance,member=graph(tmp_path)
    before=records.instance_control(instance)
    # A real deferred SQLite constraint fails at COMMIT, after the original
    # operations INSERT and epoch CAS. No mocked COMMIT/ledger is involved.
    records._db.execute('PRAGMA foreign_keys=ON')
    records._db.execute('CREATE TABLE commit_parent (id INTEGER PRIMARY KEY)')
    records._db.execute('CREATE TABLE commit_child (id INTEGER REFERENCES commit_parent(id) DEFERRABLE INITIALLY DEFERRED)')
    records._db.execute("CREATE TRIGGER reject_stop_commit AFTER INSERT ON operations WHEN NEW.operation='stop' BEGIN INSERT INTO commit_child VALUES(1); END")
    invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('bad-commit',instance,invocation))
    assert refused.value.code=='RECORDS_UNAVAILABLE'
    assert member.calls==[] and not records._db.in_transaction
    assert records.instance_control(instance)==before
    assert records._db.execute("SELECT count(*) FROM operations WHERE operation='stop'").fetchone()==(0,)
    assert records._db.execute('SELECT count(*) FROM commit_child').fetchone()==(0,)


def test_missing_independent_authority_refuses_before_claim(tmp_path):
    manager, records, instance, member = graph(tmp_path, authority=SimpleNamespace())
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'LIFECYCLE_AUTHORITY_UNSUPPORTED'
    assert member.calls == []


def test_check_only_authority_cannot_claim_or_advance_epoch(tmp_path):
    authority=Authority()
    authority.guard_instance_lifecycle=None
    manager,records,instance,member=graph(tmp_path,authority=authority)
    before=records.instance_control(instance);changes=records._db.total_changes
    invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
    with pytest.raises(ManagerRefused,match='LIFECYCLE_AUTHORITY_GUARD_UNSUPPORTED'):
        asyncio.run(manager.stop('no-authority-guard',instance,invocation))
    assert records.instance_control(instance)==before
    assert records._db.total_changes==changes and member.calls==[]


def test_original_authority_guard_serializes_revocation_through_physical_effect(tmp_path):
    from contextlib import contextmanager
    import threading
    lock=threading.RLock();attempted=threading.Event();revoked=threading.Event()
    class LockedAuthority(Authority):
        @contextmanager
        def guard_instance_lifecycle(self,*args,**kwargs):
            with lock:
                if revoked.is_set():raise ManagerRefused('REVOKED')
                yield
    manager,records,instance,member=graph(tmp_path,authority=LockedAuthority())
    workers=[]
    async def physical(request_id,force,invocation,*,binding,guard):
        with guard():
            def revoke():
                attempted.set()
                with lock:revoked.set()
            worker=threading.Thread(target=revoke);workers.append(worker);worker.start()
            assert attempted.wait(1) and not revoked.is_set()
            assert not records._db.in_transaction
            member.calls.append('physical-effect')
        worker.join(1)
        assert not worker.is_alive() and revoked.is_set()
        # Native response completion occurs after the authority lock is released.
        return LaunchObservation('original-resource-op','completed',facts={
            'action':'terminate','cancellation':'requested','processState':'running'})
    member.terminate_guarded=physical
    invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
    try:
        assert asyncio.run(manager.stop('one',instance,invocation)).status=='completed'
        assert member.calls==['physical-effect']
    finally:
        for worker in workers:worker.join(1)


def test_guarded_member_is_mandatory_and_failure_is_not_retried(tmp_path):
    manager, records, instance, member = graph(tmp_path, guarded=False)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'GUARDED_LIFECYCLE_UNAVAILABLE'
    row = records.operation(canonical_digest({'instance': canonical_digest({
        'namespace': instance.namespace, 'instanceId': instance.instance_id}),
        'action': 'stop', 'requestId': 'r1'}), 'stop')
    assert row is None          # support is proven before any claim exists
    control, _ = records.instance_control(instance)
    assert control.writer_epoch == 0


def test_stop_fences_epoch_replays_once_and_keeps_pending_operation(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    observation = asyncio.run(manager.stop('r1', instance, invocation, force=False))
    assert observation.status == 'accepted'
    control, _ = records.instance_control(instance)
    assert control.writer_epoch == 1
    assert control.active_operation_ref is not None and control.association == 'running'
    assert member.calls == [('r1', False, 1)]
    replay = asyncio.run(manager.stop('r1', instance, invocation, force=False))
    assert replay.status == 'accepted' and member.calls == [('r1', False, 1)]
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation, force=True))
    assert refused.value.code == 'REQUEST_CONFLICT'


def test_detach_only_drops_the_association(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    observation = asyncio.run(manager.detach('r1', instance, invocation))
    assert observation.status == 'completed'
    control, _ = records.instance_control(instance)
    assert control.association == 'detached' and control.writer_epoch == 1


def test_two_managers_share_one_durable_effect(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    second = AgentManager(Resolver(member), Records(tmp_path / 'agents.sqlite'),
                          lifecycle_authority=Authority())
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    first = asyncio.run(manager.stop('r1', instance, invocation))
    second_result = asyncio.run(second.stop('r1', instance, invocation))
    assert first.operation_ref == second_result.operation_ref
    assert member.calls == [('r1', False, 1)]


def test_cross_principal_collision_refuses_before_effect(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='bob'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'LIFECYCLE_OWNER_MISMATCH'
    assert member.calls == []


def test_reserved_after_crash_replays_unknown_without_second_effect(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    from ordessa_agents.sdk.prepare import canonical_digest
    digest = canonical_digest({'action': 'stop', 'instance': canonical_digest({
        'namespace': instance.namespace, 'instanceId': instance.instance_id}),
        'force': False, 'endpoint': EndpointRef('issuer', 'endpoint-1', 'rev-1',
                                                'sha256:' + 'd' * 64).projection()})
    records.claim_lifecycle(instance, 'stop', request_id='r1', principal_scope='principal:alice',
                            request_digest=digest, force=False)
    replay = asyncio.run(manager.stop('r1', instance, invocation))
    assert replay.status == 'unknown' and replay.error.code == 'OPERATION_UNCONFIRMED'
    assert member.calls == []


def test_control_seed_keeps_v1_start_and_binding_bytes(tmp_path):
    records = Records(tmp_path / 'legacy.sqlite')
    from types import SimpleNamespace
    endpoint = EndpointRef('issuer', 'endpoint-1', 'rev-1', 'sha256:' + 'd' * 64)
    instance,provenance,material=control_values(endpoint)
    start = SimpleNamespace(principal='principal:alice', operation_ref='agent-start/op-1')
    records.publish_instance_binding(provenance,None,principal_scope='principal:alice',protocol_id=None)
    records.claim('historical-start','start',principal='principal:alice',target='historical',
        request_digest='old-digest',operation_ref='old-start',payload={'history':'unchanged-v1'})
    before = {}
    for table in ('operations',):
        rows = records._db.execute('SELECT request_id,operation,payload FROM operations').fetchall()
        before[table] = rows
    records.publish_instance_control(provenance, start, 'principal:alice',binding_material=material)
    after = records._db.execute('SELECT request_id,operation,payload FROM operations').fetchall()
    added = [row for row in after if row not in before['operations']]
    assert len(added) == 1 and added[0][1] == 'instance-control'


def test_missing_guarded_member_does_not_change_epoch_or_claim(tmp_path):
    manager, records, instance, member = graph(tmp_path, guarded=False)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'GUARDED_LIFECYCLE_UNAVAILABLE'
    control, _ = records.instance_control(instance)
    assert control.writer_epoch == 0 and control.active_operation_ref is None
    assert records._db.execute("SELECT COUNT(*) FROM operations WHERE operation='stop'").fetchone()[0] == 0


def test_physical_guard_rechecks_current_authority_and_preserves_uncertainty(tmp_path):
    authority = DenyAtCut()
    manager, records, instance, member = graph(tmp_path, authority=authority)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'LIFECYCLE_AUTHORITY_REFUSED'
    assert member.calls == []
    replay = asyncio.run(manager.stop('r1', instance, invocation))
    assert replay.status == 'refused'          # zero effect proven before the CAS
    control, _ = records.instance_control(instance)
    assert control.active_operation_ref is None


class _FailAfterGuard(Member):
    async def terminate_guarded(self, request_id, force, invocation, *, binding, guard):
        with guard():
            self.calls.append((request_id, force, binding['writerEpoch']))
        raise OSError('OS signal failed after the cut was entered')


def test_unknown_keeps_the_active_lifecycle_fence(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    failing = _FailAfterGuard()
    manager.resolver.member = failing
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    with pytest.raises(ManagerRefused) as refused:
        asyncio.run(manager.stop('r1', instance, invocation))
    assert refused.value.code == 'OPERATION_UNCONFIRMED'
    control, _ = records.instance_control(instance)
    assert control.active_operation_ref is not None       # UNKNOWN still blocks
    assert control.association == 'running'
    with pytest.raises(ManagerRefused) as blocked:
        asyncio.run(manager.stop('r2', instance, invocation))
    assert blocked.value.code == 'LIFECYCLE_BUSY'
    replay = asyncio.run(manager.stop('r1', instance, invocation))
    assert replay.status == 'unknown'


def test_completion_never_overwrites_a_newer_control_with_stale_bytes(tmp_path):
    manager, records, instance, member = graph(tmp_path)
    invocation = SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))
    digest = canonical_digest({'action': 'stop', 'instance': canonical_digest({
        'namespace': instance.namespace, 'instanceId': instance.instance_id}),
        'force': False, 'endpoint': EndpointRef('issuer', 'endpoint-1', 'rev-1',
                                                'sha256:' + 'd' * 64).projection()})
    state, control, control_payload, record = records.claim_lifecycle(
        instance, 'stop', request_id='r1', principal_scope='principal:alice',
        request_digest=digest, force=False)
    # Simulate a newer writer control (e.g. a concurrent owner CAS) before completion.
    from ordessa_agents.instances.contracts import InstanceControl
    newer = InstanceControl(control.namespace, control.instance_id, control.binding_digest,
                            control.principal_scope, control.endpoint_ref,
                            control.writer_epoch + 1, control.association,
                            control.active_operation_ref, control.active_action)
    from ordessa_agents.sdk.interactions import _digest_of
    control_row=records.instance_control(instance)[1]
    newer_payload = {**control_row.payload,'control': newer.projection()}
    records._db.execute(
        "UPDATE operations SET payload=?, request_digest=? WHERE request_id=? AND operation='instance-control'",
        (__import__('json').dumps(newer_payload, sort_keys=True), _digest_of(newer_payload),
         __import__('ordessa_agents.instances.contracts',
                    fromlist=['instance_control_key']).instance_control_key(instance)))
    with pytest.raises(ManagerRefused) as stale:
        records.complete_lifecycle(control, control_payload, record, status='completed', payload={})
    assert stale.value.code == 'RECORD_CHANGED'
    current, _ = records.instance_control(instance)
    assert current.writer_epoch == newer.writer_epoch       # not overwritten
    assert records.operation(record.request_id, 'stop').status == 'reserved'
