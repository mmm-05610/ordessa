"""Read a caller's own durable operation metadata without recovery effects."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
)
from ordessa_infrastructure.database.records import DomainStorePort
from ordessa_execution_api.environment.operations import OperationStorePort, sealed_mapping

from ordessa_units.bindings.publication import decode_node_ref
from ordessa_execution_api.environment.operations import operation_holder, node_holder


OPERATION_IDENTITIES = "core.operation-identities"


@dataclass(frozen=True)
class AgentUnresolvedSnapshot:
    """Read-only facts from this Environment's original Unit ledger."""

    unresolved_operation_refs: tuple[str, ...]
    active_usage_ids: tuple[str, ...]


class OperationNotFound(LookupError):
    """No operation visible to the authenticated Environment principal."""

    code = "OPERATION_NOT_FOUND"


class AgentOperations:
    """Read a fixed, redacted projection from the existing operation ledger.

    This service never queries an owner, creates an invocation, or advances an
    operation. Node-bound reads pass through the existing NodePublication
    historical integrity and ACL checks.
    """

    def __init__(self, environment, nodes):
        self._environment, self._nodes = environment, nodes

    def read(self, operation_ref: str):
        return self._read(operation_ref, closed_inventory=False)

    def _read(self, operation_ref: str, *, closed_inventory: bool):
        env = self._environment
        with env._admission_lock:
            if closed_inventory:
                if not env._closed:
                    raise GuaranteeUnavailableError("closed operation inventory requires the admission cut")
            else:
                env._check_open()
            if (not isinstance(operation_ref, str) or not operation_ref
                    or operation_ref.strip() != operation_ref or len(operation_ref) > 256
                    or any(ord(char) < 32 for char in operation_ref)):
                raise IdentityMismatchError("complete operation identity required")
            store = env._store
            if (not isinstance(store, OperationStorePort)
                    or not isinstance(store, DomainStorePort)):
                raise GuaranteeUnavailableError("same-store operation and identity reads required")
            if (env._policy is None
                    or not env._policy.admit_object_access(
                        env._principal_scope,
                        f"{env.environment_id}:operation:{operation_ref}",
                        "read",
                    )):
                raise AdmissionRefusedError("operation read refused")

            identity = store.read_domain(
                env.environment_id, OPERATION_IDENTITIES, operation_ref
            )
            if identity is None:
                raise OperationNotFound("operation not found")
            try:
                if (not isinstance(identity, Mapping)
                        or set(identity) != {"record_id", "revision", "value"}
                        or identity["record_id"] != operation_ref
                        or type(identity["revision"]) is not int
                        or identity["revision"] != 1
                        or not isinstance(identity["value"], Mapping)
                        or set(identity["value"]) != {"holder"}):
                    raise ValueError("identity record shape differs")
                holder = identity["value"]["holder"]
                expected_holder_fields = {
                    "kind", "environmentNamespace", "principalScope", "requestId", "operationId"
                }
                if (not isinstance(holder, Mapping)
                        or set(holder) != expected_holder_fields
                        or holder["kind"] != "operation"
                        or holder["environmentNamespace"] != env.environment_id
                        or holder["operationId"] != operation_ref):
                    raise ValueError("operation identity holder differs")
                # A foreign principal sees the same result as an absent index.
                # The caller's identity comes only from the trusted Environment.
                if holder["principalScope"] != env._principal_scope:
                    raise OperationNotFound("operation not found")
                request = RequestKey(
                    holder["environmentNamespace"],
                    holder["principalScope"],
                    holder["requestId"],
                )
                operation = store.read_operation(request)
                if (operation is None or operation.request != request
                        or operation.intent.operation_ref != operation_ref):
                    raise ValueError("operation record and identity index differ")

                target_node = operation.intent.node_ref
                if target_node is not None:
                    node_ref = decode_node_ref(target_node)
                    if node_ref.environment != env.environment_id:
                        raise ValueError("operation target Environment differs")
                    try:
                        node_facts = (self._nodes._read_for_closed_inventory(node_ref)
                                      if closed_inventory else self._nodes.read(node_ref))
                    except AdmissionRefusedError:
                        # The operation object may be readable while its Node
                        # is not. Hide that association the same way as an
                        # absent operation from this principal.
                        raise OperationNotFound("operation not found") from None
                    if node_facts is None and not (
                        operation.intent.kind == "agent-preparation"
                        and operation.status != "published"
                    ):
                        raise ValueError("published operation target Node is absent")
                    # agent-preparation binds a planned Node before publication.
                    # NodePublication.read still enforces target ACL; a missing
                    # publication is accepted only for that nonpublished intent.

                projection = {
                    "operationRef": operation.intent.operation_ref,
                    "kind": operation.intent.kind,
                    "revision": operation.revision,
                    "status": operation.status,
                    "nodeRef": target_node,
                    "hasResult": operation.result is not None,
                }
                return sealed_mapping(projection)
            except OperationNotFound:
                raise
            except AdmissionRefusedError:
                # Operation ACL is checked before any identity lookup.
                raise
            except GuaranteeUnavailableError:
                raise
            except Exception:
                raise GuaranteeUnavailableError("stored operation identity or target is inconsistent") from None

    def unresolved_snapshot(self) -> AgentUnresolvedSnapshot:
        """Inspect original durable obligations without advancing an operation."""
        return self._unresolved_snapshot(closed_inventory=False)

    def closed_unresolved_snapshot(self) -> AgentUnresolvedSnapshot:
        """Read the original Unit obligations after Environment admission closes.

        This is the public read-only close inventory for an owner of this exact
        Environment. It requires ``Environment.close()`` to have set its
        admission cut and the original StorePort still to be open. It applies
        the same principal/object ACL, identity, Node provenance, and Usage
        validation as ``unresolved_snapshot()``; it never dispatches, releases,
        reconciles, or creates a second authority. The caller must serialize
        this read with final StorePort closure when a close report needs a
        single durable Store cut. Calling it before the admission cut refuses.
        """
        return self._unresolved_snapshot(closed_inventory=True)

    def _unresolved_snapshot(self, *, closed_inventory: bool) -> AgentUnresolvedSnapshot:
        env = self._environment
        with env._admission_lock:
            if closed_inventory:
                if not env._closed:
                    raise GuaranteeUnavailableError("closed inventory requires Environment admission cut")
            else:
                env._check_open()
            store = env._store
            if not isinstance(store, OperationStorePort) or not isinstance(store, DomainStorePort):
                raise GuaranteeUnavailableError("same-store Unit inventory unavailable")
            operations = []
            usages = set()
            for row in store.list_domain(env.environment_id, OPERATION_IDENTITIES):
                try:
                    holder = row["value"]["holder"]
                    if (holder["kind"] != "operation"
                            or holder["environmentNamespace"] != env.environment_id
                            or holder["operationId"] != row["record_id"]):
                        raise ValueError("operation identity differs")
                    if holder["principalScope"] != env._principal_scope:
                        continue
                    request = RequestKey(env.environment_id,
                                         holder["principalScope"], holder["requestId"])
                    view = self._read(row["record_id"], closed_inventory=closed_inventory)
                    if view["status"] not in {"reserved", "running", "unknown"}:
                        continue
                    operation = store.read_operation(request)
                    if operation is None or operation.intent.operation_ref != row["record_id"]:
                        raise GuaranteeUnavailableError("stored operation inventory is inconsistent")
                    # Read and validate rights before classifying a lifecycle
                    # row whose generic status remains `running` after its
                    # concluded step. A residual active/unknown Usage always
                    # keeps the operation unresolved and is never hidden.
                    holder_usages = store.read_usages(env.environment_id,
                                                     operation_holder(request, row["record_id"]))
                    active_holder_usages = False
                    for usage in holder_usages:
                        if (usage["state"] not in {"active", "unknown", "released"}
                                or type(usage["usageId"]) is not str or not usage["usageId"]):
                            raise GuaranteeUnavailableError("stored Usage inventory is inconsistent")
                        if usage["state"] != "released":
                            usages.add(usage["usageId"])
                            active_holder_usages = True
                    lifecycle_concluded = (
                        view["status"] == "running"
                        and view["kind"] in {"agent-stop", "agent-release", "agent-recovery"}
                        and operation.intent.steps
                        and all((step_record := store.read_operation_step(request, step.step_id)) is not None
                                and step_record.outcome == "concluded"
                                for step in operation.intent.steps))
                    if not lifecycle_concluded or active_holder_usages:
                        operations.append(row["record_id"])
                except (KeyError, TypeError, ValueError):
                    raise GuaranteeUnavailableError("stored operation inventory is inconsistent") from None
            nodes = (self._nodes._list_for_closed_inventory_if_present() if closed_inventory
                     else self._nodes.list())
            for node in nodes:
                ref = decode_node_ref(node["nodeRef"])
                for usage in store.read_usages(env.environment_id,
                                               node_holder(ref.environment, ref.instance_id, ref.generation)):
                    if (usage["state"] not in {"active", "unknown", "released"}
                            or type(usage["usageId"]) is not str or not usage["usageId"]):
                        raise GuaranteeUnavailableError("stored Usage inventory is inconsistent")
                    if usage["state"] != "released":
                        usages.add(usage["usageId"])
            return AgentUnresolvedSnapshot(tuple(sorted(operations)), tuple(sorted(usages)))
