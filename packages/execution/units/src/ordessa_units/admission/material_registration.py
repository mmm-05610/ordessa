"""Units-owned registration and retirement of resource/material providers.

The catalog stores only the provider's fixed metadata pin and the exact
provider object supplied by the Unit owner. It never invokes resource or
material effect methods.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from threading import RLock

from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable
from ordessa_units.definitions.admission_identity import MaterialProviderActivationRef
from ordessa_units.definitions.materials import ResourceProviderDescriptor

from .material_contracts import MaterialContractError, MaterialCapability, snapshot_material_capability


@dataclass(frozen=True)
class MaterialProviderMetadata:
    owner_activation: MaterialProviderActivationRef
    descriptor: ResourceProviderDescriptor
    supported_contract_ids: tuple[str, ...]
    capability: MaterialCapability | None


@dataclass(frozen=True)
class _ProviderPin:
    metadata: MaterialProviderMetadata
    provider: object

    @property
    def owner_activation(self):
        return self.metadata.owner_activation

    @property
    def descriptor(self):
        return self.metadata.descriptor

    @property
    def supported_contract_ids(self):
        return self.metadata.supported_contract_ids

    @property
    def capability(self):
        return self.metadata.capability


@dataclass
class _OwnerState:
    pins: tuple[_ProviderPin, ...]
    state: str
    holds: int = 0


class MaterialCatalog:
    """Authoritative Unit-local material provider registration catalog."""

    _RESOURCE_METHODS = ("describe", "acquire", "release", "reconcile")

    def __init__(self, environment_namespace: str, *, admission_lock=None,
                 retirement_guard=None):
        if type(environment_namespace) is not str or not environment_namespace:
            raise ValueError("environment namespace is required")
        if admission_lock is not None and not callable(getattr(admission_lock, "__enter__", None)):
            raise TypeError("admission_lock must be a context manager lock")
        if retirement_guard is not None and not callable(retirement_guard):
            raise TypeError("retirement_guard must be callable")
        self.environment_namespace = environment_namespace
        self.admission_lock = admission_lock if admission_lock is not None else RLock()
        self.retirement_guard = retirement_guard
        self._owners: dict[tuple[str, int], _OwnerState] = {}
        self._providers: dict[str, _ProviderPin] = {}
        self._closed = False
        self._registration_busy = False

    @contextmanager
    def _registration_change(self):
        with self.admission_lock:
            if self._registration_busy:
                raise UnitAdmissionRefused("material provider registration cannot reenter")
            self._registration_busy = True
            try:
                yield
            finally:
                self._registration_busy = False

    @staticmethod
    def _ref(environment: str, owner_id: str, generation: int) -> MaterialProviderActivationRef:
        try:
            return MaterialProviderActivationRef(environment, owner_id, generation)
        except (TypeError, ValueError):
            raise UnitAdmissionRefused("material provider owner identity is unavailable") from None

    @staticmethod
    def _coverage(provider: object) -> tuple[str, ...]:
        try:
            raw = getattr(provider, "supported_contract_ids", None)
        except Exception:
            raise UnitAdmissionRefused("ResourceProvider contract coverage is unavailable") from None
        if raw is None:
            raise UnitGuaranteeUnavailable("ResourceProvider contract coverage is undeclared")
        if not isinstance(raw, (frozenset, set, tuple, list)):
            raise UnitAdmissionRefused("ResourceProvider contract coverage is malformed")
        if any(type(item) is not str or not item for item in raw):
            raise UnitAdmissionRefused("ResourceProvider contract coverage is malformed")
        return tuple(sorted(set(raw)))

    @classmethod
    def _snapshot(cls, environment: str, owner_id: str, generation: int,
                  providers: tuple[object, ...], contract_ids: tuple[str, ...]) -> tuple[_ProviderPin, ...]:
        if type(providers) is not tuple or type(contract_ids) is not tuple:
            raise UnitAdmissionRefused("material provider registration must use immutable tuples")
        if any(type(item) is not str or not item for item in contract_ids):
            raise UnitAdmissionRefused("material contract identities are malformed")
        if tuple(sorted(set(contract_ids))) != contract_ids:
            raise UnitAdmissionRefused("material contract identities must be sorted and unique")
        owner = cls._ref(environment, owner_id, generation)
        pins: list[_ProviderPin] = []
        ids: set[str] = set()
        for provider in providers:
            try:
                methods = tuple(getattr(provider, name, None) for name in cls._RESOURCE_METHODS)
                if any(not callable(method) for method in methods):
                    raise UnitAdmissionRefused("ResourceProvider methods are unavailable")
                descriptor = provider.describe()
                coverage = cls._coverage(provider)
                capability = snapshot_material_capability(provider)
                if capability is not None:
                    # snapshot_material_capability already verifies the complete
                    # material method role and copies the fixed capability DTO.
                    pass
            except MaterialContractError:
                raise UnitAdmissionRefused("material provider capability is invalid") from None
            except UnitAdmissionRefused:
                raise
            except Exception:
                raise UnitAdmissionRefused("ResourceProvider metadata is unavailable") from None
            if not isinstance(descriptor, ResourceProviderDescriptor):
                raise UnitAdmissionRefused("ResourceProvider descriptor is malformed")
            try:
                descriptor = ResourceProviderDescriptor(
                    descriptor.id, descriptor.display_name,
                    descriptor.version, descriptor.reconcile_support)
            except Exception:
                raise UnitAdmissionRefused("ResourceProvider descriptor is malformed") from None
            if descriptor.id in ids:
                raise UnitAdmissionRefused("duplicate ResourceProvider identity")
            ids.add(descriptor.id)
            if not set(coverage).issubset(contract_ids):
                raise UnitAdmissionRefused("ResourceProvider references an unavailable contract")
            pins.append(_ProviderPin(
                MaterialProviderMetadata(owner, descriptor, coverage, capability), provider))
        return tuple(pins)

    def stage(self, owner_id: str, generation: int, providers: tuple,
              contract_ids: tuple[str, ...]) -> "MaterialRegistration":
        if type(owner_id) is not str or not owner_id or type(generation) is not int or generation < 0:
            raise UnitAdmissionRefused("material provider owner identity is unavailable")
        key = (owner_id, generation)
        with self._registration_change():
            if self._closed:
                raise UnitGuaranteeUnavailable("material catalog is closed")
            if key in self._owners:
                raise UnitAdmissionRefused("material provider owner generation already exists")
            if any(state.state == "pending" and state.pins and state.pins[0].owner_activation.plugin_id == owner_id
                   for state in self._owners.values()):
                raise UnitAdmissionRefused("material provider owner has a pending registration")
            pins = self._snapshot(self.environment_namespace, owner_id, generation, providers, contract_ids)
            existing_ids = set(self._providers)
            existing_ids.update(pin.descriptor.id for state in self._owners.values()
                                if state.state == "pending" for pin in state.pins)
            staged_ids = {pin.descriptor.id for pin in pins}
            if existing_ids.intersection(staged_ids):
                raise UnitAdmissionRefused("ResourceProvider identity is already registered")
            self._owners[key] = _OwnerState(pins, "pending")
            return MaterialRegistration(self, key, pins, providers, contract_ids)

    def _commit(self, registration: "MaterialRegistration") -> tuple[MaterialProviderMetadata, ...]:
        with self._registration_change():
            self._require_open()
            state = self._owners.get(registration.key)
            if state is None or state.state != "pending" or state.pins is not registration._pins:
                raise UnitAdmissionRefused("material provider registration is no longer pending")
            current = self._snapshot(self.environment_namespace, registration.key[0], registration.key[1],
                                     registration.providers, registration.contract_ids)
            if (len(current) != len(registration._pins)
                    or any(left.provider is not right.provider
                           or left.owner_activation != right.owner_activation
                           or left.descriptor != right.descriptor
                           or left.supported_contract_ids != right.supported_contract_ids
                           or left.capability != right.capability
                           for left, right in zip(current, registration._pins))):
                raise UnitAdmissionRefused("material provider metadata changed before publication")
            if set(self._providers).intersection(pin.descriptor.id for pin in current):
                raise UnitAdmissionRefused("ResourceProvider identity is already registered")
            state.state = "active"
            self._providers.update((pin.descriptor.id, pin) for pin in current)
            return tuple(pin.metadata for pin in current)

    def _rollback(self, registration: "MaterialRegistration") -> None:
        with self.admission_lock:
            state = self._owners.get(registration.key)
            if state is None or state.state != "pending" or state.pins is not registration._pins:
                raise UnitAdmissionRefused("only a pending material registration can be rolled back")
            del self._owners[registration.key]

    def provider(self, provider_id: str) -> MaterialProviderMetadata | None:
        with self.admission_lock:
            self._require_open()
            pin = self._providers.get(provider_id)
            if pin is None:
                return None
            state = self._owners.get((pin.owner_activation.plugin_id, pin.owner_activation.generation))
            if state is None or state.state != "active":
                return None
            return pin.metadata

    def _provider_pin(self, provider_id: str) -> _ProviderPin | None:
        """Internal exact-object lookup for MaterialAdmission only."""
        with self.admission_lock:
            self._require_open()
            pin = self._providers.get(provider_id)
            if pin is None:
                return None
            state = self._owners.get((pin.owner_activation.plugin_id, pin.owner_activation.generation))
            return pin if state is not None and state.state == "active" else None

    def providers(self, *, material_only: bool = False) -> tuple[MaterialProviderMetadata, ...]:
        with self.admission_lock:
            self._require_open()
            return tuple(pin.metadata for state in self._owners.values() if state.state == "active"
                         for pin in state.pins
                         if not material_only or pin.capability is not None)

    def drain(self, owner_id: str, generation: int) -> None:
        with self.admission_lock:
            self._require_open()
            state = self._owners.get((owner_id, generation))
            if state is None:
                raise UnitAdmissionRefused("unknown material provider owner")
            if state.state == "pending":
                raise UnitAdmissionRefused("pending material provider owner cannot drain")
            if state.state != "active":
                raise UnitAdmissionRefused("material provider owner is not active")
            state.state = "draining"

    def hold(self, owner_id: str, generation: int) -> None:
        with self.admission_lock:
            self._require_open()
            state = self._owners.get((owner_id, generation))
            if state is None or state.state != "active":
                raise UnitAdmissionRefused("material provider owner is not active")
            state.holds += 1

    def release_hold(self, owner_id: str, generation: int) -> None:
        with self.admission_lock:
            state = self._owners.get((owner_id, generation))
            if state is None or state.holds <= 0:
                raise UnitAdmissionRefused("material provider hold is unavailable")
            state.holds -= 1

    def retire(self, owner_id: str, generation: int) -> tuple[MaterialProviderMetadata, ...]:
        # The parent-owned authority check must run without the catalog lock.
        guard = self.retirement_guard
        if guard is None:
            raise UnitGuaranteeUnavailable("material provider retirement guard is unavailable")
        try:
            permit = guard(owner_id, generation)
            if not callable(getattr(permit, "__enter__", None)):
                raise UnitAdmissionRefused("material provider retirement guard is unavailable")
            with permit as result:
                if result is not None:
                    raise UnitAdmissionRefused("material provider retirement guard returned an invalid permit")
                with self.admission_lock:
                    self._require_open()
                    state = self._owners.get((owner_id, generation))
                    if state is None:
                        raise UnitAdmissionRefused("unknown material provider owner")
                    if state.state == "pending":
                        raise UnitAdmissionRefused("pending material provider owner cannot retire")
                    if state.state != "draining":
                        raise UnitAdmissionRefused("only a drained material provider owner can retire")
                    if state.holds:
                        raise UnitAdmissionRefused("material provider still has active holds")
                    del self._owners[(owner_id, generation)]
                    for pin in state.pins:
                        self._providers.pop(pin.descriptor.id, None)
                    return tuple(pin.metadata for pin in state.pins)
        except (UnitAdmissionRefused, UnitGuaranteeUnavailable):
            raise
        except Exception:
            raise UnitAdmissionRefused("material provider retirement was refused") from None

    def close(self) -> None:
        with self.admission_lock:
            self._require_open()
            if self._owners:
                raise UnitAdmissionRefused("material catalog cannot close with registered owners")
            self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise UnitGuaranteeUnavailable("material catalog is closed")


class MaterialRegistration:
    """One staged Units provider registration transaction."""

    def __init__(self, catalog: MaterialCatalog, key: tuple[str, int],
                 pins: tuple[_ProviderPin, ...], providers: tuple,
                 contract_ids: tuple[str, ...]):
        self._catalog = catalog
        self.key = key
        self._pins = pins
        self.providers = providers
        self.contract_ids = contract_ids
        self._finished = False

    def commit(self) -> tuple[MaterialProviderMetadata, ...]:
        if self._finished:
            raise UnitAdmissionRefused("material provider registration is already finished")
        result = self._catalog._commit(self)
        self._finished = True
        return result

    def rollback(self) -> None:
        if self._finished:
            raise UnitAdmissionRefused("material provider registration is already finished")
        self._catalog._rollback(self)
        self._finished = True
