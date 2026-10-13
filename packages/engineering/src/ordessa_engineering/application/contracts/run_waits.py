"""Trusted Work selection over original persisted run rows; never caller truth."""
from dataclasses import asdict, dataclass
from typing import Protocol
from ordessa_infrastructure.encoding import canonical_bytes
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import Digest, validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.common.mechanisms.hashing import record_digest


@dataclass(frozen=True)
class BoundRunWait:
    scope: Scope
    run_id: str
    row_digest: Digest
    next_step_ordinal: int
    family: str
    refs: tuple = ()
    intent: object = None
    approval_ref: object = None
    action: str | None = None
    expected_control_version: int | None = None

    def __post_init__(self):
        validate_id(self.run_id)
        if (type(self.scope) is not Scope or type(self.row_digest) is not Digest
                or type(self.next_step_ordinal) is not int or self.next_step_ordinal < 0
                or self.family not in {'object_exists','review_gate','action_authorization','result_exists'}
                or type(self.refs) is not tuple or len(self.refs) > 4096):
            raise ReferenceError('INVALID_RUN_WAIT')
        exists = self.family in {'object_exists','result_exists'}
        if exists:
            if (not self.refs or any(value is not None for value in
                    (self.intent,self.approval_ref,self.action,self.expected_control_version))):
                raise ReferenceError('INVALID_RUN_WAIT')
        elif (self.refs or self.intent is None or getattr(self.intent,'scope',None) != self.scope
                or not getattr(self.intent,'required_review_requirements',())):
            raise ReferenceError('INVALID_RUN_WAIT')
        if self.family == 'review_gate' and any(value is not None for value in
                (self.approval_ref,self.action,self.expected_control_version)):
            raise ReferenceError('INVALID_RUN_WAIT')
        if self.family == 'action_authorization' and (self.approval_ref is None
                or type(self.action) is not str or self.action not in self.intent.actions
                or type(self.expected_control_version) is not int or self.expected_control_version < 0):
            raise ReferenceError('INVALID_RUN_WAIT')

    @property
    def digest(self):
        return record_digest('bound-run-wait', asdict(self))


def run_wait_row_digest(row):
    """Identity includes the original method/registry/inputs/cursor/timestamps."""
    return record_digest('run-wait-row', {
        **row, 'method_ref': asdict(row['method_ref'])})


class CurrentRunWaitBindings(Protocol):
    def guard_wait(self, context, run_id, row):
        """Hold current trusted method/Work selection and yield BoundRunWait.

        Owner must establish exact row belongs to context.scope and its actual
        selected workflow condition. Missing production Work owner refuses;
        wire refs/condition booleans and C09 material casts cannot select it.
        """
        ...
