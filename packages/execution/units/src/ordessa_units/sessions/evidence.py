"""Same-channel live evidence for UnitRecords; no journal or authority clone."""
from dataclasses import dataclass
import hashlib
from threading import RLock

from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.lifecycle.unit_lifecycle import same_reference, UnitLifecycleRefused


@dataclass(frozen=True)
class _SessionReceipt:
    unit_ref: str
    record: object
    session_id: str


class AcpUnitEvidence:
    def __init__(self, *, preparation_authority, start_authority, publication_owner=None, configuration_authority=None):
        if not callable(preparation_authority) or not callable(start_authority):
            raise UnitLifecycleRefused('Explicit preparation/start authorities required')
        self.preparation_authority, self.start_authority = preparation_authority, start_authority
        self.publication_owner = publication_owner
        self.configuration_authority = configuration_authority
        self._configuration_receipts = {}
        self.records = None
        self._factory_lock = RLock()
        self._factories = []
        self._unit_factories = {}
        self._factory_roots = {}
        self._bindings = {}
        self._receipts = {}

    def attach_owner(self, records):
        if self.records is not None and self.records is not records:
            raise UnitLifecycleRefused('Cannot replace original UnitRecords owner')
        self.records = records

    def bind_factory(self, factory):
        with self._factory_lock:
            if not any(item is factory for item in self._factories):
                self._factories.append(factory)

    def bind_preparation(self, unit_ref, factory, roots):
        with self._factory_lock:
            if not any(item is factory for item in self._factories):
                raise UnitLifecycleRefused('Foreign Unit channel factory')
            unit = self.records.owner_read_unit(unit_ref)
            if not same_reference(roots, unit.facts['privateRootFacts']):
                raise UnitLifecycleRefused('Original Unit preparation roots differ')
            prior = self._unit_factories.get(unit_ref)
            if prior is not None and prior is not factory:
                raise UnitLifecycleRefused('Cannot replace original Unit channel factory')
            if any(other is not factory and same_reference(other_roots, roots)
                   for other, other_roots in self._factory_roots.items()):
                raise UnitLifecycleRefused('Unit preparation roots already owned by another factory')
            self._unit_factories[unit_ref] = factory
            self._factory_roots[factory] = dict(roots)

    def _factory_for_unit(self, unit):
        with self._factory_lock:
            factory = self._unit_factories.get(unit.unit_ref)
            if factory is None or not same_reference(
                    unit.facts['privateRootFacts'], self._factory_roots.get(factory)):
                raise UnitLifecycleRefused('Original Unit process/root binding unavailable')
            return factory

    def verify_preparation(self, plan, facts):
        return self.preparation_authority(plan, facts)

    def revalidate_start(self, unit, context):
        return self.start_authority(unit, context)

    def read_unit(self, ref):
        return self.records.owner_read_unit(ref['unitId'])

    def read_session(self, ref):
        return self.records.owner_read_session(ref['unitId'])

    def bind_unit_channel(self, unit_ref, record):
        unit = self.records.owner_read_unit(unit_ref)
        factory = self._factory_for_unit(unit)
        if factory.record(record.entry) is not record:
            raise UnitLifecycleRefused('Foreign Unit native record')
        prior = self._bindings.get(unit_ref)
        if prior is not None and prior is not record:
            raise UnitLifecycleRefused('Unit already bound to a different process')
        self._bindings[unit_ref] = record

    def _record(self, unit):
        record = self._bindings.get(unit.unit_ref)
        factory = self._factory_for_unit(unit)
        if record is None or factory.owned_record is not record or not same_reference(unit.facts['privateRootFacts'], factory._roots):
            raise UnitLifecycleRefused('Original Unit process/root binding unavailable')
        return record

    def publish_channel(self, unit, client, observed):
        record = self._record(unit)
        if (record.entry is not client or record.process.observe().state != "running"
                or client.session_id != observed.get('sessionId')):
            raise UnitLifecycleRefused('Native ACP session is not observed on the original live channel')
        receipt = _SessionReceipt(unit.unit_ref, record, client.session_id)
        self._receipts[unit.unit_ref] = receipt
        return receipt

    def verify_binding(self, unit, correlation, evidence):
        receipt = self._receipts.get(unit.unit_ref)
        if receipt is None:
            raise UnitLifecycleRefused('Original same-channel session receipt missing')
        record = self._record(unit)
        if record is not receipt.record or record.entry.session_id != receipt.session_id:
            raise UnitLifecycleRefused('Original native ACP session identity changed')
        key = {'unit':unit.public_ref,'correlation':correlation,
               'environment':record.environment_identity,'process':record.process.identity,
               'session':receipt.session_id,'profileRevision':record.prepared_agent.profile_revision}
        ref = 'sha256:'+hashlib.sha256(safe_json(key).encode()).hexdigest()
        if evidence is not receipt and evidence != ref:
            raise UnitLifecycleRefused('Original same-channel session receipt missing or forged')
        # Stored provenance remains verifiable after stop. A fresh receipt
        # requires liveness; reading that original receipt does not relaunch.
        if evidence is receipt and record.process.observe().state != "running":
            raise UnitLifecycleRefused('New session confirmation requires a live original process')
        return {'nativeRealm':record.environment_identity,'sessionId':receipt.session_id,'evidenceRef':ref}

    def publication_facts(self, unit_ref):
        if not callable(self.publication_owner):
            raise UnitLifecycleRefused('Original Unit publication owner unavailable')
        return self.publication_owner(self.read_unit(unit_ref), self.read_session(unit_ref))

    def query_creation(self, correlation, verified_query_facts):
        raise UnitLifecycleRefused('Cold native reconciliation requires an explicit deployment owner')

    def verify_termination(self, unit, action, correlation, evidence):
        if evidence.get('action') != action or evidence.get('correlation') != correlation:
            raise UnitLifecycleRefused('Termination evidence belongs to another attempt')
        record = self._bindings.get(unit.unit_ref)
        if record is None:
            # Absence of a live handle after restart is never proof of exit.
            if self.records.owner_read_session(unit.unit_ref).state != 'notCreated' or self._factory_for_unit(unit).owned_record is not None:
                raise UnitLifecycleRefused('Cold/unknown original native ownership cannot prove absence')
            if evidence.get('ownedProcess') != 'none':
                raise UnitLifecycleRefused('Original no-process evidence unavailable')
        else:
            record = self._record(unit)
            observation = record.process.observe()
            code = observation.exit_code if observation.state == "exited" else None
            if (code is None or evidence.get('processIdentity') != record.process.identity
                    or evidence.get('exitCode') != str(int(code))):
                raise UnitLifecycleRefused('Owned native exit unavailable or evidence forged')
        payload = {'unit':unit.public_ref,'action':action,'correlation':correlation,'evidence':dict(evidence)}
        return {'terminationEvidenceRef':'sha256:'+hashlib.sha256(safe_json(payload).encode()).hexdigest()}


    def revalidate_configuration(self, unit, context):
        if not callable(self.configuration_authority):
            raise UnitLifecycleRefused('Original configuration authority unavailable')
        return self.configuration_authority(unit, context)

    def observe_configuration(self, unit, connection):
        record = self._record(unit)
        method = record.prepared_agent.harness.descriptor.get('configurationReadMethod')
        if not isinstance(method, str) or not method or record.process.observe().state != "running":
            raise UnitLifecycleRefused('Harness native configuration observation unavailable')
        result = connection.command(method, sessionId=record.entry.session_id, timeout=self._factory_for_unit(unit).timeout)
        if not isinstance(result, dict) or result.get('sessionId') != record.entry.session_id:
            raise UnitLifecycleRefused('Observed configuration belongs to another session')
        from ordessa_execution_agents.harness.configuration.compilation.native_digest import configuration_digest
        options = result.get('configOptions')
        digest = 'sha256:'+configuration_digest(options)
        return {'sessionId':result['sessionId'], 'configOptions':options, 'sourceRevision':digest}

    def capture_configuration(self, unit, facts, request, receipt, before, after):
        record = self._record(unit)
        params = request.get('params', {})
        if (record.process.observe().state != "running" or request.get('method') != 'session/set_config_option'
                or params.get('sessionId') != record.entry.session_id
                or receipt.get('id') != request.get('id') or 'error' in receipt
                or before['sourceRevision'] == after['sourceRevision'] and
                    not any(o.get('id') == params.get('configId') and o.get('currentValue') == params.get('value') for o in after['configOptions'])):
            raise UnitLifecycleRefused('Original configuration receipt/effect unavailable')
        selected = [o for o in after['configOptions'] if o.get('id') == params.get('configId')]
        if len(selected) != 1 or selected[0].get('currentValue') != params.get('value'):
            raise UnitLifecycleRefused('Configuration ACK differs from actual readback')
        native_digest = 'sha256:'+hashlib.sha256(safe_json(request).encode()).hexdigest()
        payload = {'unit':unit.public_ref, 'request':request, 'receipt':receipt,
                   'before':before, 'after':after, 'profileRevision':record.prepared_agent.profile_revision}
        ref = 'sha256:'+hashlib.sha256(safe_json(payload).encode()).hexdigest()
        proof = {'operationRef':facts['operationRef'], 'unitRef':unit.public_ref,
                 'scopeRef':unit.configuration_target_ref, 'requestDigest':facts['inputDigest'],
                 'nativeRequestId':request['id'], 'nativeRequestDigest':native_digest,'evidenceRef':ref}
        self._configuration_receipts[ref] = (unit.unit_ref, record, proof)
        return ref

    def verify_configuration(self, unit, identity, native_id, native_digest, evidence):
        if not isinstance(evidence, str):
            raise UnitLifecycleRefused("Configuration evidence must be an original owner ref")
        item = self._configuration_receipts.get(evidence)
        if (item is None or item[0] != unit.unit_ref or self._record(unit) is not item[1]
                or item[2]['nativeRequestId'] != native_id or item[2]['nativeRequestDigest'] != native_digest
                or any(item[2][k] != identity[k] for k in ('operationRef','unitRef','scopeRef','requestDigest'))):
            raise UnitLifecycleRefused('Original configuration evidence missing/forged; cold confirmation unavailable')
        return item[2]
