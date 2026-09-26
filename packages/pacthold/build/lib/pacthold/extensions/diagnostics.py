"""Small, side-effect-free diagnostics shared by CLI and plugin conformance."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ..work_core.registry import ExtensionRegistry, ProviderDescriptor
from .api import PLUGIN_API_VERSION, PluginDescriptor, PluginRegistration


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class PluginDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    plugin_id: str | None = None
    component: str | None = None
    remediation: str | None = None


@dataclass(frozen=True)
class PluginDiagnosticReport:
    diagnostics: tuple[PluginDiagnostic, ...] = ()

    @property
    def errors(self):
        return tuple(d for d in self.diagnostics if d.severity is DiagnosticSeverity.ERROR)

    @property
    def warnings(self):
        return tuple(d for d in self.diagnostics if d.severity is DiagnosticSeverity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors

    def format_text(self) -> str:
        if not self.diagnostics:
            return "OK"
        return "\n".join(
            f"{d.severity.value:<7} {d.code}: {d.message}"
            + (f" ({d.remediation})" if d.remediation else "")
            for d in self.diagnostics
        )


def _diag(items, code, severity, message, plugin_id=None, component=None, remediation=None):
    items.append(PluginDiagnostic(code, severity, message, plugin_id, component, remediation))


def _provider_descriptor(items, provider, plugin_id, kind):
    try:
        descriptor = provider.descriptor()
        if not isinstance(descriptor, ProviderDescriptor):
            raise TypeError("descriptor() did not return ProviderDescriptor")
        if not descriptor.id or not descriptor.version:
            raise ValueError("descriptor id/version is required")
        return descriptor
    except Exception as exc:
        _diag(items, "provider.descriptor", DiagnosticSeverity.ERROR,
              f"{kind} descriptor is invalid: {type(exc).__name__}: {exc}", plugin_id)
        return None


def check_registration_conformance(
    registration: Any,
    context,
    *,
    plugin_id: str | None = None,
    descriptor: PluginDescriptor | None = None,
    registry: ExtensionRegistry | None = None,
    available_contract_types: Mapping[str, type] | None = None,
) -> PluginDiagnosticReport:
    """Check structure only. This function never starts or resolves a provider."""
    items: list[PluginDiagnostic] = []
    if not isinstance(registration, PluginRegistration):
        _diag(items, "registration.type", DiagnosticSeverity.ERROR,
              "build() must return PluginRegistration", plugin_id)
        return PluginDiagnosticReport(tuple(items))
    fields_are_tuples = True
    for name in ("contracts", "resource_providers", "execution_providers", "finalization_contributors", "resource_selectors", "host_controls", "harness_managers", "continuation_routes", "credential_materializers"):
        if not isinstance(getattr(registration, name), tuple):
            fields_are_tuples = False
            _diag(items, "registration.tuple", DiagnosticSeverity.ERROR,
                  f"registration.{name} must be a tuple", plugin_id)

    seen: dict[str, str] = {}
    own_contracts = (
        registration.contracts
        if isinstance(registration.contracts, tuple)
        else ()
    )
    available = available_contract_types
    if available is None and registry is not None:
        available = registry.contract_types()
    target = ExtensionRegistry()
    own_ids = {getattr(contract, "contract_id", None) for contract in own_contracts}
    if available is not None:
        for contract_id, contract_type in available.items():
            if contract_id not in own_ids and contract_id not in target.contract_types():
                try:
                    target.register_contract(contract_type)
                except Exception as exc:
                    _diag(items, "contract.available", DiagnosticSeverity.ERROR,
                          f"available contract {contract_id!r} is invalid: {type(exc).__name__}: {exc}",
                          plugin_id, contract_id)
    if not fields_are_tuples:
        return PluginDiagnosticReport(tuple(items))
    for contract in registration.contracts:
        cid = getattr(contract, "contract_id", None)
        if not isinstance(cid, str):
            _diag(items, "contract.id", DiagnosticSeverity.ERROR, "contract_id is required", plugin_id)
            continue
        try:
            target._validate_contract_type(contract)
        except Exception as exc:
            _diag(items, "contract.invalid", DiagnosticSeverity.ERROR, str(exc), plugin_id, cid)
        if cid in seen:
            _diag(items, "duplicate.component", DiagnosticSeverity.ERROR, f"duplicate contract id: {cid}", plugin_id, cid)
        seen[cid] = "contract"

    for provider in registration.resource_providers:
        desc = _provider_descriptor(items, provider, plugin_id, "ResourceProvider")
        pid = desc.id if desc else None
        if pid and pid in seen:
            _diag(items, "duplicate.component", DiagnosticSeverity.ERROR, f"duplicate component id: {pid}", plugin_id, pid)
        if pid:
            seen[pid] = "resource_provider"
        supported = getattr(provider, "supported_contract_ids", None)
        if not isinstance(supported, frozenset):
            _diag(items, "resource.supported_contracts", DiagnosticSeverity.ERROR,
                  "supported_contract_ids must be frozenset", plugin_id, pid)
        else:
            known = set(target.contract_types()) | {getattr(c, "contract_id", "") for c in own_contracts}
            for cid in sorted(supported - known):
                _diag(items, "resource.unknown_contract", DiagnosticSeverity.ERROR,
                      f"ResourceProvider declares unknown contract: {cid}", plugin_id, pid)

    for provider in registration.execution_providers:
        desc = _provider_descriptor(items, provider, plugin_id, "ExecutionProvider")
        pid = desc.id if desc else None
        if pid and pid in seen:
            _diag(items, "duplicate.component", DiagnosticSeverity.ERROR, f"duplicate component id: {pid}", plugin_id, pid)
        if pid:
            seen[pid] = "execution_provider"
        try:
            limits = provider.input_limits()
            if not isinstance(limits, Mapping):
                raise TypeError("input_limits() must return a Mapping")
            known = set(target.contract_types()) | {getattr(c, "contract_id", "") for c in own_contracts}
            for cid, bounds in limits.items():
                if cid not in known:
                    _diag(items, "execution.unknown_contract", DiagnosticSeverity.ERROR,
                          f"input limit names unknown contract: {cid}", plugin_id, pid)
                if not isinstance(bounds, tuple) or len(bounds) != 2:
                    _diag(items, "execution.input_limits", DiagnosticSeverity.ERROR, "input limit must be (min, max)", plugin_id, pid)
                    continue
                low, high = bounds
                if not isinstance(low, int) or low < 0 or (high is not None and (not isinstance(high, int) or high < low)):
                    _diag(items, "execution.input_limits", DiagnosticSeverity.ERROR, "input limit must have non-negative min and max >= min", plugin_id, pid)
        except Exception as exc:
            _diag(items, "execution.input_limits", DiagnosticSeverity.ERROR, str(exc), plugin_id, pid)
        try:
            capabilities = provider.capabilities()
            if not isinstance(capabilities, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in capabilities.items()):
                raise TypeError("capabilities() must return Mapping[str, str]")
        except Exception as exc:
            _diag(items, "execution.capabilities", DiagnosticSeverity.ERROR, str(exc), plugin_id, pid)

    for kind, items_to_check, attr in (
        ("selector", registration.resource_selectors, "id"),
        ("contributor", registration.finalization_contributors, "id"),
        ("control", registration.host_controls, "provider_id"),
    ):
        component_ids: set[str] = set()
        for component in items_to_check:
            component_id = getattr(component, attr, None)
            if not isinstance(component_id, str) or not component_id:
                _diag(items, f"{kind}.id", DiagnosticSeverity.ERROR,
                      f"{kind} must declare a non-empty {attr}", plugin_id)
                continue
            if component_id in component_ids:
                _diag(items, "duplicate.component", DiagnosticSeverity.ERROR,
                      f"duplicate {kind} id: {component_id}", plugin_id, component_id)
            component_ids.add(component_id)

    if descriptor is not None:
        if descriptor.api_version != PLUGIN_API_VERSION:
            _diag(items, "descriptor.api_version", DiagnosticSeverity.ERROR, f"plugin API {descriptor.api_version} != host API {PLUGIN_API_VERSION}", plugin_id)
        if descriptor.docs_url is None:
            _diag(items, "descriptor.docs_url", DiagnosticSeverity.INFO, "plugin has no documentation URL", plugin_id)
        if descriptor.config_namespace:
            _diag(items, "config.expected_path", DiagnosticSeverity.INFO,
                  f"expected config path: {Path(context.agent_box_home) / 'plugins' / descriptor.config_namespace / 'config.json'}", plugin_id)
    try:
        target.register_components(contracts=registration.contracts,
                                   resource_providers=registration.resource_providers,
                                   execution_providers=registration.execution_providers)
    except Exception as exc:
        _diag(items, "registration.atomic", DiagnosticSeverity.ERROR,
              f"registration into a clean registry failed: {type(exc).__name__}: {exc}", plugin_id)
    return PluginDiagnosticReport(tuple(items))


def diagnostic_json(report: PluginDiagnosticReport) -> list[dict[str, Any]]:
    return [{"code": d.code, "severity": d.severity.value, "message": d.message,
             "plugin_id": d.plugin_id, "component": d.component, "remediation": d.remediation}
            for d in report.diagnostics]
