"""匹配层行为合同：注册表、覆盖语义、逐 demand 判定顺序与 fail-closed 缺省。"""
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
)
from pacthold_runtime_compat.capability.errors import (
    REFUSAL_DECLARATION_CONFLICT,
    REFUSAL_DECLARATION_MISSING,
    REFUSAL_PARAMETER_NOT_COVERED,
    REFUSAL_UNKNOWN_CAPABILITY,
)
from pacthold_runtime_compat.capability.match import (
    REGISTRY,
    MatchedItem,
    match_requirements,
)

BINDING = "distro-x/conn-1/opt/hermes"
NOW = 10_000
CONTEXT = MatchContext(environment_binding=BINDING, now=NOW)
PROVIDER = "sandbox-bwrap"


def _static_evidence(locator: str = "exec:test:1", **overrides: Any):
    fields: dict[str, Any] = {
        "kind": "probe",
        "locator": locator,
        "environment_binding": None,
        "observed_at": None,
        "expires_at": None,
    }
    fields.update(overrides)
    return EvidenceRef(**fields)


def _requirement(capability_id: str, targets: tuple[str, ...] = ()) -> SandboxRequirement:
    return SandboxRequirement(
        capability_id=capability_id,
        parameters=RequirementParameterSet(targets=targets),
        source=_static_evidence("config:demand"),
    )


def _grant(capability_id: str, targets: tuple[str, ...] = ()) -> SandboxGrant:
    return SandboxGrant(
        capability_id=capability_id,
        parameters=RequirementParameterSet(targets=targets),
        provenance="locked-policy",
        source=_static_evidence("config:grant"),
    )


def _declaration(
    capability_id: str,
    *,
    support_state: str = "supported",
    parameters: RequirementParameterSet | None = None,
) -> SandboxDeclaration:
    return SandboxDeclaration(
        capability_id=capability_id,
        support_state=support_state,  # type: ignore[arg-type]
        condition=None,
        parameters=RequirementParameterSet() if parameters is None else parameters,
        evidence=(_static_evidence(),),
        provider=PROVIDER,
    )


def _document(*declarations: SandboxDeclaration) -> SandboxDeclarationDocument:
    return SandboxDeclarationDocument(
        provider=PROVIDER,
        revision=1,
        environment_binding=BINDING,
        declarations=tuple(declarations),
        digest="0" * 64,
    )


def _match(requirements, grants, document):
    return match_requirements(requirements, grants, document, context=CONTEXT)


def test_registry_registers_exactly_the_four_slice_ids() -> None:
    assert set(REGISTRY) == {
        "filesystem.readonly@1",
        "filesystem.writable@1",
        "network.none@1",
        "network.inherit@1",
    }


def test_readonly_demand_covered_by_superset_declaration_matches() -> None:
    document = _document(
        _declaration("filesystem.readonly@1", parameters=RequirementParameterSet(targets=("/ro", "/conf")))
    )
    outcome = _match(
        (_requirement("filesystem.readonly@1", ("/ro",)),),
        (_grant("filesystem.readonly@1", ("/ro",)),),
        document,
    )
    assert outcome.satisfied
    assert outcome.refusals == ()
    assert outcome.matches == (MatchedItem("filesystem.readonly@1", "targets-superset"),)


def test_writable_rule_uses_the_same_superset_semantics() -> None:
    document = _document(
        _declaration("filesystem.writable@1", parameters=RequirementParameterSet(targets=("/state", "/tmp")))
    )
    outcome = _match(
        (_requirement("filesystem.writable@1", ("/state",)),),
        (_grant("filesystem.writable@1", ("/state",)),),
        document,
    )
    assert outcome.satisfied
    assert outcome.matches == (MatchedItem("filesystem.writable@1", "targets-superset"),)


def test_network_enum_rules_require_equal_targets() -> None:
    document = _document(_declaration("network.inherit@1"))

    empty = _match(
        (_requirement("network.inherit@1"),), (_grant("network.inherit@1"),), document
    )
    assert empty.satisfied
    assert empty.matches[0].rule == "targets-equal"

    widened = _match(
        (_requirement("network.inherit@1", ("/net",)),),
        (_grant("network.inherit@1", ("/net",)),),
        document,
    )
    assert not widened.satisfied
    assert widened.refusals[0].reason == REFUSAL_PARAMETER_NOT_COVERED

    crossed = _match(
        (_requirement("network.inherit@1"),),
        (_grant("network.inherit@1"),),
        _document(_declaration("network.none@1")),
    )
    assert not crossed.satisfied
    assert crossed.refusals[0].reason == REFUSAL_DECLARATION_MISSING


def test_unregistered_capability_id_is_refused() -> None:
    outcome = _match((_requirement("env.bounded@1"),), (), _document())
    assert not outcome.satisfied
    assert outcome.matches == ()
    refusal = outcome.refusals[0]
    assert (refusal.reason, refusal.capability_id) == (REFUSAL_UNKNOWN_CAPABILITY, "env.bounded@1")


def test_duplicate_same_id_declarations_are_refused_defensively() -> None:
    document = _document(
        _declaration("filesystem.readonly@1"), _declaration("filesystem.readonly@1")
    )
    outcome = _match(
        (_requirement("filesystem.readonly@1", ("/ro",)),),
        (_grant("filesystem.readonly@1", ("/ro",)),),
        document,
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_DECLARATION_CONFLICT


def test_declaration_targets_not_covering_demand_is_refused() -> None:
    document = _document(
        _declaration("filesystem.readonly@1", parameters=RequirementParameterSet(targets=("/other",)))
    )
    outcome = _match(
        (_requirement("filesystem.readonly@1", ("/ro",)),),
        # grant 覆盖 demand：失败出在声明侧，而非授权侧。
        (_grant("filesystem.readonly@1", ("/ro", "/other")),),
        document,
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_PARAMETER_NOT_COVERED


def test_supported_declaration_without_parameters_is_fail_closed() -> None:
    document = _document(
        SandboxDeclaration(
            capability_id="filesystem.readonly@1",
            support_state="supported",
            condition=None,
            parameters=None,
            evidence=(_static_evidence(),),
            provider=PROVIDER,
        )
    )
    outcome = _match(
        (_requirement("filesystem.readonly@1", ("/ro",)),),
        (_grant("filesystem.readonly@1", ("/ro",)),),
        document,
    )
    assert not outcome.satisfied
    # B+C 复审 R2-002：supported 而 parameters=None 是非法形状（不得静默按空参数集匹配），
    # 按缺失声明 fail-closed 拒绝。
    assert outcome.refusals[0].reason == REFUSAL_DECLARATION_MISSING


def test_each_demand_gets_its_own_verdict_and_ids_without_demands_produce_nothing() -> None:
    document = _document(
        _declaration("filesystem.readonly@1", parameters=RequirementParameterSet(targets=("/ro",))),
        _declaration("network.inherit@1"),
    )
    grants = (
        _grant("filesystem.readonly@1", ("/ro",)),
        _grant("filesystem.readonly@1", ("/uncovered",)),
        _grant("network.inherit@1"),
        _grant("filesystem.writable@1", ("/state",)),  # 无对应 demand：不得产生匹配项
    )
    outcome = _match(
        (
            _requirement("filesystem.readonly@1", ("/ro",)),
            _requirement("network.inherit@1"),
            _requirement("filesystem.readonly@1", ("/uncovered",)),
        ),
        grants,
        document,
    )
    assert outcome.matches == (
        MatchedItem("filesystem.readonly@1", "targets-superset"),
        MatchedItem("network.inherit@1", "targets-equal"),
    )
    assert len(outcome.refusals) == 1
    assert (outcome.refusals[0].reason, outcome.refusals[0].capability_id) == (
        REFUSAL_PARAMETER_NOT_COVERED,
        "filesystem.readonly@1",
    )
    assert not outcome.satisfied


def test_empty_requirements_are_trivially_satisfied() -> None:
    outcome = _match(
        (),
        (_grant("filesystem.readonly@1", ("/ro",)),),
        _document(_declaration("filesystem.readonly@1")),
    )
    assert outcome.satisfied
    assert outcome.matches == () and outcome.refusals == ()
