"""Specific Unit admission scope, not a plugin host or capability registry."""
from contextlib import contextmanager
from collections.abc import Mapping
from threading import RLock
from ordessa_execution_api.environment import EnvironmentId, AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError
from ordessa_execution_api.environment.identity import ParticipantInstanceRef
from ordessa_execution_api.environment.operations import safe_json, sealed_mapping, node_holder

class UnitAdmissionContext:
    def __init__(self, environment_namespace, *, store, policy, fingerprint_port,
                 harness_catalog, material_catalog, principal_scope='local', admission_lock=None):
        self._namespace = EnvironmentId(environment_namespace).value
        if not isinstance(principal_scope, str) or not principal_scope:
            raise ValueError('explicit principal scope required')
        if store is None:
            raise GuaranteeUnavailableError('original Unit operation store required')
        if harness_catalog.environment_namespace != self._namespace or material_catalog.environment_namespace != self._namespace:
            raise IdentityMismatchError('catalog namespace differs from Unit admission')
        self._store, self._policy, self._fingerprint_port = store, policy, fingerprint_port
        self._principal_scope = principal_scope
        self._admission_lock = admission_lock or RLock()
        self._harness_catalog, self._material_catalog = harness_catalog, material_catalog
        self._closed, self._draining = False, False
        self._agent_services, self._agent_owner_ports = None, None

    @property
    def environment_namespace(self): return self._namespace
    @property
    def environment_id(self): return self._namespace
    @property
    def store_port(self): return self._store
    @property
    def policy(self): return self._policy
    @property
    def principal_scope(self): return self._principal_scope
    @property
    def admission_lock(self): return self._admission_lock
    @property
    def harness_catalog(self): return self._harness_catalog
    @property
    def material_catalog(self): return self._material_catalog
    @property
    def draining(self): return self._draining

    def check_open(self):
        if self._closed: raise AdmissionRefusedError('Unit admission owner is closed')
    def _check_open(self): self.check_open()
    def _check_environment(self, namespace):
        if namespace != self._namespace: raise IdentityMismatchError('Unit admission namespace differs')

    def drain(self):
        with self._admission_lock:
            self.check_open(); self._draining = True
            if self._agent_services is not None and self._agent_services.unit_manager is not None:
                self._agent_services.unit_manager.drain()

    def pending(self):
        with self._admission_lock:
            manager = self._agent_services.unit_manager if self._agent_services is not None else None
            return sealed_mapping({'unitRefs': manager.references() if manager is not None else (),
                'creationHolds': manager.has_unsettled_creations() if manager is not None else False,
                'operationRefs': tuple(record.intent.operation_ref for record in self._store.pending_operations(self._namespace)),
                'usageIds': self._store.pending_usage_ids(self._namespace),
                'unclassifiedRequests': self._store.pending_unclassified_requests(self._namespace)})

    @contextmanager
    def provider_retirement_guard(self, owner_id, generation):
        # Trusted root passes this bound method to the role catalog. No Boolean proof.
        with self._admission_lock:
            self.check_open()
            manager = self._agent_services.unit_manager if self._agent_services is not None else None
            if manager is not None and (manager.has_unsettled_creations() or any(
                    ref['ownerProviderRef'].get('ownerActivationRef', {}).get('pluginId') == owner_id
                    and ref['ownerProviderRef'].get('generation') == generation for ref in manager.references())):
                raise GuaranteeUnavailableError('original Unit live owner still holds provider')
            with self._store.transaction():
                if self._store.unresolved_provider_usages(self._namespace, owner_id, generation):
                    raise GuaranteeUnavailableError('original provider Usage remains held')
                yield None

    def close(self):
        with self._admission_lock:
            if self._closed: return
            self.drain()
            if any(self.pending().values()):
                raise GuaranteeUnavailableError('Unit operation/Usage/live creation remains pending')
            if self._agent_owner_ports is not None: self._agent_owner_ports.issuer.close()
            self._closed = True
            # No native stop, no EnvironmentUse/resource deletion, no store close here.

    def read_held_node_usages(self, node_ref, usage_ids, required_targets, *, allowed_states):
        """Read one exact, original Node-held Usage set without provider dispatch.

        This neutral preflight returns an immutable snapshot for a later claim
        fence; it does not make that read atomic with claim_operation_step.
        Callers must still let the original Store perform that CAS.
        """
        from ordessa_execution_api.environment.operations import node_holder, safe_json, sealed_mapping
        with self._admission_lock:
            self._check_open()
            if (not isinstance(node_ref, ParticipantInstanceRef)
                    or node_ref.environment != self.environment_id
                    or self._policy is None or not self._policy.admit_object_access(
                        self._principal_scope,
                        f"{self.environment_id}:agents.node:{node_ref.instance_id}", "read")):
                raise AdmissionRefusedError("original Node cleanup access refused")
            reader = getattr(self._store, "read_usages", None)
            if not callable(reader):
                raise GuaranteeUnavailableError("original Node Usage ledger unavailable")
            if (not isinstance(usage_ids, tuple) or not usage_ids
                    or any(not isinstance(value, str) or not value for value in usage_ids)
                    or len(set(usage_ids)) != len(usage_ids)):
                raise IdentityMismatchError("original Node Usage identities required")
            if (not isinstance(required_targets, Mapping) or not required_targets
                    or any(not isinstance(label, str) or not label
                           or not isinstance(target, Mapping)
                           for label, target in required_targets.items())
                    or len({safe_json(target) for target in required_targets.values()})
                       != len(required_targets)):
                raise IdentityMismatchError("exact original Node Usage targets required")
            if (not isinstance(allowed_states, (tuple, frozenset)) or not allowed_states
                    or any(not isinstance(state, str) or state not in ("active", "unknown")
                           for state in allowed_states)
                    or len(set(allowed_states)) != len(allowed_states)):
                raise IdentityMismatchError("original Node Usage states required")
            rows = reader(self.environment_id, node_holder(
                self.environment_id, node_ref.instance_id, node_ref.generation))
            # Reject malformed original evidence before reserving a request.
            # The original Store claim transaction still owns the atomic CAS;
            # admission must not persist a request on an invalid fence basis.
            if any(not isinstance(row, Mapping)
                   or not isinstance(row.get("usageId"), str) or not row["usageId"]
                   or type(row.get("revision")) is not int or row["revision"] < 1
                   or type(row.get("rights")) is not list or not row["rights"]
                   or any(not isinstance(right, str) or not right for right in row["rights"])
                   or not isinstance(row.get("targetRef"), Mapping)
                   or not isinstance(row.get("state"), str)
                   for row in rows):
                raise GuaranteeUnavailableError("original Node Usage row is invalid")
            if ({row["usageId"] for row in rows} != set(usage_ids)
                    or any(row["state"] not in allowed_states for row in rows)):
                raise GuaranteeUnavailableError("original Node Usage set is not held exactly")
            for label, target in required_targets.items():
                if not any(safe_json({"ref": row["targetRef"]}) == safe_json({"ref": target})
                           and "use" in row["rights"] for row in rows):
                    raise GuaranteeUnavailableError(f"{label} Usage is absent")
            # This first read is only the frozen fence basis. The operation
            # Store compares these exact rows again during the claim transaction.
            return tuple(sealed_mapping(row) for row in rows)

