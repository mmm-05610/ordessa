"""Contribution batches, the registration handle, and the per-runtime
in-process registry (C1, specs/010 T004).

``CoreRegistry`` is a real registration mechanism but *instance-scoped*: one
registry belongs to one ``CoreRuntime`` and never to the process (FR-001).
It deliberately does not import ``work_core.registry`` — that module's
package chain pulls ``resource_contracts`` into the public facade.  The
staging pattern follows the ``ExtensionRegistry.register_components``
precedent: validate first, reserve ids, publish by whole-batch swap, so a
failed stage leaves the registry exactly as before (zero leak).

Visibility rules (contract: "宿主冻结激活期间请求接纳，禁止半发布被消费"):

* a staged batch reserves its ids immediately (two owners can never both
  stage the same id) but publishes nothing until ``commit``;
* ``commit`` makes the entire batch visible in one swap and is idempotent;
* ``rollback`` only undoes *unused* staged batches and is idempotent; a
  committed batch may already be consumed by dispatch, so it must be removed
  through ``CoreRuntime.unregister`` — rollback then refuses with a typed
  ``BatchAlreadyUsedError``;
* ``unregister`` removes exactly one owner's active batch.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from functools import wraps
from threading import RLock

from .descriptors import ResourceProviderDescriptor, validate_component_id, validate_contract_id
from .errors import (
    BatchAlreadyUsedError,
    CoreDTOError,
    CoreError,
    MissingContractReferenceError,
    OwnerNotRegisteredError,
    RegistrationConflictError,
)
from .resource_admission import MaterialContractError, MaterialCapability, snapshot_material_capability

_PROVIDER_METHODS = ("describe", "acquire", "release", "reconcile")
_EXECUTION_METHODS = ("start", "observe", "stop")


def _snapshot_resource_descriptor(descriptor: ResourceProviderDescriptor) -> ResourceProviderDescriptor:
    """Copy even frozen/subclass descriptors so the provider retains no alias."""
    return ResourceProviderDescriptor(
        descriptor.id, descriptor.display_name, descriptor.version, descriptor.reconcile_support)


def _mutation(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            if self._mutating:
                raise CoreDTOError("registry mutation cannot reenter author callbacks")
            self._mutating = True
            try:
                return method(self, *args, **kwargs)
            finally:
                self._mutating = False
    return invoke


def _query(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return invoke


@dataclass(frozen=True)
class CoreContributionSet:
    """The C1 payload: exactly contracts/resource_providers/execution_providers."""

    contracts: tuple[type, ...] = ()
    resource_providers: tuple[object, ...] = ()
    execution_providers: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        for name in ("contracts", "resource_providers", "execution_providers"):
            value = getattr(self, name)
            if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
                raise CoreDTOError(f"{name} must be a sequence, got {value!r}")
            object.__setattr__(self, name, tuple(value))
        for contract in self.contracts:
            _validate_contract(contract)
        for provider in self.resource_providers:
            _validate_provider_shape(provider, _PROVIDER_METHODS, "resource")
        for provider in self.execution_providers:
            _validate_provider_shape(provider, _EXECUTION_METHODS, "execution")



def _validate_contract(contract: object) -> None:
    if not isinstance(contract, type):
        raise CoreDTOError("resource contract must be a Python type")
    try:
        validate_contract_id(getattr(contract, "contract_id", None))
    except CoreError as exc:
        raise CoreDTOError(f"invalid resource contract: {exc}") from exc
    if not dataclasses.is_dataclass(contract) or not contract.__dataclass_params__.frozen:
        raise CoreDTOError("resource contract must be a frozen dataclass")


def _validate_provider_shape(provider: object, methods: tuple[str, ...], kind: str) -> None:
    missing = [name for name in methods if not callable(getattr(provider, name, None))]
    if missing:
        raise CoreDTOError(
            f"{kind} provider {provider!r} does not satisfy the C1 protocol; "
            f"missing: {', '.join(missing)}"
        )


_CONFIGURATION_ROUTES_MISSING = object()


def _snapshot_configuration_routes(provider: object):
    """Validate the optional ``configuration_routes`` mount (freeze §1).

    Absence means no configuration contribution — never guessed or filled.
    A present mount must be exactly ``tuple[ConfigurationRoute, ...]``; each
    item is reconstructed so the frozen ``ConfigurationRoute`` contract
    re-runs and the registry retains no alias into author state. Anything
    else — unreadable attribute, wrong container, wrong item type, invalid
    route — is a typed ``CoreDTOError``.
    """
    from .configuration_admission import ConfigurationRoute
    try:
        declared = getattr(provider, "configuration_routes", _CONFIGURATION_ROUTES_MISSING)
    except Exception:
        raise CoreDTOError("RuntimeProvider configuration_routes is unreadable") from None
    if declared is _CONFIGURATION_ROUTES_MISSING:
        return None
    if type(declared) is not tuple:
        raise CoreDTOError(
            "RuntimeProvider configuration_routes must be a tuple of ConfigurationRoute"
        )
    routes = []
    for item in declared:
        if type(item) is not ConfigurationRoute:
            raise CoreDTOError(
                "RuntimeProvider configuration_routes must be a tuple of ConfigurationRoute"
            )
        try:
            routes.append(ConfigurationRoute(item.configuration_kind, item.schema_version,
                                             item.definition_refs, item.actions,
                                             item.field_claims))
        except (TypeError, ValueError):
            raise CoreDTOError(
                "RuntimeProvider configuration_routes contains an invalid route"
            ) from None
    return tuple(routes)


@dataclass(frozen=True)
class CoreRegistrySnapshot:
    """Read-only view of the *active* (committed) registration state."""

    contract_ids: tuple[str, ...] = ()
    resource_provider_ids: tuple[str, ...] = ()
    execution_provider_ids: tuple[str, ...] = ()
    agent_runtime_provider_ids: tuple[str, ...] = ()


class _Batch:
    """Internal reservation record for one staged/committed contribution set."""

    __slots__ = ("owner", "contributions", "contract_ids", "resource_ids",
                 "resource_descriptors", "resource_supported_contract_ids",
                 "resource_material_capabilities",
                 "execution_ids", "agent_runtime_ids", "agent_runtime_descriptors",
                 "configuration_provider_ids", "configuration_routes", "state")

    def __init__(self, owner: str, contributions: CoreContributionSet) -> None:
        self.owner = owner
        self.contributions = contributions
        self.contract_ids: tuple[str, ...] = ()
        self.resource_ids: list[str] = []
        self.resource_descriptors: list[ResourceProviderDescriptor] = []
        self.resource_supported_contract_ids: list[tuple[str, ...] | None] = []
        self.resource_material_capabilities: list[MaterialCapability | None] = []
        self.execution_ids: list[str] = []
        self.agent_runtime_ids: list[str] = []
        self.agent_runtime_descriptors: list[object] = []
        self.configuration_provider_ids: list[str] = []
        self.configuration_routes: list[tuple] = []
        self.state = "staged"  # staged -> committed | rolled_back | unregistered


class CoreRegistry:
    """Instance-scoped contract/provider registry with staged-batch safety."""

    def __init__(self) -> None:
        self._lock, self._mutating = RLock(), False
        self._contracts: dict[str, tuple[str, type]] = {}
        self._resource_providers: dict[
            str, tuple[str, object, ResourceProviderDescriptor, tuple[str, ...] | None,
                       MaterialCapability | None]
        ] = {}
        self._execution_providers: dict[str, tuple[str, object]] = {}
        self._agent_runtime_providers: dict[str, tuple[str, object, object]] = {}
        self._agent_runtime_configuration_routes: dict[str, tuple] = {}
        self._pending: list[_Batch] = []
        self._active: dict[str, list[_Batch]] = {}

    # -- queries -----------------------------------------------------------

    @_query
    def snapshot(self) -> CoreRegistrySnapshot:
        return CoreRegistrySnapshot(
            contract_ids=tuple(sorted(self._contracts)),
            resource_provider_ids=tuple(sorted(self._resource_providers)),
            execution_provider_ids=tuple(sorted(self._execution_providers)),
            agent_runtime_provider_ids=tuple(sorted(self._agent_runtime_providers)),
        )

    @_query
    def active_owners(self) -> frozenset[str]:
        return frozenset(self._active)

    # -- committed-lookup (used by the T008 dispatch surface) --------------

    @_query
    def resource_provider(self, provider_id: str) -> tuple[str, object] | None:
        """``(owner, provider)`` of the committed resource provider, or None.
        Only *committed* registrations are visible (staged publishes nothing)."""
        entry = self._resource_providers.get(provider_id)
        return None if entry is None else entry[:2]

    @_query
    def resource_provider_admission(self, provider_id: str):
        """Original C1 admission record, internal to Environment's metadata gate."""
        entry = self._resource_providers.get(provider_id)
        return None if entry is None else entry[:4]

    @_query
    def resource_provider_material_admission(self, provider_id: str):
        """Same-entry material admission snapshot; never a second index."""
        return self._resource_providers.get(provider_id)

    @_query
    def execution_provider(self, provider_id: str) -> tuple[str, object] | None:
        """``(owner, provider)`` of the committed execution provider, or None."""
        return self._execution_providers.get(provider_id)

    @_query
    def has_contract(self, contract_id: str) -> bool:
        """True when the contract is registered in this instance's registry."""
        return contract_id in self._contracts

    @_query
    def agent_runtime_provider(self, provider_id: str):
        """Committed host owner, payload and immutable admitted descriptor."""
        return self._agent_runtime_providers.get(provider_id)

    @_query
    def agent_runtime_configuration_routes(self, provider_id: str):
        """Committed configuration route declarations mounted on a runtime provider.

        Same registry entry family, same batch authority — never a second
        index. Providers without a ``configuration_routes`` mount have no
        entry (no contribution is ever guessed or filled).
        """
        return self._agent_runtime_configuration_routes.get(provider_id)

    # -- staging -----------------------------------------------------------

    @_mutation
    def stage(self, owner: str, contributions: CoreContributionSet) -> _Batch:
        """Validate one batch against the current claims; reserve ids;
        publish nothing.  Any typed failure leaves the registry untouched."""
        batch = _Batch(owner, contributions)

        claimed_contracts = set(self._contracts)
        claimed_resources = set(self._resource_providers)
        claimed_executions = set(self._execution_providers)
        claimed_agent_runtime = set(self._agent_runtime_providers)
        claimed_definitions = {tuple(item[2].definition_ref.items())
                               for item in self._agent_runtime_providers.values()}
        for pending in self._pending:
            claimed_contracts.update(pending.contract_ids)
            claimed_resources.update(pending.resource_ids)
            claimed_executions.update(pending.execution_ids)
            claimed_agent_runtime.update(pending.agent_runtime_ids)
            claimed_definitions.update(tuple(item.definition_ref.items())
                                       for item in pending.agent_runtime_descriptors)

        # 1. contract id validation + double-claim conflict
        contract_ids: list[str] = []
        for contract in contributions.contracts:
            contract_id = contract.contract_id
            if contract_id in claimed_contracts:
                holder = self._contracts.get(contract_id, ("a pending batch", None))[0]
                raise RegistrationConflictError(
                    f"contract {contract_id!r} already claimed by owner {holder!r}"
                )
            contract_ids.append(contract_id)
            claimed_contracts.add(contract_id)
        batch.contract_ids = tuple(contract_ids)

        available_contracts = set(self._contracts) | set(contract_ids)

        # 2. resource providers: descriptor shape, conflict, dependency integrity
        for provider in contributions.resource_providers:
            descriptor = provider.describe()
            if not isinstance(descriptor, ResourceProviderDescriptor):
                raise CoreDTOError(
                    "resource provider describe() must return a "
                    f"ResourceProviderDescriptor, got {descriptor!r}"
                )
            if descriptor.id in claimed_resources:
                raise RegistrationConflictError(
                    f"resource provider {descriptor.id!r} already registered or claimed"
                )
            claimed_resources.add(descriptor.id)
            batch.resource_ids.append(descriptor.id)
            supported_contracts = _check_supported_contracts(provider, descriptor.id, available_contracts)
            try:
                material_capability = snapshot_material_capability(provider)
            except MaterialContractError:
                raise CoreDTOError("resource provider material capability is invalid") from None
            batch.resource_descriptors.append(_snapshot_resource_descriptor(descriptor))
            batch.resource_supported_contract_ids.append(supported_contracts)
            batch.resource_material_capabilities.append(material_capability)

        # 3. execution providers: identity via descriptor()/provider_id,
        #    conflict, dependency integrity (same contract-reference rule)
        for provider in contributions.execution_providers:
            provider_id = None
            describe = getattr(provider, "describe", None)
            if callable(describe):
                value = describe()
                if isinstance(value, ResourceProviderDescriptor):
                    provider_id = value.id
            if provider_id is None:
                provider_id = getattr(provider, "provider_id", None)
            try:
                validate_component_id(provider_id, kind="provider")
            except CoreError as exc:
                raise CoreDTOError(
                    "execution provider must expose a valid descriptor().id or "
                    f"provider_id: {exc}"
                ) from exc
            if provider_id in claimed_executions:
                raise RegistrationConflictError(
                    f"execution provider {provider_id!r} already registered or claimed"
                )
            claimed_executions.add(provider_id)
            batch.execution_ids.append(provider_id)
            _check_supported_contracts(provider, provider_id, available_contracts)

        # Agent lifecycle providers use this same staged/publication authority.
        # No side registry or legacy execution-provider fallback is consulted.
        for provider in getattr(contributions, "agent_runtime_providers", ()):
            from .lifecycle import RUNTIME_METHODS, RuntimeProviderDescriptor
            if any(hasattr(provider, key) for key in ("owner", "owner_activation", "generation")):
                raise CoreDTOError("RuntimeProvider may not supply host ownership")
            _validate_provider_shape(provider, RUNTIME_METHODS, "Agent runtime")
            descriptor = getattr(provider, "descriptor", None)
            if type(descriptor) is not RuntimeProviderDescriptor:
                raise CoreDTOError("RuntimeProvider descriptor changed before staging")
            descriptor = descriptor.snapshot()
            definition_key = tuple(descriptor.definition_ref.items())
            if descriptor.provider_id in claimed_agent_runtime or definition_key in claimed_definitions:
                raise RegistrationConflictError("Agent RuntimeProvider id or exact definition already claimed")
            batch.agent_runtime_ids.append(descriptor.provider_id)
            batch.agent_runtime_descriptors.append(descriptor)
            claimed_agent_runtime.add(descriptor.provider_id)
            claimed_definitions.add(definition_key)

        # Configuration contributions ride this same staged batch (freeze §1/§2):
        # mounted route declarations are validated, keyed and reserved here.
        # Second pass so a route may acknowledge a Runtime definition staged
        # later in the same batch.
        configuration = [
            (provider_id, _snapshot_configuration_routes(provider))
            for provider_id, provider in zip(
                batch.agent_runtime_ids,
                getattr(contributions, "agent_runtime_providers", ()))
        ]
        configuration = [(provider_id, routes)
                         for provider_id, routes in configuration if routes]
        if configuration:
            runtime_definition_keys = {
                tuple(item[2].definition_ref.items())
                for item in self._agent_runtime_providers.values()}
            runtime_definition_keys.update(
                tuple(item.definition_ref.items())
                for item in batch.agent_runtime_descriptors)
            descriptors = dict(zip(batch.agent_runtime_ids, batch.agent_runtime_descriptors))
            claimed_configuration_keys = set()
            claimed_configuration_owners: dict[tuple, str] = {}
            for provider_id, routes in self._agent_runtime_configuration_routes.items():
                for route in routes:
                    claimed_configuration_keys.add(
                        (route.configuration_kind, route.schema_version))
                    for item in route.definition_refs:
                        claimed_configuration_owners[tuple(item.items())] = provider_id
            for pending in self._pending:
                for provider_id, routes in zip(pending.configuration_provider_ids,
                                               pending.configuration_routes):
                    for route in routes:
                        claimed_configuration_keys.add(
                            (route.configuration_kind, route.schema_version))
                        for item in route.definition_refs:
                            claimed_configuration_owners[tuple(item.items())] = provider_id
            staged_provider_ids: list[str] = []
            staged_routes: list[tuple] = []
            for provider_id, routes in configuration:
                environment = descriptors[provider_id].definition_ref["environmentNamespace"]
                seen_keys = set()
                for route in routes:
                    if route.environment_namespace != environment:
                        raise CoreDTOError(
                            "configuration route belongs to another Environment")
                    key = (route.configuration_kind, route.schema_version)
                    if key in seen_keys:
                        raise RegistrationConflictError(
                            "one provider declares the same configuration kind/schema twice")
                    if key in claimed_configuration_keys:
                        raise RegistrationConflictError(
                            "configuration kind/schema is already claimed in this Registry")
                    seen_keys.add(key)
                    claimed_configuration_keys.add(key)
                    for item in route.definition_refs:
                        definition_key = tuple(item.items())
                        if definition_key not in runtime_definition_keys:
                            raise RegistrationConflictError(
                                "configuration route declares a definition that no "
                                "RuntimeProvider in this Registry acknowledges")
                        holder = claimed_configuration_owners.get(definition_key)
                        if holder is not None and holder != provider_id:
                            raise RegistrationConflictError(
                                "one configuration definition is declared by routes "
                                "of two different providers")
                        claimed_configuration_owners[definition_key] = provider_id
                staged_provider_ids.append(provider_id)
                staged_routes.append(tuple(routes))
            batch.configuration_provider_ids = staged_provider_ids
            batch.configuration_routes = staged_routes

        # All checks passed against local copies: reserve as pending.
        self._pending.append(batch)
        return batch

    # -- publication -------------------------------------------------------

    @_mutation
    def commit(self, batch: _Batch) -> None:
        if batch.state == "committed":
            return  # the whole batch is already visible; re-commit is a no-op
        if batch.state != "staged":
            raise BatchAlreadyUsedError(
                f"batch of owner {batch.owner!r} is {batch.state}; only a staged batch commits"
            )
        # Validate all mutable author payloads before publishing any category.
        for admitted_id, contract in zip(batch.contract_ids, batch.contributions.contracts):
            _validate_contract(contract)
            if contract.contract_id != admitted_id:
                raise CoreDTOError("contract identity changed before publication")
        available_contracts = set(self._contracts) | set(batch.contract_ids)
        for provider_id, provider, admitted_descriptor, admitted_contracts, admitted_material in zip(
                batch.resource_ids, batch.contributions.resource_providers,
                batch.resource_descriptors, batch.resource_supported_contract_ids,
                batch.resource_material_capabilities):
            _validate_provider_shape(provider, _PROVIDER_METHODS, "resource")
            try:
                descriptor = provider.describe()
            except Exception as exc:
                raise CoreDTOError("resource provider descriptor unavailable before publication") from exc
            if not isinstance(descriptor, ResourceProviderDescriptor):
                raise CoreDTOError("resource provider descriptor changed before publication")
            descriptor = _snapshot_resource_descriptor(descriptor)
            if descriptor.id != provider_id or descriptor != admitted_descriptor:
                raise CoreDTOError("resource provider descriptor changed before publication")
            supported_contracts = _check_supported_contracts(
                provider, provider_id, available_contracts)
            if supported_contracts != admitted_contracts:
                raise CoreDTOError("resource provider supported contracts changed before publication")
            try:
                material_capability = snapshot_material_capability(provider)
            except MaterialContractError:
                raise CoreDTOError("resource provider material capability changed before publication") from None
            if material_capability != admitted_material:
                raise CoreDTOError("resource provider material capability changed before publication")
        for provider, descriptor in zip(getattr(batch.contributions, "agent_runtime_providers", ()),
                                        batch.agent_runtime_descriptors):
            if getattr(provider, "descriptor", None) != descriptor:
                raise CoreDTOError("RuntimeProvider descriptor changed before publication")
            from .lifecycle import RUNTIME_METHODS
            _validate_provider_shape(provider, RUNTIME_METHODS, "Agent runtime")
            if any(hasattr(provider, key) for key in ("owner", "owner_activation", "generation")):
                raise CoreDTOError("RuntimeProvider may not supply host ownership")
        admitted_configuration = dict(zip(batch.configuration_provider_ids,
                                         batch.configuration_routes))
        for provider_id, provider in zip(batch.agent_runtime_ids,
                                         getattr(batch.contributions, "agent_runtime_providers", ())):
            current_routes = _snapshot_configuration_routes(provider) or None
            if current_routes != admitted_configuration.get(provider_id):
                raise CoreDTOError(
                    "RuntimeProvider configuration routes changed before publication")
        for contract_id, contract in zip(batch.contract_ids, batch.contributions.contracts):
            self._contracts[contract_id] = (batch.owner, contract)
        for provider_id, provider, descriptor, supported_contracts, material_capability in zip(
                batch.resource_ids, batch.contributions.resource_providers,
                batch.resource_descriptors, batch.resource_supported_contract_ids,
                batch.resource_material_capabilities):
            self._resource_providers[provider_id] = (
                batch.owner, provider, descriptor, supported_contracts, material_capability)
        for provider_id, provider in zip(batch.execution_ids, batch.contributions.execution_providers):
            self._execution_providers[provider_id] = (batch.owner, provider)
        for provider_id, provider, descriptor in zip(batch.agent_runtime_ids,
                getattr(batch.contributions, "agent_runtime_providers", ()), batch.agent_runtime_descriptors):
            self._agent_runtime_providers[provider_id] = (batch.owner, provider, descriptor)
        for provider_id, routes in zip(batch.configuration_provider_ids,
                                       batch.configuration_routes):
            self._agent_runtime_configuration_routes[provider_id] = routes
        self._pending.remove(batch)
        self._active.setdefault(batch.owner, []).append(batch)
        batch.state = "committed"

    @_mutation
    def rollback(self, batch: _Batch) -> None:
        if batch.state == "rolled_back":
            return  # idempotent: undoing an already-undone unused batch is harmless
        if batch.state != "staged":
            raise BatchAlreadyUsedError(
                f"batch of owner {batch.owner!r} was committed and may already be "
                "consumed; remove it via CoreRuntime.unregister, never rollback"
            )
        self._pending.remove(batch)
        batch.state = "rolled_back"

    @_mutation
    def unregister(self, owner: str, *, batch: _Batch | None = None) -> _Batch:
        batches = self._active.get(owner, [])
        if not batches:
            raise OwnerNotRegisteredError(f"owner has no active batch: {owner!r}")
        if batch is None:
            if len(batches) != 1:
                raise CoreDTOError("retirement requires the exact activation batch")
            batch = batches[0]
        if not any(item is batch for item in batches):
            raise OwnerNotRegisteredError("activation batch is not owned by this registry")
        for key in batch.contract_ids:
            if self._contracts.get(key, (None,))[0] == owner:
                del self._contracts[key]
        for key in batch.resource_ids:
            if self._resource_providers.get(key, (None,))[0] == owner:
                del self._resource_providers[key]
        for key in batch.execution_ids:
            if self._execution_providers.get(key, (None,))[0] == owner:
                del self._execution_providers[key]
        for key in batch.agent_runtime_ids:
            if self._agent_runtime_providers.get(key, (None,))[0] == owner:
                del self._agent_runtime_providers[key]
                self._agent_runtime_configuration_routes.pop(key, None)
        batches.remove(batch)
        if not batches:
            del self._active[owner]
        batch.state = "unregistered"
        return batch


def _check_supported_contracts(
    provider: object, provider_id: str, available: set[str]
) -> tuple[str, ...] | None:
    """Dependency-reference integrity: every contract a provider declares
    (duck-typed ``supported_contract_ids``, work_core.provider precedent) must
    be in this same batch or already active.  No implicit contract choice."""
    declared = getattr(provider, "supported_contract_ids", None)
    if declared is None:
        return
    if not isinstance(declared, (frozenset, set, tuple, list)):
        raise CoreDTOError(
            f"provider {provider_id!r} supported_contract_ids must be a set of contract ids"
        )
    normalized = tuple(sorted(set(declared)))
    missing = sorted(set(normalized).difference(available))
    if missing:
        raise MissingContractReferenceError(
            f"provider {provider_id!r} declares contracts that are neither in "
            f"this batch nor active: {', '.join(missing)}"
        )
    return normalized


class CoreRegistration:
    """Handle over one staged batch: the only way to commit or rollback it.

    The handle carries no authority beyond its own batch; providers never
    receive the registry through it (contract: "provider 不获得整个注册表").
    """

    __slots__ = ("_registry", "_batch", "owner")

    def __init__(self, registry: CoreRegistry, batch: _Batch) -> None:
        self._registry = registry
        self._batch = batch
        self.owner = batch.owner

    @property
    def state(self) -> str:
        return self._batch.state

    def commit(self) -> None:
        """Publish the whole batch atomically; staged content becomes visible."""
        self._registry.commit(self._batch)

    def rollback(self) -> None:
        """Undo this batch while it is unused; idempotent once rolled back;
        typed refusal once committed (it may already be consumed)."""
        self._registry.rollback(self._batch)
