"""A method document is selectable only through a Proposal's exact frozen target."""
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.proposal_closure import (
    proposal_exact_document_revision_ref,
)
from ordessa_engineering.domain.artifacts.method_binding import (
    ExactMethodResourceRef,
    MethodRef,
)
from ordessa_engineering.domain.artifacts.models import ArtifactRevision, MethodContent, MethodPayload
from ordessa_engineering.domain.changes.models import Mutation, Proposal
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import CriterionSetRef
from ordessa_engineering.domain.reviews.requirements import (
    ExactArtifactRevisionSelector,
    ReviewRequirementTemplate,
    TemplateCheck,
    TemplateTarget,
)


SCOPE = Scope("closure-realm", "closure-project")
METHOD = MethodRef("closure-method", "1.0.0", 1, Digest("sha256", "a" * 64))
ACTOR = ActorRef("closure-author", "human", "closure-test")
SCHEMA_ID = "document.session_summary.schema"
SCHEMA_REF = ExactMethodResourceRef(
    METHOD, "documents/session-summary/schema.json", Digest("sha256", "b" * 64), SCHEMA_ID,
)


def _revision(revision_id, document_type="session-summary", *, scope=SCOPE):
    payload = MethodPayload(
        "application/json", "method-content/1",
        MethodContent.from_value(SCHEMA_REF, {
            "document_type": document_type,
            "schema_version": 1,
            "summary": revision_id,
        }),
    )
    return ArtifactRevision(
        scope, "summary-artifact", revision_id, "2026-10-13T10:00:00.000000Z",
        ACTOR, payload, schema_version=2, method_refs=(METHOD,),
    )


def _proposal(*revisions):
    targets = tuple(TemplateTarget("support", ExactArtifactRevisionSelector(revision.ref))
                    for revision in revisions)
    checks = tuple(TemplateCheck(target, "summary_fidelity") for target in targets)
    template = ReviewRequirementTemplate(
        SCOPE, "frozen-summary", 1, "quality", targets, METHOD,
        CriterionSetRef("summary-criteria", 1, Digest("sha256", "c" * 64)),
        checks, ("reviewer",), "summary-review",
    )
    primary = revisions[0]
    return Proposal(
        SCOPE, "closure-proposal", "2026-10-13T10:00:00.000000Z", ACTOR,
        "closure-change", "review exact summary", "proposal freezes summary revision",
        (Mutation(primary.artifact_id, "create", None, primary.ref),), (), (), (),
        METHOD, (template,),
    )


def test_selects_only_the_unique_matching_revision_frozen_by_proposal():
    frozen = _revision("frozen-summary")
    later_head = _revision("later-head")
    proposal = _proposal(frozen)

    selected = proposal_exact_document_revision_ref(
        proposal, (frozen, later_head), document_type="session-summary",
        schema_resource_ids=(SCHEMA_ID,),
    )

    assert selected == frozen.ref
    assert selected != later_head.ref


def test_missing_or_wrong_scope_revision_is_rejected_without_lookup_fallback():
    frozen = _revision("frozen-summary")
    proposal = _proposal(frozen)
    foreign = _revision("frozen-summary", scope=Scope("other-realm", "other-project"))

    with pytest.raises(ApplicationError, match="METHOD_DOCUMENT_SOURCE_UNAVAILABLE"):
        proposal_exact_document_revision_ref(
            proposal, (), document_type="session-summary", schema_resource_ids=(SCHEMA_ID,),
        )
    with pytest.raises(ApplicationError, match="METHOD_DOCUMENT_SOURCE_UNAVAILABLE"):
        proposal_exact_document_revision_ref(
            proposal, (foreign,), document_type="session-summary", schema_resource_ids=(SCHEMA_ID,),
        )


def test_ambiguous_matching_exact_revisions_are_rejected():
    first = _revision("first-summary")
    second = _revision("second-summary")
    proposal = _proposal(first, second)

    with pytest.raises(ApplicationError, match="METHOD_DOCUMENT_SOURCE_AMBIGUOUS"):
        proposal_exact_document_revision_ref(
            proposal, (first, second), document_type="session-summary",
            schema_resource_ids=(SCHEMA_ID,),
        )


def test_wrong_method_resource_or_document_type_does_not_match():
    frozen = _revision("frozen-summary", document_type="decision-context")
    proposal = _proposal(frozen)

    with pytest.raises(ApplicationError, match="METHOD_DOCUMENT_SOURCE_UNAVAILABLE"):
        proposal_exact_document_revision_ref(
            proposal, (frozen,), document_type="session-summary",
            schema_resource_ids=(SCHEMA_ID,),
        )
    with pytest.raises(ApplicationError, match="METHOD_DOCUMENT_SOURCE_UNAVAILABLE"):
        proposal_exact_document_revision_ref(
            proposal, (frozen,), document_type="decision-context",
            schema_resource_ids=("other.method.schema",),
        )
