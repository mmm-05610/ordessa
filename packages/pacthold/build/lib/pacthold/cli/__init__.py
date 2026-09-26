"""Thin command-line entry point for Core diagnostics and installed Hosts."""
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
        description="Pacthold work core and plugin host launcher.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command")
    parser.set_defaults(func=cmd_help)

    p_web = sub.add_parser("web", help="Start the local Web Workbench Host")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=4173)
    p_web.add_argument("--no-browser", action="store_true")
    p_web.set_defaults(func=cmd_web)

    p_launch = sub.add_parser("launch", help="Open the Web Workbench Quick Launch")
    p_launch.add_argument("--host", default="127.0.0.1")
    p_launch.add_argument("--port", type=int, default=4173)
    p_launch.set_defaults(func=cmd_launch)

    p_doctor = sub.add_parser("doctor", help="Check local Web Host readiness")
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
    print(f"{PROG}: use `pacthold web` to start the Local Web Workbench")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    try:
        from agent_box_web.cli import run
    except ModuleNotFoundError as exc:
        if exc.name == "agent_box_web" or (exc.name and exc.name.startswith("agent_box_web.")):
            print(
                "pacthold web: Web Host is not installed; install with "
                "the Web Host is a separate distribution: `pip install agent-box-web`.",
                file=sys.stderr,
            )
            return 1
        raise
    return run(host=args.host, port=args.port, open_browser=not args.no_browser)


def cmd_launch(args: argparse.Namespace) -> int:
    try:
        from agent_box_web.cli import run
    except ModuleNotFoundError as exc:
        if exc.name == "agent_box_web" or (exc.name and exc.name.startswith("agent_box_web.")):
            print("pacthold launch: Web Host is not installed; install with the Web Host is a separate distribution: `pip install agent-box-web`.", file=sys.stderr)
            return 1
        raise
    return run(host=args.host, port=args.port, open_browser=True, initial_route="/quick-launch")


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
    try:
        from agent_box_web.cli import web_readiness
    except ModuleNotFoundError as exc:
        if exc.name == "agent_box_web" or (exc.name and exc.name.startswith("agent_box_web.")):
            checks.update({"web_plugin": False, "frontend_static_build": False, "frontend_static_dir": None})
        else:
            raise
    else:
        checks.update(web_readiness())
    if args.as_json:
        print(json.dumps(checks, ensure_ascii=False, sort_keys=True))
    else:
        for key, value in checks.items(): print(f"{key}: {'ok' if value else 'missing'}")
    # Providers and the Web Host are optional distributions.  They are
    # reported for diagnostics, but only an installed Web Host with missing
    # static data is unhealthy; a root-only installation remains valid.
    healthy = checks.get("plugin_registry", False)
    if checks.get("web_plugin"):
        healthy = healthy and checks.get("frontend_static_build", False)
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
