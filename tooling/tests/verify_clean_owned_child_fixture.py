#!/usr/bin/env python3
"""Controlled, service-free process-supervisor counterexamples; do not run real gates."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


class Controls:
    def __init__(self, helper: Path, root: Path) -> None:
        self.helper = helper
        self.root = root
        self.live: list[tuple[subprocess.Popen[bytes], Path]] = []

    def start(self, name: str, command: list[str]) -> tuple[subprocess.Popen[bytes], Path, Path, Path]:
        stdout = self.root / f"{name}.stdout"
        stderr = self.root / f"{name}.stderr"
        result = self.root / f"{name}.child.json"
        marker = self.root / f"{name}.children-clean"
        proc = subprocess.Popen([
            sys.executable, str(self.helper), "--stdout", str(stdout), "--stderr", str(stderr),
            "--result", str(result), "--clean-marker", str(marker), "--", *command,
        ], start_new_session=True)
        self.live.append((proc, marker))
        return proc, stdout, stderr, result

    def finish(self, name: str, proc: subprocess.Popen[bytes], result_path: Path, timeout: float = 12) -> tuple[int, dict[str, Any]]:
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self.request_cleanup(proc)
            raise AssertionError(f"{name}: supervisor exceeded {timeout}s; TERM sent, result retained") from exc
        result = json.loads(result_path.read_text(encoding="utf-8"))
        return rc, result

    @staticmethod
    def request_cleanup(proc: subprocess.Popen[bytes]) -> bool:
        """Ask the owned supervisor to forward TERM; never kill it directly."""
        if proc.poll() is not None:
            return True
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=12)
            return True
        except subprocess.TimeoutExpired:
            return False

    def cleanup_live(self) -> list[int]:
        unresolved: list[int] = []
        for proc, _marker in self.live:
            if proc.poll() is None and not self.request_cleanup(proc):
                unresolved.append(proc.pid)
        return unresolved


def shell_heredoc(controls: Controls, name: str, payload: bytes, expected_rc: int) -> None:
    helper, root = controls.helper, controls.root
    pidfile = root / f"{name}.helper.pid"
    stdout, stderr = root / f"{name}.stdout", root / f"{name}.stderr"
    result, marker = root / f"{name}.child.json", root / f"{name}.children-clean"
    script = r'''set -u
helper=$1; root=$2; name=$3
run_owned() {
  local input_fd
  exec {input_fd}<&0
  python3 "$helper" --stdout "$root/$name.stdout" --stderr "$root/$name.stderr" \
    --result "$root/$name.child.json" --clean-marker "$root/$name.children-clean" -- \
    python3 -c 'import sys; data=sys.stdin.read(); sys.stdout.write(data); sys.exit(19 if data.startswith("FAIL:") else 0)' <&"$input_fd" &
  child=$!
  printf '%s\n' "$child" >"$root/$name.helper.pid"
  wait "$child"; rc=$?
  exec {input_fd}<&-
  exit "$rc"
}
run_owned <<'PAYLOAD'
''' + payload.decode("ascii") + r'''PAYLOAD
'''
    shell = subprocess.Popen(
        ["bash", "--noprofile", "--norc", "-c", script, "fixture", str(helper), str(root), name],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        rc = shell.wait(timeout=12)
    except subprocess.TimeoutExpired as exc:
        if pidfile.is_file():
            try:
                helper_pid = int(pidfile.read_text().strip())
                os.kill(helper_pid, signal.SIGTERM)
            except (OSError, ValueError):
                pass
        else:
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not pidfile.is_file():
                time.sleep(.02)
            if pidfile.is_file():
                try:
                    os.kill(int(pidfile.read_text().strip()), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
            else:
                # No helper PID was published; signal only this fixture wrapper.
                shell.send_signal(signal.SIGTERM)
        try:
            shell.wait(timeout=24)
        except subprocess.TimeoutExpired:
            # Preserve shell/helper/process facts; never kill the supervisor.
            raise AssertionError(f"{name}: wrapper timeout; TERM requested from recorded helper") from exc
        raise AssertionError(f"{name}: wrapper exceeded initial timeout; cleanup was requested") from exc
    if rc != expected_rc or not result.is_file() or not marker.is_file():
        raise AssertionError(f"{name}: heredoc outcome/clean marker mismatch: rc={rc}")
    value = json.loads(result.read_text(encoding="utf-8"))
    if value.get("returncode") != expected_rc:
        raise AssertionError(f"{name}: helper lost heredoc child exit code: {value}")
    if (root / f"{name}.stdout").read_bytes() != payload:
        raise AssertionError(f"{name}: heredoc bytes were not delivered intact")


def enable_fixture_subreaper() -> None:
    """Adopt and reap the detached test grandchild after its leader exits (Linux)."""
    if sys.platform != "linux":
        raise RuntimeError("controlled orphan-reaping fixture requires Linux PR_SET_CHILD_SUBREAPER")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def reap_adopted(pid: int, done: threading.Event, status: list[int | None]) -> None:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            waited, wait_status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                status.append(wait_status)
                done.set()
                return
        except ChildProcessError:
            # The child is still owned by its live parent, or not yet orphaned.
            pass
        time.sleep(.02)
    done.set()


def wait_for(*paths: Path, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(path.is_file() for path in paths):
            return True
        time.sleep(.02)
    return all(path.is_file() for path in paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--helper", required=True, type=Path)
    parser.add_argument("--owned-root", required=True, type=Path)
    args = parser.parse_args()
    helper = args.helper.resolve(strict=True)
    root = args.owned_root
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    enable_fixture_subreaper()
    controls = Controls(helper, root)
    try:
        normal_code = "import sys; print('normal stdout'); print('normal stderr', file=sys.stderr)"
        proc, stdout, stderr, result_path = controls.start("normal", [sys.executable, "-c", normal_code])
        rc, result = controls.finish("normal", proc, result_path)
        if rc != 0 or result.get("returncode") != 0 or result.get("cleanup_complete") is not True:
            raise AssertionError(f"normal completion mismatch: rc={rc}, result={result}")
        if stdout.read_bytes() != b"normal stdout\n" or stderr.read_bytes() != b"normal stderr\n":
            raise AssertionError("normal child raw stdout/stderr mismatch")

        failed_code = "import sys; print('failure stdout'); print('failure stderr', file=sys.stderr); raise SystemExit(23)"
        proc, stdout, stderr, result_path = controls.start("child-failure", [sys.executable, "-c", failed_code])
        rc, result = controls.finish("child-failure", proc, result_path)
        if rc != 23 or result.get("returncode") != 23 or result.get("cleanup_complete") is not True:
            raise AssertionError(f"nonzero child exit mismatch: rc={rc}, result={result}")
        if stdout.read_bytes() != b"failure stdout\n" or stderr.read_bytes() != b"failure stderr\n":
            raise AssertionError("failed child's raw stdout/stderr mismatch")

        shell_heredoc(controls, "heredoc-success", b"PASS: heredoc reached child\n", 0)
        shell_heredoc(controls, "heredoc-failure", b"FAIL: heredoc reached child\n", 19)

        # TERM cannot stop this child. The supervisor must escalate only its owned
        # session, report forced_kill, retain the leader's signal return code, and
        # publish a clean marker only after the process is gone.
        stubborn_code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
        proc, stdout, _stderr, result_path = controls.start("forced-escalation", [sys.executable, "-c", stubborn_code])
        ready_deadline = time.monotonic() + 3
        while time.monotonic() < ready_deadline and (not stdout.is_file() or stdout.read_bytes() != b"ready\n"):
            time.sleep(.02)
        if not stdout.is_file() or stdout.read_bytes() != b"ready\n":
            controls.request_cleanup(proc)
            raise AssertionError("forced-escalation child did not reach its ready state")
        proc.send_signal(signal.SIGTERM)
        rc, result = controls.finish("forced-escalation", proc, result_path, timeout=12)
        if rc != 125 or result.get("forced_kill") is not True or result.get("cleanup_complete") is not True:
            raise AssertionError(f"forced escalation was not reported fail-closed: rc={rc}, result={result}")
        if result.get("returncode") != -signal.SIGKILL:
            raise AssertionError(f"raw leader SIGKILL return code missing: {result}")

        # Counterexample: leader exits 17 while a child remains in its owned group.
        # The supervisor must TERM that child, mark the suite failed (125), and
        # preserve raw leader rc 17. The fixture adopts/reaps the orphan by exact PID.
        child_script = root / "residual-child.py"
        parent_script = root / "residual-parent.py"
        started = root / "residual-child.started"
        ended = root / "residual-child.ended"
        child_pidfile = root / "residual-child.pid"
        child_script.write_text(
            "import signal,sys,time\nfrom pathlib import Path\n"
            "started=Path(sys.argv[1]); ended=Path(sys.argv[2])\n"
            "def stop(_sig,_frame): ended.write_text('ended\\n'); raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM,stop)\nstarted.write_text('ready\\n')\nwhile True: time.sleep(.05)\n",
            encoding="utf-8",
        )
        parent_script.write_text(
            "import subprocess,sys,time\nfrom pathlib import Path\n"
            "p=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2],sys.argv[3]])\n"
            "Path(sys.argv[4]).write_text(str(p.pid))\n"
            "end=time.monotonic()+3\n"
            "while time.monotonic()<end and not Path(sys.argv[2]).is_file(): time.sleep(.01)\n"
            "if not Path(sys.argv[2]).is_file(): raise SystemExit(91)\n"
            "raise SystemExit(17)\n",
            encoding="utf-8",
        )
        proc, _stdout, _stderr, result_path = controls.start(
            "leader-residual-child", [sys.executable, str(parent_script), str(child_script), str(started), str(ended), str(child_pidfile)],
        )
        if not wait_for(child_pidfile, started, timeout=5):
            controls.request_cleanup(proc)
            raise AssertionError("residual child startup markers did not both arrive")
        child_pid = int(child_pidfile.read_text().strip())
        reaped = threading.Event()
        reap_status: list[int | None] = []
        reaper = threading.Thread(target=reap_adopted, args=(child_pid, reaped, reap_status), daemon=True)
        reaper.start()
        rc, result = controls.finish("leader-residual-child", proc, result_path, timeout=12)
        reaper.join(timeout=12)
        if not reaped.is_set() or not reap_status:
            raise AssertionError("residual grandchild was not reaped by the fixture subreaper")
        if rc != 125 or result.get("returncode") != 17 or result.get("cleanup_complete") is not True:
            raise AssertionError(f"leader residual child was hidden/accepted: rc={rc}, result={result}")
        if result.get("had_remaining_members_after_leader_exit") is not True:
            raise AssertionError(f"supervisor failed to recognize residual owned child: {result}")
        if not (ended.is_file() and ended.read_text() == "ended\n"):
            raise AssertionError("residual owned child did not finish before clean marker")

        for name in ("normal", "child-failure", "heredoc-success", "heredoc-failure", "forced-escalation", "leader-residual-child"):
            marker = root / f"{name}.children-clean"
            if not marker.is_file():
                raise AssertionError(f"{name}: missing owned-process clean marker")
        print("PASS normal and nonzero child raw exits/streams preserved")
        print("PASS actual Bash heredoc bytes and rc 0/19 preserved")
        print("PASS stubborn child escalated to KILL and gate rejected with rc 125")
        print("PASS leader rc 17 with residual owned child rejected and child reaped")
        return 0
    finally:
        unresolved = controls.cleanup_live()
        if unresolved:
            print(f"FAIL: supervisors did not stop after bounded TERM; evidence retained at {root}; pids={unresolved}", file=sys.stderr)
            raise RuntimeError("owned supervisors remained live; fixture cannot report PASS")


if __name__ == "__main__":
    raise SystemExit(main())
