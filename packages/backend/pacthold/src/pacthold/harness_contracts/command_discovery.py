"""Harness-owned PATH command candidates; presence grants no runtime guarantee.

Sources, checked by the product's build-time generator:
* src/ordessa_harness/harnesses.toml: identity.harness_type,
  executable.identity and launch_modes.argv[0] (native CLI definitions).
* third_party/harness_remote/bridge/src/harness-profiles.js:
  codex/pi/claude.adapterCommand (installed ACP adapter executable names).
* runtime/profile_extensions.mjs: claude-code/hermes/dsh/kilo/qwen command and
  adapterCommand literals, including their explicitly declared Windows names.

Those paths are source provenance, never client runtime dependencies. Generic
package runners such as npx are not Harness candidates. No version probe,
execution, credential access, model/session claim or plugin loading occurs.
"""
from __future__ import annotations

import hashlib
import json

HARNESS_COMMAND_CATALOG_VERSION = "harness-command-discovery/1"

_CANDIDATES = (
    ("claude-code", ("claude", "claude-agent-acp", "claude-agent-acp.cmd")),
    ("codex", ("codex", "codex-acp")),
    ("dsh", ("dsh", "dsh.cmd")),
    ("hermes", ("hermes", "hermes.exe")),
    ("kilo", ("kilo", "kilo.exe")),
    ("opencode", ("opencode",)),
    ("pi", ("pi", "pi-acp")),
    ("qwen", ("qwen", "qwen.cmd")),
)


def command_catalog() -> dict:
    """Return a fresh versioned candidate-name document, without capabilities."""
    return {"catalogVersion": HARNESS_COMMAND_CATALOG_VERSION,
            "candidates": [{"familyId": family, "commands": list(commands)}
                           for family, commands in _CANDIDATES]}


def command_catalog_digest() -> str:
    encoded = json.dumps(command_catalog(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def command_catalog_document() -> dict:
    """Return the public catalog plus its canonical content digest."""
    return {"catalog": command_catalog(), "catalogDigest": command_catalog_digest()}
