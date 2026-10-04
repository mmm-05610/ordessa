"""Codex native channel facts (N002, night-harness-expansion).

Family-owned, pinned L0 facts plus pure planning functions for the native
``codex app-server`` JSON-RPC channel. This module neither launches a
subprocess nor touches any install file; the frozen transport continues to own
the process (``ProcessChannel``), and runtime composition stays with the
existing provider ports of this package (no parallel registry here:
``FAMILY_ID = "codex"`` is the identity already registered in
``ordessa_harness.harnesses.toml`` — ``driver = "codex"`` with the
``app-server`` launch mode ``argv = ["codex", "app-server"]``).

All statements are pinned to a specific reviewed state (npm ``@openai/codex``
0.157.1, app-server protocol docs read 2026-10-04) and are never auto-upgraded
into claims about a newer binary or untested behaviour.

L2 status: **BLOCKED (local artifact broken)**. The local platform binary is a
truncated artifact — see ``BROKEN_LOCAL_ARTIFACT`` — so no live process of this
channel has ever been observed by this package. Nothing below is marked
observed-yes and no ``runtimeReady`` is published anywhere in this module;
re-install stays registered and pending user authorization.
"""
from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Mapping

FAMILY_ID = "codex"

#: Pinned release (npm @openai/codex 0.157.1 installed at
#: ~/.local/lib/node_modules/@openai/codex, read 2026-10-04).
PINNED_RELEASE = "0.157.1"

#: First-hand sha256 of the on-disk platform binary as found 2026-10-04
#: (@openai/codex-linux-x64 vendor binary). It digests the *broken* artifact;
#: any re-install invalidates it and requires a re-pin (G1).
PINNED_ARTIFACT_DIGEST = "632b790674b5462899a61bd248c33a3fb4594d3388f33259b8ca00dce014c42d"

#: First-hand evidence that the local artifact is broken (2026-10-04): the
#: file is 125,251,498 bytes but its ELF section table offset declares
#: 285,338,280 bytes, i.e. the image is truncated; execve fails EFAULT and the
#: process dies with SIGSEGV. The npm launcher additionally reports
#: "Missing optional dependency". This is why L2 is BLOCKED — it is recorded
#: verbatim, never papered over with a runtimeReady claim.
BROKEN_LOCAL_ARTIFACT: dict[str, Any] = {
    "file_size": 125251498,
    "elf_section_offset": 285338280,
    "failure": "execve EFAULT → SIGSEGV",
    "npm_launcher_error": "Missing optional dependency",
}

_LANG = "C.UTF-8"

#: Keys ``compile_config`` accepts (G3). Anything else is refused before any
#: launch — never silently dropped, never mapped to a guessed key.
COMPILE_SUPPORTED_KEYS = frozenset(
    {"model", "cwd", "approval_policy", "sandbox", "effort", "history_mode", "offline"}
)

#: Known second-ownership / out-of-family native-config keys. ``sandbox`` (the
#: per-thread thread/start value) is supported; a standalone sandbox instance
#: pool is a different ownership surface and is refused. Refusing these is the
#: G3 counter-example gate: the family reports refusal instead of the shared
#: engine silently swallowing the key.
COMPILE_REFUSAL_KEYS = frozenset(
    {"mcpServers", "sandboxInstancePool", "sandboxPools", "hotModelSwitch"}
)

#: Refusal reason per recognized out-of-scope key (G3); unrecognized keys get
#: the generic reason in ``compile_config``.
COMPILE_REFUSAL_REASONS: dict[str, str] = {
    "mcpServers": (
        "owned by another surface (mcp slot → $CODEX_HOME/config.toml); "
        "not a thread/start parameter"
    ),
    "sandboxInstancePool": (
        "standalone sandbox instance pool is another ownership surface; "
        "thread/start only accepts the per-thread sandbox value"
    ),
    "sandboxPools": (
        "same ownership surface as sandboxInstancePool; not a thread/start parameter"
    ),
    "hotModelSwitch": (
        "no pinned native equivalent; the model is fixed per thread/start"
    ),
}


class ConfigRefusal(ValueError):
    """Raised by ``compile_config`` for unsupported configuration keys (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    """L0 pin-board facts for the codex native channel (seams.md §4).

    Every value is evidence-backed; the broken local artifact and the L2
    BLOCKED state are recorded verbatim, and unmeasured behaviour stays
    explicitly marked (``unknown`` / declared-not-observed) rather than
    asserted.
    """
    return {
        "family": FAMILY_ID,
        "channel": "native-rpc-jsonl (codex app-server, stdio JSON-RPC 2.0)",
        "upstream": {
            "repo": "github.com/openai/codex",
            "package": "@openai/codex",
            "license": "Apache-2.0",
        },
        "release": {
            "version": PINNED_RELEASE,
            "source": (
                "npm @openai/codex 0.157.1 "
                "(~/.local/lib/node_modules/@openai/codex, read 2026-10-04)"
            ),
            "volatile": True,  # re-pin and re-verify on upgrade (G1); not a protocol guarantee
        },
        "artifact": {
            "path": "@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex",
            "sha256": PINNED_ARTIFACT_DIGEST,
            "sha256_scope": (
                "digest of the on-disk (broken) platform binary as found "
                "2026-10-04; a re-install invalidates it (G1)"
            ),
            "local_state": {
                "broken": True,
                "evidence": BROKEN_LOCAL_ARTIFACT,
                "disposition": (
                    "L2 BLOCKED (local artifact broken); re-install pending "
                    "user authorization"
                ),
            },
        },
        "protocol": {
            "schema_source": "learn.chatgpt.com/docs/app-server (2026-10-04)",
            "framing": (
                "JSONL over stdio (codex app-server); JSON-RPC 2.0 with the "
                "jsonrpc header omitted on the wire (G5 byte-framing rules "
                "still apply)"
            ),
            "handshake": (
                "initialize (params.clientInfo{name,title,version} + "
                "params.capabilities{experimentalApi,optOutNotificationMethods,...}) "
                "→ reply, then the `initialized` notification"
            ),
            "identity": (
                "thread/start (params.model, cwd, approvalPolicy, sandbox, ...) → "
                "result.thread.id + sessionId; turn/start (params.threadId, "
                "input items[{type:'text',text}...]) → result.turn.id status "
                "'inProgress' — the receipt is NOT completion; the terminal "
                "state only arrives via the turn/completed notification "
                "(completed|interrupted|failed); turn/steer carries "
                "expectedTurnId; thread/resume|fork|read|list|unsubscribe"
            ),
            "correlation": (
                "server→client requests (item/permissions/requestApproval, "
                "mcpServer/elicitation/request, tool/requestUserInput "
                "(experimental), attestation/generate) are correlated by "
                "JSON-RPC id; a serverRequest/resolved notification follows "
                "the reply"
            ),
            "version_negotiation": "none; capabilities-gated only (release pinned instead)",
            "errors": (
                "error{message, codexErrorInfo?}; overload -32001 'Server "
                "overloaded; retry later' is surfaced as-is — never "
                "auto-retried (G11)"
            ),
        },
        "launch": {
            "argv_shape": "codex app-server (see plan_launch)",
            "runtime_flags": {
                "listen": (
                    "--listen defaults to stdio; ws/unix alternatives exist "
                    "and are deliberately not selected"
                ),
            },
        },
        "isolation": {
            "home": "scratch HOME; XDG_CONFIG/DATA/STATE/CACHE and TMPDIR all pinned inside the scratch tree",
            "codex_home": (
                "CODEX_HOME pinned to <scratch>/codex — the default ~/.codex "
                "user configuration is never read (G12)"
            ),
            "no_user_state": (
                "user ~/.codex (config.toml, Auth.json) is never read under "
                "the pinned scratch HOME/CODEX_HOME (G12)"
            ),
        },
        "network": {
            "default": (
                "model calls are the only outbound traffic; the app-server "
                "handshake needs no network"
            ),
            "listen": "stdio only; ws/unix listeners are not selected",
            "launch_env": "NO_COLOR=1 pinned at launch",
        },
        "auth": {
            "method": "Auth.json under CODEX_HOME or an API key",
            "isolated_behavior": (
                "under the pinned scratch HOME/CODEX_HOME the user auth "
                "(default ~/.codex) is never read; this planner injects no "
                "credential (G12: no credential inheritance)"
            ),
        },
        "session": {
            "create": (
                "thread/start yields thread.id + sessionId (declared, not "
                "observed); turn receipts never fake completion"
            ),
            "resume": (
                "thread/resume / thread/fork / thread/read / thread/list / "
                "thread/unsubscribe declared; not observed (L2 blocked)"
            ),
        },
        "callbacks": {
            "outbound": (
                "item/permissions/requestApproval → "
                "accept|acceptForSession|decline|cancel|"
                "{acceptWithExecpolicyAmendment} (auto-approve forbidden, "
                "SAFETY gate); mcpServer/elicitation/request; "
                "tool/requestUserInput (experimental); attestation/generate"
            ),
            "events": (
                "thread/started, turn/started, turn/completed, item/started, "
                "item/completed, item/agentMessage/delta, …"
            ),
        },
        "cancel": {
            "abort": (
                "turn/interrupt (threadId, turnId); the turn receipt never "
                "fakes a completed state"
            ),
            "steer": "turn/steer (expectedTurnId) redirects the running turn instead of cancelling it",
        },
        "unknown_boundary": {
            "extensions": "unknown method/event names are preserved verbatim (G4); no schema squeeze",
            "overload": (
                "-32001 'Server overloaded; retry later' propagates unchanged; "
                "no automatic retry (G11)"
            ),
            "upgrade": "no version negotiation; upgrades re-pin the release and re-verify (G1)",
        },
        "l2_status": "BLOCKED (local artifact broken; no live process observation by this package)",
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure launch plan for an isolated codex app-server channel. Executes nothing.

    The executable is the PATH-resolved ``codex`` name; a caller that owns a
    pinned binary may prepare ``extra_args`` at its own seam — this planner
    never hardcodes a user path (G1 identity is checked at launch time by the
    driver, not fabricated here). ``--listen`` is left at its stdio default;
    ws/unix alternatives are never selected.
    """
    home_path = Path(home)
    argv = ["codex", "app-server"]
    argv.extend(extra_args)
    env = {
        "HOME": os.fspath(home_path),
        # Isolation anchor: without this pin codex would read the user's
        # ~/.codex (config, Auth.json) — G12.
        "CODEX_HOME": os.fspath(home_path / "codex"),
        "XDG_CONFIG_HOME": os.fspath(home_path / "config"),
        "XDG_DATA_HOME": os.fspath(home_path / "data"),
        "XDG_STATE_HOME": os.fspath(home_path / "state"),
        "XDG_CACHE_HOME": os.fspath(home_path / "cache"),
        "TMPDIR": os.fspath(home_path / "tmp"),
        "LANG": _LANG,
        "LC_ALL": _LANG,
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    return {
        "argv": argv,
        "cwd": os.fspath(workspace),
        "env": env,
        "executable": "codex",
    }


def compile_config(materials: Mapping[str, Any]) -> dict:
    """Family-owned configuration compile (G3) → ``thread/start`` param plan.

    Supported keys map onto ``thread/start`` parameter names: ``model``/``cwd``
    /``approval_policy``/``sandbox`` use the protocol-pinned wire names
    (``model``, ``cwd``, ``approvalPolicy``, ``sandbox``); ``effort`` follows
    the in-repo app-server precedent. ``history_mode`` and ``offline`` are
    accepted family vocabulary whose ``thread/start`` wire names are not
    pinned yet (L2 blocked), so they are carried in ``deferred`` instead of
    being invented into a guessed wire key.

    Any other key is refused before any launch (``ConfigRefusal``) — never
    silently swallowed, never mapped to a guessed flag. The ``args`` fragment
    stays empty on purpose: codex configuration rides the JSON params, and
    ``plan_launch`` remains the sole owner of the base argv shape.
    """
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            reason = COMPILE_REFUSAL_REASONS.get(
                key, "not a recognized codex configuration key"
            )
            raise ConfigRefusal(key, reason)
    thread_params: dict[str, Any] = {}
    deferred: dict[str, Any] = {}
    model = materials.get("model")
    if model is not None:
        thread_params["model"] = str(model)
    cwd = materials.get("cwd")
    if cwd is not None:
        thread_params["cwd"] = os.fspath(cwd)
    approval_policy = materials.get("approval_policy")
    if approval_policy is not None:
        thread_params["approvalPolicy"] = str(approval_policy)
    sandbox = materials.get("sandbox")
    if sandbox is not None:
        thread_params["sandbox"] = str(sandbox)
    effort = materials.get("effort")
    if effort is not None:
        thread_params["effort"] = str(effort)
    history_mode = materials.get("history_mode")
    if history_mode is not None:
        deferred["history_mode"] = history_mode
    offline = materials.get("offline")
    if offline is not None:
        deferred["offline"] = offline
    return {"thread_params": thread_params, "args": [], "deferred": deferred}


def capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed per capability; never all-true (seams §4).

    The local artifact is broken, so this package has observed nothing of the
    real channel: every ``observed`` entry stays ``no`` — never ``yes``
    (L2 blocked). ``implemented`` is client-side where the frozen transport +
    client seam already own the mechanics, and ``plan-only`` where only this
    module's planning exists.
    """
    return {
        "prompt": {"declared": "yes", "implemented": "yes(client)", "observed": "no(L2-blocked)"},
        "turn": {"declared": "yes", "implemented": "yes(client)", "observed": "no(L2-blocked)"},
        "steer": {"declared": "yes(turn/steer)", "implemented": "plan-only", "observed": "no"},
        "cancel": {"declared": "yes(turn/interrupt)", "implemented": "plan-only", "observed": "no"},
        "resume": {"declared": "yes(thread/resume)", "implemented": "plan-only", "observed": "no"},
        "approvalCallback": {"declared": "yes", "implemented": "plan-only", "observed": "no"},
        "sessionCreate": {"declared": "yes", "implemented": "yes(client)", "observed": "no"},
        "modelConfig": {"declared": "yes", "implemented": "yes(client)", "observed": "no"},
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {"declared": "yes", "implemented": "yes", "observed": "no"},
    }
