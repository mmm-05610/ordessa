"""G-fake 反例清单（合同 §5）：匹配语义的逐条反例，走真实 seam、不读源码断言。

覆盖：声明缺失/unavailable；conditional verified/failed/unknown；证据过期作用于
声明 evidence / 事实 evidence / 条件 evidence（grant.source 面见
test_capability_authorization.py）；环境绑定不符（文档级与证据级）；环境观测不改写
demand、不放宽 grant；时效边界（expires_at == now 仍有效）。
"""
from __future__ import annotations

from typing import Any

from pacthold_runtime_compat.capability import (
    Condition,
    EnvironmentFact,
    EvidenceRef,
    MatchContext,
    RequirementParameterSet,
    SandboxDeclaration,
    SandboxDeclarationDocument,
    SandboxGrant,
    SandboxRequirement,
)
from pacthold_runtime_compat.capability.errors import (
    REFUSAL_CONDITION_UNSATISFIED,
    REFUSAL_DECLARATION_MISSING,
    REFUSAL_ENVIRONMENT_MISMATCH,
    REFUSAL_EVIDENCE_STALE,
)
from pacthold_runtime_compat.capability.match import match_requirements

BINDING = "distro-x/conn-1/opt/hermes"
OTHER_BINDING = "distro-x/conn-2/opt/other"
NOW = 10_000
CONTEXT = MatchContext(environment_binding=BINDING, now=NOW)
PROVIDER = "sandbox-bwrap"
INHERIT = "network.inherit@1"


def _static_evidence(locator: str = "exec:test:1", **overrides: Any) -> EvidenceRef:
    fields: dict[str, Any] = {
        "kind": "probe",
        "locator": locator,
        "environment_binding": None,
        "observed_at": None,
        "expires_at": None,
    }
    fields.update(overrides)
    return EvidenceRef(**fields)


def _stale_evidence() -> EvidenceRef:
    return _static_evidence(observed_at=NOW - 100, expires_at=NOW - 1)


def _requirement(capability_id: str = INHERIT) -> SandboxRequirement:
    return SandboxRequirement(
        capability_id=capability_id,
        parameters=RequirementParameterSet(),
        source=_static_evidence("config:demand"),
    )


def _grant(capability_id: str = INHERIT) -> SandboxGrant:
    return SandboxGrant(
        capability_id=capability_id,
        parameters=RequirementParameterSet(),
        provenance="locked-policy",
        source=_static_evidence("config:grant"),
    )


def _conditional_declaration(
    *,
    condition: Condition | None,
    evidence: tuple[EvidenceRef, ...] = (),
) -> SandboxDeclaration:
    return SandboxDeclaration(
        capability_id=INHERIT,
        support_state="conditional",
        condition=condition,
        parameters=RequirementParameterSet(),
        evidence=evidence if evidence else (_static_evidence(),),
        provider=PROVIDER,
    )


def _supported_declaration(
    capability_id: str = INHERIT,
    *,
    parameters: RequirementParameterSet | None = None,
    evidence: tuple[EvidenceRef, ...] | None = None,
) -> SandboxDeclaration:
    return SandboxDeclaration(
        capability_id=capability_id,
        support_state="supported",
        condition=None,
        parameters=RequirementParameterSet() if parameters is None else parameters,
        evidence=(_static_evidence(),) if evidence is None else evidence,
        provider=PROVIDER,
    )


def _document(*declarations: SandboxDeclaration, binding: str = BINDING) -> SandboxDeclarationDocument:
    return SandboxDeclarationDocument(
        provider=PROVIDER,
        revision=1,
        environment_binding=binding,
        declarations=tuple(declarations),
        digest="0" * 64,
    )


def _match(requirements, grants, document, facts=()):
    return match_requirements(requirements, grants, document, facts, context=CONTEXT)


_NET_CONDITION = Condition(
    name="net-inherit",
    expected_facts=(("net.mode", "inherit"),),
    evidence=(_static_evidence("probe:net"),),
)


def test_missing_declaration_refuses_the_demand() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(
            SandboxDeclaration(
                capability_id="filesystem.readonly@1",
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(),
                evidence=(_static_evidence(),),
                provider=PROVIDER,
            )
        ),
    )
    assert not outcome.satisfied
    refusal = outcome.refusals[0]
    assert (refusal.reason, refusal.capability_id) == (REFUSAL_DECLARATION_MISSING, INHERIT)


def test_unavailable_declaration_refuses_the_demand() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(
            SandboxDeclaration(
                capability_id=INHERIT,
                support_state="unavailable",
                condition=None,
                parameters=None,
                evidence=(),
                provider=PROVIDER,
            )
        ),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_DECLARATION_MISSING
    assert "unavailable" in outcome.refusals[0].detail


def test_conditional_with_verified_facts_and_valid_evidence_matches() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(_conditional_declaration(condition=_NET_CONDITION)),
        facts=(EnvironmentFact("net.mode", "inherit", (_static_evidence(),)),),
    )
    assert outcome.satisfied
    assert outcome.matches[0].capability_id == INHERIT


def test_conditional_with_contradictory_fact_is_refused_failed() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(_conditional_declaration(condition=_NET_CONDITION)),
        facts=(EnvironmentFact("net.mode", "none", (_static_evidence(),)),),
    )
    assert not outcome.satisfied
    refusal = outcome.refusals[0]
    assert refusal.reason == REFUSAL_CONDITION_UNSATISFIED
    assert refusal.detail == "failed"


def test_conditional_with_missing_or_unknown_fact_is_refused_unknown() -> None:
    requirements = (_requirement(INHERIT),)
    grants = (_grant(INHERIT),)
    document = _document(_conditional_declaration(condition=_NET_CONDITION))

    missing = _match(requirements, grants, document)
    assert not missing.satisfied
    assert missing.refusals[0].reason == REFUSAL_CONDITION_UNSATISFIED
    assert missing.refusals[0].detail == "unknown"

    unknown_value = _match(
        requirements,
        grants,
        document,
        facts=(EnvironmentFact("net.mode", None, (_static_evidence(),)),),
    )
    assert not unknown_value.satisfied
    assert unknown_value.refusals[0].detail == "unknown"


def test_stale_declaration_evidence_refuses_the_demand() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(
            SandboxDeclaration(
                capability_id=INHERIT,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(),
                evidence=(_stale_evidence(),),
                provider=PROVIDER,
            )
        ),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_EVIDENCE_STALE


def test_stale_participating_fact_evidence_refuses_the_demand() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(_conditional_declaration(condition=_NET_CONDITION)),
        # 取值本身命中，但参与求值的事实证据过期 → 闭合失败优先。
        facts=(EnvironmentFact("net.mode", "inherit", (_stale_evidence(),)),),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_EVIDENCE_STALE


def test_stale_condition_evidence_refuses_the_demand() -> None:
    stale_condition = Condition(
        name="net-inherit",
        expected_facts=(("net.mode", "inherit"),),
        evidence=(_stale_evidence(),),
    )
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(_conditional_declaration(condition=stale_condition)),
        facts=(EnvironmentFact("net.mode", "inherit", (_static_evidence(),)),),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_EVIDENCE_STALE


def test_non_participating_fact_evidence_is_not_consulted() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(_conditional_declaration(condition=_NET_CONDITION)),
        facts=(
            EnvironmentFact("net.mode", "inherit", (_static_evidence(),)),
            EnvironmentFact("other.key", "whatever", (_stale_evidence(),)),  # 未参与求值
        ),
    )
    assert outcome.satisfied


def test_expiry_boundary_exactly_at_now_is_still_valid() -> None:
    boundary = _static_evidence(observed_at=NOW - 10, expires_at=NOW)
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(
            SandboxDeclaration(
                capability_id=INHERIT,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(),
                evidence=(boundary,),
                provider=PROVIDER,
            )
        ),
    )
    assert outcome.satisfied


def test_document_environment_binding_mismatch_refuses_whole_document() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(
            SandboxDeclaration(
                capability_id=INHERIT,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(),
                evidence=(_static_evidence(),),
                provider=PROVIDER,
            ),
            binding=OTHER_BINDING,
        ),
    )
    assert not outcome.satisfied
    assert outcome.matches == ()
    refusal = outcome.refusals[0]
    assert (refusal.reason, refusal.capability_id) == (REFUSAL_ENVIRONMENT_MISMATCH, None)


def test_evidence_level_environment_binding_mismatch_refuses_the_demand() -> None:
    outcome = _match(
        (_requirement(INHERIT),),
        (_grant(INHERIT),),
        _document(
            SandboxDeclaration(
                capability_id=INHERIT,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(),
                evidence=(_static_evidence(environment_binding=OTHER_BINDING),),
                provider=PROVIDER,
            )
        ),
    )
    assert not outcome.satisfied
    refusal = outcome.refusals[0]
    assert (refusal.reason, refusal.capability_id) == (REFUSAL_ENVIRONMENT_MISMATCH, INHERIT)


def test_environment_observations_never_rewrite_demand_nor_relax_grants() -> None:
    """同一 demand 分别对照 inherit / none 两个文档，加不加观测结果都必须一致。"""
    demand = _requirement(INHERIT)
    grant = _grant(INHERIT)
    facts = (
        EnvironmentFact("net.unshared", "true", (_static_evidence(),)),
        EnvironmentFact("net.mode", "none", (_static_evidence(),)),
    )
    inherit_document = _document(
        SandboxDeclaration(
            capability_id=INHERIT,
            support_state="supported",
            condition=None,
            parameters=RequirementParameterSet(),
            evidence=(_static_evidence(),),
            provider=PROVIDER,
        )
    )
    none_first_document = _document(
        SandboxDeclaration(
            capability_id="network.none@1",
            support_state="supported",
            condition=None,
            parameters=RequirementParameterSet(),
            evidence=(_static_evidence(),),
            provider=PROVIDER,
        ),
        SandboxDeclaration(
            capability_id=INHERIT,
            support_state="unavailable",
            condition=None,
            parameters=None,
            evidence=(),
            provider=PROVIDER,
        ),
    )

    plain_inherit = _match((demand,), (grant,), inherit_document)
    observed_inherit = _match((demand,), (grant,), inherit_document, facts)
    assert plain_inherit.satisfied and observed_inherit == plain_inherit

    plain_none = _match((demand,), (grant,), none_first_document)
    observed_none = _match((demand,), (grant,), none_first_document, facts)
    assert not plain_none.satisfied and observed_none == plain_none
    assert observed_none.refusals[0].reason == REFUSAL_DECLARATION_MISSING


# ---------------------------------------------------------------------------
# B+C 复审硬化反例（CAP01-BC-002/003）：运行时非法值 fail-closed、空证据不构成证明
# ---------------------------------------------------------------------------

from pacthold_runtime_compat import capability as capability_api  # noqa: E402
from pacthold_runtime_compat.capability.errors import (  # noqa: E402
    REFUSAL_AUTHORIZATION_MISSING,
    REFUSAL_EVIDENCE_ABSENT,
)


def test_grant_with_non_locked_policy_provenance_does_not_authorize() -> None:
    # Literal 注解只在静态检查生效：运行时的非法 provenance 必须 fail-closed。
    invalid_grant = SandboxGrant(
        capability_id=INHERIT,
        parameters=RequirementParameterSet(),
        provenance="profile-default",  # type: ignore[arg-type]
        source=_static_evidence("grant"),
    )
    outcome = _match(
        (_requirement(INHERIT),), (invalid_grant,), _document(_supported_declaration())
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_AUTHORIZATION_MISSING


def test_unknown_support_state_is_refused_and_never_treated_as_supported() -> None:
    baseline = _supported_declaration()
    hostile = SandboxDeclaration(
        capability_id=baseline.capability_id,
        support_state="SUPPORTED",  # type: ignore[arg-type]
        condition=None,
        parameters=baseline.parameters,
        evidence=baseline.evidence,
        provider=PROVIDER,
    )
    outcome = _match((_requirement(INHERIT),), (_grant(INHERIT),), _document(hostile))
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_DECLARATION_MISSING


def test_supported_declaration_without_evidence_is_no_proof() -> None:
    declaration = SandboxDeclaration(
        capability_id=INHERIT,
        support_state="supported",
        condition=None,
        parameters=RequirementParameterSet(),
        evidence=(),
        provider=PROVIDER,
    )
    outcome = _match((_requirement(INHERIT),), (_grant(INHERIT),), _document(declaration))
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_EVIDENCE_ABSENT


def test_conditional_without_evidence_or_facts_can_never_verify() -> None:
    empty_condition = SandboxDeclaration(
        capability_id=INHERIT,
        support_state="conditional",
        condition=Condition(name="empty", expected_facts=(), evidence=()),
        parameters=RequirementParameterSet(),
        evidence=(_static_evidence("decl"),),
        provider=PROVIDER,
    )
    outcome = _match((_requirement(INHERIT),), (_grant(INHERIT),), _document(empty_condition))
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_CONDITION_UNSATISFIED
    assert outcome.refusals[0].detail == "unknown"

    evidenced_condition_but_evidence_empty = SandboxDeclaration(
        capability_id=INHERIT,
        support_state="conditional",
        condition=Condition(
            name="needs-fact", expected_facts=(("net", "inherit"),), evidence=(),
        ),
        parameters=RequirementParameterSet(),
        evidence=(_static_evidence("decl"),),
        provider=PROVIDER,
    )
    outcome = _match(
        (_requirement(INHERIT),), (_grant(INHERIT),),
        _document(evidenced_condition_but_evidence_empty),
        (EnvironmentFact(key="net", value="inherit", evidence=(_static_evidence("fact"),)),),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_EVIDENCE_ABSENT


def test_package_level_api_is_the_public_seam() -> None:
    # B+C 冻结合同要求以 capability.<name> 形式消费：包根入口可独立调用三层。
    requirements = capability_api.sidecar_requirements(
        executable_targets=(), projection_targets=("/proj",), artifact_targets=(),
        state_target=None,
    )
    grants = capability_api.sidecar_grants(
        deployment_executable_targets=(), deployment_projection_targets=("/proj",),
        deployment_artifact_targets=(), deployment_state_target=None,
    )
    readonly_document = _document(_supported_declaration(
        "filesystem.readonly@1",
        parameters=RequirementParameterSet(targets=("/proj",)),
    ))
    outcome = capability_api.match_requirements(
        requirements, grants, readonly_document, context=CONTEXT,
    )
    assert outcome.satisfied, outcome.refusals
    record = capability_api.select_declaration(
        requirements, grants, (), (readonly_document,),
        context=CONTEXT, binding="turn-1",
    )
    assert record.selected is not None
    assert capability_api.REGISTRY["filesystem.readonly@1"].rule == "targets-superset"


def test_supported_declaration_with_condition_is_refused() -> None:
    # 冻结形状：condition 仅在 conditional 时非空；supported+condition 不得绕过条件求值。
    illegal = SandboxDeclaration(
        capability_id=INHERIT,
        support_state="supported",
        condition=Condition(
            name="sneaky", expected_facts=(("net", "inherit"),),
            evidence=(_static_evidence("cond"),),
        ),
        parameters=RequirementParameterSet(),
        evidence=(_static_evidence("decl"),),
        provider=PROVIDER,
    )
    outcome = _match((_requirement(INHERIT),), (_grant(INHERIT),), _document(illegal))
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_DECLARATION_MISSING


def test_conditional_without_parameters_object_is_refused() -> None:
    illegal = SandboxDeclaration(
        capability_id=INHERIT,
        support_state="conditional",
        condition=Condition(
            name="net", expected_facts=(("net", "inherit"),),
            evidence=(_static_evidence("cond"),),
        ),
        parameters=None,
        evidence=(_static_evidence("decl"),),
        provider=PROVIDER,
    )
    outcome = _match(
        (_requirement(INHERIT),), (_grant(INHERIT),), _document(illegal),
        (EnvironmentFact(key="net", value="inherit", evidence=(_static_evidence("fact"),)),),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_DECLARATION_MISSING
