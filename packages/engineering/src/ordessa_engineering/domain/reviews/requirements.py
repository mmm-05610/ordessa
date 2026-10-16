"""Frozen review templates; exact requirements are expanded after their subject."""
from dataclasses import dataclass, field, asdict
from typing import Literal

from ..common.models.values import (Digest, validate_id, validate_items, validate_version, ordered_unique)
from ..common.models.identity import (Scope)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.artifacts.models import (ArtifactRevision)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.reviews.refs import (SubmissionRef)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.mechanisms.hashing import (record_digest)
from ordessa_engineering.domain.artifacts.provenance import (ClaimRef)
from .models import (PURPOSES, CriterionSetRef, CheckKey, ReviewRequirement,
    payload_fields)
from ordessa_infrastructure.encoding import canonical_bytes


@dataclass(frozen=True)
class SubjectSelector:
    kind: str
    index: int | None = None
    implementation_intent_id: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ReferenceError('INVALID_REVIEW_SELECTOR')
        if self.kind in {'base_mutation', 'proposed_mutation', 'claim_owner'}:
            valid=type(self.index) is int and 0 <= self.index < 4096 and self.implementation_intent_id is None
        elif self.kind == 'self_proposal':
            valid=self.index is None and self.implementation_intent_id is None
        elif self.kind == 'result_of_intent':
            valid=self.index is None and self.implementation_intent_id is not None
            if valid:
                validate_id(self.implementation_intent_id)
        else:
            valid=False
        if not valid:
            raise ReferenceError('INVALID_REVIEW_SELECTOR')


@dataclass(frozen=True)
class ExactArtifactRevisionSelector:
    """Select one explicit immutable artifact revision as a review target."""
    artifact_revision_ref: ArtifactRevisionRef
    kind: Literal['exact_artifact_revision'] = field(default='exact_artifact_revision', init=False)

    def __post_init__(self):
        if type(self.artifact_revision_ref) is not ArtifactRevisionRef:
            raise ReferenceError('INVALID_REVIEW_SELECTOR')


@dataclass(frozen=True)
class TemplateTarget:
    role: str
    selector: SubjectSelector | ExactArtifactRevisionSelector

    def __post_init__(self):
        if type(self.selector) not in {SubjectSelector, ExactArtifactRevisionSelector} or self.role not in {'primary','base','proposed','output','support'}:
            raise ReferenceError('INVALID_REVIEW_SELECTOR')


@dataclass(frozen=True)
class TemplateCheck:
    target: TemplateTarget
    criterion_id: str
    claim_id: str | None = None

    def __post_init__(self):
        if type(self.target) is not TemplateTarget:
            raise ReferenceError('INVALID_REVIEW_SELECTOR')
        validate_id(self.criterion_id)
        if self.claim_id is not None:
            validate_id(self.claim_id)
            if self.target.selector.kind in {'self_proposal','result_of_intent'}:
                raise ReferenceError('INVALID_REVIEW_SELECTOR')


@dataclass(frozen=True)
class ReviewRequirementTemplateRef:
    scope: Scope
    template_id: str
    template_version: int
    digest: Digest

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.digest) is not Digest:
            raise ReferenceError('INVALID_SCHEMA')
        validate_id(self.template_id)
        validate_version(self.template_version,positive=True)


@dataclass(frozen=True)
class ReviewRequirementTemplate:
    scope: Scope
    template_id: str
    template_version: int
    purpose: str
    expected_targets: tuple[TemplateTarget,...]
    method_ref: MethodRef
    criterion_set_ref: CriterionSetRef
    required_check_keys: tuple[TemplateCheck,...]
    eligible_reviewer_roles: tuple[str,...]
    phase_key: str
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.method_ref) is not MethodRef or
                type(self.criterion_set_ref) is not CriterionSetRef or type(self.purpose) is not str or self.purpose not in PURPOSES):
            raise ReferenceError('INVALID_SCHEMA')
        validate_id(self.template_id)
        validate_id(self.phase_key)
        validate_version(self.template_version,positive=True)
        validate_items(self.expected_targets,TemplateTarget,nonempty=True)
        validate_items(self.required_check_keys,TemplateCheck,nonempty=True)
        for name in ('expected_targets','required_check_keys'):
            object.__setattr__(self,name,ordered_unique(getattr(self,name),lambda x:canonical_bytes(asdict(x)), code='DUPLICATE_CHECK'))
        if (any(k.target not in self.expected_targets for k in self.required_check_keys) or
                set(k.target for k in self.required_check_keys) != set(self.expected_targets)):
            raise ReferenceError('REVIEW_INCOMPLETE')
        deferred=[t for t in self.expected_targets if t.selector.kind=='result_of_intent']
        if deferred and (self.purpose!='acceptance' or len(deferred)!=len(self.expected_targets)):
            raise ReferenceError('INVALID_REVIEW_SELECTOR')
        validate_items(self.eligible_reviewer_roles,str,nonempty=True)
        for role in self.eligible_reviewer_roles:
            validate_id(role)
        object.__setattr__(self,'eligible_reviewer_roles',ordered_unique(self.eligible_reviewer_roles,lambda x:x, code='DUPLICATE_CHECK'))
        object.__setattr__(self,'digest',record_digest('review-template',payload_fields(self,{'digest'})))

    @property
    def ref(self):
        return ReviewRequirementTemplateRef(self.scope,self.template_id,self.template_version,self.digest)

    @property
    def deferred(self):
        return self.expected_targets[0].selector.kind=='result_of_intent'


def expand_requirement(template, proposal_ref, mutations, claim_refs, resolved_revisions):
    """Pure expansion from exact resolved revisions; no adoption or trust implied.

    Deferred implementation results deliberately cannot use this entrypoint;
    the Submission-specific resolver handles those after owner resolution.
    """
    if type(template) is not ReviewRequirementTemplate or type(proposal_ref) is not ProposalRef:
        raise ReferenceError('INVALID_SCHEMA')
    if template.deferred:
        raise ReferenceError('SUBMISSION_REQUIRED')
    if (proposal_ref.realm_id,proposal_ref.project_id)!=(template.scope.realm_id,template.scope.project_id):
        raise ReferenceError('REALM_MISMATCH')
    def target(value):
        selector=value.selector
        if type(selector) is ExactArtifactRevisionSelector:
            ref=selector.artifact_revision_ref
            revision=resolved_revisions.get(ref)
            if ((ref.realm_id,ref.project_id)!=(template.scope.realm_id,template.scope.project_id)
                    or type(revision) is not ArtifactRevision or revision.ref!=ref
                    or revision.scope!=template.scope):
                raise ReferenceError('UNRESOLVED_REVIEW_TARGET')
        elif selector.kind=='self_proposal':
            ref=proposal_ref
        else:
            sequence=claim_refs if selector.kind=='claim_owner' else mutations
            if selector.index >= len(sequence):
                raise ReferenceError('INVALID_REVIEW_SELECTOR')
            entry=sequence[selector.index]
            ref=(entry.owner_revision_ref if selector.kind=='claim_owner' else
                entry.base_ref if selector.kind=='base_mutation' else entry.proposed_ref)
            if ref is None or type(ref) is not ArtifactRevisionRef or ref not in resolved_revisions:
                raise ReferenceError('UNRESOLVED_REVIEW_TARGET')
        return Target(value.role,ref)
    targets=TargetSet(tuple(dict.fromkeys(target(value) for value in template.expected_targets)))
    checks=[]
    for check in template.required_check_keys:
        resolved=target(check.target)
        if check.claim_id is not None:
            revision=resolved_revisions.get(resolved.ref)
            if revision is None or not any(c.claim_id==check.claim_id for c in revision.claims):
                raise ReferenceError('UNRESOLVED_CLAIM')
            if check.target.selector.kind=='claim_owner' and claim_refs[check.target.selector.index].claim_id!=check.claim_id:
                raise ReferenceError('UNRESOLVED_CLAIM')
        checks.append(CheckKey(resolved,check.criterion_id,check.claim_id))
    identifier=record_digest('expanded-requirement',{'template':asdict(template.ref),'subject':asdict(proposal_ref)}).hex
    return ReviewRequirement(template.scope,'requirement:'+identifier,template.template_version,
        template.purpose,targets,template.method_ref,template.criterion_set_ref,
        tuple(checks),template.eligible_reviewer_roles,template.phase_key)


def expand_submission_requirement(template, submission_ref, implementation_intent_id,
                                  output_refs, resolved_revisions):
    """Expand one frozen acceptance template over every exact result revision.

    This is a pure projection. The caller must resolve the Submission, package,
    intent and revision graph through their original owners before invoking it.
    Blob outputs have no reviewable revision identity and are rejected.
    """
    if (type(template) is not ReviewRequirementTemplate
            or type(submission_ref) is not SubmissionRef
            or type(implementation_intent_id) is not str):
        raise ReferenceError('INVALID_SCHEMA')
    validate_id(implementation_intent_id)
    if not template.deferred or template.purpose != 'acceptance':
        raise ReferenceError('INVALID_REVIEW_SELECTOR')
    if (submission_ref.realm_id, submission_ref.project_id) != (template.scope.realm_id, template.scope.project_id):
        raise ReferenceError('REALM_MISMATCH')
    if any(t.selector.implementation_intent_id != implementation_intent_id
           for t in template.expected_targets):
        raise ReferenceError('IMPLEMENTATION_INTENT_MISMATCH')
    if type(output_refs) is not tuple or not output_refs or len(output_refs) > 4096:
        raise ReferenceError('SUBMISSION_OUTPUT_UNSUPPORTED')
    if any(type(ref) is not ArtifactRevisionRef for ref in output_refs):
        raise ReferenceError('SUBMISSION_OUTPUT_UNSUPPORTED')
    if len(set(output_refs)) != len(output_refs):
        raise ReferenceError('DUPLICATE_REVIEW_TARGET')
    if any((ref.realm_id, ref.project_id) != (template.scope.realm_id, template.scope.project_id)
           for ref in output_refs):
        raise ReferenceError('REALM_MISMATCH')
    if (type(resolved_revisions) is not dict
            or any(type(resolved_revisions.get(ref)) is not ArtifactRevision
                   or resolved_revisions[ref].ref != ref
                   or resolved_revisions[ref].scope != template.scope for ref in output_refs)):
        raise ReferenceError('UNRESOLVED_REVIEW_TARGET')

    targets = tuple(Target(target.role, ref)
                    for target in template.expected_targets for ref in output_refs)
    target_set = TargetSet(tuple(dict.fromkeys(targets)))
    checks = []
    for check in template.required_check_keys:
        for ref in output_refs:
            target = Target(check.target.role, ref)
            checks.append(CheckKey(target, check.criterion_id, check.claim_id))
    identifier = record_digest('expanded-submission-requirement', {
        'template': asdict(template.ref), 'submission': asdict(submission_ref),
        'implementation_intent_id': implementation_intent_id,
    }).hex
    return ReviewRequirement(template.scope, 'requirement:' + identifier,
        template.template_version, 'acceptance', target_set, template.method_ref,
        template.criterion_set_ref, tuple(checks), template.eligible_reviewer_roles,
        template.phase_key)
