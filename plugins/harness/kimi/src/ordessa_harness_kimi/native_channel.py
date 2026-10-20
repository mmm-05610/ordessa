"""Kimi native Wire channel facts (N006, night-harness-expansion).

Family-owned, pinned L0 facts plus pure planning functions for the native
``kimi --wire`` JSON-RPC 2.0 channel. This module neither launches a
subprocess nor touches any install file; the frozen transport continues to own
the process (``ProcessChannel``), and runtime composition stays with the
existing provider ports of this package (no parallel registry here:
``FAMILY_ID = "kimi"`` is the identity pinned in
``docs/implementation/agent-tools/night-harness-expansion/seams.md`` §1, to be
registered in ``harnesses.toml`` by N012).

All statements are pinned to a specific reviewed state: the legacy **Python**
Kimi CLI final release 1.52.0, Wire protocol 1.10, official docs read
2026-10-04 (all source URLs in the evidence file ``kimi-decision.md``). They
are never auto-upgraded into claims about a newer binary or untested
behaviour.

L2 status: **NOT RUN** — no ``kimi``/``kimi-agent`` executable exists on this
machine (and installing/updating third-party harnesses is not authorized this
night), so no live process of this channel has ever been observed by this
package. Nothing below is marked observed-yes and no ``runtimeReady`` is
published anywhere in this module.

Two honesty notes that the evidence records in full:

- Upstream ``github.com/MoonshotAI/kimi-cli`` is **archived** at 1.52.0 and
  the successor product (``kimi-code``) does not document Wire mode; whether
  Wire carries over is *unknown* and is registered as an upgrade/migration
  boundary, not asserted.
- The Rust variant (``kimi-agent``, ``MoonshotAI/kimi-agent-rs``,
  experimental) vendor-claims Wire compatibility but documents different
  capabilities (Wire only, Kimi provider only, no account login, no
  ``--prompt``/``--command``, different MCP OAuth storage). It must not be
  treated as the Python family with identical capabilities.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
from typing import Any, Mapping

FAMILY_ID = "kimi"

#: Pinned release. GitHub ``releases/latest`` resolves to tag 1.52.0 and the
#: official changelog records 1.52.0 (2026-09-22) as the final release of the
#: archived Python CLI. Read 2026-10-04.
PINNED_RELEASE = "1.52.0"

#: Wire protocol version documented as current on 2026-10-04
#: (wire-mode page: "The current protocol version is 1.10").
WIRE_PROTOCOL_VERSION = "1.10"

#: The pinned release is the *legacy* CLI; the successor product does not
#: document a Wire mode. Recorded verbatim, never papered over.
UPSTREAM_ARCHIVED = True

#: Isolation anchor (official docs): all runtime data — config.toml,
#: credentials/, sessions/, mcp.json, logs — lives under the share directory,
#: default ``~/.kimi``.
SHARE_DIR_ENV = "KIMI_SHARE_DIR"

_LANG = "C.UTF-8"

#: Keys ``compile_config`` accepts (G3). Anything else is refused before any
#: launch — never silently dropped, never mapped to a guessed flag.
COMPILE_SUPPORTED_KEYS = frozenset(
    {"model", "provider", "thinking", "session", "replay"}
)

#: Known second-ownership / out-of-family native-config keys. Refusing these
#: is the G3 counter-example gate: the family reports refusal instead of the
#: shared engine silently swallowing the key.
COMPILE_REFUSAL_KEYS = frozenset({"mcpServers", "sandbox", "hotModelSwitch"})

#: Refusal reason per recognized out-of-scope key (G3); unrecognized keys get
#: the generic reason in ``compile_config``.
COMPILE_REFUSAL_REASONS: dict[str, str] = {
    "mcpServers": (
        "MCP server configuration is file-owned (mcp.json / --mcp-config-file); "
        "not a Wire or launch compile key"
    ),
    "sandbox": (
        "kimi documents no sandbox configuration; refusing instead of mapping "
        "to a guessed flag"
    ),
    "hotModelSwitch": (
        "no Wire method to switch the model mid-session is documented "
        "(set_plan_mode exists, set_model does not); the model is fixed at launch"
    ),
}

#: Explicit N006 fence (Wire ``replay`` is read-only): replayed request
#: messages must NEVER be answered, so a replayed approval/question can never
#: be approved a second time. The client enforces this; this constant is the
#: one phrase both the driver matrix and the evidence file quote.
REPLAY_APPROVAL_FENCE = (
    "replay must never answer historical approval/question requests"
)


class ConfigRefusal(ValueError):
    """Raised by ``compile_config`` for unsupported configuration keys (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    """L0 pin-board facts for the kimi Wire channel (seams.md §4).

    Every value is evidence-backed (sources in ``kimi-decision.md``); the
    archived/not-installed state and the unmeasured behaviour stay explicitly
    marked (``unknown`` / ``no``) rather than asserted.
    """
    return {
        "family": FAMILY_ID,
        "channel": "native-wire-jsonrpc (kimi --wire, stdio JSON-RPC 2.0)",
        "upstream": {
            "repo": "github.com/MoonshotAI/kimi-cli",
            "package": "kimi-cli (PyPI)",
            "license": "Apache-2.0",
            "archived": UPSTREAM_ARCHIVED,
            "successor": (
                "github.com/MoonshotAI/kimi-code (Kimi Code CLI) — successor "
                "docs list Server API and ACP, no Wire mode page; Wire "
                "continuation is unknown/unverified (migration boundary)"
            ),
        },
        "release": {
            "version": PINNED_RELEASE,
            "source": (
                "github.com/MoonshotAI/kimi-cli releases/latest → 1.52.0 + "
                "official changelog 1.52.0 (2026-09-22, final release), read "
                "2026-10-04"
            ),
            "volatile": True,  # re-pin and re-verify on upgrade (G1); archived upstream
        },
        "artifact": {
            "local_install": (
                "absent — no kimi CLI on this machine; L2 NOT RUN "
                "(install/update not authorized this night)"
            ),
            "sha256": "unknown (nothing installed to digest)",
        },
        "protocol": {
            "schema_source": (
                "moonshotai.github.io/kimi-cli/en/customization/wire-mode.html "
                "(Wire mode, protocol version 1.10, read 2026-10-04)"
            ),
            "framing": (
                "JSON-RPC 2.0 over stdin/stdout; every message is a single "
                "line of JSON (LF framing); all four JSON-RPC members "
                "(jsonrpc/method|id|params|result|error) are on the wire (G5)"
            ),
            "version_negotiation": {
                "mechanism": (
                    "optional `initialize` request (added Wire 1.1) carries "
                    "params.protocol_version; the response reports the "
                    "server's protocol_version, server{name,version}, "
                    "slash_commands and capabilities"
                ),
                "mismatch_policy": "unknown — not documented",
                "no_handshake_fallback": (
                    "documented: a server without `initialize` answers -32601 "
                    "and the client falls back to no-handshake mode (legacy "
                    "clients may skip initialize and send prompt directly)"
                ),
            },
            "correlation": (
                "client requests use string ids; agent→client `request` "
                "frames are answered on the SAME JSON-RPC id with a result "
                "that repeats the payload's own id (approval: request_id + "
                "response; question: request_id + answers; tool call: "
                "tool_call_id + return_value)"
            ),
        },
        "launch": {
            "argv_shape": (
                "kimi --wire [--work-dir <d>] [--session <id> | --continue] "
                "[--model <m>] [--thinking | --no-thinking] "
                "[--config '<json>']"
            ),
            "runtime_flags": {
                "mode": (
                    "--wire (mutually exclusive with --print/--acp/shell); "
                    "running `kimi` with no arguments downloads and runs an "
                    "installer from the CDN — a bare launch is never planned"
                ),
                "work_dir": "--work-dir <d> (default current directory)",
                "session": (
                    "--session <id>/--resume <id> resumes (creates new if the "
                    "id does not exist); --continue resumes the latest session "
                    "of the working directory"
                ),
                "model": "--model <m> overrides the config default",
                "thinking": "--thinking / --no-thinking (boolean, model-dependent)",
            },
        },
        "isolation": {
            "home": (
                "scratch HOME; XDG_CONFIG/DATA/STATE/CACHE and TMPDIR all "
                "pinned inside the scratch tree"
            ),
            "share_dir": (
                "KIMI_SHARE_DIR pinned to <scratch>/kimi — config.toml, "
                "credentials/, sessions/, mcp.json, plans/, logs/ all live "
                "there; the default ~/.kimi user configuration is never read "
                "(G12)"
            ),
            "skills": (
                "no documented flag disables skill discovery (--skills-dir "
                "only appends); the scratch HOME keeps user-level skill "
                "directories empty, project-level skills of the workspace "
                "remain visible (declared, not observed)"
            ),
        },
        "network": {
            "default": (
                "model calls are the only task traffic; startup auto-update "
                "checking is pinned off with KIMI_CLI_NO_AUTO_UPDATE=1 "
                "(documented env var)"
            ),
            "telemetry": (
                "config `telemetry` defaults to true and no environment "
                "variable disables it; the planner does not inject a --config "
                "override (it would replace provider/model config), so the "
                "caller may pin telemetry=false explicitly via plan_launch "
                "config= (G12 note, declared)"
            ),
            "no_model": (
                "prompt without a configured LLM answers -32001 'LLM is not "
                "set' (documented error code) — the channel itself needs no "
                "model to start"
            ),
            "l2": "unobserved (CLI not installed)",
        },
        "auth": {
            "method": (
                "KIMI_API_KEY / KIMI_BASE_URL / KIMI_MODEL_* environment "
                "overrides, or providers/models in <KIMI_SHARE_DIR>/"
                "config.toml; OAuth credentials under <KIMI_SHARE_DIR>/"
                "credentials/ via `kimi login`"
            ),
            "isolated_behavior": (
                "under the pinned HOME/XDG/KIMI_SHARE_DIR the user ~/.kimi and "
                "its credentials are never read; this planner injects no "
                "credential (G12: no credential inheritance)"
            ),
        },
        "session": {
            "create": (
                "the CLI creates a session per start; Wire 1.10 documents NO "
                "session-create method — the consumer keeps create_session "
                "at the 'prepared' state and never fabricates a sessionId"
            ),
            "resume": (
                "launch-time --session <id> / --continue only (declared, not "
                "observed); session data: <share>/sessions/<work-dir-md5>/"
                "<session-id>/{context.jsonl,wire.jsonl,state.json}"
            ),
            "replay": (
                "Wire method `replay` (1.3+) reads <session>/wire.jsonl and "
                "re-sends recorded event and request messages in order; it is "
                "read-only and its result is {status, events, requests}. "
                + REPLAY_APPROVAL_FENCE + " (N006 fence)"
            ),
        },
        "config_capabilities": {
            "supported_keys": sorted(COMPILE_SUPPORTED_KEYS),
            "refused_keys": sorted(COMPILE_REFUSAL_KEYS),
            "provider_note": (
                "provider selection is config-file owned (--config / "
                "--config-file); no CLI provider flag is documented, so "
                "compile_config carries provider as a deferred plan item "
                "instead of a guessed flag"
            ),
            "replay_note": (
                "replay is a runtime Wire request (post-handshake), not a "
                "launch flag; compile_config returns it as a plan flag"
            ),
        },
        "callbacks": {
            "outbound": (
                "agent→client `request` frames: ApprovalRequest "
                "(approve|approve_for_session|reject; optional feedback), "
                "QuestionRequest (answers map), ToolCallRequest (external "
                "tools registered via initialize), HookRequest (hook "
                "subscriptions declared via initialize); answered on the same "
                "JSON-RPC id, never auto-approved by this family"
            ),
            "events": (
                "`event` notifications carrying WireMessage payloads: "
                "TurnBegin, TurnEnd, StepBegin, StepInterrupted, StepRetry "
                "(1.10), CompactionBegin/End, StatusUpdate, ContentPart, "
                "ToolCall/ToolCallPart/ToolResult, ApprovalResponse, "
                "SubagentEvent, BtwBegin/BtwEnd, SteerInput, PlanDisplay, "
                "HookTriggered/HookResolved"
            ),
        },
        "cancel": {
            "method": (
                "`cancel` (no params) cancels the running turn or replay; the "
                "in-flight prompt then returns status 'cancelled' — cancel is "
                "real evidence, never 'completed'"
            ),
            "steer": (
                "`steer` injects user input into the running turn without "
                "starting a new one; result {'status': 'steered'}; -32000 "
                "'No agent turn is in progress' when nothing runs"
            ),
        },
        "variants": {
            "python": (
                "kimi (Python, archived 1.52.0): the pinned subject of this "
                "module"
            ),
            "rust": (
                "kimi-agent (MoonshotAI/kimi-agent-rs, experimental) — "
                "vendor-claims full Wire compatibility but documented limits: "
                "Wire mode only, Kimi provider only, no account login, no "
                "--prompt/--command, local execution only, different MCP "
                "OAuth storage; NOT the same capability set as the Python "
                "family (never substituted silently)"
            ),
        },
        "unknown_boundary": {
            "extensions": (
                "unknown Wire message types, unknown event types and unknown "
                "fields are preserved verbatim (G4); no schema squeeze"
            ),
            "upgrade": (
                "initialize protocol_version is the only negotiation field; "
                "mismatch policy is undocumented → unknown; upgrades re-pin "
                "the release and re-verify (G1)"
            ),
        },
        "l2_status": "NOT RUN (no kimi CLI installed; no live process observed)",
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    session: str | None = None,
    continue_session: bool = False,
    model: str | None = None,
    thinking: bool | None = None,
    config: Mapping[str, Any] | None = None,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure launch plan for an isolated kimi Wire channel. Executes nothing.

    The executable is the PATH-resolved ``kimi`` name; a caller that owns a
    pinned binary may prepare ``extra_args`` at its own seam — this planner
    never hardcodes a user path (G1 identity is checked at launch time by the
    driver, not fabricated here). ``--wire`` is always present: a bare ``kimi``
    invocation (documented behavior) would download and run an installer from
    the CDN, which this planner never plans.
    """
    home_path = Path(home)
    workspace_path = Path(workspace)
    if session is not None and continue_session:
        raise ValueError("session=<id> and continue_session=True are mutually exclusive")
    argv = ["kimi", "--wire", "--work-dir", os.fspath(workspace_path)]
    if session is not None:
        argv.extend(["--session", str(session)])
    elif continue_session:
        argv.append("--continue")
    if model is not None:
        argv.extend(["--model", str(model)])
    if thinking is True:
        argv.append("--thinking")
    elif thinking is False:
        argv.append("--no-thinking")
    if config is not None:
        argv.extend(
            [
                "--config",
                json.dumps(dict(config), ensure_ascii=False, separators=(",", ":")),
            ]
        )
    argv.extend(extra_args)
    env = {
        "HOME": os.fspath(home_path),
        # Isolation anchor: without this pin the CLI would read the user's
        # ~/.kimi (config, credentials, sessions) — G12.
        SHARE_DIR_ENV: os.fspath(home_path / "kimi"),
        "XDG_CONFIG_HOME": os.fspath(home_path / "config"),
        "XDG_DATA_HOME": os.fspath(home_path / "data"),
        "XDG_STATE_HOME": os.fspath(home_path / "state"),
        "XDG_CACHE_HOME": os.fspath(home_path / "cache"),
        "TMPDIR": os.fspath(home_path / "tmp"),
        "LANG": _LANG,
        "LC_ALL": _LANG,
        "TERM": "dumb",
        "NO_COLOR": "1",
        # Documented switch disabling the startup auto-update check.
        "KIMI_CLI_NO_AUTO_UPDATE": "1",
    }
    return {
        "argv": argv,
        "cwd": os.fspath(workspace_path),
        "env": env,
        "executable": "kimi",
    }


def compile_config(materials: Mapping[str, Any]) -> dict:
    """Family-owned configuration compile (G3) → launch/plan fragment.

    Documented mappings only:

    - ``model`` → ``--model <m>`` (documented CLI flag)
    - ``thinking`` → ``--thinking`` / ``--no-thinking`` (documented boolean)
    - ``session`` → ``--session <id>``; ``True`` means ``--continue``
    - ``replay`` → plan flag (a runtime Wire request, not a launch flag)
    - ``provider`` → carried in ``deferred``: provider selection is config-file
      owned and no CLI provider flag is documented, so it is never mapped to a
      guessed flag

    Any other key is refused before any launch (``ConfigRefusal``) — never
    silently swallowed. Returns the argument fragment only; ``plan_launch``
    remains the sole owner of the base argv shape.
    """
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = COMPILE_REFUSAL_REASONS.get(
                key, "not a recognized kimi configuration key"
            )
            raise ConfigRefusal(key, reason)
    args: list[str] = []
    deferred: dict[str, Any] = {}
    plan: dict[str, Any] = {}

    model = materials.get("model")
    if model is not None:
        args.extend(["--model", str(model)])
    thinking = materials.get("thinking")
    if thinking is not None:
        if thinking is True:
            args.append("--thinking")
        elif thinking is False:
            args.append("--no-thinking")
        elif isinstance(thinking, str) and thinking.lower() in {"on", "off"}:
            args.append("--thinking" if thinking.lower() == "on" else "--no-thinking")
        else:
            raise ConfigRefusal(
                "thinking", "must be a boolean or 'on'/'off' (documented --thinking/--no-thinking)"
            )
    session = materials.get("session")
    if session is not None:
        if session is True:
            args.append("--continue")
            plan["continue_session"] = True
        elif session is False:
            pass
        else:
            args.extend(["--session", str(session)])
            plan["session"] = str(session)
    provider = materials.get("provider")
    if provider is not None:
        deferred["provider"] = {
            "value": provider,
            "reason": (
                "provider selection is owned by the config file (--config/"
                "--config-file); kimi documents no CLI provider flag"
            ),
        }
    replay = materials.get("replay")
    if replay is not None:
        plan["replay"] = bool(replay)
    return {"args": args, "plan": plan, "deferred": deferred}


def _historical_capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed per capability; never all-true (seams §4).

    The CLI is not installed, so this package has observed nothing of the real
    channel: every ``observed`` entry stays ``no`` or ``unknown`` — never
    ``yes`` (L2 NOT RUN). ``implemented`` is client/plan-side only.
    """
    return {
        "prompt": {"declared": "yes", "implemented": "yes(client)", "observed": "no"},
        "turn": {
            "declared": "yes(TurnBegin/TurnEnd/StepRetry)",
            "implemented": "yes(client)",
            "observed": "no",
        },
        "sessionCreate": {"declared": "unknown", "implemented": "prepared-only", "observed": "unknown"},
        "resume": {
            "declared": "yes(--session/--continue launch flags)",
            "implemented": "plan-only",
            "observed": "no",
        },
        "replay": {
            "declared": "yes(Wire 1.3+ read-only)",
            "implemented": "yes(client, fence: " + REPLAY_APPROVAL_FENCE + ")",
            "observed": "no",
        },
        "steer": {"declared": "yes(Wire 1.4+)", "implemented": "yes(client)", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "yes(client)", "observed": "no"},
        "approvalCallback": {
            "declared": "yes(ApprovalRequest)",
            "implemented": "yes(client, caller-decides)",
            "observed": "no",
        },
        "questionCallback": {
            "declared": "yes(QuestionRequest, supports_question)",
            "implemented": "yes(client, caller-decides)",
            "observed": "no",
        },
        "toolCallCallback": {
            "declared": "yes(ToolCallRequest)",
            "implemented": "yes(client, caller-decides)",
            "observed": "no",
        },
        "modelConfig": {
            "declared": "yes(--model/--thinking at launch)",
            "implemented": "yes(compile)",
            "observed": "no",
        },
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "rustVariant": {
            "declared": "different capability set (documented limits)",
            "implemented": "not substituted",
            "observed": "unknown",
        },
    }


def capability_matrix() -> dict[str, dict]:
    """Current SDK migration state; historical protocol declarations are retained."""
    matrix = _historical_capability_matrix()
    for item in matrix.values():
        if 'implemented' in item and ('client' in item['implemented'] or item['implemented'] in ('yes','reply-no-auto','prepared-only')):
            item['implemented'] = 'unavailable (original-owner native protocol port pending); historical requirement: ' + item['implemented']
    return matrix
