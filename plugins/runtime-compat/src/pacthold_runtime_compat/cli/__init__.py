"""Product CLI: the kernel plugin surface plus the Web Workbench launcher.

specs/010 T009: the ``web``/``launch`` subcommands and the Web-aware
readiness doctor moved out of ``pacthold.cli`` into this assembly; the
neutral plugin/doctor handlers are reused from the kernel unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List

from pacthold.cli import (
    PROG,
    cmd_plugins_list,
)
from pacthold.work_core.runtime import agent_box_home


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
    from pacthold.extensions.bootstrap import build_extension_registry
    from ..bootstrap import build_product_registry
    checks = {"AGENT_BOX_HOME": str(agent_box_home()), "git": bool(which("git"))}
    try:
        registry, report = build_extension_registry(
            strict=False, registry=build_product_registry()
        )
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


def cmd_help(_args: argparse.Namespace) -> int:
    print(f"{PROG}: use `pacthold web` to start the Local Web Workbench")
    return 0


def build_product_parser() -> argparse.ArgumentParser:
    from pacthold.cli.commands.plugins import (
        cmd_plugins_doctor,
        cmd_plugins_inspect,
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Pacthold work core and plugin host launcher.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s 0.1.0-runtime-compat",
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
    p_plugins_inspect.set_defaults(func=cmd_plugins_inspect)

    p_plugins_doctor = plugins_sub.add_parser("doctor", help="Diagnose plugin structure")
    p_plugins_doctor.add_argument("plugin_id", nargs="?")
    p_plugins_doctor.add_argument("--json", action="store_true", dest="as_json")
    p_plugins_doctor.set_defaults(func=cmd_plugins_doctor)

    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_product_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
