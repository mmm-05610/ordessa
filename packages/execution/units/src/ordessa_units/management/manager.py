"""Run-scoped live Unit handles; durable authority remains in original owners."""
from collections.abc import Mapping
from threading import RLock
import hashlib
import json
from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.lifecycle.unit_lifecycle import same_reference
from .instance import UnitInstance
from .planning import fixed_profile_plan


class UnitManagementRefused(RuntimeError):
    code = 'UNIT_MANAGEMENT_REFUSED'


_RELEASE_RECEIPT_SEAL = object()
_REFUSED_BEFORE_PREPARATION = object()


class ManagerReleaseReceipt:
    """Opaque run-scoped proof that the original Unit release was confirmed."""
    __slots__ = ()

    def __new__(cls, seal=None):
        if seal is not _RELEASE_RECEIPT_SEAL:
            raise TypeError('ManagerReleaseReceipt is issued by UnitManager')
        return super().__new__(cls)


class UnitManager:
    def __init__(self, *, create_instance, records, verifier):
        if not callable(create_instance) or records.verifier is not verifier:
            raise UnitManagementRefused('Explicit factory and original records/verifier required')
        self._factory, self.records, self.verifier = create_instance, records, verifier
        self._lock = RLock()
        self._draining = False
        self._attempts = {}  # Live ownership retention, never a durable outcome ledger.
        self._units = {}
        self._release_receipts = {}  # Opaque in-process receipts; no durable outcome authority.
        self._deferred_by_unit = {}

    def drain(self):
        with self._lock: self._draining = True

    def has_unsettled_creations(self):
        with self._lock:
            for unit in self._attempts.values():
                if unit is _REFUSED_BEFORE_PREPARATION:
                    continue
                if unit is None or unit._prepared_unit is None:
                    return True
                ref = unit._prepared_unit['unitRef']
                if ref['unitId'] in self._units:
                    return True
                receipt = self.records.owner_read_termination(ref['unitId'], 'release')
                if receipt is None or receipt.get('state') != 'confirmed':
                    return True
            return False

    @staticmethod
    def _creation_key(context):
        try:
            facts = context.facts
            if facts['action'] != 'prepare' or facts['query'] is not False:
                raise ValueError()
            return safe_json({name: facts[name] for name in ('request', 'operationRef', 'stepId')})
        except Exception:
            raise UnitManagementRefused('Original prepare invocation identity required') from None

    def plan_preparation(self, snapshot, context, correlation):
        """Build a fixed plan without consulting the factory or durable owners."""
        try:
            return fixed_profile_plan(snapshot, context, correlation)
        except Exception as exc:
            raise UnitManagementRefused('Fixed complete Profile preparation plan required') from exc

    def _remember(self, unit):
        receipt = unit.prepared_unit
        ref = receipt['unitRef']
        prior = self._units.get(ref['unitId'])
        if prior is not None and prior[0] is not unit:
            raise UnitManagementRefused('Original Unit already has a live owner')
        self._units[ref['unitId']] = (unit, ref)

    def create(self, plan, invocation_context, *, specification=None):
        if not isinstance(plan, Mapping):
            raise UnitManagementRefused('Fixed preparation plan required')
        key = self._creation_key(invocation_context)
        with self._lock:
            if self._draining:
                raise UnitManagementRefused('original Unit Manager is draining')
            if key in self._attempts:
                raise UnitManagementRefused('Original creation retained; never replay factory or prepare')
            self._attempts[key] = None
            unit = self._factory(plan)
            if (type(unit) is not UnitInstance or unit.records is not self.records
                    or unit._verifier is not self.verifier
                    or unit._prepared_unit is not None or unit.channel_factory.environment is not None):
                raise UnitManagementRefused('Factory must return a fresh fixed Unit on original owners')
            self._attempts[key] = unit
            if specification is not None:
                from ordessa_units.definitions import UnitSpec
                if (type(specification) is not UnitSpec
                        or unit.definition.agent_id != specification.agent_id
                        or unit.definition.profile_revision != specification.profile_revision
                        or not same_reference(unit.definition.environment_reference,
                                              specification.environment_reference)):
                    # Nothing was prepared/acquired; the request is spent, but
                    # this unstarted handle holds no resource requiring close.
                    self._attempts[key] = _REFUSED_BEFORE_PREPARATION
                    raise UnitManagementRefused('Fixed Unit factory differs from UnitSpec')
            try:
                unit.prepare(plan, invocation_context)
            except BaseException:
                # A partial prepare can already own records/files/a Use. Keep
                # the original handle; never turn an error into a retry path.
                if unit._prepared_unit is not None:
                    try:
                        self._remember(unit)
                    except Exception:
                        # The original failure remains authoritative. The
                        # attempt still retains the handle even if its owner
                        # cannot currently verify a public reference.
                        pass
                raise
            self._remember(unit)
            return unit

    def find(self, unit_ref):
        with self._lock:
            if not isinstance(unit_ref, Mapping):
                raise UnitManagementRefused('Complete original Unit reference required')
            entry = self._units.get(unit_ref.get('unitId'))
            if entry is None or not same_reference(unit_ref, entry[1]):
                raise UnitManagementRefused('Unit is not owned by this manager scope')
            if (entry[0].records is not self.records or entry[0]._verifier is not self.verifier
                    or self.records.verifier is not self.verifier):
                raise UnitManagementRefused('Original Manager records/verifier binding changed')
            entry[0]._unit_record(unit_ref)
            return entry[0]

    def list(self):
        with self._lock:
            return tuple(self.find(ref) for _, ref in self._units.values())

    def references(self):
        """Exact current live references, without exposing handles as facts."""
        with self._lock:
            for _, ref in self._units.values():
                self.find(ref)
            return tuple(sealed_mapping(ref) for _, ref in self._units.values())

    def start(self, prepared_unit, invocation_context):
        """Start only the exact prepared Unit retained by this manager."""
        if not isinstance(prepared_unit, Mapping) or not isinstance(prepared_unit.get('unitRef'), Mapping):
            raise UnitManagementRefused('Complete original prepared Unit reference required')
        with self._lock:
            unit = self.find(prepared_unit['unitRef'])
            return unit.start(unit.prepared_unit, invocation_context)

    def release(self, unit_ref, invocation_context):
        with self._lock:
            unit = self.find(unit_ref)
            if unit_ref['unitId'] in self._deferred_by_unit:
                raise UnitManagementRefused('Original Node release COMMIT must finalize its retained handle')
            result = unit.release(unit_ref, invocation_context)
            if result.get('state') == 'confirmed':
                del self._units[unit_ref['unitId']]
            return result

    @staticmethod
    def _facts_key(facts):
        names = ('request', 'operationRef', 'stepId', 'action', 'inputDigest',
                 'targetRef', 'providerRef', 'managementEpoch')
        return safe_json({name: facts[name] for name in names})

    def release_deferred(self, unit_ref, invocation_context):
        """Run the original release but retain its live manager handle until Node COMMIT."""
        with self._lock:
            unit = self.find(unit_ref)
            facts = invocation_context.facts
            owner_facts = self.records.owner_read_unit(unit_ref['unitId']).facts
            if (facts.get('action') != 'release' or facts.get('query') is not False
                    or not same_reference(facts.get('providerRef'), owner_facts.get('providerRef'))
                    or not same_reference(facts.get('targetRef'), owner_facts.get('nodeRef'))):
                raise UnitManagementRefused('Original Unit release invocation scope required')
            key = self._facts_key(facts)
            unit_id = unit_ref['unitId']
            prior = self._deferred_by_unit.get(unit_id)
            if unit_id in self._deferred_by_unit:
                if prior is None:
                    raise UnitManagementRefused('Original deferred release is pending; never replay its effect')
                entry = self._release_receipts.get(id(prior))
                if entry is None or entry['receipt'] is not prior:
                    raise UnitManagementRefused('Deferred release receipt is unavailable')
                if entry['factsKey'] != key or entry['unit'] is not unit or not same_reference(entry['unitRef'], unit_ref):
                    raise UnitManagementRefused('Original release already concluded for another request')
                return json.loads(entry['result']), prior
            # Fence the original Node attempt before native I/O leaves this lock.
            # Failure retains ownership; direct release cannot retire it before COMMIT.
            self._deferred_by_unit[unit_id] = None
        result = unit.release(unit_ref, invocation_context)
        if not isinstance(result, Mapping) or result.get('state') != 'confirmed':
            return result, None
        original = self.records.owner_read_termination(unit_ref['unitId'], 'release')
        expected_correlation = safe_json({
            'request': facts['request'], 'operationRef': facts['operationRef'],
            'stepId': facts['stepId']})
        identity = original.get('identity', {}) if isinstance(original, Mapping) else {}
        if (facts.get('action') != 'release' or facts.get('query') is not False
                or original is None or original.get('state') != 'confirmed'
                or identity.get('action') != 'release'
                or identity.get('correlation') != expected_correlation
                or identity.get('inputDigest') != facts.get('inputDigest')
                or not same_reference(identity.get('unitRef'), unit_ref)
                or not same_reference(result.get('outcome'), original.get('outcome'))):
            raise UnitManagementRefused('Confirmed original UnitRecords release proof unavailable')
        with self._lock:
            receipt = ManagerReleaseReceipt(_RELEASE_RECEIPT_SEAL)
            self._release_receipts[id(receipt)] = {
                'receipt': receipt, 'unit': unit, 'unitRef': dict(unit_ref),
                'termination': safe_json(original), 'result': safe_json(dict(result)),
                'factsKey': key, 'invocationContext': invocation_context,
            }
            self._deferred_by_unit[unit_ref['unitId']] = receipt
            return dict(result), receipt

    def release_reconciliation(self, unit_ref, *, request):
        """Revalidate the original possibly-dispatched release without replaying it.

        This is deliberately live-only: the original Unit handle, receipt,
        InvocationContext, Grant and Environment claim must all still exist.
        It cannot recover an unknown claim or manufacture a new release proof.
        """
        with self._lock:
            unit = self.find(unit_ref)
            if not isinstance(request, RequestKey):
                raise UnitManagementRefused('Original Node release RequestKey required')
            receipt = self._deferred_by_unit.get(unit_ref['unitId'])
            entry = self._release_receipts.get(id(receipt)) if receipt is not None else None
            if (entry is None or entry.get('receipt') is not receipt
                    or entry.get('unit') is not unit
                    or not same_reference(entry.get('unitRef'), unit_ref)):
                raise UnitManagementRefused('Live deferred release receipt unavailable')
            facts = json.loads(entry['factsKey'])
            request_ref = {'environmentNamespace': request.environment_namespace,
                           'principalScope': request.principal_scope,
                           'requestId': request.request_id}
            if (facts.get('action') != 'release'
                    or not same_reference(facts.get('request'), request_ref)):
                raise UnitManagementRefused('Reconciliation request differs from original release')
            context = entry.get('invocationContext')
            if context is None:
                raise UnitManagementRefused('Original live release invocation is unavailable')
            try:
                context_facts = context.facts
                if (self._facts_key(context_facts) != entry['factsKey']
                        or context_facts.get('query') is not False):
                    raise UnitManagementRefused('Original live release context changed')
                original = self.records.owner_read_termination(unit_ref['unitId'], 'release')
                termination = json.loads(entry['termination'])
                if original is None or not same_reference(original, termination):
                    raise UnitManagementRefused('Confirmed UnitRecords release proof changed')
                verifier = self.verifier
                verify = getattr(verifier, '_verify', None)
                issuer = getattr(verify, '__self__', None)
                continuation = getattr(issuer, 'verify_continuation', None)
                if not callable(continuation):
                    raise UnitManagementRefused('Original invocation issuer unavailable')
                # The original issuer checks the consumed Grant and the exact
                # possibly-dispatched claim/revision; no new claim is issued.
                continuation(context, 'release', facts['providerRef'],
                             facts['targetRef'], facts['inputDigest'])
            except UnitManagementRefused:
                raise
            except Exception as exc:
                raise UnitManagementRefused(
                    'Original release is not safely reconcilable from its live claim') from exc
            return context, json.loads(entry['result']), receipt

    def _release_commit(self, request, entry):
        verifier = self.verifier
        if (self.records.verifier is not verifier or entry['unit'].records is not self.records
                or entry['unit']._verifier is not verifier):
            raise UnitManagementRefused('Original Manager records/verifier binding changed')
        verify = getattr(verifier, '_verify', None)
        issuer = getattr(verify, '__self__', None)
        store = getattr(issuer, '_store', None)
        if store is None:
            raise UnitManagementRefused('Original Environment operation store unavailable')
        operation = store.read_operation(request)
        unit_ref = entry['unitRef']
        unit_facts = self.records.owner_read_unit(unit_ref["unitId"]).facts
        facts = json.loads(entry['factsKey'])
        if (operation is None or operation.intent.kind != 'agent-release'
                or operation.request.environment_namespace != request.environment_namespace
                or operation.request.principal_scope != request.principal_scope
                or operation.request.request_id != request.request_id
                or operation.intent.operation_ref != facts.get('operationRef')
                or not same_reference(operation.intent.profile_snapshot_ref, unit_ref)):
            raise UnitManagementRefused('Original Node release operation unavailable')
        intent = operation.intent
        fixed = intent.context_ref.get('lifecycleRequest')
        if (not isinstance(fixed, Mapping) or fixed.get('action') != 'release'
                or not same_reference(fixed.get('unitRef'), unit_ref)
                or not same_reference(fixed.get('pinnedProviderRef'), unit_facts.get('providerRef'))
                or not same_reference(fixed.get('nodeRef'), intent.node_ref)):
            raise UnitManagementRefused('Release operation is not bound to the original Node and Unit')
        if len(intent.steps) != 1:
            raise UnitManagementRefused('Release operation step recipe differs')
        step_intent = intent.steps[0]
        step = store.read_operation_step(request, step_intent.step_id)
        termination = json.loads(entry['termination'])
        if (step_intent.step_id != 'release' or step is None or step.outcome != 'concluded'
                or operation.status in {'unknown', 'refused', 'cancelled'}
                or facts.get('stepId') != step_intent.step_id
                or facts.get('action') != 'release'
                or facts.get('inputDigest') != step_intent.input_digest
                or not same_reference(facts.get('targetRef'), intent.node_ref)
                or not same_reference(facts.get('providerRef'), unit_facts.get('providerRef'))
                or facts.get('managementEpoch') != step_intent.management_epoch
                or not same_reference(step.intent.to_dict(), step_intent.to_dict())
                or not same_reference(step_intent.pinned_provider_ref, unit_facts.get('providerRef'))
                or step_intent.input_digest != termination['identity'].get('inputDigest')
                or step_intent.recovery_correlation != intent.operation_ref + '.release'
                or not same_reference(step.evidence.get('termination'), termination)):
            raise UnitManagementRefused('Original Node release step has not committed its exact Unit proof')
        current_termination = self.records.owner_read_termination(unit_ref['unitId'], 'release')
        if current_termination is None or not same_reference(current_termination, termination):
            raise UnitManagementRefused('Original UnitRecords release proof changed')

        from ordessa_units.bindings.publication import NODES, decode_node_ref, node_holder
        node_ref = decode_node_ref(intent.node_ref)
        node_row = store.read_domain(node_ref.environment, NODES,
                                     f'{node_ref.instance_id}:{node_ref.generation}')
        if node_row is None or node_row.get('revision') != 1:
            raise UnitManagementRefused('Original published Node record unavailable')
        stored = node_row['value']
        node = stored.get('record') if isinstance(stored, Mapping) else None
        if (not isinstance(node, Mapping)
                or not same_reference(node.get('nodeRef'), intent.node_ref)
                or not same_reference(node.get('binding', {}).get('harnessUnitRef'), unit_ref)
                or not same_reference(node.get('binding', {}).get('harnessProviderRef'), unit_facts.get('providerRef'))):
            raise UnitManagementRefused('Published Node is not bound to this original Unit')
        try:
            source = stored['operationRequest']
            source_request = RequestKey(source['environmentNamespace'], source['principalScope'], source['requestId'])
            source_operation = store.read_operation(source_request)
            digest = 'sha256:' + hashlib.sha256(safe_json(node).encode('utf-8')).hexdigest()
        except Exception as exc:
            raise UnitManagementRefused('Original Node publication source is unavailable') from exc
        if (stored.get('recordDigest') != digest or source_operation is None
                or source_operation.status != 'published'
                or not same_reference(source_operation.result, node)
                or node.get('publicationRevision') != source_operation.revision):
            raise UnitManagementRefused('Original Node publication COMMIT is not verifiable')
        refs = node.get('resourceUsageRefs')
        if not isinstance(refs, list) or not refs:
            raise UnitManagementRefused('Original Node Usage inventory unavailable')
        if any(not isinstance(item, Mapping)
               or set(item) != {'environmentNamespace', 'usageId'}
               or item.get('environmentNamespace') != node_ref.environment
               or not isinstance(item.get('usageId'), str) or not item.get('usageId')
               for item in refs):
            raise UnitManagementRefused('Original Node Usage inventory is malformed')
        usage_ids = {item['usageId'] for item in refs}
        if len(usage_ids) != len(refs):
            raise UnitManagementRefused('Original Node Usage inventory has duplicate references')
        holder = node_holder(node_ref.environment, node_ref.instance_id, node_ref.generation)
        usages = store.read_usages(node_ref.environment, holder)
        if ({row['usageId'] for row in usages} != usage_ids
                or any(row.get('state') != 'released'
                       or not same_reference(row.get('holderRef'), holder)
                       or not row.get('rights') or not isinstance(row.get('targetRef'), Mapping)
                       or row['targetRef'].get('environmentNamespace') != node_ref.environment
                       for row in usages)):
            raise UnitManagementRefused('Original Node Usage COMMIT is incomplete')
        snapshot = intent.context_ref.get('nodeUsageFenceSnapshot')
        if not isinstance(snapshot, (tuple, list)) or len(snapshot) != len(usages):
            raise UnitManagementRefused('Original release Usage fence snapshot unavailable')
        original_rows = {row['usageId']: row for row in snapshot}
        if set(original_rows) != usage_ids or any(
                row.get('revision') != original_rows[row['usageId']]['revision'] + 1
                or original_rows[row['usageId']].get('state') != 'active'
                or safe_json({'rights': row.get('rights')}) != safe_json(
                    {'rights': original_rows[row['usageId']]['rights']})
                or not same_reference(row.get('targetRef'), original_rows[row['usageId']]['targetRef'])
                for row in usages):
            raise UnitManagementRefused('Original Node release Usage provenance differs')
        return store, request, step

    def finalize_committed_release(self, unit_ref, *, request):
        """Retire the retained original receipt after a previously committed Node step.

        This is a read-back/finalization path, never a native release or claim.
        Exact publication, termination and Usage COMMIT checks remain in
        finalize_release; a cold Manager has no receipt to finalize.
        """
        with self._lock:
            if not isinstance(unit_ref, Mapping):
                raise UnitManagementRefused('Complete original Unit reference required')
            receipt = self._deferred_by_unit.get(unit_ref.get('unitId'))
            entry = self._release_receipts.get(id(receipt)) if receipt is not None else None
            if (entry is None or entry.get('receipt') is not receipt
                    or not same_reference(entry.get('unitRef'), unit_ref)):
                raise UnitManagementRefused('Live deferred release receipt unavailable')
            return self.finalize_release(receipt, request=request)

    def finalize_release(self, receipt, *, request):
        """Retire a retained Unit only after the original Node release COMMIT is read back."""
        with self._lock:
            entry = self._release_receipts.get(id(receipt)) if receipt is not None else None
            if entry is None or entry.get('receipt') is not receipt:
                raise UnitManagementRefused('Original manager release receipt required')
            if not isinstance(request, RequestKey):
                raise UnitManagementRefused('Original Node release RequestKey required')
            facts = json.loads(entry['factsKey'])
            request_ref = {'environmentNamespace': request.environment_namespace,
                           'principalScope': request.principal_scope, 'requestId': request.request_id}
            if not same_reference(facts.get('request'), request_ref):
                raise UnitManagementRefused('Finalize request differs from original deferred release')
            self._release_commit(request, entry)
            unit_ref = entry['unitRef']
            current = self._units.get(unit_ref['unitId'])
            if current is not None:
                if current[0] is not entry['unit'] or not same_reference(current[1], unit_ref):
                    raise UnitManagementRefused('Manager Unit ownership changed before finalization')
                del self._units[unit_ref['unitId']]
            return json.loads(entry['result'])
