"""Read a caller's own durable operation metadata without recovery effects."""
from __future__ import annotations

from collections.abc import Mapping

from ordessa_environment_api import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    RequestKey,
)
from ordessa_environment_api.domain import DomainStorePort
from ordessa_environment_api.operations import OperationStorePort, sealed_mapping

from .nodes import decode_node_ref


OPERATION_IDENTITIES = "core.operation-identities"


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
        env = self._environment
        with env._admission_lock:
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
                        node_facts = self._nodes.read(node_ref)
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
