"""Order 62: the workspace's Git status - read-only, bounded, typed.

The product shows six fields: `branch`, `changedFiles`, `additions`,
`deletions`, `ahead`, `behind`. Every one of them may be **null**, and null
means "not obtainable" - never zero. Three disciplines make that honest:

* **machine-readable input only**: `git --no-optional-locks status
  --porcelain=v2 --branch` for the branch and the changed-file count,
  `git --no-optional-locks diff --numstat HEAD` for the line counts. No regex
  over human output, and `--no-optional-locks` is what keeps the query from
  refreshing (writing) the index while another process is using the repo;
* **bounded**: a hard timeout and a hard output cap; exceeding either is a
  typed refusal, never a truncated number that looks complete;
* **a reason instead of a guess**: "not a repository", "no commits yet",
  "binary diff present" (line counts are not obtainable) and every failure
  mode carry a typed code, and the unavailable fields stay null.

Nothing here writes the workspace: both commands are read-only, and the
caller's argv is fixed in this module.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

#: The two commands, fixed here: a caller never supplies argv.
STATUS_ARGV = ("--no-optional-locks", "status", "--porcelain=v2", "--branch")
NUMSTAT_ARGV = ("--no-optional-locks", "diff", "--numstat", "HEAD")
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_BYTES = 256 * 1024

REASONS = (
    "GIT_UNAVAILABLE", "GIT_NOT_A_REPOSITORY", "GIT_TIMEOUT", "GIT_OUTPUT_LIMIT",
    "GIT_PARSE_FAILED", "GIT_NO_COMMITS", "GIT_BINARY_DIFF", "GIT_WORKSPACE_MISSING",
)


@dataclass
class GitStatus:
    """The six fields, each nullable, plus the reason for the nulls."""

    branch: str | None = None
    changed_files: int | None = None
    additions: int | None = None
    deletions: int | None = None
    ahead: int | None = None
    behind: int | None = None
    reason: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_wire(self) -> dict:
        return {
            "branch": self.branch,
            "changedFiles": self.changed_files,
            "additions": self.additions,
            "deletions": self.deletions,
            "ahead": self.ahead,
            "behind": self.behind,
            "reason": self.reason,
        }


def parse_porcelain_v2(stdout: bytes) -> tuple[str | None, int | None, int | None, int | None]:
    """(branch, changedFiles, ahead, behind) from one porcelain v2 output.

    Header lines start with `#`; entries (changed files) start with `1`, `2`,
    `u` or `?`. `# branch.ab +A -B` carries ahead/behind and is absent when no
    upstream is configured - which is exactly when both stay null.
    """
    branch: str | None = None
    ahead: int | None = None
    behind: int | None = None
    changed = 0
    text = stdout.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):].strip()
            # Porcelain v2 reports `(detached)` for a detached head: that is a
            # real state, and it is not a branch name.
            branch = None if head == "(detached)" else head
        elif line.startswith("# branch.ab "):
            parts = line.split()
            if len(parts) != 4 or not parts[2].startswith(("+", "-")):
                raise ValueError("GIT_PARSE_FAILED: malformed branch.ab line")
            ahead = int(parts[2][1:])
            behind = int(parts[3][1:])
        elif line[:1] in {"1", "2", "u", "?"}:
            changed += 1
        elif line.startswith("#"):
            continue
        else:
            raise ValueError("GIT_PARSE_FAILED: unknown porcelain v2 line")
    return branch, changed, ahead, behind


def parse_numstat(stdout: bytes) -> tuple[int, int, bool]:
    """(additions, deletions, has_binary) from one `diff --numstat` output."""
    additions = 0
    deletions = 0
    has_binary = False
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            raise ValueError("GIT_PARSE_FAILED: malformed numstat line")
        if parts[0] == "-" or parts[1] == "-":
            has_binary = True
            continue
        additions += int(parts[0])
        deletions += int(parts[1])
    return additions, deletions, has_binary


def _run_git(
    path: str, argv: tuple[str, ...], *, timeout: float, max_bytes: int,
) -> tuple[bytes, str | None]:
    """Run one fixed git command with a *streaming* byte cap and a deadline.

    Reading through `subprocess.run` would consume a flooding command's output
    before any bound applied; here the read is bounded as it goes, and the
    child is killed the moment either bound is crossed.
    """
    import selectors
    import signal

    command = ["git", "-C", path, *argv]
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        return b"", "GIT_UNAVAILABLE"
    deadline = time.monotonic() + timeout
    collected = bytearray()
    reason: str | None = None
    try:
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 and process.poll() is None:
                    reason = "GIT_TIMEOUT"
                    break
                if not selector.select(timeout=max(remaining, 0.0) or 0.05):
                    if process.poll() is not None:
                        break
                    if time.monotonic() >= deadline:
                        reason = "GIT_TIMEOUT"
                        break
                    continue
                chunk = process.stdout.read1(min(8192, max_bytes + 1 - len(collected)))
                if not chunk:
                    break
                collected.extend(chunk)
                if len(collected) > max_bytes:
                    reason = "GIT_OUTPUT_LIMIT"
                    break
        finally:
            selector.close()
    finally:
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if process.stdout is not None:
            process.stdout.close()
    if reason is not None:
        return b"", reason
    return bytes(collected), None


def local_git_status(
    path: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> GitStatus:
    """The status of one workspace on this machine."""
    if not isinstance(path, str) or not path or not os.path.isdir(path):
        return GitStatus(reason="GIT_WORKSPACE_MISSING", reasons=("GIT_WORKSPACE_MISSING",))
    status_out, reason = _run_git(path, STATUS_ARGV, timeout=timeout, max_bytes=max_bytes)
    if reason is not None:
        return GitStatus(reason=reason, reasons=(reason,))
    try:
        branch, changed, ahead, behind = parse_porcelain_v2(status_out)
    except (ValueError, TypeError):
        return GitStatus(reason="GIT_PARSE_FAILED", reasons=("GIT_PARSE_FAILED",))
    if branch is None and changed == 0 and ahead is None and behind is None:
        # No header at all: the path is inside a git repo or not; `status`
        # answers `fatal: not a git repository` on stderr and prints nothing.
        return GitStatus(reason="GIT_NOT_A_REPOSITORY", reasons=("GIT_NOT_A_REPOSITORY",))

    reasons: list[str] = []
    additions = deletions = None
    numstat_out, numstat_reason = _run_git(
        path, NUMSTAT_ARGV, timeout=timeout, max_bytes=max_bytes)
    if numstat_reason == "GIT_TIMEOUT":
        reasons.append("GIT_TIMEOUT")
    elif numstat_reason == "GIT_OUTPUT_LIMIT":
        reasons.append("GIT_OUTPUT_LIMIT")
    elif numstat_reason == "GIT_UNAVAILABLE":
        reasons.append("GIT_UNAVAILABLE")
    else:
        try:
            total_add, total_del, has_binary = parse_numstat(numstat_out)
        except (ValueError, TypeError):
            reasons.append("GIT_PARSE_FAILED")
        else:
            if has_binary:
                # A binary file's line counts do not exist; summing the rest
                # would look like a complete number. Null it, with the reason.
                reasons.append("GIT_BINARY_DIFF")
            else:
                additions, deletions = total_add, total_del
    return GitStatus(
        branch=branch, changed_files=changed, additions=additions, deletions=deletions,
        ahead=ahead, behind=behind,
        reason=reasons[0] if reasons else None, reasons=tuple(reasons),
    )
