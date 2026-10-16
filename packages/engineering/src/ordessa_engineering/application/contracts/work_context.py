"""Declarative Work context: fixed published method declaration plus owner references.

A Work binds one project scope to an exact published method declaration snapshot
and to caller-selected owner references. It is a context record, never execution
state: no compiled program, no plan digest, no program cursor, no dispatch recipe
and no permission. Actions are chosen by the caller; the method declaration only
constrains what the caller may ask for.
"""
from dataclasses import asdict, dataclass, field
from typing import Protocol
from ordessa_infrastructure.encoding import canonical_bytes
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import MAX_VERSION, validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.artifacts.method_binding import MethodRef
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.approvals.refs import ApprovalRef
from ...domain.changes.refs import ProposalRef
from ...domain.packages.refs import ImplementationPackageRef
from ...domain.reviews.refs import SubmissionRef
from .errors import ApplicationError

WORK_CONTEXT_CONTRACT = 'ordessa.engineering.declarative-work/1'
WORK_CONTEXT_KIND = 'work-context'
WORK_STABLE_ID_PREFIX = 'declarative-work:'
_ASSOCIATION_TYPES = {'artifact': ArtifactRevisionRef, 'proposal': ProposalRef,
                      'package': ImplementationPackageRef, 'submission': SubmissionRef,
                      # An approval the Work itself recorded; it grants nothing
                      # until the authorization owner verifies it at use.
                      'approval': ApprovalRef}
_MAX_ASSOCIATIONS = 4096


@dataclass(frozen=True)
class WorkAssociation:
    """One caller-selected exact owner reference; it grants nothing by itself."""
    kind: str
    ref: ArtifactRevisionRef | ProposalRef | ImplementationPackageRef | SubmissionRef | ApprovalRef

    def __post_init__(self):
        expected = _ASSOCIATION_TYPES.get(self.kind)
        if expected is None or type(self.ref) is not expected:
            raise ApplicationError('WORK_ASSOCIATION_INVALID')


@dataclass(frozen=True)
class WorkBinding:
    """Persisted Work body: fixed declaration snapshot plus exact references.

    The revision here is the material row revision and must agree with it on
    read; a caller-supplied expected revision that differs is stale, never
    silently accepted. No field of this value is derived from a method program.
    """
    work_id: str
    scope: Scope
    method_ref: MethodRef
    revision: int
    associations: tuple[WorkAssociation, ...] = ()

    def __post_init__(self):
        try:
            validate_id(self.work_id)
            if (type(self.scope) is not Scope or type(self.method_ref) is not MethodRef
                    or type(self.associations) is not tuple
                    or len(self.associations) > _MAX_ASSOCIATIONS
                    or any(type(a) is not WorkAssociation for a in self.associations)):
                raise ApplicationError('WORK_BINDING_INVALID')
            if type(self.revision) is not int or not 1 <= self.revision <= MAX_VERSION:
                raise ApplicationError('WORK_BINDING_INVALID')
            if not self.method_ref.snapshot_digest.hex:
                raise ApplicationError('WORK_BINDING_INVALID')
            if len({(a.kind, a.ref) for a in self.associations}) != len(self.associations):
                raise ApplicationError('WORK_BINDING_INVALID')
            for association in self.associations:
                if (association.ref.realm_id, association.ref.project_id) != (
                        self.scope.realm_id, self.scope.project_id):
                    raise ApplicationError('WORK_ASSOCIATION_SCOPE_MISMATCH')
            if len(canonical_bytes(work_binding_projection(self))) > 2097152:
                raise ApplicationError('WORK_BINDING_INVALID')
        except ReferenceError:
            raise ApplicationError('WORK_BINDING_INVALID') from None

    @property
    def stable_id(self):
        return f'{WORK_STABLE_ID_PREFIX}{self.work_id}'


def _method_ref_projection(method_ref):
    """Exact published declaration reference; it is not a program reference."""
    return {'method_id': method_ref.method_id, 'release_version': method_ref.release_version,
            'schema_version': method_ref.schema_version,
            'snapshot_digest': {'algorithm': 'sha256', 'hex': method_ref.snapshot_digest.hex}}


@dataclass(frozen=True)
class WorkContext:
    """Read view of one persisted Work; it carries no live condition claim."""
    work_id: str
    scope: Scope
    method_ref: MethodRef
    revision: int
    digest: str
    associations: tuple[WorkAssociation, ...]

    def to_dict(self):
        return {'work_id': self.work_id, 'scope': asdict(self.scope),
                'method_ref': _method_ref_projection(self.method_ref),
                'revision': self.revision, 'digest': self.digest,
                'contract': WORK_CONTEXT_CONTRACT,
                'associations': sorted((asdict(a) for a in self.associations),
                                       key=lambda item: (item['kind'],
                                                         canonical_bytes(item['ref']).decode()))}


def work_binding_projection(binding):
    """Canonical persisted body; it pins the contract and every exact reference."""
    if type(binding) is not WorkBinding:
        raise ApplicationError('WORK_BINDING_INVALID')
    return {'contract': WORK_CONTEXT_CONTRACT, 'work_id': binding.work_id,
            'scope': asdict(binding.scope),
            'method_ref': _method_ref_projection(binding.method_ref),
            'revision': binding.revision,
            'associations': [{'kind': a.kind, 'ref': asdict(a.ref)} for a in binding.associations]}


def decode_work_binding(value):
    """Decode a persisted Work body without resolving or deriving any fact."""
    from ...domain.common.mechanisms.codec import require_object, decode_scope
    from ...domain.artifacts.method_codec import decode_method_ref
    from ...domain.artifacts.ref_codec import decode_artifact_ref
    from ...domain.reviews.target_codec import decode_subject_ref
    from ...domain.packages.codec import decode_package_ref
    from ...domain.approvals.ref_codec import decode_approval_ref
    try:
        require_object(value, {'contract', 'work_id', 'scope', 'method_ref', 'revision',
                               'associations'}, 'INVALID_SCHEMA')
        if value['contract'] != WORK_CONTEXT_CONTRACT:
            raise ApplicationError('WORK_CONTRACT_UNSUPPORTED')
        associations = []
        if type(value['associations']) is not list:
            raise ApplicationError('WORK_BINDING_INVALID')
        for item in value['associations']:
            require_object(item, {'kind', 'ref'}, 'INVALID_SCHEMA')
            ref = item['ref']
            if item['kind'] == 'package':
                decoded = decode_package_ref(ref)
            elif item['kind'] == 'artifact':
                decoded = decode_artifact_ref(ref)
            elif item['kind'] == 'approval':
                decoded = decode_approval_ref(ref)
            else:
                decoded = decode_subject_ref(ref)
            associations.append(WorkAssociation(item['kind'], decoded))
        return WorkBinding(value['work_id'], decode_scope(value['scope']),
                           decode_method_ref(value['method_ref']), value['revision'],
                           tuple(associations))
    except ApplicationError:
        raise
    except (ReferenceError, TypeError, ValueError, KeyError):
        raise ApplicationError('WORK_BINDING_INVALID') from None


class WorkContextSource(Protocol):
    def read_declaration(self, method_ref):
        """Read the exact published declaration this Work pins; no live grant.

        It must not materialize a compiled program, and it must refuse when the
        release is not a published declaration of this library.
        """
        ...
