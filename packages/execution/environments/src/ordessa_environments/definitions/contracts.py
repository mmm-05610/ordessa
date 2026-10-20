"""The execution-environment contract.

An environment is an **execution space**: it owns a real process, its
bidirectional byte streams and a bounded file area. It is *not* the governance /
storage context that ``pacthold.Environment`` implements (installations,
activations, participants, permissions, leases) — those are a different owner and
are adapted to, never renamed into, this contract.

Contract purity (enforced by ``tests/test_contract_surface.py``)
---------------------------------------------------------------
This module and the rest of ``ordessa_environments.definitions`` must not import
or name concrete execution mechanics. Specifically:

- no ``subprocess`` / ``Popen`` / ``os.fork`` / ``pty``;
- no container, VM, remote-shell or cloud SDK types (docker, ssh, OpenShell, ...);
- no ``asyncio`` stream classes — the public channel must not bind one concrete
  stream implementation.

The mechanics live in providers (``plugins/environments/<kind>``). A provider
returns a :class:`ProcessHandle`; the *concrete* object behind it may be a real
OS process, which is exactly why nothing here may name that type.

Layering
--------
``units`` depends on this contract; ``agents`` and ``environments`` never depend
on ``units``. The execution-space contract in this module uses the standard library.
Runtime resource identities also use the explicit Infrastructure digest mechanism;
no environment declaration depends on Agents, Units, Interfaces or providers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence, TYPE_CHECKING, runtime_checkable

from .errors import EnvironmentRefused

if TYPE_CHECKING:
    from .models import ProcessObservation, ProcessCancellation

#: Capability keys the contract recognises. A provider reports the subset it
#: really provides; a reference that requires anything else is refused.
PROCESS_CAPABILITY = "process"
BYTE_CHANNEL_CAPABILITY = "byte-channel"
FILE_AREA_CAPABILITY = "files"
TERMINAL_CAPABILITY = "terminal"
STREAMING_STDERR_CAPABILITY = "stderr"

KNOWN_CAPABILITIES = frozenset(
    {
        PROCESS_CAPABILITY,
        BYTE_CHANNEL_CAPABILITY,
        FILE_AREA_CAPABILITY,
        TERMINAL_CAPABILITY,
        STREAMING_STDERR_CAPABILITY,
    }
)


@dataclass(frozen=True)
class ProcessRequest:
    """A fully resolved launch request for one process in the execution space.

    This is the *generic* shape: an argument vector, a working directory and a
    fully built environment mapping. It carries no brand, profile or agent
    semantics — the single semantic ``LaunchSpec`` producer stays on the agents
    side and is mapped onto this request by the caller.
    """

    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.argv, tuple) or not self.argv:
            raise EnvironmentRefused("process request requires a non-empty argv tuple")
        for item in self.argv:
            if not isinstance(item, str) or not item:
                raise EnvironmentRefused("process request argv entries must be non-empty strings")
        if not isinstance(self.cwd, str) or not os.path.isabs(self.cwd):
            raise EnvironmentRefused("process request cwd must be an absolute path")
        if not isinstance(self.env, Mapping):
            raise EnvironmentRefused("process request env must be a mapping")
        for key, value in self.env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise EnvironmentRefused("process request env must map strings to strings")

    @classmethod
    def build(cls, argv: Sequence[str], *, cwd: str, env: Mapping[str, str]) -> "ProcessRequest":
        return cls(argv=tuple(argv), cwd=os.path.abspath(cwd), env=dict(env))


@runtime_checkable
class ProcessHandle(Protocol):
    """The sole managed process/byte-IO owner; no fd or concrete stream requirement.

    Reads on each output are exclusive, as are stdin writes. stdout and stderr
    are independent and drained separately by providers. EOF is only stream EOF.
    Write acceptance is not a remote-consumption receipt; uncertain writes must
    never be retried implicitly. Cancellation/release are not exit evidence.
    """
    identity: str
    generation: int

    async def read_stdout(self, max_bytes: int = 65536, *, timeout: float | None = None) -> bytes: ...
    async def read_stderr(self, max_bytes: int = 65536, *, timeout: float | None = None) -> bytes: ...
    async def write_stdin(self, data: bytes, *, timeout: float | None = None) -> int: ...
    async def close_stdin(self) -> None: ...
    def observe(self) -> ProcessObservation: ...
    async def wait_exit(self, *, timeout: float | None = None) -> ProcessObservation: ...
    async def cancel(self, *, force: bool = False) -> ProcessCancellation: ...
    def release(self) -> Mapping[str, object]:
        """Idempotently release this transport; never claim exit or destroy resource."""
        ...


@runtime_checkable
class FileArea(Protocol):
    """A bounded file area owned by the environment.

    Paths are always relative to the area root. The area is the environment's
    working space. Multiple Uses may share this area when external policy
    explicitly permits sharing. FileArea is not an isolation or authorization
    boundary; releasing a Use leaves the resource intact.
    """

    def root(self) -> str: ...

    def ensure(self, relative: str) -> str:
        """Create the directory and return its absolute path."""

    def path(self, relative: str) -> str:
        """Resolve an absolute path inside the area; refuse escapes."""

    def list(self) -> tuple[str, ...]: ...

    def exists(self, relative: str) -> bool: ...

    def read_text(self, relative: str) -> str: ...

    def write_text(self, relative: str, content: str) -> None: ...


@runtime_checkable
class ExecutionSpace(Protocol):
    """The process-start seam of one environment handle."""

    def start(self, request: ProcessRequest) -> ProcessHandle:
        """Perform the **real spawn** and return the owned handle.

        The environment owns the process. Callers must never spawn around this
        seam — an ACP/SDK spawn path that bypasses it is a contract violation.
        """


__all__ = [
    "PROCESS_CAPABILITY",
    "BYTE_CHANNEL_CAPABILITY",
    "FILE_AREA_CAPABILITY",
    "TERMINAL_CAPABILITY",
    "STREAMING_STDERR_CAPABILITY",
    "KNOWN_CAPABILITIES",
    "ProcessRequest",
    "ProcessHandle",
    "FileArea",
    "ExecutionSpace",
]
