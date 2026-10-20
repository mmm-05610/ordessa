"""Policy-gated metadata and exact-provider admission for Units materials."""
from __future__ import annotations

from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable
from ordessa_units.definitions.admission_identity import MaterialProviderActivationRef

from .material_contracts import (
    AdmittedMaterialProviderMetadata,
    AdmittedResourceProviderMetadata,
    MaterialContractError,
    snapshot_material_capability,
)


class MaterialAdmission:
    """Read admission evidence exclusively from the public Unit context/catalog."""

    def __init__(self, context):
        catalog = getattr(context, "material_catalog", None)
        if (catalog is None or not callable(getattr(catalog, "provider", None))
                or not callable(getattr(catalog, "_provider_pin", None))):
            raise UnitGuaranteeUnavailable("Units material catalog binding unavailable")
        namespace = getattr(context, "environment_namespace", None)
        if namespace is not None and namespace != getattr(catalog, "environment_namespace", None):
            raise UnitGuaranteeUnavailable("Units material catalog belongs to another Environment")
        self._context = context
        self._catalog = catalog

    def _lock(self):
        lock = getattr(self._context, "admission_lock", None)
        if lock is None:
            lock = self._catalog.admission_lock
        if not callable(getattr(lock, "__enter__", None)):
            raise UnitGuaranteeUnavailable("Units admission lock is unavailable")
        return lock

    def _check_open(self):
        check = getattr(self._context, "check_open", None)
        if not callable(check):
            check = getattr(self._context, "ensure_open", None)
        if callable(check):
            check()
            return
        if getattr(self._context, "closed", False):
            raise UnitGuaranteeUnavailable("Units admission context is closed")

    def _admit_resource_metadata_read(self):
        policy = getattr(self._context, "policy", None)
        principal = getattr(self._context, "principal_scope", None)
        namespace = getattr(self._context, "environment_namespace", None)
        if (policy is None or not isinstance(principal, str) or not principal
                or not isinstance(namespace, str) or not namespace
                or not callable(getattr(policy, "admit_object_access", None))):
            raise UnitGuaranteeUnavailable("ResourceProvider discovery policy is unavailable")
        try:
            admitted = policy.admit_object_access(
                principal, f"{namespace}:agents.resources", "read")
        except Exception:
            raise UnitAdmissionRefused("ResourceProvider discovery refused") from None
        if not admitted:
            raise UnitAdmissionRefused("ResourceProvider discovery refused")

    @staticmethod
    def _resource_metadata(pin: object) -> AdmittedResourceProviderMetadata:
        try:
            return AdmittedResourceProviderMetadata(
                owner_activation=pin.owner_activation,
                descriptor=pin.descriptor,
                supported_contract_ids=pin.supported_contract_ids,
            )
        except Exception:
            raise UnitAdmissionRefused("ResourceProvider metadata is unavailable") from None

    def _resource_provider_metadata_locked(self, provider_id: str, *, omit_inactive: bool):
        if type(provider_id) is not str or not provider_id:
            raise UnitAdmissionRefused("ResourceProvider identity is unavailable")
        pin = self._catalog._provider_pin(provider_id)
        if pin is None:
            if omit_inactive:
                return None
            raise UnitAdmissionRefused("ResourceProvider is not admitted in this Unit")
        try:
            methods = tuple(getattr(pin.provider, name, None)
                            for name in ("describe", "acquire", "release", "reconcile"))
            if any(not callable(method) for method in methods):
                raise ValueError("provider role changed")
            descriptor = pin.provider.describe()
            coverage = getattr(pin.provider, "supported_contract_ids", None)
            if coverage is None or not isinstance(coverage, (frozenset, set, tuple, list)):
                raise ValueError("coverage unavailable")
            coverage = tuple(sorted(set(coverage)))
            from ordessa_units.definitions.materials import ResourceProviderDescriptor
            if not isinstance(descriptor, ResourceProviderDescriptor):
                raise ValueError("descriptor unavailable")
            descriptor = ResourceProviderDescriptor(
                descriptor.id, descriptor.display_name, descriptor.version,
                descriptor.reconcile_support)
        except Exception:
            raise UnitAdmissionRefused("ResourceProvider metadata is unavailable or changed") from None
        if descriptor != pin.descriptor or coverage != pin.supported_contract_ids:
            raise UnitAdmissionRefused("ResourceProvider metadata changed after admission")
        metadata = self._resource_metadata(pin)
        return metadata

    def resource_provider_contribution(self, provider_id: str):
        with self._lock():
            self._check_open()
            self._admit_resource_metadata_read()
            return self._resource_provider_metadata_locked(provider_id, omit_inactive=False)

    def resource_provider_contributions(self):
        with self._lock():
            self._check_open()
            self._admit_resource_metadata_read()
            result = [self._resource_provider_metadata_locked(pin.descriptor.id, omit_inactive=True)
                      for pin in self._catalog.providers()]
            return tuple(item for item in result if item is not None)

    def _material_provider_metadata_locked(self, provider_id: str, *, omit_missing_capability: bool):
        if type(provider_id) is not str or not provider_id.strip():
            raise UnitAdmissionRefused("material provider identity is unavailable")
        pin = self._catalog._provider_pin(provider_id)
        if pin is None:
            if omit_missing_capability:
                return None
            raise UnitAdmissionRefused("material provider is not admitted in this Unit")
        if pin.capability is None:
            if omit_missing_capability:
                return None
            raise UnitGuaranteeUnavailable("authorized material capability is unavailable")
        resource_metadata = self._resource_provider_metadata_locked(
            provider_id, omit_inactive=omit_missing_capability)
        if resource_metadata is None:
            return None
        try:
            capability = snapshot_material_capability(pin.provider)
        except MaterialContractError:
            raise UnitAdmissionRefused("material provider capability changed after admission") from None
        if capability is None or capability != pin.capability:
            raise UnitAdmissionRefused("material provider capability changed after admission")
        return AdmittedMaterialProviderMetadata(resource_metadata, pin.capability)

    def material_provider_contribution(self, provider_id: str):
        with self._lock():
            self._check_open()
            self._admit_resource_metadata_read()
            return self._material_provider_metadata_locked(
                provider_id, omit_missing_capability=False)

    def material_provider_contributions(self):
        with self._lock():
            self._check_open()
            self._admit_resource_metadata_read()
            result = [self._material_provider_metadata_locked(
                pin.descriptor.id, omit_missing_capability=True)
                for pin in self._catalog.providers(material_only=True)]
            return tuple(item for item in result if item is not None)

    def _material_provider_for_operation(self, provider_id, contract_id,
                                         provider_version, owner_activation):
        """Return metadata and its exact pinned provider for one fixed step."""
        with self._lock():
            self._check_open()
            self._admit_resource_metadata_read()
            if (type(provider_id) is not str or not provider_id.strip()
                    or type(contract_id) is not str or not contract_id.strip()
                    or type(provider_version) is not str or not provider_version.strip()
                    or type(owner_activation) is not MaterialProviderActivationRef):
                raise UnitAdmissionRefused("fixed material provider identity is unavailable")
            metadata = self._material_provider_metadata_locked(
                provider_id, omit_missing_capability=False)
            pin = self._catalog._provider_pin(provider_id)
            if (pin is None or contract_id not in pin.supported_contract_ids
                    or pin.descriptor.version != provider_version
                    or pin.owner_activation != owner_activation
                    or metadata.resource_provider.owner_activation != owner_activation):
                raise UnitAdmissionRefused("material provider pin or contract changed")
            # The provider is the same object held by the catalog; no alias or
            # cross-layer forwarding object is introduced.
            return metadata, pin.provider
