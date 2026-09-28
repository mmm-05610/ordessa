"""Declaration of the brand adapters on the real Harness public point.

Since the foundation checkpoint the platform ships a public contribution
seam: the point id ``harness.configuration-adapters`` (API version ``v1``)
is declared by the product composition and bound to the harness-side
conflict registry; plugins only *declare* `Contribution` entries on their
registration. This module builds those declarations - it admits nothing:
duplicate/overlap refusal, field-claim conflicts, owner injection and
publish-on-commit are all performed by the platform.

Each brand ships a callable `PolicyConfigurationAdapter` carrying one
`ConfigurationAdapterDescriptor` under the facet ``permissions.policy-adapters``.
The carrier delegates controlled compilation to the measured C1 brand adapter;
without a trusted snapshot/ceiling resolver it refuses configuration writes.

* `harness_id` / `native_versions` are the pins compiled against
  (`PINNED_NATIVE_VERSIONS`); a drift test parses the real registry file
  (`harnesses.toml` identity versions) and refuses silent drift - a pin
  bump must land with an explicit claim update here.
* `adapter_versions` is the exact release pin of THIS distribution
  (`pyproject.toml`: `version = "0.1.0"`), the only runtime-adapter version
  fact this tree backs - see `_ADAPTER_VERSION` below and
  `tests/test_adapter_version_evidence.py`; it is never an unbounded
  self-declared minimum.
* `entries` are the native fields the projection writes, measured in the
  compat layer (`posture_config.py` writable paths; Pi's gate fields are
  extension-scoped, not native-file fields).
* `claims` are real `FieldClaim` objects for the fields the Permissions
  projection genuinely owns. `sandbox_mode` is deliberately NOT claimed:
  contracts.md §C2 pre-allocates it to the Sandbox facet, and field claims
  are exactly where the two domains must be disjoint - the platform's
  conflict gate refuses two facets claiming one field, by composition, not
  by priority.
* `payload_schema` is the public contract schema type (closed object:
  `additional_properties` is False), so an out-of-shape facet payload is a
  platform-side refusal.

Boundary: only the published contracts are imported here
(`server_plugin_api`, the harness public API package) - never the harness
plugin implementation, never the host. The public seam's constants
(point id, API version) are mirrored as literals by plugin convention
(the platform's own external-adapter exemplar does the same); the tests
pin them against the seam so a drift is a red test, not a silent split-brain.
"""
from __future__ import annotations

import re
from typing import Callable

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    ErrorCode, FieldClaim, FieldPath, IntentSet, IntentSource, SetField,
    ValueSchema, VerificationUnknown, VersionRange,
)
from server_plugin_api import Contribution, ContributionBatch

from .claude_code import ClaudeAdapter
from .codex import CodexAdapter
from .pi import PiAdapter
from .dto import PolicyCompileSnapshot, SupportEvidence
from .results import CompiledIntentSet, SupportOutcome

__all__ = [
    "CONFIGURATION_POINT",
    "FACET_ID",
    "FACET_SCHEMA_VERSION",
    "PINNED_NATIVE_VERSIONS",
    "POINT_API_VERSION",
    "configuration_descriptor",
    "PolicyConfigurationAdapter",
    "default_adapters",
    "default_configuration_descriptors",
    "policy_adapter_contributions",
    "select_adapter",
]

#: The real Harness public contribution point for configuration adapters.
CONFIGURATION_POINT = "harness.configuration-adapters"
POINT_API_VERSION = "v1"
#: The Permissions facet within that point (contracts.md §C1 contract name;
#: `permissions.policy-adapters@1` reads as facet `permissions.policy-adapters`
#: at api_version `v1`).
FACET_ID = "permissions.policy-adapters"
FACET_SCHEMA_VERSION = "v1"

#: The pins this package was compiled against, per harness id, as recorded by
#: the harness registry file's identity versions. A test parses that file and
#: fails if a pin moves without the claim here moving with it.
PINNED_NATIVE_VERSIONS = {
    "claude-code": "0.81.2",
    "codex": "2.0",
    "pi": "2.0",
}

#: The measured writable native fields per brand (compat posture surface).
_ENTRIES = {
    "claude-code": ("permissions.ask", "permissions.deny"),
    "codex": ("sandbox_mode", "approval_policy"),
    # Pi writes through the extension gate, not a native config file: these
    # are extension-scoped fields, which is why the pi descriptor claims
    # nothing.
    "pi": ("toolCallGate.extensionId", "toolCallGate.ask", "toolCallGate.deny"),
}

#: Field paths the Permissions projection genuinely owns (posture_config.py
#: writable paths, minus what §C2 pre-allocates to the Sandbox facet). The
#: target ids name the native config files the writes land in.
_CLAIMS = {
    "claude-code": (
        FieldClaim("file", ".claude/settings.json", ("permissions", "ask")),
        FieldClaim("file", ".claude/settings.json", ("permissions", "deny")),
    ),
    "codex": (
        FieldClaim("file", ".codex/config.toml", ("approval_policy",)),
    ),
    "pi": (),
}

_STRING_ARRAY = ValueSchema("array", items=ValueSchema("string"))

_PAYLOAD_FIELDS = {
    "claude-code": {"permissions.ask": _STRING_ARRAY,
                    "permissions.deny": _STRING_ARRAY},
    "codex": {"sandbox_mode": ValueSchema("string", enum=("read-only", "workspace-write")),
              "approval_policy": ValueSchema("string", enum=("untrusted", "on-request"))},
    "pi": {"toolCallGate.extensionId": ValueSchema("string"),
           "toolCallGate.ask": _STRING_ARRAY,
           "toolCallGate.deny": _STRING_ARRAY},
}

#: The adapter-side version of these declarations, pinned EXACTLY to this
#: distribution's own release fact: `version = "0.1.0"`
#: (`plugins/permissions/adapters/pyproject.toml:7`), the only version fact
#: this package can back. The former `VersionRange((1, 0, 0))` = `[1.0.0, ∞)`
#: was a self-declared minimum with an unbounded maximum: no observation in
#: this tree backs open-ended runtime-adapter support
#: (`RuntimeAdapter.describe_installation()` has no production implementer
#: here - the only in-tree Installation is the controlled fixture at
#: `plugins/harness/tests/fixtures/external_adapter/.../__init__.py:69`), and
#: the unbounded range was disjoint from the Sandbox facet's exact pin
#: (`_ADAPTER_VERSIONS` in the Sandbox adapters package, points.py:66),
#: making a real-product two-facet joint admission version-wise unsatisfiable
#: (C0 finding, `specs/011-c0-foundation-harness/api-requests.md`). This is a
#: narrowing-to-a-measured-fact, not a widening; a drift test
#: (`tests/test_adapter_version_evidence.py`) pins it to the release version.
_ADAPTER_VERSION = VersionRange((0, 1, 0), (0, 1, 0))

_VERSION_CORE = re.compile(r"\A\d+(\.\d+)*")


def _pin_tuple(text: str) -> tuple[int, int, int]:
    """Numeric core of a pin, padded to the 3-segment shape the public
    VersionRange requires ("2.0" -> (2, 0, 0); "0.81.2" -> (0, 81, 2))."""
    match = _VERSION_CORE.match(text.strip())
    if match is None:
        raise ValueError(f"unparsable pinned version: {text!r}")
    parts = tuple(int(p) for p in match.group(0).split("."))
    return (parts + (0, 0))[:3]  # type: ignore[return-value]


def default_adapters() -> tuple[ClaudeAdapter, CodexAdapter, PiAdapter]:
    return (ClaudeAdapter(), CodexAdapter(), PiAdapter())


def configuration_descriptor(adapter) -> ConfigurationAdapterDescriptor:
    """The public-point declaration for one brand adapter.

    `native_versions` is the exact measured pin on both ends (inclusive
    bounds): an adapter claims exactly what it was compiled against, never
    "everything above".
    """
    harness = adapter.harness_id
    if harness not in PINNED_NATIVE_VERSIONS:
        raise ValueError(f"{adapter.adapter_id}: no measured pin claim for "
                         f"harness {harness!r}")
    pin = _pin_tuple(PINNED_NATIVE_VERSIONS[harness])
    schema = ValueSchema("object",
                         properties=tuple(_PAYLOAD_FIELDS[harness].items()),
                         required=())
    return ConfigurationAdapterDescriptor(
        adapter.adapter_id, POINT_API_VERSION, FACET_ID, FACET_SCHEMA_VERSION,
        harness, VersionRange(pin, pin), _ADAPTER_VERSION,
        _ENTRIES[harness], schema, _CLAIMS[harness])


def default_configuration_descriptors() -> tuple[ConfigurationAdapterDescriptor, ...]:
    return tuple(configuration_descriptor(a) for a in default_adapters())


class PolicyConfigurationAdapter:
    """C2 carrier for a C1 brand adapter.

    A trusted composition may supply a C1 snapshot resolver.  The default
    product has no such authority: JSON desired values cannot certify an
    administrator ceiling, so it refuses before constructing native intents.
    """

    def __init__(self, adapter, descriptor: ConfigurationAdapterDescriptor | None = None,
                 snapshot_resolver: Callable[[AdapterContext, object], PolicyCompileSnapshot | None] | None = None):
        self._adapter = adapter
        self.descriptor = descriptor or configuration_descriptor(adapter)
        self._snapshot_resolver = snapshot_resolver

    def _snapshot(self, context: AdapterContext, desired: object) -> PolicyCompileSnapshot | None:
        if not isinstance(context, AdapterContext) or self._snapshot_resolver is None:
            return None
        try:
            snapshot = self._snapshot_resolver(context, desired)
            if not isinstance(snapshot, PolicyCompileSnapshot):
                return None
            installation = context.installation
            if (installation.harness_id != self.descriptor.harness_id or
                    installation.native_version is None or
                    self.descriptor.native_versions.contains(installation.native_version) is not True or
                    snapshot.harness_id != installation.harness_id or
                    snapshot.native_version != PINNED_NATIVE_VERSIONS.get(installation.harness_id) or
                    snapshot.ceiling is None or not snapshot.ceiling.is_trusted):
                return None
            return snapshot
        except Exception:
            # A backend authority outage or malformed evidence cannot escape
            # C4 inspect/plan as an exception or become supported by default.
            return None

    def assess(self, context: AdapterContext, request: object) -> Assessment:
        if not isinstance(context, AdapterContext) or context.installation.harness_id != self.descriptor.harness_id:
            return Assessment("unsupported", reason="wrong harness identity")
        if context.installation.native_version is None or self.descriptor.native_versions.contains(context.installation.native_version) is not True:
            return Assessment("unknown", reason="native version is not the measured pin")
        if context.entry not in self.descriptor.entries:
            return Assessment("unsupported", reason="entry is outside this adapter")
        try:
            if request is not None:
                self.descriptor.payload_schema.validate(request)
        except (TypeError, ValueError):
            return Assessment("unsupported", reason="invalid policy projection shape")
        snapshot = self._snapshot(context, request)
        if snapshot is None:
            return Assessment("unknown", reason="trusted policy ceiling/snapshot authority is absent")
        try:
            report = self._adapter.supports(SupportEvidence.of(
                harness_id=snapshot.harness_id, native_version=snapshot.native_version,
                pi_tool_call_gate=None if snapshot.evidence is None else snapshot.evidence.pi_tool_call_gate))
            if report.outcome is not SupportOutcome.SUPPORTED:
                return Assessment(report.outcome.value, reason=report.reason)
            compiled = self._adapter.compilePolicy(snapshot)
            if not isinstance(compiled, CompiledIntentSet):
                return Assessment("unsupported", reason="C1 policy cannot compile on this native surface")
            if request != compiled.as_record():
                return Assessment("unsupported", reason="projection is not the trusted C1 compile")
            claims = {".".join(claim.field_path): claim for claim in self.descriptor.claims}
            for field in compiled.fields:
                claim = claims.get(field)
                if claim is None or not any(
                    target.kind == claim.target_kind and
                    target.handle.handle_id == claim.target_id and
                    claim.field_path in target.allowed_fields
                    for target in context.targets
                ):
                    return Assessment("unsupported", reason="compiled field lacks Permissions target authority")
            if not compiled.fields:
                return Assessment("unsupported", reason="C1 policy has no owned native fields")
            return Assessment("supported", evidence_ref=context.capability_evidence_ref)
        except Exception:
            return Assessment("unknown", reason="trusted policy authority or compiler unavailable")

    def compile(self, context: AdapterContext, before: object, desired: object) -> IntentSet | AdapterRefusal:
        assessment = self.assess(context, desired)
        if assessment.status != "supported":
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, assessment.reason or "not supported")
        snapshot = self._snapshot(context, desired)
        if snapshot is None:
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, "trusted snapshot changed")
        try:
            compiled = self._adapter.compilePolicy(snapshot)
        except Exception:
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                                  "trusted policy authority or compiler unavailable")
        if not isinstance(compiled, CompiledIntentSet):
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, str(compiled))
        # The C1 compiler, not renderer JSON, decides values.  A requested
        # projection must equal those values exactly; no partial approximation.
        expected = compiled.as_record()
        if desired != expected:
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, "desired projection differs from trusted C1 compile")
        claims = {".".join(claim.field_path): claim for claim in self.descriptor.claims}
        targets = {(target.kind, target.handle.handle_id): target for target in context.targets}
        intents = []
        for field, value in expected.items():
            claim = claims.get(field)
            if claim is None:
                return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, f"{field} is outside Permissions ownership")
            target = targets.get((claim.target_kind, claim.target_id))
            if target is None or claim.field_path not in target.allowed_fields:
                return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, "claimed target authority is absent")
            source = IntentSource(self.descriptor.facet_id, self.descriptor.adapter_id,
                                  self.descriptor.facet_schema_version)
            intents.append(SetField(source, target.handle, FieldPath(claim.field_path), value))
        if not intents:
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, "C1 compiler yielded no owned native fields")
        return IntentSet(tuple(intents))

    def verify(self, context: AdapterContext, observed: object) -> VerificationUnknown:
        # C2's observed JSON has no C1 compile/observed identity pair or
        # operation receipt.  A value match alone never confirms an effect.
        return VerificationUnknown("operation-bound native receipt and readback binding are absent")


def policy_adapter_contributions() -> ContributionBatch:
    """The registration batch: three contributions on the one real point.

    The point is multi-owner (open) on the host side; declaring it in
    `open_points` is what lets one batch carry several entries for it - the
    platform's own duplicate guard refuses the batch otherwise, and the
    conflict gate inside the point does the §C1 uniqueness work.
    """
    items = tuple(Contribution(CONFIGURATION_POINT, POINT_API_VERSION,
                               PolicyConfigurationAdapter(adapter), required=True)
                  for adapter in default_adapters())
    return ContributionBatch(items, open_points=frozenset({CONFIGURATION_POINT}))


def select_adapter(harness_id: str, native_version: str):
    """Pure lookup over the default brand set for the §C1 compile surface
    (the adapters' own bounded `version_range`).

    This is a consumer-side convenience, NOT an admission authority: it
    registers nothing and refuses nothing. What got admitted lives in the
    platform's published view of the real point.
    """
    for adapter in default_adapters():
        if adapter.harness_id == harness_id and \
                adapter.version_range.contains(native_version):
            return adapter
    return None
