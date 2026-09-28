"""需求/授权生成层：per-target demand 形状、去重保序、静态出处、grant 同形与 digest 稳定。"""
from __future__ import annotations

from pacthold_runtime_compat.capability import (
    EvidenceRef,
    MatchContext,
    RequirementParameterSet,
    SandboxDeclaration,
    SandboxDeclarationDocument,
    requirement_set_digest,
)
from pacthold_runtime_compat.capability.match import match_requirements
from pacthold_runtime_compat.capability.requirements import sidecar_grants, sidecar_requirements

BINDING = "distro-x/conn-1/opt/hermes"
NOW = 10_000
CONTEXT = MatchContext(environment_binding=BINDING, now=NOW)
READONLY = "filesystem.readonly@1"
WRITABLE = "filesystem.writable@1"


def _static_evidence() -> EvidenceRef:
    return EvidenceRef(
        kind="config-key", locator="deployment:projection_targets",
        environment_binding=None, observed_at=None, expires_at=None,
    )


def test_empty_faces_yield_an_empty_requirement_set() -> None:
    assert sidecar_requirements(
        executable_targets=(), projection_targets=(), artifact_targets=(), state_target=None
    ) == ()


def test_readonly_demands_are_one_per_unique_target_in_first_occurrence_order() -> None:
    requirements = sidecar_requirements(
        executable_targets=("/exec", "/shared"),
        projection_targets=("/proj",),
        artifact_targets=("/artifact",),
        state_target=None,
    )
    assert [requirement.capability_id for requirement in requirements] == [READONLY] * 4
    assert [requirement.parameters.targets for requirement in requirements] == [
        ("/exec",),
        ("/shared",),
        ("/proj",),
        ("/artifact",),
    ]
    assert [requirement.source.locator for requirement in requirements] == [
        "deployment:executable_targets",
        "deployment:executable_targets",
        "deployment:projection_targets",
        "deployment:artifact_targets",
    ]


def test_duplicate_target_is_claimed_by_the_first_field() -> None:
    requirements = sidecar_requirements(
        executable_targets=("/shared",),
        projection_targets=("/shared",),
        artifact_targets=("/shared",),
        state_target=None,
    )
    assert len(requirements) == 1
    assert requirements[0].parameters.targets == ("/shared",)
    assert requirements[0].source.locator == "deployment:executable_targets"


def test_state_target_appends_a_single_writable_demand() -> None:
    requirements = sidecar_requirements(
        executable_targets=("/exec",),
        projection_targets=(),
        artifact_targets=(),
        state_target="/state",
    )
    assert len(requirements) == 2
    writable = requirements[-1]
    assert writable.capability_id == WRITABLE
    assert writable.parameters.targets == ("/state",)
    assert writable.source.locator == "deployment:state_target"


def test_absent_state_target_yields_no_writable_demand() -> None:
    requirements = sidecar_requirements(
        executable_targets=("/exec",),
        projection_targets=(),
        artifact_targets=(),
        state_target=None,
    )
    assert all(requirement.capability_id == READONLY for requirement in requirements)


def test_every_source_is_static_environment_agnostic_config_key_evidence() -> None:
    requirements = sidecar_requirements(
        executable_targets=("/a",),
        projection_targets=("/b",),
        artifact_targets=("/c",),
        state_target="/s",
    )
    for requirement in requirements:
        source = requirement.source
        assert (source.kind, source.environment_binding, source.observed_at, source.expires_at) == (
            "config-key",
            None,
            None,
            None,
        )
        assert source.locator.startswith("deployment:")


def test_sidecar_grants_mirror_requirements_with_locked_policy_provenance() -> None:
    executable, projection, artifact, state = ("/exec", "/shared"), ("/shared", "/proj"), ("/art",), "/state"
    requirements = sidecar_requirements(
        executable_targets=executable,
        projection_targets=projection,
        artifact_targets=artifact,
        state_target=state,
    )
    grants = sidecar_grants(
        deployment_executable_targets=executable,
        deployment_projection_targets=projection,
        deployment_artifact_targets=artifact,
        deployment_state_target=state,
    )
    # 同形：同 id、同逐 target 展开（跨字段去重）、同出处字段名。
    assert [(grant.capability_id, grant.parameters.targets) for grant in grants] == [
        (requirement.capability_id, requirement.parameters.targets) for requirement in requirements
    ]
    assert [grant.source.locator for grant in grants] == [
        requirement.source.locator for requirement in requirements
    ]
    assert all(grant.provenance == "locked-policy" for grant in grants)
    assert len(grants) == 5  # /shared 去重后 4 条 readonly + 1 条 writable


def test_generated_requirement_digest_is_stable() -> None:
    first = sidecar_requirements(
        executable_targets=("/b", "/a"),
        projection_targets=(),
        artifact_targets=(),
        state_target="/s",
    )
    second = sidecar_requirements(
        executable_targets=("/b", "/a"),
        projection_targets=(),
        artifact_targets=(),
        state_target="/s",
    )
    assert requirement_set_digest(first) == requirement_set_digest(second)


def test_generated_grants_authorize_generated_demands_in_match() -> None:
    requirements = sidecar_requirements(
        executable_targets=("/exec",),
        projection_targets=("/proj",),
        artifact_targets=(),
        state_target="/state",
    )
    grants = sidecar_grants(
        deployment_executable_targets=("/exec",),
        deployment_projection_targets=("/proj",),
        deployment_artifact_targets=(),
        deployment_state_target="/state",
    )
    document = SandboxDeclarationDocument(
        provider="sandbox-bwrap",
        revision=1,
        environment_binding=BINDING,
        declarations=(
            SandboxDeclaration(
                capability_id=READONLY,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(targets=("/exec", "/proj")),
                evidence=(_static_evidence(),),
                provider="sandbox-bwrap",
            ),
            SandboxDeclaration(
                capability_id=WRITABLE,
                support_state="supported",
                condition=None,
                parameters=RequirementParameterSet(targets=("/state",)),
                evidence=(_static_evidence(),),
                provider="sandbox-bwrap",
            ),
        ),
        digest="0" * 64,
    )
    outcome = match_requirements(requirements, grants, document, context=CONTEXT)
    assert outcome.satisfied
