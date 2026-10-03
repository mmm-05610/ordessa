"""`SkillsFacetProvider` — the `assets.skills` facet as a profile-api v2 provider.

Registration path (the only one this domain uses): the composition hands
the plugin a `ProfilePluginServices`, `register_skills_facet()` builds this
provider and calls `services.register_v2_facet(provider, owner_plugin_id)`
— the owner is injected by the host-facing API call, mirroring the proof in
`plugins/profile/tests/test_v2_extension.py`. The provider never touches
Profile storage or the registry directly.

Tri-state mapping onto the PF04 value vocabulary (docs/design/skills-v2/
contracts.md §Profile: 每 Skill 保存 inherit | enable(revision) | disable):

* ``inherit``  — the ABSENENCE of a stored binding for the item. Their
  `value_state(...)` of an unset item is ``'unset'`` (`UNSET` is never a
  stored value; profile's resolution simply omits the row), so inherit is
  expressed exactly the way Profile's data model expresses it.
* ``enable(revision)`` — an explicit stored value
  ``{"decision": "enable", "revision": <int >= 1>}``: the FIXED revision
  the assignment model requires (data-model: 启用必须钉修订). The provider's
  `validate` ruling is the authority on the shape (the controlled schema
  subset has no property keywords; the v2 provider ruling covers it, which
  is the mechanism Profile's `profiles._validate_v2_item` documents).
* ``disable`` — an explicit stored value ``{"decision": "disable"}``. The
  business "off" is carried inside the value because the facet's stored
  encoding is JSON (`json_dumps` at write time); their `ValueDisabled`
  sentinel is the in-process state, never a wire/stored object. Read back,
  this maps to `ValueDisabled`-equivalent semantics: an explicit off,
  distinct from unset — `entry_from_value` is the single decoding site.

One item per known skill asset: `descriptor()` lists the live asset ids
(supplied as a zero-argument listing callable — the provider never opens
the database itself), so Profile's unknown-item storage refusal is the
domain's unknown-asset refusal, and an asset removed later keeps its
stored value quarantined honestly (their G13 semantics) rather than
silently deleted here.

Applicability is three-valued and never promoted from absence
(contracts.md): the three controlled brands of the frozen research matrix
(research/brand-matrix.md — browse via files exists for all three) answer
``supported``; any other harness answers ``unknown``, never ``unsupported``
(no evidence is not disproof either).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ..api.identity import ASSET_ID
from ..harness_adapters.capabilities import registered_brands

#: Facet identity — the id docs/design/skills-v2/contracts.md §Profile
#: freezes for this domain.
FACET_ID = "assets.skills"
FACET_API_MAJOR = 2
FACET_SCHEMA_VERSION = "1.0.0"

DECISION_ENABLE = "enable"
DECISION_DISABLE = "disable"

#: The stored encoding of the two explicit states (inherit = no row).
DISABLE_VALUE: Mapping[str, Any] = {"decision": DECISION_DISABLE}


def decision_value(revision: int) -> dict[str, Any]:
    """The stored value for ``enable(revision)`` — the pin is mandatory."""
    if isinstance(revision, bool) or not isinstance(revision, int) \
            or revision < 1:
        raise ValueError("an enable binding must pin a positive revision")
    return {"decision": DECISION_ENABLE, "revision": revision}


def entry_from_value(value: Any) -> tuple[str, int | None] | None:
    """Decode one stored facet value to ``(decision, revision)``.

    Returns ``None`` for anything the facet does not recognise — a stale
    value under a changed schema never resolves as a fake decision; the
    caller surfaces the item as unknown and refuses it visibly (the same
    G10 discipline the resolver applies to foreign content).
    """
    if not isinstance(value, Mapping):
        return None
    keys = set(value)
    decision = value.get("decision")
    if decision == DECISION_DISABLE and keys == {"decision"}:
        return DECISION_DISABLE, None
    if decision == DECISION_ENABLE and keys == {"decision", "revision"}:
        revision = value["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) \
                or revision < 1:
            return None
        return DECISION_ENABLE, revision
    return None


class SkillsFacetProvider:
    """The v2 provider object the profile registry holds under us."""

    def __init__(self, *, asset_ids: Callable[[], Sequence[str]]) -> None:
        self._asset_ids = asset_ids

    # -- FacetProviderV2 ------------------------------------------------------

    def descriptor(self):
        from ordessa_profile.contracts import FacetDescriptor, ItemDescriptor

        items = tuple(
            ItemDescriptor(
                item_id=asset_id,
                value_schema={
                    "type": "object",
                    "title": f"assets.skills binding for {asset_id}",
                    "description": (
                        "inherit = no stored binding; enable carries "
                        "{\"decision\": \"enable\", \"revision\": N} with a "
                        "mandatory fixed revision; disable carries "
                        "{\"decision\": \"disable\"}"),
                },
                optional=True,
                override_supported=True,
                sensitivity="non-secret",
                # The binding SELECTS content for the session; it is not a
                # secret and not a permission grant (G03).
                effect="capability-selection",
                title=f"Skill {asset_id}",
            )
            for asset_id in sorted(set(self._asset_ids()))
            if ASSET_ID.fullmatch(asset_id) is not None
        )
        return FacetDescriptor(
            facet_id=FACET_ID,
            api_major=FACET_API_MAJOR,
            schema_version=FACET_SCHEMA_VERSION,
            label="Skills (v2)",
            description=("Per-Skill inherit | enable(revision) | disable "
                         "bindings for the assets.skills facet"),
            category="capabilities",
            order=60,
            item_descriptors=items,
        )

    def applicability(self, capability_facts: Mapping[str, Any]):
        from ordessa_profile.contracts import Applicability

        harness_id = capability_facts.get("harness_id")
        if harness_id is None:
            # describe without a target: the FACT to decide on is absent —
            # unknown, never promoted (contracts.md 三值适用性).
            return Applicability.UNKNOWN
        if harness_id in registered_brands():
            # The frozen matrix (research/brand-matrix.md) evidences the
            # file-based browse mechanism for all three controlled brands;
            # the FACET stores selections, which does not depend on the
            # invocation axis that stays unknown.
            return Applicability.SUPPORTED
        return Applicability.UNKNOWN

    def validate(self, items: Mapping[str, Any],
                 reference_facts: Mapping[str, Any]):
        from ordessa_profile.contracts import Violation

        violations = []
        known = set(self._asset_ids())
        for item_id in sorted(items):
            value = items[item_id]
            where = f"{FACET_ID}/{item_id}"
            if item_id not in known:
                violations.append(Violation(
                    facet_id=FACET_ID, item_id=item_id,
                    code="ASSET_NOT_FOUND",
                    message=f"{where}: no skill asset with that id in this "
                            "content library (the facet never stores a "
                            "binding for content it cannot name)"))
                continue
            if entry_from_value(value) is None:
                violations.append(Violation(
                    facet_id=FACET_ID, item_id=item_id,
                    code="FACET_VALUE_INVALID",
                    message=f"{where}: value must be "
                            '{"decision": "enable", "revision": >=1} or '
                            '{"decision": "disable"} — inherit is expressed '
                            "by removing the binding, never by a third "
                            "spelling"))
        del reference_facts  # the provider's own listing is the reference
        return tuple(violations)

    def migrate(self, old_schema_version: str, stored_items: Mapping[str, Any]):
        from ordessa_profile.contracts import MigratedItems, MigrationUnsupported

        if old_schema_version == FACET_SCHEMA_VERSION:
            return MigratedItems(
                items=tuple(sorted(stored_items.items())),
                from_schema_version=old_schema_version,
                to_schema_version=FACET_SCHEMA_VERSION,
            )
        # No other schema version of this facet has ever been published;
        # ruling stored rows under a guessed migration would be the fake
        # green this slice's evidence rules forbid.
        return MigrationUnsupported(
            reason=("assets.skills has exactly one published schema version "
                    f"({FACET_SCHEMA_VERSION}); rows stamped "
                    f"{old_schema_version!r} cannot be re-ruled here"),
            from_schema_version=str(old_schema_version),
            to_schema_version=FACET_SCHEMA_VERSION,
        )

    def compile(self, resolved_items: Mapping[str, Any],
                target_facts: Mapping[str, Any]):
        """Zero native config steps — declared out loud, never silently.

        A skill binding is not a Harness configuration key: the projection
        of selected revisions into a brand's authorized instance root runs
        through the Skills harness adapters and the §G2 Harness seam
        (api-requests.md), and the resolver's evidence ladder caps at
        `selected` (api/evidence.py). Emitting `ConfigIntent` rows here
        would make Profile's journal claim an application this domain can
        only perform elsewhere — and with `HarnessConfigPort` absent the
        application attempt stays Profile's own typed block
        (`APPLICATION_PORT_ABSENT`), which this facet consumes rather than
        re-implements.
        """
        from ordessa_profile.contracts import CompileResult

        del resolved_items, target_facts
        return CompileResult(intents=(), violations=())


def register_skills_facet(services: Any, *, owner_plugin_id: str,
                          asset_ids: Callable[[], Sequence[str]]):
    """Register the facet through the published API and return the provider.

    `services` is the host-composed `ProfilePluginServices`; the owner is
    the plugin id the host scope carries (`register_v2_facet` is documented
    "owner injected by the host scope" — a provider never names its own
    owner, and a duplicate facet id under another owner refuses with
    `FACET_ID_CONFLICT`).
    """
    provider = SkillsFacetProvider(asset_ids=asset_ids)
    services.register_v2_facet(provider, owner_plugin_id)
    return provider


__all__ = [
    "DISABLE_VALUE", "FACET_API_MAJOR", "FACET_ID", "FACET_SCHEMA_VERSION",
    "SkillsFacetProvider", "decision_value", "entry_from_value",
    "register_skills_facet",
]
