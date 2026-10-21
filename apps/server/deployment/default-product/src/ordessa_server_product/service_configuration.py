"""Explicit service configuration for the default Server product (strict JSON v1).

Zero configuration is the default path: everything below is derived from the C-01
data-root contract. A configuration file exists only to override those defaults,
and when it is supplied it must state the whole selection — a partially specified
file is refused instead of being silently completed, so "what this instance
allows" is always a fact a reader can see in one place.

The file never carries a token byte, a model key, the data root or the port: the
token is a *locator*, and root/port stay host-owned.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
from types import MappingProxyType

from ordessa_infrastructure.encoding import decode_json
from ordessa_infrastructure.layout import token_file


class ServiceConfigurationError(ValueError):
    """The service configuration is malformed, ambiguous or incomplete."""

    code = "SERVICE_CONFIGURATION_INVALID"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


#: Every Profile operation this product exposes. Grants are exact ids; there is
#: no wildcard and no implicit "everything the capability offers".
PROFILE_OPERATIONS: "tuple[str, ...]" = (
    "agents.profiles.capabilities", "agents.profiles.list", "agents.profiles.readEntry",
    "agents.profiles.read", "agents.profiles.preview", "agents.profiles.create",
    "agents.profiles.edit", "agents.profiles.clone", "agents.profiles.rename",
    "agents.profiles.archive", "agents.profiles.restore",
)

#: Environment operations this product exposes; grants name these exact ids.
ENVIRONMENT_OPERATIONS: "tuple[str, ...]" = tuple(
    "environments." + action for action in (
        "providers", "list", "inspect", "create", "register", "stop", "delete",
        "exec", "files", "acquire", "release", "process-release",
        "export-endpoint", "endpoint-inspect", "use-inspect",
        # Permission rights the exec/endpoint paths also authorize.
        "launch", "observe", "communicate", "terminate", "detach", "export", "resolve"))

#: Decision operations this product exposes; grants name these exact ids.
DECISION_OPERATIONS: "tuple[str, ...]" = (
    "decisions.validate", "decisions.run", "decisions.get",
    "decisions.evidence", "decisions.query")

#: Agent instance operations this product exposes. The ids are the ones the
#: instances capability descriptor publishes; grants name these exact ids.
AGENT_INSTANCE_OPERATIONS: "tuple[str, ...]" = (
    "agents.start", "agents.get", "agents.stop", "agents.detach",
    "agents.reconcile", "agents.prompt", "agents.query", "agents.cancel")

#: Native operation ids the native capability descriptor publishes.
AGENT_NATIVE_OPERATIONS: "tuple[str, ...]" = (
    "agents.native.freeze", "agents.native.recorded", "agents.native.query")

#: Every Agent operation (instance + native) this product can serve.
AGENT_OPERATIONS: "tuple[str, ...]" = AGENT_INSTANCE_OPERATIONS + AGENT_NATIVE_OPERATIONS

#: Capability groups this slice can actually assemble. Adding a group here without
#: a real assembly would advertise something the product cannot serve.
SUPPORTED_CAPABILITIES: "frozenset[str]" = frozenset({"agents", "environments", "decisions"})

_MAX_DOCUMENT_BYTES = 1_048_576

# -- harness.providers -------------------------------------------------------
#
# The optional provider configuration follows the CLI's own harness
# configuration rules (the CLI reads the same three keys from its
# ``harness.json``): a bounded argv list, explicit string environment values
# and ``envFrom`` references that name an environment variable. The two
# narrowings below are the Server's own and are documented here.

#: A name that looks like a credential holder. An explicit ``env`` value under
#: such a name would put a secret in this file, so the name itself is refused.
_CREDENTIAL_NAME_MARKERS: "tuple[str, ...]" = (
    "TOKEN", "SECRET", "PASSWORD", "APIKEY", "API_KEY", "CREDENTIAL",
)

#: A POSIX environment variable name. ``envFrom`` may only *reference* the
#: environment, so both its sides are names and never literals.
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

#: Literal credential shapes. Only shapes that cannot plausibly be ordinary
#: configuration are refused, so a legitimate value is never blocked by a
#: guess, and a real key is never accepted under a harmless-looking name.
_SECRET_LITERAL_PREFIXES: "tuple[str, ...]" = (
    "sk-", "sk_", "sk-ant-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
    "glpat-", "xoxb-", "xoxp-", "xoxa-", "xoxr-", "AKIA", "ASIA",
    "AIza", "eyJ",
)
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9_-]{40,}")

_MAX_COMMAND_ITEMS = 64
_MAX_COMMAND_ITEM_LENGTH = 4096


def _looks_like_secret(value: str) -> bool:
    """True for a literal that can only be a credential, not configuration."""
    return (value.startswith(_SECRET_LITERAL_PREFIXES)
            or _OPAQUE_TOKEN.fullmatch(value) is not None)


@dataclass(frozen=True)
class ServiceAccess:
    token_file: Path
    principal_id: str
    realm: str
    project: str
    grants: "tuple[str, ...]"
    #: Transport request deadline for one operations.call (1..300 seconds).
    request_deadline_seconds: float = 30.0


@dataclass(frozen=True)
class ServiceConfiguration:
    server_id: str
    access: ServiceAccess
    profiles_namespace: str
    harness_allowlist: "tuple[str, ...]"
    capabilities: "tuple[str, ...]"
    #: Per-brand launch configuration (command/env/envFrom). The mapping is
    #: read-only: it is the Server's trusted provider configuration and the
    #: preparation port consumes it without changing it.
    harness_providers: "Mapping[str, Mapping[str, object]]" = field(
        default_factory=dict, hash=False)

    @property
    def principal_scope(self) -> str:
        """The existing Profile principal scope this instance maps its caller to."""
        return "principal:" + self.access.principal_id


def _absolute(value: object, what: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        raise ServiceConfigurationError(f"{what} must be a non-empty path string")
    path = Path(value)
    if not path.is_absolute():
        raise ServiceConfigurationError(f"{what} must be an absolute path")
    return path


def _identifier(value: object, what: str, *, pattern_ok) -> str:
    if type(value) is not str or not value or not pattern_ok(value):
        raise ServiceConfigurationError(f"{what} is invalid")
    return value


def _token_name(value: object) -> bool:
    import re
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,511}", value) is not None


def _read_document(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ServiceConfigurationError("service configuration is unreadable") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        import stat
        if not stat.S_ISREG(info.st_mode) or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ServiceConfigurationError(
                "service configuration must be a regular file without group/other write access")
        raw = stream.read(_MAX_DOCUMENT_BYTES + 1)
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise ServiceConfigurationError("service configuration exceeds 1 MiB")
    try:
        document = decode_json(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        raise ServiceConfigurationError("service configuration is not strict UTF-8 JSON") from None
    if type(document) is not dict:
        raise ServiceConfigurationError("service configuration must be a JSON object")
    return document


def _harness_providers(value: object) -> "Mapping[str, Mapping[str, object]]":
    """Validate the optional ``harness.providers`` section.

    The rules are the CLI's own harness-configuration rules, so the same
    provider configuration means the same thing on both entry points:

    * ``command`` is an argv list of non-empty strings;
    * ``env`` maps a variable name to an explicit string value, and a
      credential-shaped name is refused (such a value would be a secret in
      this file);
    * ``envFrom`` maps a variable name to the *name* of an environment
      variable — a reference, never a literal — and it may not bind the same
      variable as ``env``.

    Two narrowings are the Server's own: a literal that can only be a
    credential is refused wherever it appears, and an environment variable
    name is a POSIX name. Both refuse more than the CLI, never less: a
    configuration the CLI accepts for these keys is accepted here too.
    """
    if value is None:
        return MappingProxyType({})
    if type(value) is not dict:
        raise ServiceConfigurationError("harness.providers must be a JSON object")
    providers: "dict[str, dict[str, object]]" = {}
    for name, entry in value.items():
        if type(name) is not str or not name:
            raise ServiceConfigurationError("harness provider name must be a non-empty string")
        if type(entry) is not dict or set(entry) - {"command", "env", "envFrom"}:
            raise ServiceConfigurationError(
                "harness provider " + name + " accepts only command/env/envFrom")
        command = entry.get("command")
        if command is not None and (
                type(command) is not list or not command
                or len(command) > _MAX_COMMAND_ITEMS
                or any(type(item) is not str or not item or len(item) > _MAX_COMMAND_ITEM_LENGTH
                       or "\x00" in item for item in command)):
            raise ServiceConfigurationError(
                "harness provider " + name + " command must be a bounded argv list")
        environment = entry.get("env", {})
        if type(environment) is not dict or any(
                type(key) is not str or type(item) is not str
                for key, item in environment.items()):
            raise ServiceConfigurationError(
                "harness provider " + name + " env must be string values")
        for key, item in environment.items():
            if any(marker in key.upper() for marker in _CREDENTIAL_NAME_MARKERS):
                raise ServiceConfigurationError(
                    "harness provider " + name + " env cannot name a credential variable")
            if _looks_like_secret(item):
                raise ServiceConfigurationError(
                    "harness provider " + name + " env cannot carry a literal credential")
        references = entry.get("envFrom", {})
        if type(references) is not dict or any(
                type(key) is not str or type(item) is not str
                or _ENVIRONMENT_NAME.fullmatch(key) is None
                or _ENVIRONMENT_NAME.fullmatch(item) is None
                for key, item in references.items()):
            raise ServiceConfigurationError(
                "harness provider " + name + " envFrom must name environment variables")
        if any(_looks_like_secret(item) for item in references.values()):
            raise ServiceConfigurationError(
                "harness provider " + name + " envFrom may only reference the environment")
        if set(references) & set(environment):
            raise ServiceConfigurationError(
                "harness provider " + name + " env and envFrom bind the same variable")
        providers[name] = {
            "command": list(command) if command is not None else None,
            "env": dict(environment),
            "envFrom": dict(references),
        }
    return MappingProxyType(providers)


def configuration_from_document(document: dict, *, harness_default: "tuple[str, ...]") -> ServiceConfiguration:
    """Validate one complete document; every section is required."""
    required = {"version", "server", "access", "profiles", "harness", "capabilities"}
    if set(document) != required:
        raise ServiceConfigurationError(
            "service configuration needs exactly version/server/access/profiles/harness/capabilities")
    if document["version"] != 1 or type(document["version"]) is not int:
        raise ServiceConfigurationError("unsupported service configuration version")

    server = document["server"]
    if type(server) is not dict or set(server) != {"serverId"}:
        raise ServiceConfigurationError("server section needs exactly serverId")
    server_id = _identifier(server["serverId"], "serverId", pattern_ok=_token_name)

    access = document["access"]
    required_access = {"tokenFile", "principalId", "realm", "project", "grants"}
    allowed_access = required_access | {"requestDeadlineSeconds"}
    if type(access) is not dict or not required_access <= set(access) or set(access) - allowed_access:
        raise ServiceConfigurationError(
            "access section needs tokenFile/principalId/realm/project/grants "
            "(optional requestDeadlineSeconds)")
    deadline = access.get("requestDeadlineSeconds", 30.0)
    if type(deadline) not in (int, float) or not 1 <= deadline <= 1800:
        raise ServiceConfigurationError("requestDeadlineSeconds must be a number in 1..1800")
    deadline = float(deadline)
    token_path = _absolute(access["tokenFile"], "tokenFile")
    principal_id = _identifier(access["principalId"], "principalId", pattern_ok=_token_name)
    realm = _identifier(access["realm"], "realm", pattern_ok=_token_name)
    project = _identifier(access["project"], "project", pattern_ok=_token_name)
    grants = access["grants"]
    if (type(grants) is not list or not grants
            or any(type(item) is not str or not item for item in grants)
            or len(set(grants)) != len(grants)):
        raise ServiceConfigurationError("grants must be a unique, non-empty string list")
    unknown = set(grants) - set(PROFILE_OPERATIONS) - set(ENVIRONMENT_OPERATIONS) \
        - set(DECISION_OPERATIONS) - set(AGENT_OPERATIONS)
    if unknown:
        raise ServiceConfigurationError("grant names an operation this product does not expose: "
                                        + ", ".join(sorted(unknown)))

    profiles = document["profiles"]
    if type(profiles) is not dict or set(profiles) != {"namespace"}:
        raise ServiceConfigurationError("profiles section needs exactly namespace")
    namespace = _identifier(profiles["namespace"], "profiles.namespace", pattern_ok=_token_name)

    harness = document["harness"]
    if (type(harness) is not dict or not {"allowlist"} <= set(harness)
            or set(harness) - {"allowlist", "providers"}):
        raise ServiceConfigurationError(
            "harness section needs allowlist and accepts only an optional providers")
    allowlist = harness["allowlist"]
    if (type(allowlist) is not list
            or any(type(item) is not str or not item for item in allowlist)
            or len(set(allowlist)) != len(allowlist)):
        raise ServiceConfigurationError("harness.allowlist must be a unique string list")
    providers = _harness_providers(harness.get("providers"))

    capabilities = document["capabilities"]
    if (type(capabilities) is not list or not capabilities
            or any(type(item) is not str or not item for item in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise ServiceConfigurationError("capabilities must be a unique, non-empty string list")
    unsupported = set(capabilities) - SUPPORTED_CAPABILITIES
    if unsupported:
        raise ServiceConfigurationError("unsupported capability: " + ", ".join(sorted(unsupported)))

    return ServiceConfiguration(
        server_id=server_id,
        access=ServiceAccess(token_file=token_path, principal_id=principal_id, realm=realm,
                             project=project, grants=tuple(grants),
                             request_deadline_seconds=deadline),
        profiles_namespace=namespace,
        harness_allowlist=tuple(allowlist),
        capabilities=tuple(capabilities),
        harness_providers=providers,
    )


def load_service_configuration(path: str | Path, *, harness_default: "tuple[str, ...]" = ()) -> ServiceConfiguration:
    """Read and validate one explicit configuration file (no defaults are filled in)."""
    if type(path) is str:
        path = Path(path)
    if not isinstance(path, Path) or not path.is_absolute():
        raise ServiceConfigurationError("an absolute service configuration path is required")
    return configuration_from_document(_read_document(path), harness_default=harness_default)


def default_service_configuration(data_root: Path, *, harness_allowlist: "tuple[str, ...]") -> ServiceConfiguration:
    """The zero-configuration selection for one data root.

    The Server identity is derived from the root path (stable across restarts, no
    fixed constant and no extra file); the token is a locator into the existing
    layout; the grants are exactly the exposed Profile operations. No provider
    configuration is admitted: a zero-configuration instance launches only the
    brands' own declared commands.
    """
    if not isinstance(data_root, Path) or not data_root.is_absolute():
        raise ServiceConfigurationError("an absolute data root is required")
    if type(harness_allowlist) is not tuple or any(type(item) is not str for item in harness_allowlist):
        raise ServiceConfigurationError("harness allowlist must be a tuple of names")
    digest = hashlib.sha256(str(data_root).encode("utf-8")).hexdigest()[:8]
    return ServiceConfiguration(
        server_id="ordessa-" + digest,
        access=ServiceAccess(
            token_file=token_file(data_root),
            principal_id="instance",
            realm="ordessa",
            project="local",
            grants=PROFILE_OPERATIONS + ENVIRONMENT_OPERATIONS + DECISION_OPERATIONS
            + AGENT_OPERATIONS,
        ),
        profiles_namespace="server",
        harness_allowlist=tuple(harness_allowlist),
        capabilities=("agents", "environments", "decisions"),
        harness_providers=MappingProxyType({}),
    )


__all__ = [
    "AGENT_INSTANCE_OPERATIONS", "AGENT_NATIVE_OPERATIONS", "AGENT_OPERATIONS",
    "ENVIRONMENT_OPERATIONS", "PROFILE_OPERATIONS", "SUPPORTED_CAPABILITIES", "ServiceAccess",
    "ServiceConfiguration", "ServiceConfigurationError", "configuration_from_document",
    "default_service_configuration", "load_service_configuration",
]
