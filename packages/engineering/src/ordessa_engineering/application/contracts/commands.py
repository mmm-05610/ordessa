"""Application command and journal values; contexts are internal inputs."""
from dataclasses import asdict, dataclass

from ...domain.common.models.values import (Digest, validate_id)
from ...domain.common.models.identity import (Scope)
from ...domain.common.outcomes.diagnostics import (ReferenceError)
from ...domain.common.mechanisms.hashing import (record_digest)
from ...domain.common.models.identity import (ActorRef)
from ...domain.common.models.values import (utc_instant)
from ...domain.common.mechanisms.codec import (canonical_value)
from ...domain.reviews.models import (ReviewSetExpectation, ReviewControlExpectation, ReviewRequestExpectation)
from .preconditions import (VersionExpectation)

__all__ = ['CommandKey', 'CommandContext', 'request_digest', 'JournalEntry', 'Reservation',
           'CommandResult', 'ReadVersion', 'ReadSet', 'read_set_projection', 'artifact_read_set_projection']


@dataclass(frozen=True)
class CommandKey:
    realm_id: str
    principal_id: str
    request_id: str

    def __post_init__(self):
        for value in (self.realm_id, self.principal_id, self.request_id):
            validate_id(value)


@dataclass(frozen=True)
class CommandContext:
    scope: Scope
    principal_id: str
    authenticated_actor: ActorRef
    request_id: str
    received_at: str
    trace_id: str

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.authenticated_actor) is not ActorRef:
            raise ReferenceError("INVALID_CONTEXT")
        for value in (self.principal_id, self.request_id, self.trace_id):
            validate_id(value)
        utc_instant(self.received_at)

    @property
    def key(self):
        return CommandKey(self.scope.realm_id, self.principal_id, self.request_id)


def request_digest(operation: str, ctx: CommandContext, parameters, preconditions, *,
                   input_schema_id: str, input_schema_digest: Digest, interface_version: str) -> Digest:
    validate_id(operation)
    validate_id(input_schema_id)
    validate_id(interface_version)
    if type(input_schema_digest) is not Digest:
        raise ReferenceError("INVALID_SCHEMA")
    return record_digest("engineering-command", {"operation": operation,
        "input_schema_id": input_schema_id, "input_schema_digest": asdict(input_schema_digest),
        "interface_version": interface_version,
        "realm_id": ctx.scope.realm_id, "project_id": ctx.scope.project_id,
        "principal_id": ctx.principal_id, "parameters": parameters, "preconditions": preconditions})


@dataclass(frozen=True)
class JournalEntry:
    key: CommandKey
    project_id: str
    operation: str
    operation_id: str
    request_digest: Digest
    state: str
    result_bytes: bytes | None
    version: int

    def __post_init__(self):
        if type(self.key) is not CommandKey or type(self.request_digest) is not Digest:
            raise ReferenceError("INVALID_JOURNAL")
        for value in (self.project_id, self.operation, self.operation_id):
            validate_id(value)
        if (self.state not in {"pending", "completed", "rejected"} or type(self.version) is not int
                or not 0 <= self.version <= (1 << 63) - 1 or (self.state == "pending") != (self.result_bytes is None)):
            raise ReferenceError("INVALID_JOURNAL")
        if self.result_bytes is not None:
            canonical_value(self.result_bytes)


@dataclass(frozen=True)
class Reservation:
    entry: JournalEntry
    created: bool

    def __post_init__(self):
        if type(self.entry) is not JournalEntry or type(self.created) is not bool:
            raise ReferenceError("INVALID_RESERVATION")


@dataclass(frozen=True)
class CommandResult:
    authority_id: str
    operation_id: str
    status: str
    result_bytes: bytes | None

    def __post_init__(self):
        validate_id(self.authority_id)
        validate_id(self.operation_id)
        if (self.status not in {"pending", "completed", "rejected"}
                or (self.status == "pending") != (self.result_bytes is None)):
            raise ReferenceError("INVALID_RESULT")
        if self.result_bytes is not None:
            canonical_value(self.result_bytes)

    @property
    def result(self):
        return canonical_value(self.result_bytes) if self.result_bytes is not None else None


@dataclass(frozen=True)
class ReadVersion:
    kind: str
    identifier: str
    version: int

    def __post_init__(self):
        validate_id(self.kind)
        validate_id(self.identifier)
        if type(self.version) is not int or not 0 <= self.version <= (1 << 63) - 1:
            raise ReferenceError("INVALID_VERSION")

    def expectation(self, scope: Scope) -> VersionExpectation:
        return VersionExpectation(self.kind, scope.realm_id, scope.project_id,
                                  self.identifier, self.version)


@dataclass(frozen=True)
class ReadSet:
    scope: Scope
    versions: tuple[ReadVersion, ...]
    review_sets: tuple[ReviewSetExpectation, ...] = ()
    review_controls: tuple[ReviewControlExpectation, ...] = ()

    review_requests: tuple[ReviewRequestExpectation, ...] = ()

    @property
    def version_expectations(self) -> tuple[VersionExpectation, ...]:
        return tuple(item.expectation(self.scope) for item in self.versions)

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.versions) is not tuple or any(type(v) is not ReadVersion for v in self.versions):
            raise ReferenceError("INVALID_READ_SET")
        if len({(v.kind, v.identifier) for v in self.versions}) != len(self.versions):
            raise ReferenceError("READ_SET_DUPLICATE")
        object.__setattr__(self, "versions", tuple(sorted(self.versions, key=lambda v: (v.kind, v.identifier))))
        if (type(self.review_sets) is not tuple or type(self.review_controls) is not tuple
                or any(type(item) is not ReviewSetExpectation for item in self.review_sets)
                or any(type(item) is not ReviewControlExpectation for item in self.review_controls)):
            raise ReferenceError("INVALID_REVIEW_READ_SET")
        if (len({item.key for item in self.review_sets}) != len(self.review_sets)
                or len({item.review_ref for item in self.review_controls}) != len(self.review_controls)):
            raise ReferenceError("READ_SET_DUPLICATE")
        if (any(item.key.scope != self.scope for item in self.review_sets)
                or any((item.review_ref.realm_id, item.review_ref.project_id) !=
                       (self.scope.realm_id, self.scope.project_id) for item in self.review_controls)):
            raise ReferenceError("REALM_MISMATCH")
        if (type(self.review_requests) is not tuple or len(self.review_requests) > 4096
                or any(type(item) is not ReviewRequestExpectation for item in self.review_requests)):
            raise ReferenceError("INVALID_REVIEW_READ_SET")
        if len({item.review_id for item in self.review_requests}) != len(self.review_requests):
            raise ReferenceError("READ_SET_DUPLICATE")
        if any(item.scope != self.scope for item in self.review_requests):
            raise ReferenceError("REALM_MISMATCH")
        object.__setattr__(self, "review_requests", tuple(sorted(self.review_requests, key=lambda i: i.review_id)))
        object.__setattr__(self, "review_sets", tuple(sorted(self.review_sets, key=lambda i: i.key.digest.hex)))
        object.__setattr__(self, "review_controls", tuple(sorted(self.review_controls, key=lambda i: i.review_ref.review_id)))


def read_set_projection(reads: ReadSet):
    """Keep historical command identities when no pending-request predicate exists."""
    value = asdict(reads)
    if not reads.review_requests:
        value.pop('review_requests')
    return value


def artifact_read_set_projection(reads: ReadSet):
    """Original interface2 Artifact projection, including historical list form."""
    versions=[{"resource":{"kind":r.kind,"id":r.identifier},"expected_version":r.version}
              for r in reads.versions]
    value=versions
    if reads.review_sets or reads.review_controls or reads.review_requests:
        value={"versions":versions,"review_sets":[asdict(r) for r in reads.review_sets],
               "review_controls":[asdict(r) for r in reads.review_controls]}
    if reads.review_requests:
        value["review_requests"]=[asdict(r) for r in reads.review_requests]
    return value
