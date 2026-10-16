"""Closed ChangeSet business refusal/context; common constructors use diagnostics.

The six existing subject kinds are an explicit use-case context, not a registry
of arbitrary references. Unknown extension codes retain the safe schema mapping.
"""
from dataclasses import dataclass, field
from enum import Enum
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.reviews.refs import ReviewRef, SubmissionRef
from ordessa_engineering.domain.reviews.targets import SubjectRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from .refs import ProposalRef
from .baselines import RepositorySnapshotRef

class DomainErrorCode(str, Enum):
    ACTION_NOT_AUTHORIZED = "ACTION_NOT_AUTHORIZED"
    ALREADY_REVOKED = "ALREADY_REVOKED"
    ANCESTRY_LIMIT = "ANCESTRY_LIMIT"
    ARTIFACT_ALREADY_ADOPTED = "ARTIFACT_ALREADY_ADOPTED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_NOT_YET_VALID = "AUTHORIZATION_NOT_YET_VALID"
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    AUTHORIZATION_UNUSABLE = "AUTHORIZATION_UNUSABLE"
    BASE_NOT_ANCESTOR = "BASE_NOT_ANCESTOR"
    BASE_TARGET_MISMATCH = "BASE_TARGET_MISMATCH"
    CHECK_OUT_OF_PLAN = "CHECK_OUT_OF_PLAN"
    CONSENT_BINDING_MISMATCH = "CONSENT_BINDING_MISMATCH"
    CONSENT_REPLAY = "CONSENT_REPLAY"
    CONTROL_NOT_AUTHORIZED = "CONTROL_NOT_AUTHORIZED"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    DUPLICATE_CHECK = "DUPLICATE_CHECK"
    DUPLICATE_CLAIM = "DUPLICATE_CLAIM"
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"
    DUPLICATE_MUTATION = "DUPLICATE_MUTATION"
    DUPLICATE_PARENT = "DUPLICATE_PARENT"
    DUPLICATE_PROPOSAL = "DUPLICATE_PROPOSAL"
    DUPLICATE_PROVENANCE = "DUPLICATE_PROVENANCE"
    DUPLICATE_REVIEW = "DUPLICATE_REVIEW"
    DUPLICATE_ROLE = "DUPLICATE_ROLE"
    DUPLICATE_TARGET = "DUPLICATE_TARGET"
    EVIDENCE_TARGET_MISMATCH = "EVIDENCE_TARGET_MISMATCH"
    GATE_NOT_SATISFIED = "GATE_NOT_SATISFIED"
    ID_ALREADY_EXISTS = "ID_ALREADY_EXISTS"
    IMMUTABLE_ID_COLLISION = "IMMUTABLE_ID_COLLISION"
    IMPLEMENTATION_INTENT_CONFLICT = "IMPLEMENTATION_INTENT_CONFLICT"
    INCOMPLETE_BATCH = "INCOMPLETE_BATCH"
    INVALID_ACTION_SCOPE = "INVALID_ACTION_SCOPE"
    INVALID_ACTOR = "INVALID_ACTOR"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"
    INVALID_BLOB_REF = "INVALID_BLOB_REF"
    INVALID_CHANGE_SET = "INVALID_CHANGE_SET"
    INVALID_CLAIM = "INVALID_CLAIM"
    INVALID_CONTEXT = "INVALID_CONTEXT"
    INVALID_CONTROL = "INVALID_CONTROL"
    INVALID_EVIDENCE_LINK = "INVALID_EVIDENCE_LINK"
    INVALID_GENERATION_ORIGIN = "INVALID_GENERATION_ORIGIN"
    INVALID_IMPLEMENTATION_BASELINE = "INVALID_IMPLEMENTATION_BASELINE"
    INVALID_IMPLEMENTATION_INTENT = "INVALID_IMPLEMENTATION_INTENT"
    INVALID_JOURNAL = "INVALID_JOURNAL"
    INVALID_METHOD_CONTENT = "INVALID_METHOD_CONTENT"
    INVALID_METHOD_RESOURCE = "INVALID_METHOD_RESOURCE"
    INVALID_MUTATION = "INVALID_MUTATION"
    INVALID_NA = "INVALID_NA"
    INVALID_PARENT = "INVALID_PARENT"
    INVALID_PATH = "INVALID_PATH"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    INVALID_POLICY = "INVALID_POLICY"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    INVALID_PROPOSAL_CONTROL = "INVALID_PROPOSAL_CONTROL"
    INVALID_RAW_RESPONSE_REF = "INVALID_RAW_RESPONSE_REF"
    INVALID_READ_SET = "INVALID_READ_SET"
    INVALID_RECORD_BYTES = "INVALID_RECORD_BYTES"
    INVALID_RESERVATION = "INVALID_RESERVATION"
    INVALID_RESOLVED_GRAPH = "INVALID_RESOLVED_GRAPH"
    INVALID_RESULT = "INVALID_RESULT"
    INVALID_REVIEW_BYTES = "INVALID_REVIEW_BYTES"
    INVALID_REVIEW_READ_SET = "INVALID_REVIEW_READ_SET"
    INVALID_REVIEW_SELECTOR = "INVALID_REVIEW_SELECTOR"
    INVALID_REVIEW_TEMPLATE = "INVALID_REVIEW_TEMPLATE"
    INVALID_REVISION = "INVALID_REVISION"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    INVALID_SELECTION = "INVALID_SELECTION"
    INVALID_SELECTOR = "INVALID_SELECTOR"
    INVALID_SOURCE = "INVALID_SOURCE"
    INVALID_SOURCE_CAPTURE = "INVALID_SOURCE_CAPTURE"
    INVALID_SOURCE_LOCATOR = "INVALID_SOURCE_LOCATOR"
    INVALID_SOURCE_URL = "INVALID_SOURCE_URL"
    INVALID_SUPERSEDES_REF = "INVALID_SUPERSEDES_REF"
    INVALID_TIME = "INVALID_TIME"
    INVALID_VERSION = "INVALID_VERSION"
    METHOD_DISABLED = "METHOD_DISABLED"
    METHOD_INCOMPATIBLE = "METHOD_INCOMPATIBLE"
    OUTPUT_OUT_OF_SCOPE = "OUTPUT_OUT_OF_SCOPE"
    PACKAGE_COVERAGE_MISSING = "PACKAGE_COVERAGE_MISSING"
    PARENT_MISMATCH = "PARENT_MISMATCH"
    PAYLOAD_KIND_MISMATCH = "PAYLOAD_KIND_MISMATCH"
    PROPOSAL_CONTROL_REQUIRED = "PROPOSAL_CONTROL_REQUIRED"
    PROPOSAL_TOO_LARGE = "PROPOSAL_TOO_LARGE"
    PROPOSAL_UNAVAILABLE = "PROPOSAL_UNAVAILABLE"
    READ_SET_DUPLICATE = "READ_SET_DUPLICATE"
    REALM_MISMATCH = "REALM_MISMATCH"
    RECORD_TOO_LARGE = "RECORD_TOO_LARGE"
    REFERENCE_CYCLE = "REFERENCE_CYCLE"
    REFERENCE_MISSING = "REFERENCE_MISSING"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
    REQUIRED_OUTPUT_MISSING = "REQUIRED_OUTPUT_MISSING"
    REVIEW_CONFLICT = "REVIEW_CONFLICT"
    REVIEW_FAILED = "REVIEW_FAILED"
    REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"
    REVIEW_INDETERMINATE = "REVIEW_INDETERMINATE"
    REVIEW_STALE = "REVIEW_STALE"
    REVISION_DIGEST_MISMATCH = "REVISION_DIGEST_MISMATCH"
    REVISION_TOO_LARGE = "REVISION_TOO_LARGE"
    SCOPE_EXCEEDED = "SCOPE_EXCEEDED"
    SELECTOR_OUT_OF_RANGE = "SELECTOR_OUT_OF_RANGE"
    SELECTOR_WORK_LIMIT = "SELECTOR_WORK_LIMIT"
    STALE_BASELINE = "STALE_BASELINE"
    STATEMENT_DIGEST_MISMATCH = "STATEMENT_DIGEST_MISMATCH"
    SUBMISSION_BINDING_MISMATCH = "SUBMISSION_BINDING_MISMATCH"
    SUBMISSION_COVERAGE_MISSING = "SUBMISSION_COVERAGE_MISSING"
    SUBMISSION_REQUIRED = "SUBMISSION_REQUIRED"
    TARGET_CONFLICT = "TARGET_CONFLICT"
    UNRESOLVED_ACCEPTANCE_TEMPLATE = "UNRESOLVED_ACCEPTANCE_TEMPLATE"
    UNRESOLVED_CLAIM = "UNRESOLVED_CLAIM"
    UNRESOLVED_EFFECT = "UNRESOLVED_EFFECT"
    UNRESOLVED_EVIDENCE_LINK = "UNRESOLVED_EVIDENCE_LINK"
    UNRESOLVED_METHOD_CONTENT = "UNRESOLVED_METHOD_CONTENT"
    UNRESOLVED_MUTATION = "UNRESOLVED_MUTATION"
    UNRESOLVED_REVIEW_TARGET = "UNRESOLVED_REVIEW_TARGET"
    UNSUPPORTED_ARTIFACT_KIND = "UNSUPPORTED_ARTIFACT_KIND"
    UNTRUSTED_CONSENT = "UNTRUSTED_CONSENT"
    UNTRUSTED_REVIEWER = "UNTRUSTED_REVIEWER"
    VERSION_CONFLICT = "VERSION_CONFLICT"

@dataclass(frozen=True)
class DomainError:
    code: DomainErrorCode
    subject_refs: tuple["SubjectRef | ReviewRef | ApprovalRef", ...] = ()
    details: tuple[tuple[str, int | bool], ...] = ()
    violations: tuple["DomainError", ...] = ()
    message_key: str = field(init=False)

    def __post_init__(self):
        if type(self.code) is not DomainErrorCode:
            raise ValueError("INVALID_DOMAIN_ERROR")
        if type(self.subject_refs) is not tuple or len(self.subject_refs) > 4096:
            raise ValueError("INVALID_DOMAIN_ERROR")
        ref_types = {ArtifactRevisionRef, ProposalRef, SubmissionRef,
                     RepositorySnapshotRef, ReviewRef, ApprovalRef}
        if any(type(ref) not in ref_types for ref in self.subject_refs):
            raise ValueError("INVALID_DOMAIN_ERROR")
        safe_keys = {"expected_version", "actual_version", "expected_count",
                     "actual_count", "limit", "index"}
        if (type(self.details) is not tuple or len(self.details) > len(safe_keys)
                or any(type(pair) is not tuple or len(pair) != 2 or
                       type(pair[0]) is not str or pair[0] not in safe_keys or
                       type(pair[1]) not in {int, bool} or
                       (type(pair[1]) is int and not 0 <= pair[1] <= (1 << 63) - 1)
                       for pair in self.details)
                or len({pair[0] for pair in self.details}) != len(self.details)):
            raise ValueError("INVALID_DOMAIN_ERROR")
        if (type(self.violations) is not tuple or len(self.violations) > 4096
                or any(type(item) is not DomainError for item in self.violations)):
            raise ValueError("INVALID_DOMAIN_ERROR")
        # Count occurrences, including shared child values, because wire output
        # repeats them. Per-layer bounds alone permit exponential expansion.
        pending = [(self, 0)]
        visited = 0
        while pending:
            item, depth = pending.pop()
            visited += 1
            if depth > 32 or visited > 4096:
                raise ValueError("INVALID_DOMAIN_ERROR")
            pending.extend((child, depth + 1) for child in item.violations)
        object.__setattr__(self, "details", tuple(sorted(self.details)))
        object.__setattr__(self, "message_key", "engineering.domain." + self.code.value.lower())


def from_reference_error(refusal: ReferenceError) -> DomainError:
    """Translate a known constructor refusal at an explicit business boundary.

    Preserve the former safe extension-code mapping without exception text;
    unrelated programming exceptions are not accepted or caught here.
    """
    if type(refusal) is not ReferenceError:
        raise TypeError("Expected ReferenceError at domain refusal boundary")
    try:
        code = DomainErrorCode(refusal.code)
    except (ValueError, TypeError):
        code = DomainErrorCode.INVALID_SCHEMA
    return DomainError(code)
