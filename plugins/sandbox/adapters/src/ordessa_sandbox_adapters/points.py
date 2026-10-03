"""T05b — the REAL `harness.configuration-adapters` binding (C2 descriptive edge).

The foundation checkpoint (8844c475bc, merged) publishes the Harness
configuration point and its payload contract: a contribution's payload carries
a ``ConfigurationAdapterDescriptor`` and callable C2 methods, validated by the
platform's ``HarnessContributionRegistry`` behind ``stage_contributions``
(duplicate adapter ids, harness+version+entry overlaps and cross-facet
native-field claim overlaps are typed refusals — contracts.md §C2,
verification.md extra-gate 3). This package contributes its three brand
descriptors through that point and keeps **no private admission authority**
(the former ``SandboxAdapterRegistry``/``stage_field_claims`` are demoted away;
see README).

Third-party shape follows the platform's own controlled contributor
(`plugins/harness/tests/fixtures/external_adapter`): the C2 vocabulary is
imported from the public contract dist ``ordessa_harness_api`` (the very
classes the point's handler isinstance-checks, module identity asserted in
tests), and the point id / api version are spelled as the constants below —
``tests/test_real_point_binding.py`` pins them equal to
``ordessa_harness.contributions.CONFIGURATION_POINT/POINT_API_VERSION``.
Harness package CODE (``ordessa_harness``) is never imported: ``harnesses.toml``
is *located* with ``importlib.util.find_spec`` (which does not execute the
package) and parsed with ``tomllib``, so `native_versions` are measured pins,
not folklore.

The C3 intent vocabulary is bound in ``seam.py`` and ``surface.py``. Default
product contributions here remain fail closed because authorized Sandbox facts,
ceiling and native readback are not supplied by C4's generic JSON context.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from ordessa_harness_api.contracts import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    FieldClaim,
    VersionRange,
    VerificationUnknown,
)
from ordessa_harness_api.errors import ContractError, ErrorCode
from ordessa_harness_api.schema import ValueSchema
from server_plugin_api import Contribution, ContributionBatch

__all__ = [
    "SANDBOX_CONFIGURATION_POINT_ID",
    "SANDBOX_POINT_API_VERSION",
    "SANDBOX_FACET_ID",
    "SANDBOX_FACET_SCHEMA_VERSION",
    "HarnessSandboxConfigurationAdapter",
    "HarnessRegistryUnavailable",
    "build_configuration_descriptor",
    "build_configuration_batch",
    "pinned_harness_versions",
]

#: the real point (spelled as the foundation publishes it; symbol-level
#: equality with `ordessa_harness.contributions` is pinned in the tests)
SANDBOX_CONFIGURATION_POINT_ID = "harness.configuration-adapters"
SANDBOX_POINT_API_VERSION = "v1"

#: `sandbox.native-configuration@1` -> facet id + schema version (§C2)
SANDBOX_FACET_ID = "sandbox.native-configuration"
SANDBOX_FACET_SCHEMA_VERSION = "1"

#: this distribution's adapter version; the pin this build was measured at.
#: Backing observation: this distribution's own release fact
#: (`plugins/assets/sandbox/adapters/pyproject.toml:7`, `version = "0.1.0"`) -
#: exact on both bounds, never widened. The joint-facet proof against the
#: Permissions facet lives in `tests/test_joint_facet_version_binding.py`
#: (each side pins its OWN release fact; both independently measure 0.1.0 -
#: the equality is not a copied range).
_ADAPTER_VERSIONS = VersionRange((0, 1, 0), (0, 1, 0))


class HarnessRegistryUnavailable(RuntimeError):
    """`harnesses.toml` could not be located; pins must come from the real
    registry (or be passed explicitly), never from an invented menu."""


def _semver_tuple(text: str) -> tuple[int, int, int]:
    """`"0.81.2"`/`"2.0"` -> 3-part semver tuple; pre-release suffix drops."""
    core = text.split("-", 1)[0].split("+", 1)[0].strip()
    parts = [int(segment) for segment in core.split(".") if segment != ""]
    if not parts:
        raise ValueError(f"unparseable native version: {text!r}")
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


def pinned_harness_versions() -> dict[str, str]:
    """The identity version of record per harness_type, read from the real
    `harnesses.toml` shipped by the installed ``ordessa-harness`` dist."""
    try:
        spec = importlib.util.find_spec("ordessa_harness")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        raise HarnessRegistryUnavailable(
            "cannot locate ordessa_harness/harnesses.toml to measure "
            "native_versions; install ordessa-harness or pass pins= "
            "explicitly — no pin is ever invented here")
    toml_path = Path(next(iter(spec.submodule_search_locations))) / "harnesses.toml"
    if not toml_path.is_file():
        raise HarnessRegistryUnavailable(
            f"ordessa_harness found at {toml_path.parent} but harnesses.toml "
            "is missing; native_versions stay unmeasurable")
    import tomllib
    document = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    return {entry["identity"]["harness_type"]: entry["identity"]["version"]
            for entry in document["harness"]}


# --------------------------------------------------- per-brand point specs
# The native config target each brand writes through. These are the logical
# target ids for the FieldClaim conflict gate: two facets claiming one
# (target_kind, target_id, field_path-prefix) collide at composition, and the
# platform (not this package) refuses. Codex's sandbox_mode /
# sandbox_workspace_write live in $CODEX_HOME/config.toml
# (harnesses.toml:36 names the same file for codex config keys); Claude's
# documented sandbox toggles live in $CLAUDE_CONFIG_DIR settings.json
# (harnesses.toml:119). Pi owns NOTHING: its sandbox is an optional extension
# (unsupported/absent), so it files zero claims and its payload schema admits
# zero keys.
@dataclass(frozen=True)
class _BrandPointSpec:
    claim_target_id: str | None
    payload_schema: ValueSchema


_CODEX_PAYLOAD_SCHEMA = ValueSchema(
    "object",
    properties=(
        # closed posture enum: the writable members of the committed,
        # version-matched App Server schema `SandboxMode`; danger-full-access
        # is not expressible through this facet at all
        ("sandbox_mode", ValueSchema("string",
                                     enum=("read-only", "workspace-write"))),
        ("writable_roots", ValueSchema("array", items=ValueSchema("string"))),
        ("network_access", ValueSchema("boolean")),
    ),
    required=("sandbox_mode",))  # additional_properties=False: no shell/path writes

_CLAUDE_PAYLOAD_SCHEMA = ValueSchema(
    "object",
    properties=(
        ("bashSandbox", ValueSchema("boolean")),
        ("powerShellSandbox", ValueSchema("boolean")),
        ("monitorSandbox", ValueSchema("boolean")),
    ),
    required=())  # no coverage=all key exists; anything else is refused

_PI_PAYLOAD_SCHEMA = ValueSchema("object")  # admits nothing non-empty

_BRAND_POINT_SPECS: Mapping[str, _BrandPointSpec] = {
    "sandbox.native-config.codex": _BrandPointSpec("codex-config-toml",
                                                   _CODEX_PAYLOAD_SCHEMA),
    "sandbox.native-config.claude-code": _BrandPointSpec("claude-settings-json",
                                                         _CLAUDE_PAYLOAD_SCHEMA),
    "sandbox.native-config.pi": _BrandPointSpec(None, _PI_PAYLOAD_SCHEMA),
}


def build_configuration_descriptor(adapter, *,
                                   pins: Mapping[str, str] | None = None
                                   ) -> ConfigurationAdapterDescriptor:
    """The real point's payload for one brand adapter, pinned from the toml."""
    spec = _BRAND_POINT_SPECS.get(adapter.adapter_id)
    if spec is None:
        raise ValueError(f"{adapter.adapter_id} has no published point spec")
    resolved = dict(pins) if pins is not None else pinned_harness_versions()
    if adapter.harness_id not in resolved:
        raise HarnessRegistryUnavailable(
            f"harnesses.toml records no harness {adapter.harness_id!r}; the "
            "descriptor stays unbuildable rather than inventing a pin")
    pin = _semver_tuple(resolved[adapter.harness_id])
    entries = tuple(adapter.native_field_claims())
    claims: tuple[FieldClaim, ...] = ()
    if spec.claim_target_id is not None:
        claims = tuple(FieldClaim("file", spec.claim_target_id, (field,))
                       for field in entries)
    return ConfigurationAdapterDescriptor(
        adapter_id=adapter.adapter_id,
        api_version=SANDBOX_POINT_API_VERSION,
        facet_id=SANDBOX_FACET_ID,
        facet_schema_version=SANDBOX_FACET_SCHEMA_VERSION,
        harness_id=adapter.harness_id,
        native_versions=VersionRange(pin, pin),
        adapter_versions=_ADAPTER_VERSIONS,
        entries=entries,
        payload_schema=spec.payload_schema,
        claims=claims,
    )


@dataclass(frozen=True)
class HarnessSandboxConfigurationAdapter:
    """Callable C2 payload that refuses effects without trusted Sandbox facts."""

    descriptor: ConfigurationAdapterDescriptor
    sandbox_adapter: object

    def assess(self, context: AdapterContext, request: object) -> Assessment:
        if not isinstance(context, AdapterContext):
            return Assessment("unknown", reason="Harness adapter context is unavailable")
        if context.installation.harness_id != self.descriptor.harness_id:
            return Assessment("unsupported", reason="Harness brand does not match this sandbox facet")
        if self.descriptor.native_versions.contains(context.installation.native_version) is not True:
            return Assessment("unknown", reason="Observed native version is outside the measured pin")
        if type(request) is dict and not request:
            return Assessment("unknown", reason="Authorized sandbox ceiling and native facts are not bound")
        try:
            self.descriptor.payload_schema.validate(request)
        except ContractError:
            return Assessment("unsupported", reason="Sandbox configuration payload is invalid")
        return Assessment("unknown", reason="Authorized sandbox ceiling and native facts are not bound")

    def compile(self, context: AdapterContext, before: object, desired: object) -> AdapterRefusal:
        try:
            self.descriptor.payload_schema.validate(desired)
        except ContractError:
            return AdapterRefusal(ErrorCode.INVALID_FRAGMENT, "Sandbox configuration payload is invalid")
        assessment = self.assess(context, desired)
        if assessment.status == "unsupported":
            return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                                  assessment.reason or "unsupported sandbox facet")
        return AdapterRefusal(ErrorCode.AUTHORIZATION_REFUSED,
                              "Sandbox ceiling and authorized facts are required before native intents")

    def verify(self, context: AdapterContext, observed: object) -> VerificationUnknown:
        return VerificationUnknown("No authenticated native sandbox readback is bound to this adapter")


def build_configuration_batch(adapters: Iterable[object] | None = None, *,
                              pins: Mapping[str, str] | None = None
                              ) -> ContributionBatch:
    """The three brand contributions on the real (open) configuration point."""
    if adapters is None:
        from .registry import default_sandbox_adapters
        adapters = default_sandbox_adapters()
    items = tuple(Contribution(SANDBOX_CONFIGURATION_POINT_ID,
                               SANDBOX_POINT_API_VERSION,
                               HarnessSandboxConfigurationAdapter(
                                   build_configuration_descriptor(adapter, pins=pins), adapter),
                               required=False)
                  for adapter in adapters)
    return ContributionBatch(items, open_points=frozenset(
        {SANDBOX_CONFIGURATION_POINT_ID}))
