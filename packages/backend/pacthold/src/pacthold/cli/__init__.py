"""Thin command-line entry point for the kernel Core and installed plugins.

specs/010 T009: the kernel CLI carries only mechanism subcommands (plugin
inspection and a provider-neutral readiness doctor).  The Web Workbench
launcher subcommands and the Web-aware doctor live in the compatibility
assembly's CLI (``pacthold_runtime_compat.cli``).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .. import __version__
from ..work_core.runtime import DISPLAY_NAME, agent_box_home


PROG = DISPLAY_NAME


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Pacthold work core and plugin host.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command")
    parser.set_defaults(func=cmd_help)

    p_doctor = sub.add_parser("doctor", help="Check kernel readiness")
    p_doctor.add_argument("--json", action="store_true", dest="as_json")
    p_doctor.set_defaults(func=cmd_doctor)

    p_plugins = sub.add_parser(
        "plugins", help="Inspect installed third-party Agent-Box plugins"
    )
    plugins_sub = p_plugins.add_subparsers(dest="plugins_command", required=True)
    p_plugins_list = plugins_sub.add_parser("list", help="List plugin load status")
    p_plugins_list.add_argument("--json", action="store_true", dest="as_json")
    p_plugins_list.set_defaults(func=cmd_plugins_list)

    p_plugins_inspect = plugins_sub.add_parser("inspect", help="Inspect one plugin")
    p_plugins_inspect.add_argument("plugin_id")
    p_plugins_inspect.add_argument("--json", action="store_true", dest="as_json")
    from .commands.plugins import cmd_plugins_inspect, cmd_plugins_doctor
    p_plugins_inspect.set_defaults(func=cmd_plugins_inspect)
    p_plugins_doctor = plugins_sub.add_parser("doctor", help="Diagnose plugin structure")
    p_plugins_doctor.add_argument("plugin_id", nargs="?")
    p_plugins_doctor.add_argument("--json", action="store_true", dest="as_json")
    p_plugins_doctor.set_defaults(func=cmd_plugins_doctor)

    return parser


def cmd_help(_args: argparse.Namespace) -> int:
    print(f"{PROG}: use `pacthold plugins list` to inspect installed plugins")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from shutil import which
    from ..extensions.bootstrap import build_extension_registry
    checks = {"AGENT_BOX_HOME": str(agent_box_home()), "git": bool(which("git"))}
    try:
        registry, report = build_extension_registry(strict=False)
        checks["plugin_registry"] = not bool(report.failed)
        checks["execution_providers"] = len(registry.descriptors()) > 0
    except Exception:
        checks["plugin_registry"] = False
        checks["execution_providers"] = False
    if args.as_json:
        print(json.dumps(checks, ensure_ascii=False, sort_keys=True))
    else:
        for key, value in checks.items(): print(f"{key}: {'ok' if value else 'missing'}")
    # Providers are optional distributions.  They are reported for
    # diagnostics, but only the registry path decides health; a kernel-only
    # installation remains valid.
    healthy = checks.get("plugin_registry", False)
    return 0 if healthy else 1


def cmd_plugins_list(args: argparse.Namespace) -> int:
    from ..extensions.bootstrap import build_extension_registry

    _registry, report = build_extension_registry(strict=False)
    rows = []
    for record in report.records:
        descriptor = record.descriptor
        registration = record.registration
        rows.append(
            {
                "entry_point": record.entry_point,
                "id": descriptor.id if descriptor else None,
                "display_name": descriptor.display_name if descriptor else None,
                "version": descriptor.version if descriptor else None,
                "api_version": descriptor.api_version if descriptor else None,
                "status": record.status,
                "contracts": sorted(
                    contract.contract_id for contract in registration.contracts
                ) if registration else [],
                "resource_providers": sorted(
                    provider.descriptor().id
                    for provider in registration.resource_providers
                ) if registration else [],
                "execution_providers": sorted(
                    provider.descriptor().id
                    for provider in registration.execution_providers
                ) if registration else [],
                "error": record.error,
                "distribution_name": record.distribution_name,
                "distribution_version": record.distribution_version,
            }
        )
    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
    elif not rows:
        print("No third-party Agent-Box plugins discovered.")
    else:
        for row in rows:
            identity = row["id"] or row["entry_point"]
            version = f" {row['version']}" if row["version"] else ""
            print(f"{row['status']:<12} {identity}{version}")
            if row["error"]:
                print(f"  {row['error']}")
    return 1 if any(row["status"] != "READY" for row in rows) else 0


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
