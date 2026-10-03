"""P0 structural conformance kit for trusted Agent-Box plugins."""
from __future__ import annotations

from typing import Mapping

from .api import PluginContext, PluginDescriptor
from .diagnostics import DiagnosticSeverity, PluginDiagnostic, PluginDiagnosticReport, check_registration_conformance


def check_plugin_conformance(
    plugin,
    context: PluginContext,
    *,
    available_contract_types: Mapping[str, type] | None = None,
) -> PluginDiagnosticReport:
    items: list[PluginDiagnostic] = []
    try:
        descriptor = plugin.descriptor()
    except Exception as exc:
        return PluginDiagnosticReport((PluginDiagnostic("descriptor.error", DiagnosticSeverity.ERROR, f"descriptor() failed: {type(exc).__name__}: {exc}"),))
    if not isinstance(descriptor, PluginDescriptor):
        return PluginDiagnosticReport((PluginDiagnostic("descriptor.type", DiagnosticSeverity.ERROR, "descriptor() must return PluginDescriptor"),))
    if descriptor.api_version != 1:
        items.append(PluginDiagnostic("descriptor.api_version", DiagnosticSeverity.ERROR, f"unsupported plugin API: {descriptor.api_version}", descriptor.id))
    try:
        registration = plugin.build(context)
    except Exception as exc:
        items.append(PluginDiagnostic("build.error", DiagnosticSeverity.ERROR, f"build() failed: {type(exc).__name__}: {exc}", descriptor.id))
        return PluginDiagnosticReport(tuple(items))
    report = check_registration_conformance(
        registration,
        context,
        plugin_id=descriptor.id,
        descriptor=descriptor,
        available_contract_types=available_contract_types,
    )
    return PluginDiagnosticReport(tuple(items) + report.diagnostics)


def assert_plugin_conforms(plugin, context: PluginContext) -> None:
    report = check_plugin_conformance(plugin, context)
    if not report.ok:
        raise AssertionError(report.format_text())


__all__ = ["check_plugin_conformance", "assert_plugin_conforms"]
