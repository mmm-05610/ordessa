"""Immutable business-to-native attempt binding; no execution or authority claim."""
from dataclasses import asdict, dataclass, field
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..common.models.identity import Scope
from ..common.models.refs import BlobRef
from ..common.models.values import Digest, validate_id, validate_items, validate_version
from ..common.mechanisms.hashing import record_digest
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.refs import ApprovalRef
from ..approvals.scope import ACTIONS
from ..packages.refs import ImplementationPackageRef


@dataclass(frozen=True)
class DispatchBinding:
    scope: Scope
    run_id: str
    step_id: str
    attempt: int
    fence: int
    package_ref: ImplementationPackageRef
    approval_ref: ApprovalRef
    intent_digest: Digest
    control_version: int
    action_instances: tuple[tuple[str, str], ...]
    unit_ref_bytes: bytes
    execution_operation_ref: str
    prompt_ref: BlobRef
    prompt_input_digest: Digest
    expected_query_digest: str
    required_results: tuple[str, ...]
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.package_ref) is not ImplementationPackageRef
                or type(self.approval_ref) is not ApprovalRef or type(self.prompt_ref) is not BlobRef
                or type(self.intent_digest) is not Digest or type(self.prompt_input_digest) is not Digest):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        for value in (self.run_id,self.step_id,self.execution_operation_ref,self.expected_query_digest):validate_id(value)
        for value in (self.attempt,self.fence,self.control_version):validate_version(value)
        if self.attempt < 1 or self.fence < 1:raise ReferenceError('INVALID_DISPATCH_BINDING')
        if (self.package_ref.realm_id,self.package_ref.project_id)!=(self.scope.realm_id,self.scope.project_id) or (self.approval_ref.realm_id,self.approval_ref.project_id)!=(self.scope.realm_id,self.scope.project_id):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        if type(self.unit_ref_bytes) is not bytes or len(self.unit_ref_bytes)>4096:raise ReferenceError('INVALID_DISPATCH_BINDING')
        try:unit=decode_json(self.unit_ref_bytes)
        except (TypeError,ValueError):raise ReferenceError('INVALID_DISPATCH_BINDING') from None
        if type(unit) is not dict or set(unit)!={'environmentNamespace','unitId','ownerProviderRef','sourceRevision'} or canonical_bytes(unit)!=self.unit_ref_bytes:
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        if type(unit['ownerProviderRef']) is not dict:raise ReferenceError('INVALID_DISPATCH_BINDING')
        for key in ('environmentNamespace','unitId','sourceRevision'):validate_id(unit[key])
        if type(self.action_instances) is not tuple or not self.action_instances:raise ReferenceError('INVALID_DISPATCH_BINDING')
        actions=[];instances=[]
        for item in self.action_instances:
            if type(item) is not tuple or len(item)!=2 or item[0] not in ACTIONS or item[0] in {'accept_artifact','apply_change','generate_package'}:
                raise ReferenceError('INVALID_DISPATCH_BINDING')
            validate_id(item[1]);actions.append(item[0]);instances.append(item[1])
        if len(set(actions))!=len(actions) or len(set(instances))!=len(instances):raise ReferenceError('INVALID_DISPATCH_BINDING')
        validate_items(self.required_results,str,nonempty=True)
        for item in self.required_results:validate_id(item)
        if len(set(self.required_results))!=len(self.required_results):raise ReferenceError('INVALID_DISPATCH_BINDING')
        payload=self.projection()
        if len(canonical_bytes(payload))>262144:raise ReferenceError('INVALID_DISPATCH_BINDING')
        object.__setattr__(self,'digest',record_digest('implementation-dispatch-binding-v1',payload))

    def projection(self):
        value={k:v for k,v in asdict(self).items() if k!='digest'}
        value['unit_ref_bytes']=decode_json(self.unit_ref_bytes)
        return value
