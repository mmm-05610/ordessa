"""The Q1 producer of the ``agent-box.skill@1`` delivery set (T14/G19).

Closes the producer gap: the harness *consumption* leg exists
(`plugins/harness/src/ordessa_harness/adapters/generic_cli.py:20-38` reads
resolved inputs of contract ``agent-box.skill@1`` and mounts each skill tree
read-only at the registry-declared ``skill_target``), and the contract type
itself is the published one
(`plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/agent_skill_v1.py`)
— but nothing in the tree yielded it, so skills could be stored, bound,
resolved and refused, yet never delivered. Producing the reference is
Skills' own domain responsibility (docs/design/skills-v2/contracts.md
§Harness 配置贡献; harness-adapters.md 映射步骤 1-3): Skills owns content +
assignment facts and hands the Harness a VERIFIED reference; the Harness
owns the instance.

Shape bound here (published symbols only, no harness internals):

* ``AgentSkillV1`` — the serializable public contract (``contract_id ==
  "agent-box.skill@1"``); per its own docstring the resolved-source
  capability is EPHEMERAL and rides beside it, never inside it.  Each
  delivery item therefore mirrors exactly what ``generic_cli.py:26-35``
  reads: ``item.contract_id``, ``item.value.contract`` (skill_id /
  revision / digest) and ``item.value.source.projection_source()``.
* ``declare_source`` — the shared projector helper of the published
  runtime-composition protocol
  (``pacthold_runtime_compat/runtime_composition/protocol.py:307-319``);
  the guest target TEMPLATE stays the caller's (Harness-owned) decision,
  this module only formats ``{skill_id}`` into it.

Every contract field is a real fact: the host directory is the store's
revision path, ``revision``/tree-digest come from the frozen snapshot pins
and are RE-VERIFIED against the store and the approval record here, name
and description are re-read from the validated frontmatter
(``SkillRevisionStore.read_metadata``), ``size`` is summed from the stored
bytes, the ``SKILL.md`` manifest is checked on disk, and the provenance
tuple is the frozen generation face (runtimeGeneration / projectId /
profileRevision / assignmentRevision / snapshotDigest).

Fail-closed preflight (BEFORE any delivery object is handed out; a refusal
raises and returns nothing, so a partial set is structurally impossible):

1. revision not installed+approved (the approval gate's own typed refusal,
   re-applied here — codes ``SKILL_DELIVERY_UNAPPROVED`` /
   ``SKILL_DELIVERY_NOT_INSTALLED``);
2. digest drift against the pin or the approval fact
   (``SKILL_DELIVERY_DIGEST_MISMATCH``);
3. nativeName collision inside the managed set or with an observed
   native-discovery item (``conflict.py`` — ``SKILL_NAME_COLLISION``);
4. target brand/version unsupported per ``capabilities.py`` — unknown is
   never read as supported (``SKILL_DELIVERY_BRAND_UNSUPPORTED``);
5. input count outside the registry's declared cardinality — the limit is
   READ from the harness definition the caller injects (duck-typed
   ``inputs``/``profile.skill_target``, the published ``InputSpec`` shape,
   ``registry/schema.py:140`` enforces 0..32 there), never hardcoded here
   (``SKILL_DELIVERY_LIMIT_EXCEEDED`` / ``SKILL_DELIVERY_LIMIT_MISSING`` /
   ``SKILL_DELIVERY_UNDECLARED``);
6. any revision path escaping the store root, symlinked revision trees
   included (``SKILL_DELIVERY_PATH_ESCAPE``).

Evidence honesty (contracts.md 证据阶梯 / verification.md G16): producing
this set proves ``selected`` facts re-verified at delivery time; a
digest-matching projection receipt (see tests) grades at most
``projected`` — nothing here or in the fake coordinator can observe a load
or an invocation, so no level above ``projected`` is ever claimed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from pacthold_runtime_compat.resource_contracts.agent_skill_v1 import AgentSkillV1
from pacthold_runtime_compat.runtime_composition import declare_source

from ..api.errors import AssetDomainError
from ..assignments.snapshot import SkillSnapshot, assert_apply_eligible
from ..library.store import SkillRevisionStore
from .capabilities import SUPPORTED, pin_for, statement_for
from .conflict import (
    evaluate_against_native_discovery, evaluate_managed_set, name_rules_for,
)
from .intent import ManagedContentRef

#: The published contract identity — BOUND to the contract type, never
#: redeclared (AGENTS.md: the contract already owns this spelling).
CONTRACT_ID = AgentSkillV1.contract_id  # "agent-box.skill@1"

#: The manifest the published contract fixes for the `agent-skills` format.
MANIFEST_NAME = "SKILL.md"


class SkillDeliveryError(AssetDomainError):
    """The delivery set was refused before anything was handed to a
    Harness (codes registered here once: ``SKILL_DELIVERY_NOT_INSTALLED``,
    ``SKILL_DELIVERY_UNAPPROVED``, ``SKILL_DELIVERY_DIGEST_MISMATCH``,
    ``SKILL_DELIVERY_MANIFEST_MISSING``, ``SKILL_DELIVERY_FRONTMATTER_INVALID``,
    ``SKILL_DELIVERY_BRAND_UNSUPPORTED``, ``SKILL_DELIVERY_LIMIT_MISSING``,
    ``SKILL_DELIVERY_LIMIT_EXCEEDED``, ``SKILL_DELIVERY_UNDECLARED``,
    ``SKILL_DELIVERY_PATH_ESCAPE``)."""


# --------------------------------------------------------------------------
# ephemeral delivery value objects (the shape generic_cli consumes)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillProjectionSource:
    """The resolved-source capability the public contract deliberately
    does NOT carry (its docstring: a Ref never contains a host path).
    Ephemeral, execution-local: ``projection_source()`` re-verifies the
    directory at call time."""

    host_directory: Path
    expected_digest: str

    def projection_source(self) -> Path:
        if not self.host_directory.is_dir():
            raise SkillDeliveryError(
                "SKILL_DELIVERY_NOT_INSTALLED",
                "the revision directory disappeared after the delivery was "
                "built; the source capability is dead",
                detail=str(self.host_directory))
        return self.host_directory


@dataclass(frozen=True)
class SkillDeliveryValue:
    """``item.value`` on the consumer side: contract + ephemeral source."""

    contract: AgentSkillV1
    source: SkillProjectionSource
    size_bytes: int


@dataclass(frozen=True)
class SkillDeliveryInput:
    """One ``request.resolved_inputs`` entry shaped exactly as
    generic_cli.py:20-35 reads it (``.contract_id`` + ``.value`` with
    ``.contract``/``.source.projection_source()``)."""

    value: SkillDeliveryValue
    contract_id: str = CONTRACT_ID


@dataclass(frozen=True)
class SkillDeliverySet:
    harness_id: str
    snapshot_digest: str
    provenance: Mapping[str, str]
    skill_input_minimum: int
    skill_input_maximum: int
    items: tuple[SkillDeliveryInput, ...] = ()

    def resolved_inputs(self) -> tuple[SkillDeliveryInput, ...]:
        return self.items

    def runtime_sources(self, *, skill_target: str) -> tuple[Any, ...]:
        """Declare every delivered tree read-only at the caller-provided
        guest template (``{skill_id}`` placeholder), mirroring the
        consumer-side spelling in generic_cli.py:35 (kind ``skill-tree``,
        provenance ``skill:<id>:<revision>``, access ``ro``, scope
        ``execution``). The template itself is the Harness's layout
        decision; this never invents a guest path for a brand that has
        not declared one."""
        ordered = sorted(
            self.items,
            key=lambda item: (item.value.contract.skill_id,
                              item.value.contract.revision,
                              item.value.contract.digest))
        return tuple(
            declare_source(
                "skill-tree",
                str(item.value.source.projection_source()),
                skill_target.format(skill_id=item.value.contract.skill_id),
                access="ro",
                provenance=(f"skill:{item.value.contract.skill_id}"
                            f":{item.value.contract.revision}"),
                authorized_scope="execution")
            for item in ordered)

    def view(self) -> dict[str, Any]:
        """The serializable face (public_dict of each contract + the
        provenance the receipt is graded against). Contains no host path:
        the source capability is ephemeral by contract design."""
        return {
            "contractId": CONTRACT_ID,
            "harnessId": self.harness_id,
            "snapshotDigest": self.snapshot_digest,
            "provenance": dict(self.provenance),
            "skillInputCardinality": [self.skill_input_minimum,
                                      self.skill_input_maximum],
            "skills": [item.value.contract.public_dict()
                       for item in self.items],
        }


# --------------------------------------------------------------------------
# preflight helpers
# --------------------------------------------------------------------------

def skill_input_limits(harness_definition: Any) -> tuple[int, int]:
    """Read the ``agent-box.skill@1`` input cardinality OFF the harness
    definition the caller injects (duck-typed published ``InputSpec``
    surface: ``definition.inputs`` items with ``contract_id``/``minimum``/
    ``maximum`` — see registry/schema.py:140 for the registry's own 0..32
    guard). Never hardcoded, never guessed: an absent declaration or an
    unbounded maximum is a typed refusal."""
    spec = None
    for item in getattr(harness_definition, "inputs", ()):
        if getattr(item, "contract_id", None) == CONTRACT_ID:
            spec = item
            break
    if spec is None:
        raise SkillDeliveryError(
            "SKILL_DELIVERY_UNDECLARED",
            "the target harness declares no agent-box.skill@1 input; "
            "delivery is refused instead of guessing a cardinality",
            detail=str(getattr(harness_definition, "harness_type", "?")))
    minimum = getattr(spec, "minimum", None)
    maximum = getattr(spec, "maximum", None)
    if (not isinstance(minimum, int) or isinstance(minimum, bool)
            or minimum < 0 or not isinstance(maximum, int)
            or isinstance(maximum, bool) or maximum < minimum):
        raise SkillDeliveryError(
            "SKILL_DELIVERY_LIMIT_MISSING",
            "the declared skill input cardinality is not a bounded int "
            "range; unknown limits are never read as unlimited")
    return minimum, maximum


def _assert_brand_supported(harness_id: str,
                            observed_native_version: str | None) -> None:
    """capabilities.py is the single brand table: an unregistered brand is
    ``unknown`` and unknown is NOT supported (G10). A brand whose native
    pin is not evidence-supported (claude-code today) may only be delivered
    to when the caller reports the exact pinned version; any other reported
    version refuses (harness-adapters.md 运行版本不符时拒绝能力)."""
    if not harness_id:
        raise SkillDeliveryError(
            "SKILL_DELIVERY_BRAND_UNSUPPORTED",
            "delivery needs an exact target harness id; none is supported "
            "without one")
    statement = statement_for(harness_id)
    if getattr(statement, "synthesized", False):
        raise SkillDeliveryError(
            "SKILL_DELIVERY_BRAND_UNSUPPORTED",
            f"brand {harness_id!r} is not registered in the capability "
            "table; unknown is never treated as supported",
            detail=harness_id)
    pin = pin_for(harness_id)
    if observed_native_version is not None:
        if pin is None or observed_native_version != pin.native_version:
            raise SkillDeliveryError(
                "SKILL_DELIVERY_BRAND_UNSUPPORTED",
                f"observed native version {observed_native_version!r} does "
                f"not match the pinned {pin.native_version if pin else '?'}",
                detail=harness_id)
        return
    if statement.value("native_version") != SUPPORTED:
        raise SkillDeliveryError(
            "SKILL_DELIVERY_BRAND_UNSUPPORTED",
            f"brand {harness_id!r} carries no evidence-supported version "
            "pin; pass the observed_native_version the runtime reports to "
            "deliver against an exact pin",
            detail=harness_id)


def _provenance(snapshot: SkillSnapshot) -> dict[str, str]:
    """The design-required binding tuple, all values from the frozen
    snapshot facts (data-model.md SkillSnapshot). Mappings are reduced to
    their canonical digest so the tuple is stable, bounded and serializable."""
    from ..assignments.snapshot import canonical_digest
    return {
        "runtimeGeneration": str(snapshot.runtime_generation),
        "projectId": snapshot.project_id or "",
        "profileRevision": canonical_digest(
            dict(snapshot.profile_revision) if snapshot.profile_revision else {}),
        "assignmentRevision": canonical_digest(
            dict(sorted(snapshot.assignment_revisions.items()))),
        "snapshotDigest": snapshot.snapshot_digest,
    }


def _tree_size_bytes(directory: Path) -> int:
    return sum(item.stat().st_size for item in directory.rglob("*")
               if item.is_file())


# --------------------------------------------------------------------------
# the producer
# --------------------------------------------------------------------------

def build_skill_delivery(
    *,
    snapshot: SkillSnapshot,
    store: SkillRevisionStore,
    approvals: Any,
    harness_id: str,
    harness_definition: Any | None = None,
    skill_input_maximum: int | None = None,
    observed_native_version: str | None = None,
    observed_native_names: Sequence[str] = (),
    resolution_service: Any | None = None,
    target: Any | None = None,
) -> SkillDeliverySet:
    """Turn one frozen snapshot into the ``agent-box.skill@1`` delivery set.

    Preflights EVERY rule first; any violation raises and NO delivery
    object ever escapes (refusal produces zero partial objects). When both
    ``resolution_service`` and ``target`` are given the snapshot's freshness
    is re-checked first (G18/FR08 — a moved layer refuses with
    ``SNAPSHOT_STALE`` before anything else runs).
    """
    if resolution_service is not None and target is not None:
        assert_apply_eligible(snapshot, resolution_service, target)

    # 4. brand/version (unknown != supported)
    _assert_brand_supported(harness_id, observed_native_version)

    # 5. registry cardinality, read from the published definition
    if harness_definition is not None:
        minimum, maximum = skill_input_limits(harness_definition)
        skill_target = getattr(
            getattr(harness_definition, "profile", None), "skill_target", None)
        if skill_target and "{skill_id}" not in skill_target:
            raise SkillDeliveryError(
                "SKILL_DELIVERY_UNDECLARED",
                "the declared skill_target cannot address one tree per "
                "skill; refusing instead of stacking deliveries on one path",
                detail=skill_target)
    elif skill_input_maximum is not None:
        minimum, maximum = 0, int(skill_input_maximum)
    else:
        raise SkillDeliveryError(
            "SKILL_DELIVERY_LIMIT_MISSING",
            "no harness definition and no explicit maximum: the delivery "
            "refuses rather than hardcoding the registry's 0..32 limit")
    pins = sorted(snapshot.resolved_skills, key=lambda item: item["assetId"])
    if len(pins) > maximum:
        raise SkillDeliveryError(
            "SKILL_DELIVERY_LIMIT_EXCEEDED",
            f"{len(pins)} resolved skills exceed the registry-declared "
            f"maximum of {maximum}; refusing before any partial delivery",
            detail=harness_id)

    root = Path(store.root).resolve()
    refs: list[ManagedContentRef] = []
    built: list[tuple[AgentSkillV1, SkillProjectionSource, int]] = []
    for pin in pins:
        asset_id = str(pin["assetId"])
        revision = int(pin["revision"])
        tree_digest = str(pin["treeDigest"])

        # 1. installed + approved (the approval gate's own typed refusal)
        directory = store.revision_dir(asset_id, revision)
        if directory.is_symlink():
            # 6. a symlinked revision tree is the classic store-root escape
            raise SkillDeliveryError(
                "SKILL_DELIVERY_PATH_ESCAPE",
                f"revision {revision} of {asset_id} is a symlinked tree; "
                "delivery refuses before any digest is trusted",
                detail=str(directory))
        if not directory.is_dir():
            raise SkillDeliveryError(
                "SKILL_DELIVERY_NOT_INSTALLED",
                f"revision {revision} of {asset_id} is not an installed "
                "directory", detail=str(directory))

        # 2. digest re-verification against the frozen pin (BEFORE the
        # approval gate, so tree drift and approval loss stay distinct)
        actual = store.revision_digest(asset_id=asset_id, revision=revision)
        if actual != tree_digest:
            raise SkillDeliveryError(
                "SKILL_DELIVERY_DIGEST_MISMATCH",
                f"the installed tree of {asset_id}@{revision} no longer "
                f"matches the frozen pin ({actual} != {tree_digest})",
                detail=asset_id)

        # 1. installed + approved (the approval gate's own typed refusal)
        try:
            approvals.assert_usable_for_assignment(asset_id, revision)
        except AssetDomainError as exc:
            # the approval store's own digest-drift refusal stays a
            # DIGEST_MISMATCH (drift against the approval fact); a missing
            # approval or a vanished revision keeps its reason code.
            code = ("SKILL_DELIVERY_DIGEST_MISMATCH"
                    if "DIGEST" in exc.code else "SKILL_DELIVERY_UNAPPROVED")
            raise SkillDeliveryError(
                code,
                f"revision {revision} of {asset_id} is not installed+approved: "
                f"{exc.code}: {exc.message}", detail=asset_id) from exc

        # 6. path containment: the resolved tree must live under the store
        # root (the islink check above refuses a symlinked escape hatch).
        resolved = directory.resolve()
        if not resolved.is_relative_to(root):
            raise SkillDeliveryError(
                "SKILL_DELIVERY_PATH_ESCAPE",
                f"the revision path of {asset_id} escapes the store root",
                detail=str(resolved))

        # manifest + validated frontmatter facts (never trust the row copy)
        if not (resolved / MANIFEST_NAME).is_file():
            raise SkillDeliveryError(
                "SKILL_DELIVERY_MANIFEST_MISSING",
                f"{asset_id}@{revision} has no {MANIFEST_NAME} manifest",
                detail=str(resolved))
        facts = store.read_metadata(asset_id=asset_id, revision=revision)
        name = str(facts.get("name") or "")
        description = str(facts.get("description") or "")
        if (not name or len(name) > 128 or not description
                or len(description) > 512):
            raise SkillDeliveryError(
                "SKILL_DELIVERY_FRONTMATTER_INVALID",
                f"{asset_id}@{revision} frontmatter cannot fill the "
                "published contract bounds", detail=asset_id)

        refs.append(ManagedContentRef(
            asset_id=asset_id, revision=revision, tree_digest=tree_digest,
            native_name=name, size_bytes=_tree_size_bytes(resolved)))

    # 3. collision rules over the COMPLETE managed set (order- and
    # case-insensitive to the brand's unknown comparison semantics)
    rules = name_rules_for(harness_id)
    evaluate_managed_set(refs, rules)
    evaluate_against_native_discovery(
        refs, tuple(observed_native_names), rules,
        statement_for(harness_id).value("native_namespacing"))

    provenance_base = _provenance(snapshot)
    for ref in refs:
        directory = store.revision_dir(ref.asset_id, ref.revision)
        description = str(store.read_metadata(
            asset_id=ref.asset_id, revision=ref.revision)["description"])
        provenance = dict(provenance_base)
        provenance.update({
            "skillId": ref.asset_id,
            "revision": str(ref.revision),
            "treeDigest": ref.tree_digest,
        })
        # Every constructor argument below is a re-verified fact; the
        # published contract's own __post_init__ bounds (slug-ish id,
        # sha256: digest, SKILL.md manifest, agent-skills format) are
        # NEVER redeclared here — AgentSkillV1 validates them.
        contract = AgentSkillV1(
            skill_id=ref.asset_id,
            name=ref.native_name,
            description=description,
            revision=ref.revision,
            digest=ref.tree_digest,
            provenance=provenance,
        )
        built.append((contract,
                      SkillProjectionSource(directory, ref.tree_digest),
                      ref.size_bytes or 0))

    items = tuple(
        SkillDeliveryInput(SkillDeliveryValue(contract=c, source=s, size_bytes=n))
        for c, s, n in built)
    return SkillDeliverySet(
        harness_id=harness_id,
        snapshot_digest=snapshot.snapshot_digest,
        provenance=provenance_base,
        skill_input_minimum=minimum,
        skill_input_maximum=maximum,
        items=items)


__all__ = [
    "CONTRACT_ID", "MANIFEST_NAME", "SkillDeliveryError", "SkillDeliveryInput",
    "SkillDeliverySet", "SkillDeliveryValue", "SkillProjectionSource",
    "build_skill_delivery", "skill_input_limits",
]
