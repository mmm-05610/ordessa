"""Demand-side fixed material origin values and method-declared independence.

These values are captured source facts, never a human credential or grant.
The configured original-record reader and current reviewer authority validate
them; callers cannot authenticate by constructing a value of these types.
"""
from dataclasses import dataclass
from typing import Protocol

from .commands import CommandKey
from .errors import ApplicationError
from ...domain.artifacts.method_binding import MethodRef
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import Digest

NATIVE_DIFFERENT_UNIT = 'original_author_unit_identity_must_differ_from_original_reviewer_unit_identity'
SOURCE_BOUND_POLICY = {
    'contract':'ordessa.review.authorship-policy/1',
    'source_rules':{'native_unit':'different_original_unit',
                    'authenticated_material_submitter':'separately_assigned_reviewer_role'},
    'unknown_source':'refuse',
}


def validate_authorship_policy(value):
    """Accept only explicitly supported frozen policies, preserving old refs."""
    if value is None or value == NATIVE_DIFFERENT_UNIT or value == SOURCE_BOUND_POLICY:
        return value
    raise ApplicationError('UNIT_REVIEW_IDENTITY_CONSTRAINT_UNSUPPORTED')


@dataclass(frozen=True)
class MaterialSubmissionProof:
    revision_ref: ArtifactRevisionRef
    command_key: CommandKey
    operation: str
    operation_id: str
    request_digest: Digest
    result_digest: Digest
    submitter_principal_id: str

    def __post_init__(self):
        if (type(self.revision_ref) is not ArtifactRevisionRef
                or type(self.command_key) is not CommandKey
                or self.operation not in ('engineering.artifacts.create','engineering.artifacts.append_revision')
                or type(self.operation_id) is not str or not self.operation_id
                or type(self.request_digest) is not Digest or type(self.result_digest) is not Digest
                or self.submitter_principal_id != self.command_key.principal_id
                or self.command_key.realm_id != self.revision_ref.realm_id):
            raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')


@dataclass(frozen=True)
class ReviewAuthorship:
    scope: Scope
    method_ref: MethodRef
    delivery_refs: tuple[ArtifactRevisionRef,...]
    source_kind: str
    author_unit_ref: dict | None = None
    material_proofs: tuple[MaterialSubmissionProof,...] = ()

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.method_ref) is not MethodRef
                or type(self.delivery_refs) is not tuple or not self.delivery_refs
                or len(self.delivery_refs)>4096 or len(set(self.delivery_refs))!=len(self.delivery_refs)
                or any(type(r) is not ArtifactRevisionRef or
                       (r.realm_id,r.project_id)!=(self.scope.realm_id,self.scope.project_id)
                       for r in self.delivery_refs)):
            raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')
        if self.source_kind=='native_unit':
            if (type(self.author_unit_ref) is not dict or set(self.author_unit_ref)!=
                    {'environmentNamespace','unitId','ownerProviderRef','sourceRevision'}
                    or self.material_proofs):
                raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')
        elif self.source_kind=='authenticated_material_submitter':
            if (self.author_unit_ref is not None or type(self.material_proofs) is not tuple
                    or any(type(p) is not MaterialSubmissionProof for p in self.material_proofs)
                    or len(self.material_proofs)!=len(self.delivery_refs)
                    or {p.revision_ref for p in self.material_proofs}!=set(self.delivery_refs)):
                raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')
        else:
            raise ApplicationError('REVIEW_AUTHOR_SOURCE_UNSUPPORTED')


class ReviewAuthorshipResolver(Protocol):
    def resolve_authorship(self, context, plan, delivery_refs) -> ReviewAuthorship: ...


def authorship_mode(policy, source):
    validate_authorship_policy(policy)
    if type(source) is not ReviewAuthorship:
        raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')
    if policy == NATIVE_DIFFERENT_UNIT:
        if source.source_kind!='native_unit':
            raise ApplicationError('UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE')
        return 'different_original_unit'
    if policy == SOURCE_BOUND_POLICY:
        return SOURCE_BOUND_POLICY['source_rules'][source.source_kind]
    raise ApplicationError('UNIT_REVIEW_IDENTITY_CONSTRAINT_UNSUPPORTED')


def resolve_plan_authorship(resolver, context, plan, delivery_refs=None):
    """Validate an original-source response; a captured DTO is not the reader."""
    refs=tuple(target.ref for target in plan.requirement.expected_targets.targets) if delivery_refs is None else delivery_refs
    if resolver is None or not callable(getattr(resolver,'resolve_authorship',None)):
        raise ApplicationError('REVIEW_AUTHOR_SOURCE_UNAVAILABLE')
    source=resolver.resolve_authorship(context,plan,refs)
    if (type(source) is not ReviewAuthorship or source.scope!=context.scope
            or source.scope!=plan.scope or source.method_ref!=plan.requirement.method_ref
            or source.delivery_refs!=refs):
        raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')
    return source
