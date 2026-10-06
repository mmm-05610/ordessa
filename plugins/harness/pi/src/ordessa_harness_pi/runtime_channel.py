"""Real Pi native RPC channel factory (family ``pi``, ``pi-rpc/1``).

This module owns the native process launch for one AgentUnit:

- Launch plan: ``<absolute pinned executable> --mode rpc --no-session
  --offline`` plus the minimal isolated no-* flags, over stdio JSONL, per the
  pinned protocol facts in ``client.py``. The factory is always constructed
  with a caller-approved installation path and never discovers, falls back or
  guesses a version.
- Process isolation (G12): the child environment is rebuilt from scratch under
  the unit's *private root* — ``HOME``/``XDG_*``/``TMPDIR`` pinned inside the
  root, ``PI_CODING_AGENT_DIR`` pointed at the unit's private Pi agent
  directory, ``PI_OFFLINE=1`` re-asserted, every credential-shaped environment
  key dropped, and nothing else inherited except ``PATH``. No user login,
  user configuration or ambient credentials are ever read or written by this
  factory (the pinned managed-install launcher keeps resolving its own
  installation relative to the binary path, never to ``HOME``).
- Authority gate: ``open`` accepts only an isolated-roots fact set plus an
  *effect-verified* start fact mapping (``action == "start"``,
  ``query is False``). A read-only query can never open a native process.
- Managed stdin fence: the channel is launched in managed mode and the
  factory's own writer lease is bound before any native call, so every write
  (by provider edges and by consumer leases) is validated inside the actual
  write barrier. Revocation denies all subsequent writes.
- Lifecycle: an opened channel is closed only through this owner's explicit
  :meth:`close` (reap; used by the stop effect) or :meth:`release` (records
  release of an already-exited channel; never kills), plus :meth:`close_all`
  for teardown.
"""
from __future__ import annotations

import os
import stat
import subprocess
import threading
from typing import Any, Mapping

from ordessa_environment_api.operations import safe_json, sealed_mapping
from ordessa_harness_transport import LaunchSpec, ProcessChannel
from ordessa_harness_pi.client import PiRpcClient, rpc_launch_argv

PROTOCOL = "pi-rpc/1"

#: The unit root layout this factory accepts. ``cwd`` is the native working
#: directory; ``home`` and ``piHome`` are the unit-private HOME and the
#: unit-private Pi agent directory (``PI_CODING_AGENT_DIR``).
PRIVATE_ROOT_FIELDS = frozenset({"cwd", "home", "piHome"})

#: Start-phase RPC timeout plan applied by the factory-owned client view. The
#: deployment owns these deadlines; the provider edge sequence stays untouched.
TIMEOUT_FIELDS = frozenset({"handshake", "rpc"})

#: Fixed installation launch plan (client.py pins the flags; never executed here).
RPC_LAUNCH_FLAGS = rpc_launch_argv(offline=True, minimal=True)


class PiChannelRefused(RuntimeError):
    code = "PI_CHANNEL_REFUSED"


def rpc_argv(executable: str) -> tuple[str, ...]:
    """Pure launch plan for the native RPC entry; never executed here."""
    return (executable,) + RPC_LAUNCH_FLAGS[1:]


def verified_private_roots(private_root_facts: Any) -> Mapping[str, str]:
    """Validate the isolated unit roots and return the sealed canonical facts.

    All three paths must be absolute, normalized, distinct directories under
    one common private root parent, so every child identity directory
    (``HOME``, ``PI_CODING_AGENT_DIR``, XDG dirs, working directory) stays
    inside the unit's private root. Nothing is created here.
    """
    if (not isinstance(private_root_facts, Mapping)
            or set(private_root_facts) != PRIVATE_ROOT_FIELDS):
        raise PiChannelRefused(
            "isolated private root facts require exactly cwd, home and piHome")
    values: dict[str, str] = {}
    for key in sorted(PRIVATE_ROOT_FIELDS):
        value = private_root_facts[key]
        if (not isinstance(value, str) or not value or not os.path.isabs(value)
                or os.path.normpath(value) != value or "\x00" in value
                or value == "/" or value.startswith("//")
                or any(ord(c) < 32 for c in value)):
            raise PiChannelRefused("private root path must be a normalized absolute directory")
        values[key] = value
    real = {key: os.path.realpath(value) for key, value in values.items()}
    if len(set(real.values())) != len(real):
        raise PiChannelRefused("private root directories must be distinct")
    parent = os.path.dirname(real["cwd"])
    if not parent or os.path.dirname(real["home"]) != parent or os.path.dirname(real["piHome"]) != parent:
        raise PiChannelRefused("private root directories must share one common root parent")
    values = {key: values[key] for key in ("cwd", "home", "piHome")}
    try:
        return sealed_mapping(values)
    except (TypeError, ValueError) as error:
        raise PiChannelRefused("private root facts are not JSON-encodable") from error


def _verified_executable(executable: Any) -> str:
    if not isinstance(executable, str) or not executable or not os.path.isabs(executable):
        raise PiChannelRefused("pinned native executable must be an absolute path")
    try:
        info = os.stat(executable)
    except OSError as error:
        raise PiChannelRefused("pinned native executable is missing") from error
    if not stat.S_ISREG(info.st_mode) or not os.access(executable, os.X_OK):
        raise PiChannelRefused("pinned native executable is not a runnable regular file")
    return executable


def _verified_timeouts(timeouts: Any) -> dict[str, float]:
    plan = {key: 10.0 for key in sorted(TIMEOUT_FIELDS)}
    if timeouts is None:
        return plan
    if not isinstance(timeouts, Mapping) or not set(timeouts) <= TIMEOUT_FIELDS:
        raise PiChannelRefused(f"start timeout plan accepts only {sorted(TIMEOUT_FIELDS)}")
    for key, value in timeouts.items():
        if type(value) not in (int, float) or isinstance(value, bool) or not 0 < value < float("inf"):
            raise PiChannelRefused("start timeout plan requires finite positive deadlines")
        plan[key] = float(value)
    return plan


class _StartPlanClient:
    """Factory-owned view of one launched client with the factory timeout plan.

    Only the start-edge deadlines are fixed here; everything else (request-id
    ledger, pending RPC receipts, event stream, ``_channel``) is delegated
    unchanged to the real :class:`PiRpcClient`, so this view never re-sends or
    duplicates anything.
    """

    __slots__ = ("_client", "_timeouts")

    def __init__(self, client: PiRpcClient, timeouts: Mapping[str, float]):
        self._client = client
        self._timeouts = sealed_mapping(timeouts)

    def initialize(self) -> Mapping[str, Any]:
        return self._client.initialize(timeout=self._timeouts["handshake"])

    def command(self, command_type: str, timeout: Any = None, **fields: Any) -> Any:
        # The deployment's plan owns the start-edge deadlines; an explicit
        # finite caller deadline (lease view passthrough) may only tighten it.
        plan = self._timeouts["handshake"] if command_type == "get_state" else self._timeouts["rpc"]
        deadline = plan
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and 0 < timeout < plan:
            deadline = float(timeout)
        return self._client.command(command_type, timeout=deadline, **fields)

    def dispatch_prepared(self, frame, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self._timeouts["rpc"])
        return self._client.dispatch_prepared(frame, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # __slots__ classes only reach here for delegated attributes.
        return getattr(self._client, name)


class ChannelRecord:
    """Trusted owner record of one opened native channel; never durable truth."""

    __slots__ = ("entry", "client", "channel", "lease", "spec", "roots")

    def __init__(self, entry, client, channel, lease, spec, roots):
        self.entry, self.client, self.channel = entry, client, channel
        self.lease, self.spec, self.roots = lease, spec, roots


class PiRpcChannelFactory:
    """Real ``ChannelFactoryPort`` implementation for the pi family."""

    def __init__(self, executable: str, *, name: str = "pi-rpc",
                 timeouts: Mapping[str, float] | None = None):
        self.executable = _verified_executable(executable)
        self.pathname = name if isinstance(name, str) and name and len(name) <= 128 else "pi-rpc"
        self.timeouts = _verified_timeouts(timeouts)
        self._records: dict[int, ChannelRecord] = {}
        self._lock = threading.RLock()
        self.opens = 0

    def open(self, private_root_facts, verified_start_facts) -> _StartPlanClient:
        """Launch the pinned installation isolated under the unit private root.

        This runs the real native binary: the caller must already hold the
        verified start authority (the provider revalidates again before every
        edge). Discovery, fallback, user login/config/credentials and model
        turns do not exist on this path.
        """
        roots = verified_private_roots(private_root_facts)
        if (not isinstance(verified_start_facts, Mapping)
                or verified_start_facts.get("action") != "start"
                or verified_start_facts.get("query") is not False):
            raise PiChannelRefused(
                "native channel open requires a verified effect start, never a read-only query")
        try:
            # An empty unit-owned PI_CODING_AGENT_DIR only; no user config or
            # login exists here.
            os.makedirs(roots["piHome"], exist_ok=True)
        except OSError as error:
            raise PiChannelRefused("unit private Pi agent directory could not be provisioned") from error
        spec = LaunchSpec.build(
            list(rpc_argv(self.executable)),
            home=roots["home"],
            cwd=roots["cwd"],
            extra_env={"PI_CODING_AGENT_DIR": roots["piHome"], "PI_OFFLINE": "1"},
        )
        try:
            channel = ProcessChannel.launch(spec, name=self.pathname, managed=True)
        except OSError as error:
            raise PiChannelRefused("native pi rpc process could not be launched") from error
        lease = channel.acquire_writer()
        client = PiRpcClient(channel.bind_writer(lease), name=self.pathname)
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
            raise PiChannelRefused("native channel record belongs to another factory view")
        return record

    def close(self, entry, *, timeout: float = 15.0) -> int:
        """Reap exactly this owned channel's process by identity (G6/G8).

        This is the real stop effect's tool: stdin close, then terminate, then
        kill, each awaited by identity. The record itself is KEPT so the
        termination evidence can still be verified against the actual exited
        handle; :meth:`release` performs the record release afterwards.
        """
        record = self.record(entry)
        try:
            record.client.close()
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
            raise PiChannelRefused("owned native process is still running; stop the unit first")
        with self._lock:
            self._records.pop(id(entry), None)
        return {"pid": process.pid, "exitCode": int(code)}

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
