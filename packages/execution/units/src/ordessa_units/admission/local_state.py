"""Fixed local Unit current-state, directory and scope authority.

This owner projects state from the original OperationStore, Harness catalog,
Environment instance/Use handle and UnitRecords. It creates no grants or rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_agents.profiles import encode_revision_ref

from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import InvocationCurrentState
from ordessa_units.records.unit_records import (
    CanonicalConfigurationScopeRef,
    UnitRecordsRefused,
)


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(safe_json(value).encode("utf-8")).hexdigest()


def _same(left, right) -> bool:
    try:
        # safe_json accepts JSON object roots; wrap values to compare the full
        # JSON scalar domain while retaining JSON's exact type distinctions.
        return safe_json({"value": left}) == safe_json({"value": right})
    except Exception:
        return False


class FixedUnitCurrentState:
    """Current-state owner for one fixed local run permission and Environment."""

    def __init__(self, *, store, harness_catalog, environment_instance,
                 environment_namespace, root_directory, owner_id, profile_revision,
                 agent_id, permission_id):
        root = Path(root_directory)
        if (not callable(getattr(store, "read_operation", None))
                or not callable(getattr(harness_catalog, "describe", None))
                or not isinstance(environment_namespace, str) or not environment_namespace
                or not isinstance(owner_id, str) or not owner_id
                or not isinstance(permission_id, str) or not permission_id
                or not isinstance(agent_id, str) or not agent_id
                or not isinstance(root_directory, str) or not root.is_absolute()
                or type(getattr(environment_instance, "identity", None)) is not str
                or not hasattr(environment_instance, "snapshot")
                or getattr(profile_revision, "environment_namespace", None) != environment_namespace
                or root.resolve(strict=False) != root
                or any(part.is_symlink() for part in (root, *root.parents))):
            raise UnitRecordsRefused("fixed Unit current-state owner inputs required")
        self.store = store
        self.harness_catalog = harness_catalog
        self.environment_instance = environment_instance
        self.environment_namespace = environment_namespace
        self.root_directory = root
        self.owner_id = owner_id
        self.profile_revision = profile_revision
        self.agent_id = agent_id
        self.permission_id = permission_id
        self._lock = RLock()
        self._records = None
        self._manager = None
        self._epochs = {}
        self._scope_sources = {}

    def attach_owner(self, records, original_manager):
        """Bind the one original records/manager pair; never replace either."""
        with self._lock:
            if (records is None or original_manager is None
                    or getattr(original_manager, "records", None) is not records
                    or getattr(records, "journal", None) is None):
                raise UnitRecordsRefused("original UnitRecords and Manager must agree")
            if self._records is not None and (self._records is not records or self._manager is not original_manager):
                raise UnitRecordsRefused("cannot replace the original Unit owner")
            self._records, self._manager = records, original_manager

    def _require_owner(self):
        if self._records is None or self._manager is None:
            raise UnitRecordsRefused("original Unit owner is not attached")
        return self._records, self._manager

    def _node(self, node_ref):
        if (not isinstance(node_ref, Mapping)
                or set(node_ref) != {"environmentNamespace", "nodeId", "generation"}
                or node_ref.get("environmentNamespace") != self.environment_namespace
                or not isinstance(node_ref.get("nodeId"), str)
                or node_ref["nodeId"] in {".", ".."}
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", node_ref["nodeId"])
                or type(node_ref.get("generation")) is not int or node_ref["generation"] < 1):
            raise UnitRecordsRefused("fixed scoped node reference required")
        return sealed_mapping(dict(node_ref))

    def _roots(self, node_ref, roots):
        node = self._node(node_ref)
        if not isinstance(roots, Mapping) or set(roots) != {"home", "cwd", "profile", "tmp"}:
            raise UnitRecordsRefused("complete fixed private-root set required")
        base = self.root_directory / node["nodeId"]
        # root_directory is the host-selected fixed root. Reject a symlink or
        # path escape at every existing component; do not create directories.
        if (not base.is_relative_to(self.root_directory)
                or base.resolve(strict=False) != base
                or any(part.is_symlink() for part in (base, *base.parents))):
            raise UnitRecordsRefused("private Unit root is not a canonical non-symlink path")
        expected = {key: str(base / key) for key in ("home", "cwd", "profile", "tmp")}
        if not _same(roots, expected):
            raise UnitRecordsRefused("private Unit roots differ from fixed owner selection")
        for path in (base, *(Path(item) for item in expected.values())):
            if path.resolve(strict=False) != path or any(part.is_symlink() for part in (path, *path.parents)):
                raise UnitRecordsRefused("private Unit root escapes its fixed selection")
        return expected

    def directory_ref(self, node_ref, roots):
        node = self._node(node_ref)
        fixed_roots = self._roots(node, roots)
        identity = {"nodeRef": dict(node), "roots": fixed_roots,
                    "ownerId": self.owner_id, "permissionId": self.permission_id}
        ref = DirectoryBindingRef(self.environment_namespace,
            "unit-" + hashlib.sha256(safe_json(identity).encode()).hexdigest()[:32],
            node["generation"], _digest(identity))
        return ref

    def _scope(self, provider_ref, node_ref, roots):
        node = self._node(node_ref)
        fixed_roots = self._roots(node, roots)
        if (not isinstance(provider_ref, Mapping)
                or provider_ref.get("environmentNamespace") != self.environment_namespace):
            raise UnitRecordsRefused("fixed Harness provider reference required")
        source = {"providerRef": dict(provider_ref), "nodeRef": dict(node),
                  "roots": fixed_roots, "ownerId": self.owner_id,
                  "permissionId": self.permission_id}
        return CanonicalConfigurationScopeRef(
            self.environment_namespace,
            "unit-scope-" + hashlib.sha256(safe_json(source).encode()).hexdigest()[:40],
            _digest(source))

    def issue_scope(self, provider_ref, node_ref, private_root_facts):
        scope = self._scope(provider_ref, node_ref, private_root_facts)
        pending = getattr(self.store, "pending_operations", None)
        if not callable(pending):
            raise UnitRecordsRefused("original operation source index is unavailable")
        matches = []
        for operation in pending(self.environment_namespace):
            context = operation.intent.context_ref
            if (not _same(context.get("nodeRef"), node_ref)
                    or not _same(context.get("privateRootFacts"), private_root_facts)
                    or context.get("localUnitRun", {}).get("ownerId") != self.owner_id
                    or not isinstance(context.get("harnessDefinitionRef"), Mapping)
                    or not operation.intent.steps
                    or not _same(operation.intent.steps[0].pinned_provider_ref, provider_ref)):
                continue
            admitted = self.harness_catalog.describe(context["harnessDefinitionRef"])
            if not _same(getattr(admitted, "provider_ref", None), provider_ref):
                continue
            request = operation.request
            if not isinstance(request, RequestKey):
                continue
            matches.append((request, _digest(context)))
        if len(matches) != 1:
            raise UnitRecordsRefused("scope must bind one exact pending original prepare operation")
        with self._lock:
            self._scope_sources[safe_json(scope.to_dict())] = (
                sealed_mapping(dict(provider_ref)), self._node(node_ref), *matches[0])
        return scope

    def verify_scope(self, scope_ref, private_root_facts):
        try:
            if not isinstance(scope_ref, CanonicalConfigurationScopeRef):
                return False
            candidate = self._scope_sources.get(safe_json(scope_ref.to_dict()))
            if candidate is None:
                return False
            provider, node, request, context_digest = candidate
            operation = self.store.read_operation(request)
            if (operation is None
                    or _digest(operation.intent.context_ref) != context_digest
                    or not _same(operation.intent.context_ref.get("nodeRef"), node)
                    or not _same(operation.intent.context_ref.get("privateRootFacts"), private_root_facts)
                    or not operation.intent.steps
                    or not _same(operation.intent.steps[0].pinned_provider_ref, provider)):
                return False
            return scope_ref == self._scope(provider, node, private_root_facts)
        except Exception:
            return False

    def map_legacy_scope(self, legacy_target):
        # No implicit conversion from legacy targets into this fixed namespace.
        return None

    def _snapshot(self):
        snapshot = self.environment_instance.snapshot
        observation = getattr(snapshot, "observation", None)
        if (getattr(snapshot, "phase", None) != "ready"
                or getattr(snapshot, "generation", None) is None
                or getattr(observation, "state", None) != "running"):
            raise UnitRecordsRefused("fixed Environment is not observed ready and running")
        return snapshot

    def _snapshot_generation(self):
        """Read the same Environment generation without requiring a live Use."""
        snapshot = self.environment_instance.snapshot
        generation = getattr(snapshot, "generation", None)
        if type(generation) is not int or generation < 0:
            raise UnitRecordsRefused("fixed Environment generation is unavailable")
        return snapshot

    def _operation_context(self, request, context_ref, node_ref, *, historical_query=False):
        if not isinstance(request, RequestKey) or not isinstance(context_ref, Mapping):
            return None
        if request.environment_namespace != self.environment_namespace:
            return None
        operation = self.store.read_operation(request)
        if operation is None or not _same(operation.intent.context_ref, context_ref):
            return None
        if not _same(context_ref.get("nodeRef"), node_ref):
            return None
        local = context_ref.get("localUnitRun")
        snapshot = self._snapshot_generation() if historical_query else self._snapshot()
        if (not isinstance(local, Mapping)
                or local.get("ownerId") != self.owner_id
                or local.get("permissionId") != self.permission_id
                or local.get("environmentIdentity") != self.environment_instance.identity
                or local.get("environmentGeneration") != snapshot.generation
                or local.get("agentId") != self.agent_id
                or not _same(local.get("profileRevision"), encode_revision_ref(self.profile_revision))
                or not _same(operation.intent.profile_snapshot_ref, encode_revision_ref(self.profile_revision))):
            return None
        try:
            roots = self._roots(node_ref, context_ref.get("privateRootFacts"))
            directory = self.directory_ref(node_ref, roots)
            persisted = DirectoryBindingRef.from_dict(dict(context_ref.get("directoryBindingRef", {})))
        except Exception:
            return None
        if persisted != directory:
            return None
        definition_ref = context_ref.get("harnessDefinitionRef")
        if (not isinstance(definition_ref, Mapping)
                or definition_ref.get("environmentNamespace") != self.environment_namespace
                or operation.intent.management_epoch != local["environmentGeneration"]
                or not operation.intent.steps):
            return None
        return operation, local, roots

    def _query_reservation(self, context_ref, node_ref, provider_ref):
        """Resolve cold-read provenance from the original UnitRecords row only."""
        records, _manager = self._require_owner()
        read = context_ref.get("acpTurnRead")
        unit_ref = read.get("unitRef") if isinstance(read, Mapping) else None
        if (not isinstance(unit_ref, Mapping)
                or set(unit_ref) != {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
                or unit_ref.get("environmentNamespace") != self.environment_namespace
                or not isinstance(unit_ref.get("unitId"), str) or not unit_ref["unitId"]):
            raise UnitRecordsRefused("exact original Unit reference required for receipt query")
        reservation = records.owner_read_unit(unit_ref["unitId"])
        if (not _same(reservation.public_ref, unit_ref)
                or not _same(reservation.facts.get("nodeRef"), node_ref)
                or not _same(reservation.facts.get("providerRef"), provider_ref)):
            raise UnitRecordsRefused("receipt query differs from the original Unit reservation")
        source = self._verify_reservation_source(reservation, node_ref)
        if (source.status != "published" or source.intent.kind != "unit-public-prepare"
                or not source.intent.steps
                or not _same(source.intent.steps[0].pinned_provider_ref, provider_ref)
                or not _same(source.intent.context_ref.get("localUnitRun"), context_ref.get("localUnitRun"))
                or not _same(source.intent.context_ref.get("privateRootFacts"), context_ref.get("privateRootFacts"))
                or not _same(source.intent.context_ref.get("directoryBindingRef"), context_ref.get("directoryBindingRef"))
                or not _same(source.intent.context_ref.get("harnessDefinitionRef"), context_ref.get("harnessDefinitionRef"))):
            raise UnitRecordsRefused("receipt query lost its exact published LocalUnitOwner source")
        return reservation

    def _provider(self, ref, *, cleanup, definition_ref=None):
        if not isinstance(definition_ref, Mapping):
            raise UnitRecordsRefused("original Harness definition reference required")
        admitted = (self.harness_catalog.describe_for_cleanup(definition_ref, ref)
                    if cleanup else self.harness_catalog.describe(definition_ref))
        pinned = getattr(admitted, "provider_ref", None)
        if not isinstance(pinned, Mapping) or not _same(pinned, ref):
            raise UnitRecordsRefused("active Harness provider pin differs")
        try:
            active = _same(
                getattr(self.harness_catalog.describe(definition_ref), "provider_ref", None), ref
            )
        except Exception:
            active = False
        if not cleanup and not active:
            raise UnitRecordsRefused("Harness provider is not currently active")
        return pinned, active

    def _unit_for_node(self, node_ref):
        records, manager = self._require_owner()
        owned = getattr(manager, "_units", None)
        if not isinstance(owned, dict):
            raise UnitRecordsRefused("original Unit Manager ownership map is unavailable")
        matches = []
        # Do not call references()/find() here: Manager.start holds its lock
        # across the SDK callback which invokes this state inspector.
        for entry in tuple(owned.copy().values()):
            if type(entry) is not tuple or len(entry) != 2:
                raise UnitRecordsRefused("original Unit Manager entry is malformed")
            instance, ref = entry
            if (not isinstance(ref, Mapping)
                    or not isinstance(ref.get("unitId"), str)
                    or getattr(instance, "records", None) is not records
                    or getattr(instance, "_verifier", None) is not manager.verifier
                    or records.verifier is not manager.verifier):
                raise UnitRecordsRefused("original Unit handle/records/verifier binding changed")
            reservation = records.owner_read_unit(ref["unitId"])
            if _same(reservation.facts.get("nodeRef"), node_ref):
                instance._unit_record(ref)
                self._verify_reservation_source(reservation, node_ref)
                if owned.get(ref["unitId"]) is not entry:
                    raise UnitRecordsRefused("original Unit handle changed during state inspection")
                matches.append((ref, reservation, instance))
        if len(matches) > 1:
            raise UnitRecordsRefused("node owns multiple live Unit reservations")
        return matches[0] if matches else None

    def _verify_reservation_source(self, reservation, node_ref):
        facts = reservation.facts
        try:
            correlation = json.loads(facts["correlation"])
            request_fields = correlation["request"]
            request = RequestKey(request_fields["environmentNamespace"],
                                 request_fields["principalScope"],
                                 request_fields["requestId"])
            operation = self.store.read_operation(request)
            if operation is None:
                raise ValueError()
            context = operation.intent.context_ref
            if (correlation.get("operationRef") != operation.intent.operation_ref
                    or not _same(context.get("nodeRef"), node_ref)
                    or not _same(context.get("privateRootFacts"), facts["privateRootFacts"])
                    or not _same(context.get("localUnitRun", {}).get("ownerId"), self.owner_id)
                    or not _same(facts.get("providerRef"), operation.intent.steps[0].pinned_provider_ref)
                    or facts.get("managementEpoch") != context.get("localUnitRun", {}).get("environmentGeneration")):
                raise ValueError()
        except Exception:
            raise UnitRecordsRefused("Unit reservation lost its exact original operation source") from None
        return operation

    def _live_use(self, unit, *, cleanup=False):
        factory = getattr(unit, "channel_factory", None)
        use = getattr(factory, "environment", None)
        if use is None:
            raise UnitRecordsRefused("original acquired Environment Use handle is unavailable")
        check = getattr(use, "check", None)
        if not callable(check):
            raise UnitRecordsRefused("Environment Use does not expose its owner check")
        snapshot = self._snapshot()
        check(self.environment_instance.identity, snapshot.generation, allow_unknown=cleanup)
        return use

    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        """Return only facts re-derived from the exact original operation."""
        try:
            historical_query = action == "query"
            if action not in {"prepare", "start", "stop", "release", "query"}:
                return None
            node = self._node(target_ref)
            resolved = self._operation_context(request, context_ref, node,
                                               historical_query=historical_query)
            if resolved is None:
                return None
            operation, local, roots = resolved
            if historical_query:
                read = context_ref.get("acpTurnRead")
                if (operation.intent.kind != "unit-acp-query"
                        or not isinstance(read, Mapping)
                        or set(read) != {"unitRef", "operationRef", "expectedPromptInputDigest"}):
                    return None
            step_id = "read" if historical_query else action
            binding = context_ref.get("invocationBindings", {}).get(step_id)
            if (not isinstance(binding, Mapping)
                    or binding.get("action") != action
                    or not _same(binding.get("targetRef"), node)
                    or binding.get("delegationRef") is not None
                    or binding.get("cleanup") is not (historical_query or action in {"stop", "release"})):
                return None
            step = next((item for item in operation.intent.steps if item.step_id == step_id), None)
            if (step is None or not _same(step.pinned_provider_ref, pinned_provider_ref)
                    or operation.intent.node_ref is None
                    or not _same(operation.intent.node_ref, node)):
                return None
            if operation.status in {"unknown", "refused", "cancelled", "published"}:
                return None
            definition_ref = context_ref.get("harnessDefinitionRef")
            if not isinstance(definition_ref, Mapping):
                return None
            if historical_query:
                reservation = self._query_reservation(context_ref, node, pinned_provider_ref)
                acquired_target, evidence_ref = node, reservation.public_ref
                # Cold reads use the immutable provider pin on the original Unit
                # row; they do not reactivate a provider or require its runtime.
                provider_active = False
                snapshot = self._snapshot_generation()
            else:
                acquired = self._unit_for_node(node)
                _pinned_provider, provider_active = self._provider(
                    pinned_provider_ref,
                    cleanup=action in {"stop", "release"},
                    definition_ref=definition_ref,
                )
                snapshot = self._snapshot()
            if snapshot.generation != local["environmentGeneration"]:
                return None
            directory = DirectoryBindingRef.from_dict(dict(context_ref["directoryBindingRef"]))
            epoch_key = safe_json(node)
            with self._lock:
                self._epochs[epoch_key] = (request, _digest(context_ref), snapshot.generation)
            if not historical_query:
                acquired_target = evidence_ref = None
                if action == "prepare":
                    if acquired is not None:
                        return None
                else:
                    if acquired is None:
                        return None
                    ref, reservation, unit = acquired
                    facts = reservation.facts
                    if (facts.get("providerRef") != pinned_provider_ref
                            or facts.get("managementEpoch") != local["environmentGeneration"]
                            or not _same(facts.get("privateRootFacts"), roots)):
                        return None
                    records, _manager = self._require_owner()
                    stop = records.owner_read_termination(reservation.unit_ref, "stop")
                    release = records.owner_read_termination(reservation.unit_ref, "release")
                    if action in {"prepare", "start"} and (stop is not None or release is not None):
                        return None
                    if action == "stop" and (stop is not None or release is not None):
                        return None
                    if action == "release" and (release is not None
                            or stop is not None and stop.get("state") != "confirmed"):
                        return None
                    self._live_use(unit, cleanup=action in {"stop", "release"})
                    acquired_target = node
                    evidence_ref = reservation.public_ref
            return InvocationCurrentState(
                provider_ref=sealed_mapping(pinned_provider_ref),
                provider_active=provider_active,
                management_epoch=snapshot.generation,
                directory_binding_ref=directory,
                directory_permitted=True,
                acquired_target_ref=acquired_target,
                acquisition_evidence_ref=evidence_ref,
            )
        except Exception:
            return None

    def check_interaction(self, instance, context):
        """Revalidate the exact attached Unit, confirmed session, and live Use."""
        try:
            if not isinstance(context, Mapping):
                return False
            node = self._node(context.get("nodeRef"))
            resolved = self._unit_for_node(node)
            if resolved is None or resolved[2] is not instance:
                return False
            _ref, reservation, unit = resolved
            source = self._verify_reservation_source(reservation, node)
            if not _same(source.intent.context_ref, context):
                return False
            stored = reservation.facts
            local = context.get("localUnitRun")
            snapshot = self._snapshot()
            if (not isinstance(local, Mapping)
                    or local.get("ownerId") != self.owner_id
                    or local.get("permissionId") != self.permission_id
                    or local.get("environmentIdentity") != self.environment_instance.identity
                    or local.get("environmentGeneration") != snapshot.generation
                    or local.get("agentId") != self.agent_id
                    or not _same(local.get("profileRevision"), encode_revision_ref(self.profile_revision))
                    or not _same(stored.get("privateRootFacts"), context.get("privateRootFacts"))
                    or not _same(context.get("harnessDefinitionRef"), instance.descriptor.definition_ref)):
                return False
            self._provider(stored["providerRef"], cleanup=False,
                           definition_ref=context.get("harnessDefinitionRef"))
            self._live_use(unit)
            session = self._records.owner_read_session(reservation.unit_ref)
            if (self._records.owner_read_termination(reservation.unit_ref, "stop") is not None
                    or self._records.owner_read_termination(reservation.unit_ref, "release") is not None):
                return False
            record = unit.channel_factory.owned_record
            return bool(session.state == "confirmed" and record is not None
                        and record.process.observe().state == "running" and record.channel is not None)
        except Exception:
            return False

    def current_epoch(self, node_ref):
        node = self._node(node_ref)
        key = safe_json(node)
        with self._lock:
            binding = self._epochs.get(key)
        if binding is None:
            raise UnitRecordsRefused("current Environment generation was not resolved from an original operation")
        request, context_digest, generation = binding
        operation = self.store.read_operation(request)
        if (operation is None or _digest(operation.intent.context_ref) != context_digest
                or not _same(operation.intent.context_ref.get("nodeRef"), node)):
            raise UnitRecordsRefused("original operation no longer binds this management epoch")
        bindings = operation.intent.context_ref.get("invocationBindings", {})
        historical_query = (isinstance(bindings, Mapping)
                            and isinstance(bindings.get("read"), Mapping)
                            and bindings["read"].get("action") == "query"
                            and bindings["read"].get("cleanup") is True)
        snapshot = self._snapshot_generation() if historical_query else self._snapshot()
        if snapshot.generation != generation:
            raise UnitRecordsRefused("fixed Environment generation changed")
        if not historical_query:
            acquired = self._unit_for_node(node)
            if acquired is not None:
                unit = acquired[2]
                cleanup_action = next((name for name, binding in bindings.items()
                                       if name in {"stop", "release"}
                                       and isinstance(binding, Mapping)
                                       and binding.get("action") == name
                                       and _same(binding.get("targetRef"), node)
                                       and binding.get("cleanup") is True), None)
                self._live_use(unit, cleanup=cleanup_action in {"stop", "release"})
        return generation


