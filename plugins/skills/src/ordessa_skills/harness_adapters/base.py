"""Shared pure semantics for the brand adapter modules.

Each brand module (`pi.py`, `codex.py`, `claude.py`) exposes the same three
pure functions — `assess(target)`, `compile(resolved_set, target)`,
`verify(observation_result)` — with the brand's frozen facts injected from
`capabilities.py`. Nothing here:

* imports `ordessa_harness` or any host/harness internal (AGENTS.md rule 3;
  the evidence strings merely *cite* harness files by path:line) — it does
  consume the published standalone contract `ordessa_harness_api`;
* writes to a filesystem, spawns a process or sends anything anywhere —
  `compile` only produces the published `IntentSet` dataclass values; the
  physical mount, HOME write and restart are Harness-owned operations on
  the `ConfigurationService`/`ApplicationTarget` handles;
* executes or reads skill bodies.

`compile` semantics follow harness-adapters.md 映射步骤 2: ONE complete
one-shot declaration for the whole resolved collection, including the
brand's native naming rules and its declared load control — never
per-skill incremental edits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ordessa_harness_api import (
    ContentRef as PublishedContentRef,
    IntentSet as PublishedIntentSet,
    IntentSource as PublishedIntentSource,
    MountContent as PublishedMountContent,
    ReconfigurationDecision as PublishedReconfigurationDecision,
    RemoveOwnedContent as PublishedRemoveOwnedContent,
    TargetHandle as PublishedTargetHandle,
)

from ..api import evidence as ladder
from ..api.errors import AssetDomainError
from .capabilities import (
    AXES, SUPPORTED, UNKNOWN, UNSUPPORTED, CapabilityStatement,
    pin_for, statement_for,
)
from .conflict import NativeNameRules, evaluate_managed_set, name_rules_for
from .intent import (
    GenerationBounds, ManagedContentRef, SkillIntentError, sweep_host_path_free,
)

#: Strategy vocabulary (decided by `decide_update_strategy`; mapped onto the
#: published `ReconfigurationDecision.mode` by `decide_reconfiguration`).
RELOAD = "reload"
RESTART_RESUME = "restart_and_resume"
REFUSE = "refuse"
NATIVE_RESET = "native_reset"
OWNED_REMOVAL_ONLY = "owned_removal_only"

#: The facet this domain's adapters compile contributions for. It must stay
#: equal to `profile_contribution.provider.FACET_ID` — the profile-api and
#: harness-api sides of one facet are the SAME id by contract (a test pins
#: it; `IntentSource.facet_id` is how the platform attributes an intent).
SKILLS_FACET_ID = "assets.skills"

#: The evidence ceiling a compiled projection may ever promise today; the
#: same value the published `Assessment.evidence_ref` carries.
_EVIDENCE_CEILING_LEVEL = "evidence_ceiling"

RELOAD_AXIS = "reload"
RESUME_AXIS = "resume"
RESET_AXIS = "reset"
LOADED_EVIDENCE_AXIS = "loaded_evidence"
EXPLICIT_AXIS = "explicit_invocation"


class HarnessAdapterError(AssetDomainError):
    """A brand adapter refused to participate (version, entry, evidence)."""


# --------------------------------------------------------------------------
# assess
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AdapterTarget:
    """What the runtime reports about the instance we are about to project into.

    `entry` is the controlled entry name (e.g. "acp"). The repo carries NO
    evidence mapping any entry to a skill-loading capability
    (brand-matrix.md §2), so `assess` records the entry but never grades
    it — an entry string can neither promote nor substitute for a pinned
    version check.
    """

    harness_id: str
    native_version: str
    adapter_version: str
    entry: str


@dataclass(frozen=True)
class Assessment:
    harness_id: str
    statement: CapabilityStatement
    #: Axes offered to planning/UI: only `supported` cells ever appear here.
    offered_axes: tuple[str, ...]
    #: Axes left `unknown` — distinct from `unsupported` (capabilities.py
    #: docstring): unknown = repo has no evidence; unsupported = repo has
    #: evidence of absence. Neither is offered; only supported is.
    unknown_axes: tuple[str, ...]
    unsupported_axes: tuple[str, ...]
    #: True when the native pin matched only a comment-grade observation
    #: (Claude CLI 2.1.274) or a packaged-closure pin with an unpinned run
    #: chain (Pi) — honest marker that the version axis evidence is weak.
    native_pin_is_machine_enforced: bool


def assess(target: AdapterTarget, *, harness_id: str) -> Assessment:
    """Fail closed on any version that is not the evidenced pinned one.

    Design rule (harness-adapters.md 品牌适配原则 / G10): 运行版本不符时拒绝
    能力. An unregistered brand has no pin at all, so it refuses too —
    `statement_for` alone keeps UI honest with `unknown`, but planning must
    not proceed without an evidenced version.
    """
    if target.harness_id != harness_id:
        raise HarnessAdapterError(
            "HARNESS_ADAPTER_BRAND_MISMATCH",
            f"target names harness {target.harness_id!r}, asked the "
            f"{harness_id!r} adapter to speak for it")
    pin = pin_for(harness_id)
    if pin is None:
        raise HarnessAdapterError(
            "HARNESS_BRAND_UNREGISTERED",
            f"no pinned version is evidenced for harness {harness_id!r}; "
            "unknown brands only get already-proven capabilities, and none "
            "is proven without a pin")
    if target.adapter_version != pin.adapter_version:
        raise HarnessAdapterError(
            "HARNESS_VERSION_MISMATCH",
            f"adapter version {target.adapter_version!r} is not the pinned "
            f"{pin.adapter_version!r} evidenced at {pin.adapter_evidence}",
            detail=harness_id)
    if target.native_version != pin.native_version:
        raise HarnessAdapterError(
            "HARNESS_VERSION_MISMATCH",
            f"native version {target.native_version!r} is not the pinned "
            f"{pin.native_version!r} evidenced at {pin.native_evidence}",
            detail=harness_id)
    statement = statement_for(harness_id)
    return Assessment(
        harness_id=harness_id,
        statement=statement,
        offered_axes=statement.offered_axes(),
        unknown_axes=tuple(axis for axis in AXES
                           if statement.value(axis) == UNKNOWN),
        unsupported_axes=tuple(axis for axis in AXES
                               if statement.value(axis) == UNSUPPORTED),
        native_pin_is_machine_enforced=pin.native_pin_is_machine_enforced,
    )


# --------------------------------------------------------------------------
# load-control decisions (G13 decision layer only — see decide_* docstrings)
# --------------------------------------------------------------------------

def decide_update_strategy(statement: CapabilityStatement) -> str:
    """Reload vs restart-and-resume vs refuse, as a PURE DECISION.

    harness-adapters.md 映射步骤 5: 支持安全 reload 用 reload, 不支持则由
    Harness 重启并恢复原会话; 恢复失败不另起空会话代替. Because `reload` is
    `unknown` for every brand today (capabilities registry), every
    registered brand lands on RESTART_RESUME (resume IS evidenced); a brand
    without evidenced resume REFUSES rather than silently session/new-ing.

    The live execution of reload / restart / resume is the Harness's
    behaviour behind the published `ConfigurationService`/`RuntimeAdapter`
    seam — this returns the decision only; `decide_reconfiguration` maps it
    onto the published `ReconfigurationDecision`.
    """
    if statement.value(RELOAD_AXIS) == SUPPORTED:
        return RELOAD
    if statement.value(RESUME_AXIS) == SUPPORTED:
        return RESTART_RESUME
    return REFUSE


def decide_reconfiguration(
    statement: CapabilityStatement,
    *,
    affected_instance_refs: Sequence[str],
) -> PublishedReconfigurationDecision:
    """Map the domain update decision onto the published decision type.

    `affected_instance_refs` are the opaque instance refs the caller froze
    the snapshot against (never host paths — the intent sweep applies);
    a brand without evidenced resume gets `unsupported` WITH a reason —
    refusing beats a fake resume that silently starts a blank session.
    """
    strategy = decide_update_strategy(statement)
    if strategy == RELOAD:
        return PublishedReconfigurationDecision(
            mode="reload", affected_instance_refs=tuple(affected_instance_refs))
    if strategy == RESTART_RESUME:
        return PublishedReconfigurationDecision(
            mode="restart-resume",
            affected_instance_refs=tuple(affected_instance_refs))
    return PublishedReconfigurationDecision(
        mode="unsupported",
        affected_instance_refs=tuple(affected_instance_refs),
        reason=(f"neither reload nor resume is evidenced for "
                f"{statement.harness_id!r}; refusing instead of declaring an "
                "update the Harness cannot honour"))


def decide_reset_strategy(statement: CapabilityStatement) -> str:
    """Reset decision: a native reset may only be claimed where evidenced.

    No brand has in-repo evidence of a reset control (all `reset` cells are
    `unknown`), so the honest strategy is OWNED_REMOVAL_ONLY: withdraw what
    Ordessa mounted and rely on generation teardown — never a claim that
    ambient native content got reset/closed (ux.md §原生发现和错误:
    原生项不被谎报"已禁用").
    """
    if statement.value(RESET_AXIS) == SUPPORTED:
        return NATIVE_RESET
    return OWNED_REMOVAL_ONLY


def evidence_ceiling(statement: CapabilityStatement) -> str:
    """The strongest level THIS adapter may ever report for the brand.

    With `loaded_evidence` unevidenced (every registered brand today) the
    ceiling is `projected`; a verified load port would raise it to
    `loaded`, and only an explicit-invocation event source on top of that
    could raise it to `used` (contracts.md 可用性最少区分).
    """
    if statement.value(LOADED_EVIDENCE_AXIS) != SUPPORTED:
        return ladder.PROJECTED
    if statement.value(EXPLICIT_AXIS) == SUPPORTED:
        return ladder.USED
    return ladder.LOADED


# --------------------------------------------------------------------------
# compile
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# compile (published vocabulary)
# --------------------------------------------------------------------------

def content_ref_for(ref: ManagedContentRef) -> PublishedContentRef:
    """Map the domain content coordinates onto the published `ContentRef`.

    `reference` names the managed revision as an opaque, path-free token
    (never a host location — the input already swept for that); `sha256`
    is the tree digest's bare hex; `size` must be a REAL byte count — a
    missing size refuses rather than a fabricated 0 that would let an
    over-budget mount pass a capacity check.
    """
    if ref.size_bytes is None:
        raise SkillIntentError(
            "SKILL_INTENT_CONTENT_SIZE_UNKNOWN",
            f"asset {ref.asset_id!r} r{ref.revision} carries no sizeBytes; "
            "ContentRef refuses a fabricated size")
    return PublishedContentRef(
        reference=f"{ref.asset_id}@{ref.revision}",
        sha256=ref.tree_digest.removeprefix("sha256:"),
        size=ref.size_bytes)


def intent_source_for(ref: ManagedContentRef) -> PublishedIntentSource:
    return PublishedIntentSource(
        facet_id=SKILLS_FACET_ID,
        item_id=ref.asset_id,
        contribution_version=f"r{ref.revision}",
    )


def preview_target_handle(harness_id: str, bounds: GenerationBounds
                          ) -> PublishedTargetHandle:
    """The generation-binding handle a PREVIEW compile mounts against.

    The published `TargetHandle` is documented "opaque server-issued;
    never a filesystem path" — in an integrated apply the Harness hands
    the real handles through `AdapterContext.targets` (see
    `contribution.SkillsConfigurationAdapter.compile`). A pure preview
    has no live server, so the handle is a deterministic derivation of
    the frozen {harness, runtimeGeneration, projectId, profileRevision,
    assignmentRevision} face: it binds the compiled set to exactly that
    face and cannot be mistaken for an addressable location.
    """
    handle_id = (f"skills-preview:{harness_id}:{bounds.runtime_generation}:"
                 f"{bounds.project_id}:pr{bounds.profile_revision}:"
                 f"ar{bounds.assignment_revision}")
    return PublishedTargetHandle(handle_id=handle_id,
                                 generation=bounds.assignment_revision)


def mount_content_for(ref: ManagedContentRef, handle: PublishedTargetHandle,
                      *, slot: str) -> PublishedMountContent:
    """Build one published `MountContent` under the brand's slot label.

    The host-path sweep runs BEFORE the DTO is constructed: the published
    `_relative_name` check admits Windows-drive-with-slashes and `~`/URL
    shapes this design forbids, so the conservative Skills rule stays.
    """
    relative_name = f"{slot}/{ref.native_name}"
    sweep_host_path_free(relative_name, "MountContent.relative_name")
    sweep_host_path_free(handle.handle_id, "TargetHandle.handle_id")
    return PublishedMountContent(
        source=intent_source_for(ref),
        target=handle,
        relative_name=relative_name,
        immutable_content_ref=content_ref_for(ref),
        mode="read-only",
    )


def remove_owned_for(asset_id: str, handle: PublishedTargetHandle, *,
                     slot: str, relative_name: str
                     ) -> PublishedRemoveOwnedContent:
    full = f"{slot}/{relative_name}"
    sweep_host_path_free(full, "RemoveOwnedContent.relative_name")
    return PublishedRemoveOwnedContent(
        source=PublishedIntentSource(
            facet_id=SKILLS_FACET_ID, item_id=asset_id,
            contribution_version="owned"),
        target=handle,
        relative_name=full,
    )


@dataclass(frozen=True)
class SkillProjection:
    """One complete, one-shot preview of the resolved collection.

    Replaces the interim `intent.IntentSet`: `intents` is the PUBLISHED
    `ordessa_harness_api.IntentSet` (MountContent/RemoveOwnedContent —
    skills contribute content, never per-skill incremental field edits);
    the frozen generation face and the declared load control ride
    alongside it, mapped onto published types by `decide_reconfiguration`.
    """

    harness_id: str
    bounds: GenerationBounds
    intents: PublishedIntentSet
    update_strategy: str  # RELOAD | RESTART_RESUME — REFUSE never projects
    reset_strategy: str   # NATIVE_RESET | OWNED_REMOVAL_ONLY
    evidence_ceiling: str  # an api.evidence level; "projected" everywhere today

    def public_dict(self) -> dict:
        return {
            "harnessId": self.harness_id,
            "bounds": {
                "runtimeGeneration": self.bounds.runtime_generation,
                "projectId": self.bounds.project_id,
                "profileRevision": self.bounds.profile_revision,
                "assignmentRevision": self.bounds.assignment_revision,
            },
            "intents": [
                {
                    "kind": intent.kind,
                    "facetId": intent.source.facet_id,
                    "itemId": intent.source.item_id,
                    "contributionVersion": intent.source.contribution_version,
                    "targetHandle": intent.target.handle_id,
                    "relativeName": intent.relative_name,
                    "contentReference": getattr(
                        intent.immutable_content_ref, "reference", None),
                    "mode": getattr(intent, "mode", None),
                }
                for intent in self.intents.intents
            ],
            "loadControl": {
                "updateStrategy": self.update_strategy,
                "resetStrategy": self.reset_strategy,
                "evidenceCeiling": self.evidence_ceiling,
            },
        }


def compile_intent_set(
    refs: Sequence[ManagedContentRef],
    target: AdapterTarget,
    *,
    harness_id: str,
    target_slot: str,
    bounds: GenerationBounds,
    removals: Sequence[ManagedContentRef] = (),
) -> SkillProjection:
    """One-shot complete projection for the whole resolved collection.

    Refuses (before any intent exists) on: foreign brand target, version
    mismatch (re-assesses; a compiled set always speaks for an assessed
    target), an internally colliding managed name set under the brand's
    comparison rules (conflict.evaluate_managed_set — no winner picking),
    or an update strategy the brand cannot honour.
    """
    assessment = assess(target, harness_id=harness_id)
    rules: NativeNameRules = name_rules_for(harness_id)
    evaluate_managed_set(refs, rules)
    seen: set[str] = set()
    handle = preview_target_handle(harness_id, bounds)
    intents = []
    for ref in refs:
        if ref.asset_id in seen:
            raise HarnessAdapterError(  # defensive; evaluate_managed_set covers
                "SKILL_NAME_COLLISION", f"duplicate asset {ref.asset_id}")
        seen.add(ref.asset_id)
        intents.append(mount_content_for(ref, handle, slot=target_slot))
    for ref in removals:
        intents.append(remove_owned_for(ref.asset_id, handle,
                                        slot=target_slot,
                                        relative_name=ref.native_name))
    update = decide_update_strategy(assessment.statement)
    if update == REFUSE:
        raise HarnessAdapterError(
            "HARNESS_LOAD_CONTROL_UNEVIDENCED",
            f"neither reload nor resume is evidenced for {harness_id!r}; "
            "refusing to declare an update the Harness cannot honour")
    return SkillProjection(
        harness_id=harness_id,
        bounds=bounds,
        intents=PublishedIntentSet(intents=tuple(intents)),
        update_strategy=update,
        reset_strategy=decide_reset_strategy(assessment.statement),
        evidence_ceiling=evidence_ceiling(assessment.statement),
    )


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

#: The observation sources an adapter may receive from the Harness side.
#: Only the last two can EVER mean more than placement, and only when the
#: brand's capability statement says the corresponding port is supported.
SOURCE_PROJECTION_DIGEST = "projection_digest"
SOURCE_NATIVE_LISTING = "native_directory_listing"
SOURCE_NATIVE_LOAD_EVENT = "native_load_event"
SOURCE_INVOCATION_EVENT = "invocation_event"
SOURCE_MODEL_CLAIM = "model_claim"
OBSERVATION_SOURCES = (
    SOURCE_PROJECTION_DIGEST, SOURCE_NATIVE_LISTING,
    SOURCE_NATIVE_LOAD_EVENT, SOURCE_INVOCATION_EVENT, SOURCE_MODEL_CLAIM,
)


@dataclass(frozen=True)
class ObservationResult:
    """One observation as reported about one managed content ref.

    `source` is which mechanism produced it; `observed_tree_digest` is what
    the mechanism saw (if anything); `session_bound` marks that an event is
    tied to this runtime generation (contracts.md: `used` 要求本会话特定
    版本的独立调用事件).
    """

    harness_id: str
    asset_id: str
    revision: int
    native_name: str
    tree_digest: str
    source: str
    observed_tree_digest: str | None = None
    session_bound: bool = False

    def __post_init__(self) -> None:
        if self.source not in OBSERVATION_SOURCES:
            raise ValueError(f"unknown observation source {self.source!r}")


@dataclass(frozen=True)
class VerificationOutcome:
    level: str
    reason: str
    statement_evidence: str

    @property
    def proves_load(self) -> bool:
        return self.level in (ladder.LOADED, ladder.USED)


def verify(observation: ObservationResult, *, harness_id: str) -> VerificationOutcome:
    """Interpret one observation into the six-level ladder (FR13, G16).

    Hard rules encoded here:

    * A digest match — of the projection or of a native directory listing —
      proves at most ``projected``, NEVER ``loaded`` (G16: 调 digest-verify
      即记 loaded 是反例; harness-adapters.md 纠正 legacy verify_load).
    * ``loaded`` additionally requires the brand's `loaded_evidence` axis
      to be `supported`; an unverified load port degrades to `unknown` —
      the ladder never moves on borrowed or implied evidence.
    * ``used`` requires a session-bound invocation event AND an evidenced
      explicit-invocation port.
    * "the model said it used it" is not an observation at all:
      ``model_claim`` always yields ``unknown`` (harness-adapters.md:
      模型口头声称"我用了"不算证据).
    """
    statement = statement_for(harness_id)
    if observation.harness_id != harness_id:
        return VerificationOutcome(ladder.UNKNOWN, "harness_identity_mismatch",
                                   statement.fact(LOADED_EVIDENCE_AXIS).evidence)
    identity_ok = observation.observed_tree_digest in (None, observation.tree_digest)
    if observation.observed_tree_digest is not None and not identity_ok:
        return VerificationOutcome(ladder.UNKNOWN, "digest_identity_mismatch",
                                   statement.fact(LOADED_EVIDENCE_AXIS).evidence)

    source = observation.source
    if source == SOURCE_MODEL_CLAIM:
        return VerificationOutcome(ladder.UNKNOWN, "model_claim_is_not_evidence",
                                   statement.fact(LOADED_EVIDENCE_AXIS).evidence)
    if source in (SOURCE_PROJECTION_DIGEST, SOURCE_NATIVE_LISTING):
        # Placement facts — capped at `projected` by the ladder itself
        # (`attest` requires load_observation/invocation_event for more).
        level = ladder.attest(ladder.PROJECTED, proofs={"projection_digest"})
        return VerificationOutcome(
            level,
            "placement_proven_load_not_observed"
            if level == ladder.PROJECTED else "unattested",
            statement.fact(LOADED_EVIDENCE_AXIS).evidence)
    if source == SOURCE_NATIVE_LOAD_EVENT:
        if statement.value(LOADED_EVIDENCE_AXIS) != SUPPORTED:
            return VerificationOutcome(
                ladder.UNKNOWN, "load_port_unverified_"
                f"{statement.value(LOADED_EVIDENCE_AXIS)}",
                statement.fact(LOADED_EVIDENCE_AXIS).evidence)
        level = ladder.attest(ladder.LOADED, proofs={"load_observation"})
        return VerificationOutcome(level, "load_observation_attested",
                                   statement.fact(LOADED_EVIDENCE_AXIS).evidence)
    # SOURCE_INVOCATION_EVENT
    if statement.value(EXPLICIT_AXIS) != SUPPORTED \
            or statement.value(LOADED_EVIDENCE_AXIS) != SUPPORTED:
        return VerificationOutcome(
            ladder.UNKNOWN, "invocation_port_unverified",
            statement.fact(EXPLICIT_AXIS).evidence)
    if not observation.session_bound:
        return VerificationOutcome(ladder.UNKNOWN, "invocation_not_session_bound",
                                   statement.fact(EXPLICIT_AXIS).evidence)
    level = ladder.attest(ladder.USED, proofs={"invocation_event"})
    return VerificationOutcome(level, "session_specific_invocation_attested",
                               statement.fact(EXPLICIT_AXIS).evidence)
