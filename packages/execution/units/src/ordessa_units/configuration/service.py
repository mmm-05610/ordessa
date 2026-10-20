"""Configuration coordination on the existing Environment operation ledger.

The admitted Unit owner interprets and confirms native configuration. Core
stores fixed intent and immutable observations, never a mutable actual cache.
"""
from __future__ import annotations
from ordessa_execution_agents.profiles.definitions.codec import decode_revision_ref, encode_content, encode_revision_ref

import hashlib
import json
from collections.abc import Mapping

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch, UnitOperationUnknown
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_infrastructure.database.records import (
    DomainStorePort,
    DomainWrite,
)
from ordessa_units.definitions.operations import (
    OperationIntent,
    OperationStorePort,
    PreDispatchRefusalStorePort,
    StepIntent,
)
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.configuration.contracts import (
 ApplicationPolicy, ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationContractError,
 ConfigurationSnapshot, ConfigurationUnsupported, ConfigurationRevisionConflict, UnitInspection,
 ConfigurationConversionRefused, ConfigurationItemResult, ConfigurationOmissionRefused,
 derive_change,
)
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationIssuer
from ordessa_units.bindings.publication import encode_node_ref
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_execution_agents.harness.providers.registry.definition_admission import HarnessAdmission
from ordessa_execution_agents.profiles.definitions.models import ProfileRevisionRef

CONFIGURATION_ATTEMPTS = 'agents.configuration-attempts'


class _KnownPreDispatchRefusal(Exception):
    def __init__(self, phase, reason):
        self.phase, self.reason = phase, reason


def _plain(value): return json.loads(safe_json(value))
def _hash(value): return 'sha256:' + hashlib.sha256(safe_json(value).encode()).hexdigest()
def _same(left,right): return safe_json({'value':left}) == safe_json({'value':right})


def _contains_secret_ref(value):
    if isinstance(value, Mapping):
        return 'secretRef' in value or any(_contains_secret_ref(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_ref(item) for item in value)
    return False


class AgentConfiguration:
    def __init__(self, environment, nodes, *, invocation_issuer=None):
        self._environment, self._nodes = environment, nodes
        self._issuer = invocation_issuer

    def capabilities(self):
        # An issuer alone does not supply the retired runtime provider's
        # configuration interpreter. Negotiated ACP options remain available
        # through the exact live Unit API, not this manifest service.
        return {'configurationManagement': False}

    def _admit(self, node_ref, access):
        env = self._environment
        env._check_open()
        if not isinstance(node_ref, AgentNodeRef):
            raise UnitIdentityMismatch('complete Node identity required')
        env._check_environment(node_ref.environment)
        if env._policy is None or not env._policy.admit_object_access(
                env._principal_scope, f'{env.environment_id}:agents.node:{node_ref.instance_id}', access):
            raise UnitAdmissionRefused('Node configuration access refused')
        node = self._nodes.read(node_ref)
        if node is None:
            raise UnitGuaranteeUnavailable('published Node unavailable')
        return node

    def _owner(self, node, *methods):
        admitted = HarnessAdmission(self._environment).describe(node['binding']['harnessDefinitionRef'])
        if not _same(admitted.provider_ref,node['binding']['harnessProviderRef']):
            raise UnitAdmissionRefused('Node owner activation differs')
        raise UnitGuaranteeUnavailable('specific Unit manifest configuration owner is not bound')

    @staticmethod
    def _call(callback, *args):
        try:
            return callback(*args)
        except Exception:
            raise UnitGuaranteeUnavailable('owner configuration evidence unavailable') from None

    def _inspection(self, node, admitted):
        unit = self._call(admitted.provider.inspect_unit, node['binding']['harnessUnitRef'])
        if (not isinstance(unit, UnitInspection) or not _same(unit.unit_ref,node['binding']['harnessUnitRef'])
                or not _same(unit.provider_ref,admitted.provider_ref)
                or not _same(unit.configuration_target_ref,node['binding']['configurationTargetRef'])):
            raise UnitGuaranteeUnavailable('current Unit owner evidence differs from Node binding')
        return unit

    def describe(self, node_ref):
        node = self._admit(node_ref, 'read')
        admitted = self._owner(node, 'describe_configuration')
        from ordessa_units.configuration.contracts import ConfigurationDescription
        result = self._call(admitted.provider.describe_configuration, node['binding']['harnessUnitRef'])
        if (not isinstance(result, tuple) or any(not isinstance(item, ConfigurationDescription) for item in result)
                or len({(item.configuration_kind,item.schema_version) for item in result}) != len(result)):
            raise UnitGuaranteeUnavailable('owner description is incomplete or ambiguous')
        return result

    def inspect(self, node_ref):
        node = self._admit(node_ref, 'read')
        admitted = self._owner(node, 'inspect_unit', 'inspect_configuration')
        unit = self._inspection(node, admitted)
        result = self._call(admitted.provider.inspect_configuration, unit.unit_ref)
        if not isinstance(result, ConfigurationSnapshot) or not _same(result.unit_ref,unit.unit_ref) or not _same(result.scope_ref,unit.configuration_target_ref):
            raise UnitGuaranteeUnavailable('owner snapshot target differs')
        return result

    def _request(self, request, node_ref):
        env = self._environment
        if not isinstance(request, RequestKey) or request.principal_scope != env._principal_scope:
            raise UnitAdmissionRefused('authenticated request realm differs')
        env._check_environment(request.environment_namespace)
        node = self._admit(node_ref, 'write')
        if env._policy is None or not env._policy.admit_invoke(env._principal_scope, 'pacthold.agents.configuration.apply', 'reliable'):
            raise UnitAdmissionRefused('configuration invocation refused')
        if not isinstance(env._store, OperationStorePort) or not isinstance(env._store, DomainStorePort) or env._fingerprint_port is None:
            raise UnitGuaranteeUnavailable('configuration requires the existing durable operation store and fingerprint port')
        if not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not env._store:
            raise UnitGuaranteeUnavailable('explicit invocation issuer on the same Environment store required')
        return node

    def reserve(self, request, node_ref, change, *, profile_ref=None, base_profile_ref=None,
                snapshot_write=None, mode=None):
        """Reserve one configuration change on the existing operation ledger.

        Manifest-sourced requests carry the frozen ``profile_ref`` (the new
        desired snapshot), the caller's ``base_profile_ref`` and optionally the
        ``snapshot_write`` that must commit in this same transaction. The
        scope fence records the current expected profile source so a later
        update can bind its base (interfaces.md 3.2); ``mode='no-change-verification'``
        reserves a data-only receipt that never dispatches and never advances
        the expected source.
        """
        if not isinstance(change, ConfigurationChangeRequest) or not isinstance(request, RequestKey) or request.request_id != change.request_id:
            raise UnitIdentityMismatch('configuration request identity differs')
        if profile_ref is not None and type(profile_ref) is not ProfileRevisionRef:
            raise UnitIdentityMismatch('fixed new Profile reference required')
        if base_profile_ref is not None and type(base_profile_ref) is not ProfileRevisionRef:
            raise UnitIdentityMismatch('fixed base Profile reference required')
        env = self._environment
        with env._admission_lock:
            node = self._request(request, node_ref)
            fixed = {'nodeRef':encode_node_ref(node_ref), 'change':change.to_dict()}
            if profile_ref is not None:
                fixed['profileRef'] = encode_revision_ref(profile_ref)
            if base_profile_ref is not None:
                fixed['baseProfileRef'] = encode_revision_ref(base_profile_ref)
            if mode is not None:
                fixed['mode'] = mode
            digest = env._fingerprint_port.fingerprint(request, 'pacthold.agents.configuration.apply', _hash(fixed))
            unknown_operation = None
            try:
                prior = env._store.read_operation(request)
            except UnitOperationUnknown as error:
                # Domain-only receipts spend the request key without an
                # Operation. Resolve them only by the exact digest below.
                unknown_operation = error
                prior = None
            if prior is not None:
                if prior.digest != digest or prior.intent.kind != 'configuration-change':
                    raise UnitIdentityMismatch('spent configuration request differs')
                return prior
            # Domain-only refusals (including omission receipts) also spend
            # this Environment request key. Detect them before any Unit-owner
            # inspection so a corrected body under the old id cannot reach a
            # provider callback before the store reports the key conflict.
            prior_domain_result = env._store.read_domain_result(request, digest)
            if prior_domain_result is None and unknown_operation is not None:
                raise unknown_operation
            if prior_domain_result is not None:
                raise UnitIdentityMismatch('spent configuration request has a domain-only result')
            required = ('inspect_unit', 'inspect_configuration') if mode is not None else (
                'inspect_unit', 'inspect_configuration', 'describe_configuration', 'apply_configuration')
            admitted = self._owner(node, *required)
            unit = self._inspection(node, admitted)
            snapshot = self.inspect(node_ref)
            if snapshot.source_revision is None or snapshot.comparison_guarantee == 'unavailable':
                raise ConfigurationUnsupported('owner revision comparison unavailable')
            if snapshot.source_revision != change.expected_configuration_revision:
                raise ConfigurationRevisionConflict('expected owner configuration revision differs')
            descriptions = {(item.configuration_kind,item.schema_version):item for item in self.describe(node_ref)} if mode is None else {}
            skipped = []
            for declaration in change.declarations:
                item = descriptions.get((declaration['configurationKind'],declaration['schemaVersion']))
                supported = item is not None and item.support_status == 'supported' and declaration['action'] in item.supported_actions
                if mode is None and not supported and declaration['requirement'] == 'required':
                    raise ConfigurationUnsupported('required declaration unsupported before dispatch')
                for ref in declaration.get('resourceRefs', ()):
                    if ref.get('environmentNamespace') != env.environment_id:
                        raise UnitIdentityMismatch('configuration material environment differs')
                # C1 material acquisition and authorized SecretRef resolution
                # are not composed here. Keep opaque references in request
                # identity, but never pass them to an owner as acquired material.
                unresolved = (bool(declaration.get('resourceRefs'))
                              or _contains_secret_ref(declaration))
                if mode is None and unresolved and declaration['requirement'] == 'required':
                    raise ConfigurationUnsupported('required material acquisition unavailable before dispatch')
                if mode is None and (not supported or unresolved):
                    skipped.append(declaration['declarationId'])
            scope_id = 'scope-' + hashlib.sha256(safe_json(unit.configuration_target_ref).encode()).hexdigest()[:48]
            fence = env._store.read_domain(env.environment_id, CONFIGURATION_ATTEMPTS, scope_id)
            expected_profile, expected_operation = self._expected_source(node, fence)
            prior_expected_profile = expected_profile
            prior_expected_operation = expected_operation
            if base_profile_ref is not None and not _same(encode_revision_ref(base_profile_ref), expected_profile):
                raise ConfigurationRevisionConflict('base Profile snapshot differs from the scope expected source')
            operation_ref = 'configuration-' + hashlib.sha256(safe_json({'environmentNamespace':env.environment_id,
                'principalScope':request.principal_scope,'requestId':request.request_id}).encode()).hexdigest()[:48]
            if mode is None and profile_ref is not None:
                expected_profile, expected_operation = encode_revision_ref(profile_ref), operation_ref
            context = {'environmentNamespace':env.environment_id, **fixed,
                'skippedOptional':skipped,
                'effectiveDeclarations':[_plain(item) for item in change.declarations if item['declarationId'] not in skipped],
                'unitRef':_plain(unit.unit_ref), 'configurationTargetRef':_plain(unit.configuration_target_ref),
                'directoryBindingRef':unit.directory_binding_ref.to_dict(), 'unitSourceRevision':unit.source_revision,
                'beforeConfigurationEvidence':_plain(snapshot.confirmation_evidence),
                'comparisonGuarantee':snapshot.comparison_guarantee,
                'preDispatchRollback':{
                    'namespace':CONFIGURATION_ATTEMPTS,'recordId':scope_id,
                    'preReservationFenceRevision':fence['revision'] if fence else 0,
                    'priorExpectedProfileRef':prior_expected_profile,
                    'priorExpectedProfileOperationRef':prior_expected_operation,
                    'reservedExpectedProfileRef':expected_profile,
                    'reservedExpectedProfileOperationRef':expected_operation,
                },
                'invocationBindings':{'configuration-apply':{'action':'applyConfiguration',
                    'targetRef':_plain(unit.configuration_target_ref),'delegationRef':None,'cleanup':False}}}
            step = StepIntent('configuration-apply', admitted.provider_ref, digest, operation_ref+'.apply',
                              management_epoch=unit.management_epoch)
            intent = OperationIntent(operation_ref, 'configuration-change', node['lineage']['profileSnapshotRef'],
                                     context, (step,), encode_node_ref(node_ref), unit.management_epoch)
            fence_value = {'scopeRef':_plain(unit.configuration_target_ref),
                'principalScope':request.principal_scope,'requestId':request.request_id,
                'operationRef':operation_ref,
                'expectedProfileRef':expected_profile,
                'expectedProfileOperationRef':expected_operation}
            writes = [DomainWrite(CONFIGURATION_ATTEMPTS, scope_id,
                                  fence['revision'] if fence else 0, fence_value)]
            if snapshot_write is not None:
                writes.append(snapshot_write)
            return env._store.reserve_operation(request, digest, intent, writes=tuple(writes))

    def _expected_source(self, node, fence):
        """Current expected profile source for this scope, never guessed.

        Without a scope fence the expected source is the frozen preparation
        snapshot. A fence must pass the original source identity checks and
        carry an explicit expected profile reference; older shapeless records
        are refused instead of reinterpreted.
        """
        env = self._environment
        if fence is None:
            return node['lineage']['profileSnapshotRef'], None
        source = fence['value']
        old_key = RequestKey(env.environment_id, source['principalScope'], source['requestId'])
        old = env._store.read_operation(old_key)
        target = node['binding']['configurationTargetRef']
        if (not _same(source.get('scopeRef'), target) or old is None
                or old.intent.kind != 'configuration-change'
                or old.intent.operation_ref != source.get('operationRef')
                or not _same(old.intent.context_ref.get('configurationTargetRef'), target)):
            raise UnitGuaranteeUnavailable('configuration scope source identity damaged')
        if old.status not in {'published', 'refused', 'cancelled'}:
            raise UnitOperationUnknown('scope has an unresolved configuration operation')
        expected = source.get('expectedProfileRef')
        expected_operation = source.get('expectedProfileOperationRef')
        try:
            if expected is None:
                raise ValueError()
            decode_revision_ref(json.loads(safe_json(expected)))
        except (ValueError, TypeError, KeyError):
            raise UnitGuaranteeUnavailable('configuration scope expected source unavailable') from None
        if expected_operation is not None and (not isinstance(expected_operation, str) or not expected_operation):
            raise UnitGuaranteeUnavailable('configuration scope source identity damaged')
        return expected, expected_operation

    def apply_profile(self, request, node_ref, profile_ref, expected_configuration_revision,
                      application_policy, *, base_profile_ref, profile_manifest=None):
        """Update a running unit from one complete manifest (interfaces.md 3.2).

        Exactly one configuration source: an exact ProfileRef or a complete
        manifest body frozen into an immutable snapshot in the same
        transaction as the reservation. The caller binds the base expected
        snapshot and the owner-observed revision. Omitted base declarations
        are never guessed as resets and in-place kind/schema changes are
        refused before dispatch. An unchanged manifest dispatches nothing:
        it reports the standing operation's owner-recorded result when that
        result covers the manifest, otherwise an explicit unverified receipt —
        never a fabricated all-applied outcome. Applying a Profile never
        writes the catalog back and a Profile update never applies itself.
        """
        from ordessa_execution_agents.profiles.management.service import ProfileService
        if (profile_ref is None) == (profile_manifest is None):
            raise ConfigurationContractError('exactly one configuration source required')
        if type(base_profile_ref) is not ProfileRevisionRef:
            raise UnitIdentityMismatch('fixed base Profile reference required')
        if profile_ref is not None and type(profile_ref) is not ProfileRevisionRef:
            raise UnitIdentityMismatch('fixed Profile reference required')
        catalog = ProfileService(UnitProfileAdmission(self._environment))
        base_manifest = catalog.get_revision(base_profile_ref)
        snapshot_write = None
        if profile_ref is None:
            profile_ref, snapshot_write = catalog.stage_snapshot(profile_manifest)
            new_content = profile_manifest
        else:
            new_content = encode_content(catalog.get_revision(profile_ref).content)
        diff = derive_change(encode_content(base_manifest.content), new_content)
        if diff.omitted:
            self._refuse_omissions(request, node_ref, profile_ref, base_profile_ref,
                                   expected_configuration_revision, application_policy, diff.omitted)
        if diff.kind_conflicts:
            raise ConfigurationConversionRefused(diff.kind_conflicts)
        declarations = tuple(json.loads(safe_json(item))
                             for item in new_content.get('declarations', ()))
        if not diff.effective:
            change = ConfigurationChangeRequest(request.request_id, expected_configuration_revision,
                                                declarations, application_policy)
            return self._no_change(request, node_ref, change, profile_ref, base_profile_ref,
                                   snapshot_write)
        change = ConfigurationChangeRequest(request.request_id, expected_configuration_revision,
                                            diff.effective, application_policy)
        return self.apply(request, node_ref, change, profile_ref=profile_ref,
                          base_profile_ref=base_profile_ref, snapshot_write=snapshot_write)

    def _refuse_omissions(self, request, node_ref, profile_ref, base_profile_ref,
                          expected_configuration_revision, application_policy, omitted):
        """Spend an omission refusal through the existing Environment domain receipt.

        Only normalized identities, policy, revision and omitted declaration
        ids enter the request fingerprint/receipt. An inline snapshot is not
        persisted because no configuration operation is reserved.
        """
        if (not isinstance(expected_configuration_revision, str)
                or not expected_configuration_revision
                or type(application_policy) is not ApplicationPolicy):
            raise ConfigurationContractError('fixed configuration revision and policy required')
        env = self._environment
        with env._admission_lock:
            self._request(request, node_ref)
            fixed = {
                'nodeRef': encode_node_ref(node_ref),
                'profileRef': encode_revision_ref(profile_ref),
                'baseProfileRef': encode_revision_ref(base_profile_ref),
                'expectedConfigurationRevision': expected_configuration_revision,
                'applicationPolicy': application_policy.to_dict(),
            }
            digest = env._fingerprint_port.fingerprint(
                request, 'pacthold.agents.configuration.apply-profile-refusal', _hash(fixed))

            unknown_operation = None
            try:
                prior = env._store.read_operation(request)
            except UnitOperationUnknown as error:
                # The exact-digest domain read below distinguishes a complete
                # historical receipt from an incomplete/unknown spent key.
                unknown_operation = error
                prior = None
            if prior is not None:
                raise UnitIdentityMismatch('spent configuration request differs')

            receipt = env._store.read_domain_result(request, digest)
            expected_omitted = tuple(omitted)
            if receipt is None and unknown_operation is not None:
                raise unknown_operation
            if receipt is not None:
                if (not isinstance(receipt, dict)
                        or receipt.get('status') != 'refused'
                        or receipt.get('code') != ConfigurationOmissionRefused.code
                        or not isinstance(receipt.get('omitted'), list)
                        or tuple(receipt['omitted']) != expected_omitted):
                    raise UnitOperationUnknown('stored configuration refusal cannot be verified; do not resend')
                raise ConfigurationOmissionRefused(expected_omitted)

            result = {'status': 'refused', 'code': ConfigurationOmissionRefused.code,
                      'omitted': list(expected_omitted)}
            committed = env._store.commit_domain_change(request, digest, (), result)
            if (not isinstance(committed, dict)
                    or committed.get('status') != 'refused'
                    or committed.get('code') != ConfigurationOmissionRefused.code
                    or not isinstance(committed.get('omitted'), list)
                    or tuple(committed['omitted']) != expected_omitted):
                raise UnitOperationUnknown('configuration refusal receipt could not be verified; do not resend')
            raise ConfigurationOmissionRefused(expected_omitted)

    def _no_change(self, request, node_ref, change, profile_ref, base_profile_ref, snapshot_write=None):
        """Unchanged manifest: dispatch nothing and report standing facts only.

        When the scope's standing configuration operation was itself derived
        from exactly this manifest, its recorded owner-verified result is the
        authoritative no-change answer (interfaces.md PJ05). Otherwise the
        request is spent on an explicit unverified receipt whose items are
        reported unknown: no owner confirmation exists for this request, so
        nothing may be reported applied (PJ08).
        """
        env = self._environment
        with env._admission_lock:
            node = self._request(request, node_ref)
            fixed = {'nodeRef': encode_node_ref(node_ref), 'change': change.to_dict(),
                     'profileRef': encode_revision_ref(profile_ref), 'baseProfileRef': encode_revision_ref(base_profile_ref),
                     'mode': 'no-change-verification'}
            digest = env._fingerprint_port.fingerprint(request, 'pacthold.agents.configuration.apply', _hash(fixed))

            # Replays are historical observations of the original request.
            # Resolve their existing receipt before consulting mutable owner
            # state so a later native revision cannot turn a replay into a
            # fresh attempt or a new conflict.
            unknown_operation = None
            try:
                prior = env._store.read_operation(request)
            except UnitOperationUnknown as error:
                # A data-only result has no Operation projection. Do not treat
                # it as unused; read_domain_result must prove the exact receipt.
                unknown_operation = error
                prior = None
            if prior is not None:
                if prior.digest != digest or prior.intent.kind != 'configuration-change':
                    raise UnitIdentityMismatch('spent configuration request differs')
                return prior
            receipt = env._store.read_domain_result(request, digest)
            if receipt is None and unknown_operation is not None:
                raise unknown_operation
            if receipt is not None:
                if (not isinstance(receipt, dict)
                        or receipt.get('verified') != 'standing-operation'
                        or not isinstance(receipt.get('noChangeOf'), str)
                        or receipt.get('profileRef') != encode_revision_ref(profile_ref)):
                    raise UnitOperationUnknown('stored no-change result cannot be verified; do not resend')
                return self.query(node_ref, receipt['noChangeOf'])

            admitted = self._owner(node, 'inspect_unit', 'inspect_configuration')
            unit = self._inspection(node, admitted)
            snapshot = self.inspect(node_ref)
            if snapshot.source_revision is None or snapshot.comparison_guarantee == 'unavailable':
                raise ConfigurationUnsupported('owner revision comparison unavailable')
            if snapshot.source_revision != change.expected_configuration_revision:
                raise ConfigurationRevisionConflict('expected owner configuration revision differs')
            scope_id = 'scope-' + hashlib.sha256(safe_json(unit.configuration_target_ref).encode()).hexdigest()[:48]
            fence = env._store.read_domain(env.environment_id, CONFIGURATION_ATTEMPTS, scope_id)
            expected_profile, standing_ref = self._expected_source(node, fence)
            if not _same(encode_revision_ref(base_profile_ref), expected_profile):
                raise ConfigurationRevisionConflict('base Profile snapshot differs from the scope expected source')
            ids = {item['declarationId'] for item in change.declarations}
            standing = None if standing_ref is None else self.query(node_ref, standing_ref)
            if standing is not None and self._standing_covers(
                    standing, standing_ref, ids, profile_ref, expected_profile, unit, snapshot):
                writes = () if snapshot_write is None else (snapshot_write,)
                env._store.commit_domain_change(request, digest, writes,
                    {'noChangeOf': standing_ref, 'verified': 'standing-operation',
                     'profileRef': encode_revision_ref(profile_ref)})
                return standing
            operation = self.reserve(request, node_ref, change, profile_ref=profile_ref,
                                     base_profile_ref=base_profile_ref,
                                     snapshot_write=snapshot_write, mode='no-change-verification')
            current = env._store.read_operation(request)
            if current.status in {'published', 'refused', 'cancelled'}:
                return current
            result = ConfigurationChangeResult(
                operation.intent.operation_ref,
                tuple(ConfigurationItemResult(item['declarationId'], 'unknown')
                      for item in change.declarations))
            evidence = {'configurationResult': result.to_dict(),
                        'reason': 'no change requested; no standing configuration result covers this manifest',
                        'ownerObservation': snapshot.to_dict()}
            if standing_ref is not None:
                evidence['standingOperationRef'] = standing_ref
            return env._store.record_operation_outcome(request, operation.digest, current.revision,
                                                       'refused', evidence)

    def _standing_covers(self, operation, standing_ref, ids, profile_ref, expected_profile, unit, snapshot):
        """Check generic owner evidence for the exact current whole manifest.

        Declaration payloads remain opaque to core. A standing result can
        satisfy a new no-change request only when its fixed Profile digest,
        complete item confirmations, and owner-confirmed snapshot all match
        the current observation's scope and revision.
        """
        if (operation is None or operation.intent.kind != 'configuration-change'
                or operation.intent.operation_ref != standing_ref
                or operation.status != 'published'):
            return False
        context = operation.intent.context_ref
        if (not _same(context.get('profileRef'), expected_profile)
                or decode_revision_ref(dict(expected_profile)).digest != profile_ref.digest):
            return False
        raw = self.operation_view(operation).get('configurationResult')
        if (not isinstance(raw, dict) or raw.get('operationRef') != standing_ref
                or raw.get('overallOutcome') != 'applied'
                or not isinstance(raw.get('itemResults'), list)
                or {item.get('declarationId') for item in raw['itemResults'] if isinstance(item, dict)} != ids
                or len(raw['itemResults']) != len(ids)):
            return False
        confirmed = raw.get('confirmedSnapshot')
        if (not isinstance(confirmed, dict)
                or confirmed.get('sourceRevision') != snapshot.source_revision
                or confirmed.get('comparisonGuarantee') != snapshot.comparison_guarantee
                or not _same(confirmed.get('unitRef'), unit.unit_ref)
                or not _same(confirmed.get('scopeRef'), unit.configuration_target_ref)
                or not _same(confirmed.get('configuration'), snapshot.configuration)
                or not _same(confirmed.get('unknownItems'), list(snapshot.unknown_items))
                or not _same(snapshot.scope_ref, unit.configuration_target_ref)):
            return False
        for item in raw['itemResults']:
            confirmation = item.get('confirmation') if isinstance(item, dict) else None
            if (not isinstance(item, dict) or item.get('outcome') != 'applied'
                    or not isinstance(confirmation, dict)
                    or confirmation.get('operationRef') != standing_ref
                    or confirmation.get('requestDigest') != operation.digest
                    or not _same(confirmation.get('unitRef'), unit.unit_ref)
                    or not _same(confirmation.get('scopeRef'), unit.configuration_target_ref)):
                return False
        return True

    def apply(self, request, node_ref, change, *, profile_ref=None, base_profile_ref=None,
              snapshot_write=None):
        operation = self.reserve(request, node_ref, change, profile_ref=profile_ref,
                                 base_profile_ref=base_profile_ref, snapshot_write=snapshot_write)
        env = self._environment
        with env._admission_lock:
            step = env._store.read_operation_step(request,'configuration-apply')
            if step is not None or operation.status in {'published','refused','cancelled','unknown'}:
                return self._finish_recorded(request, operation, step)
            try:
                node = self._request(request,node_ref)
                admitted = self._owner(node,'inspect_unit','inspect_configuration','apply_configuration')
                unit = self._inspection(node,admitted)
                context = operation.intent.context_ref
                snapshot = self.inspect(node_ref)
                if (unit.management_epoch != operation.intent.management_epoch
                        or unit.source_revision != context['unitSourceRevision']
                        or not _same(unit.directory_binding_ref.to_dict(),context['directoryBindingRef'])
                        or snapshot.comparison_guarantee != context['comparisonGuarantee']):
                    raise _KnownPreDispatchRefusal('owner-recheck', 'owner-evidence-changed')
                if snapshot.source_revision != change.expected_configuration_revision:
                    raise _KnownPreDispatchRefusal('owner-recheck', 'configuration-revision-changed')
                effective = context['effectiveDeclarations']
                if not effective:
                    result = ConfigurationChangeResult(operation.intent.operation_ref,
                        tuple(ConfigurationItemResult(item['declarationId'],'rejected')
                              for item in change.declarations))
                    return env._store.record_operation_outcome(
                        request,operation.digest,operation.revision,'refused',
                        {'configurationResult':result.to_dict(),
                         'reason':'no applicable declarations; no native dispatch'})
                effective_change = replace_change(change,effective)
                invocation = self._issuer.issue(request,operation.digest,'configuration-apply','applyConfiguration',unit.configuration_target_ref)
            except _KnownPreDispatchRefusal as refusal:
                self._refuse_unclaimed(request, operation, refusal.phase, refusal.reason)
                raise UnitAdmissionRefused('owner evidence changed before configuration dispatch') from None
            except UnitAdmissionRefused:
                self._refuse_unclaimed(request, operation, 'owner-recheck', 'admission-refused')
                raise
            except ConfigurationRevisionConflict:
                self._refuse_unclaimed(request, operation, 'owner-recheck', 'configuration-revision-changed')
                raise
            except ConfigurationUnsupported:
                self._refuse_unclaimed(request, operation, 'owner-recheck', 'configuration-unsupported')
                raise
            except InvocationAuthorityRefused:
                self._refuse_unclaimed(request, operation, 'invocation-issuance', 'invocation-authority-refused')
                raise
        # External owner code executes outside the Environment admission lock.
        try:
            result = admitted.provider.apply_configuration(unit.unit_ref,effective_change,invocation)
            if not self._issuer.verified_consumption(invocation):
                raise UnitGuaranteeUnavailable('owner did not verify the issued invocation')
            result = merge_skipped(operation,effective_change,result)
            self._validate_result(operation,change,unit,result)
        except Exception:
            return self._record(request,operation,None,invocation.facts['claimRevision'])
        return self._record(request,operation,result,invocation.facts['claimRevision'])

    def _refuse_unclaimed(self, request, operation, phase, reason):
        """Conclude only an explicitly refused request with durable no-step proof."""
        env = self._environment
        refusal_method = getattr(env._store, 'refuse_unclaimed_operation', None)
        if (not isinstance(env._store, PreDispatchRefusalStorePort)
                or not callable(refusal_method)):
            # Older stores keep their existing reserved/held state. No second
            # write path can safely emulate the capability.
            raise UnitAdmissionRefused('atomic pre-dispatch refusal capability unavailable')
        rollback = operation.intent.context_ref.get('preDispatchRollback')
        expected_keys = {
            'namespace', 'recordId', 'preReservationFenceRevision',
            'priorExpectedProfileRef', 'priorExpectedProfileOperationRef',
            'reservedExpectedProfileRef', 'reservedExpectedProfileOperationRef',
        }
        if not isinstance(rollback, Mapping) or set(rollback) != expected_keys:
            raise UnitAdmissionRefused('pre-dispatch rollback facts unavailable')
        previous_revision = rollback.get('preReservationFenceRevision')
        namespace, record_id = rollback.get('namespace'), rollback.get('recordId')
        target_ref = operation.intent.context_ref.get('configurationTargetRef')
        if not isinstance(target_ref, Mapping):
            raise UnitAdmissionRefused('pre-dispatch target identity unavailable')
        expected_record_id = 'scope-' + hashlib.sha256(safe_json(target_ref).encode()).hexdigest()[:48]
        if (type(previous_revision) is not int or previous_revision < 0
                or namespace != CONFIGURATION_ATTEMPTS or record_id != expected_record_id):
            raise UnitAdmissionRefused('pre-dispatch rollback facts invalid')
        prior_profile = rollback.get('priorExpectedProfileRef')
        prior_operation = rollback.get('priorExpectedProfileOperationRef')
        reserved_profile = rollback.get('reservedExpectedProfileRef')
        reserved_operation = rollback.get('reservedExpectedProfileOperationRef')
        try:
            prior_ref = decode_revision_ref(_plain(prior_profile))
            reserved_ref = decode_revision_ref(_plain(reserved_profile))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise UnitAdmissionRefused('pre-dispatch prior Profile source unavailable') from None
        if (prior_ref.environment_namespace != env.environment_id
                or reserved_ref.environment_namespace != env.environment_id
                or (prior_operation is not None
                    and (not isinstance(prior_operation, str) or not prior_operation))
                or (reserved_operation is not None
                    and (not isinstance(reserved_operation, str) or not reserved_operation))):
            raise UnitAdmissionRefused('pre-dispatch prior source identity invalid')
        fence = env._store.read_domain(env.environment_id, namespace, record_id)
        expected_reserved_revision = previous_revision + 1
        if fence is None or fence.get('revision') != expected_reserved_revision:
            raise UnitAdmissionRefused('reserved configuration fence changed')
        value = _plain(fence.get('value'))
        context = operation.intent.context_ref
        if (value.get('principalScope') != request.principal_scope
                or value.get('requestId') != request.request_id
                or value.get('operationRef') != operation.intent.operation_ref
                or not _same(value.get('scopeRef'), target_ref)
                or not _same(value.get('expectedProfileRef'), encode_revision_ref(reserved_ref))
                or not _same(value.get('expectedProfileOperationRef'), reserved_operation)):
            raise UnitAdmissionRefused('reserved configuration fence identity changed')
        value['expectedProfileRef'] = encode_revision_ref(prior_ref)
        value['expectedProfileOperationRef'] = prior_operation
        restore = DomainWrite(namespace, record_id, expected_reserved_revision, value)
        return refusal_method(request, operation.digest, operation.revision,
                              {'phase': phase, 'reason': reason}, (restore,))

    @staticmethod
    def _validate_result(operation,change,unit,result):
        if not isinstance(result,ConfigurationChangeResult) or result.operation_ref != operation.intent.operation_ref:
            raise ConfigurationContractError('owner result identity differs')
        if {item.declaration_id for item in result.item_results} != {item['declarationId'] for item in change.declarations}:
            raise ConfigurationContractError('result must account for every declaration')
        for item in result.item_results:
            if item.outcome=='applied' and (not _same(item.confirmation['unitRef'],unit.unit_ref)
                    or not _same(item.confirmation['scopeRef'],unit.configuration_target_ref)
                    or item.confirmation['requestDigest'] != operation.digest):
                raise ConfigurationContractError('owner confirmation target or request differs')
            if item.outcome=='deferred' and not change.application_policy.allow_deferred:
                raise ConfigurationContractError('owner deferred without application permission')
        if result.confirmed_snapshot is not None and (not _same(result.confirmed_snapshot.unit_ref,unit.unit_ref)
                or not _same(result.confirmed_snapshot.scope_ref,unit.configuration_target_ref)):
            raise ConfigurationContractError('owner confirmed snapshot target differs')

    def _finish_recorded(self, request, operation, step):
        """Complete a data-only publication interrupted after owner evidence.

        This consumes the same concluded step, never another native call.
        """
        if operation.status in {'published','refused','cancelled'} or step is None or step.outcome != 'concluded':
            return operation
        evidence = json.loads(step.evidence_json)
        result = evidence.get('configurationResult')
        if result is None:
            raise UnitGuaranteeUnavailable('concluded configuration result unavailable')
        return self._environment._store.publish_operation(request,operation.digest,operation.revision,
            ('configuration-apply',),(),(),{'nodeRef':_plain(operation.intent.node_ref),'configurationResult':result})

    def _record(self,request,operation,result,expected_step_revision):
        env=self._environment
        with env._admission_lock:
            current=env._store.read_operation(request)
            step=env._store.read_operation_step(request,'configuration-apply')
            if (current.status in {'published','refused','cancelled'} or step is None
                    or step.revision != expected_step_revision or step.outcome == 'concluded'):
                # A query is an observation of this attempt, never permission
                # to replace a newer receipt or dispatch under a new key.
                return self._finish_recorded(request,current,step)
            evidence={'environmentNamespace':env.environment_id,'operationRef':operation.intent.operation_ref}
            if result is not None:
                evidence['configurationResult']=result.to_dict()
            else:
                evidence['reason']='owner result unavailable or unconfirmed'
            previous=json.loads(step.evidence_json)
            observations=list(previous.get('observations',()))
            observation={key:value for key,value in evidence.items() if key not in {'environmentNamespace','operationRef'}}
            if not observations or not _same(observations[-1],observation):
                observations.append(observation)
            evidence['observations']=observations
            uncertain=result is None or any(item.outcome in {'unknown','deferred'} for item in result.item_results)
            env._store.record_operation_step(request,operation.digest,'configuration-apply',step.intent.input_digest,
                                            step.revision,'unknown' if uncertain else 'concluded',evidence)
            current=env._store.read_operation(request)
            if uncertain: return current
            return env._store.publish_operation(request,operation.digest,current.revision,('configuration-apply',),(),(),
                {'nodeRef':_plain(operation.intent.node_ref),'configurationResult':result.to_dict()})

    def query(self,node_ref,operation_ref):
        env=self._environment
        with env._admission_lock:
            node=self._admit(node_ref,'read')
            if (not isinstance(env._store,OperationStorePort) or not isinstance(env._store,DomainStorePort)
                    or not isinstance(self._issuer,InvocationIssuer) or self._issuer._store is not env._store):
                raise UnitGuaranteeUnavailable('same-store operation and read authority required')
            if not isinstance(operation_ref,str) or not operation_ref or len(operation_ref)>256:
                raise UnitIdentityMismatch('complete operation identity required')
            if not env._policy.admit_object_access(env._principal_scope,f'{env.environment_id}:operation:{operation_ref}','read'):
                raise UnitAdmissionRefused('configuration operation read refused')
            # Existing core identity index, never a new recovery dictionary.
            identity=env._store.read_domain(env.environment_id,'core.operation-identities',operation_ref)
            if identity is None:
                raise UnitGuaranteeUnavailable('configuration operation unavailable')
            holder=identity['value']['holder']
            if holder.get('principalScope')!=env._principal_scope or holder.get('operationId')!=operation_ref:
                raise UnitAdmissionRefused('operation belongs to another authenticated realm')
            request=RequestKey(env.environment_id,holder['principalScope'],holder['requestId'])
            operation=env._store.read_operation(request)
            if (operation is None or operation.intent.kind!='configuration-change'
                    or operation.intent.operation_ref!=operation_ref
                    or not _same(operation.intent.node_ref,encode_node_ref(node_ref))):
                raise UnitIdentityMismatch('configuration operation target differs')
            if operation.status in {'published','refused','cancelled','reserved'}:
                return operation
            step=env._store.read_operation_step(request,'configuration-apply')
            if step is None:
                raise UnitGuaranteeUnavailable('configuration dispatch claim unavailable')
            if step.outcome == 'concluded':
                return self._finish_recorded(request,operation,step)
            admitted=self._owner(node,'inspect_unit','query_change')
            unit=self._inspection(node,admitted)
            if not _same(admitted.provider_ref,operation.intent.steps[0].pinned_provider_ref):
                raise UnitAdmissionRefused('original configuration owner no longer admitted')
            change=ConfigurationChangeRequest.from_dict(_plain(operation.intent.context_ref['change']))
            invocation=self._issuer.issue_query(request,operation.digest,'configuration-apply')
        try:
            result=admitted.provider.query_change(unit.unit_ref,operation_ref,invocation)
            if not self._issuer.verified_observation(invocation):
                raise UnitGuaranteeUnavailable('owner did not verify read authority')
            result=merge_skipped(operation,replace_change(change,operation.intent.context_ref['effectiveDeclarations']),result)
            self._validate_result(operation,change,unit,result)
        except Exception:
            return env._store.read_operation(request)
        return self._record(request,operation,result,step.revision)

    def operation_view(self, operation):
        """Public attempt projection, not a current configuration snapshot."""
        step=self._environment._store.read_operation_step(operation.request,'configuration-apply')
        result=(operation.result or {}).get('configurationResult')
        if result is None and step is not None:
            result=step.evidence.get('configurationResult')
        if result is None:
            result=json.loads(operation.evidence_json).get('configurationResult')
        return {'operationRef':operation.intent.operation_ref,'revision':operation.revision,
                'status':operation.status,'configurationResult':_plain(result) if result is not None else None}


def replace_change(change,declarations):
    return ConfigurationChangeRequest(change.request_id,change.expected_configuration_revision,
                                      tuple(_plain(item) for item in declarations),change.application_policy)


def merge_skipped(operation,effective_change,result):
    from ordessa_units.configuration.contracts import ConfigurationItemResult
    if not isinstance(result,ConfigurationChangeResult) or {item.declaration_id for item in result.item_results}!={item['declarationId'] for item in effective_change.declarations}:
        raise ConfigurationContractError('owner result must cover exactly the effective declarations')
    skipped=tuple(ConfigurationItemResult(name,'rejected') for name in operation.intent.context_ref['skippedOptional'])
    return ConfigurationChangeResult(result.operation_ref,result.item_results+skipped,result.confirmed_snapshot)
