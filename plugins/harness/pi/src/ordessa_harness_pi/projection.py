"""Real Pi trusted projection over the SAME deployment UnitRecords.

This is the deployment's own ``UnitProjectionPort`` adapter (and the records'
``NativeSessionEvidencePort``). Every durable read goes through the records
owner reads (``owner_read_unit`` / ``owner_read_session``): it consumes no
invocation, issues no ticket and creates no effect permission. The journal
stays the only durable truth.

- ``verify_preparation`` validates the original plan binding and returns the
  canonical isolated roots that the journal will seal.
- ``revalidate_start`` / ``revalidate_configuration`` delegate the
  current-authority re-check to the deployment's explicit authority ports;
  they never consume an invocation.
- ``publish_channel`` records the ORIGINAL observed native ``get_state``
  receipt under a digest evidence reference; ``verify_binding`` (the native
  session evidence port) can only confirm that same original receipt
  afterwards. Bookkeeping here is live/process-local: a cold restart
  re-verify of session evidence requires the original owner evidence store to
  be composed (registered limitation).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from ordessa_environment_api.operations import safe_json, sealed_mapping
from pacthold.agents.nodes.directory import DirectoryBindingRef
from ordessa_harness_pi.client import PI_PROTOCOL_ID
from ordessa_harness_pi.runtime_channel import verified_private_roots

COMPLETE_UNIT_FIELDS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


class PiProjectionRefused(RuntimeError):
    code = "PI_PROJECTION_REFUSED"


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
        raise PiProjectionRefused("owner projection value is not JSON-encodable") from error


class PiUnitProjection:
    """Real projection adapter; only the records owner reads expose journal facts.

    ``start_authority(unit, context)`` and, if composed,
    ``configuration_authority(unit, context)`` are the deployment's
    current-authority re-validation callables (authority / activation /
    directory / epoch facets). ``publication_owner(unit, binding)`` supplies
    the core publication references for :meth:`publication_facts`.
    """

    def __init__(self, records=None, *, start_authority: Callable,
                 configuration_authority: Callable | None = None,
                 publication_owner: Callable | None = None):
        self._records = records
        self._start_authority = start_authority
        self._configuration_authority = configuration_authority
        self._publication_owner = publication_owner
        self._evidence: dict[str, Mapping[str, str]] = {}  # original observed receipts, live only
        self._creations: dict[str, str] = {}  # observed start correlations -> unit ids, live only

    def attach_owner(self, records) -> None:
        """Bind the one journal this owner projects (single writer relationship)."""
        if self._records is not None and self._records is not records:
            raise PiProjectionRefused("projection already attached to another journal owner")
        self._records = records

    # -- preparation / revalidation ----------------------------------------
    def verify_preparation(self, plan, invocation_facts):
        if not isinstance(plan, Mapping) or not isinstance(invocation_facts, Mapping):
            raise PiProjectionRefused("original preparation plan and facts required")
        context = plan.get("context")
        if (not isinstance(context, Mapping)
                or not same_reference(context.get("nodeRef"), invocation_facts.get("targetRef"))):
            raise PiProjectionRefused("preparation plan node binding differs")
        return verified_private_roots(context.get("privateRootFacts"))

    def revalidate_start(self, unit, context):
        verified = self._start_authority(unit, context)
        if not isinstance(verified, Mapping):
            raise PiProjectionRefused("current start authority unavailable or not verified")
        if self._records is None:
            raise PiProjectionRefused("projection journal owner is absent")
        # Owner read with no invocation: observe the durable creation
        # correlation fixed by begin_session, for later query observations.
        binding = self._records.owner_read_session(unit.unit_ref)
        correlation = binding.creation_correlation
        if isinstance(correlation, str) and correlation:
            self._creations[correlation] = unit.unit_ref
        return verified

    def revalidate_configuration(self, unit, context):
        if self._configuration_authority is None:
            raise PiProjectionRefused("configuration authority owner is absent")
        verified = self._configuration_authority(unit, context)
        if not isinstance(verified, Mapping):
            raise PiProjectionRefused("current configuration authority unavailable or not verified")
        return verified

    # -- owner reads (no invocation, no ticket) -----------------------------
    def _owner_unit(self, unit_ref):
        if (not isinstance(unit_ref, Mapping) or set(unit_ref) != COMPLETE_UNIT_FIELDS
                or not isinstance(unit_ref.get("unitId"), str) or not unit_ref["unitId"]
                or len(unit_ref["unitId"]) > 256):
            raise PiProjectionRefused("complete owner-bound unit reference required")
        if self._records is None:
            raise PiProjectionRefused("projection journal owner is absent")
        # The owner records refusals surface unchanged (loader boundary: this
        # package only imports its declared dependencies, never records).
        unit = self._records.owner_read_unit(unit_ref["unitId"])
        if not same_reference(unit.public_ref, unit_ref):
            raise PiProjectionRefused("unit reference differs from original owner source")
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
            raise PiProjectionRefused("core publication owner is absent")
        publication = self._publication_owner(unit, binding)
        if (not isinstance(publication, Mapping)
                or not isinstance(publication.get("directoryBindingRef"), DirectoryBindingRef)
                or not isinstance(publication.get("evidenceRef"), Mapping)):
            raise PiProjectionRefused("core publication owner references differ")
        directory = publication["directoryBindingRef"]
        if directory.environment_namespace != unit.public_ref["environmentNamespace"]:
            raise PiProjectionRefused("core publication directory belongs to another environment")
        facts = {"unitRef": _plain(unit.public_ref),
                 "providerRef": _plain(unit.facts["providerRef"]),
                 "configurationTargetRef": _plain(unit.configuration_target_ref),
                 "managementEpoch": unit.facts["managementEpoch"],
                 "sourceRevision": "native-owner-observation-" + str(binding.source_revision),
                 "directoryBindingRef": directory,
                 "evidenceRef": publication["evidenceRef"]}
        try:
            return {"unitRef": sealed_mapping(facts["unitRef"]),
                    "providerRef": facts["providerRef"],
                    "configurationTargetRef": facts["configurationTargetRef"],
                    "managementEpoch": facts["managementEpoch"],
                    "sourceRevision": facts["sourceRevision"],
                    "directoryBindingRef": directory,
                    "evidenceRef": facts["evidenceRef"]}
        except (TypeError, ValueError) as error:
            raise PiProjectionRefused("publication facts are not JSON-encodable") from error

    # -- original native channel evidence -------------------------------------
    def publish_channel(self, unit, client, native_evidence) -> str:
        """Record the ORIGINAL observed get_state receipt under an evidence digest.

        ``client`` is never retained or exposed here: native channel handles
        stay with their owner (provider/lease), not with the projection.
        """
        if (not isinstance(native_evidence, Mapping)
                or not isinstance(native_evidence.get("sessionId"), str)):
            raise PiProjectionRefused("observed native channel evidence lacks a session id")
        session_id = native_evidence["sessionId"]
        if not session_id or len(session_id) > 256 or any(ord(c) < 32 for c in session_id):
            raise PiProjectionRefused("observed native session identity differs")
        if self._records is None:
            raise PiProjectionRefused("projection journal owner is absent")
        observed = _plain(native_evidence)
        digest = hashlib.sha256(safe_json({"unitRef": _plain(unit.public_ref),
                                           "sessionId": session_id, "observed": observed}).encode()).hexdigest()
        evidence_ref = "pi-native-session/" + digest
        self._evidence[evidence_ref] = sealed_mapping({"unitRef": _plain(unit.public_ref),
                                                       "sessionId": session_id, "observed": observed})
        return evidence_ref

    def verify_binding(self, unit, creation_correlation, evidence) -> Mapping[str, str]:
        """Native session evidence port for the records: confirm the original receipt only."""
        record = self._evidence.get(evidence) if isinstance(evidence, str) else None
        if (record is None or not isinstance(creation_correlation, str) or not creation_correlation
                or not same_reference(record["unitRef"], unit.public_ref)):
            raise PiProjectionRefused("original native session evidence is missing or forged")
        try:
            step = json.loads(creation_correlation).get("stepId")
        except (TypeError, ValueError):
            step = None
        if step != "start":
            raise PiProjectionRefused("native binding is not the original start correlation")
        return sealed_mapping({"nativeRealm": PI_PROTOCOL_ID, "sessionId": record["sessionId"],
                               "evidenceRef": evidence})

    # -- creation outcome query ----------------------------------------------
    def query_creation(self, correlation, verified_query_facts):
        if (not isinstance(verified_query_facts, Mapping)
                or verified_query_facts.get("query") is not True):
            raise PiProjectionRefused("read authority required to query original creation")
        if (not isinstance(correlation, str) or not correlation or len(correlation) > 2048):
            raise PiProjectionRefused("original creation correlation required")
        if self._records is None:
            raise PiProjectionRefused("projection journal owner is absent")
        unit_id = self._creations.get(correlation)
        if unit_id is None:
            raise PiProjectionRefused(
                "original creation correlation was not observed by this projection owner")
        binding = self._records.owner_read_session(unit_id)
        if binding.creation_correlation != correlation:
            raise PiProjectionRefused("durable session does not belong to the observed creation")
        unit = self._records.owner_read_unit(unit_id)
        return {"unitRef": _plain(unit.public_ref), "state": binding.state}
