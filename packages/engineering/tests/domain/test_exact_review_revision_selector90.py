"""Exact immutable revision selectors preserve legacy selector bytes."""
from dataclasses import asdict
import hashlib
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.usecases.proposal_closure import proposal_review_revision_refs
from ordessa_engineering.domain.artifacts.models import ArtifactRevision, InlinePayload
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.codec import (
    _template_target,
    decode_proposal,
    encode_proposal,
)
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.models import Mutation, Proposal
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.reviews.models import CheckKey, CriterionSetRef
from ordessa_engineering.domain.reviews.requirements import (
    ExactArtifactRevisionSelector,
    ReviewRequirementTemplate,
    SubjectSelector,
    TemplateCheck,
    TemplateTarget,
    expand_requirement,
)
from ordessa_engineering.domain.reviews.targets import Target


SCOPE = Scope("review-selector-realm", "review-selector-project")
ACTOR = ActorRef("review-selector-author", "human", "review-selector-test")
CREATED_AT = "2026-10-13T10:00:00.000000Z"
METHOD = MethodRef("selector-method", "1.0.0", 1, Digest("sha256", "a" * 64))


def _revision(revision_id="summary-v1", *, scope=SCOPE):
    return ArtifactRevision(
        scope,
        "summary-artifact",
        revision_id,
        CREATED_AT,
        ACTOR,
        InlinePayload.from_value("application/json", "session-summary/1", {"summary": "fixed"}),
        schema_version=1,
    )


def _template(target):
    return ReviewRequirementTemplate(
        SCOPE,
        "exact-summary-review",
        1,
        "quality",
        (target,),
        METHOD,
        CriterionSetRef("summary-criteria", 1, Digest("sha256", "b" * 64)),
        (TemplateCheck(target, "summary_fidelity"),),
        ("reviewer",),
        "summary-review",
    )


def test_exact_revision_wire_is_closed_and_legacy_selector_shape_is_unchanged():
    revision = _revision()
    target = TemplateTarget("support", ExactArtifactRevisionSelector(revision.ref))
    wire = asdict(target)
    assert wire == {
        "role": "support",
        "selector": {
            "artifact_revision_ref": asdict(revision.ref),
            "kind": "exact_artifact_revision",
        },
    }
    assert _template_target(wire) == target

    legacy = SubjectSelector("self_proposal")
    assert asdict(legacy) == {
        "kind": "self_proposal",
        "index": None,
        "implementation_intent_id": None,
        "schema_version": 1,
    }
    legacy_target = TemplateTarget("primary", legacy)
    assert _template_target(asdict(legacy_target)) == legacy_target

    malformed = {**wire, "selector": {**wire["selector"], "index": 0}}
    with pytest.raises(ReferenceError):
        _template_target(malformed)


def test_exact_revision_expansion_requires_the_exact_same_scope_resolved_record():
    revision = _revision()
    target = TemplateTarget("support", ExactArtifactRevisionSelector(revision.ref))
    template = _template(target)
    proposal_ref = ProposalRef(
        SCOPE.realm_id, SCOPE.project_id, "selector-change", "selector-proposal",
        Digest("sha256", "c" * 64),
    )

    expanded = expand_requirement(template, proposal_ref, (), (), {revision.ref: revision})
    expected_target = Target("support", revision.ref)
    assert expanded.expected_targets.targets == (expected_target,)
    assert expanded.required_check_keys == (CheckKey(expected_target, "summary_fidelity"),)

    with pytest.raises(ReferenceError) as missing:
        expand_requirement(template, proposal_ref, (), (), {})
    assert missing.value.code == "UNRESOLVED_REVIEW_TARGET"

    foreign = _revision(scope=Scope("other-review-realm", "other-review-project"))
    foreign_target = TemplateTarget("support", ExactArtifactRevisionSelector(foreign.ref))
    with pytest.raises(ReferenceError) as wrong_scope:
        expand_requirement(_template(foreign_target), proposal_ref, (), (), {foreign.ref: foreign})
    assert wrong_scope.value.code == "UNRESOLVED_REVIEW_TARGET"


def test_exact_selector_roundtrips_inside_real_proposal_and_rejects_foreign_scope():
    revision = _revision()
    target = TemplateTarget("support", ExactArtifactRevisionSelector(revision.ref))
    proposal = Proposal(
        SCOPE, "selector-proposal", CREATED_AT, ACTOR, "selector-change",
        "review an exact summary", "The summary is an immutable review target.",
        (Mutation(revision.artifact_id, "create", None, revision.ref),), (), (), (),
        METHOD, (_template(target),),
    )

    raw = encode_proposal(proposal)
    decoded = decode_proposal(raw)
    assert decoded == proposal
    assert decoded.digest == proposal.digest
    assert encode_proposal(decoded) == raw

    foreign = _revision(scope=Scope("foreign-selector-realm", "foreign-selector-project"))
    with pytest.raises(ReferenceError) as wrong_scope:
        Proposal(
            SCOPE, "foreign-selector-proposal", CREATED_AT, ACTOR, "selector-change",
            "review an exact summary", "The reference belongs to another scope.",
            (Mutation("summary-artifact", "create", None, revision.ref),), (), (), (),
            METHOD, (_template(TemplateTarget("support", ExactArtifactRevisionSelector(foreign.ref))),),
        )
    assert wrong_scope.value.code == "INVALID_REVIEW_SELECTOR"


def test_legacy_proposal_digest_and_bytes_remain_frozen():
    revision = _revision()
    target = TemplateTarget("primary", SubjectSelector("self_proposal"))
    template = ReviewRequirementTemplate(
        SCOPE, "legacy-selector-review", 1, "quality", (target,), METHOD,
        CriterionSetRef("legacy-criteria", 1, Digest("sha256", "b" * 64)),
        (TemplateCheck(target, "proposal_fidelity"),), ("reviewer",), "legacy-review",
    )
    proposal = Proposal(
        SCOPE, "legacy-selector-proposal", CREATED_AT, ACTOR, "selector-change",
        "legacy review", "historical selector fixture",
        (Mutation(revision.artifact_id, "create", None, revision.ref),), (), (), (),
        METHOD, (template,),
    )
    raw = encode_proposal(proposal)
    assert proposal.digest.hex == "ebec1320290effe07f3ecf0976a3c5d2655fcb21984ccfadc578aaf796db4f7c"
    assert hashlib.sha256(raw).hexdigest() == "b2d2075d9c2b6e36a308f969f773c036d83df56829dfa89ab806faac3ae33c0a"
    assert encode_proposal(decode_proposal(raw)) == raw


def test_proposal_closure_root_projection_only_adds_explicit_revision_selectors():
    exact = ExactArtifactRevisionSelector(_revision().ref)
    legacy = SubjectSelector("self_proposal")
    proposal = SimpleNamespace(review_requirement_templates=(
        SimpleNamespace(expected_targets=(
            SimpleNamespace(selector=legacy),
            SimpleNamespace(selector=exact),
            SimpleNamespace(selector=exact),
        )),
    ))
    assert proposal_review_revision_refs(proposal) == (exact.artifact_revision_ref,)
