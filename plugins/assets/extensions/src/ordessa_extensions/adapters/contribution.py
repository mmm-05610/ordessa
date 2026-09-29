"""Hooks configuration adapters (EXT-5) — published C2 vocabulary only.

One adapter per implemented brand, registered through the published
`harness.configuration-adapters` point (v1, multi-owner) — the same
constants `ordessa_harness.contributions` validates against (pinned in
tests; the strings are duplicated here because this package must not
import the harness plugin — AGENTS.md rule 3).

The honest state of projection tonight (AR-3, verified in-tree):

* the registry DECLARES hooks slots for codex (`hooks_target`,
  harnesses.toml:38-40) and claude (`hooks_target`+`hooks_key`,
  harnesses.toml:117-120) — `assess` may claim placement support for the
  pinned installations;
* the runtime supplies NO hooks targets (`hooks_target`/`hooks_key` are
  parsed in registry/schema.py:90-104 and consumed nowhere else), and the
  native hook-entry VALUE schema is incomplete in-repo (the codex config
  extraction carries the `hooks.<Event>[].hooks[]` key family but not the
  inner item leaves; the claude extraction carries the bare key only).
  Authoring a payload in a guessed schema would write fiction into a
  brand's config — so `compile` REFUSES with a typed refusal instead,
  and `verify` keeps every observation ceiling at `projected`.

The intent-construction half is real and tested: `build_*_intents`
compiles OUR validated payload onto server-issued target handles with the
published DTO vocabulary (MountContent for the whole-file slot, SetField
for the keyed slot), so the day the runtime seam and the pinned native
schema land, `compile`'s two gates are the only thing to lift. Until then
the refusal IS the deliverable — the AR-3 fallback shape the ledger
anticipated: 「定义就绪、投影待通」.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    ConfigurationCapability, ConfigurationCapabilities, ContentRef, ContractError,
    ErrorCode, FieldClaim, IntentSet, IntentSource, Match, Mismatch,
    MountContent, SetField, TargetDescriptor, Verification,
    VerificationUnknown, VersionRange,
)

from .. import FACET_ID
from ..blocking import OBSERVATIONAL
from ..capabilities import (SUPPORTED, UNKNOWN, UNSUPPORTED, statement_for)
from ..definitions import KNOWN_EVENTS

#: The published point identity (must equal the harness handler's —
#: pinned against `ordessa_harness.contributions` in the tests).
CONFIGURATION_POINT = "harness.configuration-adapters"
POINT_API_VERSION = "v1"

#: The controlled entry (ACP launch; the only entry with in-repo evidence).
ENTRY = "acp"

#: The registry/runtime gap, one shared citation.
RUNTIME_GAP_EVIDENCE = (
    "plugins/harness/src/ordessa_harness/registry/schema.py:90-104"
    " (hooks_target/hooks_key parsed) — zero consumers elsewhere in"
    " plugins/harness/src; runtime supplies no hooks targets (AR-3)")

#: The native value-schema gap, one shared citation.
VALUE_SCHEMA_EVIDENCE = (
    "docs/design/harness-configuration/source-index.json:196-203 (codex:"
    " hooks.<Event>[].hooks[] key family, inner item leaves not extracted);"
    " :552 (claude: bare hooks key only)")

_VERSION = re.compile(r"\A(\d+)\.(\d+)\.(\d+)\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class BrandPin:
    """One brand's machine pins with their in-repo evidence."""

    harness_id: str
    native_version: tuple[int, int, int]
    adapter_version: tuple[int, int, int]
    native_evidence: str
    adapter_evidence: str
    #: the slot shape this registry entry declares (drives target
    #: selection and the descriptor's FieldClaim).
    slot: str  # "file-whole" (codex hooks.json) | "keyed" (claude settings)
    #: "machine" = first-hand in-repo machine constant (a mismatch is
    #: first-hand evidence the installation differs -> unsupported);
    #: "comment" = comment-grade observation only (a mismatch is NOT
    #: first-hand evidence of anything -> unknown, fail-closed all the
    #: same: neither grades supported).
    native_grade: str = "machine"


PINS: Mapping[str, BrandPin] = {
    "codex": BrandPin(
        harness_id="codex",
        native_version=(0, 147, 0),
        adapter_version=(1, 1, 14),
        native_evidence=("plugins/harness/src/ordessa_harness/codex/"
                         "production.py:88"),
        adapter_evidence=("plugins/harness/packaging/codex/package.json:9"),
        slot="file-whole"),
    "claude": BrandPin(
        harness_id="claude",
        # CLI 2.1.274 is comment-grade only (harnesses.toml:111); it is
        # not a proven pin — recorded honestly, still the only observed
        # value, so assess fail-closes on anything else.
        native_version=(2, 1, 274),
        adapter_version=(0, 81, 2),
        native_evidence=("plugins/harness/src/ordessa_harness/"
                         "harnesses.toml:111 (comment-grade observation; "
                         "not a proven pin)"),
        adapter_evidence=("plugins/harness/src/ordessa_harness/claude/"
                          "production.py:67"),
        slot="keyed", native_grade="comment"),
}


def version_tuple(text: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(text)
    if match is None:
        raise ValueError(f"not a machine X.Y.Z triple: {text!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def build_payload_schema():
    """The managed-set schema — OUR canonical hook payload (not the
    brands' native shapes; the native mapping is exactly what is NOT
    evidenced yet)."""
    from ordessa_harness_api import ValueSchema
    hook = ValueSchema(
        "object",
        properties=(
            ("hookId", ValueSchema("string")),
            ("event", ValueSchema("string", enum=tuple(sorted(KNOWN_EVENTS)))),
            ("matcher", ValueSchema("string", nullable=True)),
            ("actionKind", ValueSchema("string", enum=("command", "handler"))),
            ("command", ValueSchema("array", items=ValueSchema("string"),
                                    nullable=True)),
            ("handlerRef", ValueSchema("string", nullable=True)),
            ("timeoutSeconds", ValueSchema("integer")),
            ("runAsync", ValueSchema("boolean")),
            ("pin", ValueSchema("string")),
            ("contentSha256", ValueSchema("string")),
            ("semantics", ValueSchema("string", enum=(OBSERVATIONAL,))),
        ),
        required=("hookId", "event", "matcher", "actionKind", "command",
                  "handlerRef", "timeoutSeconds", "runAsync", "pin",
                  "contentSha256", "semantics"),
    )
    return ValueSchema(
        "object",
        properties=(
            ("hooks", ValueSchema("array", items=hook)),
            ("runtimeGeneration", ValueSchema("string")),
            ("projectId", ValueSchema("string")),
        ),
        required=("hooks", "runtimeGeneration", "projectId"),
    )


def build_managed_set_payload(definitions: Sequence[Any], *,
                              runtime_generation: str,
                              project_id: str) -> dict[str, Any]:
    """Our validated canonical payload for one full-set projection.

    Injects the EXT-6 `semantics: "observational"` marker — the schema
    refuses anything else, so a blocking claim is inexpressible here.
    Definitions pass through `.payload()` (validated at construction).
    """
    return {
        "hooks": [definition.payload() | {"semantics": OBSERVATIONAL}
                  for definition in definitions],
        "runtimeGeneration": runtime_generation,
        "projectId": project_id,
    }


def _refusal(code: ErrorCode, message: str) -> AdapterRefusal:
    return AdapterRefusal(code, message)


def _source(harness_id: str) -> IntentSource:
    return IntentSource(facet_id=FACET_ID,
                        item_id=f"assets.hooks.{harness_id}",
                        contribution_version="1")


def build_codex_intents(source: IntentSource, target: TargetDescriptor,
                        desired: Mapping[str, Any]) -> IntentSet:
    """Whole-file slot: one read-only mount of the complete managed set.

    Pure intent construction over the published vocabulary — the payload
    is already schema-validated by the caller.
    """
    payload_bytes = json.dumps(dict(desired), sort_keys=True,
                               ensure_ascii=False).encode("utf-8")
    ref = ContentRef(
        reference=f"assets.hooks.codex@{desired['runtimeGeneration']}",
        sha256=hashlib.sha256(payload_bytes).hexdigest(),
        size=len(payload_bytes))
    return IntentSet(intents=(
        MountContent(source=source, target=target.handle,
                     relative_name="hooks/hooks.json",
                     immutable_content_ref=ref, mode="read-only"),))


def build_claude_intents(source: IntentSource, target: TargetDescriptor,
                         desired: Mapping[str, Any]) -> IntentSet:
    """Keyed slot: one SetField of the `hooks` key (full replacement)."""
    from ordessa_harness_api import FieldPath
    hooks_value = [dict(hook) for hook in desired["hooks"]]
    return IntentSet(intents=(
        SetField(source=source, target=target.handle,
                 field_path=FieldPath(("hooks",)),
                 typed_value=hooks_value),))


class HooksConfigurationAdapter:
    """One brand's `ConfigurationAdapter` for the `assets.hooks` facet.

    Satisfies the published `ordessa_harness_api.ConfigurationAdapter`
    Protocol (descriptor / assess / compile / verify). Never carries an
    `owner` attribute (the harness handler refuses author-declared
    owners) and never touches HOME/network/spawn.
    """

    def __init__(self, harness_id: str) -> None:
        pin = PINS.get(harness_id)
        if pin is None:
            raise ValueError(
                f"no hooks adapter pin for {harness_id!r} (only codex and"
                " claude are implemented; see capabilities.py)")
        self._pin = pin
        self._statement = statement_for(harness_id)
        # The published FieldClaim refuses an empty field path; the
        # whole-file slot claims the single managed document face (the
        # Skills adapters use the same one-pseudo-part shape).
        claim = (FieldClaim("file", f"assets.hooks.{harness_id}.hooksfile",
                            ("hooks-document",))
                 if pin.slot == "file-whole"
                 else FieldClaim("file", f"assets.hooks.{harness_id}.settings",
                                 ("hooks",)))
        self.descriptor = ConfigurationAdapterDescriptor(
            adapter_id=f"assets.hooks.{harness_id}",
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
            claims=(claim,),
        )

    # -- assess ---------------------------------------------------------------

    def assess(self, context: AdapterContext, request: Any) -> Assessment:
        installation = context.installation
        if installation.harness_id != self._pin.harness_id:
            # same identity fail-closed gate verify() carries: a foreign
            # installation is never graded, no matter its version tuple
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
                reason=(f"entry {context.entry!r} has no in-repo hooks"
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
        # note: adapter_version is NON-optional in the published
        # Installation contract (ordessa_harness_api), so the native-side
        # "not inspected -> unknown" case has no adapter-side twin; any
        # MISMATCH still fail-closes below (round 12)
        if installation.adapter_version != self._pin.adapter_version:
            return Assessment(
                status="unsupported",
                reason=(f"adapter version {installation.adapter_version!r} "
                        f"is not the pinned "
                        f"{self._pin.adapter_version!r}; evidence: "
                        f"{self._pin.adapter_evidence}"))
        if request is not None:
            try:
                self.descriptor.payload_schema.validate(request)
            except ContractError as exc:
                # a caller-side payload error is NOT a capability grade
                # (unsupported = first-hand evidence this pin/path cannot
                # do it — never a synonym for "bad request"); unknown
                # makes no claim either way (review round 9).
                return Assessment(
                    status="unknown",
                    reason=f"payload rejected (caller error, no capability"
                           f" claim): {exc}")
        if not self._matching_targets(context):
            # definition-ready, projection-pending (AR-3): without a
            # server-issued hooks target the placement claim would be a
            # grade the runtime cannot cash (review round 10)
            return Assessment(
                status="unknown",
                reason=(f"pinned installation, but the runtime supplies no"
                        f" hooks target declaring the claimed face for this"
                        f" instance ({RUNTIME_GAP_EVIDENCE}) — definition"
                        " ready, projection pending"))
        # SAME gate compile ends with (review round 12: assess must never
        # grade a status compile cannot cash): until the native value
        # schema is evidenced at the pinned versions, nothing projects.
        return Assessment(
            status="unknown",
            reason=("pinned installation with a declared hooks target, but"
                    f" the native hook-entry value schema is incomplete"
                    f" in-repo ({VALUE_SCHEMA_EVIDENCE}) — definition"
                    " ready, projection pending (AR-3); supported becomes"
                    " gradeable the day that gate lifts"))

    # -- compile ---------------------------------------------------------------

    def compile(self, context: AdapterContext, before: Any,
                desired: Any) -> IntentSet | AdapterRefusal:
        try:
            return self._compile(context, desired)
        except ContractError as exc:
            return _refusal(exc.code, str(exc))

    def _compile(self, context: AdapterContext,
                 desired: Any) -> IntentSet | AdapterRefusal:
        if not isinstance(desired, Mapping):
            return _refusal(ErrorCode.INVALID_FRAGMENT,
                            "desired payload must be an object")
        try:
            self.descriptor.payload_schema.validate(dict(desired))
        except ContractError as exc:
            return _refusal(ErrorCode.INVALID_FRAGMENT,
                            f"payload rejected: {exc}")
        for hook in desired["hooks"]:
            if hook.get("semantics") != OBSERVATIONAL:
                return _refusal(
                    ErrorCode.INVALID_FRAGMENT,
                    "every hook must declare semantics='observational'"
                    " (EXT-6: no blocking claim is expressible)")
        if not self._matching_targets(context):
            return _refusal(
                ErrorCode.ADAPTER_MISSING,
                "no server-issued hooks target declaring the claimed face"
                f" for this instance ({RUNTIME_GAP_EVIDENCE}); refusing to"
                " compile against a self-chosen location")
        # The schema gate is LAST so its message never hides a target
        # shortage; both refusals are first-hand in-repo facts.
        return _refusal(
            ErrorCode.CAPABILITY_UNSUPPORTED,
            "native hook-entry value schema is incomplete in-repo"
            f" ({VALUE_SCHEMA_EVIDENCE}); authoring a guessed schema is"
            " refused — materialization waits on a pinned-schema read"
            " (AR-3). Intent construction is proven separately"
            " (build_codex_intents / build_claude_intents).")

    def _matching_targets(self, context: AdapterContext
                          ) -> Sequence[TargetDescriptor]:
        """Symmetric with the descriptor's FieldClaim (review round 9):
        the keyed slot needs the ("hooks",) part allowed; the whole-file
        slot needs its ("hooks-document",) part allowed — a target that
        restricts fields without admitting the claimed part is not ours
        to write."""
        claimed = (("hooks",) if self._pin.slot == "keyed"
                   else ("hooks-document",))
        out = []
        for target in context.targets:
            if target.kind != "file" or target.codec != "json":
                continue
            # STRICT (round 11): the runtime must explicitly declare the
            # claimed face — an empty allowed_fields is NOT a wildcard,
            # otherwise the "server-issued hooks target" evidence would
            # be broader than anything the code checks
            if not target.allowed_fields or claimed not in target.allowed_fields:
                continue
            out.append(target)
        return out

    # -- verify -------------------------------------------------------------

    def verify(self, context: AdapterContext,
               observed: Any) -> Verification:
        """Grade ONE runtime-sampled observation.

        Caller-trust boundary, stated plainly (review round 6): this
        method grades the observation the host runtime hands it; it
        cannot independently re-derive the sampled bytes, so a
        well-formed `observedDigest == expectedDigest` pair proves the
        GRADING RULE, not the truth of the sample — that trust is the
        same one the published observation vocabulary (skills' adapters,
        same shape) already requires of the runtime. The Match evidence
        string stays downgraded accordingly ("observational placement
        fact only")."""
        if not isinstance(observed, Mapping):
            return VerificationUnknown("observation payload is not an object")
        if context.installation.harness_id != self._pin.harness_id:
            return VerificationUnknown("harness_identity_mismatch")
        source = observed.get("source")
        expected = observed.get("expectedDigest")
        seen = observed.get("observedDigest")
        if source == "model_claim":
            return VerificationUnknown("model_claim_is_not_evidence")
        if source not in ("projection_digest", "native_file_stat",
                          "native_load_event"):
            return VerificationUnknown(
                f"unrecognised observation source {source!r}")
        if source == "native_load_event":
            # graded BEFORE any digest comparison: no brand load port is
            # evidenced, so a load event can never be evidence — it can
            # neither confirm (Match) nor contradict (Mismatch), it can
            # only be unknown.
            return VerificationUnknown(
                "no brand load port is evidenced for hooks"
                " (capabilities.load_evidence); an event can never promote"
                " placement to loading here")
        if not isinstance(seen, str) or not _HEX64.fullmatch(seen):
            return VerificationUnknown(
                "observation carries no well-formed observed digest — an"
                " absent or malformed observation is never graded as a"
                " match")
        if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
            return VerificationUnknown(
                "observation carries no well-formed expected digest")
        if seen != expected:
            return Mismatch(f"observed digest {seen!r} does not match the"
                            " expected managed hooks identity")
        return Match(evidence_ref=(
            "observational placement fact only; blocking/enforcement is"
            " NOT claimed (EXT-6, classification.md:52)"))

    # -- published capability rows -------------------------------------------

    def configuration_capabilities(
            self, target: Any) -> ConfigurationCapabilities:
        from ordessa_harness_api import ApplicationTarget
        if not isinstance(target, ApplicationTarget):
            raise ValueError("needs the published ApplicationTarget")
        statement = self._statement

        def cell(operation: str, axis: str | None, *,
                 forced: str | None = None,
                 forced_reason: str | None = None
                 ) -> ConfigurationCapability:
            if forced is not None:
                value, reason = forced, forced_reason
            elif axis is not None:
                value = statement.value(axis)
                reason = (None if value == SUPPORTED else
                          f"{axis} cell: {statement.fact(axis).evidence}")
            else:
                value, reason = UNKNOWN, "no in-repo evidence"
            axis_evidence = (statement.fact(axis).evidence
                             if axis is not None else None)
            return ConfigurationCapability(
                facet_id=FACET_ID, harness_id=self._pin.harness_id,
                native_version=self._pin.native_version,
                adapter_version=self._pin.adapter_version,
                entry=ENTRY, scope="instance", operation=operation,
                status=value,
                # the row carries THE cell's own evidence when supported
                # (never a hardcoded stand-in — round 18); unsupported/
                # unknown rows explain themselves through `reason`
                evidence_ref=(axis_evidence if value == SUPPORTED else None),
                reason=reason)

        return ConfigurationCapabilities(
            target=target,
            capabilities=(
                cell("content", "projection_path"),
                cell("set", "projection_path"),
                cell("reset", None, forced=UNSUPPORTED,
                     forced_reason=("no reset control is evidenced for any"
                                    " brand's hooks slot")),
                cell("secret", None),
                cell("action", "load_evidence"),
            ))


def hooks_adapters() -> tuple[HooksConfigurationAdapter, ...]:
    """The two implemented adapters (brand priority ruling: codex/claude)."""
    return (HooksConfigurationAdapter("codex"),
            HooksConfigurationAdapter("claude"))


__all__ = ["CONFIGURATION_POINT", "ENTRY", "PINS", "POINT_API_VERSION",
           "RUNTIME_GAP_EVIDENCE", "VALUE_SCHEMA_EVIDENCE", "BrandPin",
           "HooksConfigurationAdapter", "build_claude_intents",
           "build_codex_intents", "build_managed_set_payload",
           "build_payload_schema", "hooks_adapters", "version_tuple"]
