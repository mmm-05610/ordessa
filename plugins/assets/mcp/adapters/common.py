"""Shared pure C2-style surface for native-lane brand adapters (Q4 T04 L1).

harness-api is unpublished; these functions are the MCP-domain implementations
the future per-brand adapters will expose through C2 (assess/compile/verify).
Every function here is pure: no file-system access, no HOME reads, no spawn,
no network, no secret resolution. All host facts (destination descriptor,
revision contents, credential provenance, observations) are injected by the
caller — see specs/011-q4-mcp/reports/t04-adapters.md for the C2 mapping.

Refusals are raised as ``backend.errors.McpError`` with the codes registered
in ``backend/native_intents.py`` plus the pre-existing domain codes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, FrozenSet, Mapping, Optional, Sequence, Tuple

from backend.definition import Literal, McpRevision, SecretRef, definition_digest
from backend.errors import (
    MCP_CAS_CONFLICT,
    MCP_OWNER_CONFLICT,
    MCP_TRANSPORT_UNSUPPORTED,
    McpError,
)
from backend.native_intents import (
    DESTINATION_INSTANCE_CONFIG,
    DESTINATION_KINDS,
    DESTINATION_SESSION_OVERRIDE,
    ENFORCEMENT_UNPROVEN,
    LANE_MANAGED,
    LANE_NATIVE,
    PERMISSION_ENFORCEMENT_UNPROVEN_MARKER,
    MCP_CREDENTIAL_PROVENANCE_UNPROVEN,
    MCP_NATIVE_NAME_CONFLICT,
    MCP_NATIVE_TARGET_UNSUPPORTED,
    MCP_PERMISSION_ENFORCEMENT_UNPROVEN,
    AssessResult,
    CredentialProvenance,
    Destination,
    InstanceConfigTarget,
    NativeIntentSet,
    NativeObservation,
    NativeServerIntent,
    ObservedServer,
    SessionOverrideTarget,
    SlotValue,
    VERDICT_SUPPORTED,
    VERDICT_UNKNOWN,
    VERDICT_UNSUPPORTED,
    VerifyResult,
    VerifiedServerFact,
    FACT_CATALOG_CHANGED,
    FACT_LOADED,
    FACT_PROJECTED,
    FACT_UNKNOWN,
    LOAD_STATE_ABSENT,
    LOAD_STATE_CONFIG_BYTES_MATCH,
    LOAD_STATE_FAILED,
    LOAD_STATE_RUNTIME_LOADED,
)

RevisionProvider = Callable[[str, int], McpRevision]

# reason codes surfaced by assess (stable strings for the future C2 wire)
REASON_NO_MCP_CONFIG_SLOT = "no-mcp-config-slot"
REASON_MISSING_MCP_SLOT = "missing-mcp-slot"
REASON_SLOT_KEY_MISMATCH = "slot-key-mismatch"
REASON_REMOTE_RENDERING_UNSUPPORTED = "remote-rendering-unsupported"
REASON_DECLARATION_SHAPE = "declaration-shape-invalid"
REASON_INSTANCE_CONFIG_SLOT_CONFLICT = "codex-instance-config-slot-conflict"


@dataclass(frozen=True)
class BrandAdapter:
    """Per-brand facts and policy, declaratively. The codex/claude modules
    instantiate this; the behaviour lives in the shared pure functions."""

    harness_type: str
    config_key: str
    config_format: str
    #: destination shapes this brand may ever target (both brands keep both
    #: shapes per R-Q4-3; compile refuses anything else)
    destination_kinds: Tuple[str, ...] = DESTINATION_KINDS
    #: destination kinds that are structurally dead for this brand
    #: (kind -> reason); assess reports unsupported, compile refuses typed
    blocked_destinations: Mapping[str, str] = field(default_factory=dict)
    #: instance-config targets that collide with read-only projections
    projection_conflict_targets: FrozenSet[str] = frozenset()
    supported_transports: FrozenSet[str] = frozenset({"stdio"})
    default_destination_kind: str = DESTINATION_SESSION_OVERRIDE
    #: routes proven by controlled runtime evidence, (harness type,
    #: destination kind): empty for both brands at L1 — nothing may be
    #: reported supported (no fake green, dispatch 需求2).
    proven_routes: FrozenSet[Tuple[str, str]] = frozenset()
    unknown_reason: str = "native-route-unproven"


def _profile_of(decl) -> object:
    return getattr(decl, "profile", decl)


def destination_kind(destination: Destination) -> str:
    if isinstance(destination, InstanceConfigTarget):
        return DESTINATION_INSTANCE_CONFIG
    if isinstance(destination, SessionOverrideTarget):
        return DESTINATION_SESSION_OVERRIDE
    raise McpError(MCP_NATIVE_TARGET_UNSUPPORTED,
                   "destination must be one of the two injected descriptor shapes")


# -- assess -----------------------------------------------------------------------

def assess_native(
    brand: BrandAdapter,
    decl,
    snapshot=None,
    *,
    destination_kind: Optional[str] = None,
    revision_provider: Optional[RevisionProvider] = None,
) -> AssessResult:
    """supported/unsupported/unknown for one harness declaration.

    Structural infeasibility (no mcp slot/key, slot-key mismatch, a transport
    nothing in this tree renders) is typed ``unsupported`` with reasons; a
    structurally possible brand route without controlled runtime evidence is
    ``unknown`` — never fake-green. Both Codex and Claude Code sit at
    ``unknown`` at L1 (t04-t05-research §3, matrix §7).
    """
    kind = destination_kind or brand.default_destination_kind
    spec = _profile_of(decl)
    try:
        mcp_target = getattr(spec, "mcp_target")
        mcp_key = getattr(spec, "mcp_key")
        slots = tuple(getattr(spec, "slots"))
    except AttributeError:
        return AssessResult(brand.harness_type, VERDICT_UNSUPPORTED, kind,
                            (REASON_DECLARATION_SHAPE,))

    reasons = []
    if not mcp_target or not mcp_key:
        reasons.append(REASON_NO_MCP_CONFIG_SLOT)
    if "mcp" not in slots:
        reasons.append(REASON_MISSING_MCP_SLOT)
    if mcp_key and mcp_key != brand.config_key:
        reasons.append(REASON_SLOT_KEY_MISMATCH)
    if kind not in brand.destination_kinds:
        reasons.append(f"destination-unsupported:{kind}")
    blocked = brand.blocked_destinations.get(kind)
    if blocked:
        reasons.append(blocked)
    if (kind == DESTINATION_INSTANCE_CONFIG and mcp_target
            and mcp_target in brand.projection_conflict_targets):
        reasons.append("instance-config-target-is-read-only-projection")

    if snapshot is not None and revision_provider is not None:
        for entry in snapshot.definition_revisions:
            lane = (snapshot.lane_by_definition or {}).get(entry["definition_id"], {})
            if lane.get("lane") != LANE_NATIVE:
                continue
            try:
                revision = revision_provider(entry["definition_id"], int(entry["revision"]))
            except McpError:
                continue  # unreadable revisions are compile-time refusals
            if revision_transport_kind(revision) not in brand.supported_transports:
                reasons.append(REASON_REMOTE_RENDERING_UNSUPPORTED)
                break

    if reasons:
        return AssessResult(brand.harness_type, VERDICT_UNSUPPORTED, kind, tuple(reasons))
    if (brand.harness_type, kind) in brand.proven_routes:
        return AssessResult(brand.harness_type, VERDICT_SUPPORTED, kind,
                            ("runtime-evidence-proven",))
    return AssessResult(brand.harness_type, VERDICT_UNKNOWN, kind, (brand.unknown_reason,))


# -- compile ------------------------------------------------------------------------

def revision_transport_kind(revision: McpRevision) -> str:
    return "stdio" if hasattr(revision.transport, "executable_ref") else "remote"


def endpoint_fingerprint(revision: McpRevision) -> str:
    """Instance-level occupancy identity of one definition (harness-adapters
    「避免双启动的机械约束」): stdio = command+args, remote = url."""
    transport = revision.transport
    if hasattr(transport, "executable_ref"):
        return definition_digest({
            "kind": "stdio", "command": transport.executable_ref,
            "args": list(transport.argv),
        })
    return definition_digest({"kind": "remote", "url": transport.url})


def _compile_slot(name: str, value, provenance: CredentialProvenance) -> SlotValue:
    if isinstance(value, Literal):
        return SlotValue(name=name, kind="literal", value=value.value)
    if isinstance(value, SecretRef):
        attestation = provenance.attest(value.credential_id)
        if attestation is None or not attestation.is_valid():
            raise McpError(
                MCP_CREDENTIAL_PROVENANCE_UNPROVEN,
                f"secretRef {value.credential_id!r} has no proof that resolution "
                "happens only at the authorised instant on the Harness/managed "
                "surface; a native intent may never carry plaintext",
            )
        return SlotValue(
            name=name, kind="secretRef",
            credential_ref=value.credential_id,
            credential_revision=attestation.credential_revision,
        )
    raise McpError(MCP_TRANSPORT_UNSUPPORTED, f"slot {name!r} has an untyped value")


def _slots(values: Mapping[str, object], provenance: CredentialProvenance) -> Tuple[SlotValue, ...]:
    return tuple(
        sorted(
            (_compile_slot(name, value, provenance) for name, value in values.items()),
            key=lambda s: s.name,
        )
    )


def compile_native(
    brand: BrandAdapter,
    snapshot,
    destination: Destination,
    provenance: CredentialProvenance,
    *,
    revision_provider: RevisionProvider,
    expected_catalog_digests: Optional[Mapping[str, str]] = None,
    strict: bool = False,
) -> NativeIntentSet:
    """Plan the **complete effective set** as one intent set (pure).

    Refusals (typed, no partial plan):
    * destination shape not admissible for the brand -> MCP_NATIVE_TARGET_UNSUPPORTED;
    * lane missing/invalid for a snapshot definition -> MCP_OWNER_CONFLICT
      (``laneByDefinition`` must bind exactly one lane per definition id);
    * managed entry sharing a native endpoint -> MCP_OWNER_CONFLICT (mutual
      exclusion; managed definitions otherwise get no native intent, only an
      exclusion record);
    * duplicate nativeName / same endpoint under different names ->
      MCP_NATIVE_NAME_CONFLICT / MCP_OWNER_CONFLICT (never last-wins);
    * unproven credential resolution -> MCP_CREDENTIAL_PROVENANCE_UNPROVEN;
    * enforcement ``unproven`` while an allowNames reduction is required:
      entry marked ``permission-enforcement-unproven``; in strict mode ->
      MCP_PERMISSION_ENFORCEMENT_UNPROVEN refusal (data-model.md:38,
      contracts.md:37).
    """
    if expected_catalog_digests is None:
        expected_catalog_digests = {}
    kind = destination_kind(destination)
    if kind not in brand.destination_kinds:
        raise McpError(MCP_NATIVE_TARGET_UNSUPPORTED,
                       f"destination kind {kind!r} is not admissible for {brand.harness_type}")
    blocked = brand.blocked_destinations.get(kind)
    if blocked:
        raise McpError(MCP_NATIVE_TARGET_UNSUPPORTED, f"{brand.harness_type}: {blocked}")
    if destination.config_key != brand.config_key or destination.config_format != brand.config_format:
        raise McpError(MCP_NATIVE_TARGET_UNSUPPORTED,
                       "destination descriptor does not match the brand's config slot")

    lanes: Mapping[str, Mapping[str, str]] = snapshot.lane_by_definition or {}
    native_entries = []
    managed_records = []
    managed_by_fingerprint: dict = {}
    native_by_fingerprint: dict = {}
    name_owner: dict = {}
    set_markers = set()

    for entry in snapshot.definition_revisions:
        definition_id = entry["definition_id"]
        revision_no = int(entry["revision"])
        lane = lanes.get(definition_id)
        if lane is None or lane.get("lane") not in (LANE_NATIVE, LANE_MANAGED):
            raise McpError(
                MCP_OWNER_CONFLICT,
                f"{definition_id}: exactly one lane must be bound in the plan "
                f"(laneByDefinition is missing/invalid: {lane!r})",
            )
        revision = revision_provider(definition_id, revision_no)
        if revision.canonical_digest != entry.get("canonical_digest"):
            raise McpError(
                MCP_CAS_CONFLICT,
                f"{definition_id}@{revision_no}: revision digest drifted from the "
                "snapshot binding; re-resolve before planning",
            )
        fingerprint = endpoint_fingerprint(revision)
        transport_kind = revision_transport_kind(revision)
        if lane["lane"] == LANE_MANAGED:
            # no native intent for managed definitions (harness-adapters
            # 「避免双启动的机械约束」); keep an exclusion record only.
            managed_records.append({
                "definitionId": definition_id, "revision": str(revision_no),
                "endpointFingerprint": fingerprint,
            })
            managed_by_fingerprint.setdefault(fingerprint, definition_id)
            continue
        if transport_kind not in brand.supported_transports:
            raise McpError(
                MCP_TRANSPORT_UNSUPPORTED,
                f"{definition_id}: transport {transport_kind!r} has no proven "
                f"rendering on {brand.harness_type} native lane",
            )
        native_name = revision.canonical["name"]
        previous = name_owner.get(native_name)
        if previous is not None and previous != definition_id:
            raise McpError(
                MCP_NATIVE_NAME_CONFLICT,
                f"nativeName {native_name!r} is claimed by {previous} and {definition_id}",
            )
        name_owner[native_name] = definition_id
        clash = managed_by_fingerprint.get(fingerprint)
        if clash is not None:
            raise McpError(
                MCP_OWNER_CONFLICT,
                f"{definition_id}: endpoint already leased as managed by {clash}; "
                "native projection and managed lease are mutually exclusive",
            )
        other = native_by_fingerprint.get(fingerprint)
        if other is not None and other != definition_id:
            raise McpError(
                MCP_OWNER_CONFLICT,
                f"{definition_id} and {other} share one endpoint under different "
                "names; refusing (no last-wins over a native duplicate)",
            )
        native_by_fingerprint[fingerprint] = definition_id

        markers = []
        enforcement = lane.get("enforcement", ENFORCEMENT_UNPROVEN)
        if enforcement == ENFORCEMENT_UNPROVEN and snapshot.allowed_tool_names:
            markers.append(PERMISSION_ENFORCEMENT_UNPROVEN_MARKER)
            set_markers.add(PERMISSION_ENFORCEMENT_UNPROVEN_MARKER)
            if strict:
                raise McpError(
                    MCP_PERMISSION_ENFORCEMENT_UNPROVEN,
                    f"{definition_id}: enforcement is unproven on this host while an "
                    "allowNames reduction is required; strict mode refuses the plan",
                )

        native_entries.append(_build_intent(
            revision, fingerprint, transport_kind, enforcement,
            tuple(snapshot.allowed_tool_names), markers,
            expected_catalog_digests.get(definition_id), provenance,
        ))

    intent_set = NativeIntentSet(
        harness_type=brand.harness_type,
        destination=destination,
        session_ref=snapshot.target_session,
        runtime_generation=snapshot.runtime_generation,
        snapshot_digest=snapshot.snapshot_digest,
        entries=tuple(sorted(native_entries, key=lambda e: (e.native_name, e.definition_id))),
        excluded_managed=tuple(sorted(managed_records, key=lambda r: r["definitionId"])),
        markers=tuple(sorted(set_markers)),
    )
    return replace(intent_set, plan_digest=intent_set.compute_plan_digest())


def _build_intent(
    revision: McpRevision, fingerprint: str, transport_kind: str,
    enforcement: str, allowed: Tuple[str, ...], markers: Sequence[str],
    expected_catalog_digest: Optional[str], provenance: CredentialProvenance,
) -> NativeServerIntent:
    transport = revision.transport
    common = dict(
        definition_id=revision.definition_id, revision=revision.revision,
        canonical_digest=revision.canonical_digest,
        native_name=revision.canonical["name"], transport=transport_kind,
        endpoint_fingerprint=fingerprint,
        allowed_tool_names=tuple(sorted(allowed)),
        expected_catalog_digest=expected_catalog_digest,
        enforcement=enforcement, markers=tuple(sorted(markers)),
    )
    if transport_kind == "stdio":
        return NativeServerIntent(
            command=transport.executable_ref, args=tuple(transport.argv),
            env=_slots(transport.env, provenance), **common)
    return NativeServerIntent(
        url=transport.url, headers=_slots(transport.headers, provenance), **common)


# -- verify ------------------------------------------------------------------------

def verify_native(intent_set: NativeIntentSet, observation: NativeObservation) -> VerifyResult:
    """Interpret an injected native observation against one planned intent set.

    ``loaded`` is only ever a *relay* of the observer attesting actual load
    (``runtime-loaded``); a byte comparison of config content yields at most
    ``projected``. Anything mismatched/missing is ``catalog-changed`` or
    ``unknown`` — never silence."""
    instance_matched = (
        observation.session_ref == intent_set.session_ref
        and observation.runtime_generation == intent_set.runtime_generation
    )
    observed_by_name = {s.server_name: s for s in observation.servers}
    facts = []
    for entry in intent_set.entries:
        facts.append(_verify_entry(
            entry, observed_by_name.pop(entry.native_name, None), instance_matched))
    return VerifyResult(
        facts=tuple(facts),
        native_discovered=tuple(sorted(observed_by_name)),
        instance_matched=instance_matched,
    )


def _verify_entry(entry: NativeServerIntent, observed: Optional[ObservedServer],
                  instance_matched: bool) -> VerifiedServerFact:
    def fact(f, reason, observed_digest=None):
        return VerifiedServerFact(
            definition_id=entry.definition_id, native_name=entry.native_name,
            fact=f, reason=reason,
            expected_catalog_digest=entry.expected_catalog_digest,
            observed_catalog_digest=observed_digest,
        )

    if not instance_matched:
        return fact(FACT_UNKNOWN, "instance-identity-mismatch")
    if observed is None:
        return fact(FACT_UNKNOWN, "not-observed")
    if observed.transport != entry.transport:
        return fact(FACT_UNKNOWN, "transport-mismatch", observed.catalog_digest)
    if observed.load_state == LOAD_STATE_CONFIG_BYTES_MATCH:
        return fact(FACT_PROJECTED, "config-bytes-match-only", observed.catalog_digest)
    if observed.load_state == LOAD_STATE_RUNTIME_LOADED:
        if entry.expected_catalog_digest is not None:
            if observed.catalog_digest is None:
                return fact(FACT_UNKNOWN, "catalog-not-observed")
            if observed.catalog_digest != entry.expected_catalog_digest:
                return fact(FACT_CATALOG_CHANGED, "catalog-differs-from-plan",
                            observed.catalog_digest)
        return fact(FACT_LOADED, "observer-attested-runtime-load", observed.catalog_digest)
    if observed.load_state == LOAD_STATE_ABSENT:
        return fact(FACT_UNKNOWN, "absent-on-host")
    if observed.load_state == LOAD_STATE_FAILED:
        return fact(FACT_UNKNOWN, "load-failed")
    return fact(FACT_UNKNOWN, "unrecognised-observer-state")
