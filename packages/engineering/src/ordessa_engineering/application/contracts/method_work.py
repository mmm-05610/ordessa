"""Trusted current Work inputs, not event truth or permission evidence."""
from dataclasses import asdict, dataclass, fields
from typing import Protocol
from .run_waits import BoundRunWait
from .errors import ApplicationError
from .commands import ReadSet
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import Digest, MAX_VERSION, validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.artifacts.method_binding import MethodRef
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.changes.refs import ProposalRef
from ...domain.packages.refs import ImplementationPackageRef
from ...domain.reviews.refs import SubmissionRef
from ...domain.reviews.models import ReviewRequirement
from ordessa_infrastructure.encoding import canonical_bytes

WORK_CONTRACT = 'ordessa.engineering.current-work/1'
WAIT_EVENT = 'engineering.work.current_condition'


@dataclass(frozen=True)
class WorkReviewSelector:
    """Exact Work-stage input selection; it grants no authority or readiness.

    Original Work/review owners check the current node, persisted attempt,
    immutable input and subject under the original transaction fence.
    """
    scope: Scope
    run_id: str
    method_ref: MethodRef
    phase_key: str
    attempt: int
    input_ref: ArtifactRevisionRef
    subject_ref: ProposalRef | ArtifactRevisionRef | ImplementationPackageRef | SubmissionRef
    expected_row_digest: Digest
    expected_next_step_ordinal: int

    def __post_init__(self):
        try:
            validate_id(self.run_id)
            validate_id(self.phase_key)
            if (type(self.scope) is not Scope or type(self.method_ref) is not MethodRef
                    or type(self.input_ref) is not ArtifactRevisionRef
                    or type(self.subject_ref) not in
                    (ProposalRef, ArtifactRevisionRef, ImplementationPackageRef, SubmissionRef)
                    or type(self.expected_row_digest) is not Digest
                    or type(self.attempt) is not int or not 1 <= self.attempt <= MAX_VERSION
                    or type(self.expected_next_step_ordinal) is not int
                    or not 0 <= self.expected_next_step_ordinal <= MAX_VERSION):
                raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
            for ref in (self.input_ref, self.subject_ref):
                if (ref.realm_id, ref.project_id) != (self.scope.realm_id, self.scope.project_id):
                    raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
        except ReferenceError:
            raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID') from None


def work_review_selector_projection(selector):
    if type(selector) is not WorkReviewSelector:
        raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
    return asdict(selector)


def decode_work_review_selector(value):
    """Decode closed owner references without resolving or deriving Work facts."""
    from ...domain.common.mechanisms.codec import require_object, decode_scope, decode_digest
    from ...domain.artifacts.method_codec import decode_method_ref
    from ...domain.artifacts.ref_codec import decode_artifact_ref
    from ...domain.reviews.target_codec import decode_subject_ref
    from ...domain.packages.codec import decode_package_ref
    try:
        require_object(value, {field.name for field in fields(WorkReviewSelector)}, 'INVALID_SCHEMA')
        subject = value['subject_ref']
        parser = (decode_package_ref if type(subject) is dict
                  and subject.get('kind') == 'implementation_package' else decode_subject_ref)
        return WorkReviewSelector(decode_scope(value['scope']), value['run_id'],
            decode_method_ref(value['method_ref']), value['phase_key'], value['attempt'],
            decode_artifact_ref(value['input_ref']), parser(subject),
            decode_digest(value['expected_row_digest']), value['expected_next_step_ordinal'])
    except (ReferenceError, TypeError, ValueError, KeyError):
        raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID') from None


@dataclass(frozen=True)
class WorkSeed:
    slots: dict
    read_set: ReadSet

    def __post_init__(self):
        if (type(self.slots) is not dict or len(canonical_bytes(self.slots)) > 2097152
                or type(self.read_set) is not ReadSet):
            raise ApplicationError('WORK_INPUT_INVALID')


@dataclass(frozen=True)
class ReviewWaitRequirements:
    scope: Scope
    required_review_requirements: tuple[ReviewRequirement, ...]

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.required_review_requirements) is not tuple
                or not self.required_review_requirements or len(self.required_review_requirements) > 4096
                or any(type(r) is not ReviewRequirement or r.scope != self.scope
                       for r in self.required_review_requirements)):
            raise ApplicationError('WORK_CONDITION_INVALID')


@dataclass(frozen=True)
class WorkWaitSelection:
    condition: BoundRunWait
    event_values: dict

    def __post_init__(self):
        if (type(self.condition) is not BoundRunWait or type(self.event_values) is not dict
                or len(canonical_bytes(self.event_values)) > 2097152):
            raise ApplicationError('WORK_CONDITION_INVALID')


@dataclass(frozen=True, kw_only=True)
class BoundWorkWait(BoundRunWait):
    next_cursor: int
    next_status: str
    next_wait_reason: str | None
    slot_updates: tuple

    def __post_init__(self):
        super().__post_init__()
        if (type(self.next_cursor) is not int or self.next_cursor < 0
                or type(self.slot_updates) is not tuple
                or len({name for name,_ in self.slot_updates}) != len(self.slot_updates)
                or self.next_status not in ('RUNNING','WAITING_FOR_CONDITION','SLICE_DONE')
                or (self.next_status == 'WAITING_FOR_CONDITION') != (self.next_wait_reason is not None)):
            raise ApplicationError('WORK_CONDITION_INVALID')
        canonical_bytes(dict(self.slot_updates))


class WorkConditionSource(Protocol):
    def step_input_ref(self, context, snapshot, view):
        """Return the method-declared exact immutable input revision, if any.

        A method with no such declaration returns None. Work-bound reviews
        require a real original revision; absence cannot establish proof.
        """
        ...

    def guard_inputs(self, context, snapshot, view, input_ref):
        """Yield a single validated method-input slot update and original ReadSet.

        Explicit immutable material selection only; it never moves a cursor,
        adopts a head, establishes permission, or advances acceptance.
        """
        ...
    def guard_start(self, context, snapshot, *, run_id, selection):
        """Yield slots plus owner-observed same-library ReadSet; held to COMMIT.

        selection is the explicit method subject/material selection supplied to
        the original Work creation command. It is input, never ready/approval
        evidence. Production sources resolve its exact refs in the original
        repositories before constructing slots.

        The original write UoW rechecks persisted dependency versions. Any
        external dependency needs its own held immutable snapshot/guard; this
        contract does not claim atomicity across independent stores.
        """
        ...
    def guard_condition(self, context, snapshot, node, row):
        """Yield WorkWaitSelection, held through original condition CAS COMMIT.

        Complete phase requirements and action intents come from original business
        owners, not caller events/approved flags. Root validates row and snapshot,
        resolves original facts, verifies full gates and never accepts ready=True.
        """
        ...

    def guard_step_completion(self, context, snapshot, node, view):
        """Yield the actual command ReadSet, held through original step CAS.

        The journal result must match the method-mapped inputs and these original
        expectations. A caller completion flag cannot stand in for this source.
        """
        ...
