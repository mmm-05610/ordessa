"""A25 GAP-G3: explicit reconcile is an observation only.

Reconcile must read the original endpoint, never restart/reattach/resend, and it
must not record an exit for a detached association. The detach path itself is
covered by ``test_lifecycle_control.py``; this file covers the read-only
observation semantics that the old CLI tests used to exercise.
"""
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.instances.contracts import InstanceBindingMaterial
from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_execution_agents.sdk.endpoint import BoundEndpoint, ProcessObservation
from ordessa_execution_agents.sdk.harness import HarnessDescriptor
from ordessa_execution_agents.sdk.instances import AgentInstanceRef, EndpointRef
from ordessa_execution_agents.sdk.interactions import BindingProvenance
from ordessa_execution_agents.sdk.manager import AgentManager, ManagerRefused, Records
from ordessa_execution_agents.sdk.prepare import canonical_digest


class Authority:
    def __init__(self, *, fail_read=False):
        self.fail_read = fail_read

    def principal_scope(self, invocation):
        return 'principal:alice'

    def check_read_instance(self, invocation, instance_id):
        if self.fail_read:
            raise RuntimeError('read denied')


class Observer:
    def __init__(self, observation):
        self.observation, self.calls = observation, []

    async def observe(self, deadline, invocation):
        self.calls.append('observe')
        return self.observation


class Resolver:
    def __init__(self, observer):
        self.observer = observer

    async def resolve(self, ref, invocation):
        return BoundEndpoint(ref, {}, observe=self.observer)


def instance_and_records(tmp_path, *, association=None):
    records = Records(tmp_path / 'agents.sqlite')
    endpoint = EndpointRef('issuer', 'endpoint-1', 'rev-1', 'sha256:' + 'd' * 64)
    digest = 'sha256:' + 'a' * 64
    profile = ProfileRevisionRef('ns-1', 'fixture-profile', 1, digest)
    harness = HarnessDescriptor('fixture', {'environmentNamespace': 'ns-1',
        'definitionId': 'fixture', 'revision': '1'}, digest, None, (), ())
    material = InstanceBindingMaterial(profile, harness, endpoint, digest, digest, None, None, 'fixture-source')
    instance = AgentInstanceRef('ns-1', 'inst-1', material.digest)
    facts = {'schemaVersion': 'agent-binding-provenance/1', 'instanceRef': instance.projection(),
        'revision': 1, 'profileRef': encode_revision_ref(profile), 'preparedPlanDigest': digest,
        'endpointRef': endpoint.projection(), 'directoryBindingDigest': digest,
        'sourceRevision': 'fixture-source', 'configurationRefs': [], 'capturedAt': '2026-10-19T00:00:00Z'}
    provenance = BindingProvenance.decode({**facts, 'observationDigest': canonical_digest(facts)})
    start = SimpleNamespace(principal='principal:alice', operation_ref='agent-start/op-1')
    records.publish_instance_binding(provenance, None, principal_scope='principal:alice', protocol_id=None)
    records.publish_instance_control(provenance, start, 'principal:alice', binding_material=material)
    return records, instance, provenance


def running():
    return ProcessObservation('running', '2026-10-20T00:00:00Z')


def exited(code=3):
    return ProcessObservation('exited', '2026-10-20T00:00:00Z', exit_code=code)


def manager_for(tmp_path, observation, *, fail_read=False, association=None):
    records, instance, provenance = instance_and_records(tmp_path)
    observer = Observer(observation)
    manager = AgentManager(Resolver(observer), records, lifecycle_authority=Authority(fail_read=fail_read))
    return manager, records, instance, observer


def invocation():
    return SimpleNamespace(owner_scope=SimpleNamespace(kind='principal', ref='alice'))


def test_reconcile_requires_an_original_instance_ref(tmp_path):
    manager, records, instance, observer = manager_for(tmp_path, running())
    before = records._db.total_changes
    with pytest.raises(ManagerRefused, match='INSTANCE_REF_REQUIRED'):
        asyncio.run(manager.reconcile(EndpointRef('issuer', 'endpoint-1', 'rev-1', 'sha256:' + 'd' * 64),
                                      invocation()))
    assert observer.calls == [] and records._db.total_changes == before


def test_reconcile_refuses_an_elapsed_deadline_before_any_observation(tmp_path):
    import time
    manager, records, instance, observer = manager_for(tmp_path, running())
    with pytest.raises(ManagerRefused, match='OBSERVATION_DEADLINE_ELAPSED'):
        asyncio.run(manager.reconcile(instance, invocation(), deadline=time.monotonic() - 1))
    assert observer.calls == []


def test_reconcile_of_an_unrecorded_instance_refuses_instead_of_inventing(tmp_path):
    records = Records(tmp_path / 'agents.sqlite')
    instance = AgentInstanceRef('ns-1', 'missing', 'sha256:' + 'b' * 64)
    manager = AgentManager(Resolver(Observer(running())), records,
                           lifecycle_authority=Authority())
    with pytest.raises(ManagerRefused, match='INSTANCE_CONTROL_UNAVAILABLE'):
        asyncio.run(manager.reconcile(instance, invocation()))


def test_reconcile_refuses_an_invalid_observation_value(tmp_path):
    manager, records, instance, observer = manager_for(tmp_path, {'state': 'exited'})
    with pytest.raises(ManagerRefused, match='OBSERVATION_INVALID'):
        asyncio.run(manager.reconcile(instance, invocation()))


def test_running_observation_is_returned_without_recording_an_exit(tmp_path):
    manager, records, instance, observer = manager_for(tmp_path, running())
    before = records._db.total_changes
    observed = asyncio.run(manager.reconcile(instance, invocation()))
    assert observed.state == 'running'
    assert observer.calls == ['observe'], 'reconcile must observe exactly once'
    assert records._db.total_changes == before, 'a running observation must not mutate records'


def test_exited_observation_records_the_original_exit_without_dispatch(tmp_path):
    manager, records, instance, observer = manager_for(tmp_path, exited(3))
    observed = asyncio.run(manager.reconcile(instance, invocation()))
    assert observed.state == 'exited' and observed.exit_code == 3
    assert observer.calls == ['observe']
    control, row = records.instance_control(instance)
    assert control.association != 'detached'
    # No new lifecycle operation was claimed by reconcile.
    rows = records._db.execute("SELECT count(*) FROM operations WHERE operation IN "
                               "('stop','detach')").fetchone()
    assert rows == (0,)


def test_read_authority_denial_refuses_before_observation(tmp_path):
    manager, records, instance, observer = manager_for(tmp_path, running(),
                                                       fail_read=True)
    with pytest.raises(RuntimeError):
        asyncio.run(manager.reconcile(instance, invocation()))
    assert observer.calls == []
