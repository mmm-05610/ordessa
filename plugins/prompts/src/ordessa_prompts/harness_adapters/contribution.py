"""The Prompts configuration adapters (brand-narrowed EXT-02).

One adapter per implemented brand (pi / codex / claude — user ruling
2026-09-28), registered through the published
`harness.configuration-adapters` point — the constants are pinned
against `ordessa_harness.contributions` in the tests; the strings are
duplicated here because this package must not import the harness plugin
(AGENTS.md rule 3; the G01 boundary scan enforces it).

The honest state tonight (AR-6, verified in-tree):

* the registry declares an `instruction` slot for every brand but
  declares NO target for it — no `instruction_target`/`instruction_key`
  field exists in the registry schema (registry/schema.py:64) and no
  instruction target path appears anywhere in harnesses.toml (contrast
  skill_target / mcp_target / hooks_target, which DO exist);
* the append/replace routes are vendor-doc listings
  (docs/design/prompts/harness-adapters.md §2), never first-hand.

So `compile` REFUSES with typed, cited refusals — there is no
server-issued target to compile against and inventing a file path or
config key would write fiction into a brand's configuration. There are
no intent-construction helpers here (unlike the hooks adapters, where
the registry at least declared a target shape): with no declared slot
path, ANY concrete intent would be a guess. `assess` therefore never
grades a status compile cannot cash — past the pin/entry gates it
answers `unknown` ("definition ready, projection pending"), and `verify`
grades placement observations only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    ConfigurationCapabilities, ConfigurationCapability, ContractError,
    ErrorCode, Verification, VerificationUnknown, VersionRange, Match,
    Mismatch,
)

from .capabilities import SUPPORTED, UNKNOWN, UNSUPPORTED, statement_for

#: The facet id this domain owns (kept here to avoid a circular import
#: through the package __init__, which re-exports this module).
FACET_ID = "assets.prompts"

#: The published point identity (pinned against the harness handler in
#: the tests; never imported here).
CONFIGURATION_POINT = "harness.configuration-adapters"
POINT_API_VERSION = "v1"

#: The controlled entry (ACP launch; the only entry with in-repo evidence).
ENTRY = "acp"

#: The registry/runtime seam, one shared citation.
REGISTRY_GAP = (
    "plugins/harness/src/ordessa_harness/registry/schema.py:64 (slots"
    " parsed; no instruction_target/instruction_key field exists);"
    " harnesses.toml greps: zero instruction target declarations"
    " (AR-6)")

@dataclass(frozen=True)
class BrandPin:
    harness_id: str
    native_version: tuple[int, int, int]
    adapter_version: tuple[int, int, int]
    native_evidence: str
    adapter_evidence: str
    native_grade: str = "machine"  # see EXT: comment-grade pins grade unknown


PINS: Mapping[str, BrandPin] = {
    "pi": BrandPin(
        harness_id="pi",
        native_version=(0, 84, 2),
        adapter_version=(0, 5, 0),
        native_evidence=("plugins/harness/packaging/pi/package-lock.json"
                         ":45-46 (packaged closure; the run chain itself is"
                         " PATH-resolved, harnesses.toml:396)"),
        adapter_evidence="plugins/harness/packaging/pi/package.json:13"),
    "codex": BrandPin(
        harness_id="codex",
        native_version=(0, 147, 0),
        adapter_version=(1, 1, 14),
        native_evidence=("plugins/harness/src/ordessa_harness/codex/"
                         "production.py:88"),
        adapter_evidence="plugins/harness/packaging/codex/package.json:9"),
    "claude": BrandPin(
        harness_id="claude",
        native_version=(2, 1, 274),
        adapter_version=(0, 81, 2),
        native_evidence=("plugins/harness/src/ordessa_harness/"
                         "harnesses.toml:111 (comment-grade observation; "
                         "not a proven pin)"),
        adapter_evidence=("plugins/harness/src/ordessa_harness/claude/"
                          "production.py:67"),
        native_grade="comment"),
}


def _refusal(code: ErrorCode, message: str) -> AdapterRefusal:
    return AdapterRefusal(code, message)


def build_payload_schema():
    """The managed-selection schema for the day projection lands: the
    fixed synthesis order is part of the payload's identity (HM §3)."""
    from ordessa_harness_api import ValueSchema
    item = ValueSchema(
        "object",
        properties=(
            ("promptId", ValueSchema("string")),
            ("revision", ValueSchema("integer")),
            ("digest", ValueSchema("string")),
            ("order", ValueSchema("integer")),
        ),
        required=("promptId", "revision", "digest", "order"),
    )
    return ValueSchema(
        "object",
        properties=(
            ("instructions", ValueSchema("array", items=item)),
            ("persona", ValueSchema("object", nullable=True)),
            ("systemReplacement", ValueSchema("object", nullable=True)),
            ("synthesis", ValueSchema(
                "string",
                enum=("systemReplacement->persona->ordered-instructions",))),
            ("separator", ValueSchema("string", enum=("\n\n",))),
            ("runtimeGeneration", ValueSchema("string")),
            ("projectId", ValueSchema("string")),
        ),
        required=("instructions", "persona", "systemReplacement",
                  "synthesis", "separator", "runtimeGeneration",
                  "projectId"),
    )


class PromptsConfigurationAdapter:
    """One brand's `ConfigurationAdapter` for the `assets.prompts` facet.

    No `owner` attribute (the handler refuses author-declared owners);
    no HOME/network/spawn; claims stay EMPTY tonight — with no declared
    instruction target there is nothing truthful to claim.
    """

    def __init__(self, harness_id: str) -> None:
        pin = PINS.get(harness_id)
        if pin is None:
            raise ValueError(
                f"no prompts adapter pin for {harness_id!r} (only pi/codex/"
                "claude are implemented; see capabilities.py)")
        self._pin = pin
        self._statement = statement_for(harness_id)
        self.descriptor = ConfigurationAdapterDescriptor(
            adapter_id=f"assets.prompts.{harness_id}",
            api_version="v1",
            facet_id=FACET_ID,
            facet_schema_version="1",
            harness_id=harness_id,
            native_versions=VersionRange(pin.native_version,
                                         pin.native_version),
            adapter_versions=VersionRange(pin.adapter_version,
                                          pin.adapter_version),
            entries=(ENTRY,),
            payload_schema=build_payload_schema(),
            claims=(),
        )

    # -- assess ---------------------------------------------------------------

    def assess(self, context: AdapterContext, request: Any) -> Assessment:
        installation = context.installation
        if installation.harness_id != self._pin.harness_id:
            return Assessment(
                status="unknown",
                reason=(f"installation {installation.harness_id!r} is not"
                        f" {self._pin.harness_id!r} — identity mismatch is"
                        " never assumed supported"))
        if installation.native_version is None:
            return Assessment(
                status="unknown",
                reason=(f"{self._pin.harness_id}: native version not "
                        "inspected; unknown versions are never assumed "
                        "supported"))
        if context.entry not in self.descriptor.entries:
            return Assessment(
                status="unknown",
                reason=(f"entry {context.entry!r} has no in-repo prompts"
                        " evidence"))
        if installation.native_version != self._pin.native_version:
            status = ("unsupported" if self._pin.native_grade == "machine"
                      else "unknown")
            return Assessment(
                status=status,
                reason=(f"native version {installation.native_version!r} is "
                        f"not the pinned {self._pin.native_version!r}; "
                        f"evidence grade {self._pin.native_grade!r}: "
                        f"{self._pin.native_evidence} — fail-closed either"
                        " way, never supported"))
        if (installation.adapter_version
                != self._pin.adapter_version):
            return Assessment(
                status="unsupported",
                reason=(f"adapter version {installation.adapter_version!r} "
                        f"is not the pinned {self._pin.adapter_version!r}; "
                        f"evidence: {self._pin.adapter_evidence}"))
        if request is not None:
            try:
                self.descriptor.payload_schema.validate(request)
            except ContractError as exc:
                return Assessment(
                    status="unknown",
                    reason=("payload rejected (caller error, no capability"
                            f" claim): {exc}"))
        # assess never grades a status compile cannot cash (EXT round-12
        # semantics): no instruction target exists anywhere in-repo, so
        # the only honest answer past the gates is projection-pending.
        return Assessment(
            status="unknown",
            reason=("pinned installation, but the registry declares no"
                    f" instruction target and the runtime supplies none"
                    f" ({REGISTRY_GAP}) — definition ready, projection"
                    " pending (AR-6)"))

    # -- compile ---------------------------------------------------------------

    def compile(self, context: AdapterContext, before: Any,
                desired: Any) -> Any:
        """Refusal-typed ALL the way out (round 5): even an internal
        defect (AttributeError/ValueError on a malformed context) fails
        closed as a typed refusal instead of leaking an exception to the
        host."""
        try:
            return self._compile(context, desired)
        except ContractError as exc:
            return _refusal(exc.code, str(exc))
        except (AttributeError, TypeError, ValueError) as exc:
            return _refusal(ErrorCode.INVALID_FRAGMENT,
                            f"adapter internal error refused: {exc!r}")

    def _compile(self, context: AdapterContext, desired: Any) -> Any:
        if not isinstance(desired, Mapping):
            return _refusal(ErrorCode.INVALID_FRAGMENT,
                            "desired payload must be an object")
        try:
            self.descriptor.payload_schema.validate(dict(desired))
        except ContractError as exc:
            return _refusal(ErrorCode.INVALID_FRAGMENT,
                            f"payload rejected: {exc}")
        if any(target.kind == "file" or target.kind == "directory"
               for target in context.targets):
            # a runtime that DOES supply targets still cannot be served
            # tonight: the registry declares no instruction slot target,
            # so no claim of ours could tell which target is ours
            return _refusal(
                ErrorCode.CAPABILITY_UNSUPPORTED,
                "targets arrived but the registry declares no instruction"
                f" slot target to claim them against ({REGISTRY_GAP});"
                " writing to an unclaimed target is refused (HM §3: slot"
                " only one Prompts adapter writes)")
        return _refusal(
            ErrorCode.ADAPTER_MISSING,
            "no server-issued instruction target exists — the registry"
            f" declares none and the runtime supplies none"
            f" ({REGISTRY_GAP}); refusing to compile against a self-chosen"
            " location (AR-6)")

    # -- verify -------------------------------------------------------------

    def verify(self, context: AdapterContext, observed: Any) -> Verification:
        """Grade ONE runtime-sampled observation. Caller-trust boundary
        (stated plainly, as the hooks adapters do): this grades the
        observation the host runtime hands it; a well-formed
        observedDigest == expectedDigest pair proves the GRADING RULE,
        not the truth of the sample."""
        import re as _re
        if not isinstance(observed, Mapping):
            return VerificationUnknown("observation payload is not an object")
        if context.installation.harness_id != self._pin.harness_id:
            return VerificationUnknown("harness_identity_mismatch")
        source = observed.get("source")
        expected = observed.get("expectedDigest")
        seen = observed.get("observedDigest")
        if source == "model_claim":
            return VerificationUnknown("model_claim_is_not_evidence")
        if source not in ("projection_digest", "native_file_stat"):
            return VerificationUnknown(
                f"unrecognised observation source {source!r}")
        hex64 = _re.compile(r"\A[0-9a-f]{64}\Z")
        if not isinstance(expected, str) or not hex64.fullmatch(expected):
            return VerificationUnknown(
                "observation carries no well-formed expected digest")
        if not isinstance(seen, str) or not hex64.fullmatch(seen):
            return VerificationUnknown(
                "observation carries no well-formed observed digest — an"
                " absent or malformed observation is never graded as a"
                " match")
        if seen != expected:
            return Mismatch(f"observed digest {seen!r} does not match the"
                            " expected managed selection identity")
        return Match(evidence_ref=(
            "observational placement fact only; confirmed requires the"
            " pinned native load entrance (HM §5), which is unevidenced"
            " tonight"))

    # -- published capability rows -------------------------------------------

    def configuration_capabilities(self, target: Any) -> ConfigurationCapabilities:
        from ordessa_harness_api import ApplicationTarget
        if not isinstance(target, ApplicationTarget):
            raise ValueError("needs the published ApplicationTarget")

        def cell(operation: str, semantic: str | None, *,
                 forced: str | None = None,
                 forced_reason: str | None = None
                 ) -> ConfigurationCapability:
            if forced is not None:
                value, reason = forced, forced_reason
            elif semantic is not None:
                cell_ = self._statement.cells[semantic]
                value = cell_.value
                reason = (None if value == SUPPORTED else
                          f"{semantic} cell: {cell_.evidence}")
            else:
                value, reason = UNKNOWN, "no in-repo evidence"
            return ConfigurationCapability(
                facet_id=FACET_ID, harness_id=self._pin.harness_id,
                native_version=self._pin.native_version,
                adapter_version=self._pin.adapter_version,
                entry=ENTRY, scope="instance", operation=operation,
                status=value, evidence_ref=None, reason=reason)

        return ConfigurationCapabilities(
            target=target,
            capabilities=(
                cell("content", "instruction"),
                cell("set", None, forced=UNSUPPORTED,
                     forced_reason=("claims are empty tonight: no registry-"
                                    "declared instruction target exists to"
                                    " claim a field on")),
                cell("reset", None, forced=UNSUPPORTED,
                     forced_reason=("no reset evidence for any brand's"
                                    " instruction route (HM §5: reset must"
                                    " restore a saved immutable baseline,"
                                    " which the routes cannot isolate"
                                    " tonight)")),
                cell("secret", None),
                cell("action", None),
            ))


def prompts_adapters() -> tuple[PromptsConfigurationAdapter, ...]:
    """The three implemented adapters (brand priority ruling)."""
    return (PromptsConfigurationAdapter("pi"),
            PromptsConfigurationAdapter("codex"),
            PromptsConfigurationAdapter("claude"))


__all__ = ["CONFIGURATION_POINT", "ENTRY", "PINS", "POINT_API_VERSION",
           "REGISTRY_GAP", "BrandPin", "PromptsConfigurationAdapter",
           "build_payload_schema", "prompts_adapters"]
