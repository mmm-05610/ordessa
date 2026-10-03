"""Profile facet for native-subagent definitions (T10, gate G16).

Pure domain glue between this definition library and the Profile v2 facet
surface (`docs/design/native-subagents/contracts.md` §C2,
`docs/design/profile-v2/contracts.md` §1): the facet contributes *candidate
definition references* plus the tri-state decision (inherit / enable a pinned
approved revision / disable a managed item), the pinned revision itself, and
read-only capability diagnostics.  Profile stores the reference and the
choice; this domain keeps the body and the provenance — nothing here copies
definition content into a facet value.

Design locks, each proven in ``tests/test_profile_facet_t10.py``:

* **No Profile import in this package.** The package registers as
  stdlib-only (`integration-request.md` I-1; `test_boundaries_t03b.py`), so
  the Z1 vocabulary (`FacetDescriptor`, `ItemDescriptor`, `Applicability`,
  `Violation`, `CompileResult`, `ConfigIntent`, `MigratedItems`,
  `MigrationUnsupported`, `SessionRef`, `AppliedReceipt`, `JournalEntry`,
  ``UNSET``) is *injected* through :class:`ProfileV2Api` by the composition
  root that already imports ``ordessa_profile.contracts``.  A missing seam
  is a typed refusal (:data:`errors.ADAPTER_MISSING`), never a fallback copy
  of Z1's types.
* **Ownership is host-injected** (design §C1/§C3, "注册 owner 由宿主授予"):
  the provider object deliberately carries no ``owner_plugin_id``; the owner
  is passed to ``register_v2_facet(provider, owner)`` by the host.
* **The effective set is single-sourced** (contracts §C1, "不能让前端重写
  覆盖算法"): every read goes through the bound resolver, which must be
  :func:`resolution.resolve_preview`.  This module re-implements no layering;
  a caller-supplied effective set is actively refused in
  :meth:`NativeSubagentsFacet.compile` and :func:`build_submission`.
* **G16 — next submission:** saving a choice records a *desired* choice
  only.  The effective snapshot is built at submit time by
  :func:`build_snapshot`, pinning definition revisions, assignment row
  versions and the adapter generation.  A failed or unknown application
  never clears the previous coverage; an unknown outcome stays queryable
  and is never projected as success (see :func:`apply_outcome_projection`).
* **Unknown brand honesty (G01–G03 facts):** :func:`default_capability_matrix`
  renders the pinned brands from `specs/011-q3-subagents/capability-matrix.md`
  — nothing is provably invokable at these pins.  Applicability is therefore
  ``unknown``/``unsupported`` with evidence; a Profile save never implies the
  definition will load, and :meth:`NativeSubagentsFacet.compile` refuses to
  emit intents without a provably supported brand.
* **Fail-closed on unknown fragments** (§C2, data-model "未知 provider/旧
  schema 的已存片段保留，不能编译入运行"): stored fragments whose provider
  or schema version this domain cannot compile are refused at validate/
  migrate/compile time while the stored bytes stay untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from . import errors
from .assignments import AssignmentDecision
from .resolution import (
    DefinitionSnapshot,
    EffectiveSet,
    ResolvedDefinition,
    build_snapshot,
)

# -- facet identity (contracts.md §C2: facet id is frozen) ------------------

FACET_ID = "assets.native-subagents"
FACET_API_MAJOR = 2
CHOICE_SCHEMA_VERSION = "1.0.0"

#: One stored choice item per candidate definition; the item id carries the
#: reference, the value carries only decision + pinned revision.
CHOICE_ITEM_PREFIX = "definition."

#: Read-only capability diagnostics projection item (never user-writable).
DIAGNOSTICS_ITEM_ID = "capability-diagnostics"

CHOICE_KEYS = frozenset({"provider", "schema_version", "decision", "revision"})

#: A caller-computed effective set smuggled in under any of these keys is
#: refused outright (§C1 single-sourcing guard; mutation-proven in tests).
RESERVED_EFFECTIVE_SET_KEYS: tuple[str, ...] = (
    "effective_set",
    "effectiveSet",
    f"{FACET_ID}.effective_set",
)

#: capability status vocabulary — the same three answers Profile renders
STATUS_SUPPORTED = "supported"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNKNOWN = "unknown"

#: the two journal/receipt states that may ever evidence a cleanup
JOURNAL_CONFIRMED = "confirmed"
EVIDENCE_LEGACY_UNVERIFIED = "legacy-unverified"

#: Violation codes this facet raises.  ``FACET_VALUE_INVALID`` is the code
#: the Profile storage path already understands; the facet-specific codes
#: surface verbatim in ``SWITCH_BLOCKED`` blockers so a refusal stays
#: locatable and never degrades into "plugin broken".
VIOLATION_SUBSTITUTION = "FACET_EFFECTIVE_SET_SUBSTITUTION"
VIOLATION_NOT_ADMITTED = "FACET_EFFECTIVE_SET_MISMATCH"
VIOLATION_APPLY_REFUSED = "FACET_APPLY_REFUSED_NO_EVIDENCE"
VIOLATION_UNKNOWN_FRAGMENT = "FACET_UNKNOWN_FRAGMENT"
VIOLATION_VALUE_INVALID = "FACET_VALUE_INVALID"
VIOLATION_NATIVE_UNCONTROLLED = errors.NATIVE_DISCOVERY_UNCONTROLLED


def choice_item_id(definition_id: str) -> str:
    """The facet item id that carries one definition's reference + choice."""
    return f"{CHOICE_ITEM_PREFIX}{definition_id}"


def definition_id_from_item(item_id: str) -> str | None:
    if not item_id.startswith(CHOICE_ITEM_PREFIX):
        return None
    return item_id[len(CHOICE_ITEM_PREFIX):] or None


# --------------------------------------------------------------------------
# injected Z1 vocabulary
# --------------------------------------------------------------------------

_API_SYMBOLS: tuple[str, ...] = (
    "FacetDescriptor", "ItemDescriptor", "Applicability", "Violation",
    "CompileResult", "ConfigIntent", "MigratedItems", "MigrationUnsupported",
    "SessionRef", "AppliedReceipt", "JournalEntry", "UNSET",
)


@dataclass(frozen=True)
class ProfileV2Api:
    """The published Profile v2 contract vocabulary, injected at composition.

    :meth:`from_contracts` binds against the *real* module surface; when a
    symbol is missing the facet refuses with ``ADAPTER_MISSING`` instead of
    inventing a look-alike type (there is deliberately no fallback model).
    """

    FacetDescriptor: type
    ItemDescriptor: type
    Applicability: Any
    Violation: type
    CompileResult: type
    ConfigIntent: type
    MigratedItems: type
    MigrationUnsupported: type
    SessionRef: type
    AppliedReceipt: type
    JournalEntry: type
    UNSET: Any

    @staticmethod
    def from_contracts(contracts_module: Any) -> "ProfileV2Api":
        missing = [
            name for name in _API_SYMBOLS if not hasattr(contracts_module, name)
        ]
        if missing:
            raise errors.refused(
                errors.ADAPTER_MISSING,
                item_id="ProfileV2Api",
                detail="the published Profile v2 contract surface is missing "
                       f"symbols {missing}; the facet refuses to substitute a "
                       "look-alike model",
            )
        return ProfileV2Api(**{name: getattr(contracts_module, name)
                               for name in _API_SYMBOLS})


# --------------------------------------------------------------------------
# candidate + capability read models
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateDefinition:
    """The reference-shaped projection of one managed definition.

    Only what an editor may show and a choice may bind: identity, the pinned
    revision options, and whether the item is managed (disabling a natively
    discovered definition is not controllable — US5).  Body and provenance
    stay in this domain's store.
    """

    definition_id: str
    slug: str
    display_name: str
    latest_revision: int
    managed: bool
    approved_revisions: frozenset[int] = frozenset()


@dataclass(frozen=True)
class BrandCapability:
    """One honest capability cell: a status plus its evidence, nothing else.

    ``supported`` is admissible only with evidence that the brand's own
    application path is proven at its pin; nothing on the current pins
    qualifies, which is why :func:`default_capability_matrix` contains no
    supported cell at all.
    """

    brand: str
    status: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in (STATUS_SUPPORTED, STATUS_UNSUPPORTED, STATUS_UNKNOWN):
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id=f"capability:{self.brand}",
                detail="capability status must be supported / unsupported / unknown",
            )
        if isinstance(self.evidence, str) or not isinstance(self.evidence, tuple):
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id=f"capability:{self.brand}",
                detail="evidence must be a tuple of citations",
            )
        if not self.evidence:
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id=f"capability:{self.brand}",
                detail="a capability verdict without evidence is not a verdict",
            )
        if not all(isinstance(entry, str) and entry.strip()
                   for entry in self.evidence):
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id=f"capability:{self.brand}",
                detail="every capability verdict needs non-empty evidence",
            )
        if self.status == STATUS_SUPPORTED:
            # a 'supported' cell must name its proof source explicitly
            if not any(":" in entry for entry in self.evidence):
                raise errors.refused(
                    errors.DEFINITION_INVALID, item_id=f"capability:{self.brand}",
                    detail="supported requires an evidence citation",
                )

    def to_mapping(self) -> dict[str, Any]:
        return {"brand": self.brand, "status": self.status,
                "evidence": list(self.evidence)}


#: Measured facts of 2026-09-28 (specs/011-q3-subagents/capability-matrix.md,
#: pi-extension-audit.md).  Nothing is provably invokable at these pins:
#: Claude is unprovable (executable absent, rebuild-class options only ⇒
#: unknown); Codex subagent discovery is proven absent in the pinned adapter
#: (unsupported); Pi has no reviewed extension registered (unsupported).
_CAPABILITY_EVIDENCE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("claude", STATUS_UNKNOWN, (
        "capability-matrix.md: `claude` executable ABSENT from PATH — L2-exec "
        "blocked (SR-2), so no invokability claim",
        "capability-matrix.md C-6: `agents`/`settingSources` are rebuild-class "
        "options at adapter 0.81.2 — no proved in-place reload",
        "capability-matrix.md field matrix: explicit invocation action stays "
        "`unknown` until reachable through Ordessa's own ACP path (G17)",
    )),
    ("codex", STATUS_UNSUPPORTED, (
        "capability-matrix.md: `.codex/agents`, agent-directory scan and "
        "`subagent` — zero hits in pinned @agentclientprotocol/codex-acp "
        "1.1.14 ⇒ discovery proven absent at this pin",
        "capability-matrix.md: `codex` executable ABSENT from PATH; a "
        "generated `.codex/agents/*.toml` cannot be claimed loaded",
    )),
    ("pi", STATUS_UNSUPPORTED, (
        "pi-extension-audit.md A1–A7: no reviewed extension is registered in "
        "the Harness runtime; measured `pi list` is empty on this host",
        "contracts §C3: Pi requires an owned, reviewed executable extension — "
        "absent ⇒ the facet stays unsupported for pi (T08)",
    )),
)


def default_capability_matrix() -> dict[str, BrandCapability]:
    """The honest capability matrix for the current pins (no supported cell)."""
    return {
        brand: BrandCapability(brand=brand, status=status, evidence=evidence)
        for brand, status, evidence in _CAPABILITY_EVIDENCE
    }


# --------------------------------------------------------------------------
# stored choice encoding
# --------------------------------------------------------------------------


def encode_choice(decision: AssignmentDecision,
                  revision: int | None = None) -> dict[str, Any]:
    """The complete stored shape of one facet choice.

    Reference + decision + pin — never body, never provenance, never a
    credential (a facet value is a declaration, §C2).
    """
    if not isinstance(decision, AssignmentDecision):
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="decision",
            detail="decision must be one of inherit / enable / disable",
        )
    if decision is AssignmentDecision.ENABLE and revision is None:
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="revision",
            detail="enable must pin a revision; a floating enable would "
                   "silently follow content edits (FR02)",
        )
    if decision is not AssignmentDecision.ENABLE and revision is not None:
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="revision",
            detail="only an enable choice may carry a pinned revision",
        )
    return {
        "provider": FACET_ID,
        "schema_version": CHOICE_SCHEMA_VERSION,
        "decision": decision.value,
        "revision": revision,
    }


def decode_choice(value: Any) -> tuple[AssignmentDecision, int | None]:
    """Strict read-back of one stored choice; anything unknown refuses.

    The provider identity and schema version inside the fragment are checked
    so an unknown provider / old schema fragment can never compile into a
    running intent (§C2 fail-closed rule).
    """
    if not isinstance(value, Mapping):
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="choice",
            detail="a stored choice must be an object",
        )
    if set(value) - CHOICE_KEYS:
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="choice",
            detail="unknown keys in a stored choice fragment",
        )
    if value.get("provider") != FACET_ID or value.get("schema_version") != CHOICE_SCHEMA_VERSION:
        raise errors.refused(
            errors.REVISION_STALE, item_id="choice",
            detail="stored fragment names an unknown provider or schema "
                   "version; it is kept but never compiled in",
        )
    raw_decision = value.get("decision")
    try:
        decision = AssignmentDecision(raw_decision)
    except ValueError:
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="decision",
            detail="stored decision is not one of inherit / enable / disable",
        ) from None
    revision = value.get("revision")
    if decision is AssignmentDecision.ENABLE:
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id="revision",
                detail="an enable choice lost its pinned revision",
            )
        return decision, revision
    if revision is not None:
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="revision",
            detail="only an enable choice may carry a pinned revision",
        )
    return decision, None


# --------------------------------------------------------------------------
# the facet provider
# --------------------------------------------------------------------------


class NativeSubagentsFacet:
    """One Profile v2 facet provider (the ``FacetProviderV2`` shape).

    Parameters
    ----------
    api:
        the injected Z1 vocabulary (:class:`ProfileV2Api`).
    candidates:
        a zero-argument read returning the current
        ``CandidateDefinition`` rows — references only.
    approvals:
        the ``ApprovalAuthority`` protocol of ``assignments.py``: answers
        "was exactly this revision approved?".  There is no default; an
        absent authority cannot wave an enable through.
    resolve_effective:
        a zero-argument read returning the current
        :class:`resolution.EffectiveSet`.  It MUST be bound to
        :func:`resolution.resolve_preview` (or the service read path over
        it).  This class performs no layering itself and refuses any
        caller-supplied set (:data:`RESERVED_EFFECTIVE_SET_KEYS`).
    capabilities:
        brand → :class:`BrandCapability`; empty (the default) can only ever
        answer ``unknown`` — absence of evidence never promotes to supported.

    The instance deliberately has no ``owner_plugin_id`` / ``facet_version``
    attribute: ownership is granted by the host at registration
    (``register_v2_facet(provider, owner)``), never self-declared.
    """

    def __init__(
        self,
        api: ProfileV2Api,
        *,
        candidates: Callable[[], Sequence[CandidateDefinition]],
        approvals: Any,
        resolve_effective: Callable[[], EffectiveSet],
        capabilities: Mapping[str, BrandCapability] | None = None,
        schema_version: str = CHOICE_SCHEMA_VERSION,
        facet_id: str = FACET_ID,
    ) -> None:
        if approvals is None or not hasattr(approvals, "has_approved_revision"):
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id="approvals",
                detail="the facet requires the ApprovalAuthority protocol; "
                       "an absent authority can never wave an enable through",
            )
        if not callable(resolve_effective) or not callable(candidates):
            raise errors.refused(
                errors.DEFINITION_INVALID, item_id="resolve_effective",
                detail="the facet requires bound candidate and effective-set "
                       "reads (resolution.resolve_preview is the resolver)",
            )
        self._api = api
        self._facet_id = facet_id
        self._schema_version = schema_version
        self._candidates = candidates
        self._approvals = approvals
        self._resolve_effective = resolve_effective
        self._capabilities = dict(capabilities or {})

    # -- reads ----------------------------------------------------------
    @property
    def facet_id(self) -> str:
        return self._facet_id

    def candidate_map(self) -> dict[str, CandidateDefinition]:
        return {c.definition_id: c for c in self._candidates()}

    def effective_set(self) -> EffectiveSet:
        """The single-sourced effective set: a fresh resolver call.

        Never cached, never accepted from a caller: the profile-layer choice
        in Profile storage is an *input* to the resolver, not its result.
        """
        return self._resolve_effective()

    def capability_diagnostics(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            self._capabilities[brand].to_mapping()
            for brand in sorted(self._capabilities)
        )

    # -- FacetProviderV2 surface ----------------------------------------
    def descriptor(self) -> Any:
        api = self._api
        items = [
            api.ItemDescriptor(
                item_id=DIAGNOSTICS_ITEM_ID,
                value_schema={
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "read-only capability diagnostics derived "
                                   "by the assets domain",
                },
                optional=True,
                override_supported=False,
                sensitivity="non-secret",
                effect="capability-selection",
                title="Capability diagnostics",
                description="Per-brand support facts with evidence; derived, "
                            "never user-settable.",
            )
        ]
        for candidate in sorted(self._candidates(),
                                key=lambda c: c.definition_id):
            items.append(api.ItemDescriptor(
                item_id=choice_item_id(candidate.definition_id),
                value_schema={
                    "type": "object",
                    "description": "tri-state choice over one definition "
                                   "reference (decision + pinned revision)",
                },
                optional=True,
                override_supported=True,
                sensitivity="non-secret",
                effect="capability-selection",
                title=candidate.display_name,
                description=(
                    "inherit defers to the lower layers; enable pins one "
                    "approved revision; disable only acts on a managed item"
                ),
            ))
        return api.FacetDescriptor(
            facet_id=self._facet_id,
            api_major=FACET_API_MAJOR,
            schema_version=self._schema_version,
            label="Native subagent definitions",
            description=("candidate definitions, tri-state choices with "
                         "pinned revisions and read-only capability "
                         "diagnostics; bodies stay in the definition library"),
            category="capabilities",
            order=40,
            item_descriptors=tuple(items),
        )

    def applicability(self, capability_facts: Mapping[str, Any]) -> Any:
        brand = capability_facts.get("harness_id") if isinstance(
            capability_facts, Mapping) else None
        cell = self._capabilities.get(brand) if isinstance(brand, str) else None
        if cell is None:
            # no evidence at all — never promoted, never guessed from the
            # brand name (profile-v2 §1: applicability 只消费真实能力事实)
            return self._api.Applicability.UNKNOWN
        if cell.status == STATUS_SUPPORTED:
            return self._api.Applicability.SUPPORTED
        if cell.status == STATUS_UNSUPPORTED:
            return self._api.Applicability.UNSUPPORTED
        return self._api.Applicability.UNKNOWN

    def validate(self, items: Mapping[str, Any],
                 reference_facts: Mapping[str, Any]) -> tuple[Any, ...]:
        del reference_facts
        api = self._api
        violations: list[Any] = []
        candidates = self.candidate_map()
        for item_id in sorted(items):
            value = items[item_id]
            if item_id == DIAGNOSTICS_ITEM_ID:
                violations.append(self._violation(
                    item_id, VIOLATION_VALUE_INVALID,
                    "capability diagnostics are derived read-only; a stored "
                    "patch cannot set them"))
                continue
            definition_id = definition_id_from_item(item_id)
            if definition_id is None:
                violations.append(self._violation(
                    item_id, VIOLATION_VALUE_INVALID,
                    "item does not belong to this facet"))
                continue
            candidate = candidates.get(definition_id)
            if candidate is None:
                violations.append(self._violation(
                    item_id, VIOLATION_VALUE_INVALID,
                    "definition reference is not a candidate of this facet"))
                continue
            violations.extend(self._validate_choice(item_id, definition_id,
                                                    candidate, value))
        return tuple(violations)

    def _validate_choice(self, item_id: str, definition_id: str,
                         candidate: CandidateDefinition,
                         value: Any) -> list[Any]:
        try:
            decision, revision = decode_choice(value)
        except errors.DomainError as exc:
            return [self._violation(item_id, VIOLATION_UNKNOWN_FRAGMENT,
                                    f"{exc.code}: {exc.detail or ''}".strip())]
        if decision is AssignmentDecision.ENABLE:
            assert revision is not None
            if not self._approvals.has_approved_revision(definition_id, revision):
                return [self._violation(
                    item_id, VIOLATION_VALUE_INVALID,
                    f"pinned revision {revision} has no approval record; each "
                    "upgrade needs its own approval (FR02)")]
        elif decision is AssignmentDecision.DISABLE and not candidate.managed:
            return [self._violation(
                item_id, VIOLATION_NATIVE_UNCONTROLLED,
                "the item is natively discovered; it stays visible and a "
                "disable here is not honoured (US5)")]
        return []

    def _violation(self, item_id: str, code: str, message: str) -> Any:
        return self._api.Violation(facet_id=self._facet_id, item_id=item_id,
                                   code=code, message=message)

    def migrate(self, old_schema_version: str,
                stored_items: Mapping[str, Any]) -> Any:
        api = self._api
        if old_schema_version != self._schema_version:
            return api.MigrationUnsupported(
                reason="this domain cannot compile fragments of provider or "
                       "schema version it does not know; the stored bytes "
                       "are kept",
                from_schema_version=old_schema_version,
                to_schema_version=self._schema_version,
            )
        for item_id in sorted(stored_items):
            if item_id == DIAGNOSTICS_ITEM_ID:
                return api.MigrationUnsupported(
                    reason="read-only diagnostics are derived, not stored",
                    from_schema_version=old_schema_version,
                    to_schema_version=self._schema_version,
                )
            definition_id = definition_id_from_item(item_id)
            if definition_id is None:
                return api.MigrationUnsupported(
                    reason="item does not belong to this facet",
                    from_schema_version=old_schema_version,
                    to_schema_version=self._schema_version,
                )
            try:
                decode_choice(stored_items[item_id])
            except errors.DomainError as exc:
                return api.MigrationUnsupported(
                    reason=f"{exc.code}: unknown fragments are kept but never "
                           "compiled in",
                    from_schema_version=old_schema_version,
                    to_schema_version=self._schema_version,
                )
        # every fragment is already in the current shape: return NO rewritten
        # items, so a reload accepts them verbatim and the stored bytes stay
        # untouched (unload hides — it never deletes).
        return api.MigratedItems(items=(), from_schema_version=old_schema_version,
                                 to_schema_version=self._schema_version)

    def compile(self, resolved_items: Mapping[str, Any],
                target_facts: Mapping[str, Any]) -> Any:
        api = self._api
        facts = target_facts if isinstance(target_facts, Mapping) else {}
        smuggled = [key for key in RESERVED_EFFECTIVE_SET_KEYS if key in facts]
        if smuggled:
            # §C1: the effective set belongs to the domain resolver; a
            # caller-computed set is refused before a single intent exists.
            return api.CompileResult(violations=(self._violation(
                ",".join(smuggled), VIOLATION_SUBSTITUTION,
                "the effective set is computed by this domain's resolver; a "
                "caller-supplied set is refused and nothing is applied"),))
        if self.applicability(facts) is not api.Applicability.SUPPORTED:
            # a Profile save never implies the definition will load: without
            # a proven-supported brand this facet compiles no intents at all.
            evidence = self.capability_diagnostics()
            return api.CompileResult(violations=(self._violation(
                "*", VIOLATION_APPLY_REFUSED,
                "no capability evidence proves this target brand as "
                "supported; choices are stored but not applied "
                + str([cell["brand"] for cell in evidence])),))
        try:
            effective = self.effective_set()
        except errors.DomainError as exc:
            return api.CompileResult(violations=(self._violation(
                "__effective_set__", VIOLATION_NOT_ADMITTED,
                f"the resolver refused: {exc.code}: {exc.detail or ''}".strip()),))
        admitted: dict[str, ResolvedDefinition] = {
            row.definition_id: row for row in effective.resolved
        }
        intents: list[Any] = []
        violations: list[Any] = []
        source = (f"profile@{facts.get('source_revision')}"
                  if facts.get("source_revision") else "profile")
        desired_ids = set(resolved_items)
        for item_id in sorted(resolved_items):
            definition_id = definition_id_from_item(item_id)
            try:
                decision, revision = decode_choice(resolved_items[item_id])
            except errors.DomainError as exc:
                violations.append(self._violation(
                    item_id, VIOLATION_UNKNOWN_FRAGMENT,
                    f"{exc.code}: kept, never compiled in"))
                continue
            if decision is AssignmentDecision.ENABLE:
                row = admitted.get(definition_id)
                if row is None or row.revision != revision:
                    violations.append(self._violation(
                        item_id, VIOLATION_NOT_ADMITTED,
                        "the stored choice is not part of the resolver's "
                        "effective set; the Profile save does not imply the "
                        "definition will load"))
                    continue
                intents.append(api.ConfigIntent(
                    facet_id=self._facet_id, item_id=item_id, op="set",
                    native_key=f"{self._facet_id}.{item_id}", source=source,
                    value={"definition_id": definition_id,
                           "revision": row.revision},
                ))
            else:
                # disable / inherit: our contribution for the item goes away
                intents.append(api.ConfigIntent(
                    facet_id=self._facet_id, item_id=item_id, op="reset",
                    native_key=f"{self._facet_id}.{item_id}", source=source,
                ))
        current_items = facts.get("current_items") or {}
        for item_id in sorted(current_items):
            if item_id in desired_ids or item_id == DIAGNOSTICS_ITEM_ID:
                continue
            if definition_id_from_item(item_id) is None:
                continue
            # an item that vanished between the two sides still needs an
            # explicit reset — a removal may never quietly disappear (G08)
            intents.append(api.ConfigIntent(
                facet_id=self._facet_id, item_id=item_id, op="reset",
                native_key=f"{self._facet_id}.{item_id}", source=source,
            ))
        return api.CompileResult(intents=tuple(intents),
                                 violations=tuple(violations))

    # -- session overlay (§ Profile v2) ---------------------------------
    def overlay_intent(self, item_id: str, choice: Mapping[str, Any],
                       *, overlay_revision: int) -> Any:
        """One session-scoped choice as their ``ConfigIntent`` vocabulary.

        The source string names the overlay revision, mirroring profile-v2
        ``application.md`` — a stored overlay is a desired value for this
        session, never a claim that anything applied.
        """
        decision, revision = decode_choice(choice)
        op = "set" if decision is AssignmentDecision.ENABLE else "reset"
        value = ({"definition_id": definition_id_from_item(item_id),
                  "revision": revision} if op == "set" else self._api.UNSET)
        return self._api.ConfigIntent(
            facet_id=self._facet_id, item_id=item_id, op=op,
            native_key=f"{self._facet_id}.{item_id}",
            source=f"session-overlay@{overlay_revision}",
            value=value,
        )


# --------------------------------------------------------------------------
# next-submission snapshot (G16 positive)
# --------------------------------------------------------------------------


def build_submission(
    facet: NativeSubagentsFacet,
    request: Any,
    *,
    approvals: Any,
    runtime_generation: str,
    profile_revision: int,
    adapter_generation: str,
    effective_set: EffectiveSet | None = None,
) -> DefinitionSnapshot:
    """Freeze the effective snapshot for ONE submission.

    ``effective_set`` exists only to be refused: passing a locally computed
    set raises ``DEFINITION_INVALID`` before anything is pinned (contracts
    §C1 "不能让前端重写覆盖算法").  The snapshot itself is built from a fresh
    :meth:`NativeSubagentsFacet.effective_set` read — pinning definition
    revisions, assignment row versions and the adapter generation — so a
    choice saved mid-output can only ever land in the *next* snapshot.
    """
    if effective_set is not None:
        raise errors.refused(
            errors.DEFINITION_INVALID, item_id="__effective_set__",
            detail="the effective set is single-sourced from the domain "
                   "resolver; a caller-computed set is refused",
        )
    return build_snapshot(
        request, facet.effective_set(), approvals=approvals,
        runtime_generation=runtime_generation,
        profile_revision=profile_revision,
        adapter_generation=adapter_generation,
    )


# --------------------------------------------------------------------------
# application outcome vocabulary (G16 negatives, overlay cleanup, §Profile v2)
# --------------------------------------------------------------------------


def apply_outcome_projection(*, journal_entry: Mapping[str, Any] | None,
                             receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project one application attempt for the editor, honestly.

    Consumes the public dicts of their ``JournalEntry`` / ``AppliedReceipt``
    shapes.  Rules (each mutation-proven): success is only ever reported for
    a ``confirmed`` journal state WITH a non-legacy receipt; a ``rejected``
    attempt keeps the previous coverage (nothing is cleared); an ``unknown``
    attempt stays queryable and is never a success; a ``legacy-unverified``
    record can never be upgraded (PV-04).
    """
    state = journal_entry.get("state") if journal_entry is not None else None
    if state is None:
        return {"state": "none", "success": False, "queryable": False,
                "reason": "no application attempt is recorded"}
    receipt_kind = receipt.get("evidence_kind") if receipt is not None else None
    if state == "unknown":
        return {"state": state, "success": False, "queryable": True,
                "reason": "the outcome cannot be proven; reconcile before "
                          "reporting anything as applied"}
    if state == "rejected":
        return {"state": state, "success": False, "queryable": True,
                "reason": "the previous configuration stays in force; the "
                          "stored choice and pin are untouched"}
    if state == JOURNAL_CONFIRMED:
        if receipt is None or receipt.get("config_digest") in (None, ""):
            return {"state": state, "success": False, "queryable": True,
                    "reason": "a confirmed journal state without a receipt "
                              "proves nothing"}
        if receipt_kind == EVIDENCE_LEGACY_UNVERIFIED:
            return {"state": state, "success": False, "queryable": True,
                    "reason": "legacy-unverified evidence can never be "
                              "upgraded to confirmed (PV-04)"}
        return {"state": state, "success": True, "queryable": True,
                "reason": f"applied with {receipt_kind} evidence"}
    return {"state": state, "success": False, "queryable": True,
            "reason": "the attempt has not been applied"}


def overlay_cleanup_evidence(*, journal_entry: Mapping[str, Any] | None,
                             receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Was a session overlay's cleanup *evidenced*, Profile-v2 style?

    A successful overlay cleanup is exactly one port-confirmed application:
    their ``JournalEntry`` in state ``confirmed`` plus their
    ``AppliedReceipt`` carrying a config digest and non-legacy evidence.
    Anything else — planned, rejected, unknown, receipt-less, legacy — says
    the overlays survived and stays honest about it.
    """
    projection = apply_outcome_projection(journal_entry=journal_entry,
                                          receipt=receipt)
    cleaned = bool(projection["success"])
    return {"cleaned": cleaned, **projection}


# --------------------------------------------------------------------------
# editor projection (facet/editor half of T10; UI mounting is T09's lane)
# --------------------------------------------------------------------------


def editor_projection(facet: NativeSubagentsFacet, *,
                      stored_items: Mapping[str, Any] | None = None,
                      harness_id: str | None = None) -> dict[str, Any]:
    """The editor's read model: candidates, stored choices, honest state.

    * never contains definition bodies or provenance (§C2) — only references,
      decisions and pins;
    * capability diagnostics render with ``readOnlyReason`` from the domain's
      evidence, so an editor cannot show a save as a green "in effect";
    * if the resolver refuses (conflict / stale pin), the projection carries
      the typed refusal as ``effectiveSetUnavailable`` instead of pretending
      the effective set is empty.
    """
    stored = dict(stored_items or {})
    candidates = sorted(facet.candidate_map().values(),
                        key=lambda c: c.definition_id)
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        item_id = choice_item_id(candidate.definition_id)
        value = stored.get(item_id)
        choice: dict[str, Any] | None = None
        refusal: dict[str, Any] | None = None
        if value is not None:
            try:
                decision, revision = decode_choice(value)
                choice = {"decision": decision.value, "revision": revision}
            except errors.DomainError as exc:
                refusal = {"code": exc.code,
                           "detail": exc.detail or "fragment cannot compile"}
        items.append({
            "item_id": item_id,
            "definition_ref": candidate.definition_id,
            "title": candidate.display_name,
            "slug": candidate.slug,
            "latest_revision": candidate.latest_revision,
            "managed": candidate.managed,
            "choice": choice,
            "uncompilable_fragment": refusal,
        })
    applicability = facet.applicability(
        {"harness_id": harness_id} if harness_id else {})
    effective: dict[str, Any]
    try:
        resolved = facet.effective_set()
        effective = {
            "resolved": [
                {"definition_id": row.definition_id, "revision": row.revision,
                 "selected_by": row.selected_by.value}
                for row in resolved.resolved
            ],
            "excluded": [
                {"definition_id": row.definition_id, "reason": row.reason_code}
                for row in resolved.excluded
            ],
        }
    except errors.DomainError as exc:
        effective = {"unavailable": True, "code": exc.code,
                     "detail": exc.detail or "the resolver refused"}
    return {
        "facet_id": facet.facet_id,
        "harness_id": harness_id,
        "applicability": applicability.value,
        "items": items,
        "capabilityDiagnostics": [
            {**cell, "readOnlyReason":
                "derived by the definition library from capability evidence; "
                "read-only here — storing a choice never proves a load"}
            for cell in facet.capability_diagnostics()
        ],
        "effectiveSet": effective,
    }
