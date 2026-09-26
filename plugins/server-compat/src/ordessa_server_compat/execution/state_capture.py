"""The audit rules for one Profile's native home, independent of the channel.

Under the native-home model the Server never carries the Harness's state
bytes: the home directory on the machine that runs the turn is the only
source of truth. What remains here is the discipline an audit must keep -
the bounded window, the protected read-only paths, the attempt-ephemeral
prefixes, and the fail-closed credential scan - stated once, with two
channel-supplied parameters: how the declared subtree is listed, and how one
file is read.

An audit that finds something outside its bounds reports the fact
(`truncated`) instead of failing the turn: nothing is uploaded any more, so
an over-large home is a bookkeeping fact about the home, not a broken
execution. The one remaining hard refusal is credential material: an
injected one-shot value that reached the home means the projection leaked,
and that is a typed failure naming the file.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

#: One audited file may not exceed this many bytes.
MAX_AUDIT_FILE_BYTES = 8 * 1024 * 1024
#: One audit may cover this many files, and this many digested bytes.
MAX_AUDIT_FILES = 1024
MAX_AUDIT_TOTAL_BYTES = 64 * 1024 * 1024

Listing = Sequence[Mapping[str, Any]]
Read = Callable[[str], tuple[bytes, str]]


class StateCaptureError(RuntimeError):
    """A typed refusal from the audit rules; ``code`` names the boundary."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        # The relative path that carried the refusal - the credential rule
        # needs exactly this to delete the one file that leaked and nothing
        # else. The message never carries the matched material itself.
        self.path = path


def _matches_ephemeral_prefix(relative: str, prefixes: Sequence[str]) -> bool:
    return any(relative == prefix or relative.startswith(prefix + "/") for prefix in prefixes)


def _safe_relative_state_path(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/") or "\\" in value
            or "\x00" in value or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise StateCaptureError("SIDECAR_STATE_PATH_INVALID", "state path is not a bounded relative path")
    return value


def audit_snapshot(
    listing: Listing, read: Read, *,
    protected_state_paths: Sequence[str] = (),
    state_ephemeral_paths: Sequence[str] = (),
    forbidden_content: bytes = b"",
    truncated: Mapping[str, int] | None = None,
    skipped: int = 0,
) -> dict[str, Any]:
    """Audit the declared home window and return the manifest's facts.

    The listing is window-relative (`{path, size}` at least; the Worker channel
    also supplies a per-file digest). Every declared, in-bounds file is read
    once - not to keep the bytes, but because the credential scan is
    fail-closed and must look at what is actually there. Protected read-only
    configuration and attempt-ephemeral scratch are not state and are excluded
    by name.
    """
    protected = frozenset(protected_state_paths)
    files: list[dict[str, Any]] = []
    total = 0
    for item in listing:
        path = item.get("path")
        size = item.get("size")
        if not isinstance(path, str) or not path:
            continue
        relative = _safe_relative_state_path(path)
        if relative in protected:
            # Declared read-only configuration, not Harness state.
            continue
        if _matches_ephemeral_prefix(relative, state_ephemeral_paths):
            # Attempt-ephemeral scratch is tmpfs inside the sandbox; it is
            # not state even if a listing catches it mid-flight.
            continue
        if not isinstance(size, int) or size < 0 or size > MAX_AUDIT_FILE_BYTES:
            # A malformed or oversized listing entry is a fact, not a read:
            # count it and move on, exactly as the channel-side bounds do.
            truncated = _bump(truncated, "entries", 1)
            truncated = _bump(truncated, "bytes", max(int(size or 0), 0))
            if isinstance(size, int) and size > MAX_AUDIT_FILE_BYTES:
                truncated = _bump(truncated, "oversize", 1)
            continue
        total += size
        try:
            content, digest_value = read(relative)
        except BaseException as error:  # noqa: BLE001 - classified, not swallowed
            # A file that existed at listing time but cannot be read now
            # (a SQLite WAL reclaimed under the harness's own housekeeping,
            # a name that churned) is an audit fact, not a failed turn: the
            # truncation accounting says it was seen and not audited. The
            # credential scan never silently passes - an unreadable file is
            # reported, never treated as clean.
            code = getattr(error, "code", None)
            if not isinstance(code, str):
                # A codeless failure is a bug in this Server, not home churn.
                raise
            # Any typed per-file refusal (vanished, shrank, an unreadable
            # special file) makes that entry unaudited: reported as a
            # truncation fact, never treated as clean.
            truncated = _bump(truncated, "entries", 1)
            truncated = _bump(truncated, "bytes", size)
            total -= size
            continue
        if forbidden_content and forbidden_content in content:
            raise StateCaptureError(
                "SIDECAR_STATE_CONTAINS_SECRET",
                f"credential material found in native state: {relative}",
                path=relative,
            )
        files.append({"path": relative, "digest": digest_value, "size": len(content)})

    return {
        "files": files,
        "audited": {"files": len(files), "bytes": total,
                    "truncated": dict(truncated or {"entries": 0, "bytes": 0, "oversize": 0})},
        "truncated": dict(truncated or {"entries": 0, "bytes": 0, "oversize": 0}),
        "skipped": skipped,
    }


def _bump(truncated: Mapping[str, int] | None, key: str, amount: int) -> dict[str, int]:
    facts = dict(truncated or {"entries": 0, "bytes": 0, "oversize": 0})
    facts[key] = facts.get(key, 0) + amount
    return facts
