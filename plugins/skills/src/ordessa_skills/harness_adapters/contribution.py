"""The Skills facet adapters as REAL published `ConfigurationAdapter`s.

Consumes the harness-api checkpoint (`ordessa_harness_api`, publication
`d3f026904e`, record `specs/011-plugin-rollout/checkpoints/harness-api.json`)
and registers through the published contribution point:

* point `harness.configuration-adapters`, api version `v1`, multi-owner —
  the same constants the harness handler validates against
  (`plugins/harness/src/ordessa_harness/contributions.py`, the point the
  default product declares with that handler bound
  `plugins/server/src/ordessa_server/../..`/`products/server` composition;
  the string ids are duplicated here only because the Skills package must
  not import the harness plugin — AGENTS.md rule 3 — and the registration
  tests prove the strings match the published constants);
* the payload is the adapter object; the host injects the owner and the
  harness handler refuses overlapping (facet, entry, version-range) or
  claim conflicts at registration (docs/design/harness-v2/contracts.md §C2).

Hard rules preserved at this boundary (all pinned in tests):

* compile only builds published intent DTOs — no HOME write, no spawn, no
  prompt send: those are Harness-owned operations on the published
  `ConfigurationService`/`ApplicationTarget` handles, reached only through
  the plan/apply transaction;
* an absolute host path anywhere in the payload refuses with a typed
  refusal BEFORE any DTO is constructed (the published `_relative_name`
  alone admits Windows-drive/`~`/URL shapes; §Harness 配置贡献 forbids
  them);
* version mismatch fail-closes (assess/compile refuse); an uninspected
  version answers `unknown`, never `supported`;
* unknown capability cells are never presented as offered: the assessed
  `ConfigurationCapability` rows are graded per operation from the
  evidence table in `capabilities.py`, and the observation ceiling stays
  `projected` until a brand gains a load-evidence cell.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    ConfigurationCapability, ConfigurationCapabilities, ContractError,
    ErrorCode, FieldClaim, IntentSet, Match, Mismatch, TargetDescriptor,
    Verification, VerificationUnknown, VersionRange,
)

from .base import (
    HarnessAdapterError, SKILLS_FACET_ID, assess, decide_reconfiguration,
    decide_update_strategy, evidence_ceiling, mount_content_for,
    remove_owned_for,
)
from .capabilities import SUPPORTED, UNKNOWN, UNSUPPORTED, pin_for, statement_for
from .conflict import name_rules_for
from .intent import (
    ManagedContentRef, SkillIntentError,
    looks_like_absolute_host_path, sweep_host_path_free,
)

#: The published point identity (must equal the harness handler's — pinned
#: against `ordessa_harness.contributions` in the registration tests).
CONFIGURATION_POINT = "harness.configuration-adapters"
POINT_API_VERSION = "v1"

#: The controlled entry every Skills configuration adapter is registered
#: for (the ACP launch entry; entries outside the descriptor's set are
#: answered `unknown`, never silently accepted).
SKILL_ENTRY = "acp"

_VERSION = re.compile(r"\A(\d+)\.(\d+)\.(\d+)\Z")


def version_tuple(text: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(text)
    if match is None:
        raise HarnessAdapterError(
            "HARNESS_VERSION_UNPARSEABLE",
            f"pinned version {text!r} is not a machine X.Y.Z triple")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


#: The managed-set payload schema is built by `build_payload_schema()`
#: below (`ValueSchema` composition is explicit there; one builder keeps
#: the two call sites — descriptor registration and assess validation —
#: on the same bytes).
def build_payload_schema():
    from ordessa_harness_api import ValueSchema
    asset = ValueSchema(
        "object",
        properties=(
            ("assetId", ValueSchema("string")),
            ("revision", ValueSchema("integer")),
            ("treeDigest", ValueSchema("string")),
            ("nativeName", ValueSchema("string")),
            ("sizeBytes", ValueSchema("integer")),
        ),
        required=("assetId", "revision", "treeDigest", "nativeName",
                  "sizeBytes"),
    )
    return ValueSchema(
        "object",
        properties=(
            ("assets", ValueSchema("array", items=asset)),
            ("removals", ValueSchema("array", items=asset)),
            ("runtimeGeneration", ValueSchema("string")),
            ("projectId", ValueSchema("string")),
            ("profileRevision", ValueSchema("integer")),
            ("assignmentRevision", ValueSchema("integer")),
        ),
        required=("assets", "runtimeGeneration", "projectId",
                  "profileRevision", "assignmentRevision"),
    )


def _refusal(exc: Exception) -> AdapterRefusal:
    """Map a domain refusal onto the published typed refusal."""
    code = getattr(exc, "code", "")
    if code == "SKILL_NAME_COLLISION":
        return AdapterRefusal(ErrorCode.TARGET_CONFLICT, str(exc))
    if code == "SKILL_INTENT_HOST_PATH":
        return AdapterRefusal(ErrorCode.INVALID_FRAGMENT, str(exc))
    if code in ("HARNESS_VERSION_MISMATCH", "HARNESS_VERSION_UNPARSEABLE"):
        return AdapterRefusal(ErrorCode.VERSION_UNVERIFIED, str(exc))
    if code == "HARNESS_TARGET_MISSING":
        return AdapterRefusal(ErrorCode.ADAPTER_MISSING, str(exc))
    if code == "HARNESS_LOAD_CONTROL_UNEVIDENCED":
        return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED, str(exc))
    return AdapterRefusal(ErrorCode.INVALID_FRAGMENT, str(exc))


def _ref_from_payload(item: Mapping[str, Any]) -> ManagedContentRef:
    return ManagedContentRef(
        asset_id=item["assetId"], revision=item["revision"],
        tree_digest=item["treeDigest"], native_name=item["nativeName"],
        size_bytes=item.get("sizeBytes"))


def _bounds_from_payload(desired: Mapping[str, Any]):
    from .intent import GenerationBounds
    return GenerationBounds(
        runtime_generation=desired["runtimeGeneration"],
        project_id=desired["projectId"],
        profile_revision=desired["profileRevision"],
        assignment_revision=desired["assignmentRevision"],
    )


class SkillsConfigurationAdapter:
    """One brand's `ConfigurationAdapter` for the `assets.skills` facet.

    Satisfies the published `ordessa_harness_api.ConfigurationAdapter`
    Protocol (descriptor / assess / compile / verify) — a conformance test
    proves `isinstance` against the Protocol and the exact method shapes.
    Never carries an `owner` attribute (the harness handler refuses
    author-declared owners) and never touches HOME/network/spawn.
    """

    def __init__(self, *, harness_id: str, target_slot: str) -> None:
        pin = pin_for(harness_id)
        if pin is None:
            raise HarnessAdapterError(
                "HARNESS_BRAND_UNREGISTERED",
                f"no pinned version is evidenced for {harness_id!r}")
        statement = statement_for(harness_id)
        self._harness_id = harness_id
        self._target_slot = target_slot
        self.descriptor = ConfigurationAdapterDescriptor(
            adapter_id=f"assets.skills.{harness_id}",
            api_version="v1",
            facet_id=SKILLS_FACET_ID,
            facet_schema_version="1",
            harness_id=harness_id,
            native_versions=VersionRange(version_tuple(pin.native_version),
                                         version_tuple(pin.native_version)),
            adapter_versions=VersionRange(version_tuple(pin.adapter_version),
                                          version_tuple(pin.adapter_version)),
            entries=(SKILL_ENTRY,),
            payload_schema=build_payload_schema(),
            # The adapter owns ONLY the mounted content directory of its
            # brand slot — no native field claims (skills never edits the
            # brand's settings.json): reset strategy is OWNED_REMOVAL_ONLY
            # because no reset control is evidenced for any brand.
            claims=(FieldClaim("directory", f"assets.skills.{harness_id}.content",
                               ("mounted-content",)),),
        )
        self._statement = statement
        self._pin = pin

    # -- assess ---------------------------------------------------------------

    def assess(self, context: AdapterContext, request: Any) -> Assessment:
        """Version-gated, evidence-cited assessment for this installation.

        distinct answers, never conflated:
        * `unsupported` — the installation is INSPECTED and differs from
          the evidenced pin (fail-closed, harness-adapters.md 运行版本不符
          时拒绝能力), or the payload does not validate against the
          registered schema;
        * `unknown` — nothing to grade against (native version not
          inspected, entry has no evidenced relation to skill loading);
        * `supported` — pinned versions matched; the placement capability
          itself is the only claim, and `evidence_ref` names the ceiling.
        """
        installation = context.installation
        if installation.native_version is None:
            return Assessment(
                status="unknown",
                reason=(f"{self._harness_id}: native version not inspected; "
                        "unknown versions are never assumed supported"))
        if context.entry not in self.descriptor.entries:
            return Assessment(
                status="unknown",
                reason=(f"entry {context.entry!r} carries no in-repo skill-"
                        "loading evidence (brand-matrix.md §2)"))
        expected_native = version_tuple(self._pin.native_version)
        expected_adapter = version_tuple(self._pin.adapter_version)
        if installation.native_version != expected_native:
            return Assessment(
                status="unsupported",
                reason=(f"native version {installation.native_version!r} is "
                        f"not the pinned {expected_native!r} evidenced at "
                        f"{self._pin.native_evidence}"))
        if installation.adapter_version != expected_adapter:
            return Assessment(
                status="unsupported",
                reason=(f"adapter version {installation.adapter_version!r} "
                        f"is not the pinned {expected_adapter!r} evidenced "
                        f"at {self._pin.adapter_evidence}"))
        if request is not None:
            try:
                self.descriptor.payload_schema.validate(request)
            except ContractError as exc:
                return Assessment(status="unsupported",
                                  reason=f"payload rejected: {exc}")
        return Assessment(
            status="supported",
            evidence_ref=(f"{context.capability_evidence_ref}; placement-"
                          f"only, evidence ceiling "
                          f"{evidence_ceiling(self._statement)}"))

    # -- compile ---------------------------------------------------------------

    def compile(self, context: AdapterContext, before: Any,
                desired: Any) -> IntentSet | AdapterRefusal:
        """One-shot full-set compile onto the published IntentSet.

        The mount targets are the SERVER-ISSUED handles from
        `context.targets` (kind directory / codec content) — never a
        handle this adapter invents; the frozen generation face in the
        payload must be the face the projection is pinned to, and every
        string is swept for host paths before a DTO exists.
        """
        try:
            return self._compile(context, desired)
        except (SkillIntentError, HarnessAdapterError) as exc:
            return _refusal(exc)
        except ContractError as exc:
            return AdapterRefusal(exc.code, str(exc))

    def _compile(self, context: AdapterContext, desired: Any) -> IntentSet:
        if not isinstance(desired, Mapping):
            raise SkillIntentError("SKILL_INTENT_INVALID",
                                   "desired payload must be an object")
        # Sweep first: the published DTO checks are weaker than this rule.
        sweep_host_path_free(dict(desired), "desired")
        self.descriptor.payload_schema.validate(dict(desired))
        assessment = self.assess(context, None)
        if assessment.status != "supported":
            if assessment.status == UNKNOWN:
                raise HarnessAdapterError(
                    "HARNESS_VERSION_MISMATCH",
                    f"compile refused, assessment unknown: "
                    f"{assessment.reason}")
            raise HarnessAdapterError(
                "HARNESS_VERSION_MISMATCH",
                f"compile refused for an unsupported installation: "
                f"{assessment.reason}")
        targets = self._content_targets(context)
        refs = tuple(_ref_from_payload(item) for item in desired["assets"])
        rules = name_rules_for(self._harness_id)
        from .conflict import evaluate_managed_set
        evaluate_managed_set(refs, rules)
        update = decide_update_strategy(self._statement)
        if update == "refuse":
            raise HarnessAdapterError(
                "HARNESS_LOAD_CONTROL_UNEVIDENCED",
                f"neither reload nor resume is evidenced for "
                f"{self._harness_id!r}")
        handle = targets[0].handle
        intents = []
        seen: set[str] = set()
        for ref in refs:
            if ref.asset_id in seen:
                raise SkillIntentError("SKILL_NAME_COLLISION",
                                       f"duplicate asset {ref.asset_id}")
            seen.add(ref.asset_id)
            intents.append(mount_content_for(ref, handle,
                                             slot=self._target_slot))
        for item in desired.get("removals", ()):
            ref = _ref_from_payload(item)
            intents.append(remove_owned_for(ref.asset_id, handle,
                                            slot=self._target_slot,
                                            relative_name=ref.native_name))
        return IntentSet(intents=tuple(intents))

    def _content_targets(self, context: AdapterContext
                         ) -> Sequence[TargetDescriptor]:
        targets = tuple(target for target in context.targets
                        if target.kind == "directory"
                        and target.codec == "content")
        if not targets:
            raise HarnessAdapterError(
                "HARNESS_TARGET_MISSING",
                f"{CONFIGURATION_POINT}: the runtime provided no content "
                "directory target for this instance; refusing to compile "
                "against a self-chosen location")
        return targets

    # -- verify -------------------------------------------------------------

    def verify(self, context: AdapterContext, observed: Any) -> Verification:
        """Interpret one Harness-sampled observation of the content slot.

        Published-vocabulary rules (pinned in tests):
        * placement facts (`projection_digest`, `native_directory_listing`)
          that match answer `Match` — a configuration-state fact ONLY; the
          evidence ladder in `base.verify` keeps the effect level at
          `projected`, never `loaded`;
        * a digest that differs from the expected one answers `Mismatch`;
        * a model claim, an uninspected source or a malformed sample
          answers `VerificationUnknown` — unknown never reports success.
        """
        if not isinstance(observed, Mapping):
            return VerificationUnknown("observation payload is not an object")
        if context.installation.harness_id != self._harness_id:
            # an observation reported for another brand grades nothing here
            return VerificationUnknown("harness_identity_mismatch")
        source = observed.get("source")
        expected = observed.get("expectedDigest")
        seen = observed.get("observedDigest")
        if source == "model_claim":
            return VerificationUnknown("model_claim_is_not_evidence")
        if source not in ("projection_digest", "native_directory_listing",
                          "native_load_event", "invocation_event"):
            return VerificationUnknown(f"unrecognised observation source "
                                       f"{source!r}")
        if not isinstance(expected, str) or not expected:
            return VerificationUnknown("observation carries no expected digest")
        if seen is not None and seen != expected:
            return Mismatch(f"observed digest {seen!r} does not match the "
                            "expected managed content identity")
        if source in ("native_load_event", "invocation_event"):
            # The brands' load/invocation ports are unevidenced (unknown
            # cells in capabilities.py) — at this boundary they cannot
            # promote anything; answer unknown honestly.
            return VerificationUnknown(
                f"{source}: brand load/invocation port has no in-repo "
                f"evidence (cell grading "
                f"{self._statement.value('loaded_evidence')})")
        return Match(evidence_ref=(
            f"specs/011-q1-skills/research/brand-matrix.md — placement-only "
            f"observation; effect ceiling {evidence_ceiling(self._statement)}"))

    # -- published capability rows (ConfigurationService.inspect vocabulary) --

    def configuration_capabilities(
        self, target: Any) -> ConfigurationCapabilities:
        """Per-operation capability rows for one ApplicationTarget.

        Grades the published operation axes from the SAME evidence table —
        `unknown` where the repo has no evidence (every brand's discovery,
        reset and reload cells today), and NEVER `supported` for an
        uninspected version or an unevidenced port. `set` is
        `unsupported` with a reason: this facet declares no native field
        edits at all (its claims carry only the owned content directory) —
        that absence is the adapter's own contract, not brand evidence.
        """
        from ordessa_harness_api import ApplicationTarget
        if not isinstance(target, ApplicationTarget):
            raise HarnessAdapterError("HARNESS_TARGET_INVALID",
                                      "needs the published ApplicationTarget")
        pin_native = version_tuple(self._pin.native_version)
        pin_adapter = version_tuple(self._pin.adapter_version)
        ceiling = evidence_ceiling(self._statement)

        def cell(operation: str, axis: str | None, *,
                 forced: str | None = None,
                 forced_reason: str | None = None) -> ConfigurationCapability:
            if forced is not None:
                value, reason = forced, forced_reason
            elif axis is not None:
                value = self._statement.value(axis)
                reason = None if value == SUPPORTED else (
                    f"{axis} cell: {self._statement.fact(axis).evidence}")
            else:
                value, reason = UNKNOWN, "no in-repo evidence"
            return ConfigurationCapability(
                facet_id=SKILLS_FACET_ID, harness_id=self._harness_id,
                native_version=pin_native, adapter_version=pin_adapter,
                entry=SKILL_ENTRY, scope="instance", operation=operation,
                status=value,
                evidence_ref=(None if value != SUPPORTED else
                              f"{self._pin.native_evidence}; ceiling {ceiling}"),
                reason=reason)

        return ConfigurationCapabilities(
            target=target,
            capabilities=(
                # Whether the BRAND discovers mounted content is the
                # `discovery_mechanism` cell — unknown for every brand
                # (brand-matrix.md §2/§6), so the `content` operation is
                # graded from it and never offered on placement alone.
                cell("content", "discovery_mechanism"),
                cell("set", None, forced=UNSUPPORTED,
                     forced_reason=("the skills facet declares no native "
                                    "field edits (claims: owned content "
                                    "directory only)")),
                cell("reset", "reset"),
                cell("secret", None),
                cell("action", "reload"),
            ))


def configuration_adapters() -> tuple[SkillsConfigurationAdapter, ...]:
    """The three controlled-brand adapters, one per registered brand."""
    from . import claude, codex, pi  # late import: brand modules are leaf
    return (
        SkillsConfigurationAdapter(harness_id=pi.HARNESS_ID,
                                   target_slot=pi.TARGET_SLOT),
        SkillsConfigurationAdapter(harness_id=codex.HARNESS_ID,
                                   target_slot=codex.TARGET_SLOT),
        SkillsConfigurationAdapter(harness_id=claude.HARNESS_ID,
                                   target_slot=claude.TARGET_SLOT),
    )


def reconfiguration_decision(harness_id: str,
                             affected_instance_refs: Sequence[str]
                             ) -> Any:
    """The published decision for one brand's next-user-submit apply."""
    return decide_reconfiguration(statement_for(harness_id),
                                  affected_instance_refs=affected_instance_refs)


__all__ = [
    "CONFIGURATION_POINT", "POINT_API_VERSION", "SKILL_ENTRY",
    "SkillsConfigurationAdapter", "configuration_adapters",
    "reconfiguration_decision", "version_tuple", "build_payload_schema",
]
