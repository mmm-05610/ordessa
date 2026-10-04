"""Pi native channel facts (N003, night-harness-expansion).

Family-owned, pinned L0 facts plus pure planning functions for the native
RPC channel. This module neither launches a subprocess nor touches any
managed-install file; the frozen transport continues to own the process
(`ProcessChannel`), and runtime composition stays with the existing
provider/composition ports of this package (no parallel registry here:
``FAMILY_ID = "pi"`` is the identity already registered in
``ordessa_harness.harnesses.toml`` and ``ProviderDescriptor("pi", ...)``).

All statements are pinned to a specific reviewed state (release 0.86.1,
docs read 2026-10-04, N001 L2 partial probe) and are never auto-upgraded
into claims about a newer binary or untested behaviour.
"""
from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Mapping

FAMILY_ID = "pi"

#: Pinned release (managed install ``install/current-version``, read 2026-10-04).
PINNED_RELEASE = "0.86.1"

#: First-hand artifact digest prefix (N001-vertical-entry.md). The full digest
#: stays pending until N003 recomputes it over the bundle; do not claim it.
PINNED_ARTIFACT_DIGEST_PREFIX = "e79626f2dd6f94aa45d30f3fa63cd84319a6eefc"

#: Isolation flags carried by every planned launch (N001 probe; G9/G12).
ISOLATION_FLAGS: tuple[str, ...] = (
    "--no-extensions",
    "--no-skills",
    "--no-context-files",
    "--no-prompt-templates",
    "--no-approve",
)

_LANG = "C.UTF-8"

#: Keys ``compile_config`` accepts (G3). Anything else is refused before any
#: launch — never silently dropped, never mapped to a guessed flag.
COMPILE_SUPPORTED_KEYS = frozenset(
    {"provider", "model", "thinking", "session_dir", "offline", "extensions"}
)

#: Known second-ownership / out-of-family native-config keys. Refusing these
#: is the G3 counter-example gate: the family reports refusal instead of the
#: shared engine silently swallowing the key.
COMPILE_REFUSAL_KEYS = frozenset({"mcpServers", "sandbox", "hotModelSwitch"})


class ConfigRefusal(ValueError):
    """Raised by ``compile_config`` for unsupported configuration keys (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    """L0 pin-board facts for the pi native RPC channel (seams.md §4).

    Every value is evidence-backed; unmeasured behaviour stays explicitly
    marked (``unknown`` / declared-not-observed) rather than asserted.
    """
    return {
        "family": FAMILY_ID,
        "channel": "native-rpc-jsonl",
        "upstream": {
            "repo": "github.com/earendil-works/pi",
            "package": "packages/coding-agent",
            "license": "MIT",
        },
        "release": {
            "version": PINNED_RELEASE,
            "source": "managed install install/current-version (0.86.1, 2026-10-04)",
            "volatile": True,  # re-pin and re-verify on upgrade (G1); not a protocol guarantee
        },
        "artifact": {
            "path": "dist/bundle/cli.js + chunks/",
            "sha256_prefix": PINNED_ARTIFACT_DIGEST_PREFIX,
            "sha256_full": "pending (full bundle digest to be recomputed; N001 note)",
        },
        "protocol": {
            "schema_source": (
                "packages/coding-agent/docs/rpc.md + rpc-commands.md (2026-10-04)",
            ),
            "framing": (
                "strict JSONL over stdio; LF byte framing; U+2028/U+2029 are valid "
                "inside JSON strings and are not delimiters (G5)"
            ),
            "correlation": (
                "client-chosen string id echoed on each response; extension_ui_response "
                "echoes its request id and produces no normal command response"
            ),
            "version_negotiation": "none documented; release pinned instead",
        },
        "launch": {
            "argv_shape": (
                "pi --mode rpc --no-session|--session-dir <d> --offline "
                "--no-extensions --no-skills --no-context-files "
                "--no-prompt-templates --no-approve",
            ),
            "runtime_flags": {
                "mode": "--mode rpc",
                "session": "--no-session (in-process) or --session-dir <d> (persistent)",
                "offline": "--offline (no network at startup; only model calls would leave the sandbox)",
            },
        },
        "isolation": {
            "home": "scratch HOME; XDG_CONFIG/DATA/STATE/CACHE and TMPDIR all pinned inside the scratch tree",
            "state_dir": "scratch/.pi (read/write state lives under the isolated HOME)",
            "no_user_state": (
                "user ~/.pi (auth.json, models-store.json, sessions) is never read "
                "under the pinned scratch HOME (G12); exact flag set observed in N001 L2 probe"
            ),
        },
        "network": {
            "default": "model calls are the only outbound traffic; CLI startup does not network",
            "offline_flag": "--offline disables startup networking (offline plans)",
            "telemetry": "PI_TELEMETRY=0 pinned at launch (G12)",
        },
        "auth": {
            "method": "environment API key or ~/.pi/agent/auth.json",
            "isolated_behavior": (
                "under the pinned scratch HOME the user auth.json is never read; "
                "an API key would only pass as an explicitly injected env key — and "
                "this planner injects none (G12: no credential inheritance)"
            ),
        },
        "session": {
            "create": (
                "--no-session yields an in-process sessionId (observed, N001 L2 partial); "
                "--session-dir persists (declared, not observed)"
            ),
            "resume": "unknown — replay semantics are not documented",
        },
        "callbacks": {
            "outbound": "extension_ui_request / extension_ui_response (same-id reply, not a command response)",
            "events": "message_update, agent_end, agent_settled, bash_execution_update",
        },
        "cancel": {
            "abort": "abort command; waits for idle before responding",
            "queue": "clear_queue removes and returns queued steering/follow-up texts (recommended before abort)",
        },
        "unknown_boundary": {
            "extensions": "unknown record types and fields are preserved verbatim (G4); no schema squeeze",
            "upgrade": "no version negotiation documented; upgrades re-pin the release and re-verify (G1)",
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    session_dir: str | os.PathLike[str] | None = None,
    offline: bool = True,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure launch plan for an isolated pi RPC channel. Executes nothing.

    The executable is the PATH-resolved ``pi`` name; a caller that owns a
    pinned binary may override it via ``extra_args`` preparation at its own
    seam — this planner never hardcodes a user path (G1 identity is checked
    at launch time by the driver, not fabricated here).
    """
    home_path = Path(home)
    argv = ["pi", "--mode", "rpc"]
    if session_dir is None:
        argv.append("--no-session")
    else:
        argv.extend(["--session-dir", os.fspath(session_dir)])
    if offline:
        argv.append("--offline")
    argv.extend(ISOLATION_FLAGS)
    argv.extend(extra_args)
    env = {
        "HOME": os.fspath(home_path),
        "XDG_CONFIG_HOME": os.fspath(home_path / "config"),
        "XDG_DATA_HOME": os.fspath(home_path / "data"),
        "XDG_STATE_HOME": os.fspath(home_path / "state"),
        "XDG_CACHE_HOME": os.fspath(home_path / "cache"),
        "TMPDIR": os.fspath(home_path / "tmp"),
        "LANG": _LANG,
        "LC_ALL": _LANG,
        "TERM": "dumb",
        "PI_TELEMETRY": "0",
    }
    if offline:
        env["PI_OFFLINE"] = "1"
    return {
        "argv": argv,
        "cwd": os.fspath(workspace),
        "env": env,
        "executable": "pi",
    }


def compile_config(materials: Mapping[str, Any]) -> dict:
    """Family-owned configuration compile (G3).

    Supported keys map to pi launch flags; any other key is refused before any
    launch (``ConfigRefusal``) — never silently swallowed, never mapped to a
    guessed flag. Returns the argument fragment only; ``plan_launch`` remains
    the sole owner of the base argv shape.
    """
    args: list[str] = []
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "owned by another surface; pi has no native equivalent"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized pi configuration key"
            )
            raise ConfigRefusal(key, reason)
    provider = materials.get("provider")
    if provider is not None:
        args.extend(["--provider", str(provider)])
    model = materials.get("model")
    if model is not None:
        args.extend(["--model", str(model)])
    thinking = materials.get("thinking")
    if thinking is not None:
        args.extend(["--thinking", str(thinking)])
    extensions = materials.get("extensions")
    if extensions is False:
        args.append("--no-extensions")
    return {"args": args, "session_dir": materials.get("session_dir"), "offline": materials.get("offline", True)}


def capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed per capability; never all-true (seams §4).

    ``observed`` only says ``L2-partial`` where the N001 probe actually saw it
    on the real 0.86.1 process; everything else is ``no`` or ``unknown``.
    """
    return {
        "prompt": {"declared": "yes", "implemented": "yes", "observed": "receipt-only(L2-partial)"},
        "cancel": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "resume": {"declared": "unknown", "implemented": "no", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "reply", "observed": "no"},
        "steer": {"declared": "yes", "implemented": "no", "observed": "no"},
        "modelConfig": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "sessionPersist": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "yes(L2-partial)"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "yes(L2-partial)"},
    }
