"""Qwen Code native channel facts (N007, night-harness-expansion).

Family-owned pinned L0 facts plus pure planning functions for the Qwen Code
native channel. The chosen channel is the ``qwen serve`` loopback HTTP + SSE
daemon protocol (``docs/developers/qwen-serve-protocol.md``): the daemon owns
the workspace registry, each per-workspace runtime and the ``qwen --acp``
child it spawns, and mediates permission votes. Direct ``qwen --acp`` was
compared and NOT chosen: it would move spawn lifecycle, workspace binding
(``session/new`` cwd) and ``request_permission`` answering into the embedding
client, a larger management surface. Both conclusions are recorded in
``channel_report()["ownership"]``.

No subprocess is launched here and no parallel registry is created:
``FAMILY_ID = "qwen"`` is the family id catalogued by seams.md §1 / the
existing ``qwen/`` package. The baseline ``harnesses.toml`` carries no qwen
block yet; registration sync belongs to N012 and is recorded, not bypassed.

Every statement is pinned to the reviewed upstream state (package.json/npm
latest 0.24.7, docs main @9915c7ff…, read 2026-10-04) and never auto-upgraded
into claims about a newer binary. No local artifact exists (the CLI is not
installed), so the artifact digest is ``unknown`` — never invented.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

FAMILY_ID = "qwen"

#: Upstream release pinned from packages/cli/package.json and the npm
#: dist-tag ``latest`` (@qwen-code/qwen-code 0.24.7, read 2026-10-04).
PINNED_RELEASE = "0.24.7"

#: Exact reviewed revision of the upstream default branch (main commit
#: 9915c7ff…, 2026-10-04T17:54:09Z). Docs and source checks below are pinned
#: to this revision.
UPSTREAM_REVISION = "9915c7ff8ff17a6c5e0840053a0c05bb72eec510"

#: No installed artifact exists on this machine (CLI absent, install not
#: authorised) — the digest stays unknown rather than fabricated (G1).
ARTIFACT_DIGEST = "unknown (no local artifact measured)"

#: Managed production artifact already referenced in-tree
#: (``qwen/production.py`` ADAPTER_VERSION); the drift against the newly
#: pinned upstream 0.24.7 is registered, not silently reconciled.
MANAGED_ARTIFACT_VERSION = "0.23.4"

#: Loopback bind only. This planner never emits a public bind: the loopback
#: default is a tokenless trusted mode granting any local caller full
#: operator API authority, so the channel is planned as a privileged
#: local-only surface.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

#: Plan-level isolation: the Web Shell is not needed by the native channel
#: and its static assets are pre-auth on loopback even under
#: ``--require-auth``; plans default to API-only.
ISOLATION_FLAGS: tuple[str, ...] = ("--no-web",)

#: Keys ``compile_config`` accepts (G3). Anything else is refused before any
#: launch — never silently dropped, never mapped to a guessed flag.
COMPILE_SUPPORTED_KEYS = frozenset(
    {
        "no_web",
        "prompt_deadline_ms",
        "event_ring_size",
        "max_sessions",
        "session_scope",
        "model_service_id",
    }
)

#: Known second-ownership / out-of-family native-config keys. Refusing these
#: is the G3 counter-example gate: qwen owns MCP through workspace routes and
#: settings, sandbox through its settings/feature surface, and model
#: switching through a runtime route — none is a launcher config this family
#: may swallow.
COMPILE_REFUSAL_KEYS = frozenset({"mcpServers", "sandbox", "hotModelSwitch"})

_SESSION_SCOPES = ("single", "thread")


class ConfigRefusal(ValueError):
    """Raised by ``compile_config`` for unsupported configuration keys (G3)."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"unsupported configuration key {key!r}: {reason}")


def channel_report() -> dict:
    """L0 pin-board facts for the qwen serve HTTP/SSE channel (seams.md §4).

    Every value is evidence-backed (source URLs and the 2026-10-04 read date
    are in the N007 evidence file); unmeasured behaviour stays explicitly
    marked ``unknown`` rather than asserted, and no value is a runtimeReady
    claim.
    """
    return {
        "family": FAMILY_ID,
        "channel": "loopback-http+sse-over-acp",
        "upstream": {
            "repo": "github.com/QwenLM/qwen-code",
            "package": "@qwen-code/qwen-code (npm)",
            "license": (
                "Apache-2.0 (repo LICENSE); the npm packument declares no "
                "license field — repo LICENSE is the pinned source"
            ),
            "docs": (
                "docs/developers/architecture.md + "
                "docs/developers/qwen-serve-protocol.md (main @"
                f"{UPSTREAM_REVISION[:8]}, read 2026-10-04)"
            ),
        },
        "release": {
            "version": PINNED_RELEASE,
            "source_revision": UPSTREAM_REVISION,
            "source": (
                "packages/cli/package.json and npm dist-tag latest both "
                "0.24.7; docs main commit 2026-10-04T17:54:09Z"
            ),
            "volatile": True,  # re-pin and re-verify on upgrade (G1)
            "local_artifact": (
                "not installed (L2 untested, install not authorised); the "
                "in-tree managed production artifact references "
                f"@qwen-code/qwen-code {MANAGED_ARTIFACT_VERSION} "
                "(qwen/production.py) — version drift registered"
            ),
            "stage": (
                "qwen serve is documented as Stage 1 experimental with "
                "--http-bridge default true; the user doc still labels "
                "v0.16-alpha while the package is 0.24.7 — doc/version drift "
                "recorded, not resolved"
            ),
        },
        "artifact": {
            "path": (
                "npm @qwen-code/qwen-code; managed artifact "
                "node_modules/@qwen-code/qwen-code/cli-entry.js"
            ),
            "sha256": ARTIFACT_DIGEST,
        },
        "protocol": {
            "schema_source": (
                "docs/developers/qwen-serve-protocol.md (routes + SSE "
                "framing), docs/developers/daemon-rest-api-reference.md and "
                "daemon-rest-api.openapi.json (machine-readable mirror)"
            ),
            "framing": (
                "HTTP JSON request/response plus SSE; one data: line per "
                "frame carrying the full JSON envelope {id?, v, type, data}, "
                "event: line duplicates envelope.type"
            ),
            "correlation": (
                "POST /session/:id/prompt answers "
                "{promptId, lastEventId[, eventEpoch]} as an admission "
                "receipt; completion is turn_complete / turn_error "
                "correlated by promptId on GET /session/:id/events; "
                "Last-Event-ID is the reconnect cursor"
            ),
            "version_negotiation": (
                "/capabilities reports protocolVersions {current: v1, "
                "supported: [v1]} and feature tags; v increments only on a "
                "breaking frame change"
            ),
        },
        "ownership": {
            "workspace": (
                "qwen serve daemon resolves and canonicalizes the workspace: "
                "--workspace (repeatable, first is primary) or process.cwd(); "
                "a mismatched POST /session cwd returns 400 "
                "workspace_mismatch; /capabilities.workspaceCwd is the "
                "pre-flight source"
            ),
            "runtime": (
                "daemon owns each workspace runtime and the qwen --acp child "
                "it spawns (one preheated primary bridge plus on-demand "
                "children for trusted secondaries); the CLI's stdout is not a "
                "management surface and is never parsed as protocol"
            ),
            "permissions": (
                "agent core applies permission policy; the acp-bridge "
                "mediates; clients observe permission_request over SSE and "
                "vote via POST /session/:id/permission/:requestId "
                "(first-responder by default, response timeout disabled by "
                "default) — this family never auto-votes"
            ),
            "direct_acp_contrast": (
                "with `qwen --acp` the embedding ACP client owns process "
                "lifecycle, session/new cwd and request_permission answering; "
                "candidate compared and NOT chosen (registered)"
            ),
        },
        "launch": {
            "argv_shape": (
                "qwen serve --hostname 127.0.0.1 --workspace <dir> "
                "[--port N] [--no-web]"
            ),
            "defaults": (
                "documented default 127.0.0.1:4170; --port 0 requests an "
                "OS-assigned ephemeral port whose value is discovered at run "
                "time, never guessed here"
            ),
            "runtime_flags": {
                "no_web": (
                    "API-only; removes the pre-auth static Web Shell surface "
                    "(plans default to this)"
                ),
                "port": "0 = OS-assigned ephemeral; any other value = explicit bind",
            },
        },
        "isolation": {
            "home": (
                "scratch HOME; QWEN_HOME pinned to <home>/.qwen; "
                "XDG_CONFIG/DATA/STATE/CACHE and TMPDIR inside the scratch tree"
            ),
            "state_dir": (
                "<QWEN_HOME>/settings.json and <QWEN_HOME>/projects/ "
                "(documented session store, chats/<project>/)"
            ),
            "no_user_state": (
                "user ~/.qwen (settings, .env credentials, session history) "
                "is never read; this planner injects no credential or bearer "
                "(G12)"
            ),
        },
        "network": {
            "default": (
                "loopback bind only; model calls are the only outbound "
                "traffic; the Web Shell is disabled by default in plans"
            ),
            "auth_posture": (
                "loopback default is tokenless trusted mode with full operator "
                "API authority for any local caller — a privileged channel; "
                "this planner never binds non-loopback and never inherits a "
                "token"
            ),
            "telemetry_updates": (
                "serve-side telemetry / auto-update behaviour is not pinned by "
                "the reviewed docs — registered unknown, no switch invented"
            ),
        },
        "auth": {
            "method": (
                "transport: optional bearer via --token or QWEN_SERVER_TOKEN "
                "(loopback default is tokenless); provider credentials are "
                "environment-based (OPENAI_API_KEY / OPENAI_BASE_URL / "
                "OPENAI_MODEL alias QWEN_MODEL, DASHSCOPE_API_KEY, "
                "ANTHROPIC_*, GEMINI_*) or settings.json env references"
            ),
            "isolated_behavior": (
                "no user environment or settings are inherited by the plan; "
                "provider credentials would only pass as an explicit caller "
                "injection (the product template references OPENAI_API_KEY)"
            ),
        },
        "session": {
            "create": (
                "POST /session into the daemon-owned ledger; default "
                "sessionScope 'single' may attach to an existing shared "
                "session (attached: true); the client defaults to 'thread' so "
                "it never silently shares or fabricates a second ledger"
            ),
            "resume": (
                "POST /session/:id/load and POST /session/:id/resume for "
                "daemon-owned persisted sessions (declared, not observed)"
            ),
            "close": (
                "DELETE /session/:id (204) cancels the active prompt and "
                "removes the live session; on-disk sessions stay loadable"
            ),
        },
        "callbacks": {
            "permission": (
                "SSE permission_request + POST /session/:id/permission/"
                ":requestId vote; caller decides, no auto-approve"
            ),
            "events": (
                "GET /session/:id/events SSE envelopes; unknown event "
                "types/fields surface verbatim (G4)"
            ),
        },
        "cancel": {
            "route": (
                "POST /session/:id/cancel -> 204; cancels only the active "
                "prompt — queued prompts keep running per the documented "
                "multi-prompt contract"
            ),
        },
        "unknown_boundary": {
            "extensions": (
                "unknown SSE envelope types/fields preserved verbatim (G4); "
                "new known events are additive"
            ),
            "sse_disconnect": (
                "NOT task completion: completion is turn_complete/turn_error "
                "by promptId; disconnecting the prompt HTTP connection makes "
                "the daemon cancel the agent (documented) — neither a stream "
                "end nor a disconnect is completion"
            ),
            "source_check": (
                "source verified 2026-10-04 against the docs: the prompt 202 "
                "body additionally carries eventEpoch in session.ts beyond "
                "the documented {promptId, lastEventId}; cancel 204 and "
                "POST /session 200 match — the additive difference is "
                "recorded, not hidden"
            ),
            "upgrade": (
                "no negotiation beyond /capabilities protocolVersions v1; "
                "upgrades re-pin release/revision and re-verify (G1)"
            ),
        },
    }


def plan_launch(
    *,
    home: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    port: int | None = None,
    web: bool = False,
    extra_args: tuple[str, ...] = (),
) -> dict:
    """Pure launch plan for an isolated qwen serve daemon. Executes nothing.

    ``hostname`` is not a parameter: the plan pins loopback only. ``port=None``
    uses the documented default 4170; ``port=0`` requests an OS-assigned
    ephemeral port (discovered at run time, never guessed here). ``web=False``
    (default) adds ``--no-web`` for an API-only daemon. The plan contains no
    credential and no token: loopback auth posture and any explicit token
    injection stay the caller's seam.
    """
    workspace_raw = os.fspath(workspace)
    if not os.path.isabs(workspace_raw):
        # qwen serve documents --workspace as an absolute path; a relative
        # value would silently resolve against the daemon's cwd instead.
        raise ValueError(f"qwen serve --workspace requires an absolute path, got {workspace_raw!r}")
    workspace_path = os.path.abspath(workspace_raw)
    home_path = Path(home)
    argv = [
        "qwen",
        "serve",
        "--hostname",
        LOOPBACK_HOSTS[0],
        "--workspace",
        workspace_path,
    ]
    if port is not None:
        argv.extend(["--port", str(port)])
    if not web:
        argv.extend(ISOLATION_FLAGS)
    argv.extend(extra_args)
    env = {
        "HOME": os.fspath(home_path),
        "QWEN_HOME": os.fspath(home_path / ".qwen"),
        "XDG_CONFIG_HOME": os.fspath(home_path / "config"),
        "XDG_DATA_HOME": os.fspath(home_path / "data"),
        "XDG_STATE_HOME": os.fspath(home_path / "state"),
        "XDG_CACHE_HOME": os.fspath(home_path / "cache"),
        "TMPDIR": os.fspath(home_path / "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    return {
        "argv": argv,
        "cwd": workspace_path,
        "env": env,
        "executable": "qwen",
    }


def _refusal_reason(key: str) -> str:
    if key in COMPILE_REFUSAL_KEYS:
        return "owned by another qwen surface; no launcher config is fabricated"
    return "not a recognized qwen configuration key"


def compile_config(materials: Mapping[str, Any]) -> dict:
    """Family-owned configuration compile (G3).

    Supported keys map to ``qwen serve`` launch flags or documented session
    creation fields. Any other key is refused before any launch
    (``ConfigRefusal``) — never silently swallowed, never mapped to a guessed
    flag. ``plan_launch`` remains the sole owner of the base argv shape.
    """
    for key in materials:
        if key not in COMPILE_SUPPORTED_KEYS:
            raise ConfigRefusal(key, _refusal_reason(key))
    args: list[str] = []
    if materials.get("no_web") is True:
        args.append("--no-web")
    deadline = materials.get("prompt_deadline_ms")
    if deadline is not None:
        args.extend(["--prompt-deadline-ms", str(deadline)])
    ring = materials.get("event_ring_size")
    if ring is not None:
        args.extend(["--event-ring-size", str(ring)])
    max_sessions = materials.get("max_sessions")
    if max_sessions is not None:
        args.extend(["--max-sessions", str(max_sessions)])
    session_fields: dict[str, Any] = {}
    scope = materials.get("session_scope")
    if scope is not None:
        if scope not in _SESSION_SCOPES:
            raise ValueError(
                f"invalid session_scope {scope!r}; qwen documents {_SESSION_SCOPES}"
            )
        session_fields["sessionScope"] = scope
    service = materials.get("model_service_id")
    if service is not None:
        session_fields["modelServiceId"] = str(service)
    return {"args": args, "session_fields": session_fields}


def capability_matrix() -> dict[str, dict]:
    """declared/implemented/observed per capability; never all-true (seams §4).

    Nothing was observed on a real process (the CLI is not installed), so
    every ``observed`` stays ``no`` — the L2 gap is registered, not papered
    over.
    """
    return {
        "prompt": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "cancel": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "resume": {"declared": "yes", "implemented": "route-known", "observed": "no"},
        "approvalCallback": {
            "declared": "yes",
            "implemented": "vote-route(no-auto)",
            "observed": "no",
        },
        "steer": {"declared": "yes", "implemented": "no", "observed": "no"},
        "modelConfig": {
            "declared": "yes",
            "implemented": "session-field",
            "observed": "no",
        },
        "sessionPersist": {
            "declared": "yes",
            "implemented": "daemon-owned",
            "observed": "no",
        },
        "unknownExtensions": {"declared": "yes", "implemented": "yes", "observed": "no"},
        "transportFence": {"declared": "no", "implemented": "no", "observed": "no"},
        "requestReconciliation": {
            "declared": "yes",
            "implemented": "yes",
            "observed": "no",
        },
        "sseDisconnectSemantics": {
            "declared": "yes",
            "implemented": "not-completion",
            "observed": "no",
        },
    }
