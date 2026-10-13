"""Real Claude Code stream-json runtime channel factory (family ``claude``).

This module owns the native process launch for one AgentUnit. The Claude
family's chosen production adapter is the official Claude Agent SDK
(:class:`ClaudeSdkSession` / :class:`FencedSdkTransport`); the SDK itself runs
the Claude Code CLI as one bidirectional stream-json subprocess
(``-p --input-format stream-json --output-format stream-json --verbose
--permission-prompt-tool stdio``, per the pinned upstream
``subprocess_cli.py``). This factory is that subprocess seam, controlled
directly: the pinned executable is launched over stdio JSONL with the same
explicit bidirectional plan ``native_channel.plan_launch(bidirectional=True)``
publishes, through the shared frozen transport, so the launch/isolation/reclaim
evidence carries to the SDK path. No fallback to any other transport exists.

- Pinned installation: the factory is always constructed with a caller-approved
  absolute executable path and never discovers, falls back or guesses a
  version. An optional ``expected_sha256`` pins the exact observed artifact;
  the resolved real path is recorded. Nothing is ever installed or updated.
- Process isolation (G12): the child environment is rebuilt from scratch under
  the unit's *private root* — ``HOME``/``XDG_*``/``TMPDIR`` pinned inside the
  root, ``CLAUDE_CONFIG_DIR`` pointed at the unit's private Claude config
  directory, documented no-traffic/no-update assertions re-asserted, every
  credential-shaped environment key dropped by the transport, and nothing else
  inherited except ``PATH``. No user login, no user ``~/.claude`` state and no
  ambient credentials are ever read or written by this factory.
- Authority gate: ``open`` accepts only an isolated-roots fact set plus an
  *effect-verified* start fact mapping (``action == "start"``,
  ``query is False``). A read-only query can never open a native process.
- Managed stdin fence: the channel is launched in managed mode and the
  factory's own writer lease is bound before any native call, so every write
  is validated inside the actual write barrier. Revocation denies all
  subsequent writes. The native ``control_request`` handshake is a
  request/receipt pair; no user message is ever sent from here (zero model).
- Lifecycle: an opened channel is closed only through this owner's explicit
  :meth:`close` (reap; the stop effect's tool) or :meth:`release` (records
  release of an already-exited channel; never kills), plus :meth:`close_all`
  for teardown. :meth:`handle` exposes the registry-facing owned-handle
  surface (``is_alive``/``close``) the termination face consumes.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import threading
from typing import Any, Mapping

from ordessa_execution_api.environment.operations import sealed_mapping
from ordessa_execution_agents.harness.transport import LaunchSpec, ProcessChannel
from .stream_json import PROTOCOL, ClaudeCodeClient

PROTOCOL_ID = PROTOCOL

#: The unit root layout this factory accepts. ``cwd`` is the native working
#: directory; ``home`` and ``config`` are the unit-private HOME and the
#: unit-private Claude config directory (``CLAUDE_CONFIG_DIR``).
PRIVATE_ROOT_FIELDS = frozenset({"cwd", "home", "config"})

#: Explicit bidirectional launch plan (native_channel.plan_launch shape; the
#: pinned upstream SDK spawns exactly these flags for its subprocess transport).
MANAGED_LAUNCH_FLAGS = (
    "-p",
    "--output-format", "stream-json",
    "--input-format", "stream-json",
    "--verbose",
    "--permission-prompt-tool", "stdio",
)

#: Documented Claude Code environment assertions re-asserted on the isolated
#: child (telemetry/auto-update/nonessential traffic stay off). ``CLAUDE_CONFIG_DIR``
#: is added per unit from the private root; nothing here is inherited ambient state.
TRAFFIC_ISOLATION_ENV = {
    "DISABLE_TELEMETRY": "1",
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}

#: Start-phase timeout plan applied by the factory-owned client view. The
#: deployment owns these deadlines; callers may only tighten them.
TIMEOUT_FIELDS = frozenset({"handshake", "control"})


class ClaudeRuntimeRefused(RuntimeError):
    code = "CLAUDE_RUNTIME_REFUSED"


def stream_json_argv(executable: str) -> tuple[str, ...]:
    """Pure launch plan for the native bidirectional entry; never executed here."""
    return (executable,) + MANAGED_LAUNCH_FLAGS


def verified_private_roots(private_root_facts: Any) -> Mapping[str, str]:
    """Validate the isolated unit roots and return the sealed canonical facts.

    All three paths must be absolute, normalized, distinct directories under
    one common private root parent, so every child identity directory
    (``HOME``, ``CLAUDE_CONFIG_DIR``, XDG dirs, working directory) stays inside
    the unit's private root. Nothing is created here.
    """
    if (not isinstance(private_root_facts, Mapping)
            or set(private_root_facts) != PRIVATE_ROOT_FIELDS):
        raise ClaudeRuntimeRefused(
            "isolated private root facts require exactly cwd, home and config")
    values: dict[str, str] = {}
    for key in sorted(PRIVATE_ROOT_FIELDS):
        value = private_root_facts[key]
        if (not isinstance(value, str) or not value or not os.path.isabs(value)
                or os.path.normpath(value) != value or "\x00" in value
                or value == "/" or value.startswith("//")
                or any(ord(c) < 32 for c in value)):
            raise ClaudeRuntimeRefused("private root path must be a normalized absolute directory")
        values[key] = value
    real = {key: os.path.realpath(value) for key, value in values.items()}
    if len(set(real.values())) != len(real):
        raise ClaudeRuntimeRefused("private root directories must be distinct")
    parent = os.path.dirname(real["cwd"])
    if not parent or os.path.dirname(real["home"]) != parent or os.path.dirname(real["config"]) != parent:
        raise ClaudeRuntimeRefused("private root directories must share one common root parent")
    values = {key: values[key] for key in ("cwd", "home", "config")}
    try:
        return sealed_mapping(values)
    except (TypeError, ValueError) as error:
        raise ClaudeRuntimeRefused("private root facts are not JSON-encodable") from error


def _verified_executable(executable: Any) -> str:
    if not isinstance(executable, str) or not executable or not os.path.isabs(executable):
        raise ClaudeRuntimeRefused("pinned native executable must be an absolute path")
    try:
        info = os.stat(executable)
    except OSError as error:
        raise ClaudeRuntimeRefused("pinned native executable is missing") from error
    if not stat.S_ISREG(info.st_mode) or not os.access(executable, os.X_OK):
        raise ClaudeRuntimeRefused("pinned native executable is not a runnable regular file")
    return executable


def _artifact_digest(executable: str) -> str:
    checksum = hashlib.sha256()
    try:
        with open(executable, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
    except OSError as error:
        raise ClaudeRuntimeRefused("pinned native executable could not be read") from error
    return "sha256:" + checksum.hexdigest()


def _verified_digest(executable: str, expected: Any) -> str:
    """Pin the exact observed artifact when a caller-approved digest is given."""
    if expected is None:
        return _artifact_digest(executable)
    if (not isinstance(expected, str) or not expected.startswith("sha256:")
            or len(expected) != 71 or any(c not in "0123456789abcdef" for c in expected[7:])):
        raise ClaudeRuntimeRefused("expected artifact digest must be a sha256: hex ref")
    digest = _artifact_digest(executable)
    if digest != expected:
        raise ClaudeRuntimeRefused("pinned native executable digest differs from the admitted artifact")
    return digest


def _verified_timeouts(timeouts: Any) -> dict[str, float]:
    plan = {"control": 10.0, "handshake": 30.0}
    if timeouts is None:
        return plan
    if not isinstance(timeouts, Mapping) or not set(timeouts) <= TIMEOUT_FIELDS:
        raise ClaudeRuntimeRefused(f"start timeout plan accepts only {sorted(TIMEOUT_FIELDS)}")
    for key, value in timeouts.items():
        if type(value) not in (int, float) or isinstance(value, bool) or not 0 < value < float("inf"):
            raise ClaudeRuntimeRefused("start timeout plan requires finite positive deadlines")
        plan[key] = float(value)
    return {key: plan[key] for key in sorted(plan)}


def version_facts(executable: str, *, home: str, cwd: str, timeout: float = 60.0) -> Mapping[str, Any]:
    """Real ``--version`` fact probe of the pinned installation.

    One isolated child (clean environment rooted at ``home``, credentials
    dropped, stdin at EOF), captured output, no interpretation: the recorded
    exit code and stdout are the observed facts, never a claimed version.
    """
    _verified_executable(executable)
    if type(timeout) not in (int, float) or isinstance(timeout, bool) or not 0 < timeout < float("inf"):
        raise ClaudeRuntimeRefused("version probe timeout must be finite and positive")
    spec = LaunchSpec.build([executable, "--version"], home=home, cwd=cwd)
    try:
        completed = subprocess.run(  # noqa: S603 - argv is the caller-pinned executable
            list(spec.argv), cwd=spec.cwd, env=dict(spec.env),
            stdin=subprocess.DEVNULL, capture_output=True, timeout=float(timeout))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise ClaudeRuntimeRefused("pinned native version probe could not run") from error
    return sealed_mapping({
        "exitCode": int(completed.returncode),
        "stdout": completed.stdout.decode("utf-8", errors="replace"),
        "stderr": completed.stderr.decode("utf-8", errors="replace"),
    })


class _StartPlanClient:
    """Factory-owned view of one launched client with the factory timeout plan.

    Only the start-edge deadlines are fixed here; everything else (record
    ledger, permission surface, ``_channel``) is delegated unchanged to the
    real :class:`ClaudeCodeClient`, so this view never re-sends or duplicates
    anything. No user-message edge is offered by the factory path at all.
    """

    __slots__ = ("_client", "_timeouts")

    def __init__(self, client: ClaudeCodeClient, timeouts: Mapping[str, float]):
        self._client = client
        self._timeouts = sealed_mapping(timeouts)

    @staticmethod
    def _deadline(caller: Any, plan: float) -> float:
        if caller is None:
            return plan
        if type(caller) not in (int, float) or isinstance(caller, bool) or not 0 < caller < float("inf"):
            raise ValueError("timeout must be finite and positive")
        return min(float(caller), plan)  # the plan owns the edge; callers may only tighten

    def initialize_control(self, *, timeout: Any = None) -> Mapping[str, Any]:
        return self._client.initialize_control(timeout=self._deadline(timeout, self._timeouts["handshake"]))

    def interrupt(self, *, timeout: Any = None) -> Mapping[str, Any]:
        return self._client.interrupt(timeout=self._deadline(timeout, self._timeouts["control"]))

    def __getattr__(self, name: str) -> Any:
        # __slots__ classes only reach here for delegated attributes.
        return getattr(self._client, name)


class ChannelRecord:
    """Trusted owner record of one opened native channel; never durable truth."""

    __slots__ = ("entry", "client", "channel", "lease", "spec", "roots")

    def __init__(self, entry, client, channel, lease, spec, roots):
        self.entry, self.client, self.channel = entry, client, channel
        self.lease, self.spec, self.roots = lease, spec, roots


class RealProcessHandle:
    """Registry-facing owned handle of one real launched channel process.

    This is the surface the frozen ownership registry and termination face
    consume (``is_alive``/``close(timeout=...)``), bound by identity to the
    factory's actual :class:`ProcessChannel`. ``close`` runs the real reap
    sequence (stdin close, then terminate, then kill, each awaited by
    identity) and the observed exit code is the subprocess's own.
    """

    def __init__(self, channel: ProcessChannel):
        if not isinstance(channel, ProcessChannel):
            raise ClaudeRuntimeRefused("a real owned process channel is required")
        self._channel = channel

    @property
    def pid(self) -> int:
        return self._channel._process.pid

    @property
    def exit_code(self) -> int | None:
        return self._channel._process.returncode

    def is_alive(self) -> bool:
        return self._channel._process.poll() is None

    def close(self, *, timeout: float = 5.0) -> int:
        code = self._channel.close(timeout=timeout)
        return code if isinstance(code, int) else -1


class ClaudeStreamChannelFactory:
    """Real runtime channel factory for the claude stream-json family."""

    def __init__(self, executable: str, *, expected_sha256: str | None = None,
                 name: str = "claude-code", timeouts: Mapping[str, float] | None = None):
        self.executable = _verified_executable(executable)
        self.realpath = os.path.realpath(self.executable)
        self.artifact_sha256 = _verified_digest(self.executable, expected_sha256)
        self.pathname = name if isinstance(name, str) and name and len(name) <= 128 else "claude-code"
        self.timeouts = _verified_timeouts(timeouts)
        self._records: dict[int, ChannelRecord] = {}
        self._lock = threading.RLock()
        self.opens = 0

    def open(self, private_root_facts, verified_start_facts) -> _StartPlanClient:
        """Launch the pinned installation isolated under the unit private root.

        This runs the real native binary: the caller must already hold the
        verified start authority (the provider revalidates again before every
        edge). Discovery, fallback, user login/config/credentials and model
        turns do not exist on this path — no user-message edge is reachable
        through this factory's view, and the unit-private config directory is
        the only state the child can ever create.
        """
        roots = verified_private_roots(private_root_facts)
        if (not isinstance(verified_start_facts, Mapping)
                or verified_start_facts.get("action") != "start"
                or verified_start_facts.get("query") is not False):
            raise ClaudeRuntimeRefused(
                "native channel open requires a verified effect start, never a read-only query")
        try:
            # An empty unit-owned CLAUDE_CONFIG_DIR only; no user config or
            # login exists here and none is ever looked up.
            os.makedirs(roots["config"], exist_ok=True)
        except OSError as error:
            raise ClaudeRuntimeRefused("unit private Claude config directory could not be provisioned") from error
        spec = LaunchSpec.build(
            list(stream_json_argv(self.executable)),
            home=roots["home"],
            cwd=roots["cwd"],
            extra_env={"CLAUDE_CONFIG_DIR": roots["config"], **TRAFFIC_ISOLATION_ENV},
        )
        try:
            channel = ProcessChannel.launch(spec, name=self.pathname, managed=True)
        except OSError as error:
            raise ClaudeRuntimeRefused("native claude stream-json process could not be launched") from error
        lease = channel.acquire_writer()
        client = ClaudeCodeClient(channel.bind_writer(lease), name=self.pathname, bidirectional=True)
        entry = _StartPlanClient(client, self.timeouts)
        with self._lock:
            self.opens += 1
            self._records[id(entry)] = ChannelRecord(entry, client, channel, lease, spec, roots)
        return entry

    # -- trusted-owner lifecycle ------------------------------------------
    def record(self, entry) -> ChannelRecord:
        with self._lock:
            record = self._records.get(id(entry))
        if record is None or record.entry is not entry:
            raise ClaudeRuntimeRefused("native channel record belongs to another factory view")
        return record

    def handle(self, entry) -> RealProcessHandle:
        """Registry-facing owned handle of this opened real channel."""
        return RealProcessHandle(self.record(entry).channel)

    def close(self, entry, *, timeout: float = 15.0) -> int:
        """Reap exactly this owned channel's process by identity (G6/G8).

        This is the real stop effect's tool: stdin close, then terminate, then
        kill, each awaited by identity. The record itself is KEPT so the
        termination evidence can still be verified against the actual exited
        handle; :meth:`release` performs the record release afterwards.
        """
        record = self.record(entry)
        try:
            record.client.close()  # disconnect the consumer view only
            code = record.channel.close(timeout=timeout)
            if not isinstance(code, int) and record.channel._process.poll() is None:
                try:
                    code = record.channel._process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    record.channel._process.kill()
                    code = record.channel._process.wait(timeout=timeout)
            return code if isinstance(code, int) else -1
        finally:
            record.channel.fence_all()

    def release(self, entry) -> Mapping[str, int]:
        """Release the owned channel record of an already-exited process.

        Refuses while the native process is still running: killing is the
        stop effect only — release never terminates (A14) and never fakes a
        stop. Returns the observed process facts for termination evidence.
        """
        record = self.record(entry)
        process = record.channel._process
        code = process.poll()
        if code is None:
            raise ClaudeRuntimeRefused("owned native process is still running; stop the unit first")
        with self._lock:
            self._records.pop(id(entry), None)
        return sealed_mapping({"pid": process.pid, "exitCode": int(code)})

    def close_all(self, *, timeout: float = 15.0) -> int:
        """Explicit owner shutdown of every channel this factory opened."""
        with self._lock:
            entries = [record.entry for record in list(self._records.values())]
        total = 0
        for entry in entries:
            try:
                total += self.close(entry, timeout=timeout)
            finally:
                with self._lock:
                    self._records.pop(id(entry), None)
        return total
