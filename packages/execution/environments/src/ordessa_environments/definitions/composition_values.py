"""Unit composition inputs and attempt facts; no provider implementation."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Sequence
from ordessa_infrastructure.encoding.content_identity import digest
from .runtime_resources import RuntimeHostRef, SandboxRef
from .runtime_ports import SecretMountInput

CONTRACT_ID = "agent-box.runtime-composition@1"

class CompositionError(RuntimeError):
    """Base class for protocol failures."""



class CompositionErrorCode(str, Enum):
    INVALID_BINDING = "INVALID_BINDING"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    AFFINITY_MISMATCH = "AFFINITY_MISMATCH"
    ATTEMPT_REPLAY = "ATTEMPT_REPLAY"
    SPAWN_TOKEN_INVALID = "SPAWN_TOKEN_INVALID"
    START_AMBIGUOUS = "START_AMBIGUOUS"



class CompositionRejected(CompositionError):
    def __init__(self, code: CompositionErrorCode, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}" if detail else code.value)



class RuntimePreparationRejected(ValueError):
    """A deterministic preparation gate rejected before provider effects.

    This is an error classification, never an authorization or replay grant.
    Provider callbacks must not be relabelled with this preparation signal.
    """

    def __init__(self, detail: str, *, code: CompositionErrorCode | None = None) -> None:
        self.code = code
        super().__init__(detail)



class StartAmbiguous(CompositionError):
    code = CompositionErrorCode.START_AMBIGUOUS



@dataclass(frozen=True)
class RuntimeBinding:
    """Frozen exact composition inputs; both refs are mandatory.

    The v1 composition binds one runtime host to one sandbox. The terminal
    session that the retired three-ref binding required is not part of
    composition: the sandbox owns the launched process.
    """

    runtime_host_ref: RuntimeHostRef
    sandbox_ref: SandboxRef

    def __post_init__(self) -> None:
        if not all((self.runtime_host_ref, self.sandbox_ref)):
            raise CompositionRejected(CompositionErrorCode.INVALID_BINDING, "both exact refs are required")



@dataclass(frozen=True)
class PreparedMountSource:
    source_token: str
    content_digest: str
    provenance_digest: str
    authorized_scope: str



@dataclass(frozen=True)
class MountPlan:
    mounts: tuple[tuple[PreparedMountSource, str, str], ...] = ()
    tmpfs_targets: tuple[str, ...] = ()
    plan_digest: str = ""
    secret_mounts: tuple[SecretMountInput, ...] = ()

    @property
    def digest(self) -> str:
        if self.plan_digest:
            return self.plan_digest
        return digest({"mounts": self.mounts, "tmpfs_targets": self.tmpfs_targets,
                       "secret_mounts": tuple((m.credential_ref.provider, m.credential_ref.native_locator,
                                                m.execution_scope, m.guest_target, m.access,
                                                m.materialization_method) for m in self.secret_mounts)})



@dataclass(frozen=True)
class RuntimeBundle:
    host_ref: RuntimeHostRef
    mount_plan: MountPlan
    bundle_digest: str
    staging_tokens: tuple[str, ...] = ()



@dataclass(frozen=True)
class NativeCorrelationSet:
    """Native identities correlated for one v1 composition attempt.

    A terminal identity is not part of the v1 correlation: the launched
    process is owned by the sandbox, and its identity is the process handle's.
    """

    runtime_host_identity: str
    sandbox_identity: str
    harness_identity: str | None = None



@dataclass(frozen=True)
class CompositionPreflightReceipt:
    binding_digest: str
    capability_digest: str
    accepted: bool
    affinity: str
    rejection_code: str | None = None
    #: The semantic capability the refusal is about (`isolation.wrap@1`, ...),
    #: so a rejection says *which* requirement failed, not only that one did.
    rejection_capability: str | None = None



@dataclass(frozen=True)
class CompositionAttemptRecord:
    attempt_key: str
    state: str
    token_consumed: bool = False
    target_creation_count: int = 0
    native_correlation: str | None = None



def attempt_key(*, execution_id: str, dispatch_id: str, ref_digests: Sequence[str], preflight_digest: str, bundle_digest: str, command_digest: str, mount_plan_digest: str) -> str:
    return digest({"execution_id": execution_id, "dispatch_id": dispatch_id, "refs": tuple(ref_digests), "preflight": preflight_digest, "bundle": bundle_digest, "command": command_digest, "mount_plan": mount_plan_digest})
