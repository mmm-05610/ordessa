#!/usr/bin/env python3
"""Emit a selected brand deployment using the Server's captured declarations.

Usage: generate-harness-deployment.py BRAND <original template arguments>.
This tool generates documents; it never starts a Harness or resolves secrets.
"""
from __future__ import annotations

import argparse
from functools import partial
import importlib
from typing import Sequence


# These are explicit application choices, not SDK defaults or discovered plugins.
TEMPLATES = {
    "codex": "ordessa_harness_codex.production",
    "claude-code": "ordessa_harness_claude_code.production",
    "dsh": "ordessa_harness_dsh.production",
    "hermes": "ordessa_harness_hermes.production",
    "kilo": "ordessa_harness_kilo.production",
    "opencode": "ordessa_harness_opencode.production",
    "pi": "ordessa_harness_pi.production",
    "qwen": "ordessa_harness_qwen.production",
}


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brand", choices=tuple(TEMPLATES))
    parser.add_argument("template_arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
    from ordessa_agents.harness.providers.declarations.capability_claims import capability_claims

    captured = capture_selected_harness_catalog()
    template = importlib.import_module(TEMPLATES[options.brand])
    return template.main(
        options.template_arguments,
        capabilities_for=partial(capability_claims, captured.registry),
    )


if __name__ == "__main__":
    raise SystemExit(main())
