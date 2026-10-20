"""Original Unit selection over the retained Manager, Use and query owners.

The live context retains a process-local Unit source fence, not authority or a
second record. Read-only snapshots remain explicitly read-time observations.
"""
from contextlib import contextmanager
from collections.abc import Mapping
import hashlib
import json

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitGuaranteeUnavailable, UnitIdentityMismatch
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_execution_agents.profiles import ProfileRevisionRef, decode_revision_ref, encode_revision_ref
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.bindings.publication import decode_node_ref
from ordessa_units.lifecycle.unit_lifecycle import same_reference


class UnitSelectionUnavailable(UnitGuaranteeUnavailable):
    code = 'UNIT_SELECTION_SYNC_UNAVAILABLE'


class _UnitSelectionLease:
    """Opaque in-process proof that this context retained the original Unit."""
    __slots__ = ()


@contextmanager
def _source_locks(env, manager, live):
    # Preserve the sole owner lock order and fail fast. The locks protect only
    # acquisition/revalidation; the lease itself is a Unit-owned fence and no
    # host authority lock is retained across an SDK or external transaction.
    held = []
    try:
        for lock in (env._admission_lock, manager._lock, live._lifecycle_lock):
            if not lock.acquire(blocking=False):
                raise UnitGuaranteeUnavailable('original live selection owner is busy')
            held.append(lock)
        yield
    finally:
        for lock in reversed(held):
            lock.release()


def _live_selection_validator(services, unit_ref, *, expected_profile_revision,
                              query_invocation, query_input_digest, expected_live):
    import os
    from ordessa_units.management.manager import UnitManager
    from ordessa_units.sessions.sdk_client import SdkAcpClient

    env, records, issuer = _owner(services)
    manager = services.unit_manager
    if (type(manager) is not UnitManager or manager is not services.assembly._unit_manager
            or manager.records is not records or manager.verifier is not records.verifier
            or not services.assembly._manager_bound()):
        raise UnitGuaranteeUnavailable('original live Manager owner is unavailable')

    def validate():
        with _source_locks(env, manager, expected_live):
            if manager._draining:
                raise UnitGuaranteeUnavailable('original Unit Manager is draining')
            try:
                live = manager.find(unit_ref)
            except Exception:
                raise UnitIdentityMismatch('original live Unit handle is unavailable') from None
            if (live is not expected_live or live.records is not records
                    or live._verifier is not manager.verifier):
                raise UnitIdentityMismatch('original retained Unit owner changed')
            # Query capabilities are verified through the original UnitRecords
            # read before the Issuer accepts a continuation of that capability.
            # This preserves the original issued/verified-state transition.
            resolved_unit = records.resolve_unit_reference(
                unit_ref, query_invocation, input_digest=query_input_digest)
            unit, node, original = _source(services, records, unit_ref)
            if resolved_unit != unit:
                raise UnitIdentityMismatch('original query resolved a different Unit source')
            actual_profile = decode_revision_ref(dict(original.intent.profile_snapshot_ref))
            if (actual_profile != expected_profile_revision
                    or live.profile_revision != expected_profile_revision
                    or not same_reference(live.prepared_unit['unitRef'], unit.public_ref)):
                raise UnitIdentityMismatch('fixed live Profile or Unit differs')
            revision = services.profiles.get_revision(actual_profile)
            if revision.ref != actual_profile:
                raise UnitIdentityMismatch('fixed immutable Profile revision is unavailable')
            # Revalidate the exact original query ticket/current state after
            # loading source and before checking retained process/use facts.
            facts = query_invocation.facts
            read = facts['contextRef'].get('acpTurnRead')
            request = facts['request']
            if original.intent.kind == 'agent-preparation':
                services.nodes._permission(request=RequestKey(
                    request['environmentNamespace'], request['principalScope'], request['requestId']))
            elif original.intent.kind == 'unit-public-prepare':
                from ordessa_execution_agents.harness.providers.registry.definition_admission import HarnessAdmission
                local_context = original.intent.context_ref
                admitted = HarnessAdmission(env).describe(local_context['harnessDefinitionRef'])
                if safe_json(admitted.provider_ref) != safe_json(unit.facts['providerRef']):
                    raise UnitIdentityMismatch('current LocalUnitOwner Harness pin differs')
            else:
                raise UnitIdentityMismatch('unsupported Unit selection owner')
            verified = records.verifier.verify_continuation(query_invocation, 'query',
                unit.facts['providerRef'], unit.facts['nodeRef'], query_input_digest)
            if (not isinstance(read, Mapping) or safe_json(read.get('unitRef')) != safe_json(unit_ref)
                    or verified.get('inputDigest') != query_input_digest):
                raise UnitIdentityMismatch('original ACP read authorization changed')

            record = live.channel_factory.owned_record
            use = live.channel_factory.environment
            session = records.owner_read_session(unit.unit_ref)
            if (record is None or type(record.entry) is not SdkAcpClient or use is None
                    or record.prepared_agent is not live.prepared_agent
                    or record.prepared_agent.profile_revision
                       != safe_json(encode_revision_ref(expected_profile_revision))
                    or record.environment_identity != use.environment_id
                    or record.environment_use_identity != use.identity
                    or live.channel_factory.instance.identity != use.environment_id):
                raise UnitGuaranteeUnavailable('original live Environment/channel binding is unavailable')
            if original.intent.kind == 'unit-public-prepare':
                local = original.intent.context_ref['localUnitRun']
                if (local['environmentIdentity'] != use.environment_id
                        or local['environmentGeneration'] != use.generation):
                    raise UnitIdentityMismatch('LocalUnitOwner Environment generation changed')
                generation = local['environmentGeneration']
            else:
                # The Use carries the only original environment generation for
                # this historical Node owner. Its own public check verifies it
                # against the retained Environment store without guessing one.
                generation = use.generation
            check = getattr(use, 'check', None)
            if not callable(check):
                raise UnitGuaranteeUnavailable('original Environment Use check unavailable')
            check(use.environment_id, generation, allow_unknown=False)
            if (session is None or session.state != 'confirmed'
                    or live._channels.get(unit.unit_ref) is not record.entry
                    or session.native_facts.get('sessionId') != record.entry.session_id
                    or not record.entry.has_io_loop or record.entry.transport.detached
                    or any(records.owner_read_termination(unit.unit_ref, action) is not None
                           for action in ('stop', 'release'))
                    or record.process.observe().state != 'running'):
                raise UnitGuaranteeUnavailable('original Unit is not live and confirmed')
            roots = unit.facts['privateRootFacts']
            if original.intent.kind == 'agent-preparation':
                _admitted, plan = services.assembly._current_plan(original.request, original)
                if not same_reference(plan['context']['privateRootFacts'], roots):
                    raise UnitIdentityMismatch('original Node preparation resolution changed')
            if (not same_reference(live.channel_factory._roots, roots)
                    or live.prepared_agent.harness.launch_spec.cwd != roots['cwd']):
                raise UnitIdentityMismatch('fixed live preparation roots changed')
            try:
                capabilities = use.capabilities
                if capabilities.isolation != 'none':
                    raise ValueError('Local file area is not within the qualified isolation contract')
                files = use.files
                cwd = roots['cwd']
                relative = os.path.relpath(cwd, files.root())
                if (files.path(relative) != os.path.normpath(cwd)
                        or not files.exists(relative) or not os.path.isdir(files.path(relative))):
                    raise ValueError('original bound cwd is unavailable')
            except Exception:
                raise UnitGuaranteeUnavailable('original bound Local file area is unavailable') from None

            # Repeat the source/query/use cuts after potentially slow public
            # file and process observations. The Unit fence prevents stop,
            # release and configuration replacement until context exit.
            latest, _latest_node, latest_original = _source(services, records, unit_ref)
            if (latest != unit or latest_original.revision != original.revision
                    or live.channel_factory.owned_record is not record
                    or record.process.observe().state != 'running'):
                raise UnitIdentityMismatch('live Unit source changed during selection')
            check(use.environment_id, generation, allow_unknown=False)
            records.verifier.verify_continuation(query_invocation, 'query',
                unit.facts['providerRef'], unit.facts['nodeRef'], query_input_digest)
        return True

    return validate


@contextmanager
def _live_authority_guard(issuer):
    """Retain only the existing authenticated interaction capability.

    This is the original LocalUnitInvocationAuthority; no new grant is issued.
    Its current InstanceAccessAuthority guard spans the caller's finite
    synchronous COMMIT section and the bounded SDK write callback, not the
    response wait.
    """
    from ordessa_units.admission.run_permission import LocalUnitInvocationAuthority
    authority = getattr(issuer, '_authority', None)
    if type(authority) is not LocalUnitInvocationAuthority:
        raise UnitSelectionUnavailable('original live authenticated permission guard is unavailable')
    authorization = authority.authorization()
    with authority.guard('interaction', authorization):
        yield


@contextmanager
def _live_unit_fence(services, env, records, unit_ref, *, expected_profile_revision,
                     query_invocation, query_input_digest):
    from ordessa_units.management.manager import UnitManager

    manager = services.unit_manager
    if type(manager) is not UnitManager or manager is not services.assembly._unit_manager:
        raise UnitSelectionUnavailable('original live Unit Manager is unavailable')
    try:
        # Resolve under the fixed owner lock order, nonblocking. No potentially
        # stale/cold Manager search is allowed to wait here.
        if not env._admission_lock.acquire(blocking=False):
            raise UnitGuaranteeUnavailable('original live selection owner is busy')
        try:
            if not manager._lock.acquire(blocking=False):
                raise UnitGuaranteeUnavailable('original live selection owner is busy')
            try:
                live = manager.find(unit_ref)
            finally:
                manager._lock.release()
        finally:
            env._admission_lock.release()
    except Exception:
        raise UnitSelectionUnavailable('original live Unit handle is unavailable') from None
    validate = _live_selection_validator(services, unit_ref,
        expected_profile_revision=expected_profile_revision,
        query_invocation=query_invocation, query_input_digest=query_input_digest,
        expected_live=live)
    token = None
    try:
        with _source_locks(env, manager, live):
            validate()
            token = live._acquire_selection_fence(validate)
        # Close the validation/fence-install race before exposing the context.
        validate()
        yield _UnitSelectionLease()
        validate()
    finally:
        if token is not None:
            live._release_selection_fence(token)


def _owner(services):
    env = services.nodes._environment
    bundle = getattr(env, '_agent_owner_ports', None)
    if bundle is None or getattr(env, '_agent_services', None) is not services:
        raise UnitGuaranteeUnavailable('original Unit owner bundle is unavailable')
    bundle.validate_for(env)
    if type(bundle.issuer) is not InvocationIssuer:
        raise UnitGuaranteeUnavailable('original invocation issuer is unavailable')
    return env, bundle.provider_view.records, bundle.issuer


def _source(services, records, unit_ref):
    """Owner-only provenance read; caller permission is checked separately."""
    if not isinstance(unit_ref, dict) and not hasattr(unit_ref, 'items'):
        raise UnitIdentityMismatch('complete Unit reference required')
    if set(unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}:
        raise UnitIdentityMismatch('complete Unit reference required')
    unit = records.owner_read_unit(unit_ref['unitId'])
    if safe_json(unit.public_ref) != safe_json(unit_ref):
        raise UnitIdentityMismatch('Unit source differs from original owner')
    env = services.nodes._environment
    correlation = json.loads(unit.facts['correlation'])
    request = correlation['request']
    original = env._store.read_operation(RequestKey(
        request['environmentNamespace'], request['principalScope'], request['requestId']))
    if (original is None or original.status != 'published'
            or original.intent.operation_ref != correlation['operationRef']
            or safe_json(original.intent.node_ref) != safe_json(unit.facts['nodeRef'])):
        raise UnitIdentityMismatch('original preparation source differs')
    node = None
    if original.intent.kind == 'agent-preparation':
        node = services.nodes.read(decode_node_ref(unit.facts['nodeRef']))
        if (node is None or safe_json(node['binding']['harnessUnitRef']) != safe_json(unit_ref)
                or safe_json(node['binding']['profileSnapshotRef']) != safe_json(original.intent.profile_snapshot_ref)
                or safe_json(node['binding']['harnessProviderRef']) != safe_json(unit.facts['providerRef'])):
            raise UnitIdentityMismatch('original preparation/Node provenance differs')
    elif original.intent.kind == 'unit-public-prepare':
        # Public LocalUnitOwner has no NodePublication row. Bind its actual
        # published preparation operation, original UnitManager reservation,
        # root facts and finite-run identity directly; never infer a Node row.
        context = original.intent.context_ref
        local = context.get('localUnitRun')
        manager = services.unit_manager
        from ordessa_units.management.manager import UnitManager
        step = next((item for item in original.intent.steps if item.step_id == 'prepare'), None)
        if (type(manager) is not UnitManager or manager.records is not records
                or manager.verifier is not records.verifier
                or not services.assembly._manager_bound()
                or not isinstance(local, Mapping)
                or set(local) != {'ownerId', 'permissionId', 'environmentIdentity',
                                  'environmentGeneration', 'agentId', 'profileRevision'}
                or type(local.get('ownerId')) is not str or not local['ownerId']
                or type(local.get('permissionId')) is not str or not local['permissionId']
                or type(local.get('environmentIdentity')) is not str or not local['environmentIdentity']
                or type(local.get('environmentGeneration')) is not int
                or type(local.get('agentId')) is not str or not local['agentId']
                or safe_json(local.get('profileRevision')) != safe_json(original.intent.profile_snapshot_ref)
                or original.intent.management_epoch != local['environmentGeneration']
                or not isinstance(step, StepIntent)
                or safe_json(step.pinned_provider_ref) != safe_json(unit.facts['providerRef'])
                or step.management_epoch != local['environmentGeneration']
                or step.input_digest != unit.facts['inputDigest']
                or safe_json(context.get('privateRootFacts')) != safe_json(unit.facts['privateRootFacts'])
                or not isinstance(context.get('directoryBindingRef'), Mapping)
                or not isinstance(original.result, Mapping)
                or safe_json(original.result.get('unitRef')) != safe_json(unit_ref)
                or original.result.get('action') != 'prepare'):
            raise UnitIdentityMismatch('original LocalUnitOwner preparation provenance differs')
    else:
        raise UnitIdentityMismatch('unsupported original Unit preparation owner')
    step = next((s for s in original.intent.steps if s.step_id == correlation['stepId']), None)
    if (step is None or step.input_digest != unit.facts['inputDigest']
            or step.management_epoch != unit.facts['managementEpoch']
            or safe_json(step.pinned_provider_ref) != safe_json(unit.facts['providerRef'])):
        raise UnitIdentityMismatch('original preparation step differs from Unit')
    return unit, node, original


def authorize_acp_turn_query(services, request, unit_ref, operation_ref, *, expected_prompt_input_digest):
    env, records, issuer = _owner(services)
    with env._admission_lock:
        if type(request) is not RequestKey:
            raise UnitIdentityMismatch('original request identity required')
        services.nodes._permission(request=request)
        if (type(operation_ref) is not str or not operation_ref or len(operation_ref) > 512
                or any(ord(c) < 32 for c in operation_ref)
                or type(expected_prompt_input_digest) is not str
                or not expected_prompt_input_digest.startswith('sha256:')
                or len(expected_prompt_input_digest) != 71
                or any(c not in '0123456789abcdef' for c in expected_prompt_input_digest[7:])):
            raise UnitIdentityMismatch('exact ACP operation and prompt digest required')
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
        raise UnitIdentityMismatch('selection mode must be an explicit bool')
    if require_live:
        with _live_authority_guard(issuer):
            with _live_unit_fence(services, env, records, unit_ref,
                    expected_profile_revision=expected_profile_revision,
                    query_invocation=query_invocation, query_input_digest=query_input_digest):
                # The context itself is the lease. The yielded opaque object
                # is informational only and callers may ignore it.
                yield _UnitSelectionLease()
        return
    with env._admission_lock:
        unit = records.resolve_unit_reference(unit_ref, query_invocation, input_digest=query_input_digest)
        facts = query_invocation.facts
        read = facts['contextRef'].get('acpTurnRead')
        if (read is None or set(read) != {'unitRef', 'operationRef', 'expectedPromptInputDigest'}
                or safe_json(read['unitRef']) != safe_json(unit_ref)
                or query_input_digest != records.acp_turn_query_digest(
                    unit_ref, read['operationRef'], read['expectedPromptInputDigest'])):
            raise UnitIdentityMismatch('selection requires the exact original ACP read recipe')
        request = facts['request']
        _, node, original = _source(services, records, unit_ref)
        if original.intent.kind == 'agent-preparation':
            services.nodes._permission(request=RequestKey(
                request['environmentNamespace'], request['principalScope'], request['requestId']))
        actual_profile = decode_revision_ref(dict(original.intent.profile_snapshot_ref))
        if type(expected_profile_revision) is not ProfileRevisionRef or expected_profile_revision != actual_profile:
            raise UnitIdentityMismatch('fixed complete Profile revision differs from original preparation')
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
            'publicationRevision': node['publicationRevision'] if node is not None else None,
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
        raise UnitGuaranteeUnavailable('original live Manager owner is unavailable')
    if type(expected_directory_binding_ref) is not DirectoryBindingRef:
        raise UnitIdentityMismatch('complete expected DirectoryBindingRef required')
    # Original owner lock order; no lock escapes this function. This observes
    # current local sources, not an approval/control or filesystem mutation lock.
    @contextmanager
    def source_lock(lock):
        # Never wait on a Unit prompt's lifecycle/model round trip while a
        # consumer may hold its own Engineering COMMIT transaction.
        if not lock.acquire(blocking=False):
            raise UnitGuaranteeUnavailable('original live-source owner is busy')
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
                if node is None:
                    # LocalUnitOwner publishes its source in the original
                    # OperationStore and UnitRecords, not NodePublication.
                    # Preserve the snapshot's read-time (never COMMIT) claim.
                    validator = _live_selection_validator(services, unit_ref,
                        expected_profile_revision=expected_profile_revision,
                        query_invocation=query_invocation, query_input_digest=query_input_digest,
                        expected_live=live)
                    validator()
                    directory = DirectoryBindingRef.from_dict(dict(
                        original.intent.context_ref['directoryBindingRef']))
                    if directory != expected_directory_binding_ref:
                        raise UnitIdentityMismatch('original LocalUnitOwner directory differs')
                    record = live.channel_factory.owned_record
                    use = live.channel_factory.environment
                    roots = unit.facts['privateRootFacts']
                    files = use.files
                    cwd = roots['cwd']
                    relative = os.path.relpath(cwd, files.root())
                    verified = records.verifier.verify_continuation(query_invocation, 'query',
                        unit.facts['providerRef'], unit.facts['nodeRef'], query_input_digest)
                    validator()
                    return sealed_mapping({
                        'contract': 'unit-live-source-snapshot/1',
                        'sourceCut': 'observed-live-owner',
                        'permissionCut': 'authorized-read-time',
                        'observedAt': issuer._now(), 'authorizedAt': issuer._now(),
                        'authorityRevision': verified['grant']['authorityRevision'],
                        'managementEpoch': original.intent.management_epoch,
                        'unitRef': unit.public_ref, 'nodeRef': unit.facts['nodeRef'],
                        'publicationRevision': None,
                        'profileRevision': encode_revision_ref(expected_profile_revision),
                        'preparationOperationRef': original.intent.operation_ref,
                        'preparationOperationRevision': original.revision,
                        'directoryBindingRef': directory.to_dict(),
                        'localDirectory': {'environmentIdentity': use.environment_id,
                            'useIdentity': use.identity, 'cwdRelativePath': relative,
                            'evidenceKind': 'bound-file-area-path-check',
                            'isolation': use.capabilities.isolation},
                        'queryOperationRef': verified['operationRef'],
                        'queryInputDigest': query_input_digest,
                        'currentThroughCommit': False, 'liveDispatchAuthorized': False,
                        'checkoutBaselineVerified': False,
                    })
                if (live.profile_revision != expected_profile_revision
                        or not same_reference(live.prepared_unit['unitRef'], unit.public_ref)):
                    raise UnitIdentityMismatch('fixed live Profile or Unit differs')
                directory = DirectoryBindingRef.from_dict(dict(original.intent.context_ref['directoryBindingRef']))
                if directory != expected_directory_binding_ref:
                    raise UnitIdentityMismatch('original preparation directory differs')
                # Re-run the trusted original Workspace/installation resolver
                # and fingerprint its plan against the original publication.
                # Expected DTO equality is not a substitute for this owner call.
                _, plan = services.assembly._current_plan(original.request, original)
                factory = live.channel_factory
                roots = unit.facts['privateRootFacts']
                if (not same_reference(plan['context']['privateRootFacts'], roots)
                        or not same_reference(factory._roots, roots)):
                    raise UnitIdentityMismatch('resolved live preparation roots differ')
                record = factory.owned_record
                use = factory.environment
                if (record is None or use is None or record.prepared_agent is not factory.prepared_agent
                        or record.prepared_agent is not live.prepared_agent
                        or record.prepared_agent.profile_revision != safe_json(
                            encode_revision_ref(expected_profile_revision))
                        or record.environment_identity != use.environment_id
                        or record.environment_use_identity != use.identity
                        or factory.instance.identity != use.environment_id):
                    raise UnitGuaranteeUnavailable('original live Environment/channel binding is unavailable')
                session = records.owner_read_session(unit.unit_ref)
                if (session is None or session.state != 'confirmed'
                        or live._channels.get(unit.unit_ref) is not record.entry
                        or session.native_facts.get('sessionId') != record.entry.session_id
                        or not record.entry.has_io_loop or record.entry.transport.detached
                        or any(records.owner_read_termination(unit.unit_ref, action) is not None
                               for action in ('stop', 'release'))
                        or record.process.observe().state != 'running'):
                    raise UnitGuaranteeUnavailable('original Unit is not live and confirmed')
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
                    raise UnitGuaranteeUnavailable('actual bound Local file area is unavailable') from None
                # Re-read publication and liveness after context/file work.
                _, latest_node, latest = _source(services, records, unit_ref)
                if (latest.revision != original.revision
                        or latest_node['publicationRevision'] != node['publicationRevision']
                        or record.process.observe().state != 'running'
                        or session.native_facts.get('sessionId') != record.entry.session_id
                        or not record.entry.has_io_loop or record.entry.transport.detached):
                    raise UnitIdentityMismatch('live source changed during observation')
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
