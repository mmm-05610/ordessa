"""Real grok-build ACP channel factory (family ``grok-build``, protocol ``grok-build-acp/1``).

This module owns the native process launch for one AgentUnit:

- Launch plan: ``<absolute pinned executable> agent stdio`` over stdio
  (frozen argv shape ``grok_acp_argv``), per the pinned ACP facts in
  ``client.py``. The factory is always constructed with a caller-approved
  installation path and never discovers, falls back or guesses a version.
- Process isolation (G12): the child environment is rebuilt from scratch under
  the unit's *private root* — ``HOME``/``XDG_*``/``TMPDIR`` pinned inside the
  root, ``GROK_HOME`` pointed at the unit's private grok home, every
  credential-shaped environment key dropped (including ``XAI_API_KEY`` and
  every other key the transport fence carries), and nothing else inherited
  except ``PATH``. No user login, user configuration or ambient credentials
  (``grok`` login / ``XAI_API_KEY``) are ever read or written by this factory.
- Authority gate: ``open`` accepts only an isolated-roots fact set plus an
  *effect-verified* start fact mapping (``action == "start"``,
  ``query is False``). A read-only query can never open a native process.
- Managed stdin fence: the channel is launched in managed mode and the
  factory's own writer lease is bound before any native call, so every write
  (by provider edges and by consumer leases) is validated inside the actual
  write barrier. Revocation denies all subsequent writes.
- Lifecycle: an opened channel is closed only through this owner's explicit
  :meth:`close` (identity-based subprocess reap; used by the stop effect;
  G6/G8) or :meth:`release` (records release of an already-exited channel;
  never kills), plus :meth:`close_all` for teardown.
"""
from __future__ import annotations

import os
import stat
import subprocess
import threading
from typing import Any, Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_execution_agents.harness.transport import LaunchSpec, ProcessChannel
from ordessa_harness_grok_build.client import GrokBuildAcpClient

#: The unit root layout this factory accepts. ``cwd`` is the native working
#: directory; ``home`` and ``grokHome`` are unit-private HOME and GROK_HOME.
PRIVATE_ROOT_FIELDS = frozenset({"cwd", "home", "grokHome"})

#: Start-phase RPC timeout plan applied by the factory-owned client view. The
#: deployment owns these deadlines; the provider edge sequence stays untouched.
TIMEOUT_FIELDS = frozenset({"initialize", "new_session", "rpc"})


class GrokBuildChannelRefused(RuntimeError):
    code = "GROKBUILD_CHANNEL_REFUSED"


def grok_acp_argv(executable: str) -> tuple[str, ...]:
    """Pure launch plan for the native ACP entry; never executed here.

    Frozen argv shape: ``grok agent stdio`` (registration draft §2); the
    caller-approved absolute executable replaces the bare launcher name.
    """
    return (executable, "agent", "stdio")


def verified_private_roots(private_root_facts: Any) -> Mapping[str, str]:
    """Validate the isolated unit roots and return the sealed canonical facts.

    All three paths must be absolute, normalized, distinct directories under
    one common private root parent, so every child identity directory
    (``HOME``, ``GROK_HOME``, XDG dirs, working directory, native session
    storage under ``~/.grok``) stays inside the unit's private root. Nothing
    is created here.
    """
    if (not isinstance(private_root_facts, Mapping)
            or set(private_root_facts) != PRIVATE_ROOT_FIELDS):
        raise GrokBuildChannelRefused(
            "isolated private root facts require exactly cwd, home and grokHome")
    values: dict[str, str] = {}
    for key in sorted(PRIVATE_ROOT_FIELDS):
        value = private_root_facts[key]
        if (not isinstance(value, str) or not value or not os.path.isabs(value)
                or os.path.normpath(value) != value or "\x00" in value
                or value == "/" or value.startswith("//")
                or any(ord(c) < 32 for c in value)):
            raise GrokBuildChannelRefused("private root path must be a normalized absolute directory")
        values[key] = value
    real = {key: os.path.realpath(value) for key, value in values.items()}
    if len(set(real.values())) != len(real):
        raise GrokBuildChannelRefused("private root directories must be distinct")
    parent = os.path.dirname(real["cwd"])
    if not parent or os.path.dirname(real["home"]) != parent or os.path.dirname(real["grokHome"]) != parent:
        raise GrokBuildChannelRefused("private root directories must share one common root parent")
    values = {key: values[key] for key in ("cwd", "home", "grokHome")}
    try:
        return sealed_mapping(values)
    except (TypeError, ValueError) as error:
        raise GrokBuildChannelRefused("private root facts are not JSON-encodable") from error


def _verified_executable(executable: Any) -> str:
    if not isinstance(executable, str) or not executable or not os.path.isabs(executable):
        raise GrokBuildChannelRefused("pinned native executable must be an absolute path")
    try:
        info = os.stat(executable)
    except OSError as error:
        raise GrokBuildChannelRefused("pinned native executable is missing") from error
    if not stat.S_ISREG(info.st_mode) or not os.access(executable, os.X_OK):
        raise GrokBuildChannelRefused("pinned native executable is not a runnable regular file")
    return executable


def _verified_timeouts(timeouts: Any) -> dict[str, float]:
    plan = {key: 10.0 for key in sorted(TIMEOUT_FIELDS)}
    if timeouts is None:
        return plan
    if not isinstance(timeouts, Mapping) or not set(timeouts) <= TIMEOUT_FIELDS:
        raise GrokBuildChannelRefused(f"start timeout plan accepts only {sorted(TIMEOUT_FIELDS)}")
    for key, value in timeouts.items():
        if type(value) not in (int, float) or isinstance(value, bool) or not 0 < value < float("inf"):
            raise GrokBuildChannelRefused("start timeout plan requires finite positive deadlines")
        plan[key] = float(value)
    return plan


class _StartPlanClient:
    """Factory-owned view of one launched client with the factory timeout plan.

    Only the two start-edge deadlines are fixed here; everything else
    (session ledger, pending RPC recovery, event stream, ``_channel``) is
    delegated unchanged to the real :class:`GrokBuildAcpClient`, so this view
    never re-sends or duplicates anything.
    """

    __slots__ = ("_client", "_timeouts")

    def __init__(self, client: GrokBuildAcpClient, timeouts: Mapping[str, float]):
        self._client = client
        self._timeouts = sealed_mapping(timeouts)

    def initialize(self) -> Mapping[str, Any]:
        return self._client.initialize(timeout=self._timeouts["initialize"])

    def new_session(self, **params: Any) -> Mapping[str, Any]:
        return self._client.new_session(timeout=self._timeouts["new_session"], **params)

    def command(self, method: str, **params: Any) -> Any:
        return self._client.command(method, timeout=self._timeouts["rpc"], **params)

    def __getattr__(self, name: str) -> Any:
        # __slots__ classes only reach here for delegated attributes.
        return getattr(self._client, name)


class ChannelRecord:
    """Trusted owner record of one opened native channel; never durable truth."""

    __slots__ = ("entry", "client", "channel", "lease", "spec", "roots")

    def __init__(self, entry, client, channel, lease, spec, roots):
        self.entry, self.client, self.channel = entry, client, channel
        self.lease, self.spec, self.roots = lease, spec, roots


class GrokBuildAcpChannelFactory:
    """Real ``ChannelFactoryPort`` implementation for the grok-build family."""

    def __init__(self, executable: str, *, name: str = "grok-build-acp",
                 timeouts: Mapping[str, float] | None = None):
        self.executable = _verified_executable(executable)
        self.pathname = name if isinstance(name, str) and name and len(name) <= 128 else "grok-build-acp"
        self.timeouts = _verified_timeouts(timeouts)
        self._records: dict[int, ChannelRecord] = {}
        self._lock = threading.RLock()
        self.opens = 0

    def open(self, private_root_facts, verified_start_facts) -> _StartPlanClient:
        """Launch the pinned installation isolated under the unit private root.

        This runs the real native binary: the caller must already hold the
        verified start authority (the provider revalidates again before every
        edge). Discovery, fallback, user login/config/credentials and model
        turns do not exist on this path. Authentication (grok login /
        XAI_API_KEY) is never touched here.
        """
        roots = verified_private_roots(private_root_facts)
        if (not isinstance(verified_start_facts, Mapping)
                or verified_start_facts.get("action") != "start"
                or verified_start_facts.get("query") is not False):
            raise GrokBuildChannelRefused(
                "native channel open requires a verified effect start, never a read-only query")
        try:
            # An empty unit-owned GROK_HOME only; no user config or login exists here.
            os.makedirs(roots["grokHome"], exist_ok=True)
        except OSError as error:
            raise GrokBuildChannelRefused("unit private GROK_HOME could not be provisioned") from error
        spec = LaunchSpec.build(
            list(grok_acp_argv(self.executable)),
            home=roots["home"],
            cwd=roots["cwd"],
            extra_env={"GROK_HOME": roots["grokHome"]},
        )
        try:
            channel = ProcessChannel.launch(spec, name=self.pathname, managed=True)
        except OSError as error:
            raise GrokBuildChannelRefused("native grok-build ACP process could not be launched") from error
        lease = channel.acquire_writer()
        client = GrokBuildAcpClient(channel.bind_writer(lease), name=self.pathname)
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
            raise GrokBuildChannelRefused("native channel record belongs to another factory view")
        return record

    def close(self, entry, *, timeout: float = 15.0) -> int:
        """Reap exactly this owned channel's process by identity (G6/G8).

        This is the real stop effect's tool: the consumer view close releases
        live entry state only (disconnect); the owned subprocess is reaped
        through this factory's REAL channel — stdin close, then terminate,
        then kill, each awaited by identity. The record itself is KEPT so the
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
            raise GrokBuildChannelRefused("owned native process is still running; stop the unit first")
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
