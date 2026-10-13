"""One complete Unit facade over the original records/lifecycle owner.

Only owned live handles and immutable preparation carriers are held here.
Reservation, opening, unknown, fencing and termination stay in UnitRecords.
No record-store creation, grant minting, recovery relaunch or alternate journal.
"""
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycle, UnitLifecycleRefused
from ordessa_units.sessions.acp_factory import AcpChannelFactory
from ordessa_units.sessions.callbacks import UnitCallbacks
from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref, decode_revision
from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_units.lifecycle.unit_lifecycle import same_reference, plain
from collections.abc import Mapping
from ordessa_units.definitions import UnitDefinition
from .planning import fixed_profile_plan


class UnitInstance(UnitLifecycle):
    def __init__(self, *, descriptor, agent_id, profile_revision, environment_instance, environment_sharing,
                 environment_reference, preparation, materializer, records, projection,
                 verifier, lease_port, termination_evidence, session_id=None, timeout=10, callback_approval=None,
                 effect_write_guard_factory=None, process_binding=None):
        if records.verifier is not verifier:
            raise UnitLifecycleRefused('Unit must share the original invocation verifier')
        if not agent_id or type(profile_revision) is not ProfileRevisionRef:
            raise UnitLifecycleRefused('Unit requires a fixed Agent and Profile revision')
        self.descriptor = descriptor
        self.provider_id = descriptor.provider_id
        self.protocol_id = 'acp/v1'
        self._definition = UnitDefinition(agent_id, preparation.harness_id, profile_revision, environment_reference)
        self._verifier = verifier
        self.termination_evidence = termination_evidence
        if process_binding is not None and any(not callable(getattr(process_binding, name, None))
                for name in ('attach', 'fix_start', 'close')):
            raise UnitLifecycleRefused('Trusted fixed process binding required')
        self._process_binding = process_binding
        if effect_write_guard_factory is not None and not callable(effect_write_guard_factory):
            raise UnitLifecycleRefused('Trusted operation write guard factory required')
        self._effect_write_guard_factory = effect_write_guard_factory
        self._fixed_effect_write_guard_factory = effect_write_guard_factory
        self._effect_write_owner = object() if effect_write_guard_factory is not None else None
        factory = AcpChannelFactory(environment_instance=environment_instance, environment_sharing=environment_sharing,
            environment_reference=self.definition.environment_reference, preparation=preparation,
            materializer=materializer, agent_id=agent_id, profile_revision=safe_json(encode_revision_ref(profile_revision)),
            session_id=session_id, timeout=timeout,
            effect_write_guard_required=effect_write_guard_factory is not None,
            effect_write_owner=self._effect_write_owner)
        self._lifecycle_init(records, projection, factory, lease_port)
        # Live selection is a process-local source fence over this exact
        # retained Unit. It grants no permission and stores no durable state.
        self._selection_fences = {}
        if callback_approval is not None and not callable(getattr(callback_approval, 'authorize', None)):
            raise UnitLifecycleRefused('Explicit callback approval owner must provide authorize')
        self.callbacks = UnitCallbacks(self, callback_approval)
        factory.client_capabilities = self.callbacks.capabilities()
        self._callback_unit_id = None
        self._prepared_unit = None
        self._connections = {}  # borrowed live views, no durable/grant authority
        projection.bind_factory(factory)
        if termination_evidence is not projection:
            termination_evidence.bind_factory(factory)

    def _unsupported(self):
        raise UnitLifecycleRefused('Unit capability or fixed owner binding unavailable')

    def _unknown_creation(self):
        raise UnitLifecycleRefused('Unit creation unknown; original attempt retained, no relaunch')

    def plan_preparation(self, snapshot, context, correlation):
        self._required('plan_preparation')
        try:
            plan = fixed_profile_plan(snapshot, context, correlation)
            revision = decode_revision({'ref':plain(plan['profileSnapshot']['ref']),
                                        'content':plain(plan['profileSnapshot']['manifest'])})
        except Exception:
            self._unsupported()
        if revision.ref != self.profile_revision:
            raise UnitLifecycleRefused('Preparation does not bind the fixed complete Profile revision')
        return plan

    def start(self, prepared_unit, invocation_context):
        # Hold the original lifecycle lock across launch, attachment and the
        # original opening/unknown record transition. A concurrent stop can
        # neither mistake an in-progress placeholder for an idle process nor
        # race the final retained-handle registration.
        with self._lifecycle_lock:
            if self._selection_fences:
                raise UnitLifecycleRefused('live Unit selection is fenced')
            try:
                if self._process_binding is not None:
                    self._process_binding.fix_start(prepared_unit, invocation_context)
                self._callback_unit_id = prepared_unit['unitRef']['unitId']
                return super().start(prepared_unit, invocation_context)
            finally:
                # Even attachment failure keeps the environment's spawned
                # handle reachable by original stop; it must never become
                # ownedProcess=none.
                record = self.channel_factory.owned_record
                if record is not None:
                    unit_id = prepared_unit['unitRef']['unitId']
                    self._channels[unit_id] = record.entry
                    self.termination_evidence.bind_unit_channel(unit_id, record)

    def prepare(self, plan, invocation_context):
        # The original prepare invocation is verified/consumed and reserved
        # before acquisition/materialization effects. Holding this facade or
        # PreparedAgent is not permission.
        if not same_reference(plan.get('profileSnapshot', {}).get('ref'), encode_revision_ref(self.profile_revision)):
            raise UnitLifecycleRefused('Prepared Run must bind the fixed complete Profile revision')
        snapshot = plan['profileSnapshot']
        decode_revision({'ref':plain(snapshot['ref']), 'content':plain(snapshot['manifest'])})
        result = super().prepare(plan, invocation_context)
        if not result['created'] and self.channel_factory.prepared_agent is None:
            raise UnitLifecycleRefused('Existing Unit requires original-owner recovery, never new preparation')
        unit = self._unit_record(result['unitRef'])
        self._prepared_unit = sealed_mapping(plain(result))
        bind = getattr(self.projection, 'bind_preparation', None)
        if callable(bind):
            bind(unit.unit_ref, self.channel_factory, unit.facts['privateRootFacts'])
        if self.termination_evidence is not self.projection:
            bind = getattr(self.termination_evidence, 'bind_preparation', None)
            if callable(bind):
                bind(unit.unit_ref, self.channel_factory, unit.facts['privateRootFacts'])
        self.channel_factory.prepare(unit.facts['privateRootFacts'], invocation_context.facts,
                                     sealed_mapping(plain(snapshot)))
        return result

    @property
    def prepared_unit(self):
        if self._prepared_unit is None:
            raise UnitLifecycleRefused("Original Unit preparation receipt unavailable")
        self._unit_record(self._prepared_unit["unitRef"])
        return self._prepared_unit

    @property
    def definition(self):
        return self._definition

    @property
    def agent_id(self):
        return self.definition.agent_id

    @property
    def profile_revision(self):
        return self.definition.profile_revision

    @property
    def prepared_agent(self):
        return self.channel_factory.prepared_agent

    @property
    def environment_identity(self):
        return self.channel_factory.environment.environment_id

    def require_effect_write_guard(self, factory):
        """Check exact trusted fixed configuration; grant/reserve/send nothing."""
        from ordessa_execution_agents.harness.transport import EffectWriteRefused
        from ordessa_units.sessions.sdk_client import SdkAcpClient
        if not self._lifecycle_lock.acquire(blocking=False):
            raise EffectWriteRefused('original Unit configuration owner is busy')
        try:
            channel_factory = self.channel_factory
            owner = self._effect_write_owner
            if (not callable(factory) or self._fixed_effect_write_guard_factory is not factory
                    or self._effect_write_guard_factory is not factory or owner is None
                    or not channel_factory.effect_write_guard_required
                    or channel_factory._effect_write_owner is not owner):
                raise EffectWriteRefused('exact fixed operation write guard factory required')
            record = channel_factory.owned_record
            if record is not None and (type(record.entry) is not SdkAcpClient
                    or not record.entry._require_effect_write_guard
                    or record.entry._effect_write_owner is not owner):
                raise EffectWriteRefused('original SDK operation write guard binding differs')
        finally:
            self._lifecycle_lock.release()

    @property
    def effect_write_thread(self):
        """Expose the original SDK target through this retained Unit owner.

        This read-only seam supplies Engineering’s handoff with the real
        ``threading.Thread`` object. It never exposes the SDK private field,
        creates a Thread/token/permission, or holds Unit locks beyond lookup.
        """
        from ordessa_units.sessions.acp_factory import AcpChannelRecord
        from ordessa_units.sessions.sdk_client import SdkAcpClient
        from ordessa_execution_agents.harness.transport import EffectWriteRefused

        if not self._lifecycle_lock.acquire(blocking=False):
            raise UnitLifecycleRefused('Original Unit lifecycle owner is busy')
        try:
            factory = self.channel_factory
            record = factory.owned_record
            if (self._fixed_effect_write_guard_factory is None
                    or self._effect_write_guard_factory is not self._fixed_effect_write_guard_factory
                    or not factory.effect_write_guard_required
                    or factory._effect_write_owner is not self._effect_write_owner
                    or type(record) is not AcpChannelRecord
                    or type(record.entry) is not SdkAcpClient
                    or record.prepared_agent is not self.prepared_agent
                    or factory.record(record.entry) is not record
                    or self._callback_unit_id is None
                    or self._channels.get(self._callback_unit_id) is not record.entry):
                raise UnitLifecycleRefused('Exact guarded original ACP target is unavailable')
            self.require_effect_write_guard(self._fixed_effect_write_guard_factory)
            source_unit = self.records.owner_read_unit(self._callback_unit_id)
            if source_unit is None:
                raise UnitLifecycleRefused('Original ACP Unit record is unavailable')
            unit = self._unit_record(source_unit.public_ref)
            session = self.projection.read_session(unit.public_ref)
            stop = self.records.owner_read_termination(unit.unit_ref, 'stop')
            release = self.records.owner_read_termination(unit.unit_ref, 'release')
            use = factory.environment
            if (session is None or session.state != 'confirmed'
                    or session.native_facts.get('sessionId') != record.entry.session_id
                    or stop is not None or release is not None
                    or record.process.observe().state != 'running'
                    or use is None or record.environment_identity != use.environment_id
                    or record.environment_use_identity != use.identity
                    or factory.instance.identity != use.environment_id):
                raise UnitLifecycleRefused('Original ACP Unit target is not live and confirmed')
            check = getattr(use, 'check', None)
            if not callable(check):
                raise UnitLifecycleRefused('Original Environment Use check unavailable')
            check(use.environment_id, use.generation, allow_unknown=False)
            try:
                return record.entry.effect_write_thread
            except EffectWriteRefused as error:
                raise UnitLifecycleRefused('Original SDK effect-write target unavailable') from error
        finally:
            self._lifecycle_lock.release()

    def prompt(self, unit_ref, authorized_lease, **params):
        # A consumer still passes through the original lease port. Native
        # side-effect permissions/fs/terminal callbacks are explicit inputs.
        if self._effect_write_guard_factory is not None:
            raise UnitLifecycleRefused('Guarded Unit requires original recorded operation prompt')
        session_id = self.projection.read_session(unit_ref).native_facts['sessionId']
        if params.get('sessionId', session_id) != session_id:
            raise UnitLifecycleRefused('Prompt belongs to a different fixed Run session')
        if 'on_request' in params:
            raise UnitLifecycleRefused('Unit callbacks are bound to the original environment/approval owner')
        params['on_request'] = self.callbacks.handle
        params['sessionId'] = session_id
        return self.connect(unit_ref, authorized_lease).prompt(**params)

    def connect(self, unit_ref, authorized_lease):
        self.describe_access(unit_ref)
        key = (unit_ref['unitId'], id(authorized_lease))
        with self._lifecycle_lock:
            cached = self._connections.get(key)
            if cached is not None and cached[0] is authorized_lease:
                return cached[1]  # its original per-write gate still revalidates
            entry = super().connect(unit_ref, authorized_lease)
            self._connections[key] = (authorized_lease, entry)
            return entry

    def prompt_recorded(self, unit_ref, authorized_lease, *, operation_ref, timeout=60, **params):
        """One explicitly recorded ACP operation on the original journal/lease."""
        from ordessa_units.sessions.recorded_prompt import prompt_recorded
        # The durable reservation starts before the wire write, and finishing
        # the original receipt may continue after the native response arrives.
        # Keep the original SDK admission open for that entire transaction.
        record = self.channel_factory.owned_record
        if record is None:
            raise UnitLifecycleRefused('Original retained ACP client required for recorded prompt')
        from ordessa_units.sessions.sdk_client import SdkAcpClient
        client = record.entry
        if type(client) is not SdkAcpClient:
            raise UnitLifecycleRefused('Original ACP client ownership required for recorded prompt')
        admitted = getattr(client, 'admitted_operation', None)
        if not callable(admitted):
            raise UnitLifecycleRefused('Original ACP native admission gate unavailable')
        # The original SDK owner tracks the full request/receipt span. Do not
        # hold the Unit lifecycle lock while the SDK loop waits for a peer.
        with admitted():
            return prompt_recorded(self, unit_ref, authorized_lease,
                operation_ref=operation_ref, timeout=timeout, params=params)

    def _acquire_selection_fence(self, validator):
        if not callable(validator):
            raise UnitLifecycleRefused('Original live selection validator required')
        with self._lifecycle_lock:
            token = object()
            self._selection_fences[token] = validator
            return token

    def _release_selection_fence(self, token):
        with self._lifecycle_lock:
            if self._selection_fences.pop(token, None) is None:
                raise UnitLifecycleRefused('Original live selection fence was lost')

    def _validate_selection_fences(self):
        with self._lifecycle_lock:
            validators = tuple(self._selection_fences.values())
        for validate in validators:
            validate()

    def try_quiesce(self):
        """Close native request admission only when this original Unit is idle.

        The lifecycle lock prevents connection setup/configuration from racing
        the SDK gate. The gate is reached through the factory's exact retained
        process record; missing or substituted SDK ownership fails closed.
        """
        if not self._lifecycle_lock.acquire(blocking=False):
            return False
        try:
            if self._selection_fences:
                return False
            record = self.channel_factory.owned_record
            if record is None:
                return True
            from ordessa_units.sessions.sdk_client import SdkAcpClient
            client = record.entry
            if type(client) is not SdkAcpClient:
                # ProcessChannel.attach can fail after the Environment has
                # spawned the original process but before any SDK/channel IO
                # exists. Permit cleanup only for the exact retained factory
                # placeholder, registered to one original Unit whose session
                # outcome is already unknown. The start lock above excludes
                # an in-progress launch/attachment from this branch.
                from ordessa_units.sessions.acp_factory import AcpChannelRecord
                if (type(record) is not AcpChannelRecord or type(client) is not object
                        or record.channel is not None
                        or self.channel_factory.record(client) is not record):
                    return False
                unit_ids = [unit_id for unit_id, entry in self._channels.items() if entry is client]
                observation = record.process.observe()
                if (len(unit_ids) != 1 or observation.state not in {'running', 'exited'}):
                    return False
                try:
                    unit = self.records.owner_read_unit(unit_ids[0])
                    unit = self._unit_record(unit.public_ref)
                    session = self.projection.read_session(unit.public_ref)
                except Exception:
                    return False
                return (unit.unit_ref == unit_ids[0] and session.state == 'unknown'
                        and self._owned_record(unit) is record)
            quiesce = getattr(client, 'try_quiesce', None)
            return callable(quiesce) and quiesce() is True
        finally:
            self._lifecycle_lock.release()

    def _preflight_termination(self, unit_ref, invocation_context, action):
        """Check the exact still-issued termination ticket before SDK gating."""
        from ordessa_units.admission.invocation import InvocationAuthorityRefused

        unit = self._unit_record(unit_ref)
        verify_admission = getattr(self._verifier, 'verify_admission', None)
        if not callable(verify_admission):
            raise InvocationAuthorityRefused('Original invocation admission preflight unavailable')
        try:
            facts = invocation_context.facts
        except Exception:
            raise InvocationAuthorityRefused('Original issued termination invocation required') from None
        if not isinstance(facts, Mapping) or facts.get('action') != action or facts.get('query') is not False:
            raise InvocationAuthorityRefused('Exact original termination invocation required')
        verified = verify_admission(invocation_context, action, facts.get('providerRef'),
                                    facts.get('targetRef'), facts.get('inputDigest'))
        if (not isinstance(verified, Mapping) or verified.get('action') != action
                or verified.get('query') is not False
                or safe_json(verified.get('providerRef')) != safe_json(unit.facts['providerRef'])
                or safe_json(verified.get('targetRef')) != safe_json(unit.facts['nodeRef'])
                or verified.get('managementEpoch') != unit.facts['managementEpoch']):
            raise InvocationAuthorityRefused('Termination ticket does not bind this original Unit')
        # Re-read source Unit facts and existing termination rows after external
        # grant/current-state calls. A prior opening/unknown/confirmed attempt
        # can never be turned into a fresh native close by this preflight.
        current = self._unit_record(unit_ref)
        if current != unit:
            raise InvocationAuthorityRefused('Original Unit changed during termination preflight')
        stop = self.records.owner_read_termination(unit.unit_ref, 'stop')
        release = self.records.owner_read_termination(unit.unit_ref, 'release')
        if action == 'stop' and (stop is not None or release is not None):
            raise InvocationAuthorityRefused('Original Unit already has a termination attempt')
        if action == 'release':
            if release is not None:
                raise InvocationAuthorityRefused('Original Unit already has a release attempt')
            if stop is None or stop.get('state') != 'confirmed':
                # Keep the original structural refusal for a live process, but
                # only after the supplied release ticket has been revalidated.
                record = self._owned_record(unit)
                if record is not None and self.channel_factory.is_running(record):
                    self._refuse('live owned unit requires stop before release')
                raise InvocationAuthorityRefused('Release requires the original confirmed stop')
        return unit, verified

    def stop(self, unit_ref, invocation_context):
        """Preflight the original ticket before closing native admission."""
        self._required('stop')
        unit, _facts = self._preflight_termination(unit_ref, invocation_context, 'stop')
        if not self.try_quiesce():
            return {'unitRef': plain(unit_ref), 'action': 'stop',
                    'state': 'pending', 'unresolved': True}
        return super().stop(unit_ref, invocation_context)

    def cancel(self, unit_ref, authorized_lease):
        entry = self.connect(unit_ref, authorized_lease)
        return entry.cancel(sessionId=self.projection.read_session(unit_ref).native_facts['sessionId'])

    def release(self, unit_ref, invocation_context):
        self._required('release')
        unit, _facts = self._preflight_termination(unit_ref, invocation_context, 'release')
        record = self._owned_record(unit)
        if record is not None and self.channel_factory.is_running(record):
            # Preserve UnitLifecycle's no-kill rule without closing the SDK
            # admission gate for a release that cannot yet be performed.
            return super().release(unit_ref, invocation_context)
        if record is not None and not self.try_quiesce():
            return {'unitRef': plain(unit_ref), 'action': 'release',
                    'state': 'pending', 'unresolved': True}
        result = super().release(unit_ref, invocation_context)
        self.channel_factory.release_environment()
        if result.get('state') == 'confirmed' and self._process_binding is not None:
            self._process_binding.close()
        return result


    def configuration_snapshot(self, unit_ref, authorized_lease):
        from ordessa_units.configuration.acp_options import snapshot
        return snapshot(self, unit_ref, authorized_lease)

    def set_config_option(self, unit_ref, authorized_lease, *, config_id, value, expected_revision, invocation_context):
        from ordessa_units.configuration.acp_options import set_option
        with self._lifecycle_lock:
            if self._selection_fences:
                raise UnitLifecycleRefused('live Unit selection fences configuration writes')
            return set_option(self,unit_ref,authorized_lease,config_id=config_id,value=value,
                              expected_revision=expected_revision,invocation_context=invocation_context)

    def query_config_change(self, unit_ref, invocation_context):
        # Only the original persisted attempt is read; no observation/retry.
        unit = self._unit_record(unit_ref)
        facts = invocation_context.facts
        return self.records.query_configuration_change(unit.unit_ref,facts['operationRef'],invocation_context,
                                                       input_digest=facts['inputDigest'])
