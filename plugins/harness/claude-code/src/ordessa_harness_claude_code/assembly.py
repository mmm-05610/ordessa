"""Explicit production assembly of the Claude family provider.

One entry point builds the production-wirable provider from explicit ports
only: the deployment's assembled owner view (records + verifier), the
owner-projection authority hooks, an owned-channel registry, the SDK session
owner and optional start-bridge and connection-entrance ports. Every dependent
capability is advertised only when its exact ports are composed; missing or
inconsistent ports are typed refusals at assembly time — a half-composed
provider is never returned and no method is ever advertised merely because a
port is importable.

The projection here reads only through the records owner's ``owner_read_*``
projection. Nothing in this module installs a package, probes a login,
contacts a network or creates an ambient SDK fallback. The default-product
assembly refuses on any failed port; there is no fallback path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.public import UnitInspection

from .configuration_face import ClaudeConfigurationFace
from .owner_projection import ClaudeOwnerUnitProjection
from .ownership import ClaudeOwnedChannels
from .provider import ClaudeCodeRuntimeProvider, ClaudeProviderUnavailable
from .termination import ClaudeTerminationCoordinator, ClaudeTerminationEffects


class ClaudeAssemblyRefused(ClaudeProviderUnavailable):
    code = "CLAUDE_ASSEMBLY_REFUSED"


RECORDS_METHODS = (
    "owner_read_unit", "owner_read_session", "owner_read_unit_confirmation",
    "begin_unit", "record_unit", "read_unit_confirmation", "reconcile_unit_confirmation",
    "begin_termination", "record_termination", "reconcile_termination", "owner_read_termination",
    "begin_configuration_change", "bind_configuration_dispatch",
    "record_configuration_change", "query_configuration_change",
)
EVIDENCE_METHODS = {
    "native_unit": ("verify_unit_binding",),
    "termination": ("verify_termination",),
    "configuration": ("verify_configuration", "capture_configuration"),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ClaudeProductionWiring:
    provider: ClaudeCodeRuntimeProvider
    projection: ClaudeOwnerUnitProjection
    termination: ClaudeTerminationCoordinator
    configuration_face: ClaudeConfigurationFace
    channels: ClaudeOwnedChannels
    access_owner: Any


def _require_port(value, label, methods):
    if value is None:
        raise ClaudeAssemblyRefused(f"owner port {label!r} is required")
    for method in methods:
        if not callable(getattr(value, method, None)):
            raise ClaudeAssemblyRefused(f"owner port {label!r} exposes no callable {method!r}")
    return value


class ClaudeAccessOwner:
    """Read-access face over the owner projection; never a live SDK escape.

    ``inspect_unit`` returns the typed current UnitInspection from the owner
    projection's publication facts; ``describe_access`` reports the confirmed
    native access facts. ``connect`` requires an explicitly wired entrance
    port bound to that unit's live owned session: without one it stays refused
    and unadvertised. This owner never exposes a raw SDK, channel or writer.
    """

    def __init__(self, *, records, verifier, projection, channels, entrance_port=None):
        self.records, self.verifier, self.projection = records, verifier, projection
        self._channels, self._entrance = channels, entrance_port
        methods = ["inspect_unit", "describe_access"]
        if entrance_port is not None and callable(getattr(entrance_port, "bind", None)):
            methods.append("connect")
        self.supported_methods = tuple(methods)

    def inspect_unit(self, unit_ref):
        unit = self.projection.read_unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed":
            raise ClaudeAssemblyRefused("current native unit observation requires a confirmed binding")
        facts = self.projection.publication_facts(unit_ref)
        ownership = facts.get("ownership")
        if ownership not in ("owned", "borrowed", "unknown"):
            raise ClaudeAssemblyRefused("publication owner facts are incomplete")
        return UnitInspection(unit_ref, facts["providerRef"], facts["configurationTargetRef"],
                              _directory_ref(facts["directoryBindingRef"]), facts["managementEpoch"],
                              ownership, facts["sourceRevision"], _now(), facts["evidenceRef"])

    def describe_access(self, unit_ref):
        unit = self.projection.read_unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed":
            raise ClaudeAssemblyRefused("native access requires the confirmed original binding")
        return {"protocol": "claude-agent-sdk", "unitRef": unit.public_ref,
                "fullNativeSideEffects": True, "leaseRequired": True,
                "readonlySupported": False, "nativeRealm": "claude-agent-sdk"}

    def connect(self, unit_ref, authorized_lease):
        if not callable(getattr(self._entrance, "bind", None)):
            raise ClaudeAssemblyRefused("no wired live session connection entrance")
        return self._entrance.bind(unit_ref, authorized_lease)


def _directory_ref(value):
    if not isinstance(value, Mapping):
        raise ClaudeAssemblyRefused("publication directory binding differs")
    try:
        return DirectoryBindingRef.from_dict(dict(value))
    except (KeyError, TypeError, ValueError) as error:
        raise ClaudeAssemblyRefused("publication directory binding differs") from error


def assemble_claude_provider(*, definition_ref, implementation_digest, records, verifier,
                             publication_owner, owned_channels, session_owner,
                             preparation_authority=None, start_authority=None,
                             configuration_authority=None, native_unit_effects=None,
                             native_unit_observations=None, entrance_port=None):
    """Compose the one production provider; refuse any missing or foreign port."""
    _require_port(records, "records", RECORDS_METHODS)
    if verifier is None or getattr(records, "verifier", None) is not verifier:
        raise ClaudeAssemblyRefused("owner view records must consume the same verifier")
    _require_port(getattr(records, "termination_evidence", None), "termination_evidence",
                  EVIDENCE_METHODS["termination"])
    _require_port(getattr(records, "configuration_evidence", None), "configuration_evidence",
                  EVIDENCE_METHODS["configuration"])
    if native_unit_effects is not None:
        _require_port(getattr(records, "native_unit_evidence", None), "native_unit_evidence",
                      EVIDENCE_METHODS["native_unit"])
    channels = owned_channels if isinstance(owned_channels, ClaudeOwnedChannels) else None
    if channels is None or not all(callable(getattr(channels, name, None))
                                   for name in ("register", "entry", "is_owned", "release")):
        raise ClaudeAssemblyRefused("owned native channel registry is required for stop/release effects")
    for method in ("session_apply_model", "observe_model", "observe_session"):
        if not callable(getattr(session_owner, method, None)):
            raise ClaudeAssemblyRefused("session owner exposes no callable %r" % method)
    if not callable(publication_owner):
        raise ClaudeAssemblyRefused("core publication owner is required")
    projection = ClaudeOwnerUnitProjection(
        records, verifier=verifier, preparation_authority=preparation_authority,
        start_authority=start_authority, configuration_authority=configuration_authority,
        publication_owner=publication_owner)
    termination_effects = ClaudeTerminationEffects(channels, records.termination_evidence)
    termination = ClaudeTerminationCoordinator(records=records, verifier=verifier,
                                               projection=projection, effects=termination_effects)
    configuration_face = ClaudeConfigurationFace(records=records, verifier=verifier,
                                                 projection=projection,
                                                 session_owner=session_owner)
    access_owner = ClaudeAccessOwner(records=records, verifier=verifier, projection=projection,
                                     channels=channels, entrance_port=entrance_port)
    provider = ClaudeCodeRuntimeProvider(
        definition_ref=definition_ref, implementation_digest=implementation_digest,
        verifier=verifier, unit_records=records, unit_port=access_owner,
        preparation_authority=preparation_authority,
        unit_projection=projection, native_unit_effects=native_unit_effects,
        native_unit_observations=native_unit_observations, termination=termination,
        configuration_face=configuration_face)
    for method in access_owner.supported_methods:
        if method not in provider.descriptor.supported_methods:
            raise ClaudeAssemblyRefused("provider access surface is inconsistent")
    if ("stop" not in provider.descriptor.supported_methods
            or "release" not in provider.descriptor.supported_methods
            or "apply_configuration" not in provider.descriptor.supported_methods
            or "query_change" not in provider.descriptor.supported_methods):
        raise ClaudeAssemblyRefused("assembled management surface is not renderable")
    return ClaudeProductionWiring(provider=provider, projection=projection,
                                 termination=termination, configuration_face=configuration_face,
                                 channels=channels, access_owner=access_owner)


def assemble_sdk_session(native, authority, *, dispatch_listener=None, options=None,
                         sdk_factory=None, native_session_id=None):
    """Wire the explicitly fenced SDK transport and session; no ambient default.

    ``native`` must be the deployment-isolated transport with the SDK's public
    native surface; ``authority.dispatch_guard`` is the port rechecked for
    EVERY SDK write. ``dispatch_listener`` is the ledger's pre-send binding
    hook (for example ``face.dispatch_listener(unit_ref)``). The installed SDK
    factory is required at run time; the launcher never installs a package.
    """
    from .sdk import ClaudeSdkSession, FencedSdkTransport
    transport = FencedSdkTransport(native, authority, dispatch_listener=dispatch_listener)
    return ClaudeSdkSession(transport=transport, options=options, sdk_factory=sdk_factory,
                            native_session_id=native_session_id)
