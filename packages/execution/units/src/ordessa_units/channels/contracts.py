"""Managed input facts and the original Workspace execution authority port.

These contracts create no capture, workspace, native session, or result store.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol

from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_infrastructure.encoding.immutable_json import safe_json

EXECUTION_EVIDENCE_VERSION = "workspace-managed-execute/1"


def plain_json_mapping(mapping: Mapping) -> dict:
    import json
    return json.loads(safe_json(mapping))


@dataclass(frozen=True)
class WorkspaceExecutionEvidence:
    environment_namespace: str
    principal_scope: str
    node_ref: Mapping
    unit_ref: Mapping
    operation_ref: str
    capture_ref: Mapping
    content_digest: str
    management_epoch: int
    evidence_ref: str

    def to_dict(self) -> dict:
        value = {"contractVersion": EXECUTION_EVIDENCE_VERSION,
            "environmentNamespace": self.environment_namespace,
            "principalScope": self.principal_scope, "nodeRef": plain_json_mapping(self.node_ref),
            "unitRef": plain_json_mapping(self.unit_ref), "operationRef": self.operation_ref,
            "captureRef": plain_json_mapping(self.capture_ref), "contentDigest": self.content_digest,
            "managementEpoch": self.management_epoch, "evidenceRef": self.evidence_ref}
        if (not self.environment_namespace or not self.principal_scope or not self.operation_ref
                or not self.evidence_ref or type(self.management_epoch) is not int
                or self.management_epoch < 0
                or not isinstance(self.content_digest, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest)
                or not isinstance(self.node_ref, Mapping)
                or not isinstance(self.unit_ref, Mapping)
                or not isinstance(self.capture_ref, Mapping)
                or self.node_ref.get("environmentNamespace") != self.environment_namespace
                or self.unit_ref.get("environmentNamespace") != self.environment_namespace
                or self.capture_ref.get("environmentNamespace") != self.environment_namespace):
            raise UnitGuaranteeUnavailable("Workspace execute evidence is incomplete")
        return value


class WorkspaceExecutionPort(Protocol):
    """Original Workspace owner; proof is revalidated at the native write edge."""
    def authorize_execute(self, request, node_ref, unit_ref, operation_ref,
                          capture_ref, content_digest, management_epoch) -> WorkspaceExecutionEvidence | None: ...
    def revalidate_execute(self, evidence: WorkspaceExecutionEvidence) -> WorkspaceExecutionEvidence | None: ...


@dataclass(frozen=True)
class ManagedInputOutcome:
    contract_version: str
    operation_ref: str
    state: str
    native_receipt_ref: str | None
    terminal_evidence_ref: str | None
    full_result_available: bool = False


__all__ = ["EXECUTION_EVIDENCE_VERSION", "plain_json_mapping", "WorkspaceExecutionEvidence",
           "WorkspaceExecutionPort", "ManagedInputOutcome"]
