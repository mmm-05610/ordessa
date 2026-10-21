"""Production local Unit composition over the original execution owners.

The host selects a real permission, Profile, Environment and Harness. This
builder hides the issuer/evidence/lease wiring, while the existing host still
opens its one original journal and store. No Engineering workflow is required.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid
from collections.abc import Mapping

from ordessa_agents.profiles import ProfileService, encode_revision_ref
from ordessa_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_units.admission.owner_ports import AgentOwnerPorts
from ordessa_units.admission.owner_selection import AgentOwnerInputs, AgentOwnerUnavailable
from ordessa_units.admission.run_permission import UnitRunPermission, LocalUnitInvocationAuthority
from ordessa_units.admission.local_state import FixedUnitCurrentState
from ordessa_units.definitions import UnitSpec
from ordessa_units.api.unit import Unit
from ordessa_units.management.manager import UnitManagementRefused
from ordessa_units.sessions.evidence import AcpUnitEvidence
from .fresh_factory import build_fresh_acp_unit_factory
from .service import build_unit_manager
from .owner import AssembledUnitOwner, assemble_unit_owner
from .profile_selection import resolve_unit_profile


def _digest(value):
    return 'sha256:' + hashlib.sha256(safe_json(value).encode()).hexdigest()


class LocalUnitOwner:
    def __init__(self, *, admission_context, permission, environment_instance,
                 preparation, materializer, environment_sharing, timeout,
                 callback_approval, process_binding_factory,
                 clock, effect_write_guard_factory=None, acp_turn_opt_in=False,
                 defer_effect_write_guard_factory=False, managed_input_ports=None):
        if (not isinstance(admission_context, UnitAdmissionContext)
                or type(permission) is not UnitRunPermission
                or permission.profile_revision.environment_namespace != admission_context.environment_namespace
                or permission.principal_scope != admission_context.principal_scope
                or permission.environment_identity != environment_instance.identity):
            raise AgentOwnerUnavailable('Original admission, authenticated permission and Environment must agree')
        if type(acp_turn_opt_in) is not bool:
            raise AgentOwnerUnavailable('Explicit boolean ACP durable opt-in required')
        if type(defer_effect_write_guard_factory) is not bool:
            raise AgentOwnerUnavailable('Explicit boolean effect-write factory deferral required')
        if defer_effect_write_guard_factory and (not acp_turn_opt_in or effect_write_guard_factory is not None):
            raise AgentOwnerUnavailable('Deferred effect-write factory requires opted-in ACP and an unbound initial factory')
        self.admission = admission_context
        self.permission, self.environment = permission, environment_instance
        if effect_write_guard_factory is not None and not callable(effect_write_guard_factory):
            raise AgentOwnerUnavailable('Fixed effect-write guard factory must be callable')
        if effect_write_guard_factory is not None and not acp_turn_opt_in:
            raise AgentOwnerUnavailable('Guarded recorded dispatch requires explicit original ACP schema opt-in')
        self.acp_turn_opt_in = acp_turn_opt_in
        from ordessa_units.channels.acp_input import ManagedAcpInputPorts, ManagedAcpInputs
        if managed_input_ports is not None and (
                type(managed_input_ports) is not ManagedAcpInputPorts or not acp_turn_opt_in):
            raise AgentOwnerUnavailable('Managed ACP input requires fixed owner ports and ACP opt-in')
        self._managed_inputs = (None if managed_input_ports is None
                                else ManagedAcpInputs(self, managed_input_ports))
        self._effect_write_guard_factory = effect_write_guard_factory
        self._defer_effect_write_guard_factory = defer_effect_write_guard_factory
        self._effect_write_guard_factory_pending = defer_effect_write_guard_factory
        self.profile_service = ProfileService(UnitProfileAdmission(admission_context))
        with permission.guard('prepare', clock=clock):
            resolution = resolve_unit_profile(self.profile_service, permission.profile_revision,
                                              admission_context.harness_catalog)
        if (not isinstance(preparation.harness_id, str) or not preparation.harness_id
                or resolution.harness_descriptor.protocol_id != 'acp/v1'):
            raise AgentOwnerUnavailable('Selected preparation must implement the fixed ACP Harness')
        self.owner_id = 'unit-owner-' + uuid.uuid4().hex
        self.authority = LocalUnitInvocationAuthority(admission_context.store_port, permission,
                                                     owner_id=self.owner_id, clock=clock)
        self.state = FixedUnitCurrentState(store=admission_context.store_port,
            harness_catalog=admission_context.harness_catalog, environment_instance=environment_instance,
            environment_namespace=admission_context.environment_namespace,
            root_directory=permission.root_directory, owner_id=self.owner_id,
            profile_revision=permission.profile_revision, agent_id=permission.agent_id,
            permission_id=permission.identity)
        self.evidence = AcpUnitEvidence(preparation_authority=self._preparation,
            start_authority=self._start)
        self.lease = ConnectionLeasePort()
        descriptor = RuntimeProviderDescriptor(resolution.harness_descriptor.provider_id,
            RUNTIME_PROVIDER_VERSION, resolution.harness_descriptor.definition_ref,
            resolution.harness_descriptor.implementation_digest,
            ('plan_preparation', 'prepare', 'start', 'connect', 'describe_access', 'stop', 'release'))
        fresh = build_fresh_acp_unit_factory(agent_id=permission.agent_id,
            profile_revision=permission.profile_revision, descriptor=descriptor,
            environment_instance=environment_instance,
            environment_reference={'environmentId': environment_instance.identity},
            environment_sharing=environment_sharing, preparation=preparation, materializer=materializer,
            evidence=self.evidence, lease_port=self.lease, timeout=timeout,
            callback_approval=callback_approval,
            effect_write_guard_factory=effect_write_guard_factory,
            defer_effect_write_guard_factory=defer_effect_write_guard_factory,
            acp_turn_opt_in=acp_turn_opt_in,
            process_binding_factory=process_binding_factory)
        self.owner_inputs = AgentOwnerInputs(authority=self.authority, current_state=self.state,
            scope_authority=self.state, native_session_evidence=self.evidence, management_epoch=self.state,
            preparation_context_port=self, fresh_unit_factory=fresh,
            termination_evidence=self.evidence,
            acp_turn_opt_in=acp_turn_opt_in,
            close=self.revoke)
        self._ports = None
        self._plan = None
        self._operations = {}
        self._connections = {}
        self.manager = None
        self.assembled_owner: AssembledUnitOwner | None = None

    @property
    def spec(self):
        return UnitSpec(self.permission.agent_id, self.permission.profile_revision,
                        {'environmentId': self.environment.identity})

    @property
    def effect_write_guard_factory(self):
        return self._effect_write_guard_factory

    def ensure_unit_creation_ready(self):
        """Purely refuse lifecycle work until any deferred owner finalization."""
        if self._effect_write_guard_factory_pending:
            raise AgentOwnerUnavailable('Original effect-write factory finalization is required before Unit creation')
        return True

    def bind_effect_write_guard_factory(self, factory):
        """Finalize this opted-in original owner once before any Unit creation."""
        if (not self._defer_effect_write_guard_factory
                or not self._effect_write_guard_factory_pending
                or self._effect_write_guard_factory is not None
                or not callable(factory)):
            raise AgentOwnerUnavailable('Deferred effect-write factory can be bound exactly once')
        ports = self._bound()
        original_manager = ports.unit_manager
        if original_manager is None:
            raise AgentOwnerUnavailable('Original Unit Manager must be bound before effect-write finalization')

        def finalize_on_original_graph():
            # This callback runs while the original Manager lock is held.
            # Recheck before taking the authority guard so a concurrent second
            # finalizer cannot invert the manager/authority lock order.
            if (self._effect_write_guard_factory_pending is not True
                    or self._effect_write_guard_factory is not None):
                raise AgentOwnerUnavailable('Deferred effect-write factory can be bound exactly once')
            with self.authority.guard('prepare', self.authorization()):
                self._bound()
                if (self._effect_write_guard_factory_pending is not True
                        or self._effect_write_guard_factory is not None
                        or self.acp_turn_opt_in is not True
                        or ports.unit_manager is not original_manager):
                    raise AgentOwnerUnavailable('Original local owner is not pending on its bound graph')
                resolve_unit_profile(self.profile_service, self.permission.profile_revision,
                                     self.admission.harness_catalog)
                if self.environment.snapshot.identity != self.permission.environment_identity:
                    raise AgentOwnerUnavailable('Original Environment changed before owner finalization')
                finalizer = self.owner_inputs.fresh_unit_factory.finalize_effect_write_guard_factory
                if not callable(finalizer):
                    raise AgentOwnerUnavailable('Original fresh factory cannot finalize its write guard')
                finalizer(factory)
                self._effect_write_guard_factory = factory
                self._effect_write_guard_factory_pending = False

        # The original Manager owns the lock. Its helper checks draining and
        # every live/attempt state before this callback acquires the authority.
        try:
            original_manager._finalize_effect_write_guard_factory(finalize_on_original_graph)
        except UnitManagementRefused as error:
            raise AgentOwnerUnavailable('Original Unit Manager is unavailable for effect-write finalization') from error
        return True

    def authorization(self):
        return self.authority.authorization()

    def submit_managed_input(self, unit, authorization, request, captured_ref, *, timeout=60):
        """Submit/replay an exact capture through this original Unit owner."""
        if self._managed_inputs is None:
            raise AgentOwnerUnavailable('Original managed ACP capture/Workspace owners unavailable')
        return self._managed_inputs.submit(unit, authorization, request, captured_ref, timeout=timeout)

    def read_managed_input(self, authorization, request, unit_ref, captured_ref):
        """Read the original attempt without capture refresh, relaunch or send."""
        if self._managed_inputs is None:
            raise AgentOwnerUnavailable('Original managed ACP capture/Workspace owners unavailable')
        return self._managed_inputs.read(authorization, request, unit_ref, captured_ref)

    @property
    def records(self):
        """Return the exact UnitRecords object installed by the original host."""
        return self._bound().provider_view.records

    def bind(self, ports):
        """Bind only the existing host's original assembled owner, once."""
        if self._ports is not None:
            if self._ports is not ports:
                raise AgentOwnerUnavailable('Cannot replace the original Unit owner')
            return self.manager
        if (type(ports) is not AgentOwnerPorts or ports.unit_manager is None
                or ports.issuer._store is not self.admission.store_port
                or ports.issuer._authority is not self.authority or ports.issuer._current_state is not self.state
                or ports.provider_view.records.native_evidence is not self.evidence
                or ports.unit_manager.records is not ports.provider_view.records):
            raise AgentOwnerUnavailable('Local owner requires its original assembled issuer and records')
        ports.validate_for(self.admission)
        self._ports = ports
        self.state.attach_owner(ports.provider_view.records, ports.unit_manager)
        self.manager = build_unit_manager(ports.unit_manager, self)
        return self.manager

    def assemble(self, *, journal):
        """Assemble the original Units owner from a caller-provisioned journal.

        The caller remains responsible for securely provisioning and retaining
        the journal. This method creates no Environment, store, authority, or
        durable owner and returns the same public Manager used by ``bind``.
        """
        if self.assembled_owner is not None:
            if self.assembled_owner.journal is journal:
                return self.manager
            raise AgentOwnerUnavailable('Local Unit owner is already assembled on another journal')
        if self._ports is not None:
            raise AgentOwnerUnavailable('Local Unit owner is already bound to another original assembly')
        assembled = assemble_unit_owner(self.admission, self.owner_inputs, journal=journal)
        try:
            manager = self.bind(assembled.ports)
        except BaseException:
            assembled.revoke()
            raise
        self.assembled_owner = assembled
        return manager

    def _bound(self):
        self.admission.check_open()
        if self._ports is None or self._ports.issuer._closed:
            raise AgentOwnerUnavailable('Original local Unit owner is not bound or is closed')
        self._ports.validate_for(self.admission)
        return self._ports

    def resolve_plan(self, spec, authorization):
        self.ensure_unit_creation_ready()
        with self.authority.guard('prepare', authorization):
            self._bound()
            if spec != self.spec:
                raise AgentOwnerUnavailable('UnitSpec is outside the selected run permission')
            resolution = resolve_unit_profile(self.profile_service, spec.profile_revision,
                                              self.admission.harness_catalog)
            snapshot = self.environment.snapshot
            node = {'environmentNamespace': self.admission.environment_namespace,
                    'nodeId': 'unit-' + uuid.uuid4().hex, 'generation': 1}
            roots = {key: str(Path(self.permission.root_directory) / node['nodeId'] / key)
                     for key in ('home', 'cwd', 'profile', 'tmp')}
            context = {'environmentNamespace': self.admission.environment_namespace,
                'nodeRef': node, 'privateRootFacts': roots,
                'harnessDefinitionRef': resolution.harness_descriptor.definition_ref,
                'directoryBindingRef': self.state.directory_ref(node, roots).to_dict(),
                'localUnitRun': {'ownerId': self.owner_id, 'permissionId': self.permission.identity,
                    'environmentIdentity': self.environment.identity,
                    'environmentGeneration': snapshot.generation, 'agentId': spec.agent_id,
                    'profileRevision': encode_revision_ref(spec.profile_revision)}}
            self._plan = sealed_mapping({'profileSnapshot': resolution.profile_snapshot, 'context': context})
            return self._plan

    def resolve(self, *args, **kwargs):
        # The new API owns fixed private-root resolution. Do not route old Node
        # preparation into an unrelated public Unit permission.
        raise AgentOwnerUnavailable('Local run owner is selected through public UnitManager.create')

    def _unit_context(self, subject):
        ports = self._bound()
        instance = ports.unit_manager.find(subject.identity)
        unit = ports.provider_view.records.owner_read_unit(subject.identity['unitId'])
        # Preparation records keep the actual original request, not a parallel
        # Unit inventory. Its operation fixes this permission and directory.
        request = json.loads(unit.facts['correlation'])['request']
        source = self.admission.store_port.read_operation(RequestKey(
            request['environmentNamespace'], request['principalScope'], request['requestId']))
        if source is None or source.intent.context_ref.get('localUnitRun', {}).get('ownerId') != self.owner_id:
            raise AgentOwnerUnavailable('Unit belongs to another run permission')
        return instance, unit, dict(source.intent.context_ref)

    def native_unit(self, unit, authorization):
        """Return this owner's original live UnitInstance behind an exact public view.

        This is a narrow composition seam for adapters which already consume
        the original instance. Possession of a copied facade, identity mapping,
        or stale permission does not expose the instance or create a lease.
        """
        self.ensure_unit_creation_ready()
        with self.authority.guard('interaction', authorization):
            self._bound()
            if type(unit) is not Unit or self.manager is None:
                raise AgentOwnerUnavailable('Exact public Unit view required')
            try:
                retained = self.manager.get(unit.identity)
            except Exception as error:
                raise AgentOwnerUnavailable('Original live Unit view is unavailable') from error
            if retained is not unit:
                raise AgentOwnerUnavailable('Exact retained public Unit view required')
            instance, _reservation, context = self._unit_context(unit)
            if instance is not unit._instance or self.state.check_interaction(instance, context) is not True:
                raise AgentOwnerUnavailable('Original live Unit interaction state is unavailable')
            return instance

    def authorize(self, action, subject, authorization):
        self.ensure_unit_creation_ready()
        with self.authority.guard(action, authorization):
            ports = self._bound()
            if action == 'prepare':
                if subject != self.spec or self._plan is None:
                    raise AgentOwnerUnavailable('Original fixed preparation plan required')
                context = dict(self._plan['context'])
                resolution = resolve_unit_profile(self.profile_service, subject.profile_revision,
                                                  self.admission.harness_catalog)
                provider = resolution.harness_provider_ref
            else:
                instance, unit, context = self._unit_context(subject)
                provider = unit.facts['providerRef']
            if action == 'interaction':
                if self.state.check_interaction(instance, context) is not True:
                    raise AgentOwnerUnavailable('Original live Unit interaction state is unavailable')
                key = safe_json(subject.identity)
                prior = self._connections.get(key)
                if prior is not None:
                    return prior
                def current_permission():
                    with self.authority.guard('interaction', authorization):
                        self._bound()
                        if self.state.check_interaction(instance, context) is not True:
                            raise AgentOwnerUnavailable('Original live Unit interaction state is unavailable')
                grant = self.lease.grant(subject.identity, revalidate=current_permission)
                self._connections[key] = grant
                self.authority._revoke_connections.append(lambda: self.lease.revoke(subject.identity))
                return grant
            if action not in {'prepare', 'start', 'stop', 'release'}:
                raise AgentOwnerUnavailable('Unsupported Unit lifecycle action')
            target = context['nodeRef']
            context['invocationBindings'] = {action: {'action': action, 'targetRef': target,
                                                       'delegationRef': None, 'cleanup': action in {'stop', 'release'}}}
            epoch = context['localUnitRun']['environmentGeneration']
            request = RequestKey(self.admission.environment_namespace, self.permission.principal_scope,
                                 'unit-' + uuid.uuid4().hex)
            operation_ref = request.request_id + '.' + action
            digest = _digest({'action': action, 'context': context})
            step = StepIntent(action, provider, digest, operation_ref + '.native', management_epoch=epoch)
            intent = OperationIntent(operation_ref, 'unit-public-' + action,
                                     encode_revision_ref(self.permission.profile_revision), context, (step,),
                                     node_ref=target, management_epoch=epoch)
            store = self.admission.store_port
            store.reserve_operation(request, digest, intent)
            invocation = ports.issuer.issue(request, digest, action, action, target,
                                            cleanup=action in {'stop', 'release'})
            self._operations[id(invocation)] = (invocation, request, digest, action)
            return invocation

    def authorize_acp_turn_query(self, authorization, request, unit_ref, operation_ref,
                                 *, expected_prompt_input_digest):
        """Issue one read-only ticket for an exact receipt in this owner's UnitRecords.

        The existing interaction permission authorizes this narrowed cold read;
        it creates no UnitRunPermission action, host grant, effect claim, or
        alternate record authority.
        """
        from ordessa_units.admission.invocation import InvocationAuthorityRefused
        if (type(request) is not RequestKey
                or request.environment_namespace != self.admission.environment_namespace
                or request.principal_scope != self.permission.principal_scope
                or type(operation_ref) is not str or not operation_ref
                or len(operation_ref) > 512 or any(ord(char) < 32 for char in operation_ref)
                or type(expected_prompt_input_digest) is not str
                or not expected_prompt_input_digest.startswith('sha256:')
                or len(expected_prompt_input_digest) != 71
                or any(char not in '0123456789abcdef' for char in expected_prompt_input_digest[7:])):
            raise InvocationAuthorityRefused('Exact original Unit receipt query inputs required')
        self.ensure_unit_creation_ready()
        with self.authority.guard('interaction', authorization):
            ports = self._bound()
            records = ports.provider_view.records
            if (self.acp_turn_opt_in is not True
                    or records.acp_turn_available is not True
                    or records.journal.acp_turn_opt_in is not True):
                raise InvocationAuthorityRefused('Original ACP schema opt-in is unavailable')
            if not isinstance(unit_ref, Mapping):
                raise InvocationAuthorityRefused('Complete original Unit reference required')
            resolver = getattr(records, 'owner_read_unit_for_query', None)
            if not callable(resolver):
                raise InvocationAuthorityRefused('Original query identity resolver unavailable')
            from ordessa_units.records.unit_records import UnitRecordsRefused
            try:
                reservation = resolver(unit_ref)
                if safe_json(reservation.public_ref) != safe_json(unit_ref):
                    raise UnitRecordsRefused('Unit receipt query differs from original records')
                source = self.state._verify_query_reservation_source(
                    reservation, reservation.facts.get('nodeRef'), principal_scope=request.principal_scope)
            except Exception as error:
                raise InvocationAuthorityRefused('Receipt query original source unavailable or changed') from error
            context = dict(source.intent.context_ref)
            generation = self.state._snapshot_generation().generation
            context['acpQuerySource'] = self.state._query_source_ref(source)
            # This is a new query under CURRENT authority, referring to an old
            # preparation. Never copy the old live owner/permission as our own.
            context['localUnitRun'] = {
                'ownerId': self.owner_id, 'permissionId': self.permission.identity,
                'agentId': self.permission.agent_id,
                'environmentIdentity': self.permission.environment_identity,
                'environmentGeneration': generation,
                'profileRevision': encode_revision_ref(self.permission.profile_revision)}
            digest = records.acp_turn_query_digest(
                reservation.public_ref, operation_ref, expected_prompt_input_digest)
            query_id = 'unit-acp-read-' + hashlib.sha256(safe_json({
                'request': {'environmentNamespace': request.environment_namespace,
                            'principalScope': request.principal_scope,
                            'requestId': request.request_id},
                'inputDigest': digest}).encode()).hexdigest()[:48]
            context['invocationBindings'] = {
                'read': {'action': 'query', 'targetRef': dict(reservation.facts['nodeRef']),
                         'delegationRef': None, 'cleanup': True}}
            context['acpTurnRead'] = {
                'unitRef': dict(reservation.public_ref),
                'operationRef': operation_ref,
                'expectedPromptInputDigest': expected_prompt_input_digest}
            step = StepIntent('read', reservation.facts['providerRef'], digest,
                              query_id + '.read', management_epoch=generation)
            intent = OperationIntent(query_id, 'unit-acp-query',
                source.intent.profile_snapshot_ref, context, (step,),
                node_ref=reservation.facts['nodeRef'], management_epoch=generation)
            self.admission.store_port.reserve_operation(request, digest, intent)
            return ports.issuer.issue_query(request, digest, 'read')

    def authorize_manager_close(self, authorization):
        """Prove both finite cleanup rights before the Manager begins draining."""
        with self.authority.guard('stop', authorization):
            with self.authority.guard('release', authorization):
                self._bound()
        return True

    def _preparation(self, plan, facts):
        self.ensure_unit_creation_ready()
        with self.authority.guard('prepare', self.authorization()):
            context = facts['contextRef']
            if (safe_json(plan['context']) != safe_json({key: value for key, value in context.items()
                                                       if key != 'invocationBindings'})
                    or context['localUnitRun']['ownerId'] != self.owner_id):
                raise AgentOwnerUnavailable('Preparation differs from its original reserved operation')
            return context['privateRootFacts']

    def _start(self, unit, invocation):
        ports = self._bound()
        return ports.issuer.verify_continuation(invocation, 'start', unit.facts['providerRef'],
                                               unit.facts['nodeRef'], invocation.facts['inputDigest'])

    def complete(self, action, subject, invocation, result, *, failed=False):
        """Conclude only from original records; failures preserve UNKNOWN claims."""
        entry = self._operations.get(id(invocation))
        if entry is None or entry[0] is not invocation or entry[3] != action:
            raise AgentOwnerUnavailable('Original local operation correlation required')
        _, request, digest, _ = entry
        store = self.admission.store_port
        step = store.read_operation_step(request, action)
        if step is None:
            raise AgentOwnerUnavailable('Original lifecycle claim is missing')
        if failed:
            store.record_operation_step(request, digest, action, step.intent.input_digest,
                                        step.revision, 'unknown', {'reason': 'original-unit-action-failed'})
            return
        unit = self._ports.provider_view.records.owner_read_unit(subject.identity['unitId'])
        if action == 'prepare':
            evidence = {'unitRef': unit.public_ref, 'scopeRef': unit.scope_ref.to_dict()}
        elif action == 'start':
            session = self._ports.provider_view.records.owner_read_session(unit.unit_ref)
            if session.state != 'confirmed':
                raise AgentOwnerUnavailable('Original session confirmation required')
            evidence = {'unitRef': unit.public_ref, 'sessionEvidence': session.native_facts}
        else:
            termination = self._ports.provider_view.records.owner_read_termination(unit.unit_ref, action)
            if termination is None or termination['state'] != 'confirmed' or result.get('state') != 'confirmed':
                self.complete(action, subject, invocation, result, failed=True)
                return
            evidence = {'unitRef': unit.public_ref, 'termination': termination}
        store.record_operation_step(request, digest, action, step.intent.input_digest,
                                    step.revision, 'concluded', evidence)
        operation = store.read_operation(request)
        store.publish_operation(request, digest, operation.revision, (action,), (), (),
                                {'nodeRef': unit.facts['nodeRef'], 'unitRef': unit.public_ref, 'action': action})

    def revoke(self):
        self.authority.revoke()


def build_local_unit_owner(*, admission_context, permission, environment_instance,
                           preparation, materializer, environment_sharing, timeout=10,
                           callback_approval=None, process_binding_factory=None,
                           effect_write_guard_factory=None, acp_turn_opt_in=False,
                           defer_effect_write_guard_factory=False, clock=time.time,
                           managed_input_ports=None):
    """Select one concrete owner over already-owned Environment/Profile inputs.

    ``assemble(journal=...)`` binds a caller-provisioned original journal and
    returns the public UnitManager. Hosts that already have an assembled
    ``AgentOwnerPorts`` bundle may continue to call ``bind(ports)``. Callers
    pass ``spec`` and ``authorization()``; they never construct invocation
    contexts, native receipts or writer grants. Selection opens no record
    store and neither acquires nor spawns an Environment.
    """
    return LocalUnitOwner(admission_context=admission_context, permission=permission,
        environment_instance=environment_instance, preparation=preparation, materializer=materializer,
        environment_sharing=environment_sharing, timeout=timeout, callback_approval=callback_approval,
        process_binding_factory=process_binding_factory,
        effect_write_guard_factory=effect_write_guard_factory,
        acp_turn_opt_in=acp_turn_opt_in,
        defer_effect_write_guard_factory=defer_effect_write_guard_factory,
        managed_input_ports=managed_input_ports,
        clock=clock)


__all__ = ['build_local_unit_owner', 'LocalUnitOwner', 'UnitRunPermission']
