"""C1/C2 adapter descriptions and closed capability/verification outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias, Union

from .errors import ContractError, ErrorCode
from .intents import IntentSet, TargetHandle
from .schema import JsonValue, ValueSchema


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
class VersionRange:
    """Inclusive semver tuple bounds; unknown versions are never assumed supported."""

    minimum: tuple[int, int, int]
    maximum: tuple[int, int, int] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.minimum, (tuple, list)) or (self.maximum is not None and not isinstance(self.maximum, (tuple, list))):
            raise ContractError("invalid version bounds")
        object.__setattr__(self, "minimum", tuple(self.minimum))
        if self.maximum is not None:
            object.__setattr__(self, "maximum", tuple(self.maximum))
        if len(self.minimum) != 3 or any(type(n) is not int or n < 0 for n in self.minimum):
            raise ContractError("invalid minimum version")
        if self.maximum is not None and (len(self.maximum) != 3 or any(type(n) is not int or n < 0 for n in self.maximum) or self.maximum < self.minimum):
            raise ContractError("invalid maximum version")

    def contains(self, version: tuple[int, int, int] | None) -> bool | None:
        if version is None:
            return None
        if not isinstance(version, tuple) or len(version) != 3 or any(type(n) is not int or n < 0 for n in version):
            raise ContractError("invalid inspected version")
        return version >= self.minimum and (self.maximum is None or version <= self.maximum)


@dataclass(frozen=True)
class Installation:
    harness_id: str
    native_version: tuple[int, int, int] | None
    adapter_version: tuple[int, int, int]
    evidence_ref: str

    def __post_init__(self) -> None:
        _nonempty(self.harness_id, "harness_id")
        _nonempty(self.evidence_ref, "evidence_ref")
        object.__setattr__(self, "adapter_version", VersionRange(self.adapter_version).minimum)
        if self.native_version is not None:
            object.__setattr__(self, "native_version", VersionRange(self.native_version).minimum)


@dataclass(frozen=True)
class TargetDescriptor:
    handle: TargetHandle
    kind: Literal["file", "directory", "environment"]
    codec: Literal["json", "toml", "yaml", "content", "environment"]
    scope: Literal["instance", "session"]
    allowed_fields: tuple[tuple[str, ...], ...] = ()
    baseline_rules: tuple[Literal["remove-key", "native-default", "restore-owned-baseline"], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.handle, TargetHandle):
            raise ContractError("target descriptor needs TargetHandle")
        if not isinstance(self.allowed_fields, (tuple, list)) or not isinstance(self.baseline_rules, (tuple, list)):
            raise ContractError("invalid target fields or baseline rules")
        if any(not isinstance(path, (tuple, list)) for path in self.allowed_fields):
            raise ContractError("invalid allowed field path")
        object.__setattr__(self, "allowed_fields", tuple(tuple(path) for path in self.allowed_fields))
        object.__setattr__(self, "baseline_rules", tuple(self.baseline_rules))
        if self.kind not in {"file", "directory", "environment"} or self.codec not in {"json", "toml", "yaml", "content", "environment"} or self.scope not in {"instance", "session"}:
            raise ContractError("invalid target kind, codec or scope")
        if self.kind == "environment" and self.codec != "environment":
            raise ContractError("environment target needs environment codec")
        if any(not path or any(not isinstance(part, str) or not part for part in path) for path in self.allowed_fields):
            raise ContractError("invalid allowed field path")
        if len(self.allowed_fields) != len(set(self.allowed_fields)):
            raise ContractError("duplicate allowed field")
        if any(rule not in {"remove-key", "native-default", "restore-owned-baseline"} for rule in self.baseline_rules):
            raise ContractError("invalid baseline rule")


@dataclass(frozen=True)
class ActionDescriptor:
    action_id: str
    schema_version: str
    input_schema: ValueSchema
    result_schema: ValueSchema
    scope: Literal["instance", "session"]
    confirmation: Literal["read-back", "protocol-ack", "restart-resume"]
    compensable: bool

    def __post_init__(self) -> None:
        _nonempty(self.action_id, "action_id")
        _nonempty(self.schema_version, "schema_version")
        if not isinstance(self.input_schema, ValueSchema) or not isinstance(self.result_schema, ValueSchema):
            raise ContractError("action schemas must be ValueSchema")
        if self.scope not in {"instance", "session"} or self.confirmation not in {"read-back", "protocol-ack", "restart-resume"} or type(self.compensable) is not bool:
            raise ContractError("invalid action scope, confirmation or compensability")


@dataclass(frozen=True)
class RuntimeAdapterDescriptor:
    adapter_id: str
    api_version: Literal["v1"]
    harness_id: str
    aliases: tuple[str, ...]
    supported_versions: VersionRange

    def __post_init__(self) -> None:
        if self.api_version != "v1" or not isinstance(self.supported_versions, VersionRange):
            raise ContractError("invalid runtime descriptor")
        _nonempty(self.adapter_id, "adapter_id")
        _nonempty(self.harness_id, "harness_id")
        if not isinstance(self.aliases, (tuple, list)) or any(not isinstance(alias, str) or not alias or alias.strip() != alias for alias in self.aliases):
            raise ContractError("invalid harness alias")
        aliases = tuple(self.aliases)
        folded = [alias.casefold() for alias in aliases]
        if self.harness_id.casefold() in folded or len(folded) != len(set(folded)):
            raise ContractError("duplicate harness alias")
        object.__setattr__(self, "aliases", aliases)


@dataclass(frozen=True)
class FieldClaim:
    target_kind: Literal["file", "directory", "environment"]
    target_id: str
    field_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.field_path, (tuple, list)):
            raise ContractError("invalid claim field path")
        object.__setattr__(self, "field_path", tuple(self.field_path))
        if self.target_kind not in {"file", "directory", "environment"}:
            raise ContractError("invalid claim target kind")
        _nonempty(self.target_id, "target_id")
        if not self.field_path or any(not isinstance(part, str) or not part for part in self.field_path):
            raise ContractError("invalid claim field path")


@dataclass(frozen=True)
class ConfigurationAdapterDescriptor:
    adapter_id: str
    api_version: Literal["v1"]
    facet_id: str
    facet_schema_version: str
    harness_id: str
    native_versions: VersionRange
    adapter_versions: VersionRange
    entries: tuple[str, ...]
    payload_schema: ValueSchema
    claims: tuple[FieldClaim, ...]

    def __post_init__(self) -> None:
        if self.api_version != "v1":
            raise ContractError("invalid configuration descriptor")
        for name in ("adapter_id", "facet_id", "facet_schema_version", "harness_id"):
            _nonempty(getattr(self, name), name)
        if (not isinstance(self.native_versions, VersionRange) or not isinstance(self.adapter_versions, VersionRange)
                or not isinstance(self.payload_schema, ValueSchema)):
            raise ContractError("invalid configuration descriptor member")
        if (not isinstance(self.entries, (tuple, list)) or not self.entries
                or any(not isinstance(entry, str) or not entry or entry.strip() != entry for entry in self.entries)
                or not isinstance(self.claims, (tuple, list))
                or any(not isinstance(claim, FieldClaim) for claim in self.claims)):
            raise ContractError("invalid entry or claim")
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "claims", tuple(self.claims))
        if len(self.entries) != len(set(self.entries)) or len(self.claims) != len(set(self.claims)):
            raise ContractError("duplicate entry or claim")


@dataclass(frozen=True)
class Assessment:
    status: Literal["supported", "unsupported", "unknown"]
    evidence_ref: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"supported", "unsupported", "unknown"}:
            raise ContractError("invalid assessment")
        if self.status != "supported" and not self.reason:
            raise ContractError("unsupported/unknown assessment needs reason")
        if self.evidence_ref is not None:
            _nonempty(self.evidence_ref, "evidence_ref")
        if self.reason is not None:
            _nonempty(self.reason, "reason")


@dataclass(frozen=True)
class Match:
    evidence_ref: str
    kind: Literal["match"] = field(default="match", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.evidence_ref, "evidence_ref")


@dataclass(frozen=True)
class Mismatch:
    reason: str
    kind: Literal["mismatch"] = field(default="mismatch", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.reason, "reason")


@dataclass(frozen=True)
class VerificationUnknown:
    reason: str
    kind: Literal["unknown"] = field(default="unknown", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.reason, "reason")


Verification: TypeAlias = Union[Match, Mismatch, VerificationUnknown]


@dataclass(frozen=True)
class AdapterRefusal:
    code: ErrorCode
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode):
            raise ContractError("invalid adapter refusal code")
        _nonempty(self.reason, "reason")


@dataclass(frozen=True)
class AdapterContext:
    targets: tuple[TargetDescriptor, ...]
    installation: Installation
    entry: str
    scope: Literal["instance", "session"]
    capability_evidence_ref: str

    def __post_init__(self) -> None:
        if (not isinstance(self.targets, (tuple, list))
                or any(not isinstance(target, TargetDescriptor) for target in self.targets)
                or not isinstance(self.installation, Installation)
                or self.scope not in {"instance", "session"}):
            raise ContractError("invalid adapter context")
        _nonempty(self.entry, "entry")
        _nonempty(self.capability_evidence_ref, "capability_evidence_ref")
        object.__setattr__(self, "targets", tuple(self.targets))


@dataclass(frozen=True)
class LaunchRequest:
    target: TargetHandle
    configuration_snapshot_ref: str
    native_session_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetHandle):
            raise ContractError("launch request needs TargetHandle")
        _nonempty(self.configuration_snapshot_ref, "configuration_snapshot_ref")
        if self.native_session_identity is not None:
            _nonempty(self.native_session_identity, "native_session_identity")


@dataclass(frozen=True)
class LaunchPlan:
    target: TargetHandle
    executable_ref: str
    arguments: tuple[str, ...]
    environment_ref: str | None
    configuration_snapshot_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetHandle):
            raise ContractError("launch plan needs TargetHandle")
        _nonempty(self.executable_ref, "executable_ref")
        _nonempty(self.configuration_snapshot_ref, "configuration_snapshot_ref")
        if not isinstance(self.arguments, tuple) or any(not isinstance(arg, str) for arg in self.arguments):
            raise ContractError("launch arguments must be strings")
        if self.environment_ref is not None:
            _nonempty(self.environment_ref, "environment_ref")


@dataclass(frozen=True)
class ResumeRequest:
    instance_ref: str
    expected_native_session_identity: str
    expected_generation: int
    method: Literal["resume"] = field(default="resume", init=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.instance_ref, str) or not self.instance_ref or self.instance_ref.strip() != self.instance_ref
                or not isinstance(self.expected_native_session_identity, str)
                or not self.expected_native_session_identity
                or self.expected_native_session_identity.strip() != self.expected_native_session_identity):
            raise ContractError("resume requires prior instance and native session identity", ErrorCode.RESUME_UNAVAILABLE)
        if type(self.expected_generation) is not int or self.expected_generation < 0:
            raise ContractError("resume requires valid expected generation", ErrorCode.RESUME_UNAVAILABLE)


@dataclass(frozen=True)
class RuntimeConfirmed:
    instance_ref: str
    native_session_identity: str
    runtime_generation: int
    evidence_ref: str
    kind: Literal["confirmed"] = field(default="confirmed", init=False)

    def __post_init__(self) -> None:
        for name in ("instance_ref", "native_session_identity", "evidence_ref"):
            _nonempty(getattr(self, name), name)
        _generation(self.runtime_generation, "runtime_generation")


@dataclass(frozen=True)
class RuntimeRefused:
    code: ErrorCode
    reason: str
    kind: Literal["refused"] = field(default="refused", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode):
            raise ContractError("invalid runtime refusal code")
        _nonempty(self.reason, "reason")


@dataclass(frozen=True)
class RuntimeUnknown:
    instance_ref: str
    observed_effects: tuple[str, ...]
    pending_checks: tuple[str, ...]
    kind: Literal["unknown"] = field(default="unknown", init=False)

    def __post_init__(self) -> None:
        _nonempty(self.instance_ref, "instance_ref")
        object.__setattr__(self, "observed_effects", _string_tuple(self.observed_effects, "observed_effects"))
        object.__setattr__(self, "pending_checks", _string_tuple(self.pending_checks, "pending_checks", required=True))


RuntimeResult: TypeAlias = Union[RuntimeConfirmed, RuntimeRefused, RuntimeUnknown]


@dataclass(frozen=True)
class ReconfigurationDecision:
    mode: Literal["session-local", "reload", "restart-resume", "unsupported"]
    affected_instance_refs: tuple[str, ...]
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"session-local", "reload", "restart-resume", "unsupported"}:
            raise ContractError("unknown reconfiguration mode")
        if self.mode == "unsupported" and not self.reason:
            raise ContractError("unsupported reconfiguration needs reason")
        if not isinstance(self.affected_instance_refs, tuple) or any(not isinstance(item, str) or not item for item in self.affected_instance_refs):
            raise ContractError("invalid affected instances")
        if self.reason is not None:
            _nonempty(self.reason, "reason")


class ConfigurationAdapter(Protocol):
    descriptor: ConfigurationAdapterDescriptor

    def assess(self, context: AdapterContext, request: JsonValue) -> Assessment: ...
    def compile(self, context: AdapterContext, before: JsonValue, desired: JsonValue) -> IntentSet | AdapterRefusal: ...
    def verify(self, context: AdapterContext, observed: JsonValue) -> Verification: ...


class RuntimeAdapter(Protocol):
    descriptor: RuntimeAdapterDescriptor

    def describe_installation(self) -> Installation: ...
    def describe_targets(self) -> tuple[TargetDescriptor, ...]: ...
    def describe_actions(self) -> tuple[ActionDescriptor, ...]: ...
    def prepare_launch(self, request: LaunchRequest) -> LaunchPlan | RuntimeRefused: ...
    def start(self, launch_plan: LaunchPlan) -> RuntimeResult: ...
    def connect(self, instance_ref: str) -> RuntimeResult: ...
    def close(self, instance_ref: str) -> RuntimeResult: ...
    def reconcile(self, instance_ref: str) -> RuntimeResult: ...
    def prepare_reconfiguration(self, plan_id: str) -> ReconfigurationDecision: ...
    def resume(self, request: ResumeRequest) -> RuntimeResult: ...
