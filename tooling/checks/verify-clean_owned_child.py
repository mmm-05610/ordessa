#!/usr/bin/env python3
"""Run one verifier child in an owned session and reap its process group."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_CHILD: subprocess.Popen[bytes] | None = None
_REQUESTED_SIGNAL: int | None = None
_SIGNAL_SENT_AT: float | None = None


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _on_signal(signum: int, _frame: Any) -> None:
    global _REQUESTED_SIGNAL, _SIGNAL_SENT_AT
    if _REQUESTED_SIGNAL is None:
        _REQUESTED_SIGNAL = signum
        _SIGNAL_SENT_AT = time.monotonic()
        if _CHILD is not None:
            _signal_group(_CHILD.pid, signum)


def _wait_for_group_exit(pgid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while _group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not _group_exists(pgid)


def _finish_group(pgid: int, requested_signal: int | None) -> tuple[bool, bool, bool]:
    """Return (all_gone, had_remaining_members, forced_kill) for this owned group."""
    had_remaining_members = _group_exists(pgid)
    forced_kill = False
    if had_remaining_members:
        if requested_signal is None:
            _signal_group(pgid, signal.SIGTERM)
        if not _wait_for_group_exit(pgid, 5.0):
            forced_kill = True
            _signal_group(pgid, signal.SIGKILL)
            if not _wait_for_group_exit(pgid, 5.0):
                return False, had_remaining_members, forced_kill
    return True, had_remaining_members, forced_kill


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _write_result(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _normal_exit_code(returncode: int) -> int:
    return 128 + abs(returncode) if returncode < 0 else returncode


def run(args: argparse.Namespace) -> int:
    global _CHILD
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)

    command = args.command
    if not command:
        raise ValueError("missing owned child argv after --")
    stdout_path = Path(args.stdout)
    stderr_path = Path(args.stderr)
    result_path = Path(args.result)
    clean_marker = Path(args.clean_marker)
    clean_marker.unlink(missing_ok=True)
    value: dict[str, Any] = {
        "schema": "ordessa.verify-clean-owned-child.v1",
        "argv": command,
        "pid": None,
        "returncode": None,
        "forwarded_signal": None,
        "forced_kill": False,
        "cleanup_complete": False,
    }
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            _CHILD = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            value["pid"] = _CHILD.pid
            if _REQUESTED_SIGNAL is not None:
                _signal_group(_CHILD.pid, _REQUESTED_SIGNAL)
                value["forwarded_signal"] = signal.Signals(_REQUESTED_SIGNAL).name
            escalated = False
            while _CHILD.poll() is None:
                if (_REQUESTED_SIGNAL is not None and not escalated and _SIGNAL_SENT_AT is not None
                        and time.monotonic() - _SIGNAL_SENT_AT >= 5.0):
                    _signal_group(_CHILD.pid, signal.SIGKILL)
                    escalated = True
                    value["forced_kill"] = True
                time.sleep(0.05)
            value["returncode"] = _CHILD.wait()

        if _REQUESTED_SIGNAL is not None:
            value["forwarded_signal"] = signal.Signals(_REQUESTED_SIGNAL).name
        cleanup_complete, had_remaining_members, forced_kill = _finish_group(_CHILD.pid, _REQUESTED_SIGNAL)
        value["cleanup_complete"] = cleanup_complete
        value["had_remaining_members_after_leader_exit"] = had_remaining_members
        value["forced_kill"] = bool(value["forced_kill"] or forced_kill)
        value["completed_at"] = time.time()
        _write_result(result_path, value)
        if cleanup_complete:
            _atomic_write(clean_marker, b"all helper-owned process-group members exited\n")
        if not cleanup_complete:
            return 125
        if value["forced_kill"]:
            return 125
        if _REQUESTED_SIGNAL is not None:
            return 128 + _REQUESTED_SIGNAL
        if had_remaining_members:
            return 125
        return _normal_exit_code(value["returncode"])
    except BaseException as error:
        value["error"] = f"{type(error).__name__}: {error}"
        if _CHILD is not None:
            _signal_group(_CHILD.pid, signal.SIGTERM)
            try:
                value["returncode"] = _CHILD.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                _signal_group(_CHILD.pid, signal.SIGKILL)
                value["forced_kill"] = True
                try:
                    value["returncode"] = _CHILD.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    # Keep this bounded: do not block forever even if an owned child
                    # is stuck in an uninterruptible kernel state.
                    value["returncode"] = _CHILD.returncode
            cleanup_complete, had_remaining_members, forced_kill = _finish_group(_CHILD.pid, _REQUESTED_SIGNAL)
            value["cleanup_complete"] = cleanup_complete
            value["had_remaining_members_after_leader_exit"] = had_remaining_members
            value["forced_kill"] = bool(value["forced_kill"] or forced_kill)
        value["completed_at"] = time.time()
        try:
            _write_result(result_path, value)
            if value["cleanup_complete"]:
                _atomic_write(clean_marker, b"all helper-owned process-group members exited\n")
        except OSError:
            pass
        if _REQUESTED_SIGNAL is not None and value["cleanup_complete"]:
            return 128 + _REQUESTED_SIGNAL
        return 125


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--clean-marker", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
