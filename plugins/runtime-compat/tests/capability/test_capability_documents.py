"""冻结数据形状的行为合同：构造不变式、排序存储、不可变性与 canonical 序列化。"""
from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from typing import Any, get_args

import pytest

from pacthold_runtime_compat.capability import (
    Condition,
    EnvironmentFact,
    EvidenceRef,
    GrantProvenance,
    MatchContext,
    RequirementParameterSet,
    SandboxDeclaration,
    SandboxDeclarationDocument,
    SandboxGrant,
    SandboxRequirement,
    SupportState,
    canonical_json,
    requirement_set_digest,
)
from pacthold_runtime_compat.capability import CapabilityContractError, EvidenceInvalid


def _evidence(**overrides: Any) -> EvidenceRef:
    fields: dict[str, Any] = {
        "kind": "probe",
        "locator": "provider.py:259",
        "environment_binding": "distro-x/conn-1/opt/hermes",
        "observed_at": 1000,
        "expires_at": 2000,
    }
    fields.update(overrides)
    return EvidenceRef(**fields)


def _requirement(targets: tuple[str, ...]) -> SandboxRequirement:
    return SandboxRequirement(
        capability_id="filesystem.readonly@1",
        parameters=RequirementParameterSet(targets=targets),
        source=_evidence(kind="config-key", locator="deployment.snapshot"),
    )


def test_literal_aliases_are_the_frozen_vocabularies() -> None:
    assert get_args(GrantProvenance) == ("locked-policy",)
    assert get_args(SupportState) == ("supported", "conditional", "unavailable")


class TestEvidenceRefWindow:
    def test_expiry_equal_to_observation_is_accepted(self) -> None:
        ref = _evidence(observed_at=1000, expires_at=1000)
        assert ref.expires_at == 1000

    def test_expiry_after_observation_is_accepted(self) -> None:
        assert _evidence(observed_at=1000, expires_at=2000).observed_at == 1000

    def test_expiry_before_observation_is_typed_rejection(self) -> None:
        with pytest.raises(EvidenceInvalid) as excinfo:
            _evidence(observed_at=2000, expires_at=1000)
        assert isinstance(excinfo.value, CapabilityContractError)

    def test_one_sided_timestamps_need_no_window(self) -> None:
        assert _evidence(observed_at=None).observed_at is None
        assert _evidence(expires_at=None).expires_at is None


class TestSortedStorage:
    def test_expected_facts_sorted_by_pair(self) -> None:
        condition = Condition(
            name="net-inherit", expected_facts=(("b", "2"), ("a", "1")), evidence=()
        )
        assert condition.expected_facts == (("a", "1"), ("b", "2"))

    def test_targets_default_empty_and_sorted(self) -> None:
        assert RequirementParameterSet().targets == ()
        assert RequirementParameterSet(targets=("/w", "/a", "/m")).targets == ("/a", "/m", "/w")

    def test_canonical_json_of_condition_carries_sorted_pairs(self) -> None:
        condition = Condition(
            name="net", expected_facts=(("net", "inherit"), ("user", "ns")), evidence=()
        )
        rendered = canonical_json(condition)
        assert rendered.index('"net"') < rendered.index('"user"')
        assert '"expected_facts":[["net","inherit"],["user","ns"]]' in rendered


class TestImmutability:
    def test_targets_cannot_be_mutated(self) -> None:
        params = RequirementParameterSet(targets=("/a",))
        with pytest.raises(FrozenInstanceError):
            params.targets = ("/b",)  # type: ignore[misc]

    def test_document_fields_cannot_be_mutated(self) -> None:
        document = SandboxDeclarationDocument(
            provider="sandbox-bwrap", revision=1, environment_binding="b", declarations=(),
            digest="0" * 64,
        )
        with pytest.raises(FrozenInstanceError):
            document.revision = 2  # type: ignore[misc]

    def test_tuple_fields_resist_item_assignment(self) -> None:
        params = RequirementParameterSet(targets=("/a",))
        with pytest.raises((TypeError, AttributeError)):
            params.targets[0] = "/b"  # type: ignore[index]


class TestCanonicalJson:
    def test_stable_across_repeated_calls(self) -> None:
        value = {"provider": "p", "revision": 1}
        assert canonical_json(value) == canonical_json(dict(reversed(list(value.items()))))

    def test_key_order_independent_and_compact(self) -> None:
        assert canonical_json({"b": 1, "a": {"d": 2, "c": 3}}) == '{"a":{"c":3,"d":2},"b":1}'

    def test_keeps_non_ascii_verbatim(self) -> None:
        assert "路径" in canonical_json({"locator": "/工作区/路径"})

    def test_dataclass_rendered_as_sorted_object(self) -> None:
        assert canonical_json(RequirementParameterSet(targets=("b", "a"))) == '{"targets":["a","b"]}'

    def test_nested_dataclass_inside_tuple(self) -> None:
        rendered = canonical_json((RequirementParameterSet(targets=("b",)),))
        assert rendered == '[{"targets":["b"]}]'

    def test_match_context_has_no_defaults(self) -> None:
        with pytest.raises(TypeError):
            MatchContext()  # type: ignore[call-arg]
        assert canonical_json(MatchContext(environment_binding="b", now=5)) == '{"environment_binding":"b","now":5}'


class TestRequirementSetDigest:
    def test_stable_for_identical_requirements(self) -> None:
        assert requirement_set_digest((_requirement(("/a", "/b")),)) == \
            requirement_set_digest((_requirement(("/a", "/b")),))

    def test_independent_of_target_construction_order(self) -> None:
        assert requirement_set_digest((_requirement(("/b", "/a")),)) == \
            requirement_set_digest((_requirement(("/a", "/b")),))

    def test_changes_when_requirements_change(self) -> None:
        base = requirement_set_digest((_requirement(("/a",)),))
        assert base != requirement_set_digest((_requirement(("/a", "/c")),))
        assert base != requirement_set_digest(())

    def test_is_sha256_of_canonical_json(self) -> None:
        requirements = (_requirement(("/a",)),)
        expected = hashlib.sha256(canonical_json(requirements).encode("utf-8")).hexdigest()
        digest = requirement_set_digest(requirements)
        assert digest == expected
        assert len(digest) == 64
        assert digest == digest.lower()


class TestDocumentShape:
    def test_full_document_round_trips(self) -> None:
        condition = Condition(name="net", expected_facts=(("net", "inherit"),), evidence=())
        declaration = SandboxDeclaration(
            capability_id="network.inherit@1",
            support_state="conditional",
            condition=condition,
            parameters=RequirementParameterSet(),
            evidence=(_evidence(),),
            provider="sandbox-bwrap",
        )
        grant = SandboxGrant(
            capability_id="filesystem.readonly@1",
            parameters=RequirementParameterSet(targets=("/ro",)),
            provenance="locked-policy",
            source=_evidence(kind="config-key", locator="deployment.grants"),
        )
        document = SandboxDeclarationDocument(
            provider="sandbox-bwrap",
            revision=1,
            environment_binding="distro-x/conn-1/opt/hermes",
            declarations=(declaration,),
            digest="0" * 64,
        )
        assert document.declarations[0].condition is condition
        assert document.declarations[0].support_state == "conditional"
        assert grant.provenance == "locked-policy"
        assert grant.parameters.targets == ("/ro",)

    def test_unavailable_declaration_needs_no_condition(self) -> None:
        declaration = SandboxDeclaration(
            capability_id="network.none@1",
            support_state="unavailable",
            condition=None,
            parameters=None,
            evidence=(),
            provider="sandbox-bwrap",
        )
        assert declaration.condition is None and declaration.parameters is None

    def test_environment_fact_allows_unknown_value(self) -> None:
        fact = EnvironmentFact(key="net.unshared", value=None, evidence=(_evidence(),))
        assert fact.value is None
