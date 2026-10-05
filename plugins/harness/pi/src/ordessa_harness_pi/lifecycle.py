"""Pi Unit lifecycle over the existing deployment-owned UnitRecords journal.

Only live process handles are retained here. The original journal/projection
owns all durable reservation, session and authority facts; no alternate store.
"""
from datetime import datetime, timezone
import json
import threading
from typing import Mapping, Protocol
from ordessa_environment_api.operations import safe_json, sealed_mapping
from pacthold.agents.configuration import UnitInspection
from pacthold.core.lifecycle import RUNTIME_PROVIDER_VERSION


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
    """Preserve Pi payload; per-write revoke/expiry/activation/epoch cut.

    bind returns an authorized entry, never the unrestricted PiRpcClient. Closing
    that entry disconnects; it must not kill the owner process or claim stop.
    """
    def bind(self, unit_ref, authorized_lease, client): ...


def plain(value):
    return json.loads(safe_json(value))


def records_ready(records, projection, verifier):
    return (records is not None and projection is not None and verifier is not None
        and getattr(records, 'verifier', None) is verifier
        and callable(getattr(verifier, 'verify_and_consume', None))
        and all(callable(getattr(records, method, None)) for method in
            ('reserve_unit','begin_session','record_session','read_unit','read_session'))
        and all(callable(getattr(projection, method, None)) for method in
            ('verify_preparation','revalidate_start','read_unit','read_session','publication_facts','publish_channel')))


class PiUnitLifecycle:
    def _lifecycle_init(self, records, projection, factory, lease):
        self.records, self.projection = records, projection
        self.channel_factory, self.lease_port = factory, lease
        self._channels = {}  # owned live handles only; never cold recovery proof
        self._lifecycle_lock = threading.RLock()

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
        if (provider.get('providerId') != 'pi' or provider.get('implementationDigest') != self.descriptor.implementation_digest
            or provider.get('contractVersion') != RUNTIME_PROVIDER_VERSION
            or not isinstance(plan, Mapping) or plan.get('context', {}).get('nodeRef') != facts['targetRef']):
            self._unsupported()
        # The same UnitRecords consumes the original prepare claim itself.
        roots = self.projection.verify_preparation(plan, facts)
        unit, created = self.records.reserve_unit(invocation_context, provider_ref=provider,
            node_ref=facts['targetRef'], input_digest=facts['inputDigest'], private_root_facts=roots)
        return {'unitRef':{'environmentNamespace':provider['environmentNamespace'],'unitId':unit.unit_ref},
                'created':created,'state':'notCreated'}

    def _unit_record(self, unit_ref):
        if not isinstance(unit_ref, Mapping) or set(unit_ref) != {'environmentNamespace','unitId'}:
            self._unsupported()
        unit = self.projection.read_unit(unit_ref)
        provider = unit.facts['providerRef']
        if (unit.unit_ref != unit_ref['unitId'] or provider.get('environmentNamespace') != unit_ref['environmentNamespace']
            or provider.get('providerId') != 'pi' or provider.get('implementationDigest') != self.descriptor.implementation_digest
            or provider.get('contractVersion') != RUNTIME_PROVIDER_VERSION):
            self._unsupported()
        return unit

    def _current_start(self, unit, context):
        facts = self.projection.revalidate_start(unit, context)
        original = context.facts
        if (not isinstance(facts, Mapping) or facts != original or facts.get('action') != 'start'
            or facts.get('query') is not False or facts.get('providerRef') != unit.facts['providerRef']
            or facts.get('targetRef') != unit.facts['nodeRef']
            or facts.get('managementEpoch') != unit.facts['managementEpoch']):
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
            self._current_start(unit, invocation_context)
            state = client.initialize()  # documented get_state; no invented handshake
            if not isinstance(state, Mapping) or not isinstance(state.get('sessionId'), str) or not state['sessionId']:
                self._unsupported()
            self._current_start(unit, invocation_context)
            observed = client.command('get_state').get('data')
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
        return UnitInspection(unit_ref,unit.facts['providerRef'],unit.scope_ref.to_dict(),
            projection['directoryBindingRef'],projection['managementEpoch'],'owned',
            projection['sourceRevision'],datetime.now(timezone.utc).isoformat(),projection['evidenceRef'])

    def query_step(self, correlation, authorized_read_context):
        self._required('query_step')
        facts = authorized_read_context.facts
        provider = facts['providerRef']
        if (provider.get('providerId') != 'pi' or provider.get('implementationDigest') != self.descriptor.implementation_digest
            or provider.get('contractVersion') != RUNTIME_PROVIDER_VERSION):
            self._unsupported()
        verified = self._verifier.verify_and_consume(authorized_read_context,'query',provider,facts['targetRef'],facts['inputDigest'])
        if verified != facts or verified.get('query') is not True:
            self._unsupported()
        return self.projection.query_creation(correlation, verified)

    def describe_access(self, unit_ref):
        self._required('describe_access')
        unit = self._unit_record(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != 'confirmed' or unit.unit_ref not in self._channels:
            self._unsupported()
        return {'protocol':'pi-rpc/1','unitRef':plain(unit_ref),'nativeSessionId':binding.native_facts['sessionId'],
                'leaseRequired':True,'fullNativeSideEffects':True,'readonlySupported':False}

    def connect(self, unit_ref, authorized_lease):
        self._required('connect')
        unit = self._unit_record(unit_ref)
        self.describe_access(unit_ref)
        return self.lease_port.bind(unit_ref,authorized_lease,self._channels[unit.unit_ref])
