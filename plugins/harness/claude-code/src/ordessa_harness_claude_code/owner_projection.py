"""Production trusted projection for the Claude family over the SAME records.

The provider IS the owner of the deployment-assembled UnitRecords (frozen
owner-pipeline contract), so every durable read here is the records owner's
own ``owner_read_unit`` / ``owner_read_session`` / ``owner_read_unit_confirmation``
projection: it consumes no invocation, issues no ticket and creates no effect
permission. The journal stays the only durable truth; a copied public
reference never supplies read permission — the whole-reference identity that
leaves the owner is re-verified against the original on every read.

``current_authority`` re-validation hooks (start/configuration) are explicit
deployment callables; absent ports mean the corresponding revalidation is
typed-refused and the dependent method is not advertised. Original start
correlations observed live are registered process-locally; a cold restart
cannot resolve an unobserved correlation without an explicit owner lookup
composition — the same registered limitation as the codex family projection.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping

UNIT_REF_FIELDS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


class ClaudeProjectionRefused(RuntimeError):
    code = "CLAUDE_PROJECTION_REFUSED"


def same_reference(left, right) -> bool:
    try:
        return safe_json(left) == safe_json(right)
    except (TypeError, ValueError):
        return False


def complete_unit_ref(value) -> bool:
    return (isinstance(value, Mapping) and set(value) == UNIT_REF_FIELDS
            and isinstance(value.get("unitId"), str) and bool(value["unitId"])
            and isinstance(value["ownerProviderRef"], Mapping))


def _plain(value):
    return sealed_mapping(value)


class ClaudeOwnerUnitProjection:
    """Real production projection; only records' owner reads expose journal facts.

    The coordinator consumes ``read_unit(reference, context)`` — the context is
    required to remain an opaque invocation object (never verified facts), but
    this owner projection consumes no invocation for its reads: the durable
    journal read is the owner's own, and every actual effect separately
    consumes its original claim through the records begin/record contracts.
    """

    def __init__(self, records, *, verifier,
                 preparation_authority: Callable | None = None,
                 start_authority: Callable | None = None,
                 configuration_authority: Callable | None = None,
                 publication_owner: Callable | None = None):
        self.records, self.verifier = records, verifier
        self._preparation_authority = preparation_authority
        self._start_authority = start_authority
        self._configuration_authority = configuration_authority
        self._publication_owner = publication_owner
        self._starts: dict[str, str] = {}  # observed start correlations -> unit ids, live only
        owner_methods = ("owner_read_unit", "owner_read_session", "owner_read_unit_confirmation")
        if (verifier is None or getattr(records, "verifier", None) is not verifier
                or any(not callable(getattr(records, name, None)) for name in owner_methods)):
            raise ClaudeProjectionRefused("projection requires the original records owner reads")

    # -- durable reads (owner-trusted, invocation-free) ----------------------
    def _owner_unit(self, reference):
        if not complete_unit_ref(reference):
            raise ClaudeProjectionRefused("complete owner-bound unit reference required")
        if isinstance(reference["unitId"], str) and len(reference["unitId"]) > 256:
            raise ClaudeProjectionRefused("complete owner-bound unit reference required")
        unit = self.records.owner_read_unit(reference["unitId"])
        if not same_reference(unit.public_ref, reference):
            raise ClaudeProjectionRefused("unit reference differs from original owner source")
        return unit

    def read_unit(self, reference, context=None):
        """Whole-reference bound owner read for one planned or invoked unit."""
        if context is not None and (isinstance(context, Mapping) or not hasattr(context, "facts")):
            raise ClaudeProjectionRefused("verified fact mappings are not opaque invocation contexts")
        return self._owner_unit(reference)

    def read_session(self, unit_ref):
        unit = self._owner_unit(unit_ref)
        return self.records.owner_read_session(unit.unit_ref)

    def read_unit_confirmation(self, unit_ref):
        unit = self._owner_unit(unit_ref)
        return self.records.owner_read_unit_confirmation(unit.unit_ref)

    def resolve_original_start(self, correlation, context):
        """Resolve the ORIGINAL observed start; never a latest-session lookup."""
        if (not isinstance(correlation, str) or not correlation or len(correlation) > 2048
                or (context is not None and isinstance(context, Mapping))):
            raise ClaudeProjectionRefused("original creation correlation required")
        snapshot = self._starts.get(correlation)
        if snapshot is None:
            raise ClaudeProjectionRefused(
                "original creation correlation was not observed by this projection owner")
        return self._owner_unit(snapshot)

    # -- authority revalidation (deployment ports) ---------------------------
    def register_original_start(self, unit, correlation) -> None:
        if (not isinstance(correlation, str) or not correlation
                or not complete_unit_ref(getattr(unit, "public_ref", None))):
            raise ClaudeProjectionRefused("original start registration requires observed facts")
        snapshot = {"environmentNamespace": unit.public_ref["environmentNamespace"],
                    "unitId": unit.public_ref["unitId"],
                    "ownerProviderRef": unit.public_ref["ownerProviderRef"],
                    "sourceRevision": unit.public_ref["sourceRevision"]}
        existing = self._starts.get(correlation)
        if existing is not None and not same_reference(existing, snapshot):
            raise ClaudeProjectionRefused("observed correlation belongs to another unit")
        self._starts[correlation] = snapshot

    def revalidate_start(self, unit, context):
        if not callable(self._start_authority):
            raise ClaudeProjectionRefused("current start authority owner is absent")
        verified = self._start_authority(unit, context)
        if not isinstance(verified, Mapping):
            raise ClaudeProjectionRefused("current start authority unavailable or not verified")
        binding = self.records.owner_read_session(unit.unit_ref)
        if isinstance(binding.creation_correlation, str) and binding.creation_correlation:
            self._starts[binding.creation_correlation] = unit.public_ref["unitId"]
        return verified

    def revalidate_configuration(self, unit, context):
        if not callable(self._configuration_authority):
            raise ClaudeProjectionRefused("configuration authority owner is absent")
        verified = self._configuration_authority(unit, context)
        if not isinstance(verified, Mapping):
            raise ClaudeProjectionRefused("current configuration authority unavailable or not verified")
        return verified

    def verify_preparation(self, plan, invocation_facts):
        if not callable(self._preparation_authority):
            raise ClaudeProjectionRefused("preparation authority owner is absent")
        return self._preparation_authority(plan, invocation_facts)

    # -- publication ----------------------------------------------------------
    def publication_facts(self, unit_ref):
        unit = self._owner_unit(unit_ref)
        binding = self.records.owner_read_session(unit.unit_ref)
        if not callable(self._publication_owner):
            raise ClaudeProjectionRefused("core publication owner is absent")
        publication = self._publication_owner(unit, binding)
        if (not isinstance(publication, Mapping)
                or not isinstance(publication.get("directoryBindingRef"), Mapping)
                or not isinstance(publication.get("evidenceRef"), Mapping)
                or any(not isinstance(publication.get(key), int) or isinstance(publication.get(key), bool)
                       for key in ("managementEpoch",))):
            raise ClaudeProjectionRefused("core publication owner references differ")
        return _plain({"unitRef": unit.public_ref,
                       "providerRef": unit.facts["providerRef"],
                       "configurationTargetRef": unit.configuration_target_ref,
                       "managementEpoch": publication["managementEpoch"],
                       "ownership": publication.get("ownership", "owned"),
                       "sourceRevision": "native-owner-observation-" + str(binding.source_revision),
                       "directoryBindingRef": publication["directoryBindingRef"],
                       "evidenceRef": publication["evidenceRef"]})
