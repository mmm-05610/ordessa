"""Q4 T013 native binding: the ONLY Q4-domain <-> harness-api conversion point.

Everything that crosses between the MCP domain DTOs
(:mod:`backend.native_intents`, :mod:`backend.resolve` snapshots) and the
published Harness C2/C4 contract types
(``ordessa_harness_api``, plugins/harness/api) happens here and nowhere
else: ``native_intents`` stays pure-domain and unit-testable on its own,
``backend/service.py`` consumes the C4 port through the converters below,
and ``adapters/codex.py`` / ``adapters/claude.py`` expose the real
:class:`McpNativeConfigurationAdapter` (facet ``mcp.servers``) through the
factories there.

Conversion map (the T04 mapping table of
``specs/011-q4-mcp/reports/t04-adapters.md`` put on the real types; the
honesty rules of ``docs/design/mcp/harness-adapters.md``「Native lane」
are preserved verbatim):

* ``AssessResult`` verdict   -> ``Assessment(status, reason/evidence_ref)``
  — without controlled runtime evidence a cell stays ``unknown``; this
  module never manufactures ``supported`` (`proven_routes` stays empty);
* ``NativeIntentSet`` (the complete effective set) -> a closed-object facet
  payload (``FACET_PAYLOAD_SCHEMA``) -> per-entry ``SetField`` on the
  brand's config slot, ``BindSecret`` for secret-bearing slots when the
  context exposes an authorised environment target, typed refusal when it
  does not. There is no plaintext-carrying shape anywhere: the domain DTO
  only has ``literal`` / ``secretRef{credentialRef, credentialRevision}``,
  and the API itself rejects secret-named ``SetField`` paths and keys
  (``looks_secret_name`` / ``validate_json``) — double-guarded;
* ``NativeObservation`` (observer-injected) -> ``Match`` / ``Mismatch`` /
  ``VerificationUnknown``: ``runtime-loaded`` relayed by an attesting
  observer may reach ``Match``; ``config-bytes-match`` yields at most
  ``projected`` and therefore NEVER ``Match`` (harness-adapters.md:15 —
  "文件字节一致只能记 projected"); identity/catalog contradictions are
  ``Mismatch``, absence is ``VerificationUnknown``;
* ``McpEffectiveSnapshot`` + plan params -> ``ApplicationTarget`` /
  ``DesiredFragment`` for the C4 ``ConfigurationService.plan`` port, and
  ``Plan`` / ``Refused`` / ``Unknown`` back to typed ``McpError`` refusals
  (``refused_to_mcp_error`` / ``unknown_to_mcp_error``) — no permit, no
  plan; drift, no reconfiguration and no launch (contracts.md §1 row 6).

Semantics the published API does NOT carry and this layer keeps on the Q4
side (registered in specs/011-q4-mcp/reports/t013-harness-wiring.md):
``targetPath`` (native file identity stays with the harness runtime — the
payload carries configKey/configFormat only), per-definition lane/owner
audit records and endpoint fingerprints (payload-side audit fields the API
schema mirrors), ``reset`` compilation (deleting a previously owned server
needs an owned-name enumeration the C2 signature does not pass in — typed
refusal, not guesswork), and the submission permit itself (the C4 ``plan``
surface takes no permit; presence is checked here, verification and spend
stay with the harness ``apply`` ``PermitVerifier``).

Import boundary: this module imports ``ordessa_harness_api`` (the published
contract) and the MCP domain only — never ``adapters/*`` (outside the
installed ``backend`` package) and never host internals. The brand-side
pure verify function is injected by the adapter factories in
``adapters/codex.py`` / ``adapters/claude.py``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, ApplicationTarget, Assessment,
    ConfigurationAdapterDescriptor, ContractError, DesiredFragment, ErrorCode,
    FieldClaim, FieldPath, IntentSet, LaunchRequest, Match, Mismatch,
    Plan, ReconfigurationDecision, Refused, SetField,
    TargetDescriptor, TargetHandle, Unknown, ValueSchema, VerificationUnknown,
    VersionRange, validate_json,
)
from ordessa_harness_api.schema import looks_secret_name

from .errors import (
    APPLICATION_PORT_ABSENT as _APPLICATION_PORT_ABSENT,
    MCP_CAS_CONFLICT,
    MCP_GATE_BUSY,
    MCP_GATE_CAPABILITY_UNSUPPORTED,
    MCP_GATE_FRAGMENT_INVALID,
    MCP_GATE_REFUSED,
    MCP_GATE_RESUME_UNAVAILABLE,
    MCP_ISOLATION_UNPROVEN,
    MCP_OWNER_CONFLICT,
    MCP_VERIFICATION_MISMATCH,
    NATIVE_PLANNER_ABSENT,
    PERMISSION_REFUSED,
    UNKNOWN_OUTCOME,
    McpError,
)
from .native_intents import (
    DESTINATION_INSTANCE_CONFIG,
    DESTINATION_SESSION_OVERRIDE,
    FACT_CATALOG_CHANGED,
    FACT_PROJECTED,
    FACT_UNKNOWN,
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
    AssessResult,
)

# -- facet and point constants (contracts.md §3; harness contributions.py) -----

FACET_ID = "mcp.servers"
FACET_SCHEMA_VERSION = "v1"
#: one facet item per complete effective set (the plan is the whole set,
#: never a per-server append — harness-adapters.md「Native lane」)
FACET_ITEM_ID = "mcp.servers.effective-set"
CONFIGURATION_POINT_ID = "harness.configuration-adapters"
POINT_API_VERSION = "v1"
#: the entry vocabulary of the fixed ACP runtime entries (the fixture and
#: the harness C4 slice both key contributions on the runtime entry)
ENTRY_ACP = "acp"
ENTRIES = (ENTRY_ACP,)

# T014 converge: this module's eight codes (the T013 additions) are
# registered in backend/errors.py; the import block above re-exports them
# for consumers (service.py imports NATIVE_PLANNER_ABSENT from here).
# ``APPLICATION_PORT_ABSENT`` is service.py's own row, reused for the
# adapter-side "no configuration service composed" refusal.


def instance_target_id(harness_type: str) -> str:
    return f"assets.mcp.{harness_type}.instance-config"


def session_target_id(harness_type: str) -> str:
    return f"assets.mcp.{harness_type}.session-override"


# -- closed facet payload -------------------------------------------------------

_SLOT_SCHEMA = ValueSchema(
    "object",
    properties=(
        ("name", ValueSchema("string")),
        ("kind", ValueSchema("string", enum=("literal", "secretRef"))),
        ("value", ValueSchema("string", nullable=True)),
        ("credentialRef", ValueSchema("string", nullable=True)),
        ("credentialRevision", ValueSchema("string", nullable=True)),
    ),
    required=("name", "kind"),
)

_ENTRY_KEYS = (
    "definitionId", "revision", "canonicalDigest", "nativeName", "transport",
    "endpointFingerprint", "command", "args", "env", "url", "headers",
    "allowedToolNames", "expectedCatalogDigest", "enforcement", "markers",
    "lane", "owner",
)

_ENTRY_SCHEMA = ValueSchema(
    "object",
    properties=(
        ("definitionId", ValueSchema("string")),
        ("revision", ValueSchema("integer")),
        ("canonicalDigest", ValueSchema("string")),
        ("nativeName", ValueSchema("string")),
        ("transport", ValueSchema("string", enum=("stdio", "remote"))),
        ("endpointFingerprint", ValueSchema("string")),
        ("command", ValueSchema("string", nullable=True)),
        ("args", ValueSchema("array", items=ValueSchema("string"))),
        ("env", ValueSchema("array", items=_SLOT_SCHEMA)),
        ("url", ValueSchema("string", nullable=True)),
        ("headers", ValueSchema("array", items=_SLOT_SCHEMA)),
        ("allowedToolNames", ValueSchema("array", items=ValueSchema("string"))),
        ("expectedCatalogDigest", ValueSchema("string", nullable=True)),
        ("enforcement", ValueSchema("string")),
        ("markers", ValueSchema("array", items=ValueSchema("string"))),
        # lane is ENUMERATED to native: a managed-lane definition cannot
        # even be shaped into a native intent payload (反例: managed 泄漏).
        ("lane", ValueSchema("string", enum=("native",))),
        ("owner", ValueSchema("string")),
    ),
    required=_ENTRY_KEYS,
)

_EXCLUDED_SCHEMA = ValueSchema(
    "object",
    properties=(
        ("definitionId", ValueSchema("string")),
        ("revision", ValueSchema("string")),
        ("endpointFingerprint", ValueSchema("string")),
    ),
    required=("definitionId", "revision", "endpointFingerprint"),
)

#: The complete effective set for one target, one brand. NO targetPath: the
#: native file identity belongs to the Harness runtime (contracts §3); the
#: payload pins the brand slot (configKey/configFormat) and the destination
#: kind only. ``additional_properties=False`` (ValueSchema default) is the
#: load-bearing part: an undeclared field — a path, a plaintext value, an
#: owner spoof — is a typed ``ContractError`` at the schema, not a silent
#: pass-through.
FACET_PAYLOAD_SCHEMA = ValueSchema(
    "object",
    properties=(
        ("harnessType", ValueSchema("string")),
        ("destinationKind",
         ValueSchema("string", enum=(DESTINATION_INSTANCE_CONFIG,
                                     DESTINATION_SESSION_OVERRIDE))),
        ("configKey", ValueSchema("string")),
        ("configFormat", ValueSchema("string", enum=("json", "toml"))),
        ("sessionRef", ValueSchema("string", nullable=True)),
        ("runtimeGeneration", ValueSchema("integer", nullable=True)),
        ("snapshotDigest", ValueSchema("string")),
        ("planDigest", ValueSchema("string")),
        ("itemId", ValueSchema("string")),
        ("markers", ValueSchema("array", items=ValueSchema("string"))),
        ("entries", ValueSchema("array", items=_ENTRY_SCHEMA)),
        ("excludedManaged", ValueSchema("array", items=_EXCLUDED_SCHEMA)),
    ),
    required=("harnessType", "destinationKind", "configKey", "configFormat",
              "sessionRef", "runtimeGeneration", "snapshotDigest", "planDigest",
              "itemId", "markers", "entries", "excludedManaged"),
)

#: The observer contract for ``verify``: the harness C3-side observer relays
#: native load facts in the T04 load-state vocabulary (t04-adapters.md §3
#: 「NativeObservation」row); ``evidenceRef`` is the observer's own
#: attestation handle — without it nothing may reach ``Match``.
OBSERVED_SCHEMA = ValueSchema(
    "object",
    properties=(
        ("observer", ValueSchema("string")),
        ("evidenceRef", ValueSchema("string", nullable=True)),
        ("sessionRef", ValueSchema("string", nullable=True)),
        ("runtimeGeneration", ValueSchema("integer", nullable=True)),
        ("servers", ValueSchema("array", items=ValueSchema(
            "object",
            properties=(
                ("serverName", ValueSchema("string")),
                ("transport", ValueSchema("string")),
                ("loadState", ValueSchema("string")),
                ("catalogDigest", ValueSchema("string", nullable=True)),
                ("toolNames", ValueSchema("array", items=ValueSchema("string"))),
            ),
            required=("serverName", "transport", "loadState",
                      "catalogDigest", "toolNames"),
        ))),
    ),
    required=("observer", "sessionRef", "runtimeGeneration", "servers"),
)

# -- domain <-> facet payload ---------------------------------------------------


@dataclass(frozen=True)
class _PayloadDestination:
    """Destination stand-in for intent sets rebuilt FROM the payload (verify
    binding): verify reads session/generation/entries only, never a path —
    the path identity is the harness runtime's (contracts §3)."""

    config_key: str
    config_format: str
    kind: str = DESTINATION_INSTANCE_CONFIG

    def to_canonical(self) -> dict:
        return {"kind": self.kind, "configKey": self.config_key,
                "configFormat": self.config_format}


def destination_of(intent_set: NativeIntentSet) -> Tuple[str, Any]:
    """(kind, destination) for a real domain intent set."""
    destination = intent_set.destination
    if isinstance(destination, InstanceConfigTarget):
        return DESTINATION_INSTANCE_CONFIG, destination
    if isinstance(destination, SessionOverrideTarget):
        return DESTINATION_SESSION_OVERRIDE, destination
    raise McpError(
        "MCP_NATIVE_TARGET_UNSUPPORTED",
        "native binding only accepts the two injected descriptor shapes")


def _slot_to_payload(slot: SlotValue) -> dict:
    if slot.kind == "literal":
        return {"name": slot.name, "kind": "literal", "value": slot.value,
                "credentialRef": None, "credentialRevision": None}
    return {"name": slot.name, "kind": "secretRef", "value": None,
            "credentialRef": slot.credential_ref,
            "credentialRevision": slot.credential_revision}


def _slot_from_payload(slot: Mapping) -> SlotValue:
    return SlotValue(name=slot["name"], kind=slot["kind"], value=slot["value"],
                     credential_ref=slot["credentialRef"],
                     credential_revision=slot["credentialRevision"])


def _entry_to_payload(entry: NativeServerIntent) -> dict:
    return {
        "definitionId": entry.definition_id, "revision": entry.revision,
        "canonicalDigest": entry.canonical_digest, "nativeName": entry.native_name,
        "transport": entry.transport, "endpointFingerprint": entry.endpoint_fingerprint,
        "command": entry.command, "args": list(entry.args),
        "env": [_slot_to_payload(s) for s in entry.env],
        "url": entry.url,
        "headers": [_slot_to_payload(s) for s in entry.headers],
        "allowedToolNames": list(entry.allowed_tool_names),
        "expectedCatalogDigest": entry.expected_catalog_digest,
        "enforcement": entry.enforcement, "markers": list(entry.markers),
        "lane": entry.lane, "owner": entry.owner,
    }


def _entry_from_payload(entry: Mapping) -> NativeServerIntent:
    return NativeServerIntent(
        definition_id=entry["definitionId"], revision=int(entry["revision"]),
        canonical_digest=entry["canonicalDigest"], native_name=entry["nativeName"],
        transport=entry["transport"], endpoint_fingerprint=entry["endpointFingerprint"],
        command=entry["command"], args=tuple(entry["args"]),
        env=tuple(_slot_from_payload(s) for s in entry["env"]),
        url=entry["url"], headers=tuple(_slot_from_payload(s) for s in entry["headers"]),
        allowed_tool_names=tuple(entry["allowedToolNames"]),
        expected_catalog_digest=entry["expectedCatalogDigest"],
        enforcement=entry["enforcement"], markers=tuple(entry["markers"]),
        lane=entry["lane"], owner=entry["owner"],
    )


def facet_payload_of(intent_set: NativeIntentSet) -> dict:
    """NativeIntentSet -> the closed facet payload (validated, detached).

    The destination's ``targetPath`` is deliberately dropped: the facet
    payload is a C2 object and TargetHandle semantics say the destination
    identity is server-issued, "never a filesystem path"."""
    kind, destination = destination_of(intent_set)
    payload = {
        "harnessType": intent_set.harness_type,
        "destinationKind": kind,
        "configKey": destination.config_key,
        "configFormat": destination.config_format,
        "sessionRef": intent_set.session_ref,
        "runtimeGeneration": intent_set.runtime_generation,
        "snapshotDigest": intent_set.snapshot_digest,
        "planDigest": intent_set.plan_digest,
        "itemId": FACET_ITEM_ID,
        "markers": list(intent_set.markers),
        "entries": [_entry_to_payload(e) for e in intent_set.entries],
        "excludedManaged": [dict(r) for r in intent_set.excluded_managed],
    }
    try:
        validated = FACET_PAYLOAD_SCHEMA.validate(payload)
    except ContractError as exc:
        raise McpError(MCP_GATE_FRAGMENT_INVALID,
                       f"facet payload violates the closed mcp.servers schema: {exc}")
    return dict(validated)


def intent_set_from_payload(payload: Mapping) -> NativeIntentSet:
    """Facet payload -> domain NativeIntentSet (verify binding / round trip).

    Entries travel lane="native" only (schema-enumerated), so a managed
    definition can never be re-shaped into a native intent here; the
    excluded-managed records stay records."""
    destination = _PayloadDestination(payload["configKey"], payload["configFormat"],
                                      kind=payload["destinationKind"])
    return NativeIntentSet(
        harness_type=payload["harnessType"],
        destination=destination,
        session_ref=payload["sessionRef"],
        runtime_generation=payload["runtimeGeneration"],
        snapshot_digest=payload["snapshotDigest"],
        entries=tuple(_entry_from_payload(e) for e in payload["entries"]),
        excluded_managed=tuple(dict(r) for r in payload["excludedManaged"]),
        markers=tuple(payload["markers"]),
        plan_digest=payload["planDigest"],
    )


def observation_payload_of(observation: NativeObservation,
                           evidence_ref: Optional[str] = None) -> dict:
    """NativeObservation -> the ``verify`` observed DTO (validated)."""
    payload = {
        "observer": observation.observer,
        "evidenceRef": evidence_ref,
        "sessionRef": observation.session_ref,
        "runtimeGeneration": observation.runtime_generation,
        "servers": [
            {"serverName": s.server_name, "transport": s.transport,
             "loadState": s.load_state, "catalogDigest": s.catalog_digest,
             "toolNames": list(s.tool_names)}
            for s in observation.servers],
    }
    try:
        return dict(OBSERVED_SCHEMA.validate(payload))
    except ContractError as exc:
        raise McpError(MCP_GATE_FRAGMENT_INVALID,
                       f"observation payload violates the closed schema: {exc}")


def observation_from_payload(observed: Mapping) -> NativeObservation:
    """Observed DTO (validated by OBSERVED_SCHEMA at the adapter door) ->
    domain NativeObservation."""
    return NativeObservation(
        observer=observed["observer"],
        session_ref=observed["sessionRef"],
        runtime_generation=observed["runtimeGeneration"],
        servers=tuple(ObservedServer(
            server_name=s["serverName"], transport=s["transport"],
            load_state=s["loadState"], catalog_digest=s["catalogDigest"],
            tool_names=tuple(s["toolNames"])) for s in observed["servers"]))


# -- C2 surface: assessment ------------------------------------------------------


def assessment_from_verdict(result: AssessResult,
                            *, evidence_ref: Optional[str] = None) -> Assessment:
    """Domain three-valued verdict -> the real ``Assessment``.

    Honesty guard on the ``supported`` edge: a verdict may only map to
    ``supported`` when it carries the runtime-evidence reason AND an
    evidence ref; anything else downgrades to ``unknown`` — an adapter
    can never upgrade its own guess into ``supported`` through this door."""
    if result.verdict == VERDICT_SUPPORTED:
        if "runtime-evidence-proven" in result.reasons and evidence_ref:
            return Assessment("supported", evidence_ref=evidence_ref)
        return Assessment("unknown",
                          reason="supported-verdict-without-runtime-evidence-downgraded")
    if result.verdict == VERDICT_UNSUPPORTED:
        return Assessment("unsupported",
                          reason=";".join(result.reasons) or "structurally-unsupported")
    return Assessment("unknown",
                      reason=";".join(result.reasons) or "native-route-unproven")


def _brand_target(context: AdapterContext, brand, destination_kind: str):
    """The context target serving one destination kind for one brand, or None.

    instance-config -> a file target of the brand codec at instance scope;
    session-override -> the same codec at session scope (the API models the
    session config overlay as a session-scoped structured target; the C3
    slice merges both the same way)."""
    want_scope = "instance" if destination_kind == DESTINATION_INSTANCE_CONFIG else "session"
    for target in context.targets:
        if (target.kind == "file" and target.codec == brand.config_format
                and target.scope == want_scope):
            return target
    return None


def _field_authorizes(target: TargetDescriptor, field: Tuple[str, ...]) -> bool:
    return any(list(field[:len(allowed)]) == list(allowed) or tuple(allowed) == field
               for allowed in target.allowed_fields)


def assess_for_context(brand, context: AdapterContext, request: Any) -> Assessment:
    """C2 ``assess`` over harness-supplied facts (AdapterContext + payload).

    Structural infeasibility (blocked destination, harness id mismatch, no
    brand target of the right codec/scope, the brand slot not authorised by
    the target descriptor) is typed ``unsupported``; a structurally possible
    brand route without controlled runtime evidence stays ``unknown`` —
    both brands sit there today (proven_routes empty), never fake green."""
    payload = request if isinstance(request, Mapping) and "harnessType" in request else None
    kind = (payload["destinationKind"] if payload is not None
            else brand.default_destination_kind)
    installation = context.installation
    if payload is not None and payload["harnessType"] != brand.harness_type:
        return Assessment("unsupported",
                          reason=f"harness-id-mismatch:payload={payload['harnessType']}")
    if installation.harness_id != brand.harness_type:
        return Assessment("unsupported",
                          reason=f"harness-id-mismatch:{installation.harness_id}")
    blocked = brand.blocked_destinations.get(kind)
    if blocked:
        return Assessment("unsupported", reason=str(blocked))
    if context.entry not in ENTRIES:
        return Assessment("unsupported", reason=f"unknown-entry:{context.entry}")
    target = _brand_target(context, brand, kind)
    if target is None:
        return Assessment("unsupported", reason=f"no-brand-target:{kind}:{brand.config_format}")
    if not any(path and path[0] == brand.config_key for path in target.allowed_fields):
        return Assessment("unsupported", reason="slot-key-mismatch")
    if (brand.harness_type, kind) in brand.proven_routes and installation.evidence_ref:
        return Assessment("supported", evidence_ref=installation.evidence_ref)
    return Assessment("unknown", reason=brand.unknown_reason)


# -- C2 surface: compile ---------------------------------------------------------


def _refusal(code: ErrorCode, reason: str) -> AdapterRefusal:
    return AdapterRefusal(code, reason)


def _native_value(entry: Mapping, drop_slots: Tuple[str, ...]) -> dict:
    """One planned server -> the native config object written under its key.

    Only literals can live in the file value; a secretRef slot is either a
    ``BindSecret`` (``drop_slots``) or a typed refusal BEFORE this point —
    there is no branch here that could serialise a plaintext, matching the
    domain DTO's absence of a plaintext shape."""
    names = set(drop_slots)
    if entry["transport"] == "stdio":
        return {
            "command": entry["command"],
            "args": list(entry["args"]),
            "env": {s["name"]: s["value"] for s in entry["env"]
                    if s["kind"] == "literal" and s["name"] not in names},
        }
    return {
        "url": entry["url"],
        "headers": {s["name"]: s["value"] for s in entry["headers"]
                    if s["kind"] == "literal" and s["name"] not in names},
    }


def compile_intent_set(brand, context: AdapterContext, desired: Any) -> Any:
    """Facet payload -> real ``IntentSet`` (or typed ``AdapterRefusal``).

    Guards executed here, on the real API types:
    * closed-object schema (undeclared field, plaintext-bearing key, wrong
      lane -> ``ContractError`` -> INVALID_FRAGMENT refusal);
    * cross-brand payload -> TARGET_CONFLICT refusal (the claude adapter
      cannot eat a codex plan and vice versa);
    * the brand slot (configKey/configFormat) and the destination-scope
      target must exist in THIS context and authorise every written field
      path -> otherwise CAPABILITY_UNSUPPORTED / TARGET_CONFLICT refusals;
      a handle that is not in the context targets can never be emitted;
    * managed/native mutual exclusion re-check: an entry endpoint that also
      appears in ``excludedManaged`` -> TARGET_CONFLICT (defense in depth on
      top of the domain compile refusal); duplicate nativeName likewise;
    * secretRef slots require an environment target whose allowed fields
      name the exact slot (the C3 merge admits BindSecret only there);
      without that surface the compile refuses typed — it never degrades
      into a plaintext write (t04-adapters.md §3 G2 hard clause)."""
    from ordessa_harness_api import BindSecret, IntentSource

    if desired is None:
        # DesiredFragment operation="reset" arrives with no value; deleting
        # previously owned servers needs the owned-name enumeration the C2
        # signature does not carry -> honest typed refusal, no guessing.
        return _refusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                        "reset compilation is not carried by the T013 binding "
                        "(no owned-name enumeration in the C2 signature)")
    try:
        payload = dict(FACET_PAYLOAD_SCHEMA.validate(desired))
    except ContractError as exc:
        return _refusal(ErrorCode.INVALID_FRAGMENT, f"facet payload invalid: {exc}")
    if payload["harnessType"] != brand.harness_type:
        return _refusal(ErrorCode.TARGET_CONFLICT,
                        f"payload brand {payload['harnessType']!r} cannot compile "
                        f"on {brand.harness_type}")
    if payload["itemId"] != FACET_ITEM_ID:
        return _refusal(ErrorCode.INVALID_FRAGMENT, "unknown facet item")
    if payload["configKey"] != brand.config_key or payload["configFormat"] != brand.config_format:
        return _refusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                        "destination descriptor does not match the brand's config slot")
    kind = payload["destinationKind"]
    blocked = brand.blocked_destinations.get(kind)
    if blocked:
        return _refusal(ErrorCode.CAPABILITY_UNSUPPORTED, f"{brand.harness_type}:{blocked}")
    target = _brand_target(context, brand, kind)
    if target is None:
        return _refusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                        f"no {brand.config_format} file target at "
                        f"{kind}-scope in the supplied context")
    env_targets = [t for t in context.targets
                   if t.kind == "environment" and t.scope == target.scope]
    managed_endpoints = {r["endpointFingerprint"] for r in payload["excludedManaged"]}
    source = IntentSource(FACET_ID, FACET_ITEM_ID, FACET_SCHEMA_VERSION)
    intents = []
    seen_names: set = set()
    for entry in payload["entries"]:
        name = entry["nativeName"]
        if name in seen_names:
            return _refusal(ErrorCode.TARGET_CONFLICT,
                            f"duplicate nativeName {name!r} in one complete set")
        seen_names.add(name)
        if entry["endpointFingerprint"] in managed_endpoints:
            return _refusal(ErrorCode.TARGET_CONFLICT,
                            f"{name}: endpoint is also leased managed "
                            "(projection and lease are mutually exclusive)")
        field = (brand.config_key, name)
        if not _field_authorizes(target, field):
            return _refusal(ErrorCode.TARGET_CONFLICT,
                            f"target {target.handle.handle_id} does not authorise "
                            f"field {'/'.join(field)}")
        drop = []
        secret_intents = []
        for slot in list(entry["env"]) + list(entry["headers"]):
            if slot["kind"] != "secretRef":
                if looks_secret_name(slot["name"]):
                    # a literal under a secret-shaped name: the API would
                    # reject the SetField anyway; refuse with the domain's
                    # own words instead of a ContractError crash.
                    return _refusal(ErrorCode.INVALID_FRAGMENT,
                                    f"slot {slot['name']!r} of {name!r} looks "
                                    "secret-bearing; secrets travel as refs")
                continue
            slot_id = f"{name}.{slot['name']}"
            env_target = next((t for t in env_targets
                               if (slot_id,) in [tuple(a) for a in t.allowed_fields]), None)
            if env_target is None:
                return _refusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                                f"secretRef slot {slot_id!r} of {name!r} has no "
                                "authorised environment binding target in this "
                                "context; a native intent may never carry the "
                                "plaintext substitute (G2 hard clause)")
            secret_intents.append(BindSecret(
                source, env_target.handle, slot_id,
                slot["credentialRef"] or "credential-ref-missing"))
            drop.append(slot["name"])
        value = _native_value(entry, tuple(drop))
        try:
            intents.append(SetField(source, target.handle, FieldPath(field), value))
        except ContractError as exc:
            return _refusal(ErrorCode.INVALID_FRAGMENT,
                            f"set-field rejected by the sealed API: {exc}")
        intents.extend(secret_intents)
    try:
        return IntentSet(tuple(intents))
    except ContractError as exc:
        return _refusal(ErrorCode.INVALID_FRAGMENT, f"intent set rejected: {exc}")


# -- C2 surface: verify ------------------------------------------------------------


def verification_from_result(intent_set: NativeIntentSet, observation: NativeObservation,
                             *, evidence_ref: Optional[str],
                             verify_fn: Callable[[NativeIntentSet, NativeObservation], Any],
                             ) -> Any:
    """VerifyResult facts -> the real ``Verification`` union (honest edges).

    ``verify_fn`` is the brand module's pure ``verify_native`` (injected at
    the adapter door; the binding never re-implements the fact logic).

    * any definite contradiction (instance identity mismatch, transport
      mismatch, catalog changed) -> ``Mismatch`` — and the mapping has no
      path from a contradiction to ``Match``;
    * everything loaded AND the observer attests an evidence ref ->
      ``Match(evidence_ref)``; a runtime-loaded claim without attestation
      is unverified -> ``VerificationUnknown`` (no fake confirmation);
    * projected-only (config-bytes-match) and any unknown/absent fact ->
      ``VerificationUnknown`` with the domain reason relayed."""
    if not intent_set.entries:
        return VerificationUnknown("empty-native-set:no-facts-to-confirm")
    result = verify_fn(intent_set, observation)
    rows = [(f.fact, f.reason, f.native_name) for f in result.facts]
    contradictions = [row for row in rows
                      if row[1] in ("instance-identity-mismatch", "transport-mismatch")
                      or row[0] == FACT_CATALOG_CHANGED]
    if contradictions:
        kind, reason, name = contradictions[0]
        return Mismatch(f"{kind}:{reason} for {name}")
    if any(row[0] == FACT_UNKNOWN for row in rows):
        first = next(row for row in rows if row[0] == FACT_UNKNOWN)
        return VerificationUnknown(f"{first[1]}:{first[2]}")
    if any(row[0] == FACT_PROJECTED for row in rows):
        # bytes matched; load was never attested — NEVER Match (honesty rule)
        return VerificationUnknown("projected-only:config-bytes-match attests "
                                   "projection, not runtime load")
    # all facts loaded
    if not evidence_ref or not observation.observer:
        return VerificationUnknown("observer-attestation-missing:runtime-loaded "
                                   "claims need an observer evidence ref before "
                                   "anything is confirmed")
    return Match(evidence_ref)


def verification_from_config_readback(payload: Mapping, readback: Any) -> Any:
    """C4 apply hands ``verify`` the NATIVE CONTENT readback (the materialized
    generation parsed), not an observer attestation. A byte/content equality
    is exactly ``config-bytes-match`` → at most projected → NEVER ``Match``
    (harness-adapters.md:15); an absent or differing planned server is a
    definite contradiction → ``Mismatch``; anything uninterpretable is
    ``VerificationUnknown``. Confirmation (``Match``) is reserved for the
    observer-attested ``OBSERVED_SCHEMA`` shape (runtime load relayed)."""
    if not isinstance(readback, Mapping):
        return VerificationUnknown("readback-not-structured-content")
    servers = readback.get(payload["configKey"])
    if not isinstance(servers, Mapping):
        return VerificationUnknown("readback-has-no-brand-slot-content")
    if not payload["entries"]:
        return VerificationUnknown("empty-native-set:no-facts-to-confirm")
    for entry in payload["entries"]:
        planned = _native_value(entry, ())
        observed_value = servers.get(entry["nativeName"])
        if observed_value is None:
            return Mismatch(f"planned-server-absent-from-readback:{entry['nativeName']}")
        if not _values_equal(planned, observed_value):
            return Mismatch(f"readback-mismatch:{entry['nativeName']}")
    return VerificationUnknown(
        "projected-only:content readback matched the plan bytes-for-bytes, "
        "which attests projection, not runtime load")


def _values_equal(left: Any, right: Any) -> bool:
    return (json.dumps(left, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            == json.dumps(right, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


# -- the real ConfigurationAdapter surface (facet mcp.servers) --------------------


def configuration_descriptor(brand, *,
                             native_versions: Tuple[int, int, int] = (0, 0, 0),
                             adapter_versions: Tuple[int, int, int] = (1, 0, 0),
                             extra_claims: Tuple[FieldClaim, ...] = ()) -> ConfigurationAdapterDescriptor:
    """Descriptor for one brand's MCP configuration adapter.

    The claim target ids are the handle identities the composition/C1 must
    issue for this facet (``assets.mcp.<harness>.instance-config`` /
    ``.session-override``); a runtime whose targets carry different handle
    ids is refused by the claim check at the service door — the handle is
    never assumed (contracts §3: the native target belongs to C1)."""
    harness = brand.harness_type
    claims = (
        FieldClaim("file", instance_target_id(harness), (brand.config_key,)),
        FieldClaim("file", session_target_id(harness), (brand.config_key,)),
    ) + tuple(extra_claims)
    return ConfigurationAdapterDescriptor(
        f"assets.mcp.{harness}.native", POINT_API_VERSION, FACET_ID,
        FACET_SCHEMA_VERSION, harness,
        VersionRange(native_versions), VersionRange(adapter_versions),
        ENTRIES, FACET_PAYLOAD_SCHEMA, claims,
    )


def _context_key(context: AdapterContext):
    return (context.installation.harness_id, context.entry, context.scope,
            tuple((t.handle.handle_id, t.handle.generation) for t in context.targets))


class McpNativeConfigurationAdapter:
    """One brand's real ``ConfigurationAdapter`` (the C2 Protocol).

    Registration is the product assembly's move — a
    ``Contribution(CONFIGURATION_POINT_ID, "v1", <instance>)`` under the
    declared ``harness.configuration-adapters@v1`` point (a plain host
    without the point refuses admission, so the plugin builds these through
    the opt-in factory, never unconditionally). ``verify`` binds to the
    plan this adapter instance compiled FOR THE SAME CONTEXT: an observer
    arriving under a changed context (other handle generations, other
    entry/scope — the cross-target/cross-instance spoof shape) never
    reaches the fact logic and answers ``VerificationUnknown``, not a
    confirmation.
    """

    def __init__(self, brand, *, verify_fn, descriptor=None) -> None:
        self.brand = brand
        self._verify_fn = verify_fn
        self.descriptor = descriptor or configuration_descriptor(brand)
        self._bound: dict = {}

    def assess(self, context: AdapterContext, request) -> Assessment:
        return assess_for_context(self.brand, context, request)

    def compile(self, context: AdapterContext, before, desired):
        outcome = compile_intent_set(self.brand, context, desired)
        if isinstance(outcome, IntentSet) and isinstance(desired, Mapping):
            # store a detached, validated copy of the payload as the
            # expectation verify is bound against
            self._bound[_context_key(context)] = dict(validate_json(desired))
        return outcome

    def verify(self, context: AdapterContext, observed) -> Any:
        key = _context_key(context)
        stored = self._bound.get(key)
        if stored is None:
            # cross-target/cross-instance spoof shape: an observer arriving
            # under a context this adapter never compiled for cannot reach
            # the fact logic, and is never a confirmation
            return VerificationUnknown("no-compiled-plan-bound-for-this-context")
        if isinstance(observed, Mapping) and "observer" in observed:
            try:
                payload = dict(OBSERVED_SCHEMA.validate(observed))
            except ContractError as exc:
                return VerificationUnknown(f"observation-shape-invalid:{exc}")
            intent_set = intent_set_from_payload(stored)
            observation = observation_from_payload(payload)
            return verification_from_result(intent_set, observation,
                                            evidence_ref=payload["evidenceRef"],
                                            verify_fn=self._verify_fn)
        if isinstance(observed, Mapping) and self.brand.config_key in observed:
            return verification_from_config_readback(stored, observed)
        return VerificationUnknown("observation-shape-invalid:not-an-observer-dto")


# -- C4 application-port converters ----------------------------------------------


def application_target(*, server_scope: str, session_ref: str,
                       target_session: Optional[str], harness: Optional[str],
                       runtime_generation: int) -> ApplicationTarget:
    """Q4 submission params -> the real ``ApplicationTarget``.

    Mapping decision (the API carries no Q4 lane/scope semantics; the Q4
    side keeps this naming layer — registered in reports/t013): server_id
    is the MCP server scope, session_id the caller's session ref,
    channel_id the target session (the channel the effective set is planned
    for) falling back to the harness brand, then ``mcp-plan``. All fields
    are bounded non-empty by the API itself."""
    channel = target_session or harness or "mcp-plan"
    return ApplicationTarget(server_scope, session_ref, channel,
                             int(runtime_generation))


def desired_fragment(payload: Mapping, *, source_revision: str,
                     business_ref: str) -> DesiredFragment:
    """Validated facet payload -> the C4 ``DesiredFragment`` (operation set).

    ``DesiredFragment`` seals its value as an immutable JSON snapshot — a
    later mutation of the caller's dict cannot reach the plan."""
    return DesiredFragment(FACET_ID, FACET_ITEM_ID, FACET_SCHEMA_VERSION,
                           business_ref, source_revision, "set", dict(payload))


def launch_request(target_handle: TargetHandle, configuration_snapshot_ref: str,
                   *, native_session_identity: Optional[str] = None) -> LaunchRequest:
    """The launch shape bound to one plan's snapshot reference.

    The API's own validation is the guard: the handle must be a real
    server-issued ``TargetHandle`` ("never a filesystem path"), the
    snapshot ref a non-empty opaque reference. The submission plan output
    carries those identity fields so a later prepare/apply binds to them."""
    if not isinstance(target_handle, TargetHandle):
        raise McpError(MCP_GATE_FRAGMENT_INVALID,
                       "launch request needs the harness-issued TargetHandle")
    try:
        return LaunchRequest(target_handle, configuration_snapshot_ref,
                             native_session_identity)
    except ContractError as exc:
        raise McpError(MCP_GATE_FRAGMENT_INVALID, f"launch request invalid: {exc}")


def plan_view(plan: Plan) -> dict:
    return {
        "kind": "plan", "planId": plan.plan_id,
        "desiredDigest": plan.desired_digest, "beforeRevision": plan.before_revision,
        "nativeVersionRef": plan.native_version_ref,
        "providerGeneration": plan.provider_generation,
        "authorizationRevision": plan.authorization_revision,
        "secretRefRevision": plan.secret_ref_revision,
        "expiresAtUtc": plan.expires_at_utc,
    }


#: C4 Refused codes -> the MCP domain's codes (families declared in
#: backend/plugin.MCP_ERROR_FAMILIES). expectedRevision drift is the CAS
#: conflict it always was; a missing adapter is the missing application
#: port; capability/version shapes stay capability refusals.
_REFUSAL_CODES = {
    ErrorCode.ADAPTER_MISSING: _APPLICATION_PORT_ABSENT,
    ErrorCode.VERSION_UNVERIFIED: MCP_GATE_CAPABILITY_UNSUPPORTED,
    ErrorCode.CAPABILITY_UNSUPPORTED: MCP_GATE_CAPABILITY_UNSUPPORTED,
    ErrorCode.INVALID_FRAGMENT: MCP_GATE_FRAGMENT_INVALID,
    ErrorCode.TARGET_CONFLICT: MCP_OWNER_CONFLICT,
    ErrorCode.STALE_PLAN: MCP_CAS_CONFLICT,
    ErrorCode.AUTHORIZATION_REFUSED: PERMISSION_REFUSED,
    ErrorCode.ISOLATION_UNPROVEN: MCP_ISOLATION_UNPROVEN,
    ErrorCode.BUSY: MCP_GATE_BUSY,
    ErrorCode.RESUME_UNAVAILABLE: MCP_GATE_RESUME_UNAVAILABLE,
    ErrorCode.VERIFICATION_MISMATCH: MCP_VERIFICATION_MISMATCH,
    ErrorCode.OPERATION_UNKNOWN: UNKNOWN_OUTCOME,
}


def refused_to_mcp_error(refused: Refused) -> McpError:
    """A real ``Refused`` never becomes a success and never re-drives the
    gate: the diagnostics travel with the typed refusal (they are the API's
    own non-blank strings — no plaintext can hide in them)."""
    code = _REFUSAL_CODES.get(refused.code, MCP_GATE_REFUSED)
    detail = "; ".join(refused.diagnostics) or refused.code.value
    return McpError(code, f"the harness configuration service refused the plan: {detail}")


def unknown_to_mcp_error(unknown: Unknown) -> McpError:
    """``Unknown`` keeps the harness semantics: effects happened or their
    state is unread; the allowed next action is reconcile/query — never a
    silent re-configure and never a launch."""
    return McpError(
        UNKNOWN_OUTCOME,
        f"submission state is unknown (phase {unknown.phase}, next action "
        f"{unknown.allowed_next_action}, pending checks: "
        f"{', '.join(unknown.pending_checks)}); reconcile before any further action")


def runtime_unknown_view(result) -> dict:
    """``Unknown`` / ``RuntimeUnknown`` -> the audit view (observed effects
    and pending checks only; instance refs stay opaque handles)."""
    if isinstance(result, Unknown):
        return {"kind": "unknown", "phase": result.phase,
                "observedEffects": list(result.observed_effects),
                "pendingChecks": list(result.pending_checks),
                "allowedNextAction": result.allowed_next_action}
    if type(result).__name__ == "RuntimeUnknown":
        return {"kind": "unknown", "phase": "reconciling",
                "observedEffects": list(result.observed_effects),
                "pendingChecks": list(result.pending_checks),
                "allowedNextAction": "reconcile"}
    raise McpError(MCP_GATE_FRAGMENT_INVALID, "not an unknown-shaped result")


def reconfiguration_view(decision: ReconfigurationDecision) -> dict:
    """``ReconfigurationDecision`` -> the plan-side posture view. The mode
    vocabulary (session-local / reload / restart-resume / unsupported) is
    relayed verbatim; an unsupported decision with its reason is shown, not
    hidden (contracts §3: reconfiguration belongs to the harness)."""
    return {"mode": decision.mode,
            "affectedInstanceRefs": list(decision.affected_instance_refs),
            "reason": decision.reason}

