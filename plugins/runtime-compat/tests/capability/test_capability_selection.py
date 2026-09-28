"""选择层行为合同：pin > incumbent > 稳定字典序、防抢占、整批拒绝与确定性。"""
from __future__ import annotations

from typing import Any

from pacthold_runtime_compat.capability import (
    EvidenceRef,
    MatchContext,
    RequirementParameterSet,
    SandboxDeclaration,
    SandboxDeclarationDocument,
    SandboxGrant,
    SandboxRequirement,
    requirement_set_digest,
)
from pacthold_runtime_compat.capability.errors import (
    REFUSAL_DECLARATION_CONFLICT,
    REFUSAL_DECLARATION_MISSING,
    REFUSAL_PIN_NOT_MATCHED,
    REFUSAL_PROVIDER_NOT_AUTHORIZED,
)
from pacthold_runtime_compat.capability.selection import (
    REASON_INCUMBENT_NOT_MATCHED,
    REASON_SUPERSEDED,
    select_declaration,
)

BINDING = "distro-x/conn-1/opt/hermes"
NOW = 10_000
CONTEXT = MatchContext(environment_binding=BINDING, now=NOW)
READONLY = "filesystem.readonly@1"
REQS = (
    SandboxRequirement(
        capability_id=READONLY,
        parameters=RequirementParameterSet(targets=("/ro",)),
        source=EvidenceRef("config-key", "config:demand", None, None, None),
    ),
)
GRANTS = (
    SandboxGrant(
        capability_id=READONLY,
        parameters=RequirementParameterSet(targets=("/ro",)),
        provenance="locked-policy",
        source=EvidenceRef("config-key", "config:grant", None, None, None),
    ),
)


def _satisfying_document(
    provider: str = "sandbox-bwrap",
    revision: int = 1,
    *,
    declarations: tuple[SandboxDeclaration, ...] | None = None,
) -> SandboxDeclarationDocument:
    if declarations is None:
        declarations = (
            SandboxDeclaration(
                capability_id=READONLY,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(targets=("/ro",)),
                evidence=(EvidenceRef("probe", "exec:1", None, None, None),),
                provider=provider,
            ),
        )
    return SandboxDeclarationDocument(
        provider=provider,
        revision=revision,
        environment_binding=BINDING,
        declarations=declarations,
        digest="0" * 64,
    )


def _broken_document(provider: str, revision: int = 1) -> SandboxDeclarationDocument:
    """声明缺失的文档：任何 demand 都会 DECLARATION_MISSING。"""
    return _satisfying_document(provider, revision, declarations=())


def _select(candidates, **overrides: Any):
    kwargs: dict[str, Any] = {"context": CONTEXT, "binding": "turn-1"}
    kwargs.update(overrides)
    return select_declaration(REQS, GRANTS, (), candidates, **kwargs)


def test_initial_selection_takes_first_satisfied_in_stable_provider_revision_order() -> None:
    c_doc = _satisfying_document("c-sandbox", 2)
    a_doc = _satisfying_document("a-sandbox", 1)
    b_doc = _satisfying_document("b-sandbox", 1)
    record = _select((c_doc, b_doc, a_doc))
    assert record.selected is a_doc
    assert record.outcome is not None and record.outcome.satisfied
    assert record.rejected == (
        ("b-sandbox", 1, REASON_SUPERSEDED),
        ("c-sandbox", 2, REASON_SUPERSEDED),
    )


def test_unsatisfied_candidates_record_their_first_refusal_reason() -> None:
    broken = _broken_document("a-sandbox")
    healthy = _satisfying_document("b-sandbox")
    record = _select((broken, healthy))
    assert record.selected is healthy
    assert record.rejected == (("a-sandbox", 1, REFUSAL_DECLARATION_MISSING),)


def test_duplicate_provider_id_rejects_the_whole_batch() -> None:
    first = _satisfying_document("a-sandbox", 1)
    second = _satisfying_document("a-sandbox", 2)
    record = _select((first, second))
    assert record.selected is None
    assert record.outcome is None
    assert record.rejected == (
        ("a-sandbox", 1, REFUSAL_DECLARATION_CONFLICT),
        ("a-sandbox", 2, REFUSAL_DECLARATION_CONFLICT),
    )


def test_pin_selects_pinned_provider_over_higher_ranked_candidates() -> None:
    a_doc = _satisfying_document("a-sandbox")
    pin_doc = _satisfying_document("pin-sandbox")
    record = _select((a_doc, pin_doc), pinned_provider="pin-sandbox")
    assert record.selected is pin_doc
    assert record.rejected == (("a-sandbox", 1, REASON_SUPERSEDED),)


def test_pin_to_absent_provider_is_pin_not_matched() -> None:
    healthy = _satisfying_document("a-sandbox")
    record = _select((healthy,), pinned_provider="phantom-sandbox")
    assert record.selected is None
    assert record.outcome is None
    assert record.rejected == (("a-sandbox", 1, REFUSAL_PIN_NOT_MATCHED),)


def test_pin_to_failing_candidate_is_pin_not_matched() -> None:
    broken = _broken_document("pinned-sandbox")
    healthy = _satisfying_document("a-sandbox")
    record = _select((broken, healthy), pinned_provider="pinned-sandbox")
    assert record.selected is None
    assert record.outcome is None
    assert record.rejected == (
        ("a-sandbox", 1, REFUSAL_PIN_NOT_MATCHED),
        ("pinned-sandbox", 1, REFUSAL_PIN_NOT_MATCHED),
    )


def test_pin_does_not_bypass_authorization() -> None:
    pinned = _satisfying_document("pinned-sandbox")
    record = _select(
        (pinned,),
        pinned_provider="pinned-sandbox",
        authorized_providers=("other-sandbox",),
    )
    assert record.selected is None
    assert record.outcome is None
    assert record.rejected == (("pinned-sandbox", 1, REFUSAL_PROVIDER_NOT_AUTHORIZED),)


def test_pin_takes_precedence_over_incumbent() -> None:
    incumbent_doc = _satisfying_document("inc-sandbox")
    pin_doc = _satisfying_document("pin-sandbox")
    record = _select(
        (incumbent_doc, pin_doc),
        incumbent_provider="inc-sandbox",
        pinned_provider="pin-sandbox",
    )
    assert record.selected is pin_doc


def test_incumbent_is_selected_over_higher_ranked_candidates() -> None:
    a_doc = _satisfying_document("a-sandbox")
    incumbent = _satisfying_document("z-sandbox")
    record = _select((a_doc, incumbent), incumbent_provider="z-sandbox")
    assert record.selected is incumbent
    assert record.rejected == (("a-sandbox", 1, REASON_SUPERSEDED),)


def test_late_high_ranked_candidate_cannot_displace_incumbent() -> None:
    incumbent = _satisfying_document("m-sandbox")
    baseline = _select((incumbent,), incumbent_provider="m-sandbox")
    assert baseline.selected is incumbent

    later_high_ranked = _satisfying_document("0-ahead-sandbox")
    again = _select((later_high_ranked, incumbent), incumbent_provider="m-sandbox")
    assert again.selected is incumbent
    assert again.outcome == baseline.outcome
    assert again.rejected == (("0-ahead-sandbox", 1, REASON_SUPERSEDED),)


def test_failing_incumbent_rejects_the_whole_batch() -> None:
    broken_incumbent = _broken_document("m-sandbox")
    healthy = _satisfying_document("a-sandbox")
    record = _select((healthy, broken_incumbent), incumbent_provider="m-sandbox")
    assert record.selected is None
    assert record.outcome is None
    assert record.rejected == (
        ("a-sandbox", 1, REASON_INCUMBENT_NOT_MATCHED),
        ("m-sandbox", 1, REASON_INCUMBENT_NOT_MATCHED),
    )


def test_absent_incumbent_rejects_the_whole_batch() -> None:
    healthy = _satisfying_document("a-sandbox")
    record = _select((healthy,), incumbent_provider="gone-sandbox")
    assert record.selected is None
    assert record.rejected == (("a-sandbox", 1, REASON_INCUMBENT_NOT_MATCHED),)


def test_incumbent_must_pass_authorization_too() -> None:
    incumbent = _satisfying_document("inc-sandbox")
    record = _select(
        (incumbent,),
        incumbent_provider="inc-sandbox",
        authorized_providers=("other-sandbox",),
    )
    assert record.selected is None
    assert record.outcome is None
    assert record.rejected == (("inc-sandbox", 1, REFUSAL_PROVIDER_NOT_AUTHORIZED),)


def test_selection_is_deterministic_under_candidate_order_permutation() -> None:
    satisfied_a = _satisfying_document("a-sandbox")
    satisfied_b = _satisfying_document("b-sandbox", 3)
    broken_c = _broken_document("c-sandbox")
    permutations = (
        (satisfied_a, satisfied_b, broken_c),
        (broken_c, satisfied_b, satisfied_a),
        (satisfied_b, satisfied_a, broken_c),
    )
    records = [_select(permutation) for permutation in permutations]
    assert records[0] == records[1] == records[2]
    assert records[0].selected is satisfied_a


def test_record_carries_requirements_digest_and_binding_verbatim() -> None:
    record = _select((_satisfying_document("a-sandbox"),), binding="turn-42")
    assert record.requirements_digest == requirement_set_digest(REQS)
    assert record.binding == "turn-42"


def test_requirements_digest_is_stable_across_selections() -> None:
    first = _select((_satisfying_document("a-sandbox"),), binding="turn-1")
    second = _select((_satisfying_document("a-sandbox"),), binding="turn-1")
    assert first.requirements_digest == second.requirements_digest
    assert first.requirements_digest == requirement_set_digest(REQS)
