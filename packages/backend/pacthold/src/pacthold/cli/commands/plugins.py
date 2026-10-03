"""CLI handlers for the trusted Agent-Box plugin surface."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from ...extensions.conformance import check_plugin_conformance
from ...extensions.diagnostics import (
    DiagnosticSeverity,
    PluginDiagnostic,
    PluginDiagnosticReport,
    check_registration_conformance,
    diagnostic_json,
)
from ...extensions.bootstrap import build_extension_registry


def _record_report(record, context, registry=None) -> PluginDiagnosticReport:
    if record.status != "READY":
        return PluginDiagnosticReport((PluginDiagnostic(
            "loader.error", DiagnosticSeverity.ERROR,
            record.error or f"plugin status: {record.status}",
            record.descriptor.id if record.descriptor else None,
        ),))
    items = []
    if record.descriptor and record.distribution_version and record.descriptor.version != record.distribution_version:
        items.append(PluginDiagnostic(
            "version.mismatch", DiagnosticSeverity.WARNING,
            f"descriptor version {record.descriptor.version} differs from distribution version {record.distribution_version}",
            record.descriptor.id,
            remediation="align the package version and descriptor when publishing the next release",
        ))
    report = check_registration_conformance(
        record.registration, context, plugin_id=record.descriptor.id,
        descriptor=record.descriptor,
        available_contract_types=registry.contract_types() if registry else None,
    )
    diagnostics = list(items) + list(report.diagnostics)
    for control in (record.registration.host_controls if record.registration else ()):
        doctor = getattr(control, "doctor", None)
        if callable(doctor):
            result = doctor()
            if result.get("status") == "SandboxUnavailable":
                diagnostics.append(PluginDiagnostic(
                    "sandbox.unavailable", DiagnosticSeverity.WARNING,
                    result.get("error", "SandboxUnavailable"), record.descriptor.id,
                    remediation="use the fake/formal vertical or enable the host namespace capability",
                ))
    return PluginDiagnosticReport(tuple(diagnostics))


def _context_for(record):
    from ...extensions.loader import _context
    return _context(record.descriptor)


def _provider_data(registration):
    resources, executions = [], []
    if registration:
        for provider in registration.resource_providers:
            try:
                descriptor = provider.descriptor()
                resources.append({"id": descriptor.id, "display_name": descriptor.display_name,
                                  "version": descriptor.version,
                                  "supported_contract_ids": sorted(getattr(provider, "supported_contract_ids", ()))})
            except Exception as exc:
                resources.append({"error": f"{type(exc).__name__}: {exc}"})
        for provider in registration.execution_providers:
            try:
                descriptor = provider.descriptor()
                limits = provider.input_limits()
                capabilities = provider.capabilities()
                executions.append({"id": descriptor.id, "display_name": descriptor.display_name,
                                   "version": descriptor.version, "input_limits": dict(limits),
                                   "capabilities": dict(capabilities)})
            except Exception as exc:
                executions.append({"error": f"{type(exc).__name__}: {exc}"})
    return resources, executions


def _inspect_row(record, diagnostics=None):
    descriptor = record.descriptor
    registration = record.registration
    context = _context_for(record) if descriptor else None
    resources, executions = _provider_data(registration)
    row = {
        "entry_point": record.entry_point,
        "distribution_name": record.distribution_name,
        "distribution_version": record.distribution_version,
        "status": record.status,
        "error": record.error,
        "descriptor": None if descriptor is None else {
            "id": descriptor.id, "display_name": descriptor.display_name,
            "version": descriptor.version, "api_version": descriptor.api_version,
            "description": descriptor.description, "docs_url": descriptor.docs_url,
            "config_namespace": descriptor.config_namespace,
        },
        "contracts": sorted(c.contract_id for c in registration.contracts) if registration else [],
        "resource_providers": resources,
        "execution_providers": executions,
        "expected_config_path": str(Path(context.agent_box_home) / "plugins" / descriptor.config_namespace / "config.json") if context and descriptor.config_namespace else None,
        "diagnostics": diagnostic_json(diagnostics) if diagnostics else [],
    }
    return row


def _load_report():
    registry, report = build_extension_registry(strict=False)
    return registry, report


def cmd_plugins_inspect(args) -> int:
    _registry, report = _load_report()
    matches = [r for r in report.records if r.entry_point == args.plugin_id or (r.descriptor and r.descriptor.id == args.plugin_id)]
    if not matches:
        print(f"agent-box plugins inspect: unknown plugin: {args.plugin_id}", file=sys.stderr)
        return 2
    record = matches[0]
    diagnostics = _record_report(record, _context_for(record) if record.descriptor else None, _registry) if record.descriptor else PluginDiagnosticReport()
    row = _inspect_row(record, diagnostics)
    if args.as_json:
        print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{row['status']} {args.plugin_id}")
        print(f"  entry_point: {row['entry_point']}")
        print(f"  distribution: {row['distribution_name'] or '-'} {row['distribution_version'] or ''}".rstrip())
        print(f"  descriptor: {row['descriptor']}")
        print(f"  contracts: {', '.join(row['contracts']) or '-'}")
        print(f"  resource providers: {row['resource_providers']}")
        print(f"  execution providers: {row['execution_providers']}")
        print(f"  expected config: {row['expected_config_path'] or '-'}")
        print(diagnostics.format_text())
    return 0 if diagnostics.ok else 1


def cmd_plugins_doctor(args) -> int:
    _registry, report = _load_report()
    records = report.records if args.plugin_id is None else tuple(r for r in report.records if r.entry_point == args.plugin_id or (r.descriptor and r.descriptor.id == args.plugin_id))
    if not records:
        print(f"agent-box plugins doctor: unknown plugin: {args.plugin_id}", file=sys.stderr)
        return 2
    rows = []
    all_diags = []
    for record in records:
        diagnostics = _record_report(record, _context_for(record) if record.descriptor else None, _registry)
        all_diags.extend(diagnostics.diagnostics)
        rows.append(_inspect_row(record, diagnostics))
    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(f"{row['status']} {row['descriptor']['id'] if row['descriptor'] else row['entry_point']}")
            if row["diagnostics"]:
                print("  " + "\n  ".join(f"{d['severity']} {d['code']}: {d['message']}" for d in row["diagnostics"]))
    return 0 if not any(d.severity is DiagnosticSeverity.ERROR for d in all_diags) else 1
