"""Order 85: landing a translated posture into a family's *native* config file.

Order 60 decided what a posture means per family; this module decides where it
is written. It is deliberately separate from `posture_translation` for one
reason: stage 1 of this order (
`docs/server-round1/fullstack/posture-config-keys-085.md`) measured the two
families' real settings surfaces and found that 60's output vocabulary is not
the settings-file vocabulary. `allowedTools`/`disallowedTools` are a CLI flag
and an agent front-matter key with no settings.json read point, so writing them
into `settings.json` would be拼ing an unverified key into a real harness config.

Three properties, each one the shape of a gate:

* **pinned keys only** - every key this module can emit is listed in
  `_PINNED_KEYS` with the measurement that pinned it, and nothing else is
  reachable from any input;
* **never looser** - the write is monotone in strictness both ways: no looser
  than the posture, and no looser than the file it replaces. A permissive
  posture therefore writes *less*, never more;
* **refuse, don't approximate** - an unpinned family, an unknown key, an
  unknown action, an unparseable base file or a base carrying a shape this
  release rejects all raise :class:`PostureConfigError`. Neither harness
  rejects an unknown key of its own (measured), so this refusal is the only
  thing standing between a typo and a silently ignored posture.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ordessa_server_compat.profiles.permissions import ACTIONS, TOOL_KEYS

#: The families with a first-hand pinned landing site. Anything outside this
#: map is refused: an unpinned family gets no config, not a guessed one.
PINNED_FAMILIES = ("claude-code", "codex")


class PostureConfigError(RuntimeError):
    """A typed refusal of one posture write."""

    def __init__(self, code: str, message: str, *, key: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.key = key


#: claude-code's settings.json tool names per neutral key, measured off the
#: pinned 2.1.270 artifact. `external_directory` has no name of its own: it is
#: directory-scoped, which this write does not invent. The consistency with
#: order 60's flag-level map is a test, not a comment.
_CLAUDE_SETTINGS_TOOLS: dict[str, tuple[str, ...]] = {
    "read": ("Read", "Glob", "Grep"),
    "edit": ("Edit", "Write", "NotebookEdit"),
    "bash": ("Bash",),
    "task": ("Task",),
    "webfetch": ("WebFetch", "WebSearch"),
    "skill": ("Skill",),
}

#: The only claude settings paths this module may touch. `permissions.allow`
#: and `permissions.defaultMode` are reachable in the schema but are *loosening*
#: knobs (an `allow` entry is pre-approval; `defaultMode` sets the floor), and
#: stage 1 measured that both can be overridden by a later-loaded source, so
#: writing them could not even be relied on. They stay unwritable.
_CLAUDE_WRITABLE_PATHS = ("permissions.ask", "permissions.deny")

#: Strictness per codex value, from the resolved values `codex doctor` and
#: `codex debug prompt-input` printed for each (085 stage 1). Higher is
#: stricter. `on-failure` reads as strict-as-`on-request` but is never
#: *written*: on either oracle it is indistinguishable from `on-request`, so
#: emitting it would claim an effect that cannot be shown.
_SANDBOX_STRICTNESS = {"read-only": 3, "workspace-write": 2, "danger-full-access": 1}
_APPROVAL_STRICTNESS = {"untrusted": 3, "on-request": 2, "on-failure": 2, "never": 1}
_WRITABLE_SANDBOX = ("read-only", "workspace-write")
_WRITABLE_APPROVAL = ("untrusted", "on-request")

_KEY_LINE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)\Z")


def _posture_keys(posture: Mapping[str, Any]) -> dict[str, str]:
    """The posture's per-key actions, validated against the closed vocabulary."""
    if not isinstance(posture, Mapping):
        raise PostureConfigError("PERMISSION_POSTURE_INVALID", "posture must be a mapping")
    raw = posture.get("keys")
    if not isinstance(raw, Mapping):
        raise PostureConfigError("PERMISSION_POSTURE_INVALID", "posture has no keys map")
    keys = dict(raw)
    for key, action in keys.items():
        if key not in TOOL_KEYS:
            raise PostureConfigError(
                "POSTURE_CONFIG_UNKNOWN_KEY", f"{key!r} is not a tool key", key=str(key))
        if action not in ACTIONS:
            raise PostureConfigError(
                "POSTURE_CONFIG_UNKNOWN_ACTION",
                f"{action!r} is not an action for {key}", key=key)
    return keys


# ---------------------------------------------------------------- claude-code

def render_claude_settings(posture: Mapping[str, Any], *, base: str) -> dict[str, Any]:
    """The claude user-settings document with this posture's `ask`/`deny` rules.

    `base` is the current file text, so the write is a merge into what is
    already reviewed and on disk rather than a replacement of it: the rules it
    already declares stay (stage 1 measured that claude pools rule lists and
    resolves `deny` > `ask` > `allow`, so dropping one here could not be
    repaired later in the file).
    """
    keys = _posture_keys(posture)
    try:
        document = json.loads(base) if base.strip() else {}
    except ValueError as error:
        raise PostureConfigError(
            "POSTURE_CONFIG_BASE_UNPARSEABLE", f"claude settings json: {error}") from error
    if not isinstance(document, dict):
        raise PostureConfigError(
            "POSTURE_CONFIG_BASE_SHAPE", "claude settings root must be a json object")
    permissions = document.get("permissions")
    if permissions is None:
        permissions = {}
    elif not isinstance(permissions, dict):
        raise PostureConfigError(
            "POSTURE_CONFIG_BASE_SHAPE", "claude settings permissions must be an object")
    for name in ("allow", "ask", "deny"):
        existing = permissions.get(name)
        if existing is not None and not isinstance(existing, list):
            raise PostureConfigError(
                "POSTURE_CONFIG_BASE_SHAPE",
                f"claude permissions.{name} must be an array", key=name)
        if any(not isinstance(rule, str) for rule in (existing or ())):
            # Measured: the harness deletes a non-string rule and reports it.
            # A rule we cannot see is a rule we cannot vouch for, so this write
            # refuses instead of re-emitting a list the harness is about to cut.
            raise PostureConfigError(
                "POSTURE_CONFIG_BASE_SHAPE",
                f"claude permissions.{name} carries a non-string rule", key=name)

    changes: list[dict[str, Any]] = []
    notes: list[str] = []
    added: dict[str, set[str]] = {"ask": set(), "deny": set()}
    written_from = {name: list(permissions.get(name) or [])
                    for name in ("ask", "deny")}
    for key in TOOL_KEYS:
        action = keys.get(key, "ask")
        tools = _CLAUDE_SETTINGS_TOOLS.get(key)
        if tools is None:
            if action == "allow":
                notes.append(f"{key}=allow needs no write")
                continue
            raise PostureConfigError(
                "POSTURE_CONFIG_UNEXPRESSIBLE",
                f"claude settings has no pinned rule name for {key}={action}", key=key)
        if action == "allow":
            # Writing these tools into permissions.allow would pre-approve them;
            # the posture asked for nothing, so the narrower file stays.
            notes.append(f"{key}=allow is not written (would pre-approve)")
            continue
        added["deny" if action == "deny" else "ask"].update(tools)
    # The document is only touched where the merged list really grows, so a
    # posture the file already satisfies leaves the reviewed bytes standing.
    for bucket in ("ask", "deny"):
        standing = sorted(written_from[bucket])
        final = sorted(set(written_from[bucket]) | added[bucket])
        if final != standing:
            permissions[bucket] = final
            changes.append({"path": f"permissions.{bucket}",
                            "before": written_from[bucket], "after": final})
    if changes:
        document["permissions"] = permissions
    return {"text": json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            "harness": "claude-code", "changes": changes, "notes": notes,
            "writablePaths": list(_CLAUDE_WRITABLE_PATHS)}


# ---------------------------------------------------------------------- codex

def _toml_lines(base: str) -> tuple[list[str], int]:
    """The base text and the index its table headers start at.

    Only the region before the first table header is top-level; a key written
    after one would land inside that table, which is a different setting.
    """
    lines = base.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("["):
            return lines, index
    return lines, len(lines)


def _top_level(base: str, name: str) -> str | None:
    lines, head = _toml_lines(base)
    for line in lines[:head]:
        match = _KEY_LINE.fullmatch(line.strip())
        if match and match.group("name") == name:
            value = match.group("value").strip()
            return value.strip("\"'")
    return None


def _codex_implied(keys: Mapping[str, str]) -> tuple[str | None, str | None, list[str]]:
    """The (sandbox_mode, approval_policy) this posture demands, or None.

    None means "this posture does not ask for that knob", which leaves the base
    file's value in place rather than moving it toward permissive.
    """
    notes: list[str] = []
    for key in ("bash", "webfetch", "skill", "task"):
        if keys.get(key) == "deny":
            raise PostureConfigError(
                "POSTURE_CONFIG_UNEXPRESSIBLE",
                f"codex has no per-tool deny for {key}; its sandbox is "
                "directory-scoped", key=key)
    writes_denied = keys.get("edit") == "deny" or keys.get("external_directory") == "deny"
    sandbox = "read-only" if writes_denied else None
    gated = [key for key in TOOL_KEYS if keys.get(key) == "ask"]
    if gated:
        approval = "untrusted" if "bash" in gated else "on-request"
        notes.append(f"asking on {sorted(gated)} is the approval policy "
                     f"{approval!r}; codex gates commands, not per-tool actions")
    else:
        approval = None
    return sandbox, approval, notes


def _stricter(base: str, name: str, wanted: str, scale: Mapping[str, int]) -> tuple[str, str]:
    """The value to write, never looser than what the file already says."""
    current = _top_level(base, name)
    if current is None:
        return wanted, f"{name} written as {wanted!r}"
    if current not in scale:
        raise PostureConfigError(
            "POSTURE_CONFIG_BASE_VALUE",
            f"codex {name}={current!r} is outside the pinned vocabulary", key=name)
    if scale[current] >= scale[wanted]:
        return current, (f"{name} kept at {current!r}: already at least as strict "
                         f"as this posture asks")
    return wanted, f"{name} tightened from {current!r} to {wanted!r}"


def render_codex_config(posture: Mapping[str, Any], *, base: str) -> dict[str, Any]:
    """The codex config.toml text with this posture's top-level scalars.

    Text surgery, not a TOML rewrite: the reviewed file carries comments and
    tables this order must not reorder or reformat, and only two top-level
    scalars are in scope.
    """
    keys = _posture_keys(posture)
    stripped = [line.strip() for line in base.splitlines()]
    for line in stripped:
        if line.startswith("[profiles") or re.fullmatch(r"profile\s*=.*", line):
            # Measured on 0.147.0: an inline profile table makes `--profile`
            # hard-error, so a file carrying one is not a file to extend.
            raise PostureConfigError(
                "POSTURE_CONFIG_BASE_LEGACY_PROFILE",
                "codex config carries a legacy profile selector/table; "
                "0.147.0 rejects it with -p")
    sandbox, approval, notes = _codex_implied(keys)
    lines, head = _toml_lines(base)
    changes: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    for name, wanted, scale, writable in (
        ("sandbox_mode", sandbox, _SANDBOX_STRICTNESS, _WRITABLE_SANDBOX),
        ("approval_policy", approval, _APPROVAL_STRICTNESS, _WRITABLE_APPROVAL),
    ):
        if wanted is None:
            continue
        if wanted not in writable:
            raise PostureConfigError(
                "POSTURE_CONFIG_UNEXPRESSIBLE",
                f"codex {name}={wanted!r} is not a writable pinned value", key=name)
        value, reason = _stricter(base, name, wanted, scale)
        notes.append(reason)
        before = _top_level(base, name)
        if before != value:
            changes.append({"path": name, "before": before, "after": value})
            replacements[name] = value
    if not changes:
        return {"text": base, "harness": "codex", "changes": [], "notes": notes,
                "writablePaths": ["sandbox_mode", "approval_policy"]}
    emitted: set[str] = set()
    out: list[str] = []
    for index, line in enumerate(lines):
        if index >= head:
            break
        match = _KEY_LINE.fullmatch(line.strip())
        if match and match.group("name") in replacements:
            name = match.group("name")
            out.append(f'{name} = "{replacements[name]}"')
            emitted.add(name)
        else:
            out.append(line)
    for name, value in replacements.items():
        if name not in emitted:
            out.append(f'{name} = "{value}"')
    out.extend(lines[head:])
    return {"text": "\n".join(out) + "\n", "harness": "codex", "changes": changes,
            "notes": notes, "writablePaths": ["sandbox_mode", "approval_policy"]}


RENDERERS = {
    "claude-code": render_claude_settings,
    "codex": render_codex_config,
}


def render_posture_config(
    posture: Mapping[str, Any], *, harness: str, base: str,
) -> dict[str, Any]:
    """Render for one family; an unpinned family refuses typed."""
    if harness not in RENDERERS:
        raise PostureConfigError(
            "POSTURE_CONFIG_UNPINNED_HARNESS",
            f"{harness!r} has no first-hand pinned settings key; nothing is written",
        )
    return RENDERERS[harness](posture, base=base)


def write_posture_config(
    posture: Mapping[str, Any], *, harness: str, destination: Path,
) -> dict[str, Any]:
    """Render and land it on `destination`, refusing without touching the file.

    The returned document is the snapshot comparison: `before`/`after` per
    changed path, so a caller (and a gate) can state what the write did to the
    reviewed file instead of trusting it.
    """
    path = Path(destination)
    try:
        base = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        base = ""
    except OSError as error:
        raise PostureConfigError(
            "POSTURE_CONFIG_BASE_UNREADABLE", f"{path}: {error}") from error
    rendered = render_posture_config(posture, harness=harness, base=base)
    if not rendered["changes"]:
        return {**rendered, "written": False, "destination": str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(rendered["text"])
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise PostureConfigError(
            "POSTURE_CONFIG_WRITE_FAILED", f"{path}: {error}") from error
    return {**rendered, "written": True, "destination": str(path)}
