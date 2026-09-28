"""C4 application port DTOs. Authorization and permit minting stay with the host."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias, Union

from .errors import ContractError, ErrorCode
from .schema import JsonValue, _JsonSnapshotField


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContractError(f"invalid {name}")


def _generation(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ContractError(f"invalid {name}")


def _string_tuple(value: object, name: str, *, required: bool = False) -> tuple[str, ...]:
    if (not isinstance(value, (tuple, list)) or (required and not value)
            or any(not isinstance(item, str) or not item or item.strip() != item for item in value)):
        raise ContractError(f"invalid {name}")
    return tuple(value)


@dataclass(frozen=True)
class ApplicationTarget:
    server_id: str
    session_id: str
    channel_id: str
    runtime_generation: int

    def __post_init__(self) -> None:
        for name in ("server_id", "session_id", "channel_id"):
            _nonempty(getattr(self, name), name)
        _generation(self.runtime_generation, "runtime_generation")


@dataclass(frozen=True)
class DesiredFragment(_JsonSnapshotField):
    _snapshot_field = "value"
    facet_id: str
    item_id: str
    schema_version: str
    business_ref: str
    source_revision: str
    operation: Literal["set", "reset"]
    value: JsonValue = None

    def __post_init__(self) -> None:
        for name in ("facet_id", "item_id", "schema_version", "business_ref", "source_revision"):
            _nonempty(getattr(self, name), name)
        if self.operation not in {"set", "reset"}:
            raise ContractError("unknown fragment operation")
        if self.operation == "reset" and self.value is not None:
            raise ContractError("reset cannot carry a value")
        self._seal_json_field()


@dataclass(frozen=True)
class ConfigurationCapability:
    facet_id: str
    harness_id: str
    native_version: tuple[int, int, int] | None
    adapter_version: tuple[int, int, int] | None
    entry: str
    scope: Literal["instance", "session"]
    operation: Literal["set", "reset", "content", "secret", "action"]
    status: Literal["supported", "unsupported", "unknown"]
    evidence_ref: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("facet_id", "harness_id", "entry"):
            _nonempty(getattr(self, name), name)
        if self.scope not in {"instance", "session"} or self.operation not in {"set", "reset", "content", "secret", "action"}:
            raise ContractError("invalid capability scope or operation")
        if self.status not in {"supported", "unsupported", "unknown"} or (self.status != "supported" and not self.reason):
            raise ContractError("capability status/reason invalid")
        if self.evidence_ref is not None:
            _nonempty(self.evidence_ref, "evidence_ref")
        if self.reason is not None:
            _nonempty(self.reason, "reason")
        for name in ("native_version", "adapter_version"):
            version = getattr(self, name)
            if version is not None:
                if (not isinstance(version, (tuple, list)) or len(version) != 3
                        or any(type(part) is not int or part < 0 for part in version)):
                    raise ContractError(f"invalid {name}")
                object.__setattr__(self, name, tuple(version))


@dataclass(frozen=True)
class ConfigurationCapabilities:
    target: ApplicationTarget
    capabilities: tuple[ConfigurationCapability, ...]

    def __post_init__(self) -> None:
        if (not isinstance(self.target, ApplicationTarget)
                or not isinstance(self.capabilities, (tuple, list))
                or any(not isinstance(item, ConfigurationCapability) for item in self.capabilities)):
            raise ContractError("invalid configuration capabilities")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True)
class Plan:
    plan_id: str
    target: ApplicationTarget
    desired_digest: str
    before_revision: str
    native_version_ref: str
    provider_generation: int
    authorization_revision: str
    secret_ref_revision: str
    expires_at_utc: str
    kind: Literal["plan"] = field(default="plan", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.target, ApplicationTarget):
            raise ContractError("plan needs ApplicationTarget")
        for name in ("plan_id", "desired_digest", "before_revision", "native_version_ref", "authorization_revision", "secret_ref_revision", "expires_at_utc"):
            _nonempty(getattr(self, name), name)
        _generation(self.provider_generation, "provider_generation")


@dataclass(frozen=True)
class Refused:
    code: ErrorCode
    diagnostics: tuple[str, ...]
    original_state_preserved: bool
    operation_id: str | None = None
    kind: Literal["refused"] = field(default="refused", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode) or type(self.original_state_preserved) is not bool:
            raise ContractError("invalid refusal code or preservation status")
        object.__setattr__(self, "diagnostics", _string_tuple(self.diagnostics, "refusal diagnostics"))
        if self.operation_id is not None:
            _nonempty(self.operation_id, "operation_id")


@dataclass(frozen=True)
class Confirmed:
    operation_id: str
    applied_revision: str
    native_session_identity: str
    runtime_generation: int
    verification_evidence_ref: str
    resource_changes: tuple[str, ...]
    kind: Literal["confirmed"] = field(default="confirmed", init=False)

    def __post_init__(self) -> None:
        for name in ("operation_id", "applied_revision", "native_session_identity", "verification_evidence_ref"):
            _nonempty(getattr(self, name), name)
        _generation(self.runtime_generation, "runtime_generation")
        object.__setattr__(self, "resource_changes", _string_tuple(self.resource_changes, "resource changes"))


@dataclass(frozen=True)
class Unknown:
    operation_id: str
    phase: Literal["applying", "verifying", "reconciling", "submission"]
    observed_effects: tuple[str, ...]
    pending_checks: tuple[str, ...]
    allowed_next_action: Literal["query", "reconcile", "operator-review"]
    kind: Literal["unknown"] = field(default="unknown", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.operation_id, "operation_id")
        if self.phase not in {"applying", "verifying", "reconciling", "submission"} or self.allowed_next_action not in {"query", "reconcile", "operator-review"}:
            raise ContractError("invalid unknown phase or next action")
        object.__setattr__(self, "observed_effects", _string_tuple(self.observed_effects, "observed effects"))
        object.__setattr__(self, "pending_checks", _string_tuple(self.pending_checks, "pending checks", required=True))


ApplicationResult: TypeAlias = Union[Confirmed, Refused, Unknown]
PlanResult: TypeAlias = Union[Plan, Refused]


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    operation_key: str
    target: ApplicationTarget
    result: ApplicationResult

    def __post_init__(self) -> None:
        if not isinstance(self.target, ApplicationTarget):
            raise ContractError("operation record needs ApplicationTarget")
        _nonempty(self.operation_id, "operation_id")
        _nonempty(self.operation_key, "operation_key")
        if not isinstance(self.result, (Confirmed, Refused, Unknown)):
            raise ContractError("invalid operation result")
        if self.result.operation_id is not None and self.result.operation_id != self.operation_id:
            raise ContractError("operation identity mismatch")


@dataclass(frozen=True)
class NotFound:
    operation_key: str
    kind: Literal["not-found"] = field(default="not-found", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.operation_key, "operation_key")


class ConfigurationService(Protocol):
    def inspect(self, target: ApplicationTarget) -> ConfigurationCapabilities: ...
    def plan(self, target: ApplicationTarget, desired_fragments: tuple[DesiredFragment, ...], expected_revision: str) -> PlanResult: ...
    def apply(self, plan_id: str, operation_key: str, submission_permit: str) -> ApplicationResult: ...
    def query(self, operation_key: str) -> OperationRecord | NotFound: ...
    def reconcile(self, operation_key: str) -> ApplicationResult: ...
