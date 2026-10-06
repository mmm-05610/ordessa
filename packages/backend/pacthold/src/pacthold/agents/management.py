"""Configuration coordination on the existing Environment operation ledger.

The admitted Unit owner interprets and confirms native configuration. Core
stores fixed intent and immutable observations, never a mutable actual cache.
"""
from __future__ import annotations

import hashlib
import json

from ordessa_environment_api import (
 AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError,
 ParticipantInstanceRef, RequestKey, UnknownResultError,
)
from ordessa_environment_api.domain import DomainStorePort, DomainWrite
from ordessa_environment_api.operations import OperationIntent, OperationStorePort, StepIntent, safe_json
from .configuration import (
 ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationContractError,
 ConfigurationSnapshot, ConfigurationUnsupported, ConfigurationRevisionConflict, UnitInspection,
)
from .invocation import InvocationIssuer
from .nodes import encode_node_ref

CONFIGURATION_ATTEMPTS = 'agents.configuration-attempts'


def _plain(value): return json.loads(safe_json(value))
def _hash(value): return 'sha256:' + hashlib.sha256(safe_json(value).encode()).hexdigest()
def _same(left,right): return safe_json({'value':left}) == safe_json({'value':right})


class AgentConfiguration:
    def __init__(self, environment, nodes, *, invocation_issuer=None):
        self._environment, self._nodes = environment, nodes
        self._issuer = invocation_issuer

    def capabilities(self):
        return {'configurationManagement':isinstance(self._issuer,InvocationIssuer)
                and self._issuer._store is self._environment._store}

    def _admit(self, node_ref, access):
        env = self._environment
        env._check_open()
        if not isinstance(node_ref, ParticipantInstanceRef):
            raise IdentityMismatchError('complete Node identity required')
        env._check_environment(node_ref.environment)
        if env._policy is None or not env._policy.admit_object_access(
                env._principal_scope, f'{env.environment_id}:agents.node:{node_ref.instance_id}', access):
            raise AdmissionRefusedError('Node configuration access refused')
        node = self._nodes.read(node_ref)
        if node is None:
            raise GuaranteeUnavailableError('published Node unavailable')
        return node

    def _owner(self, node, *methods):
        admitted = self._environment.agent_runtime_contribution(node['binding']['harnessDefinitionRef'])
        if not _same(admitted.provider_ref,node['binding']['harnessProviderRef']):
            raise AdmissionRefusedError('Node owner activation differs')
        if any(method not in admitted.descriptor.supported_methods for method in methods):
            raise ConfigurationUnsupported('owner does not support the requested operation')
        return admitted

    @staticmethod
    def _call(callback, *args):
        try:
            return callback(*args)
        except Exception:
            raise GuaranteeUnavailableError('owner configuration evidence unavailable') from None

    def _inspection(self, node, admitted):
        unit = self._call(admitted.provider.inspect_unit, node['binding']['harnessUnitRef'])
        if (not isinstance(unit, UnitInspection) or not _same(unit.unit_ref,node['binding']['harnessUnitRef'])
                or not _same(unit.provider_ref,admitted.provider_ref)
                or not _same(unit.configuration_target_ref,node['binding']['configurationTargetRef'])):
            raise GuaranteeUnavailableError('current Unit owner evidence differs from Node binding')
        return unit

    def describe(self, node_ref):
        node = self._admit(node_ref, 'read')
        admitted = self._owner(node, 'describe_configuration')
        from .configuration import ConfigurationDescription
        result = self._call(admitted.provider.describe_configuration, node['binding']['harnessUnitRef'])
        if (not isinstance(result, tuple) or any(not isinstance(item, ConfigurationDescription) for item in result)
                or len({(item.configuration_kind,item.schema_version) for item in result}) != len(result)):
            raise GuaranteeUnavailableError('owner description is incomplete or ambiguous')
        return result

    def inspect(self, node_ref):
        node = self._admit(node_ref, 'read')
        admitted = self._owner(node, 'inspect_unit', 'inspect_configuration')
        unit = self._inspection(node, admitted)
        result = self._call(admitted.provider.inspect_configuration, unit.unit_ref)
        if not isinstance(result, ConfigurationSnapshot) or not _same(result.unit_ref,unit.unit_ref) or not _same(result.scope_ref,unit.configuration_target_ref):
            raise GuaranteeUnavailableError('owner snapshot target differs')
        return result

    def _request(self, request, node_ref):
        env = self._environment
        if not isinstance(request, RequestKey) or request.principal_scope != env._principal_scope:
            raise AdmissionRefusedError('authenticated request realm differs')
        env._check_environment(request.environment_namespace)
        node = self._admit(node_ref, 'write')
        if env._policy is None or not env._policy.admit_invoke(env._principal_scope, 'pacthold.agents.configuration.apply', 'reliable'):
            raise AdmissionRefusedError('configuration invocation refused')
        if not isinstance(env._store, OperationStorePort) or not isinstance(env._store, DomainStorePort) or env._fingerprint_port is None:
            raise GuaranteeUnavailableError('configuration requires the existing durable operation store and fingerprint port')
        if not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not env._store:
            raise GuaranteeUnavailableError('explicit invocation issuer on the same Environment store required')
        return node

    def reserve(self, request, node_ref, change):
        if not isinstance(change, ConfigurationChangeRequest) or not isinstance(request, RequestKey) or request.request_id != change.request_id:
            raise IdentityMismatchError('configuration request identity differs')
        env = self._environment
        with env._admission_lock:
            node = self._request(request, node_ref)
            fixed = {'nodeRef':encode_node_ref(node_ref), 'change':change.to_dict()}
            digest = env._fingerprint_port.fingerprint(request, 'pacthold.agents.configuration.apply', _hash(fixed))
            prior = env._store.read_operation(request)
            if prior is not None:
                if prior.digest != digest or prior.intent.kind != 'configuration-change':
                    raise IdentityMismatchError('spent configuration request differs')
                return prior
            admitted = self._owner(node, 'inspect_unit', 'inspect_configuration', 'describe_configuration', 'apply_configuration')
            unit = self._inspection(node, admitted)
            snapshot = self.inspect(node_ref)
            if snapshot.source_revision is None or snapshot.comparison_guarantee == 'unavailable':
                raise ConfigurationUnsupported('owner revision comparison unavailable')
            if snapshot.source_revision != change.expected_configuration_revision:
                raise ConfigurationRevisionConflict('expected owner configuration revision differs')
            descriptions = {(item.configuration_kind,item.schema_version):item for item in self.describe(node_ref)}
            skipped = []
            for declaration in change.declarations:
                item = descriptions.get((declaration['configurationKind'],declaration['schemaVersion']))
                supported = item is not None and item.support_status == 'supported' and declaration['action'] in item.supported_actions
                if not supported and declaration['requirement'] == 'required':
                    raise ConfigurationUnsupported('required declaration unsupported before dispatch')
                for ref in declaration.get('resourceRefs', ()):
                    if ref.get('environmentNamespace') != env.environment_id:
                        raise IdentityMismatchError('configuration material environment differs')
                # C1 material acquisition is not yet composed here. Never
                # let an opaque reference masquerade as an acquired resource.
                unresolved = bool(declaration.get('resourceRefs'))
                if unresolved and declaration['requirement'] == 'required':
                    raise ConfigurationUnsupported('required material acquisition unavailable before dispatch')
                if not supported or unresolved:
                    skipped.append(declaration['declarationId'])
            scope_id = 'scope-' + hashlib.sha256(safe_json(unit.configuration_target_ref).encode()).hexdigest()[:48]
            fence = env._store.read_domain(env.environment_id, CONFIGURATION_ATTEMPTS, scope_id)
            if fence is not None:
                source = fence['value']
                old_key = RequestKey(env.environment_id, source['principalScope'], source['requestId'])
                old = env._store.read_operation(old_key)
                if (not _same(source.get('scopeRef'),unit.configuration_target_ref) or old is None
                        or old.intent.kind != 'configuration-change'
                        or old.intent.operation_ref != source.get('operationRef')
                        or not _same(old.intent.context_ref.get('configurationTargetRef'),unit.configuration_target_ref)):
                    raise GuaranteeUnavailableError('configuration scope source identity damaged')
                if old.status not in {'published','refused','cancelled'}:
                    raise UnknownResultError('scope has an unresolved configuration operation')
            operation_ref = 'configuration-' + hashlib.sha256(safe_json({'environmentNamespace':env.environment_id,
                'principalScope':request.principal_scope,'requestId':request.request_id}).encode()).hexdigest()[:48]
            context = {'environmentNamespace':env.environment_id, **fixed,
                'skippedOptional':skipped,
                'effectiveDeclarations':[_plain(item) for item in change.declarations if item['declarationId'] not in skipped],
                'unitRef':_plain(unit.unit_ref), 'configurationTargetRef':_plain(unit.configuration_target_ref),
                'directoryBindingRef':unit.directory_binding_ref.to_dict(), 'unitSourceRevision':unit.source_revision,
                'beforeConfigurationEvidence':_plain(snapshot.confirmation_evidence),
                'comparisonGuarantee':snapshot.comparison_guarantee,
                'invocationBindings':{'configuration-apply':{'action':'applyConfiguration',
                    'targetRef':_plain(unit.configuration_target_ref),'delegationRef':None,'cleanup':False}}}
            step = StepIntent('configuration-apply', admitted.provider_ref, digest, operation_ref+'.apply',
                              management_epoch=unit.management_epoch)
            intent = OperationIntent(operation_ref, 'configuration-change', node['lineage']['profileSnapshotRef'],
                                     context, (step,), encode_node_ref(node_ref), unit.management_epoch)
            return env._store.reserve_operation(request,digest,intent,writes=(DomainWrite(CONFIGURATION_ATTEMPTS,
                scope_id,fence['revision'] if fence else 0,{'scopeRef':_plain(unit.configuration_target_ref),
                    'principalScope':request.principal_scope,'requestId':request.request_id,'operationRef':operation_ref}),))

    def apply_profile(self, request, node_ref, profile_ref, expected_configuration_revision,
                      application_policy):
        """Derive one fixed Profile's declarations in core and apply them.

        The declarations always come from the core-held Profile snapshot; the
        request body can never carry or alter them. Applying a Profile never
        writes the catalog back and a Profile update never applies itself.
        """
        from .configuration import ConfigurationChangeRequest
        from .contracts import ProfileRef
        from .profiles import ProfileCatalog
        if type(profile_ref) is not ProfileRef:
            raise IdentityMismatchError('fixed Profile reference required')
        manifest = ProfileCatalog(self._environment).read(profile_ref)
        declarations = tuple(json.loads(safe_json(item))
                             for item in manifest.content.get('declarations', ()))
        change = ConfigurationChangeRequest(request.request_id, expected_configuration_revision,
                                            declarations, application_policy)
        return self.apply(request, node_ref, change)

    def apply(self, request, node_ref, change):
        operation = self.reserve(request,node_ref,change)
        env = self._environment
        with env._admission_lock:
            step = env._store.read_operation_step(request,'configuration-apply')
            if step is not None or operation.status in {'published','refused','cancelled','unknown'}:
                return self._finish_recorded(request, operation, step)
            node = self._request(request,node_ref)
            admitted = self._owner(node,'inspect_unit','inspect_configuration','apply_configuration')
            unit = self._inspection(node,admitted)
            context = operation.intent.context_ref
            snapshot = self.inspect(node_ref)
            if (unit.management_epoch != operation.intent.management_epoch
                    or unit.source_revision != context['unitSourceRevision']
                    or not _same(unit.directory_binding_ref.to_dict(),context['directoryBindingRef'])
                    or snapshot.source_revision != change.expected_configuration_revision
                    or snapshot.comparison_guarantee != context['comparisonGuarantee']):
                raise AdmissionRefusedError('owner evidence changed before configuration dispatch')
            effective = context['effectiveDeclarations']
            if not effective:
                from .configuration import ConfigurationItemResult
                result = ConfigurationChangeResult(operation.intent.operation_ref,
                    tuple(ConfigurationItemResult(item['declarationId'],'rejected') for item in change.declarations))
                return env._store.record_operation_outcome(request,operation.digest,operation.revision,'refused',
                    {'configurationResult':result.to_dict(),'reason':'no applicable declarations; no native dispatch'})
            effective_change = replace_change(change,effective)
            invocation = self._issuer.issue(request,operation.digest,'configuration-apply','applyConfiguration',unit.configuration_target_ref)
        # External owner code executes outside the Environment admission lock.
        try:
            result = admitted.provider.apply_configuration(unit.unit_ref,effective_change,invocation)
            if not self._issuer.verified_consumption(invocation):
                raise GuaranteeUnavailableError('owner did not verify the issued invocation')
            result = merge_skipped(operation,effective_change,result)
            self._validate_result(operation,change,unit,result)
        except Exception:
            return self._record(request,operation,None,invocation.facts['claimRevision'])
        return self._record(request,operation,result,invocation.facts['claimRevision'])

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
            raise GuaranteeUnavailableError('concluded configuration result unavailable')
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
                raise GuaranteeUnavailableError('same-store operation and read authority required')
            if not isinstance(operation_ref,str) or not operation_ref or len(operation_ref)>256:
                raise IdentityMismatchError('complete operation identity required')
            if not env._policy.admit_object_access(env._principal_scope,f'{env.environment_id}:operation:{operation_ref}','read'):
                raise AdmissionRefusedError('configuration operation read refused')
            # Existing core identity index, never a new recovery dictionary.
            identity=env._store.read_domain(env.environment_id,'core.operation-identities',operation_ref)
            if identity is None:
                raise GuaranteeUnavailableError('configuration operation unavailable')
            holder=identity['value']['holder']
            if holder.get('principalScope')!=env._principal_scope or holder.get('operationId')!=operation_ref:
                raise AdmissionRefusedError('operation belongs to another authenticated realm')
            request=RequestKey(env.environment_id,holder['principalScope'],holder['requestId'])
            operation=env._store.read_operation(request)
            if (operation is None or operation.intent.kind!='configuration-change'
                    or operation.intent.operation_ref!=operation_ref
                    or not _same(operation.intent.node_ref,encode_node_ref(node_ref))):
                raise IdentityMismatchError('configuration operation target differs')
            if operation.status in {'published','refused','cancelled','reserved'}:
                return operation
            step=env._store.read_operation_step(request,'configuration-apply')
            if step is None:
                raise GuaranteeUnavailableError('configuration dispatch claim unavailable')
            if step.outcome == 'concluded':
                return self._finish_recorded(request,operation,step)
            admitted=self._owner(node,'inspect_unit','query_change')
            unit=self._inspection(node,admitted)
            if not _same(admitted.provider_ref,operation.intent.steps[0].pinned_provider_ref):
                raise AdmissionRefusedError('original configuration owner no longer admitted')
            change=ConfigurationChangeRequest.from_dict(_plain(operation.intent.context_ref['change']))
            invocation=self._issuer.issue_query(request,operation.digest,'configuration-apply')
        try:
            result=admitted.provider.query_change(unit.unit_ref,operation_ref,invocation)
            if not self._issuer.verified_observation(invocation):
                raise GuaranteeUnavailableError('owner did not verify read authority')
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
    from .configuration import ConfigurationItemResult
    if not isinstance(result,ConfigurationChangeResult) or {item.declaration_id for item in result.item_results}!={item['declarationId'] for item in effective_change.declarations}:
        raise ConfigurationContractError('owner result must cover exactly the effective declarations')
    skipped=tuple(ConfigurationItemResult(name,'rejected') for name in operation.intent.context_ref['skippedOptional'])
    return ConfigurationChangeResult(result.operation_ref,result.item_results+skipped,result.confirmed_snapshot)
