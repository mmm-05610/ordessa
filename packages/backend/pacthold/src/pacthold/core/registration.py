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

from .descriptors import ResourceProviderDescriptor, validate_component_id, validate_contract_id
from .errors import (
    BatchAlreadyUsedError,
    CoreDTOError,
    CoreError,
    MissingContractReferenceError,
    OwnerNotRegisteredError,
    RegistrationConflictError,
)

_PROVIDER_METHODS = ("describe", "acquire", "release", "reconcile")
_EXECUTION_METHODS = ("start", "observe", "stop")


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


@dataclass(frozen=True)
class CoreRegistrySnapshot:
    """Read-only view of the *active* (committed) registration state."""

    contract_ids: tuple[str, ...] = ()
    resource_provider_ids: tuple[str, ...] = ()
    execution_provider_ids: tuple[str, ...] = ()


class _Batch:
    """Internal reservation record for one staged/committed contribution set."""

    __slots__ = ("owner", "contributions", "contract_ids", "resource_ids",
                 "execution_ids", "state")

    def __init__(self, owner: str, contributions: CoreContributionSet) -> None:
        self.owner = owner
        self.contributions = contributions
        self.contract_ids: tuple[str, ...] = ()
        self.resource_ids: list[str] = []
        self.execution_ids: list[str] = []
        self.state = "staged"  # staged -> committed | rolled_back | unregistered


class CoreRegistry:
    """Instance-scoped contract/provider registry with staged-batch safety."""

    def __init__(self) -> None:
        self._contracts: dict[str, tuple[str, type]] = {}
        self._resource_providers: dict[str, tuple[str, object]] = {}
        self._execution_providers: dict[str, tuple[str, object]] = {}
        self._pending: list[_Batch] = []
        self._active: dict[str, _Batch] = {}

    # -- queries -----------------------------------------------------------

    def snapshot(self) -> CoreRegistrySnapshot:
        return CoreRegistrySnapshot(
            contract_ids=tuple(sorted(self._contracts)),
            resource_provider_ids=tuple(sorted(self._resource_providers)),
            execution_provider_ids=tuple(sorted(self._execution_providers)),
        )

    def active_owners(self) -> frozenset[str]:
        return frozenset(self._active)

    # -- committed-lookup (used by the T008 dispatch surface) --------------

    def resource_provider(self, provider_id: str) -> tuple[str, object] | None:
        """``(owner, provider)`` of the committed resource provider, or None.
        Only *committed* registrations are visible (staged publishes nothing)."""
        return self._resource_providers.get(provider_id)

    def execution_provider(self, provider_id: str) -> tuple[str, object] | None:
        """``(owner, provider)`` of the committed execution provider, or None."""
        return self._execution_providers.get(provider_id)

    def has_contract(self, contract_id: str) -> bool:
        """True when the contract is registered in this instance's registry."""
        return contract_id in self._contracts

    # -- staging -----------------------------------------------------------

    def stage(self, owner: str, contributions: CoreContributionSet) -> _Batch:
        """Validate one batch against the current claims; reserve ids;
        publish nothing.  Any typed failure leaves the registry untouched."""
        batch = _Batch(owner, contributions)

        claimed_contracts = set(self._contracts)
        claimed_resources = set(self._resource_providers)
        claimed_executions = set(self._execution_providers)
        for pending in self._pending:
            claimed_contracts.update(pending.contract_ids)
            claimed_resources.update(pending.resource_ids)
            claimed_executions.update(pending.execution_ids)

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
            _check_supported_contracts(provider, descriptor.id, available_contracts)

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

        # All checks passed against local copies: reserve as pending.
        self._pending.append(batch)
        return batch

    # -- publication -------------------------------------------------------

    def commit(self, batch: _Batch) -> None:
        if batch.state == "committed":
            return  # the whole batch is already visible; re-commit is a no-op
        if batch.state != "staged":
            raise BatchAlreadyUsedError(
                f"batch of owner {batch.owner!r} is {batch.state}; only a staged batch commits"
            )
        for contract_id, contract in zip(batch.contract_ids, batch.contributions.contracts):
            self._contracts[contract_id] = (batch.owner, contract)
        for provider_id, provider in zip(batch.resource_ids, batch.contributions.resource_providers):
            self._resource_providers[provider_id] = (batch.owner, provider)
        for provider_id, provider in zip(batch.execution_ids, batch.contributions.execution_providers):
            self._execution_providers[provider_id] = (batch.owner, provider)
        self._pending.remove(batch)
        self._active[batch.owner] = batch
        batch.state = "committed"

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

    def unregister(self, owner: str) -> _Batch:
        batch = self._active.get(owner)
        if batch is None:
            raise OwnerNotRegisteredError(f"owner has no active batch: {owner!r}")
        for key, (o, _v) in list(self._contracts.items()):
            if o == owner:
                del self._contracts[key]
        for key, (o, _v) in list(self._resource_providers.items()):
            if o == owner:
                del self._resource_providers[key]
        for key, (o, _v) in list(self._execution_providers.items()):
            if o == owner:
                del self._execution_providers[key]
        del self._active[owner]
        batch.state = "unregistered"
        return batch


def _check_supported_contracts(provider: object, provider_id: str, available: set[str]) -> None:
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
    missing = sorted(set(declared).difference(available))
    if missing:
        raise MissingContractReferenceError(
            f"provider {provider_id!r} declares contracts that are neither in "
            f"this batch nor active: {', '.join(missing)}"
        )


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
