"""V2 immutable Agent dispatch bytes; no runtime, authorization or Unit fallback."""
from dataclasses import asdict, dataclass, field

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..common.models.identity import Scope
from ..common.models.refs import BlobRef
from ..common.models.values import Digest
from ..common.models.execution_refs import read_agent_instance_ref,validate_agent_turn_query_bytes
from ..common.mechanisms.hashing import record_digest
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.refs import ApprovalRef
from ..packages.refs import ImplementationPackageRef
from .dispatch import validate_dispatch_facts

SCHEMA_VERSION = 'engineering-dispatch-binding/2.1'
PRE_F2_SCHEMA_VERSION = 'engineering-dispatch-binding/2'


@dataclass(frozen=True)
class AgentDispatchBinding:
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
    agent_ref_bytes: bytes
    engineering_attempt_ref: str
    prompt_ref: BlobRef
    prompt_input_digest: Digest
    expected_query_digest: str
    required_results: tuple[str, ...]
    turn_ref_bytes: bytes | None = None
    digest: Digest = field(init=False, default=None)

    def __post_init__(self):
        validate_dispatch_facts(self, operation_ref=self.engineering_attempt_ref)
        read_agent_instance_ref(self.agent_ref_bytes)
        if self.turn_ref_bytes is not None:
            validate_agent_turn_query_bytes(self.turn_ref_bytes,self.agent_ref_bytes,
                'sha256:'+self.prompt_input_digest.hex,self.expected_query_digest)
        payload = self.projection()
        if len(canonical_bytes(payload)) > 262144:
            raise ReferenceError('INVALID_DISPATCH_BINDING')
        tag='implementation-dispatch-binding-v2' if self.turn_ref_bytes is None else 'implementation-dispatch-binding-v2-f2'
        object.__setattr__(self, 'digest', record_digest(tag, payload))
        if len(canonical_bytes(payload | {'digest': asdict(self.digest)})) > 262144:
            raise ReferenceError('INVALID_DISPATCH_BINDING')

    def projection(self):
        value = {k:v for k,v in asdict(self).items() if k != 'digest'}
        value['agent_ref_bytes'] = decode_json(self.agent_ref_bytes)
        if self.turn_ref_bytes is None:
            value.pop('turn_ref_bytes')
            return {'schemaVersion': PRE_F2_SCHEMA_VERSION, **value}
        value['turn_ref_bytes']=decode_json(self.turn_ref_bytes)
        return {'schemaVersion': SCHEMA_VERSION, **value}

    def require_turn_binding(self):
        if self.turn_ref_bytes is None:raise ReferenceError('AGENT_DISPATCH_TURN_REFERENCE_UNAVAILABLE')
        validate_agent_turn_query_bytes(self.turn_ref_bytes,self.agent_ref_bytes,
            'sha256:'+self.prompt_input_digest.hex,self.expected_query_digest)
        return self.turn_ref_bytes


WORK_SCHEMA_VERSION = 'engineering-agent-work-dispatch-binding/1'


@dataclass(frozen=True)
class AgentWorkDispatchBinding(AgentDispatchBinding):
    """Original declared Work/subject with original Agent/Turn identity.

    This new stored format never changes existing F2 bytes. Its local Work
    shape follows the original binding; repository/physical guards independently
    enforce the actual current key, exact package subject and live business cut.
    """
    work: dict = field(kw_only=True)
    subject: dict = field(kw_only=True)

    def __post_init__(self):
        super().__post_init__()
        from .dispatch import DispatchBinding
        DispatchBinding._check_declared_work_binding(self)
        self.require_turn_binding()
        if (self.subject['subject_kind'] != 'frozen_package'
                or self.work['dispatch_key'] != self.run_id
                or self.work['step_id'] != self.step_id):
            raise ReferenceError('INVALID_AGENT_WORK_DISPATCH_BINDING')
        object.__setattr__(self, 'digest', record_digest(
            'implementation-dispatch-binding-agent-work-v1', self.projection()))

    @property
    def binding_version(self):
        return 2  # Same declared Work relation; distinct Agent schema/identity.

    def projection(self):
        return {**super().projection(), 'schemaVersion': WORK_SCHEMA_VERSION}
