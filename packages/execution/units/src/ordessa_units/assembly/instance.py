"""Instance assembly over the retained original Unit handles and records."""
from collections.abc import Mapping
import json
from threading import RLock
from uuid import uuid4

from ordessa_agents.profiles import encode_revision_ref
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_units.definitions import UnitSpec
from ordessa_units.management import UnitManager as OriginalManager
from ordessa_units.management import UnitManagementRefused
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused, same_reference
from ordessa_units.errors import UnitApiRefused, UnitReconnectUnavailable
from ordessa_units.api.unit import Unit
from ordessa_units.api.interaction import UnitInteraction
from ordessa_units.records import UnitRecordsRefused


class UnitAssembly:
    def __init__(self, original, bindings):
        if type(original) is not OriginalManager or any(
                not callable(getattr(bindings, method, None))
                for method in ('resolve_plan', 'authorize')):
            raise UnitApiRefused('Original Unit owner and explicit resolution/authorization bindings required')
        self.original, self.bindings = original, bindings
        self._handles = {}  # views only; get/list revalidate the original owner
        self._interactions = {}  # writer views only, no durable state
        self._lock = RLock()

    def _handle(self, instance):
        return self._handles.setdefault(instance, Unit(self, instance))

    def _complete(self, action, subject, context, result, *, failed=False):
        complete = getattr(self.bindings, 'complete', None)
        if callable(complete):
            complete(action, subject, context, result, failed=failed)

    def _owned(self, unit):
        if (type(unit) is not Unit or unit._assembly is not self
                or self._handles.get(unit._instance) is not unit):
            raise UnitApiRefused('Unit belongs to another Manager')
        try:
            original = self.original.find(unit.identity)
        except UnitManagementRefused as error:
            raise UnitApiRefused('Original live Unit unavailable') from error
        if original is not unit._instance:
            raise UnitApiRefused('Original Unit owner changed')
        return original

    def create(self, spec, authorization):
        if type(spec) is not UnitSpec:
            raise UnitApiRefused('UnitSpec with fixed Profile and existing Environment required')
        with self._lock:
            with self.original._lock:
                if self.original._draining:
                    raise UnitApiRefused('Original Unit Manager is closing')
            plan = self.bindings.resolve_plan(spec, authorization)
            if (not isinstance(plan, Mapping) or not same_reference(
                    plan.get('profileSnapshot', {}).get('ref'), encode_revision_ref(spec.profile_revision))):
                raise UnitApiRefused('Resolved Profile differs from UnitSpec')
            context = self.bindings.authorize('prepare', spec, authorization)
            try:
                instance = self.original.create(plan, context, specification=spec)
            except UnitManagementRefused as error:
                self._complete('prepare', spec, context, None, failed=True)
                raise UnitApiRefused('Unit preparation refused by original owner') from error
            except BaseException:
                self._complete('prepare', spec, context, None, failed=True)
                raise
            unit = self._handle(instance)
            self._complete('prepare', unit, context, instance.prepared_unit)
            context = self.bindings.authorize('start', unit, authorization)
            try:
                result = self.original.start(instance.prepared_unit, context)
            except BaseException:
                self._complete('start', unit, context, None, failed=True)
                raise
            self._complete('start', unit, context, result)
            return unit

    def get(self, identity):
        try:
            return self._handle(self.original.find(identity))
        except UnitManagementRefused as error:
            raise UnitApiRefused('Complete original live Unit identity required') from error

    def list(self):
        return tuple(self._handle(instance) for instance in self.original.list())

    def snapshot(self, unit):
        # No private roots, launch argv, captured input or credential data leaves.
        instance = unit._instance
        if self._handles.get(instance) is not unit:
            raise UnitApiRefused('Original Unit view required')
        instance._unit_record(unit.identity)
        binding = instance.records.owner_read_session(unit.identity['unitId'])
        stop = instance.records.owner_read_termination(unit.identity['unitId'], 'stop')
        release = instance.records.owner_read_termination(unit.identity['unitId'], 'release')
        state = 'prepared' if binding.state == 'notCreated' else binding.state
        if stop is not None:
            state = 'stopped' if stop['state'] == 'confirmed' else 'unknown'
        if release is not None:
            state = 'released' if release['state'] == 'confirmed' else 'unknown'
            with self.original._lock:
                if release['state'] == 'confirmed' and unit.identity['unitId'] in self.original._units:
                    state = 'releasePending'
        definition = instance.definition
        return sealed_mapping({'identity': unit.identity, 'state': state,
            'definition': {'agentId': definition.agent_id, 'harnessId': definition.harness_id,
                'profileRevision': encode_revision_ref(definition.profile_revision),
                'environmentReference': definition.environment_reference},
            'sessionId': (binding.native_facts or {}).get('sessionId'),
            'reconnectSupported': False})

    def interaction(self, unit, authorization):
        instance = self._owned(unit)
        prior = self._interactions.get(instance)
        if prior is not None:
            if prior._disconnected:
                raise UnitReconnectUnavailable('Original writer disconnected; no session relaunch')
            # Authorization is checked for each attachment, not inferred from
            # possession of this Unit or a previously returned interaction.
            grant = self.bindings.authorize('interaction', unit, authorization)
            if grant is not prior._connection._binding.grant:
                raise UnitApiRefused('Original interaction is already bound to another authorization')
            return prior
        grant = self.bindings.authorize('interaction', unit, authorization)
        interaction = UnitInteraction(unit, instance.connect(unit.identity, grant))
        self._interactions[instance] = interaction
        return interaction

    def request(self, unit, connection, method, params, timeout, *, operation_ref=None):
        instance = self._owned(unit)
        self._require_connection(instance, connection)
        if method != 'session/prompt' and operation_ref is not None:
            raise UnitApiRefused('Stable operation reference is only supported for session/prompt')
        session = instance.projection.read_session(unit.identity).native_facts['sessionId']
        if params.get('sessionId', session) != session:
            raise UnitApiRefused('Native request belongs to another Unit session')
        if method == 'session/prompt':
            if getattr(self.bindings, '_managed_inputs', None) is not None:
                raise UnitApiRefused('Selected Unit requires its original managed-input capture')
            if 'operationRef' in params:
                raise UnitApiRefused('Prompt operation reference is owned by the original Unit')
            if (instance._effect_write_guard_factory is not None
                    or instance._fixed_effect_write_guard_factory is not None):
                raise UnitApiRefused('Canonical effect-guarded prompts require their original Engineering binding')
            native = dict(params, sessionId=session)
            try:
                receipt = instance.prompt(unit.identity, connection._binding.grant,
                    operation_ref=(operation_ref if operation_ref is not None
                                   else 'unit-prompt/' + uuid4().hex),
                    timeout=timeout, params=native)
            except (UnitLifecycleRefused, UnitRecordsRefused) as error:
                # Translate only the original owner's typed local refusal at
                # the public API boundary. Native ACP failures and durable
                # unknowns have their own types and remain distinguishable.
                raise UnitApiRefused(str(error)) from error
            response = receipt.get('response') if isinstance(receipt, Mapping) else None
            if isinstance(response, Mapping) and isinstance(response.get('error'), Mapping):
                from ordessa_agents.harness.protocols.acp import AcpRemoteError
                raise AcpRemoteError('session/prompt', response.get('id'), response['error'])
            if not isinstance(response, Mapping) or 'result' not in response:
                raise UnitApiRefused('Original recorded prompt has no confirmed native result')
            # Records deliberately seal their evidence. Restore only the native
            # JSON result representation, including lists, at the ACP boundary.
            return json.loads(safe_json(response['result']))
        # A fresh outer mapping binds identity; opaque values remain unchanged.
        native = dict(params)
        if method.startswith('session/'):
            native['sessionId'] = session
        return connection.request(method, native, timeout=timeout, on_request=instance.callbacks.handle)

    def cancel(self, unit, connection):
        instance = self._owned(unit)
        self._require_connection(instance, connection)
        session = instance.projection.read_session(unit.identity).native_facts['sessionId']
        return connection.cancel(sessionId=session)

    def submit_input(self, unit, connection, request, captured_ref, *, timeout):
        instance = self._owned(unit)
        self._require_connection(instance, connection)
        submit = getattr(self.bindings, 'submit_managed_input', None)
        authorize = getattr(self.bindings, 'authorization', None)
        if not callable(submit) or not callable(authorize):
            raise UnitApiRefused('Original managed ACP input owner unavailable')
        return submit(unit, authorize(), request, captured_ref, timeout=timeout)

    def read_input(self, authorization, request, unit_ref, captured_ref):
        # A receipt read requires neither a live Unit nor a writer connection.
        # The bound original owner still verifies current permission, issuer,
        # exact request/capture/Unit and its own Records query authority.
        read = getattr(self.bindings, 'read_managed_input', None)
        if not callable(read):
            raise UnitApiRefused('Original managed ACP input owner unavailable')
        return read(authorization, request, unit_ref, captured_ref)

    def _require_connection(self, instance, connection):
        retained = self._interactions.get(instance)
        if retained is None or retained._connection is not connection:
            raise UnitApiRefused('Original authorized Unit interaction required')
        connection._port._require_writable(connection)

    @staticmethod
    def _pending_close(instance, identity):
        try:
            observation = instance.quiescence_observation()
        except Exception:
            observation = {'reason': 'observation_unavailable'}
        return sealed_mapping({'identity': identity, 'state': 'pending',
                               'unresolved': True, 'quiescence': observation})

    def close_unit(self, unit, authorization):
        with self._lock:
            instance = unit._instance
            if self._handles.get(instance) is not unit:
                raise UnitApiRefused('Original Unit view required')
            # Prove both original cleanup rights before changing native SDK
            # admission. This owner preflight has no Operation/UnitRecords
            # claim side effect; the real stop/release invocations are issued
            # only after the exact retained client is idle and quiesced.
            authorize_close = getattr(self.bindings, 'authorize_manager_close', None)
            try:
                if not callable(authorize_close) or authorize_close(authorization) is not True:
                    return sealed_mapping({'identity': unit.identity, 'state': 'refused'})
            except Exception:
                return sealed_mapping({'identity': unit.identity, 'state': 'refused'})
            identity = unit.identity
            release = instance.records.owner_read_termination(identity['unitId'], 'release')
            if release is not None and release['state'] == 'confirmed':
                try:
                    self.original.find(identity)
                except UnitManagementRefused:
                    return sealed_mapping({'identity': identity, 'state': 'confirmed'})
                # A confirmed process release can still have an incomplete Use
                # or Node COMMIT. Do not replay the release to fake a close.
                return sealed_mapping({'identity': identity, 'state': 'partial'})
            instance = self._owned(unit)
            stop = instance.records.owner_read_termination(identity['unitId'], 'stop')
            if any(row is not None and row['state'] != 'confirmed' for row in (stop, release)):
                return sealed_mapping({'identity': identity, 'state': 'unknown'})
            try:
                if instance.try_quiesce() is not True:
                    return self._pending_close(instance, identity)
            except Exception:
                # A damaged/missing gate is not evidence of idleness. Keep the
                # handle and all original Use/termination state for inspection.
                return self._pending_close(instance, identity)
            try:
                if stop is None:
                    context = self.bindings.authorize('stop', unit, authorization)
                    try:
                        stopped = instance.stop(identity, context)
                    except BaseException:
                        self._complete('stop', unit, context, None, failed=True)
                        raise
                    self._complete('stop', unit, context, stopped)
                    if stopped.get('state') != 'confirmed':
                        return sealed_mapping({'identity': identity, 'state': 'unknown'})
                context = self.bindings.authorize('release', unit, authorization)
                try:
                    result = self.original.release(identity, context)
                except BaseException:
                    self._complete('release', unit, context, None, failed=True)
                    raise
                self._complete('release', unit, context, result)
                return sealed_mapping({'identity': identity, 'state': result['state']})
            except Exception:
                stop = instance.records.owner_read_termination(identity['unitId'], 'stop')
                release = instance.records.owner_read_termination(identity['unitId'], 'release')
                state = ('unknown' if any(row is not None and row['state'] != 'confirmed'
                                         for row in (stop, release)) else
                         'refused' if stop is None and release is None else 'partial')
                return sealed_mapping({'identity': identity, 'state': state})

    def close_manager(self, authorization):
        with self._lock:
            authorize_close = getattr(self.bindings, 'authorize_manager_close', None)
            if not callable(authorize_close) or authorize_close(authorization) is not True:
                raise UnitApiRefused('Exact manager close authorization required')
            self.original.drain()
            # One damaged owner must not prevent closing healthy siblings.
            # This is the original owner's retained handle inventory; no new
            # durable inventory or reconstructed native handle is introduced.
            with self.original._lock:
                entries = tuple(self.original._units.values())
            # Quiesce every exact original Unit before any sibling is stopped
            # or released. Idle clients may now reject further native calls;
            # a busy or unverifiable member leaves every UnitRecords row,
            # Environment Use and process handle untouched for a later close.
            try:
                idle = tuple(instance.try_quiesce() is True for instance, _identity in entries)
            except Exception:
                idle = ()
            if len(idle) != len(entries) or not all(idle):
                # The Server's zero-effect all-Units-pending proof has an exact
                # shape. Detailed observations belong to authorized Unit.close.
                pending = tuple(sealed_mapping({'identity': identity, 'state': 'pending', 'unresolved': True})
                                for _instance, identity in entries)
                return sealed_mapping({'state': 'pending', 'units': pending, 'unresolved': True})
            results = []
            for instance, identity in entries:
                try:
                    result = self.close_unit(self._handle(instance), authorization)
                except Exception:
                    result = sealed_mapping({'identity': identity, 'state': 'refused'})
                results.append(result)
            unresolved = self.original.has_unsettled_creations()
            return sealed_mapping({'state': 'partial' if unresolved or any(
                result['state'] != 'confirmed' for result in results) else 'confirmed',
                'units': tuple(results), 'unresolved': unresolved})
