"""Original live Unit/Node/Profile/Local sources; no model or fake Grant."""
from dataclasses import replace
from pathlib import Path
import copy

import pytest

from agent_tools_fixtures.manager_joint import build_joint_owner
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import IdentityMismatchError, GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import safe_json
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.bindings.publication import decode_node_ref
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.bindings.dispatch_selection import UnitSelectionUnavailable
from ordessa_units.management.manager import UnitManagementRefused
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused


@pytest.fixture
def owner(tmp_path):
    with build_joint_owner(tmp_path, acp_turn_opt_in=True) as j:
        original = j.services.assembly.prepare(RequestKey('env', 'principal', 'prepare'), j.profile, {}, {})
        assert original.status == 'published'
        j.original = original
        j.node = decode_node_ref(original.intent.node_ref)
        j.ref = j.services.nodes.read(j.node)['binding']['harnessUnitRef']
        j.unit = j.manager.find(j.ref)
        j.current.acquired = dict(original.intent.node_ref)
        j.current.evidence = dict(j.ref)
        j.invocation = j.services.authorize_acp_turn_query(RequestKey('env', 'principal', 'query'),
            j.ref, 'future-turn', expected_prompt_input_digest='sha256:'+'a'*64)
        j.directory = DirectoryBindingRef.from_dict(dict(original.intent.context_ref['directoryBindingRef']))
        yield j


def snapshot(j, **changes):
    params = dict(expected_profile_revision=j.profile, expected_directory_binding_ref=j.directory,
                  query_invocation=j.invocation, query_input_digest=j.invocation.facts['inputDigest'])
    params.update(changes)
    return j.services.snapshot_live_unit_selection(j.ref, **params)


def test_actual_sources_resolver_files_and_no_strong_guard(owner, monkeypatch):
    j = owner
    resolver = j.services.assembly._context_port.resolve
    calls = []
    def resolve(*args):
        calls.append(args)
        return resolver(*args)
    monkeypatch.setattr(j.services.assembly._context_port, 'resolve', resolve)
    receipt = snapshot(j)
    assert len(calls) == 1 and calls[0][0] == j.original.request
    assert receipt['contract'] == 'unit-live-source-snapshot/1'
    assert receipt['sourceCut'] == 'observed-live-owner'
    assert receipt['permissionCut'] == 'authorized-read-time'
    assert receipt['currentThroughCommit'] is receipt['liveDispatchAuthorized'] is receipt['checkoutBaselineVerified'] is False
    assert receipt['observedAt'] == receipt['authorizedAt'] == 50
    assert receipt['authorityRevision'] == 'rev-1' and receipt['managementEpoch'] == 0
    assert receipt['unitRef'] == j.ref and receipt['nodeRef'] == j.original.intent.node_ref
    assert receipt['preparationOperationRef'] == j.original.intent.operation_ref
    assert receipt['preparationOperationRevision'] == j.original.revision
    assert receipt['directoryBindingRef'] == j.directory.to_dict()
    assert receipt['localDirectory'] == {'environmentIdentity':j.local.identity,
        'useIdentity':j.unit.channel_factory.environment.identity, 'cwdRelativePath':'cwd',
        'evidenceKind':'bound-file-area-path-check', 'isolation':'none'}
    assert str(Path(j.unit.prepared_agent.harness.launch_spec.cwd).parent) not in safe_json(receipt)
    with pytest.raises(TypeError): receipt['currentThroughCommit'] = True
    # This receipt holds no owner locks/permission across the caller COMMIT.
    j.inputs.authority.allowed = False
    with pytest.raises(InvocationAuthorityRefused): snapshot(j)
    with pytest.raises(UnitSelectionUnavailable):
        with j.services.guard_unit_selection(j.ref, expected_profile_revision=j.profile,
                query_invocation=j.invocation, query_input_digest=j.invocation.facts['inputDigest'], require_live=True):
            raise AssertionError('old strong guard must refuse')
    assert j.events.count('spawn') == 1 and len(j.factory_calls) == 1


@pytest.mark.parametrize('change', ['profile','directory','query_digest','copied_query','authority_revision','epoch','source','cold_manager'])
def test_exact_owner_ref_and_read_permission(owner, change):
    j = owner; params = {}
    if change == 'profile': params['expected_profile_revision'] = replace(j.profile, revision=j.profile.revision+1)
    if change == 'directory': params['expected_directory_binding_ref'] = replace(j.directory, binding_revision=2)
    if change == 'query_digest': params['query_input_digest'] = 'sha256:'+'b'*64
    if change == 'copied_query': params['query_invocation'] = copy.copy(j.invocation)
    if change == 'authority_revision': j.inputs.authority.revision = 'rev-2'
    if change == 'epoch': j.current.epoch = 1
    if change == 'source': j.ref = dict(j.ref, sourceRevision='wrong')
    if change == 'cold_manager': j.manager._units.clear()  # simulate original live scope lost, no relaunch
    with pytest.raises((IdentityMismatchError, InvocationAuthorityRefused, UnitManagementRefused)):
        snapshot(j, **params)
    assert j.events.count('spawn') == 1 and len(j.factory_calls) == 1


@pytest.mark.parametrize('change', ['directory','roots','installation','resolver_refuses'])
def test_re_resolve_original_sources_not_just_equal_expected_dto(owner, monkeypatch, change):
    j = owner
    original = j.services.assembly._context_port.resolve
    def drift(*args):
        value = original(*args)
        if change == 'resolver_refuses': raise PermissionError('private-not-output')
        if change == 'directory': return replace(value, directory_binding_ref=replace(value.directory_binding_ref, binding_revision=2))
        if change == 'installation': return replace(value, source_refs={'installationRef':{
            'environmentNamespace':'env','installationId':'fixture.plugin','sourceRevision':'wrong'}})
        context = dict(value.private_context)
        context['privateRootFacts'] = dict(context['privateRootFacts'], cwd=str(Path(context['privateRootFacts']['cwd']).parent/'other'))
        return replace(value, private_context=context)
    monkeypatch.setattr(j.services.assembly._context_port, 'resolve', drift)
    from ordessa_execution_api.environment import AdmissionRefusedError
    with pytest.raises((GuaranteeUnavailableError, IdentityMismatchError, AdmissionRefusedError)):
        snapshot(j)
    assert j.events.count('spawn') == 1


@pytest.mark.parametrize('change', ['missing_cwd','file_instead_of_cwd','symlink_escape','wrong_use','stopped','released','detached','session_mismatch'])
def test_actual_bound_local_and_termination_not_prepared_dto(owner, tmp_path, monkeypatch, change):
    j = owner
    cwd = Path(j.unit.prepared_agent.harness.launch_spec.cwd)
    if change == 'missing_cwd': cwd.rmdir()
    if change == 'file_instead_of_cwd': cwd.rmdir(); cwd.write_text('not a directory')
    if change == 'symlink_escape':
        cwd.rmdir(); outside=tmp_path/'outside';outside.mkdir();cwd.symlink_to(outside, target_is_directory=True)
    if change == 'wrong_use':
        factory=j.unit.channel_factory
        monkeypatch.setattr(factory, '_record', replace(factory.owned_record, environment_use_identity='foreign'))
    if change == 'detached':
        entry=j.unit.channel_factory.owned_record.entry
        entry.detach()
        assert not entry.has_io_loop
        assert j.unit.channel_factory.owned_record.process.observe().state == 'running'
    if change == 'session_mismatch':
        monkeypatch.setattr(j.unit.channel_factory.owned_record.entry, '_session_id', 'foreign-session')
    if change in ('stopped','released'):
        j.services.lifecycle.stop(RequestKey('env','principal','stop'), j.node, {})
        if change == 'released': j.services.lifecycle.release(RequestKey('env','principal','release'), j.node, {})
    try:
        with pytest.raises((GuaranteeUnavailableError, UnitManagementRefused, UnitLifecycleRefused)):
            snapshot(j)
    finally:
        if change == 'detached':
            # The prior real detach destroyed the byte-IO loop. Preserve that
            # red ordinary-close receipt; cleanup this test's exact process via
            # its public cancel/observe/release, not a replacement IO binding.
            import asyncio
            process = j.unit.channel_factory.owned_record.process
            async def terminate_owned():
                await process.cancel(force=True)
                loop = asyncio.get_running_loop(); deadline=loop.time()+2
                while process.observe().state != 'exited':
                    assert loop.time() < deadline
                    await asyncio.sleep(.01)
                assert process.observe().exit_code is not None
            asyncio.run(terminate_owned())
            facts=j.unit.channel_factory.release(entry)
            assert facts['processIdentity'] == process.identity
            j.unit.channel_factory.release_environment()
            assert j.local.instance.snapshot.active_uses == 0
            # This mechanical fixture cleanup is not a Unit stop/release record.
    assert j.events.count('spawn') == 1


@pytest.mark.parametrize('owner_lock', ['environment','manager','unit'])
def test_snapshot_refuses_busy_original_owner_instead_of_waiting_for_model(owner, owner_lock):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    j=owner
    lock={'environment':j.env._admission_lock, 'manager':j.manager._lock,
          'unit':j.unit._lifecycle_lock}[owner_lock]
    held=Event(); release=Event()
    def hold_original():
        with lock:
            held.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(hold_original)
        assert held.wait(1)
        try:
            with pytest.raises(GuaranteeUnavailableError, match='busy'):
                snapshot(j)
        finally:
            release.set()
        pending.result(timeout=2)
    assert snapshot(j)['currentThroughCommit'] is False
    assert j.events.count('spawn') == 1
