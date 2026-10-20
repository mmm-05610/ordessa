"""GitHub Copilot CLI native channel facts (N009, night-harness-expansion).

Family-owned, pinned L0 facts plus pure planning functions for the Copilot CLI
server JSON-RPC channel. This module neither launches a subprocess nor touches
any managed-install file; the frozen transport continues to own the process
(``ProcessChannel``), and runtime composition stays with the existing
provider/composition ports of this package (no parallel registry here:
``FAMILY_ID = "copilot"`` is the new-family identity assigned in
seams.md §1, to be registered in ``harnesses.toml`` by the N012 main
executor — this unit only submits the registration request).

Pinned evidence (official docs and first-hand SDK source read 2026-10-04,
URLs itemised in ``docs/implementation/agent-tools/night-harness-expansion/
evidence/copilot-decision.md``):

- The upstream SDK (``github/copilot-sdk``, MIT) speaks JSON-RPC to the
  Copilot CLI in **server mode**. The SDK "manages the CLI process lifecycle
  automatically" and the Node/Python/.NET SDKs bundle or **auto-download** the
  CLI. The Python SDK resolution order is explicit path > ``COPILOT_CLI_PATH``
  > downloaded runtime (``ensure_runtime_wrapper``), and its spawn argv is
  ``<cli> --headless --no-auto-update --log-level <lvl> [--no-auto-login]
  [--stdio | --port N]`` with ``COPILOT_HOME`` set on the child.
  This driver therefore never calls the SDK: it is a *plan* for an explicitly
  bound, caller-supplied binary with download disabled and a scratch
  ``COPILOT_HOME`` (G12).
- Handshake: ``connect`` (docs name ``server.connect``) carries
  ``supportedTaskKinds`` / optional ``clientInfo`` and returns
  ``protocolVersion``; a legacy server answering ``-32601`` falls back to
  ``ping``. Python SDK main pins protocol min == max == 3 — out-of-range or
  unreported versions are a hard error, never a downgrade.
- Sessions: ``session.create`` / ``session.resume`` (native ``sessionId`` in
  the response), sends via ``session.send`` whose result is a
  ``{messageId}`` **receipt** (``wait`` defaults to false; the receipt is not
  completion — completion is the ``session.idle`` event). Abort is
  ``session.abort`` (``{sessionId}`` -> ``{success, error}``).
- Permissions: the CLI asks the consumer; decision values are the documented
  ``PermissionDecisionKind`` strings, answered against the SAME JSON-RPC id.
  This driver never auto-approves and never injects a token.

Everything here is pinned to this reviewed state and is never auto-upgraded
into claims about a newer binary; no local ``copilot`` artifact exists in this
environment (installation not authorised), so L2 is NOT RUN.
"""
from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Mapping

FAMILY_ID = "copilot"

#: Command-catalog family id assigned by seams.md §1 (N012 registers it).
COMMAND_CATALOG_ID = "copilot"

#: Pinned upstream releases (read 2026-10-04; no local artifact).
PINNED_SDK_RELEASE = "v1.0.16 (published 2026-09-30)"
PINNED_CLI_RELEASE = "v1.0.91 (releases/latest checked 2026-10-04)"
SDK_CLI_SNAPSHOT = "1.0.90 (CLI snapshot named by the v1.0.16 release body)"

#: Protocol version pinned from ``sdk-protocol-version.json`` {"version": 3}
#: and the Python SDK bound ``_MIN_PROTOCOL_VERSION = 3`` (main, 2026-10-04).
PINNED_PROTOCOL_VERSION = 3

#: No measured local artifact: the CLI is not installed in this environment.
ARTIFACT_DIGEST = "unknown (no local copilot binary installed; L2 NOT RUN)"

_LANG = "C.UTF-8"

#: Documented CLI server-mode launch flags (SDK source argv + docs).
SERVER_MODE_FLAGS: tuple[str, ...] = ("--headless",)

#: Flags this planner always carries (G12: no auto-update, no auto-login).
ISOLATION_FLAGS: tuple[str, ...] = ("--no-auto-update", "--no-auto-login")

#: Environment key pinned at launch so a wrapper/SDK-style runtime can never
#: auto-download a CLI behind the caller's back (python SDK ``_cli_download``).
DOWNLOAD_DISABLE_ENV = "COPILOT_SKIP_CLI_DOWNLOAD"

#: Launch flags that would bypass the caller's approval decisions. The Copilot
#: README states "nothing happens without your explicit approval"; a planner
#: that passed an allow-all flag would break that guarantee (SAFETY).
FORBIDDEN_AUTO_APPROVE_FLAGS: tuple[str, ...] = (
    "--allow-all",
    "--allow-all-tools",
    "--allow-all-paths",
    "--yolo",
    "--auto-approve",
    "--yes",
)

#: Keys ``compile_config`` accepts (G3). Anything else is refused before any
#: launch — never silently dropped, never mapped to a guessed flag.
COMPILE_SUPPORTED_KEYS = frozenset(
    {"model", "reasoning_effort", "session_id", "session_idle_timeout", "log_level"}
)

#: Known second-ownership / out-of-family native-config keys. Refusing these is
#: the G3 counter-example gate: the family reports refusal instead of the
#: shared engine silently swallowing the key.
COMPILE_REFUSAL_KEYS = frozenset({"hotModelSwitch", "sandbox", "mcpServers"})

#: Token-shaped key fragments: refused outright, never forwarded (G12).
_TOKEN_HINTS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "APIKEY",
    "API_KEY",
)


class ConfigRefusal(ValueError):
    """Raised by ``compile_config`` for unsupported configuration keys (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def is_token_key(key: str) -> bool:
    """True when a configuration key is credential-shaped (never accepted)."""
    upper = key.upper()
    return any(hint in upper for hint in _TOKEN_HINTS)


def channel_report() -> dict:
    """L0 pin-board facts for the Copilot CLI server JSON-RPC channel.

    Every value is evidence-backed; unmeasured behaviour stays explicitly
    marked (``unknown`` / declared-not-observed) rather than asserted.
    """
    return {
        "family": FAMILY_ID,
        "commandCatalogId": COMMAND_CATALOG_ID,
        "channel": "stdio-jsonrpc-server-mode",
        "upstream": {
            "sdk_repo": "github.com/github/copilot-sdk",
            "sdk_license": "MIT (LICENSE, copyright GitHub, Inc.)",
            "cli_repo": "github.com/github/copilot-cli",
            "cli_license": (
                "GitHub Copilot CLI License (custom; unmodified redistribution only "
                "as part of an application providing material extra functionality, "
                "not standalone; see evidence/copilot-decision.md)"
            ),
            "docs": (
                "github/copilot-sdk docs (getting-started, client-info, "
                "streaming-events, session-persistence, auth, setup/*) read 2026-10-04"
            ),
        },
        "release": {
            "sdk": PINNED_SDK_RELEASE,
            "cli": PINNED_CLI_RELEASE,
            "sdk_cli_snapshot": SDK_CLI_SNAPSHOT,
            "protocol_version": PINNED_PROTOCOL_VERSION,
            "volatile": True,  # re-pin and re-verify on upgrade (G1)
            "local_artifact": ARTIFACT_DIGEST,
        },
        "artifact": {
            "path": "github/copilot-cli release assets (copilot-linux-x64.tar.gz etc.)",
            "sha256": ARTIFACT_DIGEST,
            "download_verification": (
                "SDK runtime downloads verify SHA256SUMS.txt from the GitHub release "
                "(python SDK _cli_download.py); nothing is downloaded by this driver"
            ),
        },
        "sdk_process_management": {
            "auto_download": (
                "documented: `python -m copilot download-runtime` is a recommended "
                "one-time step and, if skipped, the python SDK auto-downloads the "
                "matching runtime on first use; Node/.NET bundle the CLI as a "
                "dependency (setup/bundled-cli.md)"
            ),
            "download_source": (
                "https://github.com/github/copilot-cli/releases/download/v<version>/"
                "github-copilot-<version>-<platform>.tgz (+ SHA256SUMS.txt); unstable "
                "snapshots use github/copilot-sdk runtime-* tags; base URL overridable "
                "via COPILOT_CLI_DOWNLOAD_BASE_URL"
            ),
            "cache_path": (
                "~/.cache/github-copilot-sdk/cli/{version}/prebuilds/{platform}/ on "
                "linux (macOS Library/Caches, Windows LOCALAPPDATA); override "
                "COPILOT_CLI_EXTRACT_DIR; COPILOT_SKIP_CLI_DOWNLOAD=1 disables"
            ),
            "resolution_order": (
                "explicit path > COPILOT_CLI_PATH > downloaded runtime "
                "(python SDK CopilotClient._resolve_runtime_entrypoint, main)"
            ),
            "process_ownership": (
                "the SDK spawns the CLI as a child and sets COPILOT_HOME on it; its "
                "argv is `<cli> --headless --no-auto-update --log-level <lvl> "
                "[--no-auto-login] [--stdio | --port N]` (python SDK client.py, main)"
            ),
            "account_environment": (
                "SDK default use_logged_in_user = not github_token; stored Copilot CLI "
                "OAuth credentials live under the CLI home (default ~/.copilot) and "
                "are read by the CLI; the SDK can pass COPILOT_SDK_AUTH_TOKEN"
            ),
            "mitigation": (
                "this driver never invokes the SDK or its wrapper: it binds an "
                "explicit caller-supplied binary, sets COPILOT_SKIP_CLI_DOWNLOAD=1, "
                "pins COPILOT_HOME inside the scratch tree, passes --no-auto-login "
                "and injects no GH/COPILOT token (G12); cleanup targets only the "
                "owned ProcessChannel process (G8)"
            ),
            "verified": (
                "documented + first-hand python SDK source (main, read 2026-10-04); "
                "NOT executed here — L2 NOT RUN"
            ),
        },
        "protocol": {
            "schema_source": (
                "SDK docs + python SDK source client.py/session.py/"
                "generated/rpc.py (main, read 2026-10-04)"
            ),
            "framing": (
                "JSON-RPC over stdio, one JSON object per LF frame; the CLI's "
                "handling of an explicit `jsonrpc` header is unverified -> unknown "
                "(the frozen transport framing is reused as-is)"
            ),
            "handshake": (
                "`connect` (docs name server.connect) with supportedTaskKinds "
                "[agent, client, shell] and optional clientInfo "
                "(applicationName/applicationVersion/integrationName/"
                "integrationVersion); result carries protocolVersion; a legacy "
                "server answering -32601 falls back to `ping`"
            ),
            "version_negotiation": (
                f"protocolVersion integer; SDK min == max == {PINNED_PROTOCOL_VERSION}; "
                "out-of-range or unreported is a hard error — no downgrade, no retry"
            ),
            "methods": (
                "connect, ping, session.create, session.resume, session.send, "
                "session.abort, session.permissions.handlePendingPermissionRequest, "
                "session.interruptMainTurn, session.shutdown (generated rpc surface)"
            ),
            "receipt_semantics": (
                "session.send returns {messageId}; `wait` defaults to false; the "
                "receipt is never completion — completion evidence is session.idle"
            ),
        },
        "launch": {
            "argv_shape": (
                "<explicit-copilot-binary> --headless --stdio --no-auto-update "
                "--no-auto-login --log-level <level>"
            ),
            "runtime_flags": {
                "server": "--headless (server mode; TCP form `--headless --port N`, loopback by default)",
                "stdio": "--stdio (stdio server mode used by the SDK child process)",
                "auto_update": "--no-auto-update (the SDK always passes it)",
                "auto_login": "--no-auto-login (the SDK passes it when no explicit token; always planned here)",
                "log": "--log-level <none|error|warning|info|debug|all>",
            },
            "docs_alias": (
                "troubleshooting/debugging docs also show `copilot --server --stdio`; "
                "whether --server is an alias of --headless is unknown (not executed)"
            ),
        },
        "isolation": {
            "home": (
                "scratch HOME; COPILOT_HOME pinned inside the scratch tree; "
                "XDG_CONFIG/DATA/STATE/CACHE and TMPDIR all pinned (G12)"
            ),
            "state_dir": (
                "COPILOT_HOME/session-state/{sessionId}/ (documented session "
                "persistence); no user ~/.copilot is read"
            ),
            "no_user_state": (
                "user OAuth credentials/config under the real ~/.copilot are never "
                "read under the pinned COPILOT_HOME; COPILOT_DISABLE_KEYTAR=1 stops "
                "the shared OS keychain probe (SDK `mode=empty` behaviour) (G12)"
            ),
            "token_isolation": (
                "GH_TOKEN/GITHUB_TOKEN/COPILOT_GITHUB_TOKEN/COPILOT_TOKEN/"
                "COPILOT_SDK_AUTH_TOKEN are never inherited or injected; no token "
                "parameter exists on the planner; authentication is out of scope "
                "(unknown) and would need explicit user authorisation"
            ),
        },
        "network": {
            "default": (
                "model calls are the only outbound task traffic; --no-auto-update "
                "disables CLI self-update, COPILOT_SKIP_CLI_DOWNLOAD=1 disables "
                "runtime download"
            ),
            "telemetry": (
                "SDK can enable OTEL forwarding (COPILOT_OTEL_ENABLED etc.); this "
                "planner does not set any OTEL key and does not enable telemetry"
            ),
        },
        "auth": {
            "method": (
                "documented env vars in priority order: COPILOT_GITHUB_TOKEN, "
                "GH_TOKEN, GITHUB_TOKEN; stored Copilot CLI OAuth credentials "
                "(login) or GitHub App user tokens; BYOK provider keys"
            ),
            "isolated_behavior": (
                "no credential is inherited or injected under the pinned scratch "
                "home; COPILOT_TOKEN is not documented upstream -> unknown"
            ),
            "device_flow": "unknown — the docs describe an authorization-code OAuth flow, not a device flow",
        },
        "session": {
            "create": "session.create -> result sessionId (native identity, no fabrication)",
            "resume": "session.resume with sessionId; state under COPILOT_HOME/session-state/{id}/",
            "delete_vs_disconnect": (
                "documented SDK semantics: delete removes on-disk state; disconnect "
                "keeps it (observed: no)"
            ),
        },
        "callbacks": {
            "permission": (
                "documented permission.requested/permission.completed events plus a "
                "pending-permission RPC; answered against the SAME JSON-RPC id with "
                "a PermissionDecisionKind kind; NEVER auto-approve"
            ),
            "user_input": "user_input.requested/completed; elicitation.requested/completed",
            "events": (
                "assistant.*, tool.execution_*, session.idle/error, permission.*, "
                "user_input.*, elicitation.*, subagent.*, abort, ... (45 named types)"
            ),
        },
        "cancel": {
            "abort": "session.abort {sessionId} -> {success, error} (aborts the current turn)",
            "interrupt": "session.interruptMainTurn also exists in the generated surface (semantics unverified)",
        },
        "unknown_boundary": {
            "extensions": "unknown events/methods/fields are preserved verbatim (G4); no schema squeeze",
            "upgrade": (
                "protocolVersion integer handshake is the only gate; upgrades re-pin "
                "the release and re-run L1/L2 (G1)"
            ),
        },
    }


def plan_launch(
    *,
    executable: str | os.PathLike[str],
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    log_level: str = "debug",
    session_idle_timeout: int | None = None,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure launch plan for an isolated Copilot CLI stdio server. Executes nothing.

    The executable path is an explicit caller parameter — this planner never
    resolves PATH and never hardcodes a user path. The caller owns binding it
    to a verified artifact (G1), and the plan always carries
    ``--no-auto-login`` and download/telemetry-off environment pins (G12).
    """
    home_path = Path(home)
    for token in extra_args:
        base = token.split("=", 1)[0]
        if base in FORBIDDEN_AUTO_APPROVE_FLAGS:
            raise ConfigRefusal(
                base,
                "auto-approve flags are never planned (SAFETY: approval decisions stay with the caller)",
            )
    argv = [os.fspath(executable), "--headless", "--stdio"]
    argv.extend(ISOLATION_FLAGS)
    argv.extend(["--log-level", str(log_level)])
    if session_idle_timeout is not None:
        argv.extend(["--session-idle-timeout", str(int(session_idle_timeout))])
    argv.extend(extra_args)
    env = {
        "HOME": os.fspath(home_path),
        "COPILOT_HOME": os.fspath(home_path / "copilot"),
        "XDG_CONFIG_HOME": os.fspath(home_path / "config"),
        "XDG_DATA_HOME": os.fspath(home_path / "data"),
        "XDG_STATE_HOME": os.fspath(home_path / "state"),
        "XDG_CACHE_HOME": os.fspath(home_path / "cache"),
        "TMPDIR": os.fspath(home_path / "tmp"),
        "LANG": _LANG,
        "LC_ALL": _LANG,
        "TERM": "dumb",
        "NO_COLOR": "1",
        DOWNLOAD_DISABLE_ENV: "1",
        "COPILOT_DISABLE_KEYTAR": "1",
    }
    return {
        "argv": argv,
        "cwd": os.fspath(workspace),
        "env": env,
        "executable": os.fspath(executable),
    }


def compile_config(materials: Mapping[str, Any]) -> dict:
    """Family-owned configuration compile (G3).

    Token-class keys are refused first (G12), then unsupported keys are refused
    before any launch — never silently swallowed, never mapped to a guessed
    flag. Launch-level keys map to argv; session-level keys are returned as
    materials for ``session.create`` (the CLI takes them there, not on argv).
    """
    session: dict[str, Any] = {}
    for key in materials:
        if is_token_key(key):
            raise ConfigRefusal(key, "credential/ownership boundary; never accepted (G12)")
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = (
                "owned by another surface; copilot has no launch-level equivalent"
                if key in COMPILE_REFUSAL_KEYS
                else "not a recognized copilot configuration key"
            )
            raise ConfigRefusal(key, reason)
    args: list[str] = []
    if materials.get("log_level") is not None:
        args.extend(["--log-level", str(materials["log_level"])])
    if materials.get("session_idle_timeout") is not None:
        args.extend(["--session-idle-timeout", str(int(materials["session_idle_timeout"]))])
    for key in ("model", "reasoning_effort", "session_id"):
        if materials.get(key) is not None:
            session[key] = materials[key]
    return {"args": args, "session": session}


def _historical_capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed per capability; nothing observed (G1).

    No local Copilot CLI exists in this environment, so every ``observed``
    value stays ``no``; ``implemented`` only claims code written in this
    unit and ``declared`` reflects the documented upstream surface.
    """
    return {
        "prompt": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "abort", "observed": "no"},
        "resume": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "reply-no-auto", "observed": "no"},
        "steer": {"declared": "yes", "implemented": "no", "observed": "no"},
        "modelConfig": {"declared": "yes", "implemented": "session-materials", "observed": "no"},
        "modelHotSwitch": {"declared": "yes", "implemented": "no-refused", "observed": "no"},
        "sessionPersist": {"declared": "yes", "implemented": "home-redirect", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "no"},
    }


def capability_matrix() -> dict[str, dict]:
    """Current SDK migration state; historical protocol declarations are retained."""
    matrix = _historical_capability_matrix()
    for item in matrix.values():
        if 'implemented' in item and ('client' in item['implemented'] or item['implemented'] in ('yes','reply-no-auto','prepared-only')):
            item['implemented'] = 'unavailable (original-owner native protocol port pending); historical requirement: ' + item['implemented']
    return matrix
