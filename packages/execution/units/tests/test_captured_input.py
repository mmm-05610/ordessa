"""Captured input on real Unit/access/SQLite/ACP owners; controlled peer only."""
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.public import (
    ManagedUnitInputs, UnitTextCapture, UnitWorkspaceExecutionEvidence,
    UNIT_TEXT_CAPTURE_VERSION, CapturedInputRef, UnitCapturedInputRefused, UnitCapturedInputPending)
from ordessa_units.api.unit import Unit
from test_local_owner import live_owner

pytestmark = pytest.mark.parametrize('live_owner', [{
    'acp_turn_opt_in': True, 'defer_effect_write_guard_factory': True}], indirect=True)


class CaptureOwner:
    capture = None
    def read_content(self, ref, principal):
        return self.capture if (self.capture is not None and self.capture.ref == ref
                               and principal == 'fixture-principal') else None


class WorkspaceOwner:
    """Controlled authority with an actual async revoke/write synchronization cut."""
    def __init__(self):
        import asyncio
        self.lock = asyncio.Lock()
        self.revoked = False
        self.held = False
        self.entered = self.released = 0
        self.before_guard = None

    def authorize_execute(self, request, unit_ref, operation_ref, capture_ref):
        if self.revoked:
            raise UnitCapturedInputRefused('controlled Workspace execute revoked')
        return UnitWorkspaceExecutionEvidence(request.environment_namespace,
            request.principal_scope, unit_ref, operation_ref, capture_ref, 'controlled-workspace-proof')

    @asynccontextmanager
    async def guard_execute(self, evidence, identity, deadline):
        import asyncio
        async with self.lock:
            if self.before_guard is not None:
                self.before_guard()
            if self.revoked:
                raise UnitCapturedInputRefused('controlled Workspace execute revoked at write')
            assert identity['unitRef'] == evidence.unit_ref
            assert identity['operationRef'] == evidence.operation_ref
            assert deadline > asyncio.get_running_loop().time()
            self.held = True
            self.entered += 1
            try:
                yield evidence
            finally:
                self.held = False
                self.released += 1


@pytest.fixture
def managed(live_owner):
    world = live_owner
    capture, workspace = CaptureOwner(), WorkspaceOwner()
    service = ManagedUnitInputs(world.owner, capture_content=capture, workspace_execution=workspace)
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = world.owner.native_unit(unit, authorization)
    client = instance.channel_factory.owned_record.entry
    process = instance.channel_factory.owned_record.process
    writes = []
    original_write = process.write_stdin
    async def write(data, *, timeout=None):
        raw = json.loads(data)
        if raw.get('method') == 'session/prompt':
            assert workspace.held and workspace.lock.locked()
            writes.append(raw)
        return await original_write(data, timeout=timeout)
    process.write_stdin = write
    envelope = {'schemaVersion': UNIT_TEXT_CAPTURE_VERSION, 'text': 'controlled original\n原文'}
    digest = 'sha256:' + hashlib.sha256(safe_json(envelope).encode()).hexdigest()
    ref = CapturedInputRef('env', 'capture-1', 1, digest)
    capture.capture = UnitTextCapture(ref, unit.identity, envelope,
        {'attachmentDigests': (), 'configOperationIds': (), 'handles': (), 'baseRevision': None})
    request = RequestKey('env', 'fixture-principal', 'input-request-1')
    value = SimpleNamespace(world=world, service=service, capture=capture, workspace=workspace,
        authorization=authorization, unit=unit, instance=instance, client=client,
        writes=writes, ref=ref, request=request)
    try:
        yield value
    finally:
        if any(operation.intent.kind == 'unit-captured-input'
               for operation in world.store.pending_operations('env')):
            # Preserve unresolved durable truth; clean only this test's exact
            # process/use, without inventing a terminal receipt or clearing it.
            world.access_revoked_cleanup = True


def test_managed_input_uses_same_environment_issuer_records_and_original_client(managed):
    """Migrated original Codex acceptance/replay/new-key/query positive case."""
    m = managed
    assert m.service.records is m.world.records is m.instance.records
    assert m.service.verifier is m.world.verifier
    assert m.service.verifier._verify.__self__ is m.world.issuer
    accepted = m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert accepted.state == 'accepted' and accepted.native_receipt_ref
    assert len(m.writes) == 1 and not m.client._channel._channel._unresolved
    assert m.instance.channel_factory.owned_record.entry is m.client
    assert m.writes[0]['params']['prompt'] == [{'type': 'text', 'text': 'controlled original\n原文'}]
    replay = m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert replay == accepted and len(m.writes) == 1
    with pytest.raises(UnitCapturedInputPending, match='unresolved attempt'):
        m.service.submit(RequestKey('env', 'fixture-principal', 'input-request-2'),
                         m.unit, m.ref, m.authorization, timeout=5)
    assert len(m.writes) == 1
    completed = m.service.query(m.request, m.authorization)
    assert completed.state == 'completed' and completed.terminal_evidence_ref
    assert len(m.writes) == 1
    assert m.world.store.read_operation(m.request).status == 'published'
    assert m.workspace.entered == m.workspace.released == 1 and not m.workspace.held
    assert m.service.query(m.request, m.authorization) == completed
    assert m.service.submit(m.request, m.unit, m.ref, m.authorization) == accepted
    assert len(m.writes) == 1


def test_copied_unit_view_and_other_principal_never_reserve_or_write(managed):
    m = managed
    copied = Unit(m.unit._assembly, m.unit._instance)
    from ordessa_units.admission.owner_selection import AgentOwnerUnavailable
    with pytest.raises(AgentOwnerUnavailable, match='Exact retained'):
        m.service.submit(m.request, copied, m.ref, m.authorization)
    with pytest.raises(UnitCapturedInputRefused, match='permission'):
        m.service.submit(RequestKey('env', 'other', 'input'), m.unit, m.ref, m.authorization)
    assert m.world.store.read_operation(m.request) is None and not m.writes


@pytest.mark.parametrize('damage', ['digest', 'unit', 'attachments'])
def test_changed_or_lossy_capture_is_rejected_before_reservation(managed, damage):
    m = managed
    capture = m.capture.capture
    if damage == 'digest':
        capture = replace(capture, envelope={'schemaVersion': UNIT_TEXT_CAPTURE_VERSION, 'text': 'changed'})
    elif damage == 'unit':
        capture = replace(capture, unit_ref={**dict(m.unit.identity), 'sourceRevision': 'forged'})
    else:
        capture = replace(capture, metadata={**dict(capture.metadata), 'attachmentDigests': ('sha256:x',)})
    m.capture.capture = capture
    with pytest.raises(UnitCapturedInputRefused):
        m.service.submit(m.request, m.unit, m.ref, m.authorization)
    assert m.world.store.read_operation(m.request) is None and not m.writes


def test_workspace_revocation_at_actual_write_prevents_bytes_and_replay(managed):
    m = managed
    m.workspace.before_guard = lambda: setattr(m.workspace, 'revoked', True)
    with pytest.raises(UnitCapturedInputRefused, match='Workspace execute revoked at write'):
        m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert not m.writes
    assert m.service.submit(m.request, m.unit, m.ref, m.authorization).state == 'unknown'
    assert not m.writes and not m.workspace.held


def test_capture_change_during_workspace_acquisition_prevents_bytes(managed):
    m = managed
    m.workspace.before_guard = lambda: setattr(m.capture, 'capture', replace(m.capture.capture,
        envelope={'schemaVersion': UNIT_TEXT_CAPTURE_VERSION, 'text': 'changed after prepare'}))
    with pytest.raises(UnitCapturedInputRefused, match='capture digest'):
        m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert not m.writes and m.workspace.entered == m.workspace.released == 1


def test_core_receipt_failure_recovers_by_original_query_without_resend(managed, monkeypatch):
    m = managed
    original = m.world.store.record_operation_step
    fail = [True]
    def record(*args, **kwargs):
        if args[5] == 'concluded' and fail[0]:
            fail[0] = False
            raise OSError('controlled core receipt failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(m.world.store, 'record_operation_step', record)
    with pytest.raises(OSError, match='core receipt failure'):
        m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert len(m.writes) == 1
    assert m.service.submit(m.request, m.unit, m.ref, m.authorization).state == 'unknown'
    completed = m.service.query(m.request, m.authorization)
    assert completed.state == 'completed' and completed.terminal_evidence_ref
    assert len(m.writes) == 1


def test_query_after_release_keeps_original_receipt_and_has_no_live_dispatch(managed):
    m = managed
    m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert m.unit.close(m.authorization)['state'] == 'confirmed'
    m.instance.prompt_recorded = lambda *a, **kw: pytest.fail('query dispatched a prompt')
    result = m.service.query(m.request, m.authorization)
    assert result.state == 'completed' and len(m.writes) == 1


def test_same_request_cannot_change_capture_or_unit(managed):
    m = managed
    m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    with pytest.raises(UnitCapturedInputRefused, match='another captured Unit input'):
        m.service.submit(m.request, m.unit, replace(m.ref, capture_revision=2), m.authorization)
    assert m.service.query(m.request, m.authorization).state == 'completed'
    assert len(m.writes) == 1


def test_claim_before_acp_record_is_unknown_and_never_replayed(managed, monkeypatch):
    m = managed
    def fail_before_record(*args, **kwargs):
        raise OSError('controlled loss after Core claim and before ACP reserve')
    monkeypatch.setattr(m.instance, 'prompt_recorded', fail_before_record)
    with pytest.raises(OSError, match='before ACP reserve'):
        m.service.submit(m.request, m.unit, m.ref, m.authorization)
    assert m.service.submit(m.request, m.unit, m.ref, m.authorization).state == 'unknown'
    assert m.service.query(m.request, m.authorization).state == 'unknown'
    assert m.world.store.read_operation(m.request).status != 'published'
    assert not m.writes
    with m.world.journal._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_acp_turn_attempts').fetchone()[0] == 0


def test_permission_expiry_during_workspace_acquisition_blocks_actual_write(managed):
    from ordessa_units.admission.invocation import InvocationAuthorityRefused
    m = managed
    m.workspace.before_guard = lambda: m.world.now.__setitem__(0, m.world.permission.expires_at + 1)
    with pytest.raises(InvocationAuthorityRefused, match='expired'):
        m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    assert not m.writes and not m.workspace.held
    assert m.workspace.entered == m.workspace.released == 1


def test_query_rechecks_real_access_revocation(managed):
    from ordessa_interfaces.system_access.contracts.transport import AccessError
    m = managed
    m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    m.world.access.revoke()
    m.world.access_revoked_cleanup = True
    with pytest.raises(AccessError):
        m.service.query(m.request, m.authorization)
    assert len(m.writes) == 1
    assert m.world.store.read_operation(m.request).status != 'published'


def test_cannot_replace_the_original_selected_guard(managed):
    from ordessa_units.admission.owner_selection import AgentOwnerUnavailable
    m = managed
    with pytest.raises(AgentOwnerUnavailable, match='exactly once'):
        ManagedUnitInputs(m.world.owner, capture_content=m.capture, workspace_execution=m.workspace)
    assert not m.writes


def test_direct_prompt_cannot_borrow_captured_operation_guard(managed):
    from ordessa_execution_agents.harness.transport import EffectWriteRefused
    m = managed
    lease = m.world.owner.authorize('interaction', m.unit, m.authorization)
    with pytest.raises(EffectWriteRefused, match='operation source'):
        m.instance.prompt_recorded(m.unit.identity, lease, operation_ref='unrelated-operation',
            prompt=[{'type': 'text', 'text': 'not a captured input'}])
    assert not m.writes


def test_concurrent_request_keys_cannot_cross_the_same_capture_fence(managed, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from ordessa_infrastructure.database.records import DomainRevisionConflict
    m = managed
    barrier, lock = Barrier(2), Lock()
    reads = [0]
    original = m.capture.read_content
    def read(ref, principal):
        with lock:
            reads[0] += 1
            wait = reads[0] <= 2
        if wait:
            barrier.wait(timeout=3)
        return original(ref, principal)
    monkeypatch.setattr(m.capture, 'read_content', read)
    requests = [m.request, RequestKey('env', 'fixture-principal', 'input-request-2')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(m.service.submit, req, m.unit, m.ref, m.authorization, timeout=5)
                   for req in requests]
        accepted, refused = [], []
        for request, future in zip(requests, futures):
            try:
                accepted.append((request, future.result(timeout=8)))
            except (UnitCapturedInputPending, DomainRevisionConflict) as error:
                refused.append(error)
    assert len(accepted) == len(refused) == 1
    assert accepted[0][1].state == 'accepted' and len(m.writes) == 1
    assert m.service.query(accepted[0][0], m.authorization).state == 'completed'
    assert m.workspace.entered == m.workspace.released == 1


def test_real_host_revocation_waits_for_the_admitted_byte_write(managed):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    m = managed
    entered, allow_write, revoked = Event(), Event(), Event()
    process = m.instance.channel_factory.owned_record.process
    original = process.write_stdin
    async def held_write(data, *, timeout=None):
        if json.loads(data).get('method') == 'session/prompt':
            assert m.workspace.held
            entered.set()
            while not allow_write.is_set():
                await asyncio.sleep(.005)
            assert not revoked.is_set()
        return await original(data, timeout=timeout)
    process.write_stdin = held_write
    def revoke():
        m.world.access.revoke()
        revoked.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        sent = pool.submit(m.service.submit, m.request, m.unit, m.ref, m.authorization, timeout=5)
        assert entered.wait(3)
        revoked_future = pool.submit(revoke)
        try:
            assert not revoked_future.done()
        finally:
            allow_write.set()
        assert sent.result(timeout=7).state == 'accepted'
        revoked_future.result(timeout=3)
    assert revoked.is_set() and len(m.writes) == 1
    m.world.access_revoked_cleanup = True


@pytest.mark.parametrize("stage", ["before", "after"])
def test_sdk_thread_reentrant_revocation_cannot_report_acceptance(managed, stage):
    from ordessa_interfaces.system_access.contracts.transport import AccessError
    m = managed
    process = m.instance.channel_factory.owned_record.process
    original = process.write_stdin
    async def reentrant_revoke(data, *, timeout=None):
        prompt = json.loads(data).get('method') == 'session/prompt'
        if prompt and stage == 'before':
            m.world.access.revoke()
        written = await original(data, timeout=timeout)
        if prompt and stage == 'after':
            m.world.access.revoke()
        return written
    process.write_stdin = reentrant_revoke
    m.world.access_revoked_cleanup = True
    with pytest.raises(AccessError):
        m.service.submit(m.request, m.unit, m.ref, m.authorization, timeout=5)
    step = m.world.store.read_operation_step(m.request, 'prompt')
    assert step.outcome == 'unknown' and not step.evidence
    assert len(m.writes) == (0 if stage == 'before' else 1) and not m.workspace.held
