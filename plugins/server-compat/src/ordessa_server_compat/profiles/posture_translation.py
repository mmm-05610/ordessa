"""Order 60 (leftover): translating a neutral posture into a family's knobs.

The neutral posture (order 60 B) is per-tool `allow`/`ask`/`deny`. Each family
expresses what it can, and this module's one rule decides the rest: **a
translation may only be stricter than the posture, never looser.** Where a
family has no knob for a key, the effective behaviour would be its default -
so if the posture asked for something narrower (`deny`/`ask`) and no knob
exists, the answer is a typed refusal, not a silent drop.

The vocabulary is first-hand from the pinned artifacts (order 60/65 rounds):

* **claude-code**: tool names `Bash` / `Edit` / `Read` / `Write` / `Glob` /
  `Grep` / `Task` / `WebFetch` / `WebSearch` / `NotebookEdit` / `Skill`, plus
  the `allowed-tools` / `disallowedTools` vocabulary and `permissions`;
* **codex**: `sandbox_mode` (`read-only` / `workspace-write` /
  `danger-full-access`) and the approval policies (`untrusted` / `on-request` /
  `on-failure` / `never`); its knobs are coarse, so several postures refuse.

Nothing here renders a file: the caller decides where a translation lands, and
the `notes` field carries every approximation so nothing is silent.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_server_compat.profiles.permissions import TOOL_KEYS


class PostureTranslationError(RuntimeError):
    """A typed refusal of one translation."""

    def __init__(self, code: str, message: str, *, key: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.key = key


#: claude-code's tool vocabulary per neutral key (first-hand names).
_CLAUDE_TOOLS: dict[str, tuple[str, ...]] = {
    "read": ("Read", "Glob", "Grep"),
    "edit": ("Edit", "Write", "NotebookEdit"),
    "bash": ("Bash",),
    "task": ("Task",),
    "webfetch": ("WebFetch", "WebSearch"),
    "skill": ("Skill",),
    # external_directory has no tool name of its own; it is expressed by the
    # directory-scoped permission entries, which this translation does not
    # invent - so it refuses unless the posture is permissive there.
}


def translate_claude(posture: Mapping[str, Any]) -> dict[str, Any]:
    """claude-code's per-tool permission lists for a neutral posture.

    Three buckets, matching claude's own `permissions.{allow,ask,deny}`
    semantics: an `allow` key becomes an auto-approved `allowedTools` entry, a
    `deny` key becomes a `disallowedTools` entry, and an `ask` key becomes an
    `ask` entry - claude's *questioning* path, where the tool is neither
    pre-approved nor blocked but gated by an interactive decision. (Order 111 /
    R-0032: `ask` used to fall into `allowedTools`, which pre-approves the tool
    and so means "does not ask" - the exact opposite of the posture.)
    """
    keys = dict(posture.get("keys") or {})
    allowed: list[str] = []
    disallowed: list[str] = []
    ask: list[str] = []
    notes: list[str] = []
    for key in TOOL_KEYS:
        action = keys.get(key, "ask")
        tools = _CLAUDE_TOOLS.get(key)
        if tools is None:
            if action == "allow":
                notes.append(f"{key}=allow has no claude knob; the family default applies")
                continue
            raise PostureTranslationError(
                "PERMISSION_POSTURE_UNEXPRESSIBLE",
                f"claude-code has no knob for {key}={action}", key=key,
            )
        if action == "deny":
            disallowed.extend(tools)
        elif action == "ask":
            # Order 111: `ask` is claude's permissions.ask path - the tool
            # stays out of the auto-approved set and is gated by a prompt.
            ask.extend(tools)
            if key != "read":
                notes.append(f"{key}=ask maps to claude's permissions.ask (提问)")
        else:
            allowed.extend(tools)
    return {"allowedTools": sorted(set(allowed)),
            "ask": sorted(set(ask)),
            "disallowedTools": sorted(set(disallowed)), "notes": notes}


def translate_codex(posture: Mapping[str, Any]) -> dict[str, Any]:
    """The `sandbox_mode` + approval policy a codex-family posture allows.

    Codex's knobs are coarse: writes are the sandbox mode's business, and a
    gated command is the approval policy's. Anything the two cannot express
    (a denied `bash`, a denied `webfetch`, a denied `skill`, or a denied
    `task`) refuses rather than silently defaulting to permissive.
    """
    keys = dict(posture.get("keys") or {})
    notes: list[str] = []
    for key in ("bash", "webfetch", "skill", "task"):
        if keys.get(key) == "deny":
            raise PostureTranslationError(
                "PERMISSION_POSTURE_UNEXPRESSIBLE",
                f"codex has no per-tool deny for {key}; its sandbox modes are "
                "directory-scoped", key=key,
            )
    writes_denied = keys.get("edit") == "deny"
    if keys.get("external_directory") == "deny":
        writes_denied = True
    sandbox_mode = "read-only" if writes_denied else "workspace-write"
    gated = [key for key in TOOL_KEYS if keys.get(key) == "ask"]
    if gated:
        approval_policy = "untrusted" if set(gated) >= {"bash"} else "on-request"
        notes.append(
            f"asking on {sorted(gated)} maps to the approval policy "
            f"{approval_policy!r}; codex gates commands, not per-tool actions"
        )
    else:
        approval_policy = "on-request"
    if not writes_denied and keys.get("external_directory") == "ask":
        notes.append("external_directory=ask is not separable from workspace writes here")
    return {"sandboxMode": sandbox_mode, "approvalPolicy": approval_policy,
            "notes": notes}


TRANSLATORS = {"claude-code": translate_claude, "codex": translate_codex}


def translate_posture(posture: Mapping[str, Any], *, harness: str) -> dict[str, Any]:
    """Translate for one family; an unknown family refuses typed."""
    translator = TRANSLATORS.get(harness)
    if translator is None:
        raise PostureTranslationError(
            "PERMISSION_POSTURE_UNEXPRESSIBLE",
            f"no posture translation is declared for {harness!r}",
        )
    return translator(posture)
