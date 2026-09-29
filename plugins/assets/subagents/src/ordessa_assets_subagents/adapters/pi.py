"""Pi conditional (extension-backed) adapter triad (G14), on the contract.

Pi has **no built-in subagent definition mechanism** (harness-adapters.md
row Pi; pi-extension-audit.md). Its subagent capability would be
extension-backed, and the audit records the precondition as verifiably false
on two independent sides today:

1. no extension package is registered in the host Pi install
   (`pi list` -> `No packages installed.`, L2-exec read-only),
2. no Harness extension audit A1–A7 exists in this repo, and
3. the pinned adapter `@automatalabs/pi-acp@0.5.0` dist exposes no
   subagent/agents surface at all (L2-static grep, zero hits).

So `assess` answers **unsupported** (absence is *proven*, so it is not the
`unknown` that unanswered A1–A7 items alone would give), and `compile` raises
a typed refusal **before producing any intent**. SR-1b answer on expressing
「extension-backed absent」 in the published contract: there is no dedicated
status — the vocabulary's best available spelling is
`Assessment(status="unsupported", reason=<named absence>, evidence_ref=…)`
plus an **empty `FieldClaim` tuple** on the descriptor (nothing claimable)
and the `reason` carried per cell internally; that is what this adapter
emits. The old `TargetSlot` had no Pi member — the empty claims tuple is the
same fact in contract types.

The audited-extension precondition is modelled as an injected
:class:`AuditedExtensionRegistry` protocol: only a Harness-granted record
`{registered, owner, pinned_commit, license, review_ref}` clears the
ADAPTER_MISSING stage — a *self-declared* record (missing owner/review_ref,
or owner = this definitions plugin) does not, because §C3 forbids the
definitions plugin from shipping its own hidden execution host. Even with a
granted record, compilation stays refused with NATIVE_ENTRY_UNAVAILABLE: no
Pi definition document format and no real control port (A6) exist at the
pin, and emitting one would invent a format the matrix marks absent. Q3
never installs the sample extension to buy a green.

This module is pure: no process is ever spawned and nothing is written; the
content comes in, the refusal goes out.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, IntentSet, ValueSchema, VersionRange,
)

from .. import errors
from . import base, intents

PI_HARNESS_ID = "pi"
PI_ADAPTER_PIN = "@automatalabs/pi-acp@0.5.0"
PI_PACKAGES_PIN = "0.84.2"
PI_ADAPTER_SEMVER = (0, 5, 0)
PI_PACKAGES_SEMVER = (0, 84, 2)
HOST_PI_VERSION = "0.86.1"  # pin drift: host observations are NOT pin evidence

#: The one extension identity the audit discusses (pi-extension-audit.md A1).
PI_SUBAGENT_EXTENSION_ID = "examples/extensions/subagent"

_COMMIT_RE = re.compile(r"\A[0-9a-f]{40}\Z")

#: A registry record is only *audited* if the Harness — never the definitions
#: plugin — owns the execution host (§C3: 「定义插件不能自带一个隐藏执行宿主」).
_SELF_DECLARED_OWNERS = frozenset({
    "assets.native-subagents", "native-subagents", "ordessa_assets_subagents",
    "q3", "self", "definitions-plugin",
})

_EVIDENCE_ABSENT: tuple[str, ...] = (
    "pi-extension-audit.md §measured starting state: `pi list` exits 0 with "
    "'No packages installed.' — no extension package of any kind is registered",
    "pi-extension-audit.md items A1–A7: no Harness extension audit exists in this "
    "repo (provenance/license, registration, trust boundary, process model, "
    "cancellation, control port, pinned-version re-run — all unanswered)",
    "capability-matrix.md §Pi: pinned automatalabs-pi-acp-0.5.0 dist has ZERO "
    "'subagent' / '.pi/extensions' / agents-directory hits (L2-static)",
    "capability-matrix.md §Pi: `pi --help` shows extension mechanism but no "
    "built-in agents file mechanism; ~/.pi/agents absent",
)

_PI_PAYLOAD_SCHEMA = ValueSchema(
    "object",
    properties=(("definitions", ValueSchema("array", items=ValueSchema("string"))),),
    required=("definitions",),
)


@runtime_checkable
class AuditedExtensionRegistry(Protocol):
    """The Harness-side registry C0 owns (SR-1 'the registry call that
    grants the owner'). Q3 only ever *reads* it; it cannot write one."""

    def lookup_extension(self, extension_id: str) -> "Mapping[str, Any] | None":
        """Return the granted audit record for `extension_id`, or None."""
        ...


def audit_gap(record: "Mapping[str, Any] | None") -> str | None:
    """Why the audited-extension precondition is NOT met, or None if met.

    Deliberately strict: a record that is self-declared (no owner, or an
    owner that is this very definitions plugin) or incomplete (no review
    ref, no pinned commit, no license) does not unlock anything.
    """
    if record is None:
        return ("no Harness-registered audited extension: the Pi adapter needs "
                "the subagent extension as a Harness execution dependency (A2); "
                "none is registered (A1–A7 unanswered, `pi list` -> 'No packages "
                "installed.')")
    if not record.get("registered"):
        return "the registry record does not answer registered=True"
    owner = record.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        return ("the record carries no owner: ownership is granted by the host, "
                "never self-declared by the contributor (§C3)")
    if owner.strip().lower() in _SELF_DECLARED_OWNERS:
        return (f"the record's owner {owner!r} is the definitions plugin's own "
                "identity: a self-declared registry does not unlock compilation "
                "(§C3 forbids shipping a hidden execution host)")
    commit = record.get("pinned_commit")
    if not isinstance(commit, str) or _COMMIT_RE.fullmatch(commit) is None:
        return ("the record carries no full 40-hex pinned commit: vendoring "
                "requires a fixed commit, not 'latest' (A1, G21)")
    if not isinstance(record.get("license"), str) or not record["license"].strip():
        return "the record carries no license entry (A1/G15)"
    review_ref = record.get("review_ref")
    if not isinstance(review_ref, str) or not review_ref.strip():
        return ("the record carries no review reference: without the Harness "
                "audit artifact this is a self-declaration with extra steps (A2)")
    return None


class PiAdapter(base.ConfigurationAdapter):
    """Triad whose honest output today is `unsupported` + typed refusal."""

    adapter_id = "ordessa.assets.native-subagents.pi"
    harness_id = PI_HARNESS_ID
    pinned_version = PI_ADAPTER_PIN
    #: No file-format target exists at any pin (Pi definitions would arrive
    #: through an audited extension, not a mount directory), so the descriptor
    #: claims NOTHING and `compile` can never emit a mount — the contract
    #: spelling of the old "no Pi TargetSlot member" fact.
    mount_suffix = ".md"

    descriptor = ConfigurationAdapterDescriptor(
        adapter_id, "v1", intents.FACET_ID, "v1", PI_HARNESS_ID,
        VersionRange(PI_PACKAGES_SEMVER, PI_PACKAGES_SEMVER),
        VersionRange(PI_ADAPTER_SEMVER, PI_ADAPTER_SEMVER),
        ("acp",),
        _PI_PAYLOAD_SCHEMA,
        (),
    )

    def __init__(self, extension_registry: AuditedExtensionRegistry | None = None) -> None:
        self._registry = extension_registry

    # -- assess ---------------------------------------------------------------
    def assess_detail(self, context: Any, request: Any = None) -> base.Assessment:
        self._validate_context(context)
        unsupported = base.AssessmentState.UNSUPPORTED
        unknown = base.AssessmentState.UNKNOWN
        cells = (
            base.CellVerdict(
                cell="extension-registered", state=unsupported,
                reason=("the precondition is verifiably false on this host: no "
                        "extension package is registered in the Pi install "
                        "(pi list -> 'No packages installed.', L2-exec read-only)"),
                evidence=_EVIDENCE_ABSENT),
            base.CellVerdict(
                cell="harness-extension-audit", state=unsupported,
                reason=("items A1–A7 are owned by C0 and none is answered in this "
                        "repo; Q3 must not substitute its own audit or install the "
                        "example extension (G14)"),
                evidence=_EVIDENCE_ABSENT),
            base.CellVerdict(
                cell="pinned-adapter-surface", state=unsupported,
                reason=("@automatalabs/pi-acp@0.5.0 dist exposes no subagent/agents "
                        "surface (zero hits, L2-static): the ACP path as pinned has "
                        "no entry to assess"),
                evidence=_EVIDENCE_ABSENT),
            base.CellVerdict(
                cell="example-extension-governance", state=unknown,
                reason=("whether the official examples/extensions/subagent behaves "
                        "to Ordessa governance (permissions/cancel/resume) is NOT "
                        "proven — unmeasured, never assumed good or bad (A3–A7)"),
                evidence=("pi-extension-audit.md 'Not proven' row",)),
        )
        return base.Assessment(
            state=unsupported,
            pinned_version=(f"adapter {PI_ADAPTER_PIN} / packages {PI_PACKAGES_PIN} "
                            f"(host pi {HOST_PI_VERSION}: pin drift, host facts are "
                            "not pin facts)"),
            evidence=_EVIDENCE_ABSENT,
            reasons=(
                "extension-backed: absent — no silent 'unknown' when the absence "
                "itself is proven (pi-extension-audit.md §Q3 behaviour-1); the "
                "unmeasured governance question stays a separate 'unknown' cell",
            ),
            cells=cells,
        )

    # -- compile ---------------------------------------------------------------
    def compile(self, context: Any, collection: Sequence[intents.ManagedItem],
                source: Any = None, *, native_names: frozenset[str] | None = None,
                stage_content: Any = None,
                secret_bindings: Sequence[tuple[str, str]] = ()) -> IntentSet:
        """Refuse before any intent exists — precondition first, item checks
        never reached while the execution host is unregistered."""
        self._validate_context(context)
        gap = audit_gap(
            self._registry.lookup_extension(PI_SUBAGENT_EXTENSION_ID)
            if self._registry is not None else None
        )
        items = tuple(collection)
        first_id = items[0].definition.definition_id if items else None
        if gap is not None:
            raise errors.DomainError(
                errors.ADAPTER_MISSING, item_id=first_id,
                detail=(f"Pi is extension-backed and the audited extension is absent: {gap}. "
                        "Q3 never installs the sample extension to buy a green "
                        "(pi-extension-audit.md, G14)."),
            )
        # A granted, complete audit record clears ADAPTER_MISSING — but not
        # more: no Pi definition document format and no proven control entry
        # (A6) exist at the pin, so there is nothing type-safe to compile TO.
        raise errors.DomainError(
            errors.NATIVE_ENTRY_UNAVAILABLE, item_id=first_id,
            detail=("the audited extension is registered, but no proven native "
                    "control entry / definition surface exists for the pinned "
                    "@automatalabs/pi-acp@0.5.0 adapter (A6 unresolved; capability-"
                    "matrix §Pi: adapter dist has no subagent surface), so "
                    "compilation stays refused rather than inventing a format"),
        )

    # -- verify ----------------------------------------------------------------
    def _on_observation_kind(self, observation: base.Observation) -> None:
        """There is nothing Pi-side to observe: no Pi IntentSet can exist
        (see compile), and no loader/control/event fact has a possible source
        at this pin. Ladder-path claims are refused (contract-shaped
        `verify` maps the refusal to `Mismatch`); a bare projection sighting
        yields `unknown`, never `loaded` (G14 counter-example shape)."""
        if observation.__class__ in (base.NativeLoaderObservation,
                                     base.ControlEntryObservation,
                                     base.InvocationEventObservation):
            raise errors.DomainError(
                errors.NATIVE_ENTRY_UNAVAILABLE, item_id=observation.native_name,
                detail=(f"a {type(observation).__name__} for {observation.native_name!r} has no "
                        "possible source: Pi exposes no subagent loader, control "
                        "entry or event surface at the pinned adapter (pi-extension-"
                        "audit.md), and no audited extension is registered"),
            )
