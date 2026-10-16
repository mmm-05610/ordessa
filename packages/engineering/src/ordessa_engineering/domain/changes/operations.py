"""Proposal validation consumes exact resolved values; it never applies heads."""
from ordessa_engineering.domain.changes.errors import (DomainError, from_reference_error)
from ordessa_engineering.domain.changes.errors import (DomainErrorCode)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.changes.result import (Result)
from ordessa_infrastructure.encoding import canonical_bytes
from ..artifacts.models import ARTIFACT_KINDS, Artifact, ArtifactRevision
from ..reviews.requirements import expand_requirement
from .models import Proposal, ProposalControl, ChangeSet


def validate_proposal(proposal, artifacts, revisions):
    if type(proposal) is not Proposal or type(artifacts) is not tuple or type(revisions) is not tuple:
        raise ReferenceError('INVALID_PROPOSAL')
    if (len(artifacts)>4096 or len(revisions)>10000 or any(type(a) is not Artifact or a.scope!=proposal.scope for a in artifacts)
            or any(type(r) is not ArtifactRevision or r.scope!=proposal.scope for r in revisions)):
        raise ReferenceError('INVALID_RESOLVED_GRAPH')
    owners={a.artifact_id:a for a in artifacts}
    graph={r.ref:r for r in revisions}
    if len(owners)!=len(artifacts) or len({(r.artifact_id,r.revision_id) for r in revisions})!=len(revisions):
        raise ReferenceError('INVALID_RESOLVED_GRAPH')
    if sum(len(canonical_bytes(r.projection())) for r in revisions)>64*1024*1024:
        raise ReferenceError('ANCESTRY_LIMIT')
    # All supplied nodes, including non-mutation claim owners, are a closed DAG.
    completed=set()
    active=set()
    edges=0
    for root in graph:
        stack=[(root,False)]
        while stack:
            ref,leaving=stack.pop()
            if leaving:
                active.remove(ref)
                completed.add(ref)
                continue
            # Count every traversed reference, including cached nodes. A dense
            # supplied graph must not evade the work bound through deduplication.
            edges+=1
            if edges>10000:
                raise ReferenceError('ANCESTRY_LIMIT')
            if ref in active:
                raise ReferenceError('INVALID_RESOLVED_GRAPH')
            if ref in completed:
                continue
            if ref not in graph:
                # Missing a declared mutation base has its stable dedicated code.
                if any(m.base_ref==ref for m in proposal.mutations):
                    raise ReferenceError('UNRESOLVED_MUTATION')
                raise ReferenceError('INVALID_RESOLVED_GRAPH')
            active.add(ref)
            stack.append((ref,True))
            stack.extend((p,False) for p in graph[ref].parent_revision_refs)
    ancestry_work=0
    for mutation in proposal.mutations:
        if mutation.artifact_id not in owners or mutation.proposed_ref not in graph:
            raise ReferenceError('UNRESOLVED_MUTATION')
        if owners[mutation.artifact_id].kind not in ARTIFACT_KINDS:
            raise ReferenceError('UNSUPPORTED_ARTIFACT_KIND')
        if mutation.operation=='revise' and mutation.base_ref not in graph:
            raise ReferenceError('UNRESOLVED_MUTATION')
        seen=set()
        visiting=set()
        stack=[(mutation.proposed_ref,False)]
        while stack:
            ref,leaving=stack.pop()
            if leaving:
                visiting.remove(ref)
                seen.add(ref)
                continue
            ancestry_work+=1
            if ancestry_work>10000:
                raise ReferenceError('ANCESTRY_LIMIT')
            if ref in visiting:
                raise ReferenceError('INVALID_RESOLVED_GRAPH')
            if ref in seen:
                continue
            if ref not in graph:
                raise ReferenceError('INVALID_RESOLVED_GRAPH')
            visiting.add(ref)
            stack.append((ref,True))
            stack.extend((p,False) for p in graph[ref].parent_revision_refs)
        if mutation.operation=='create':
            if owners[mutation.artifact_id].head_revision_id is not None:
                raise ReferenceError('ARTIFACT_ALREADY_ADOPTED')
        else:
            if mutation.base_ref not in seen:
                raise ReferenceError('BASE_NOT_ANCESTOR')
    for ref in proposal.claim_refs:
        revision=graph.get(ref.owner_revision_ref)
        if revision is None or not any(c.claim_id==ref.claim_id and c.statement_digest==ref.statement_digest for c in revision.claims):
            raise ReferenceError('UNRESOLVED_CLAIM')
    return tuple(expand_requirement(t,proposal.ref,proposal.mutations,proposal.claim_refs,graph)
                 for t in proposal.review_requirement_templates if not t.deferred)


def validate_change_set(proposals: tuple[Proposal, ...],
                        controls: tuple[ProposalControl, ...]) -> Result[ChangeSet, DomainError]:
    """Return anticipated validation refusals; constructors remain strict.

    All values are supplied by the caller. This operation neither resolves data
    nor evaluates authorization, and it does not catch programming exceptions.
    """
    if type(proposals) is not tuple or type(controls) is not tuple or any(type(p) is not Proposal for p in proposals):
        return Result.failure(DomainError(DomainErrorCode.INVALID_CHANGE_SET))
    try:
        change_set=ChangeSet(tuple(p.ref for p in proposals))
    except ReferenceError as refusal:
        return Result.failure(from_reference_error(refusal))
    if len(controls)!=len(proposals) or any(type(c) is not ProposalControl for c in controls):
        return Result.failure(DomainError(DomainErrorCode.PROPOSAL_CONTROL_REQUIRED))
    control_map={c.proposal_ref:c for c in controls}
    if len(control_map)!=len(controls) or set(control_map)!=set(change_set.proposal_refs):
        return Result.failure(DomainError(DomainErrorCode.PROPOSAL_CONTROL_REQUIRED))
    if any(c.disposition!='available' for c in controls):
        return Result.failure(DomainError(DomainErrorCode.PROPOSAL_UNAVAILABLE))
    artifacts=[m.artifact_id for p in proposals for m in p.mutations]
    if len(artifacts)!=len(set(artifacts)):
        return Result.failure(DomainError(DomainErrorCode.DUPLICATE_MUTATION))
    specs=[p.implementation_intent for p in proposals if p.implementation_intent is not None]
    if specs and any(spec!=specs[0] for spec in specs):
        return Result.failure(DomainError(DomainErrorCode.IMPLEMENTATION_INTENT_CONFLICT))
    return Result.success(change_set)
