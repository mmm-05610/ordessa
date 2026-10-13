"""Pure Proposal validation and bounds; tests do not imply review trust or authority."""
from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.approvals.scope import ActionScope, PathRule, RepositoryScope
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.changes.intent import ImplementationIntentSpec
from ordessa_engineering.domain.changes.models import (
    Change, ChangeSet, Mutation, Proposal, ProposalControl,
)
from ordessa_engineering.domain.changes.operations import validate_change_set, validate_proposal
from ordessa_engineering.domain.changes.result import (Result)
from ordessa_engineering.domain.artifacts.provenance import (Claim, ClaimRef)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.changes.baselines import (RepositorySnapshotRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.models import (CriterionSetRef)
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, ReviewRequirementTemplateRef, SubjectSelector,
    TemplateCheck, TemplateTarget, expand_requirement,
)


SCOPE = Scope("realm-proposal-test", "project-proposal-test")
OTHER_SCOPE = Scope("realm-other", "project-other")
ACTOR = ActorRef("author-1", "human", "synthetic-proposal-test")
CREATED_AT = "2026-10-09T12:00:00.000000Z"
METHOD = MethodRef("engineering-method", "1.0.0", 1, Digest("sha256", "a" * 64))


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _revision(revision_id: str, statement: str, parents=(), *, scope=SCOPE, artifact_id="design-1"):
    raw_value = canonical_bytes(statement)
    claim = Claim("claim-shared", ContentSelector("json_pointer", pointer="/statement"), _digest(raw_value))
    return ArtifactRevision(
        scope, artifact_id, revision_id, CREATED_AT, ACTOR,
        InlinePayload.from_value("application/json", "proposal-test/1", {"statement": statement}),
        tuple(parents), schema_version=2, claims=(claim,),
    )


def _two_claim_revision(revision_id: str, *, scope=SCOPE, artifact_id="design-1"):
    payload = InlinePayload.from_value("application/json", "proposal-test/1", {"statement": "shared"})
    selector = ContentSelector("json_pointer", pointer="/statement")
    statement_digest = _digest(canonical_bytes("shared"))
    return ArtifactRevision(
        scope, artifact_id, revision_id, CREATED_AT, ACTOR, payload, (), schema_version=2,
        claims=(Claim("claim-left", selector, statement_digest),
                Claim("claim-right", selector, statement_digest)),
    )


def _graph(*, second_statement="beta", scope=SCOPE, artifact_id="design-1", head=None):
    base = _revision("rev-1", "alpha", scope=scope, artifact_id=artifact_id)
    proposed = _revision("rev-2", second_statement, (base.ref,), scope=scope, artifact_id=artifact_id)
    artifact = Artifact(scope, artifact_id, "design", CREATED_AT, head_revision_id=head)
    return artifact, base, proposed


def _claim_ref(revision: ArtifactRevision, *, digest=None):
    claim = revision.claims[0]
    return ClaimRef(revision.ref, claim.claim_id, digest or claim.statement_digest)


def _template(*selectors, purpose="quality", template_id="template-1", checks=None):
    targets = tuple(TemplateTarget(role, selector) for role, selector in selectors)
    required = checks or tuple(TemplateCheck(target, f"criterion-{index}",
        "claim-shared" if target.selector.kind == "claim_owner" else None)
        for index, target in enumerate(targets))
    return ReviewRequirementTemplate(
        SCOPE, template_id, 1, purpose, targets, METHOD,
        CriterionSetRef("criteria-1", 1, Digest("sha256", "b" * 64)),
        tuple(required), ("reviewer",), "proposal-review",
    )


def _proposal(*, proposal_id="proposal-1", mutations=None, claim_refs=(), templates=(),
              implementation_intent=None, supersedes_refs=(), scope=SCOPE, change_id="change-1"):
    return Proposal(
        scope, proposal_id, CREATED_AT, ACTOR, change_id, "intent", "rationale",
        tuple(mutations if mutations is not None else ()), (), tuple(claim_refs), (), METHOD,
        tuple(templates), implementation_intent, tuple(supersedes_refs),
    )


def _reject(call, code: str):
    with pytest.raises(ReferenceError) as caught:
        call()
    assert caught.value.code == code


def test_mutations_are_nonempty_unique_and_create_revise_shapes_are_closed():
    artifact, base, proposed = _graph()
    create = Mutation("design-1", "create", None, proposed.ref)
    assert create.base_ref is None
    revise = Mutation("design-1", "revise", base.ref, proposed.ref)
    assert revise.base_ref == base.ref

    _reject(lambda: _proposal(), "INVALID_SCHEMA")
    _reject(lambda: Mutation("design-1", "create", base.ref, proposed.ref), "INVALID_MUTATION")
    _reject(lambda: Mutation("design-1", "revise", None, proposed.ref), "INVALID_MUTATION")
    _reject(lambda: Mutation("other-artifact", "revise", base.ref, proposed.ref), "INVALID_MUTATION")
    _reject(lambda: Mutation("design-1", "revise", base.ref,
        replace(proposed.ref, revision_id=base.ref.revision_id)), "INVALID_MUTATION")
    _reject(lambda: _proposal(mutations=(revise, revise)), "DUPLICATE_MUTATION")
    _reject(lambda: Mutation("design-1", "revise",
        replace(base.ref, realm_id=OTHER_SCOPE.realm_id, project_id=OTHER_SCOPE.project_id), proposed.ref),
        "INVALID_MUTATION")


def test_validation_requires_exact_same_scope_refs_and_base_in_full_ancestry():
    artifact, base, proposed = _graph()
    proposal = _proposal(mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),))
    assert validate_proposal(proposal, (artifact,), (base, proposed)) == ()

    middle = _revision("rev-middle", "middle", (base.ref,))
    tip = _revision("rev-tip", "tip", (middle.ref,))
    transitive = _proposal(mutations=(Mutation("design-1", "revise", base.ref, tip.ref),))
    assert validate_proposal(transitive, (artifact,), (base, middle, tip)) == ()

    _reject(lambda: validate_proposal(proposal, (artifact,), (proposed,)), "UNRESOLVED_MUTATION")
    unrelated = _revision("unrelated", "gamma")
    disconnected = _revision("rev-3", "delta", (unrelated.ref,))
    disconnected_proposal = _proposal(mutations=(Mutation("design-1", "revise", base.ref, disconnected.ref),))
    _reject(lambda: validate_proposal(disconnected_proposal, (artifact,), (base, unrelated, disconnected)),
            "BASE_NOT_ANCESTOR")

    wrong_scope_artifact, wrong_scope_base, wrong_scope_proposed = _graph(scope=OTHER_SCOPE)
    _reject(lambda: validate_proposal(proposal, (wrong_scope_artifact,), (wrong_scope_base, wrong_scope_proposed)),
            "INVALID_RESOLVED_GRAPH")
    adopted = replace(artifact, head_revision_id=base.revision_id)
    create = _proposal(mutations=(Mutation("design-1", "create", None, proposed.ref),))
    _reject(lambda: validate_proposal(create, (adopted,), (base, proposed)), "ARTIFACT_ALREADY_ADOPTED")

    missing_parent_create = _proposal(mutations=(Mutation("design-1", "create", None, proposed.ref),))
    _reject(lambda: validate_proposal(missing_parent_create, (artifact,), (proposed,)), "INVALID_RESOLVED_GRAPH")

    duplicate_a = _revision("duplicate-id", "first")
    duplicate_b = _revision("duplicate-id", "second")
    duplicate_identity = _proposal(mutations=(Mutation("design-1", "create", None, duplicate_a.ref),))
    _reject(lambda: validate_proposal(duplicate_identity, (artifact,), (duplicate_a, duplicate_b)),
            "INVALID_RESOLVED_GRAPH")

    cycle_a = _revision("cycle-a", "cycle-a")
    cycle_b = _revision("cycle-b", "cycle-b")
    # Simulate a corrupt resolved graph after constructing individually valid
    # immutable records: a digest-consistent cycle cannot be authored normally.
    object.__setattr__(cycle_a, "parent_revision_refs", (cycle_b.ref,))
    object.__setattr__(cycle_b, "parent_revision_refs", (cycle_a.ref,))
    cycle_proposal = _proposal(mutations=(Mutation("design-1", "create", None, cycle_a.ref),))
    _reject(lambda: validate_proposal(cycle_proposal, (artifact,), (cycle_a, cycle_b)), "INVALID_RESOLVED_GRAPH")


def test_claim_refs_resolve_exact_revision_and_real_claim_digest():
    artifact, base, proposed = _graph()
    # Same local claim name is legal in different immutable revisions; the exact
    # owner ref and statement digest distinguish the two facts.
    refs = (_claim_ref(base), _claim_ref(proposed))
    proposal = _proposal(
        mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
        claim_refs=refs,
    )
    assert validate_proposal(proposal, (artifact,), (base, proposed)) == ()
    assert proposal.claim_refs == refs

    forged = _claim_ref(proposed, digest=Digest("sha256", "c" * 64))
    bad = _proposal(mutations=proposal.mutations, claim_refs=(refs[0], forged))
    _reject(lambda: validate_proposal(bad, (artifact,), (base, proposed)), "UNRESOLVED_CLAIM")


def test_dense_non_mutation_claim_owner_graph_charges_repeated_parent_visits():
    artifact, base, proposed = _graph()

    # This auxiliary artifact is only the owner of a supplied claim, not a
    # mutation target. Build a bounded 100-node chain, then 101 revisions that
    # each reference the whole completed chain. The graph has only 203 nodes,
    # while its parent edges exceed the 10,000-unit traversal budget.
    owner_nodes = []
    previous = None
    for index in range(100):
        parents = () if previous is None else (previous.ref,)
        previous = _revision(
            f"owner-base-{index:03d}", f"owner-base-{index}", parents,
            artifact_id="claim-owner-graph",
        )
        owner_nodes.append(previous)

    shared_parents = tuple(node.ref for node in owner_nodes)
    dense_nodes = tuple(
        _revision(
            f"owner-dense-{index:03d}", f"owner-dense-{index}", shared_parents,
            artifact_id="claim-owner-graph",
        )
        for index in range(101)
    )
    owner = dense_nodes[-1]
    revisions = (base, proposed, *owner_nodes, *dense_nodes)
    parent_visits = sum(len(revision.parent_revision_refs) for revision in revisions)
    canonical_size = sum(len(canonical_bytes(revision.projection())) for revision in revisions)

    assert len(revisions) < 10_000
    assert parent_visits > 10_000
    assert canonical_size < 64 * 1024 * 1024
    assert sum(len(revision.parent_revision_refs) for revision in (base, proposed)) == 1
    assert owner.ref not in {base.ref, proposed.ref}

    proposal = _proposal(
        mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
        claim_refs=(_claim_ref(owner),),
    )
    _reject(lambda: validate_proposal(proposal, (artifact,), revisions), "ANCESTRY_LIMIT")


def test_mutation_and_claim_indexes_remain_semantic_order_and_affect_digest():
    artifact_a, base_a, proposed_a = _graph(artifact_id="design-a")
    artifact_b, base_b, proposed_b = _graph(artifact_id="design-b")
    mutations = (
        Mutation("design-a", "revise", base_a.ref, proposed_a.ref),
        Mutation("design-b", "revise", base_b.ref, proposed_b.ref),
    )
    claims = (_claim_ref(base_a), _claim_ref(proposed_a), _claim_ref(base_b))
    first = _proposal(mutations=mutations, claim_refs=claims)
    reordered = _proposal(mutations=tuple(reversed(mutations)), claim_refs=tuple(reversed(claims)))
    assert first.mutations == mutations
    assert first.claim_refs == claims
    assert first.digest != reordered.digest


def test_review_template_selectors_expand_only_to_exact_proposal_and_mutation_refs():
    artifact, base, proposed = _graph()
    claim_refs = (_claim_ref(base), _claim_ref(proposed))
    template = _template(
        ("primary", SubjectSelector("self_proposal")),
        ("base", SubjectSelector("base_mutation", 0)),
        ("proposed", SubjectSelector("proposed_mutation", 0)),
        ("support", SubjectSelector("claim_owner", 1)),
    )
    proposal = _proposal(
        mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
        claim_refs=claim_refs, templates=(template,),
    )
    expanded, = validate_proposal(proposal, (artifact,), (base, proposed))
    target_refs = {target.role: target.ref for target in expanded.expected_targets.targets}
    assert target_refs == {
        "primary": proposal.ref,
        "base": base.ref,
        "proposed": proposed.ref,
        "support": proposed.ref,
    }
    claim_checks = [key for key in expanded.required_check_keys if key.claim_id == "claim-shared"]
    assert len(claim_checks) == 1 and claim_checks[0].target.ref == proposed.ref

    _reject(lambda: SubjectSelector("proposed_mutation", True), "INVALID_REVIEW_SELECTOR")
    _reject(lambda: SubjectSelector("claim_owner", -1), "INVALID_REVIEW_SELECTOR")
    out_of_range_template = _template(("primary", SubjectSelector("proposed_mutation", 1)))
    _reject(lambda: _proposal(mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
        templates=(out_of_range_template,)), "INVALID_REVIEW_SELECTOR")
    _reject(lambda: _proposal(mutations=(Mutation("design-1", "create", None, proposed.ref),),
        templates=(_template(("base", SubjectSelector("base_mutation", 0))),)), "INVALID_REVIEW_SELECTOR")


def test_result_of_intent_is_deferred_and_cannot_expand_before_submission():
    target = TemplateTarget("output", SubjectSelector("result_of_intent", implementation_intent_id="intent-1"))
    template = _template(("output", target.selector), purpose="acceptance", template_id="acceptance-1")
    artifact, base, proposed = _graph()
    path_rule = PathRule("packages/engineering", "subtree", ("add", "modify", "delete", "rename"))
    action_scope = ActionScope("project-proposal-test", (RepositoryScope("repo-1", (path_rule,)),), (), (), (), "intent-1")
    baseline = RepositorySnapshotRef(SCOPE.realm_id, SCOPE.project_id, "repo-1", "git", "1" * 40,
                                    Digest("sha256", "d" * 64), None)
    spec = ImplementationIntentSpec("intent-1", ("edit_repository",), action_scope,
                                     (baseline,), (template.ref,), ("keep changes within scope",))
    proposal = _proposal(mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
                         templates=(template,), implementation_intent=spec)
    assert validate_proposal(proposal, (artifact,), (base, proposed)) == ()
    _reject(lambda: expand_requirement(template, proposal.ref, proposal.mutations, (), {}), "SUBMISSION_REQUIRED")

    wrong_ref = ReviewRequirementTemplateRef(SCOPE, "another-template", 1, Digest("sha256", "e" * 64))
    wrong_spec = replace(spec, acceptance_requirement_refs=(wrong_ref,))
    _reject(lambda: _proposal(mutations=proposal.mutations, templates=(template,), implementation_intent=wrong_spec),
            "UNRESOLVED_ACCEPTANCE_TEMPLATE")
    _reject(lambda: _proposal(mutations=proposal.mutations, templates=(template,),
        implementation_intent=replace(spec,acceptance_requirement_refs=())), "UNRESOLVED_ACCEPTANCE_TEMPLATE")
    _reject(lambda: SubjectSelector("result_of_intent", index=0, implementation_intent_id="intent-1"),
            "INVALID_REVIEW_SELECTOR")


def test_claim_owner_selectors_on_one_revision_share_target_but_keep_each_check():
    artifact = Artifact(SCOPE, "design-1", "design", CREATED_AT)
    revision = _two_claim_revision("revision-two-claims")
    claims = tuple(ClaimRef(revision.ref, claim.claim_id, claim.statement_digest) for claim in revision.claims)
    target_a = TemplateTarget("support", SubjectSelector("claim_owner", 0))
    target_b = TemplateTarget("support", SubjectSelector("claim_owner", 1))
    template = _template(
        ("support", target_a.selector), ("support", target_b.selector),
        checks=(TemplateCheck(target_a, "check-left", "claim-left"),
                TemplateCheck(target_b, "check-right", "claim-right")),
    )
    proposal = _proposal(
        mutations=(Mutation("design-1", "create", None, revision.ref),),
        claim_refs=claims, templates=(template,),
    )

    expanded, = validate_proposal(proposal, (artifact,), (revision,))
    assert len(expanded.expected_targets.targets) == 1
    assert expanded.expected_targets.targets[0].role == "support"
    assert expanded.expected_targets.targets[0].ref == revision.ref
    assert len(expanded.required_check_keys) == 2
    assert {check.claim_id for check in expanded.required_check_keys} == {"claim-left", "claim-right"}


def test_change_set_requires_exact_controls_unique_artifact_targets_and_identical_shared_spec():
    artifact_a, base_a, proposed_a = _graph(artifact_id="design-a")
    artifact_b, base_b, proposed_b = _graph(artifact_id="design-b")
    p1 = _proposal(proposal_id="proposal-a", mutations=(Mutation("design-a", "revise", base_a.ref, proposed_a.ref),))
    p2 = _proposal(proposal_id="proposal-b", mutations=(Mutation("design-b", "revise", base_b.ref, proposed_b.ref),))
    controls = (ProposalControl(p1.ref), ProposalControl(p2.ref))
    result = validate_change_set((p1, p2), controls)
    assert result.ok and result.error is None
    change_set = result.value
    assert set(change_set.proposal_refs) == {p1.ref, p2.ref}

    duplicate_target = _proposal(proposal_id="proposal-c", mutations=p1.mutations)
    _reject_result(lambda: validate_change_set((p1, duplicate_target),
        (ProposalControl(p1.ref), ProposalControl(duplicate_target.ref))), "DUPLICATE_MUTATION")
    _reject_result(lambda: validate_change_set((p1, p2), (controls[0],)), "PROPOSAL_CONTROL_REQUIRED")
    withdrawn = ProposalControl(p2.ref, "withdrawn", control_evidence=(Digest("sha256", "f" * 64),), version=1)
    _reject_result(lambda: validate_change_set((p1, p2), (controls[0], withdrawn)), "PROPOSAL_UNAVAILABLE")

    shared = _implementation_spec()
    with_spec_a = _proposal(proposal_id="proposal-a", mutations=p1.mutations, implementation_intent=shared)
    with_spec_b = _proposal(proposal_id="proposal-b", mutations=p2.mutations, implementation_intent=shared)
    assert validate_change_set((with_spec_a, with_spec_b),
        (ProposalControl(with_spec_a.ref), ProposalControl(with_spec_b.ref))).ok
    altered = replace(shared, instruction_constraints=("different bounded instruction",))
    conflict = _proposal(proposal_id="proposal-b", mutations=p2.mutations, implementation_intent=altered)
    _reject_result(lambda: validate_change_set((with_spec_a, conflict),
        (ProposalControl(with_spec_a.ref), ProposalControl(conflict.ref))), "IMPLEMENTATION_INTENT_CONFLICT")


def _reject_result(call, code):
    result = call()
    assert type(result) is Result
    assert not result.ok
    assert result.value is None
    assert result.error.code.value == code


@pytest.mark.parametrize("proposals, controls, code", [
    ([], (), "INVALID_CHANGE_SET"),
    ((), [], "INVALID_CHANGE_SET"),
    ((object(),), (), "INVALID_CHANGE_SET"),
    ((), (), "INVALID_SCHEMA"),
])
def test_change_set_validation_returns_expected_invalid_input_failures(proposals, controls, code):
    _reject_result(lambda: validate_change_set(proposals, controls), code)


def test_change_set_preserves_constructor_error_codes_and_validation_priority():
    _, base, proposed = _graph()
    first = _proposal(mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),))
    _reject_result(lambda: validate_change_set((first, first), ()), "DUPLICATE_PROPOSAL")
    _, other_base, other_proposed = _graph(scope=OTHER_SCOPE)
    other = _proposal(scope=OTHER_SCOPE, proposal_id="other", mutations=(
        Mutation("design-1", "revise", other_base.ref, other_proposed.ref),))
    _reject_result(lambda: validate_change_set((first, other), ()), "REALM_MISMATCH")
    _reject_result(lambda: validate_change_set((first,), (object(),)), "PROPOSAL_CONTROL_REQUIRED")


def test_change_set_does_not_capture_programming_exceptions(monkeypatch):
    from ordessa_engineering.domain.changes import operations

    def broken_constructor(_refs):
        raise RuntimeError("synthetic programmer failure")

    _, base, proposed = _graph()
    proposal = _proposal(mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),))
    monkeypatch.setattr(operations, "ChangeSet", broken_constructor)
    with pytest.raises(RuntimeError, match="synthetic programmer failure"):
        validate_change_set((proposal,), ())


def _implementation_spec():
    rule = PathRule("packages/engineering", "subtree", ("add", "modify", "delete", "rename"))
    scope = ActionScope("project-proposal-test", (RepositoryScope("repo-1", (rule,)),), (), (), (), "intent-1")
    baseline = RepositorySnapshotRef(SCOPE.realm_id, SCOPE.project_id, "repo-1", "git", "1" * 40,
                                    Digest("sha256", "d" * 64), None)
    return ImplementationIntentSpec("intent-1", ("edit_repository",), scope, (baseline,), (), ("bounded",))


def test_supersedes_reference_does_not_mutate_prior_proposal_control_or_change_selection():
    artifact, base, proposed = _graph()
    old = _proposal(proposal_id="proposal-old", mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),))
    old_control = ProposalControl(old.ref)
    new = _proposal(proposal_id="proposal-new", mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
                    supersedes_refs=(old.ref,))
    assert new.supersedes_refs == (old.ref,)
    assert old_control == ProposalControl(old.ref, "available", None, (), 0)

    change = Change(SCOPE, "change-1", CREATED_AT, (old.proposal_id, new.proposal_id), new.proposal_id)
    assert change.selected_proposal_id == new.proposal_id
    assert old_control.disposition == "available" and old_control.version == 0
    _reject(lambda: Change(SCOPE, "change-1", CREATED_AT, (old.proposal_id,), new.proposal_id), "INVALID_SELECTION")
    _reject(lambda: _proposal(proposal_id="proposal-new", mutations=new.mutations,
        supersedes_refs=(replace(old.ref, change_id="other-change"),)), "INVALID_SUPERSEDES_REF")


def test_path_scope_uses_segment_boundaries_exclusions_and_both_rename_paths():
    include = PathRule("packages/engineering", "subtree", ("add", "modify", "delete", "rename"))
    exclude = PathRule("packages/engineering/secrets", "subtree", ("modify", "rename"))
    scope = ActionScope("project-proposal-test", (RepositoryScope("repo-1", (include,)),), (), (), (exclude,), "intent-1")
    assert scope.allows_path("repo-1", "packages/engineering/domain/file.py", "modify")
    assert not scope.allows_path("repo-1", "packages/engineering-old/file.py", "modify")
    assert not scope.allows_path("repo-1", "packages/engineering/secrets/key", "modify")
    assert not scope.allows_path("repo-1", "packages/engineering/domain/file.py", "rename",
                                 destination="packages/engineering/secrets/key")
    assert not scope.allows_path("repo-1", "packages/engineering/secrets/key", "rename",
                                 destination="packages/engineering/domain/file.py")
    assert not scope.allows_path("unknown-repo", "packages/engineering/domain/file.py", "modify")
    _reject(lambda: scope.allows_path("repo-1", "packages/engineering/a", "rename"), "INVALID_ACTION_SCOPE")


def test_implementation_intent_binds_complete_repository_baselines_actions_and_acceptance_templates():
    template = _template(("output", SubjectSelector("result_of_intent", implementation_intent_id="intent-1")),
                         purpose="acceptance", template_id="intent-acceptance")
    spec = _implementation_spec()
    complete = replace(spec, acceptance_requirement_refs=(template.ref,))
    artifact, base, proposed = _graph()
    proposal = _proposal(mutations=(Mutation("design-1", "revise", base.ref, proposed.ref),),
                         templates=(template,), implementation_intent=complete)
    assert proposal.implementation_intent.expected_baselines == spec.expected_baselines
    assert validate_proposal(proposal, (artifact,), (base, proposed)) == ()

    wrong_baseline = replace(spec.expected_baselines[0], repository_id="repo-2")
    _reject(lambda: replace(spec, expected_baselines=(wrong_baseline,)), "INVALID_IMPLEMENTATION_BASELINE")
    second_rule = PathRule("docs/implementation", "subtree", ("add", "modify"))
    second_repository = RepositoryScope("repo-2", (second_rule,))
    two_repo_scope = replace(spec.scope, repository_scopes=(spec.scope.repository_scopes[0], second_repository))
    _reject(lambda: replace(spec, scope=two_repo_scope), "INVALID_IMPLEMENTATION_BASELINE")
    second_baseline = RepositorySnapshotRef(SCOPE.realm_id, SCOPE.project_id, "repo-2", "git", "2" * 40,
                                           Digest("sha256", "9" * 64), None)
    complete_two_repo = replace(spec, scope=two_repo_scope,
                                 expected_baselines=(*spec.expected_baselines, second_baseline))
    assert {ref.repository_id for ref in complete_two_repo.expected_baselines} == {"repo-1", "repo-2"}
    wrong_scope = replace(spec.scope, project_id="another-project")
    _reject(lambda: replace(spec, scope=wrong_scope), "INVALID_IMPLEMENTATION_BASELINE")
    _reject(lambda: _proposal(mutations=proposal.mutations, templates=(template,),
        implementation_intent=replace(spec,acceptance_requirement_refs=())), "UNRESOLVED_ACCEPTANCE_TEMPLATE")
