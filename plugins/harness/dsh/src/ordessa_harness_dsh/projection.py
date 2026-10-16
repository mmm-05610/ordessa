"""Real dsh trusted projection over the SAME deployment UnitRecords.

This is the deployment's own ``UnitProjectionPort`` adapter. Every durable
read goes through the records owner reads (``owner_read_unit`` /
``owner_read_session``): it consumes no invocation, issues no ticket and
creates no effect permission. The journal stays the only durable truth.

- ``verify_preparation`` validates the original plan binding and returns the
  canonical isolated roots that the journal will seal.
- ``revalidate_start`` delegates the current-authority re-check to the
  deployment's explicit authority port; it never consumes an invocation.
- ``publish_channel`` records the ORIGINAL observed native session receipt
  (``session/new`` result plus the initialize facts) under a digest evidence
  reference; ``verify_binding`` (the native evidence port) can only confirm
  that same original receipt afterwards. Bookkeeping here is
  live/process-local: a cold restart re-verify of session evidence requires
  the original owner evidence store to be composed (registered limitation).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_harness_dsh.client import PROTOCOL, identity_text
from ordessa_harness_dsh.runtime_channel import verified_private_roots

COMPLETE_UNIT_FIELDS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


class DshProjectionRefused(RuntimeError):
    code = "DSH_PROJECTION_REFUSED"


def same_reference(left, right) -> bool:
    """JSON identity of two owner references, retaining JSON scalar types."""
    try:
        return safe_json(left) == safe_json(right)
    except (TypeError, ValueError):
        return False


def _plain(value):
    try:
        return json.loads(safe_json(value))
    except (TypeError, ValueError) as error:
        raise DshProjectionRefused("owner projection value is not JSON-encodable") from error


class DshUnitProjection:
    """Real projection adapter; only the records owner reads expose journal facts.

    ``start_authority(unit, context)`` is the deployment's current-authority
    re-validation callable (authority / activation / directory / epoch facets).
    ``publication_owner(unit, binding)`` supplies the core publication
    references for :meth:`publication_facts`.
    """

    def __init__(self, records=None, *, start_authority: Callable,
                 publication_owner: Callable | None = None):
        self._records = records
        self._start_authority = start_authority
        self._publication_owner = publication_owner
        self._evidence: dict[str, Mapping[str, str]] = {}  # original observed receipts, live only
        self._creations: dict[str, str] = {}  # observed start correlations -> unit ids, live only

    def attach_owner(self, records) -> None:
        """Bind the one journal this owner projects (single writer relationship)."""
        if self._records is not None and self._records is not records:
            raise DshProjectionRefused("projection already attached to another journal owner")
        self._records = records

    # -- preparation / revalidation ----------------------------------------
    def verify_preparation(self, plan, invocation_facts):
        if not isinstance(plan, Mapping) or not isinstance(invocation_facts, Mapping):
            raise DshProjectionRefused("original preparation plan and facts required")
        context = plan.get("context")
        if (not isinstance(context, Mapping)
                or not same_reference(context.get("nodeRef"), invocation_facts.get("targetRef"))):
            raise DshProjectionRefused("preparation plan node binding differs")
        return verified_private_roots(context.get("privateRootFacts"))

    def revalidate_start(self, unit, context):
        verified = self._start_authority(unit, context)
        if not isinstance(verified, Mapping):
            raise DshProjectionRefused("current start authority unavailable or not verified")
        if self._records is None:
            raise DshProjectionRefused("projection journal owner is absent")
        # Owner read with no invocation: observe the durable creation
        # correlation fixed by begin_session, for later query observations.
        binding = self._records.owner_read_session(unit.unit_ref)
        correlation = binding.creation_correlation
        if isinstance(correlation, str) and correlation:
            self._creations[correlation] = unit.unit_ref
        return verified

    # -- owner reads (no invocation, no ticket) -----------------------------
    def _owner_unit(self, unit_ref):
        if (not isinstance(unit_ref, Mapping) or set(unit_ref) != COMPLETE_UNIT_FIELDS
                or not isinstance(unit_ref.get("unitId"), str) or not unit_ref["unitId"]
                or len(unit_ref["unitId"]) > 256):
            raise DshProjectionRefused("complete owner-bound unit reference required")
        if self._records is None:
            raise DshProjectionRefused("projection journal owner is absent")
        # The owner records refusals surface unchanged (loader boundary: this
        # package only imports its declared dependencies, never records).
        unit = self._records.owner_read_unit(unit_ref["unitId"])
        if not same_reference(unit.public_ref, unit_ref):
            raise DshProjectionRefused("unit reference differs from original owner source")
        return unit

    def read_unit(self, unit_ref):
        return self._owner_unit(unit_ref)

    def read_session(self, unit_ref):
        unit = self._owner_unit(unit_ref)
        return self._records.owner_read_session(unit.unit_ref)

    # -- publication ---------------------------------------------------------
    def publication_facts(self, unit_ref):
        unit = self._owner_unit(unit_ref)
        binding = self._records.owner_read_session(unit.unit_ref)
        if self._publication_owner is None:
            raise DshProjectionRefused("core publication owner is absent")
        publication = self._publication_owner(unit, binding)
        if (not isinstance(publication, Mapping)
                or not isinstance(publication.get("directoryBindingRef"), Mapping)
                or not isinstance(publication.get("evidenceRef"), str) or not publication["evidenceRef"]):
            raise DshProjectionRefused("core publication owner references differ")
        facts = {"unitRef": _plain(unit.public_ref),
                 "providerRef": _plain(unit.facts["providerRef"]),
                 "configurationTargetRef": _plain(unit.configuration_target_ref),
                 "managementEpoch": unit.facts["managementEpoch"],
                 "sourceRevision": "native-owner-observation-" + str(binding.source_revision),
                 "directoryBindingRef": _plain(publication["directoryBindingRef"]),
                 "evidenceRef": publication["evidenceRef"]}
        try:
            return sealed_mapping(facts)
        except (TypeError, ValueError) as error:
            raise DshProjectionRefused("publication facts are not JSON-encodable") from error

    # -- original native channel evidence -------------------------------------
    def publish_channel(self, unit, client, native_evidence) -> str:
        """Record the ORIGINAL observed session receipt under an evidence digest.

        ``client`` is never retained or exposed here: native channel handles
        stay with their owner (provider/lease), not with the projection.
        """
        if (not isinstance(native_evidence, Mapping)
                or not identity_text(native_evidence.get("sessionId"))
                or not isinstance(native_evidence.get("initialize"), Mapping)):
            raise DshProjectionRefused("observed native channel evidence lacks a session identity")
        session_id = native_evidence["sessionId"]
        if len(session_id) > 256:
            raise DshProjectionRefused("observed native session identity differs")
        if self._records is None:
            raise DshProjectionRefused("projection journal owner is absent")
        observed = _plain(native_evidence)
        digest = hashlib.sha256(safe_json({"unitRef": _plain(unit.public_ref),
                                           "sessionId": session_id, "observed": observed}).encode()).hexdigest()
        evidence_ref = "dsh-native-session/" + digest
        self._evidence[evidence_ref] = sealed_mapping({"unitRef": _plain(unit.public_ref),
                                                       "sessionId": session_id, "observed": observed})
        return evidence_ref

    def verify_binding(self, unit, creation_correlation, evidence) -> Mapping[str, str]:
        """Native evidence port for the records: confirm the original receipt only."""
        record = self._evidence.get(evidence) if isinstance(evidence, str) else None
        if (record is None or not isinstance(creation_correlation, str) or not creation_correlation
                or not same_reference(record["unitRef"], unit.public_ref)):
            raise DshProjectionRefused("original native channel evidence is missing or forged")
        try:
            step = json.loads(creation_correlation).get("stepId")
        except (TypeError, ValueError):
            step = None
        if step != "start":
            raise DshProjectionRefused("native binding is not the original start correlation")
        return sealed_mapping({"nativeRealm": PROTOCOL, "sessionId": record["sessionId"],
                               "evidenceRef": evidence})

    # -- creation outcome query ----------------------------------------------
    def query_creation(self, correlation, verified_query_facts):
        if (not isinstance(verified_query_facts, Mapping)
                or verified_query_facts.get("query") is not True):
            raise DshProjectionRefused("read authority required to query original creation")
        if not isinstance(correlation, str) or not correlation or len(correlation) > 2048:
            raise DshProjectionRefused("original creation correlation required")
        if self._records is None:
            raise DshProjectionRefused("projection journal owner is absent")
        unit_id = self._creations.get(correlation)
        if unit_id is None:
            raise DshProjectionRefused(
                "original creation correlation was not observed by this projection owner")
        binding = self._records.owner_read_session(unit_id)
        if binding.creation_correlation != correlation:
            raise DshProjectionRefused("durable session does not belong to the observed creation")
        unit = self._records.owner_read_unit(unit_id)
        return {"unitRef": _plain(unit.public_ref), "state": binding.state}
