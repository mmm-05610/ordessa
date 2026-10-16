"""Application proposal-closure coordination.

The adapter implements the reads (``ProposalReadPort``: canonical decode of a
proposal record, revision-graph resolution, artifact-owner selection) and the
writes/CAS. This module owns the closure orchestration and the business
validation: the application calls ``verify_sources`` and the domain
``validate_proposal`` here, on the caller's per-operation budget (same UoW /
readset / content binding).
"""
from __future__ import annotations

from dataclasses import replace

from ..contracts.errors import ApplicationError
from ..contracts.access import proposal_validation_key
from ..contracts.repositories import ProposalReadPort
from .material_closure import verify_sources
from ...domain.changes.operations import validate_proposal
from ...domain.reviews.requirements import ExactArtifactRevisionSelector
from ...domain.artifacts.models import ArtifactRevision, MethodPayload

PROPOSAL_LIMIT = 4096
ANCESTRY_LIMIT = 10000


def proposal_review_revision_refs(proposal):
    """Return explicit review-target revisions in frozen Proposal templates.

    The refs remain subject to the original ProposalReadPort graph resolver and
    proposal validation; this projection does not establish ownership or trust.
    """
    return tuple(dict.fromkeys(
        target.selector.artifact_revision_ref
        for template in proposal.review_requirement_templates
        for target in template.expected_targets
        if type(target.selector) is ExactArtifactRevisionSelector
    ))


def proposal_exact_document_revision_ref(
        proposal, resolved_revisions, *, document_type, schema_resource_ids):
    """Resolve one method-document revision explicitly frozen in a Proposal.

    ``schema_resource_ids`` must come from the guarded method snapshot. The
    candidate set is strictly the Proposal's existing exact template targets;
    this never consults an artifact head, another Work node, or a library scan.
    """
    if (type(document_type) is not str or not document_type
            or type(schema_resource_ids) not in (tuple, frozenset, set)
            or not schema_resource_ids
            or any(type(item) is not str or not item for item in schema_resource_ids)):
        raise ApplicationError('METHOD_DOCUMENT_SOURCE_UNAVAILABLE')
    refs = proposal_review_revision_refs(proposal)
    by_ref = {revision.ref: revision for revision in resolved_revisions
              if type(revision) is ArtifactRevision}
    selected = []
    for ref in refs:
        revision = by_ref.get(ref)
        if revision is None or revision.scope != proposal.scope:
            continue
        payload = revision.payload
        if type(payload) is not MethodPayload:
            continue
        content = payload.content
        schema_ref = content.schema_ref
        if (schema_ref.method_ref != proposal.method_ref
                or schema_ref.resource_id not in schema_resource_ids):
            continue
        value = content.value
        if type(value) is dict and value.get('document_type') == document_type:
            selected.append(ref)
    if not selected:
        raise ApplicationError('METHOD_DOCUMENT_SOURCE_UNAVAILABLE')
    if len(selected) != 1:
        raise ApplicationError('METHOD_DOCUMENT_SOURCE_AMBIGUOUS')
    return selected[0]


def resolve_record(record, reader: ProposalReadPort, budget, *, creating=False):
    """Validate one proposal record against its exact resolved values."""
    if record.implementation_intent is not None:
        # Only an exact baseline in the original same-UoW owner can resolve.
        resolve_baseline = getattr(reader, 'resolve_repository_baseline', None)
        if resolve_baseline is None:
            raise ApplicationError('IMPLEMENTATION_BASELINE_AUTHORITY_UNAVAILABLE')
        for ref in record.implementation_intent.expected_baselines:
            resolve_baseline(ref, budget)
    if record.schema_version == 1:
        verify_sources(record.basis_sources, record.evidence_links, budget)
        budget.method(record.method_ref)
        for template in record.review_requirement_templates:
            budget.method(template.method_ref)
        roots = (tuple(m.proposed_ref for m in record.mutations)
                 + tuple(m.base_ref for m in record.mutations if m.base_ref is not None)
                 + tuple(c.owner_revision_ref for c in record.claim_refs)
                 + proposal_review_revision_refs(record))
    else:
        # Schema-2 SourceChange records are immutable external pins. Historical
        # reads verify their canonical bytes/ref without requiring the external
        # provider or current method publication to remain available. Fresh
        # writes verify those inputs under their explicit demand-side guards.
        roots = ()
    revisions = reader.resolve_revision_graph(roots, budget)
    owners = tuple(reader.select_artifact(record.scope, m.artifact_id) for m in record.mutations)
    if any(owner is None for owner in owners):
        raise ApplicationError('NOT_FOUND')
    # The proposal records a create request, even after a later apply adopts its
    # head. Current head eligibility is checked only while creating/applying.
    if not creating:
        owners = tuple(replace(owner, head_revision_id=None) for owner in owners)
    return validate_proposal(record, owners, revisions)


def coordinate_closure(record, reader: ProposalReadPort, budget, *, creating=False):
    """Walk the supersession closure, validating each record on one budget."""
    pending = [record]
    seen = set()
    validated = {}
    edges = 0
    requirements = ()
    while pending:
        value = pending.pop()
        if value.ref in seen:
            continue
        seen.add(value.ref)
        if len(seen) > PROPOSAL_LIMIT:
            raise ApplicationError('PROPOSAL_LIMIT')
        current = resolve_record(value, reader, budget, creating=creating and value.ref == record.ref)
        if value.ref == record.ref:
            requirements = current
        validated[value.ref] = value
        edges += len(value.supersedes_refs)
        if edges > ANCESTRY_LIMIT:
            raise ApplicationError('PROPOSAL_LIMIT')
        pending.extend(reader.read_proposal(ref, budget) for ref in value.supersedes_refs)
    return requirements, validated


def validate_create(record, reader: ProposalReadPort, budget):
    """Application-triggered create validation; binds the result on the budget.

    Marks the budget and binds the returned requirements under the same
    per-operation key, so ``create_proposal`` can consume exactly the validated
    result instead of an arbitrary argument.
    """
    requirements, _ = coordinate_closure(record, reader, budget, creating=True)
    key = proposal_validation_key(record)
    budget.mark_validated(key)
    budget.bind_validated_result(key, requirements)
    return requirements


__all__ = ['proposal_review_revision_refs', 'proposal_exact_document_revision_ref',
           'resolve_record', 'coordinate_closure', 'validate_create']
