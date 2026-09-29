"""Q4 T04 native-lane intent DTOs (own types, deterministic serialisation).

harness-api is not published yet (api-requests G2). These are the MCP-domain
shapes the Codex/Claude native adapters exchange with the future C2 surface;
where harness-api names differ, a thin adapter maps field-by-field
(``docs/design/mcp/contracts.md:70`` — "名称不吻合用薄适配"). The expected
C2 type mapping lives in ``specs/011-q4-mcp/reports/t04-adapters.md``.

Hard rules encoded here (harness-adapters.md「Native lane」, R-Q4-3):

* the destination is **always an injected descriptor** in one of exactly two
  shapes — ``InstanceConfigTarget`` (instance config file path + key) or
  ``SessionOverrideTarget`` (per-session config override) — both brands keep
  both shapes; this module never derives a path from HOME or the environment;
* the plan covers the **complete effective set at once** (one
  :class:`NativeIntentSet` carrying every native-lane server), never a
  per-server append;
* secrets are carried as ``{"credentialRef": id, "credentialRevision": rev}``
  slot entries only — there is no field anywhere that could hold plaintext;
* every intent binds its ``lane`` and ``owner`` so a managed lease and a
  native projection for the same endpoint can be checked against each other
  (``MCP_OWNER_CONFLICT``).

Serialisation is deterministic by construction: canonical = plain
dict/list/str/int/None with sorted keys, digest via
``backend.definition.definition_digest`` (same ``sha256:`` rule as
revisions/snapshots), ``serialize()`` = ``json.dumps(sort_keys=True)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Tuple, runtime_checkable

from .definition import definition_digest
from .errors import (
    MCP_CREDENTIAL_PROVENANCE_UNPROVEN,
    MCP_NATIVE_NAME_CONFLICT,
    MCP_NATIVE_TARGET_UNSUPPORTED,
    MCP_PERMISSION_ENFORCEMENT_UNPROVEN,
)

# -- destination shapes ---------------------------------------------------------

DESTINATION_INSTANCE_CONFIG = "instance-config"
DESTINATION_SESSION_OVERRIDE = "session-override"
DESTINATION_KINDS = (DESTINATION_INSTANCE_CONFIG, DESTINATION_SESSION_OVERRIDE)

_CONFIG_FORMATS = ("json", "toml")


def _validate_config_key(config_key: str) -> str:
    if not isinstance(config_key, str) or not config_key or len(config_key) > 64:
        raise ValueError("config_key must be a short non-empty string")
    return config_key


def _validate_format(config_format: str) -> str:
    if config_format not in _CONFIG_FORMATS:
        raise ValueError(f"config_format must be one of {_CONFIG_FORMATS}")
    return config_format


def _validate_instance_path(path: str) -> str:
    """Same canonical bound the host registry puts on ``mcp_target``
    (plugins/harness/src/ordessa_harness/registry/schema.py:80-87), re-derived
    here so the MCP plugin stays free of host-internal imports."""
    if not isinstance(path, str) or not path or len(path) > 256:
        raise ValueError("target_path must be a short string")
    if not path.startswith("/") or ".." in path.split("/"):
        raise ValueError("target_path must be a canonical absolute path")
    if "{" in path or "}" in path:
        raise ValueError("target_path must not be a template")
    return path


@dataclass(frozen=True)
class InstanceConfigTarget:
    """Destination: a Harness-owned *instance* config file (never global HOME;
    path is injected by the caller, e.g. the profile-instance
    ``/runtime/home/.../config`` the host owns)."""

    target_path: str
    config_key: str
    config_format: str

    kind = DESTINATION_INSTANCE_CONFIG

    def __post_init__(self) -> None:
        _validate_instance_path(self.target_path)
        _validate_config_key(self.config_key)
        _validate_format(self.config_format)
        if not self.target_path.endswith("." + self.config_format):
            raise ValueError("target_path suffix must match config_format")

    def to_canonical(self) -> dict:
        return {
            "kind": self.kind,
            "targetPath": self.target_path,
            "configKey": self.config_key,
            "configFormat": self.config_format,
        }


@dataclass(frozen=True)
class SessionOverrideTarget:
    """Destination: a per-session config override handed to the Harness at
    session new/resume (the R-Q4-3 Codex route: ``session/new.mcpServers`` ->
    app-server ``mcp_servers`` overlay). No file path exists or is read."""

    config_key: str
    config_format: str

    kind = DESTINATION_SESSION_OVERRIDE

    def __post_init__(self) -> None:
        _validate_config_key(self.config_key)
        _validate_format(self.config_format)

    def to_canonical(self) -> dict:
        return {
            "kind": self.kind,
            "configKey": self.config_key,
            "configFormat": self.config_format,
        }


Destination = (InstanceConfigTarget, SessionOverrideTarget)

# -- credential provenance ------------------------------------------------------

PROVENANCE_MODE = "authorized-instant-resolution"
PROVENANCE_RESOLVERS = ("harness", "managed")


@dataclass(frozen=True)
class CredentialAttestation:
    """Proof that one credential id is resolved **only** at the authorised
    instant by the Harness or the managed surface (contracts.md §3/§4,
    data-model「秘密与留存」). It carries the credential revision identity,
    never any plaintext.

    Absence of a valid attestation is a compile refusal
    (``MCP_CREDENTIAL_PROVENANCE_UNPROVEN``): intents always travel with
    ``ref + revision`` only."""

    mode: str
    resolver: str
    credential_revision: str

    def is_valid(self) -> bool:
        return (
            self.mode == PROVENANCE_MODE
            and self.resolver in PROVENANCE_RESOLVERS
            and isinstance(self.credential_revision, str)
            and bool(self.credential_revision)
        )


@runtime_checkable
class CredentialProvenance(Protocol):
    """Injected proof surface. A future thin adapter maps this onto whatever
    harness-api / the Q5 credential service publish (G2 item 1)."""

    def attest(self, credential_id: str) -> Optional[CredentialAttestation]: ...


# -- intents ---------------------------------------------------------------------

LANE_NATIVE = "native"
LANE_MANAGED = "managed"
OWNER_HARNESS_NATIVE = "harness-native"

ENFORCEMENT_PROVEN = "proven"
ENFORCEMENT_UNPROVEN = "unproven"

# data-model.md:38 downgrade clause; contracts.md:37 refuses in strict mode.
PERMISSION_ENFORCEMENT_UNPROVEN_MARKER = "permission-enforcement-unproven"

# T014 converge: the T04 native-intent codes are registered in
# backend/errors.py (imported above); this module keeps re-exporting the
# names for its consumers (adapters/common.py and the tests import them
# from here; reported in specs/011-q4-mcp/reports/t04-adapters.md).


def _slot_canonical(slot: "SlotValue") -> dict:
    if slot.kind == "literal":
        return {"kind": "literal", "name": slot.name, "value": slot.value}
    return {
        "kind": "secretRef",
        "name": slot.name,
        "credentialRef": slot.credential_ref,
        "credentialRevision": slot.credential_revision,
    }


@dataclass(frozen=True)
class SlotValue:
    """One env/header slot in an intent. Two shapes only: a non-secret
    literal, or a credential **reference plus revision** — the plaintext type
    simply does not exist in this DTO space."""

    name: str
    kind: str  # "literal" | "secretRef"
    value: Optional[str] = None
    credential_ref: Optional[str] = None
    credential_revision: Optional[str] = None

    def to_canonical(self) -> dict:
        return _slot_canonical(self)


@dataclass(frozen=True)
class NativeServerIntent:
    """The plan for one server inside the complete-set intent. lane/owner and
    the endpoint fingerprint make the native-vs-managed mutual exclusion
    checkable by whoever receives the set (Harness C3 / reconcile)."""

    definition_id: str
    revision: int
    canonical_digest: str
    native_name: str
    transport: str  # "stdio" | "remote"
    endpoint_fingerprint: str
    command: Optional[str] = None
    args: Tuple[str, ...] = ()
    env: Tuple[SlotValue, ...] = ()
    url: Optional[str] = None
    headers: Tuple[SlotValue, ...] = ()
    allowed_tool_names: Tuple[str, ...] = ()
    expected_catalog_digest: Optional[str] = None
    enforcement: str = ENFORCEMENT_PROVEN
    markers: Tuple[str, ...] = ()
    lane: str = LANE_NATIVE
    owner: str = OWNER_HARNESS_NATIVE

    def to_canonical(self) -> dict:
        return {
            "definitionId": self.definition_id,
            "revision": self.revision,
            "canonicalDigest": self.canonical_digest,
            "nativeName": self.native_name,
            "transport": self.transport,
            "endpointFingerprint": self.endpoint_fingerprint,
            "command": self.command,
            "args": list(self.args),
            "env": [_slot_canonical(s) for s in self.env],
            "url": self.url,
            "headers": [_slot_canonical(s) for s in self.headers],
            "allowedToolNames": list(self.allowed_tool_names),
            "expectedCatalogDigest": self.expected_catalog_digest,
            "enforcement": self.enforcement,
            "markers": list(self.markers),
            "lane": self.lane,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class NativeIntentSet:
    """One complete effective set for one target — every native-lane server is
    planned together (harness-adapters.md:15 "所有服务器作为一个受管集合规划").
    Managed-lane definitions never appear as entries; they are only listed as
    exclusion records so the owner-conflict check is auditable."""

    harness_type: str
    destination: object  # InstanceConfigTarget | SessionOverrideTarget
    session_ref: Optional[str]
    runtime_generation: Optional[int]
    snapshot_digest: str
    entries: Tuple[NativeServerIntent, ...]
    excluded_managed: Tuple[Mapping[str, str], ...] = ()
    markers: Tuple[str, ...] = ()
    plan_digest: str = ""

    @property
    def owner(self) -> str:
        return f"{OWNER_HARNESS_NATIVE}:{self.harness_type}"

    def to_canonical(self) -> dict:
        return {
            "harnessType": self.harness_type,
            "owner": self.owner,
            "destination": self.destination.to_canonical(),
            "sessionRef": self.session_ref,
            "runtimeGeneration": self.runtime_generation,
            "snapshotDigest": self.snapshot_digest,
            "entries": [e.to_canonical() for e in self.entries],
            "excludedManaged": [dict(e) for e in self.excluded_managed],
            "markers": list(self.markers),
        }

    def serialize(self) -> bytes:
        import json  # local: keeps the module's import surface minimal for AST guards

        return json.dumps(
            self.to_canonical(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def compute_plan_digest(self) -> str:
        return definition_digest(self.to_canonical())


# -- verification observations ----------------------------------------------------

# Observer load-state vocabulary. ``runtime-loaded`` must mean the observer
# saw the host actually load the server (tool catalog / live status); a byte
# comparison of the on-disk/override config is only ``config-bytes-match`` and
# can yield at most the ``projected`` fact (harness-adapters.md:15).
LOAD_STATE_RUNTIME_LOADED = "runtime-loaded"
LOAD_STATE_CONFIG_BYTES_MATCH = "config-bytes-match"
LOAD_STATE_ABSENT = "absent"
LOAD_STATE_FAILED = "load-failed"
LOAD_STATES = (
    LOAD_STATE_RUNTIME_LOADED, LOAD_STATE_CONFIG_BYTES_MATCH,
    LOAD_STATE_ABSENT, LOAD_STATE_FAILED,
)

FACT_LOADED = "loaded"
FACT_PROJECTED = "projected"
FACT_CATALOG_CHANGED = "catalog-changed"
FACT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ObservedServer:
    server_name: str
    transport: str
    load_state: str
    catalog_digest: Optional[str] = None
    tool_names: Tuple[str, ...] = ()

    def to_canonical(self) -> dict:
        return {
            "serverName": self.server_name,
            "transport": self.transport,
            "loadState": self.load_state,
            "catalogDigest": self.catalog_digest,
            "toolNames": list(self.tool_names),
        }


@dataclass(frozen=True)
class NativeObservation:
    """Native observation as reported by an **injected** observer (future
    Harness C3 ``verify(handle)`` surface, G2 item 3). Q4 never reads HOME or
    shells into the host to build this itself."""

    observer: str
    session_ref: Optional[str]
    runtime_generation: Optional[int]
    servers: Tuple[ObservedServer, ...]

    def to_canonical(self) -> dict:
        return {
            "observer": self.observer,
            "sessionRef": self.session_ref,
            "runtimeGeneration": self.runtime_generation,
            "servers": [s.to_canonical() for s in self.servers],
        }


@dataclass(frozen=True)
class VerifiedServerFact:
    definition_id: str
    native_name: str
    fact: str  # FACT_* above
    reason: str
    expected_catalog_digest: Optional[str]
    observed_catalog_digest: Optional[str]

    def to_canonical(self) -> dict:
        return {
            "definitionId": self.definition_id,
            "nativeName": self.native_name,
            "fact": self.fact,
            "reason": self.reason,
            "expectedCatalogDigest": self.expected_catalog_digest,
            "observedCatalogDigest": self.observed_catalog_digest,
        }


@dataclass(frozen=True)
class VerifyResult:
    facts: Tuple[VerifiedServerFact, ...]
    native_discovered: Tuple[str, ...]  # observed but not planned: read-only display
    instance_matched: bool

    def to_canonical(self) -> dict:
        return {
            "facts": [f.to_canonical() for f in self.facts],
            "nativeDiscovered": list(self.native_discovered),
            "instanceMatched": self.instance_matched,
        }

    def serialize(self) -> bytes:
        import json

        return json.dumps(
            self.to_canonical(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


# -- assess ------------------------------------------------------------------------

VERDICT_SUPPORTED = "supported"
VERDICT_UNSUPPORTED = "unsupported"
VERDICT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class AssessResult:
    harness_type: str
    verdict: str
    destination_kind: str
    reasons: Tuple[str, ...]

    @property
    def is_supported(self) -> bool:
        return self.verdict == VERDICT_SUPPORTED
