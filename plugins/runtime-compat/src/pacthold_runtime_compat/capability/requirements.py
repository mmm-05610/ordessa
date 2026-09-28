"""需求/授权生成：部署派生挂载面 → 冻结 demand/grant 集（两条独立推导路径，A-R2-001）。

demand 只由 launcher 实际将执行的挂载面生成（:func:`sidecar_requirements`）；grant
只由部署文档显式授权字段生成（:func:`sidecar_grants`）。两条路径互不读取，声明文档
与环境观测不参与生成，也不得在此放宽任何一侧。

readonly 面按 target 展开：跨字段去重保序（先出现的字段认领该 target），每个唯一
target 一条单 target 的 demand/grant；``state_target`` 非 None 时追加一条单 target
的 writable demand/grant。每条 source 是静态 config-key 出处（环境无关、无观测时刻、
不过期），locator 指向认领该 target 的部署字段名（``deployment:<字段名>``）。
"""
from __future__ import annotations

from typing import Iterable

from .documents import (
    EvidenceRef,
    RequirementParameterSet,
    SandboxGrant,
    SandboxRequirement,
)

_READONLY_CAPABILITY_ID = "filesystem.readonly@1"
_WRITABLE_CAPABILITY_ID = "filesystem.writable@1"


def _config_key_evidence(field: str) -> EvidenceRef:
    """静态部署字段出处：环境无关、无观测时刻、不过期。"""
    return EvidenceRef(
        kind="config-key",
        locator=f"deployment:{field}",
        environment_binding=None,
        observed_at=None,
        expires_at=None,
    )


def _unique_in_order(targets: Iterable[str]) -> tuple[str, ...]:
    """去重保序：保留首次出现顺序（canonical 路径由部署座位与插件语法校验保证）。"""
    return tuple(dict.fromkeys(targets))


def sidecar_requirements(
    *,
    executable_targets: tuple[str, ...],
    projection_targets: tuple[str, ...],
    artifact_targets: tuple[str, ...],
    state_target: str | None,
) -> tuple[SandboxRequirement, ...]:
    """launcher 实际挂载面 → demand 集：readonly 逐唯一 target，state 目标一条 writable。"""
    requirements: list[SandboxRequirement] = []
    claimed: set[str] = set()
    for field, targets in (
        ("executable_targets", executable_targets),
        ("projection_targets", projection_targets),
        ("artifact_targets", artifact_targets),
    ):
        for target in _unique_in_order(targets):
            if target in claimed:
                continue
            claimed.add(target)
            requirements.append(
                SandboxRequirement(
                    capability_id=_READONLY_CAPABILITY_ID,
                    parameters=RequirementParameterSet(targets=(target,)),
                    source=_config_key_evidence(field),
                )
            )
    if state_target is not None:
        requirements.append(
            SandboxRequirement(
                capability_id=_WRITABLE_CAPABILITY_ID,
                parameters=RequirementParameterSet(targets=(state_target,)),
                source=_config_key_evidence("state_target"),
            )
        )
    return tuple(requirements)


def sidecar_grants(
    *,
    deployment_executable_targets: tuple[str, ...],
    deployment_projection_targets: tuple[str, ...],
    deployment_artifact_targets: tuple[str, ...],
    deployment_state_target: str | None,
) -> tuple[SandboxGrant, ...]:
    """部署文档显式授权字段 → grant 集：与 demand 同形，全部 ``provenance="locked-policy"``。"""
    grants: list[SandboxGrant] = []
    claimed: set[str] = set()
    for field, targets in (
        ("executable_targets", deployment_executable_targets),
        ("projection_targets", deployment_projection_targets),
        ("artifact_targets", deployment_artifact_targets),
    ):
        for target in _unique_in_order(targets):
            if target in claimed:
                continue
            claimed.add(target)
            grants.append(
                SandboxGrant(
                    capability_id=_READONLY_CAPABILITY_ID,
                    parameters=RequirementParameterSet(targets=(target,)),
                    provenance="locked-policy",
                    source=_config_key_evidence(field),
                )
            )
    if deployment_state_target is not None:
        grants.append(
            SandboxGrant(
                capability_id=_WRITABLE_CAPABILITY_ID,
                parameters=RequirementParameterSet(targets=(deployment_state_target,)),
                provenance="locked-policy",
                source=_config_key_evidence("state_target"),
            )
        )
    return tuple(grants)


__all__ = ["sidecar_grants", "sidecar_requirements"]
