"""Brand-independent provider-side Unit lifecycle.

Compose :class:`UnitLifecycle` into a runtime provider: this base owns the whole
run/session/termination mechanism over the deployment-owned UnitRecords journal
and the four injected ports. A brand supplies only its identity — the runtime
provider id, the native protocol name and its typed refusal — plus the
host-provided ``descriptor`` and ``_unsupported``.

Only live process handles are retained here. The original journal/projection
owns all durable reservation, session and authority facts; no alternate store.

The unified termination face is consumed here for the records path: stop
terminates the unit's owned native process (real effect, exit-code evidence
through the deployment's ``NativeTerminationEvidencePort``); release frees
this side's owned records/leases only and never kills (a live owned unit is
refused to its caller before any claim). Unknown outcomes keep the attempt,
its hold and its ticket; nothing is released or faked automatically.
"""
from datetime import datetime, timezone
import json
import threading
from typing import Mapping, Protocol

from ordessa_execution_agents.harness.definitions.runtime_providers import RUNTIME_PROVIDER_VERSION
from ordessa_execution_api.environment.operations import safe_json, sealed_mapping

from ..configuration.contracts import UnitInspection


class UnitLifecycleRefused(RuntimeError):
    """Typed refusal of a lifecycle effect. Brands subclass it for their own."""

    code = "UNIT_LIFECYCLE_REFUSED"


class UnitProjectionPort(Protocol):
    def verify_preparation(self, plan, invocation_facts): ...
    def revalidate_start(self, unit, invocation_context): ...
    def read_unit(self, unit_ref): ...
    def read_session(self, unit_ref): ...
    def publication_facts(self, unit_ref): ...
    def publish_channel(self, unit, client, native_evidence): ...
    def query_creation(self, correlation, verified_query_facts): ...


class ChannelFactoryPort(Protocol):
    """Fixed verified installation/root, managed writer, no fallback/model call."""
    def open(self, private_root_facts, verified_start_facts): ...


class ConnectionLeasePort(Protocol):
    """Preserve the native payload; per-write revoke/expiry/activation/epoch cut.

    bind returns an authorized entry, never the unrestricted native client.
    Closing that entry disconnects; it must not kill the owner process or claim
    stop.
    """
    def bind(self, unit_ref, authorized_lease, client): ...


class NativeTerminationEvidencePort(Protocol):
    """Original stop/release effect proof, never an ACK or a caller string.

    The deployment's owner verifies fixed installation/root, original unit
    and correlation and the actual termination effect against the real owned
    process; it returns only versioned provenance refs.
    """
    def bind_unit_channel(self, unit_ref, record): ...
    def verify_termination(self, unit, action, correlation, evidence): ...


def plain(value):
    return json.loads(safe_json(value))


def same_reference(left, right):
    """Compare the full original owner projection, retaining JSON scalar types."""
    try:
        return isinstance(left, Mapping) and isinstance(right, Mapping) and safe_json(left) == safe_json(right)
    except Exception:
        return False


def records_ready(records, projection, verifier):
    return (records is not None and projection is not None and verifier is not None
        and getattr(records, 'verifier', None) is verifier
        and callable(getattr(verifier, 'verify_and_consume', None))
        and all(callable(getattr(records, method, None)) for method in
            ('reserve_unit','begin_session','record_session','read_unit','read_session'))
        and all(callable(getattr(projection, method, None)) for method in
            ('verify_preparation','revalidate_start','read_unit','read_session','publication_facts','publish_channel')))


class UnitLifecycle:
    """The provider-side lifecycle mechanism, parameterized by brand identity.

    The host class must provide ``descriptor`` (with ``implementation_digest``
    and ``supported_methods``) and ``_unsupported()``. A brand subclass sets:

    - :attr:`provider_id` — the runtime provider id this lifecycle serves;
    - :attr:`protocol_id` — the native protocol name ``describe_access`` reports;
    - :attr:`refusal_type` — the brand's typed refusal class.
    """

    #: Runtime provider id this lifecycle serves.
    provider_id: str = ""

    #: Native protocol name reported by ``describe_access``.
    protocol_id: str = ""

    #: The typed refusal raised by :meth:`_refuse`.
    refusal_type = UnitLifecycleRefused

    def _lifecycle_init(self, records, projection, factory, lease):
        self.records, self.projection = records, projection
        self.channel_factory, self.lease_port = factory, lease
        self._channels = {}  # owned live handles only; never cold recovery proof
        self._lifecycle_lock = threading.RLock()

    def _refuse(self, detail):
        raise self.refusal_type(detail)

    def _required(self, method):
        if method not in self.descriptor.supported_methods:
            self._unsupported()

    def plan_preparation(self, snapshot, context, correlation):
        self._required('plan_preparation')
        if not isinstance(snapshot, Mapping) or not isinstance(context, Mapping):
            self._unsupported()
        if snapshot.get('manifest', {}).get('declarations'):
            self._unsupported()  # material acquisition/configuration owner not composed
        if not isinstance(context.get('privateRootFacts'), Mapping) or not context['privateRootFacts']:
            self._unsupported()
        return sealed_mapping({'profileSnapshot':plain(snapshot),'context':plain(context),'correlation':plain(correlation)})

    def prepare(self, plan, invocation_context):
        self._required('prepare')
        facts = invocation_context.facts
        provider = facts['providerRef']
        if (provider.get('providerId') != self.provider_id or provider.get('implementationDigest') != self.descriptor.implementation_digest
            or provider.get('contractVersion') != RUNTIME_PROVIDER_VERSION
            or not isinstance(plan, Mapping) or not same_reference(plan.get('context', {}).get('nodeRef'), facts['targetRef'])):
            self._unsupported()
        # The same UnitRecords consumes the original prepare claim itself.
        roots = self.projection.verify_preparation(plan, facts)
        unit, created = self.records.reserve_unit(invocation_context, provider_ref=provider,
            node_ref=facts['targetRef'], input_digest=facts['inputDigest'], private_root_facts=roots)
        reference = getattr(unit, 'public_ref', None)
        if (not isinstance(reference, Mapping) or set(reference) !=
                {'environmentNamespace','unitId','ownerProviderRef','sourceRevision'}
                or not same_reference(reference['ownerProviderRef'], provider) or reference['unitId'] != unit.unit_ref
                or reference['environmentNamespace'] != provider['environmentNamespace']):
            self._unsupported()
        return {'unitRef':plain(reference),
                'created':created,'state':'notCreated'}

    def _unit_record(self, unit_ref):
        if not isinstance(unit_ref, Mapping) or set(unit_ref) != {'environmentNamespace','unitId','ownerProviderRef','sourceRevision'}:
            self._unsupported()
        unit = self.projection.read_unit(unit_ref)
        provider = unit.facts['providerRef']
        if (not same_reference(getattr(unit, 'public_ref', None), unit_ref) or unit.unit_ref != unit_ref['unitId'] or provider.get('environmentNamespace') != unit_ref['environmentNamespace']
            or provider.get('providerId') != self.provider_id or provider.get('implementationDigest') != self.descriptor.implementation_digest
            or provider.get('contractVersion') != RUNTIME_PROVIDER_VERSION):
            self._unsupported()
        return unit

    def _current_start(self, unit, context):
        facts = self.projection.revalidate_start(unit, context)
        original = context.facts
        if (not isinstance(facts, Mapping) or not same_reference(facts, original) or facts.get('action') != 'start'
            or facts.get('query') is not False or not same_reference(facts.get('providerRef'), unit.facts['providerRef'])
            or not same_reference(facts.get('targetRef'), unit.facts['nodeRef'])
            or type(facts.get('managementEpoch')) is not int or facts.get('managementEpoch') != unit.facts['managementEpoch']):
            self._unsupported()
        return facts

    def start(self, prepared_unit, invocation_context):
        self._required('start')
        unit_ref = prepared_unit.get('unitRef')
        unit = self._unit_record(unit_ref)
        facts = invocation_context.facts
        # Opening is durably fixed BEFORE process launch. There is never a
        # replacement launch if any original creation binding already exists.
        ticket = self.records.begin_session(unit.unit_ref, invocation_context,input_digest=facts['inputDigest'])
        client = None
        try:
            verified = self._current_start(unit, invocation_context)
            client = self.channel_factory.open(unit.facts['privateRootFacts'], verified)
            # The opened owned channel record is bound for later termination
            # evidence verification (fixed installation/root/process identity).
            termination = getattr(self, 'termination_evidence', None)
            if (callable(getattr(termination, 'bind_unit_channel', None))
                    and callable(getattr(self.channel_factory, 'record', None))):
                termination.bind_unit_channel(unit.unit_ref, self.channel_factory.record(client))
            self._current_start(unit, invocation_context)
            handshake = self.channel_factory.handshake(
                client, before_effect=lambda: self._current_start(unit, invocation_context))
            state = self.channel_factory.establish_session(
                client, handshake, before_effect=lambda: self._current_start(unit, invocation_context))
            if not isinstance(state, Mapping) or not isinstance(state.get('sessionId'), str) or not state['sessionId']:
                self._unsupported()
            self._current_start(unit, invocation_context)
            observed = self.channel_factory.verify_session(client, state)
            if not isinstance(observed, Mapping) or observed.get('sessionId') != state['sessionId']:
                self._unsupported()
            self._current_start(unit, invocation_context)
            # Deployment supplies owner-verified native evidence, not a session
            # string fabricated from the plan or database reservation.
            evidence = self.projection.publish_channel(unit, client, observed)
            binding = self.records.record_session(ticket,expected_source_revision=2,state='confirmed',evidence=evidence)
            with self._lifecycle_lock:
                self._channels[unit.unit_ref] = client
            return {'unitRef':plain(unit_ref),'nativeBinding':plain(binding.native_facts),
                    'sourceRevision':str(binding.source_revision),'state':'confirmed'}
        except Exception:
            if client is not None:
                with self._lifecycle_lock:
                    self._channels[unit.unit_ref] = client
            try:
                self.records.record_session(ticket,expected_source_revision=2,state='unknown')
            except Exception:
                pass  # do not downgrade a concurrently confirmed original binding
            self._unknown_creation()

    def _inspect_record(self, unit_ref):
        unit = self._unit_record(unit_ref)
        projection = self.projection.publication_facts(unit_ref)
        if (not same_reference(projection.get('unitRef'), unit.public_ref)
                or not same_reference(projection.get('configurationTargetRef'), unit.configuration_target_ref)
                or type(projection.get('managementEpoch')) is not int or projection.get('managementEpoch') != unit.facts['managementEpoch']):
            self._unsupported()
        return UnitInspection(unit_ref,unit.facts['providerRef'],unit.configuration_target_ref,
            projection['directoryBindingRef'],projection['managementEpoch'],'owned',
            projection['sourceRevision'],datetime.now(timezone.utc).isoformat(),projection['evidenceRef'])

    def query_step(self, correlation, authorized_read_context):
        self._required('query_step')
        facts = authorized_read_context.facts
        provider = facts['providerRef']
        if (provider.get('providerId') != self.provider_id or provider.get('implementationDigest') != self.descriptor.implementation_digest
            or provider.get('contractVersion') != RUNTIME_PROVIDER_VERSION):
            self._unsupported()
        verified = self._verifier.verify_and_consume(authorized_read_context,'query',provider,facts['targetRef'],facts['inputDigest'])
        if not same_reference(verified, facts) or verified.get('query') is not True:
            self._unsupported()
        return self.projection.query_creation(correlation, verified)

    def describe_access(self, unit_ref):
        self._required('describe_access')
        unit = self._unit_record(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != 'confirmed' or unit.unit_ref not in self._channels:
            self._unsupported()
        return {'protocol':self.protocol_id,'unitRef':plain(unit_ref),'nativeSessionId':binding.native_facts['sessionId'],
                'leaseRequired':True,'fullNativeSideEffects':True,'readonlySupported':False}

    def connect(self, unit_ref, authorized_lease):
        self._required('connect')
        unit = self._unit_record(unit_ref)
        self.describe_access(unit_ref)
        return self.lease_port.bind(unit_ref,authorized_lease,self._channels[unit.unit_ref])

    # -- unified termination face (records path) ------------------------------
    def _live(self, unit_ref, unit):
        binding = self.projection.read_session(unit_ref)
        if binding.state != 'confirmed' or unit.unit_ref not in self._channels:
            self._refuse("live confirmed native owner unavailable")
        return binding, self._channels[unit.unit_ref]

    def _owned_record(self, unit):
        """Resolve the factory record of this unit's live owned channel, or None."""
        with self._lifecycle_lock:
            client = self._channels.get(unit.unit_ref)
        if client is None:
            return None
        return self.channel_factory.record(client)

    def _termination_correlation(self, unit, action):
        """Read the just-opened attempt's correlation from the owner projection."""
        row = self.records.owner_read_termination(unit.unit_ref, action)
        if not isinstance(row, Mapping) or not isinstance(row.get('identity'), Mapping):
            self._refuse("original termination attempt projection unavailable")
        correlation = row['identity'].get('correlation')
        if not isinstance(correlation, str) or not correlation:
            self._refuse("original termination correlation unavailable")
        return correlation

    def _conclude_termination(self, unit, ticket, action, error):
        """Record the unknown outcome and refuse; the attempt keeps its hold."""
        try:
            self.records.record_termination(ticket, expected_source_revision=1, state='unknown')
        except Exception:
            pass  # never downgrade a concurrently confirmed original attempt
        raise self.refusal_type(
            f"{action} outcome unknown; the original attempt retains its hold") from error

    def stop(self, unit_ref, invocation_context):
        self._required('stop')
        if not isinstance(unit_ref, Mapping):
            self._unsupported()
        unit = self._unit_record(unit_ref)
        facts = invocation_context.facts
        # The one original stop attempt for this Unit; consumed before effect.
        ticket = self.records.begin_termination(unit.unit_ref, invocation_context,
                                                input_digest=facts['inputDigest'], action='stop')
        try:
            observed = {'action': 'stop', 'observedAt': datetime.now(timezone.utc).isoformat()}
            record = self._owned_record(unit)
            if record is None:
                observed['ownedProcess'] = 'none'  # nothing owned was ever running
            else:
                code = self.channel_factory.close(record.entry)
                observed.update(self.channel_factory.termination_facts(record, code))
            observed['correlation'] = self._termination_correlation(unit, 'stop')
            outcome = self.records.record_termination(ticket, expected_source_revision=1,
                                                      state='confirmed', evidence=observed)
            return {'unitRef': plain(unit_ref), 'action': 'stop', 'state': outcome['state'],
                    'outcome': plain(outcome['outcome'])}
        except Exception as error:
            self._conclude_termination(unit, ticket, 'stop', error)

    def release(self, unit_ref, invocation_context):
        self._required('release')
        if not isinstance(unit_ref, Mapping):
            self._unsupported()
        unit = self._unit_record(unit_ref)
        record = self._owned_record(unit)
        if record is not None and self.channel_factory.is_running(record):
            # A live owned unit is stopped first; release never kills (A14),
            # never claims the destructive effect outside the stop ledger and
            # never consumes authority for an impossible release.
            self._refuse("live owned unit requires stop before release")
        facts = invocation_context.facts
        ticket = self.records.begin_termination(unit.unit_ref, invocation_context,
                                                input_digest=facts['inputDigest'], action='release')
        try:
            observed = {'action': 'release', 'observedAt': datetime.now(timezone.utc).isoformat()}
            if record is None:
                with self._lifecycle_lock:
                    self._channels.pop(unit.unit_ref, None)
                observed['ownedProcess'] = 'none'
            else:
                released = self.channel_factory.release(record.entry)
                with self._lifecycle_lock:
                    self._channels.pop(unit.unit_ref, None)
                observed.update(released)
            revoke = getattr(self.lease_port, 'revoke', None)
            if callable(revoke):
                revoke(unit_ref)  # this side's usage ends: borrowed views lose writes
            observed['correlation'] = self._termination_correlation(unit, 'release')
            outcome = self.records.record_termination(ticket, expected_source_revision=1,
                                                      state='confirmed', evidence=observed)
            return {'unitRef': plain(unit_ref), 'action': 'release', 'state': outcome['state'],
                    'outcome': plain(outcome['outcome'])}
        except Exception as error:
            self._conclude_termination(unit, ticket, 'release', error)


__all__ = [
    "ChannelFactoryPort",
    "ConnectionLeasePort",
    "NativeTerminationEvidencePort",
    "UnitLifecycle",
    "UnitLifecycleRefused",
    "UnitProjectionPort",
    "plain",
    "records_ready",
    "same_reference",
]
