"""授权层 fail-closed 行为：缺 grant、超 grant、grant 证据闭合、provider 授权集。"""
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
    REFUSAL_AUTHORIZATION_EXCEEDED,
    REFUSAL_AUTHORIZATION_MISSING,
    REFUSAL_ENVIRONMENT_MISMATCH,
    REFUSAL_EVIDENCE_STALE,
    REFUSAL_PROVIDER_NOT_AUTHORIZED,
)
from pacthold_runtime_compat.capability.match import match_requirements
from pacthold_runtime_compat.capability.selection import select_declaration

BINDING = "distro-x/conn-1/opt/hermes"
OTHER_BINDING = "distro-x/conn-2/opt/other"
NOW = 10_000
CONTEXT = MatchContext(environment_binding=BINDING, now=NOW)
READONLY = "filesystem.readonly@1"


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


def _foreign_evidence() -> EvidenceRef:
    return _static_evidence(environment_binding=OTHER_BINDING)


def _requirement(targets: tuple[str, ...]) -> SandboxRequirement:
    return SandboxRequirement(
        capability_id=READONLY,
        parameters=RequirementParameterSet(targets=targets),
        source=_static_evidence("config:demand"),
    )


def _grant(targets: tuple[str, ...], *, evidence: tuple[EvidenceRef, ...] | None = None) -> SandboxGrant:
    return SandboxGrant(
        capability_id=READONLY,
        parameters=RequirementParameterSet(targets=targets),
        provenance="locked-policy",
        source=_static_evidence("config:grant") if evidence is None else evidence[0],
    )


def _satisfying_document(provider: str = "sandbox-bwrap") -> SandboxDeclarationDocument:
    return SandboxDeclarationDocument(
        provider=provider,
        revision=1,
        environment_binding=BINDING,
        declarations=(
            SandboxDeclaration(
                capability_id=READONLY,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(targets=("/a", "/b")),
                evidence=(_static_evidence(),),
                provider=provider,
            ),
        ),
        digest="0" * 64,
    )


def _match(requirements, grants, document):
    return match_requirements(requirements, grants, document, context=CONTEXT)


def test_demand_without_same_id_grant_is_refused_missing() -> None:
    outcome = _match((_requirement(("/a",)),), (), _satisfying_document())
    assert not outcome.satisfied
    refusal = outcome.refusals[0]
    assert (refusal.reason, refusal.capability_id) == (REFUSAL_AUTHORIZATION_MISSING, READONLY)


def test_demand_exceeding_grant_targets_is_refused_exceeded() -> None:
    outcome = _match(
        (_requirement(("/a", "/b")),), (_grant(("/a",)),), _satisfying_document()
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_AUTHORIZATION_EXCEEDED


def test_covering_grant_authorizes_the_demand() -> None:
    outcome = _match(
        (_requirement(("/a",)),), (_grant(("/a", "/b")),), _satisfying_document()
    )
    assert outcome.satisfied


def test_stale_grant_evidence_is_refused() -> None:
    outcome = _match(
        (_requirement(("/a",)),),
        (_grant(("/a",), evidence=(_stale_evidence(),)),),
        _satisfying_document(),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_EVIDENCE_STALE


def test_grant_evidence_environment_mismatch_is_refused() -> None:
    outcome = _match(
        (_requirement(("/a",)),),
        (_grant(("/a",), evidence=(_foreign_evidence(),)),),
        _satisfying_document(),
    )
    assert not outcome.satisfied
    assert outcome.refusals[0].reason == REFUSAL_ENVIRONMENT_MISMATCH


def test_valid_grant_among_same_id_grants_authorizes_regardless_of_order() -> None:
    requirements = (_requirement(("/a",)),)
    document = _satisfying_document()
    stale_first = ( _grant(("/a",), evidence=(_stale_evidence(),)), _grant(("/a",)) )
    valid_first = tuple(reversed(stale_first))
    assert _match(requirements, stale_first, document).satisfied
    assert _match(requirements, valid_first, document).satisfied


def test_candidate_provider_outside_authorized_set_is_rejected() -> None:
    requirements = (_requirement(("/a",)),)
    grants = (_grant(("/a",)),)
    insider = _satisfying_document(provider="sandbox-bwrap")
    outsider = _satisfying_document(provider="rogue-sandbox")
    record = select_declaration(
        requirements,
        grants,
        (),
        (outsider, insider),
        context=CONTEXT,
        binding="turn-1",
        authorized_providers=("sandbox-bwrap",),
    )
    assert record.selected is insider
    assert record.rejected == (("rogue-sandbox", 1, REFUSAL_PROVIDER_NOT_AUTHORIZED),)


def test_authorized_providers_none_disables_the_filter() -> None:
    requirements = (_requirement(("/a",)),)
    grants = (_grant(("/a",)),)
    outsider = _satisfying_document(provider="rogue-sandbox")
    record = select_declaration(
        requirements, grants, (), (outsider,), context=CONTEXT, binding="turn-1"
    )
    assert record.selected is outsider
    assert record.rejected == ()
