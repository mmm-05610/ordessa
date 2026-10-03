"""`NativeSandboxIntent`: what an OS/process-level native sandbox must reach.

Brand schemas are closed vocabularies measured from this tree (Codex modes
from ``posture_config._SANDBOX_STRICTNESS``; the bridge ``ProfileConfig``
``Sandbox`` field; Claude's Bash/PowerShell/Monitor sandbox per the official
limits collected in research-and-reuse.md; Pi has no built-in brand config at
all — it is extension-backed, so an absent extension is an explicit
unsupported refusal). This is NOT the Pacthold neutral execution resource.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .coverage import ToolCategory, parse_coverage
from .errors import SandboxApiError, SandboxErrorCode


class NetworkMode(str, Enum):
    DISABLED = "disabled"
    ALLOWED = "allowed"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class SandboxApplyScope(str, Enum):
    #: data-model.md "scope (request/session/process/project/user)": a
    #: PROCESS-scope native change can touch co-resident sessions.
    REQUEST = "request"
    SESSION = "session"
    PROJECT = "project"
    PROCESS = "process"
    USER = "user"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


@dataclass(frozen=True)
class PlatformGate:
    allowed_os: tuple[str, ...] = ()


def _refuse(message: str, code: SandboxErrorCode = SandboxErrorCode.SANDBOX_INTENT_INVALID,
            suggestion: str | None = None) -> SandboxApiError:
    return SandboxApiError(code, message, suggestion=suggestion)


def _validate_paths(paths: Any, name: str) -> tuple[str, ...]:
    if isinstance(paths, str) or not isinstance(paths, (list, tuple)):
        raise _refuse(f"{name} must be a list of explicit scope tokens")
    out: list[str] = []
    for entry in paths:
        text = str(entry)
        if text in ("*", "all", "**", "/"):
            raise _refuse(
                f"{name} carries wildcard {entry!r}; a wildcard scope cannot "
                "be probed and is never accepted",
                suggestion="name each scope token explicitly")
        out.append(text)
    return tuple(out)


# ------------------------------------------------------------- brand schemas

@dataclass(frozen=True)
class CodexSandboxConfig:
    #: Values measured from `posture_config._SANDBOX_STRICTNESS` keys;
    #: higher number is stricter.
    STRICTNESS = {"read-only": 3, "workspace-write": 2, "danger-full-access": 1}
    MAX_STRICTNESS = 3
    COVERABLE = frozenset({ToolCategory.BASH, ToolCategory.READ,
                           ToolCategory.EDIT, ToolCategory.NETWORK})

    sandbox_mode: str
    writable_roots: tuple[str, ...] = ()
    network_access: bool = False

    def __post_init__(self) -> None:
        if self.sandbox_mode not in self.STRICTNESS:
            raise _refuse(
                f"codex sandbox_mode {self.sandbox_mode!r} is outside the "
                "pinned vocabulary")
        object.__setattr__(self, "writable_roots",
                           _validate_paths(self.writable_roots, "writable_roots"))

    @property
    def strictness(self) -> int:
        return self.STRICTNESS[self.sandbox_mode]

    @property
    def sandbox_disabled(self) -> bool:
        # danger-full-access is codex's de-facto "no sandbox" posture.
        return self.sandbox_mode == "danger-full-access"

    @property
    def network_allowed(self) -> bool:
        return self.network_access


@dataclass(frozen=True)
class ClaudeSandboxConfig:
    """Bash/PowerShell/Monitor sandbox toggles (documented native fields)."""

    MAX_STRICTNESS = 1
    COVERABLE = frozenset({ToolCategory.BASH})

    enable_bash_sandbox: bool = False
    enable_power_shell_sandbox: bool = False
    enable_monitor_sandbox: bool = False

    def __post_init__(self) -> None:
        for name in ("enable_bash_sandbox", "enable_power_shell_sandbox",
                     "enable_monitor_sandbox"):
            if not isinstance(getattr(self, name), bool):
                raise _refuse(f"claude field {name} must be a boolean")

    @property
    def strictness(self) -> int:
        return 1 if (self.enable_bash_sandbox or self.enable_power_shell_sandbox
                     or self.enable_monitor_sandbox) else 0

    @property
    def sandbox_disabled(self) -> bool:
        return self.strictness == 0

    @property
    def network_allowed(self) -> bool:
        # The documented claude sandbox schema carries no network knob.
        return False


@dataclass(frozen=True)
class PiSandboxConfig:
    """Pi is extension-backed: there is no built-in brand sandbox config."""

    MAX_STRICTNESS = 1
    COVERABLE = frozenset({ToolCategory.BASH})

    sandbox_extension: str | None = None

    def __post_init__(self) -> None:
        if not self.sandbox_extension:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                "pi has no built-in native sandbox; without its sandbox "
                "extension there is nothing to declare or fall back to",
                suggestion="install and name the sandbox extension, or do "
                           "not attach a native sandbox intent")

    @property
    def strictness(self) -> int:
        return 1

    @property
    def sandbox_disabled(self) -> bool:
        return False

    @property
    def network_allowed(self) -> bool:
        return False


_BRAND_CONFIGS = {
    "codex": CodexSandboxConfig,
    "claude-code": ClaudeSandboxConfig,
    "pi": PiSandboxConfig,
}

_INTENT_FIELDS = frozenset({
    "sandbox_id", "revision", "harness_id", "brand", "config", "read_scope",
    "write_scope", "network", "covered_categories", "required_coverage",
    "platform_gate", "scope", "declared_impact_set", "native_version_pin",
    "requested_strictness",
})

_CONFIG_FIELDS = {
    "codex": frozenset({"sandbox_mode", "writable_roots", "network_access"}),
    "claude-code": frozenset({"enable_bash_sandbox", "enable_power_shell_sandbox",
                              "enable_monitor_sandbox"}),
    "pi": frozenset({"sandbox_extension"}),
}


@dataclass(frozen=True)
class NativeSandboxIntent:
    sandbox_id: str
    revision: int
    harness_id: str
    brand: str
    config: Any
    read_scope: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    network: NetworkMode = NetworkMode.DISABLED
    covered_categories: frozenset[ToolCategory] = frozenset()
    required_coverage: frozenset[ToolCategory] = frozenset()
    platform_gate: PlatformGate = field(default_factory=PlatformGate)
    scope: SandboxApplyScope = SandboxApplyScope.SESSION
    declared_impact_set: tuple[str, ...] = ()
    native_version_pin: str | None = None
    requested_strictness: int | None = None

    def __post_init__(self) -> None:
        if self.brand not in _BRAND_CONFIGS:
            raise _refuse(
                f"brand {self.brand!r} has no closed native sandbox schema "
                "in this package",
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                suggestion="only codex / claude-code / pi have measured vocabularies")
        expected = _BRAND_CONFIGS[self.brand]
        if not isinstance(self.config, expected):
            raise _refuse(
                f"{self.brand} config must be a {expected.__name__}")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise _refuse("revision must be an integer >= 1")
        if not self.sandbox_id or not self.harness_id:
            raise _refuse("sandbox_id and harness_id are required")
        object.__setattr__(self, "read_scope",
                           _validate_paths(self.read_scope, "read_scope"))
        object.__setattr__(self, "write_scope",
                           _validate_paths(self.write_scope, "write_scope"))
        if isinstance(self.network, str):
            object.__setattr__(self, "network", NetworkMode(self.network))
        if isinstance(self.covered_categories, (list, tuple, set, frozenset)):
            object.__setattr__(self, "covered_categories",
                               _as_categories(self.covered_categories))
        if isinstance(self.required_coverage, (list, tuple, set, frozenset)):
            object.__setattr__(self, "required_coverage",
                               _as_categories(self.required_coverage))
        uncovered = self.covered_categories - expected.COVERABLE
        if uncovered:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                f"{self.brand}'s native sandbox schema cannot express coverage "
                f"of {sorted(str(c) for c in uncovered)}; it will not be "
                "approximated",
                suggestion="drop the claim or choose a harness that covers it")
        if self.requested_strictness is not None:
            if self.requested_strictness > expected.MAX_STRICTNESS:
                raise SandboxApiError(
                    SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                    f"strictness {self.requested_strictness} is beyond what "
                    f"{self.brand}'s closed schema can express "
                    f"(max {expected.MAX_STRICTNESS}); refusing to approximate",
                    suggestion="request at most the brand's strictest "
                               "expressible posture")
            if self.config.strictness < self.requested_strictness:
                raise SandboxApiError(
                    SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
                    "the concrete config does not reach the requested "
                    "strictness level",
                    suggestion="tighten the brand config to match")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "NativeSandboxIntent":
        """Strict wire-shape intake: unknown keys are refused, not dropped."""
        if not isinstance(data, Mapping):
            raise _refuse("intent must be a mapping")
        unknown = set(data) - _INTENT_FIELDS
        if unknown:
            raise _refuse(
                f"unknown intent fields {sorted(unknown)} are refused at "
                "construction")
        brand = str(data["brand"]) if "brand" in data else ""
        raw_config = data.get("config")
        if brand in _BRAND_CONFIGS and isinstance(raw_config, Mapping):
            cfg_fields = _CONFIG_FIELDS[brand]
            cfg_unknown = set(raw_config) - cfg_fields
            if cfg_unknown:
                raise _refuse(
                    f"unknown {brand} config fields {sorted(cfg_unknown)} "
                    "are refused at construction")
            config = _BRAND_CONFIGS[brand](**dict(raw_config))
        else:
            config = raw_config
        kwargs: dict[str, Any] = {"config": config, "brand": brand}
        for key in _INTENT_FIELDS - {"config", "brand"}:
            if key in data:
                kwargs[key] = data[key]
        if isinstance(kwargs.get("network"), str):
            kwargs["network"] = NetworkMode(kwargs["network"])
        if isinstance(kwargs.get("scope"), str):
            kwargs["scope"] = SandboxApplyScope(kwargs["scope"])
        gate = kwargs.get("platform_gate")
        if isinstance(gate, Mapping):
            kwargs["platform_gate"] = PlatformGate(
                tuple(str(os_name) for os_name in gate.get("allowed_os", ())))
        return cls(**kwargs)


def _as_categories(values: Any) -> frozenset[ToolCategory]:
    for value in values:
        if isinstance(value, str) and value.strip().lower() in {"all", "*",
                                                                "everything", "any"}:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
                "coverage wildcard is not declarable; name each category",
                suggestion="list bash/read/edit/mcp/network explicitly")
    return parse_coverage(values)


def brand_coverable_categories(brand: str) -> frozenset[ToolCategory]:
    """Categories the brand's native schema can ever claim to cover."""
    if brand not in _BRAND_CONFIGS:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
            f"brand {brand!r} has no measured native sandbox schema")
    return _BRAND_CONFIGS[brand].COVERABLE
