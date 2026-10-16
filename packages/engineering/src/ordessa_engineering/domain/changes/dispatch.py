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
from ..artifacts.method_codec import decode_method_ref
from ..common.mechanisms.codec import decode_digest
from ..packages.refs import ImplementationPackageRef
from ..reviews.ref_codec import decode_review_ref
from .ref_codec import decode_proposal_ref

# A generation binding acts on an already reviewed change. The subject carries
# exactly the reviewed design change, the review that passed it, the pinned
# method and the exact inputs digest; nothing else is accepted.
GENERATION_SUBJECT_FIELDS = frozenset({'review_ref', 'change_ref', 'method_ref', 'inputs_digest'})


def package_ref_projection(ref):
    """The one canonical projection of a frozen implementation package reference.

    An implementation step's subject is exactly this: the whole package identity
    (its scope, its id, its content digest and its kind). This is a *domain data*
    helper, not a decode-time gate: the binding's own decode accepts a v2 record
    whose subject it does not compare (old rows stay readable). The active write
    guard consumes this projection to refuse a subject that names another package
    than the one the binding acts on — a substitution is refused at the write, not
    while reading an already stored row.
    """
    return {'realm_id': ref.realm_id, 'project_id': ref.project_id,
            'package_id': ref.package_id, 'digest': asdict(ref.digest), 'kind': ref.kind}


@dataclass(frozen=True)
class DispatchBinding:
    scope: Scope
    run_id: str
    step_id: str
    attempt: int
    fence: int
    package_ref: ImplementationPackageRef | None
    approval_ref: ApprovalRef | None
    intent_digest: Digest | None
    control_version: int | None
    action_instances: tuple[tuple[str, str], ...]
    unit_ref_bytes: bytes
    execution_operation_ref: str
    prompt_ref: BlobRef
    prompt_input_digest: Digest
    expected_query_digest: str
    required_results: tuple[str, ...]
    # Schema 2 only. `work` carries the original fields plus the namespaced
    # internal dispatch key; `subject` says what the step acts on. A v1 row has
    # none of these and keeps its original schema, bytes and digest.
    binding_version: int = 1
    work: dict | None = None
    subject: dict | None = None
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        if self.binding_version not in (1, 2):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        if self.binding_version == 1 and (self.work is not None or self.subject is not None):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        if self.binding_version == 2:
            self._check_declared_work_binding()
        if (type(self.scope) is not Scope
                or (self.package_ref is not None
                    and type(self.package_ref) is not ImplementationPackageRef)
                or type(self.prompt_ref) is not BlobRef
                or type(self.prompt_input_digest) is not Digest):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        # A generation binding (declared Work acting on an already reviewed
        # change) carries no approval, no implementation intent and no control
        # version: the applicable authority is the reviewed change plus the host
        # execution permission. Stuffing an unrelated approval here would
        # fabricate authority, so those fields must be absent.
        generation = self._generation_subject()
        if generation:
            if (self.approval_ref is not None or self.intent_digest is not None
                    or self.control_version is not None):
                raise ReferenceError('INVALID_DISPATCH_BINDING')
        elif (type(self.approval_ref) is not ApprovalRef
                or type(self.intent_digest) is not Digest
                or self.control_version is None):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        for value in (self.run_id,self.step_id,self.execution_operation_ref,self.expected_query_digest):validate_id(value)
        for value in (self.attempt,self.fence):validate_version(value)
        if self.control_version is not None:validate_version(self.control_version)
        if self.attempt < 1 or self.fence < 1:raise ReferenceError('INVALID_DISPATCH_BINDING')
        if ((self.package_ref is not None
                and (self.package_ref.realm_id, self.package_ref.project_id)
                    != (self.scope.realm_id, self.scope.project_id))
                or (self.approval_ref is not None
                    and (self.approval_ref.realm_id,self.approval_ref.project_id)
                        !=(self.scope.realm_id,self.scope.project_id))):
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
            forbidden = {'accept_artifact', 'apply_change'}
            if self.binding_version == 2 and self.subject is not None \
                    and self.subject.get('subject_kind') == 'reviewed_change':
                generation_ok = True
            else:
                generation_ok = False
                forbidden = forbidden | {'generate_package'}
            if (type(item) is not tuple or len(item) != 2 or item[0] not in ACTIONS
                    or item[0] in forbidden):
                raise ReferenceError('INVALID_DISPATCH_BINDING')
            validate_id(item[1]);actions.append(item[0]);instances.append(item[1])
        if len(set(actions))!=len(actions) or len(set(instances))!=len(instances):raise ReferenceError('INVALID_DISPATCH_BINDING')
        validate_items(self.required_results,str,nonempty=True)
        for item in self.required_results:validate_id(item)
        if len(set(self.required_results))!=len(self.required_results):raise ReferenceError('INVALID_DISPATCH_BINDING')
        payload=self.projection()
        if len(canonical_bytes(payload))>262144:raise ReferenceError('INVALID_DISPATCH_BINDING')
        kind = ('implementation-dispatch-binding-v2' if self.binding_version == 2
                else 'implementation-dispatch-binding-v1')
        object.__setattr__(self,'digest',record_digest(kind,payload))

    def _generation_subject(self):
        """True only for a schema-2 binding acting on an already reviewed change."""
        return (self.binding_version == 2 and type(self.subject) is dict
                and self.subject.get('subject_kind') == 'reviewed_change')

    def _check_declared_work_binding(self):
        """Schema 2: a declared Work step, never a run-derived package stand-in."""
        work = self.work
        if (type(work) is not dict
                or set(work) != {'work_id', 'action_id', 'step_id', 'dispatch_key'}):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        for name in ('work_id', 'action_id', 'step_id', 'dispatch_key'):
            validate_id(work[name])
        if not work['dispatch_key'].split(':')[:1] in (['w1'], ['w1h']):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        subject = self.subject
        if (type(subject) is not dict or set(subject) != {'subject_kind', 'subject_ref'}
                or subject['subject_kind'] not in ('reviewed_change', 'frozen_package')
                or type(subject['subject_ref']) is not dict or not subject['subject_ref']):
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        if subject['subject_kind'] == 'reviewed_change':
            # Generation acts on the already reviewed change: there is no
            # package yet, so a package_ref here would be a fabrication.
            if self.package_ref is not None:
                raise ReferenceError('INVALID_DISPATCH_BINDING')
            ref = subject['subject_ref']
            if (type(ref) is not dict or set(ref) != set(GENERATION_SUBJECT_FIELDS)):
                raise ReferenceError('INVALID_DISPATCH_BINDING')
            decode_review_ref(ref['review_ref'])
            decode_proposal_ref(ref['change_ref'])
            decode_method_ref(ref['method_ref'])
            if type(ref['inputs_digest']) is not dict:
                raise ReferenceError('INVALID_DISPATCH_BINDING')
            decode_digest(ref['inputs_digest'])
        elif type(self.package_ref) is not ImplementationPackageRef:
            # The frozen-package subject is typed here; whether it is the *exact*
            # projection of the package the binding acts on is an active-write
            # question, enforced by the write guard (`package_ref_projection`),
            # never by decode. A v2 record stored before that guard existed still
            # decodes and reads back unchanged.
            raise ReferenceError('INVALID_DISPATCH_BINDING')

    def projection(self):
        value={k:v for k,v in asdict(self).items() if k!='digest'}
        if self.binding_version == 1:
            # A v1 row projects exactly the fields it always did: its stored
            # bytes and digest are never recomputed under a new schema.
            for key in ('binding_version', 'work', 'subject'):
                value.pop(key, None)
        value['unit_ref_bytes']=decode_json(self.unit_ref_bytes)
        return value
