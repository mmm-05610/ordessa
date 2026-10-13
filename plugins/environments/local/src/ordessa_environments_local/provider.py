"""Local ``isolation=none`` environment provider.

This is the only environment implementation required for v1. It reports its real
isolation level honestly (``"none"``), refuses a configuration reference that
asks for anything it does not actually provide, and never claims a guarantee it
cannot check.

``release`` is not ``destroy``: releasing a handle leaves the working directory,
the file area and every shared resource intact. Nothing in this module deletes a
project directory, and nothing removes a user resource.
"""
from __future__ import annotations

import itertools
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from ordessa_environments import (
    BYTE_CHANNEL_CAPABILITY,
    FILE_AREA_CAPABILITY,
    PROCESS_CAPABILITY,
    STREAMING_STDERR_CAPABILITY,
    Capabilities,
    EnvironmentRefused,
    ProcessHandle,
    ProcessRequest,
    require_guarantees,
    BackendObservation,
    BackendNotFound,
)

from .files import LocalFileArea
from .process import LocalProcessHandle, spawn

#: The isolation level this provider really implements.
ISOLATION = "none"

#: Capabilities the local provider really provides.
PROVIDES = frozenset(
    {
        PROCESS_CAPABILITY,
        BYTE_CHANNEL_CAPABILITY,
        FILE_AREA_CAPABILITY,
        STREAMING_STDERR_CAPABILITY,
    }
)

#: Reference keys this provider accepts. Anything else is refused, never ignored.
REFERENCE_KEYS = frozenset({"isolation", "root"})


class LocalExecutionSpace:
    """The real spawn seam of one local environment handle."""

    def __init__(self, handle: "LocalEnvironmentHandle"):
        self._handle = handle
        self._opened: dict[str, LocalProcessHandle] = {}

    def start(self, request: ProcessRequest) -> ProcessHandle:
        if self._handle.released:
            raise EnvironmentRefused(
                f"environment {self._handle.identity!r} was released; open a new handle"
            )
        handle = spawn(request,generation=self._handle.generation)
        self._opened[handle.identity] = handle
        return handle

    def owned(self) -> tuple[str, ...]:
        return tuple(sorted(identity for identity, handle in self._opened.items() if not handle.released))

    def handles(self) -> tuple[LocalProcessHandle, ...]:
        """The owner's view of the processes this space still owns.

        Used by the owner to reap on teardown. Callers must not treat this as a
        way to reach around the contract: the generic surface is still
        :class:`ordessa_environments.ProcessHandle`.
        """
        return tuple(self._opened[identity] for identity in self.owned())

    def running(self) -> tuple[str, ...]:
        return tuple(
            sorted(identity for identity, handle in self._opened.items() if handle.poll() is None)
        )


class LocalEnvironmentHandle:
    """One real local execution space (``isolation=none``)."""

    def __init__(self, identity: str, root: str, generation: int = 0):
        self._identity = identity
        self.generation = generation
        self._root = root
        self._files = LocalFileArea(root)
        self._execution = LocalExecutionSpace(self)
        self._capabilities = Capabilities(
            isolation=ISOLATION,
            provides=PROVIDES,
            detail={"root": root, "provider": "local"},
        )
        self.released = False

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def files(self) -> LocalFileArea:
        return self._files

    @property
    def execution(self) -> LocalExecutionSpace:
        return self._execution

    def release(self) -> Mapping[str, object]:
        """Release this handle. **Never** destroys the project or shared resources.

        Refuses while a process this environment started is still running: the
        stop effect belongs to the caller, and release must not fake a stop.
        The file area and its contents are left in place — releasing is not
        destroying.
        """
        if self.released:
            return dict(self._release_receipt)
        running = self._execution.running()
        if running:
            raise EnvironmentRefused(
                f"environment {self._identity!r} still owns running processes: {list(running)}"
            )
        self.released = True
        self._release_receipt = {
            "identity": self._identity,
            "isolation": ISOLATION,
            "root": self._root,
            "rootPreserved": os.path.isdir(self._root),
            "processes": list(self._execution.owned()),
        }

        return dict(self._release_receipt)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<LocalEnvironmentHandle {self._identity} root={self._root}>"


class LocalEnvironmentProvider:
    """Resolves a configuration reference to a real local environment handle."""

    def __init__(self, *, default_root: str):
        if not isinstance(default_root, str) or not os.path.isabs(default_root):
            raise EnvironmentRefused("local provider requires an absolute default root")
        self._default_root = os.path.normpath(default_root)
        self._identity_namespace = uuid.uuid4().hex
        self._counter = itertools.count(1)

    # -- contract ----------------------------------------------------------
    def probe(self) -> Mapping[str, object]:
        return {
            "provider": "local",
            "available": True,
            "isolation": ISOLATION,
            "capabilities": sorted(PROVIDES),
            "defaultRoot": self._default_root,
        }

    def resolve(self, reference: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Turn a configuration reference into concrete, checked settings.

        A reference asking for a different isolation level, or carrying an
        unknown key, is refused — never silently downgraded to ``none``.
        """
        if reference is None:
            reference = {}
        if not isinstance(reference, Mapping):
            raise EnvironmentRefused("environment reference must be a mapping")
        unknown = sorted(set(reference) - REFERENCE_KEYS)
        if unknown:
            raise EnvironmentRefused(f"unsupported environment reference keys: {unknown}")
        isolation = reference.get("isolation", ISOLATION)
        if isolation != ISOLATION:
            raise EnvironmentRefused(
                f"local provider implements isolation={ISOLATION!r}, not {isolation!r}"
            )
        root = reference.get("root", self._default_root)
        if not isinstance(root, str) or not root or not os.path.isabs(root):
            raise EnvironmentRefused("environment root must be an absolute path")
        return {"isolation": ISOLATION, "root": os.path.normpath(root)}

    def open(self, reference: Mapping[str, Any] | None = None) -> LocalEnvironmentHandle:
        """Acquire a real local environment handle.

        The root directory is provisioned if absent. The handle's reported
        capabilities are then checked against the caller's reference, so a
        reference that requires something the provider does not really provide
        fails here rather than at first use.
        """
        settings = self.resolve(reference)
        root = str(settings["root"])
        try:
            os.makedirs(root, exist_ok=True)
        except OSError as error:
            raise EnvironmentRefused(f"environment root could not be provisioned: {error}") from error
        handle = LocalEnvironmentHandle(
            identity=f"local-environment/{self._identity_namespace}/{next(self._counter)}", root=root
        )
        require_guarantees(handle, sorted(PROVIDES))
        return handle


class LocalEnvironmentResourceProvider:
    """Development adapter over existing Local mechanics; never an isolation fallback.

    Immutable backend identity is the physical directory root. A directory has
    no isolated runtime stop/start/delete; these effects explicitly refuse.
    Each use retains the original per-handle process owner view and preserves files.
    """
    identity = 'local'
    binding_id = 'local-development-process-v1'
    operations = frozenset()

    def __init__(self, *, default_root):
        self._provider = LocalEnvironmentProvider(default_root=default_root)

    def create(self, reference, *, operation_id):
        handle = self._provider.open(reference)
        backend_id = os.path.realpath(handle.files.root())
        handle.release()
        return self.inspect(backend_id)

    def inspect(self, backend_id):
        if not isinstance(backend_id, str) or not os.path.isabs(backend_id):
            raise EnvironmentRefused('local backend identity must be an absolute root')
        if os.path.realpath(backend_id) != backend_id:
            raise EnvironmentRefused('local backend root identity changed')
        if not os.path.isdir(backend_id):
            raise BackendNotFound('local backend directory is absent')
        return BackendObservation(backend_id, 'running',
            Capabilities(ISOLATION, PROVIDES, {'resourceKind':'directory'}),
            datetime.now(timezone.utc).isoformat())

    def open_use(self, backend_id, *, use_id, generation):
        self.inspect(backend_id)
        return LocalEnvironmentHandle(use_id, backend_id,generation=generation)

    def recover_creation(self, operation_id):
        raise EnvironmentRefused('Local has no external creation-correlation authority')

    def start(self, backend_id):
        raise EnvironmentRefused('Local directory resource has no isolated start operation')

    def stop(self, backend_id):
        raise EnvironmentRefused('Local directory resource cannot stop external processes')

    def delete(self, backend_id):
        raise EnvironmentRefused('Local resource deletion is unavailable; user files are preserved')


__all__ = [
    "LocalEnvironmentResourceProvider",
    "ISOLATION",
    "PROVIDES",
    "REFERENCE_KEYS",
    "LocalExecutionSpace",
    "LocalEnvironmentHandle",
    "LocalEnvironmentProvider",
]
