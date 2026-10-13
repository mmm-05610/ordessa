"""Original Unit/Node query composition with an explicit read-time permission cut.

No checkout inference, effect Grant, replacement records or transport lease.
Current authority ports revalidate reads but expose no shared revoke-writer guard;
therefore they cannot promise current-through-external-COMMIT live selection.
"""
from contextlib import contextmanager
import hashlib
import json

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    GuaranteeUnavailableError,
    IdentityMismatchError,
)
from ordessa_execution_api.environment.operations import OperationIntent, StepIntent, safe_json, sealed_mapping
from ordessa_execution_agents.profiles import ProfileRevisionRef, decode_revision_ref, encode_revision_ref
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.bindings.publication import decode_node_ref


class UnitSelectionUnavailable(GuaranteeUnavailableError):
    code = 'UNIT_SELECTION_SYNC_UNAVAILABLE'


def _owner(services):
    env = services.nodes._environment
    bundle = getattr(env, '_agent_owner_ports', None)
    if bundle is None or getattr(env, '_agent_services', None) is not services:
        raise GuaranteeUnavailableError('original Unit owner bundle is unavailable')
    bundle.validate_for(env)
    if type(bundle.issuer) is not InvocationIssuer:
        raise GuaranteeUnavailableError('original invocation issuer is unavailable')
    return env, bundle.provider_view.records, bundle.issuer


def _source(services, records, unit_ref):
    """Owner-only provenance read; caller permission is checked separately."""
    if not isinstance(unit_ref, dict) and not hasattr(unit_ref, 'items'):
        raise IdentityMismatchError('complete Unit reference required')
    if set(unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}:
        raise IdentityMismatchError('complete Unit reference required')
    unit = records.owner_read_unit(unit_ref['unitId'])
    if safe_json(unit.public_ref) != safe_json(unit_ref):
        raise IdentityMismatchError('Unit source differs from original owner')
    node = services.nodes.read(decode_node_ref(unit.facts['nodeRef']))
    if node is None or safe_json(node['binding']['harnessUnitRef']) != safe_json(unit_ref):
        raise IdentityMismatchError('original Node does not bind this Unit')
    env = services.nodes._environment
    correlation = json.loads(unit.facts['correlation'])
    request = correlation['request']
    original = env._store.read_operation(RequestKey(
        request['environmentNamespace'], request['principalScope'], request['requestId']))
    if (original is None or original.status != 'published'
            or original.intent.kind != 'agent-preparation'
            or original.intent.operation_ref != correlation['operationRef']
            or safe_json(original.intent.node_ref) != safe_json(unit.facts['nodeRef'])
            or safe_json(node['binding']['profileSnapshotRef']) != safe_json(original.intent.profile_snapshot_ref)
            or safe_json(node['binding']['harnessProviderRef']) != safe_json(unit.facts['providerRef'])):
        raise IdentityMismatchError('original preparation/Node provenance differs')
    step = next((s for s in original.intent.steps if s.step_id == correlation['stepId']), None)
    if (step is None or step.input_digest != unit.facts['inputDigest']
            or step.management_epoch != unit.facts['managementEpoch']
            or safe_json(step.pinned_provider_ref) != safe_json(unit.facts['providerRef'])):
        raise IdentityMismatchError('original preparation step differs from Unit')
    return unit, node, original


def authorize_acp_turn_query(services, request, unit_ref, operation_ref, *, expected_prompt_input_digest):
    env, records, issuer = _owner(services)
    with env._admission_lock:
        if type(request) is not RequestKey:
            raise IdentityMismatchError('original request identity required')
        services.nodes._permission(request=request)
        if (type(operation_ref) is not str or not operation_ref or len(operation_ref) > 512
                or any(ord(c) < 32 for c in operation_ref)
                or type(expected_prompt_input_digest) is not str
                or not expected_prompt_input_digest.startswith('sha256:')
                or len(expected_prompt_input_digest) != 71
                or any(c not in '0123456789abcdef' for c in expected_prompt_input_digest[7:])):
            raise IdentityMismatchError('exact ACP operation and prompt digest required')
        unit, node, original = _source(services, records, unit_ref)
        digest = records.acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest)
        # Drained providers may serve original acquired-target reads, but only
        # if the original current-state owner supplies that acquisition proof.
        binding = {'action': 'query', 'targetRef': unit.facts['nodeRef'],
                   'delegationRef': None, 'cleanup': True}
        grant = issuer._refused_call(lambda: issuer._authority.authorize(
            request, ('query',), binding['targetRef'], None))
        issuer._check_grant(grant, request, 'query', binding)
        issuer._revalidate(grant, request, 'query', binding)
        context = {'environmentNamespace': env.environment_id,
                   'directoryBindingRef': original.intent.context_ref['directoryBindingRef'],
                   'invocationBindings': {'read': binding},
                   'acpTurnRead': {'unitRef': unit_ref, 'operationRef': operation_ref,
                                  'expectedPromptInputDigest': expected_prompt_input_digest}}
        # Deterministic identity in the existing operation store. Reusing a
        # request for another fullUnit/op/input fails original digest/intent CAS.
        query_id = 'acp-read-' + hashlib.sha256(safe_json({
            'request': {'environmentNamespace': request.environment_namespace,
                        'principalScope': request.principal_scope, 'requestId': request.request_id},
            'inputDigest': digest}).encode()).hexdigest()[:48]
        step = StepIntent('read', unit.facts['providerRef'], digest, query_id + '.read',
                          management_epoch=original.intent.management_epoch)
        intent = OperationIntent(query_id, 'unit-acp-query', original.intent.profile_snapshot_ref,
                                 context, (step,), original.intent.node_ref, original.intent.management_epoch)
        env._store.reserve_operation(request, digest, intent)
        return issuer.issue_query(request, digest, 'read')


@contextmanager
def guard_unit_selection(services, unit_ref, *, expected_profile_revision,
                         query_invocation, query_input_digest, require_live):
    env, records, issuer = _owner(services)
    if type(require_live) is not bool:
        raise IdentityMismatchError('selection mode must be an explicit bool')
    if require_live:
        # No guessed lock can synchronize direct Unit stop, Environment policy
        # and arbitrary authority/current-state writers. Never return a weaker
        # historical receipt to the existing current-through-COMMIT contract.
        raise UnitSelectionUnavailable('original authority/current-state ports provide no live COMMIT guard')
    with env._admission_lock:
        unit = records.resolve_unit_reference(unit_ref, query_invocation, input_digest=query_input_digest)
        facts = query_invocation.facts
        read = facts['contextRef'].get('acpTurnRead')
        if (read is None or set(read) != {'unitRef', 'operationRef', 'expectedPromptInputDigest'}
                or safe_json(read['unitRef']) != safe_json(unit_ref)
                or query_input_digest != records.acp_turn_query_digest(
                    unit_ref, read['operationRef'], read['expectedPromptInputDigest'])):
            raise IdentityMismatchError('selection requires the exact original ACP read recipe')
        request = facts['request']
        services.nodes._permission(request=RequestKey(
            request['environmentNamespace'], request['principalScope'], request['requestId']))
        _, node, original = _source(services, records, unit_ref)
        actual_profile = decode_revision_ref(dict(original.intent.profile_snapshot_ref))
        if type(expected_profile_revision) is not ProfileRevisionRef or expected_profile_revision != actual_profile:
            raise IdentityMismatchError('fixed complete Profile revision differs from original preparation')
        services.profiles.get_revision(actual_profile)
        # Revalidate last, after the immutable source reads. This timestamp and
        # original grant/epoch versions describe this permission cut only.
        verified = records.verifier.verify_continuation(query_invocation, 'query',
            unit.facts['providerRef'], unit.facts['nodeRef'], query_input_digest)
        receipt = sealed_mapping({
            'contract': 'unit-selection-read-cut/1', 'permissionCut': 'authorized-read-time',
            'currentThroughCommit': False, 'liveDispatchAuthorized': False,
            'authorizedAt': issuer._now(), 'authorityRevision': verified['grant']['authorityRevision'],
            'managementEpoch': verified['managementEpoch'],
            'publicationRevision': node['publicationRevision'],
            'queryOperationRef': verified['operationRef'], 'queryInputDigest': query_input_digest,
            'unitRef': unit.public_ref, 'profileRevision': encode_revision_ref(actual_profile),
        })
    # Deliberately release original locks before the consumer's external TX.
    # The receipt says read-time; Engineering must check its current admissions.
    yield receipt


def snapshot_live_unit_selection(services, unit_ref, *, expected_profile_revision,
                                 expected_directory_binding_ref, query_invocation,
                                 query_input_digest):
    """One authorized original live-source observation, never an external TX guard."""
    import os
    from ordessa_units.bindings.contracts import DirectoryBindingRef
    from ordessa_units.lifecycle.unit_lifecycle import same_reference
    from ordessa_units.management.manager import UnitManager

    env, records, issuer = _owner(services)
    manager = services.unit_manager
    if (type(manager) is not UnitManager or manager is not services.assembly._unit_manager
            or manager is not env._agent_owner_ports.unit_manager
            or manager.records is not records or manager.verifier is not records.verifier
            or not services.assembly._manager_bound()):
        raise GuaranteeUnavailableError('original live Manager owner is unavailable')
    if type(expected_directory_binding_ref) is not DirectoryBindingRef:
        raise IdentityMismatchError('complete expected DirectoryBindingRef required')
    # Original owner lock order; no lock escapes this function. This observes
    # current local sources, not an approval/control or filesystem mutation lock.
    @contextmanager
    def source_lock(lock):
        # Never wait on a Unit prompt's lifecycle/model round trip while a
        # consumer may hold its own Engineering COMMIT transaction.
        if not lock.acquire(blocking=False):
            raise GuaranteeUnavailableError('original live-source owner is busy')
        try:
            yield
        finally:
            lock.release()

    with source_lock(env._admission_lock), source_lock(manager._lock):
        live = manager.find(unit_ref)
        with source_lock(live._lifecycle_lock):
            with guard_unit_selection(services, unit_ref,
                    expected_profile_revision=expected_profile_revision,
                    query_invocation=query_invocation, query_input_digest=query_input_digest,
                    require_live=False) as read_cut:
                unit, node, original = _source(services, records, unit_ref)
                if (live.profile_revision != expected_profile_revision
                        or not same_reference(live.prepared_unit['unitRef'], unit.public_ref)):
                    raise IdentityMismatchError('fixed live Profile or Unit differs')
                directory = DirectoryBindingRef.from_dict(dict(original.intent.context_ref['directoryBindingRef']))
                if directory != expected_directory_binding_ref:
                    raise IdentityMismatchError('original preparation directory differs')
                # Re-run the trusted original Workspace/installation resolver
                # and fingerprint its plan against the original publication.
                # Expected DTO equality is not a substitute for this owner call.
                _, plan = services.assembly._current_plan(original.request, original)
                factory = live.channel_factory
                roots = unit.facts['privateRootFacts']
                if (not same_reference(plan['context']['privateRootFacts'], roots)
                        or not same_reference(factory._roots, roots)):
                    raise IdentityMismatchError('resolved live preparation roots differ')
                record = factory.owned_record
                use = factory.environment
                if (record is None or use is None or record.prepared_agent is not factory.prepared_agent
                        or record.prepared_agent is not live.prepared_agent
                        or record.prepared_agent.profile_revision != safe_json(
                            encode_revision_ref(expected_profile_revision))
                        or record.environment_identity != use.environment_id
                        or record.environment_use_identity != use.identity
                        or factory.instance.identity != use.environment_id):
                    raise GuaranteeUnavailableError('original live Environment/channel binding is unavailable')
                session = records.owner_read_session(unit.unit_ref)
                if (session is None or session.state != 'confirmed'
                        or live._channels.get(unit.unit_ref) is not record.entry
                        or session.native_facts.get('sessionId') != record.entry.session_id
                        or not record.entry.has_io_loop or record.entry.transport.detached
                        or any(records.owner_read_termination(unit.unit_ref, action) is not None
                               for action in ('stop', 'release'))
                        or record.process.observe().state != 'running'):
                    raise GuaranteeUnavailableError('original Unit is not live and confirmed')
                # The narrow contract qualifies only the existing bound Local
                # file area. Public guarded Use getters reject inactive Uses.
                try:
                    capabilities = use.capabilities
                    if capabilities.isolation != 'none':
                        raise ValueError('local isolation contract required')
                    files = use.files
                    cwd = record.prepared_agent.harness.launch_spec.cwd
                    if cwd != roots['cwd']:
                        raise ValueError('actual fixed cwd differs')
                    relative = os.path.relpath(cwd, files.root())
                    if (files.path(relative) != os.path.normpath(cwd)
                            or not files.exists(relative) or not os.path.isdir(files.path(relative))):
                        raise ValueError('actual bound cwd is unavailable')
                except Exception:
                    raise GuaranteeUnavailableError('actual bound Local file area is unavailable') from None
                # Re-read publication and liveness after context/file work.
                _, latest_node, latest = _source(services, records, unit_ref)
                if (latest.revision != original.revision
                        or latest_node['publicationRevision'] != node['publicationRevision']
                        or record.process.observe().state != 'running'
                        or session.native_facts.get('sessionId') != record.entry.session_id
                        or not record.entry.has_io_loop or record.entry.transport.detached):
                    raise IdentityMismatchError('live source changed during observation')
                observed_at = issuer._now()
                verified = records.verifier.verify_continuation(query_invocation, 'query',
                    unit.facts['providerRef'], unit.facts['nodeRef'], query_input_digest)
                return sealed_mapping({
                    'contract': 'unit-live-source-snapshot/1', 'sourceCut': 'observed-live-owner',
                    'permissionCut': 'authorized-read-time',
                    'observedAt': observed_at, 'authorizedAt': issuer._now(),
                    'authorityRevision': verified['grant']['authorityRevision'],
                    'managementEpoch': verified['managementEpoch'],
                    'unitRef': unit.public_ref, 'nodeRef': unit.facts['nodeRef'],
                    'publicationRevision': node['publicationRevision'],
                    'profileRevision': encode_revision_ref(expected_profile_revision),
                    'preparationOperationRef': original.intent.operation_ref,
                    'preparationOperationRevision': original.revision,
                    'directoryBindingRef': directory.to_dict(),
                    'localDirectory': {'environmentIdentity': use.environment_id,
                        'useIdentity': use.identity, 'cwdRelativePath': relative,
                        'evidenceKind': 'bound-file-area-path-check', 'isolation': 'none'},
                    'queryOperationRef': verified['operationRef'], 'queryInputDigest': query_input_digest,
                    'currentThroughCommit': False, 'liveDispatchAuthorized': False,
                    'checkoutBaselineVerified': False,
                })


__all__ = ['UnitSelectionUnavailable']
