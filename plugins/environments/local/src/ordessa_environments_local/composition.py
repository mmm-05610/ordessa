"""Local v1 runtime composition: one exact host/sandbox pair for one root.

This is the plugin-local factory for the local ``isolation=none`` provider. It
owns the v1 composition seam (``RuntimeHost`` + ``Sandbox`` with
``wrap``/``launch``/``cleanup``) and the managed :class:`LocalUse` that the
resource provider hands to ``EnvironmentUse``. The retired local handle/provider
path (``LocalEnvironmentHandle``/``LocalEnvironmentProvider``) is gone.

The pair reports only what it really provides. A local host has no host
transport and no compensation, so ``transport.submit`` and ``terminate``
refuse and ``cleanup`` returns a no-op receipt that claims neither compensation
nor exit. The local sandbox really spawns through the existing local process
machinery and returns the single managed async ``ProcessHandle``.
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass
from typing import Mapping

from ordessa_environments import (
    CapabilityReport,
    CapabilityStatus,
    EnvironmentRefused,
    ProcessRequest,
)
from ordessa_environments.composition import (
    COMPENSATION_CAPABILITY,
    CapabilitySet,
    CommandInput,
    CompositionErrorCode,
    CompositionRejected,
    IsolatedProcessSpec,
    MountPlan,
    MountPlanInput,
    ProcessHandle,
    ProjectionRejected,
    RuntimeBundleInput,
    RuntimeHostRef,
    SandboxRef,
    SandboxUnsupported,
    guest_path,
)
from ordessa_infrastructure.encoding.content_identity import digest

from .files import LocalFileArea
from .process import spawn

#: The provider identity every local composition ref carries.
PROVIDER_ID = "local"

#: The isolation level this provider really implements.
ISOLATION = "none"

#: The managed-path report: the proven keys plus the explicit non-claim that a
#: local handle owns no terminal. Outbound network is deliberately not claimed:
#: a local process inherits the host network, which is not a managed guarantee.
MANAGED_VALUES = {
    "process": CapabilityStatus.SUPPORTED,
    "byte-channel": CapabilityStatus.SUPPORTED,
    "files": CapabilityStatus.SUPPORTED,
    "stderr": CapabilityStatus.SUPPORTED,
    "terminal": CapabilityStatus.UNSUPPORTED,
}

#: The semantic v1 composition capabilities the coordinator preflight requires
#: (``process.spawn.typed@1`` on the host, ``isolation.wrap@1`` on the sandbox).
#: A local composition really provides both: the sandbox types the spawn and
#: wraps the command, so declaring them is a fact, not a wish.
COMPOSITION_CAPABILITIES = {
    "process.spawn.typed@1": CapabilityStatus.SUPPORTED,
    "isolation.wrap@1": CapabilityStatus.SUPPORTED,
}

_MAX_ARGV = 4096
_MAX_ENV_ENTRIES = 128
_MAX_ENV_KEY = 128
_MAX_ENV_VALUE = 4096
_MAX_ATTEMPT_KEY = 256
_MAX_IO_MODE = 64


def _require_attempt_key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_ATTEMPT_KEY or "\0" in value:
        raise EnvironmentRefused("attempt key must be a bounded non-empty string")
    return value


def _local_capabilities(affinity: str) -> CapabilitySet:
    values = dict(MANAGED_VALUES)
    values.update(COMPOSITION_CAPABILITIES)
    return CapabilitySet(values, "provider_self_report", affinity)


class _RefusingHostTransport:
    """The local host has no host-transport operations; every submit refuses."""

    operations = frozenset()

    def submit(self, operation: object) -> str:
        raise CompositionRejected(
            CompositionErrorCode.CAPABILITY_UNSUPPORTED,
            "local runtime host exposes no host transport operations",
        )


class LocalRuntimeHost:
    """One exact local ``RuntimeHost`` for one environment root.

    It resolves only its own ref, stages only a bundle bound to that ref (and
    returns it unchanged — there is no local staging step to fake), and refuses
    the host-side effects it cannot honestly provide.
    """

    def __init__(self, ref: RuntimeHostRef, *, root: str):
        if not isinstance(ref, RuntimeHostRef):
            raise EnvironmentRefused("local runtime host requires a RuntimeHostRef")
        if ref.provider != PROVIDER_ID:
            raise EnvironmentRefused(f"local runtime host ref provider must be {PROVIDER_ID!r}")
        if not isinstance(root, str) or not os.path.isabs(root):
            raise EnvironmentRefused("local runtime host requires an absolute environment root")
        self._ref = ref
        self._root = os.path.normpath(root)
        self._capabilities = _local_capabilities(ref.affinity)
        self._transport = _RefusingHostTransport()

    @property
    def ref(self) -> RuntimeHostRef:
        return self._ref

    @property
    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    @property
    def transport(self) -> _RefusingHostTransport:
        return self._transport

    def resolve(self, ref: RuntimeHostRef) -> "LocalRuntimeHost":
        if not isinstance(ref, RuntimeHostRef) or ref != self._ref:
            raise CompositionRejected(
                CompositionErrorCode.INVALID_BINDING,
                "local runtime host resolves only its own exact ref",
            )
        return self

    def stage(self, bundle: RuntimeBundleInput) -> RuntimeBundleInput:
        if getattr(bundle, "host_ref", None) != self._ref:
            raise CompositionRejected(
                CompositionErrorCode.INVALID_BINDING,
                "bundle host_ref does not match this local runtime host",
            )
        # No fake staging: local has no staging step, so the bundle is returned
        # unchanged and no staging receipt is invented.
        return bundle

    def terminate(self, op: object) -> object:
        raise CompositionRejected(
            CompositionErrorCode.CAPABILITY_UNSUPPORTED,
            f"local runtime host does not provide {COMPENSATION_CAPABILITY}",
        )

    def cleanup(self, execution_id: str | None = None) -> Mapping[str, object]:
        # An honest no-op: the host performs no cleanup and claims no compensation.
        return {
            "provider": self._ref.provider,
            "host": self._ref.native_id,
            "compensation": COMPENSATION_CAPABILITY,
            "compensationSupported": False,
            "state": "no-op",
        }


class LocalSandbox:
    """One exact local ``Sandbox`` for one environment root.

    ``wrap`` maps a guest working directory under the environment root, keeps
    the fully built environment mapping and produces a stable spec digest.
    Those local launch facts are **provider-private**: they stay in this
    instance, keyed by the attempt, and never enter the frozen public
    :class:`IsolatedProcessSpec`. ``launch`` looks them up for a spec it
    wrapped and refuses a spec with no recorded (or a mismatched) fact set.
    ``cleanup`` clears the recorded facts and returns a receipt that never
    claims exit.
    """

    def __init__(self, ref: SandboxRef, *, root: str):
        if not isinstance(ref, SandboxRef):
            raise EnvironmentRefused("local sandbox requires a SandboxRef")
        if ref.provider != PROVIDER_ID:
            raise EnvironmentRefused(f"local sandbox ref provider must be {PROVIDER_ID!r}")
        if not isinstance(root, str) or not os.path.isabs(root):
            raise EnvironmentRefused("local sandbox requires an absolute environment root")
        self._ref = ref
        self._root = os.path.normpath(root)
        self._capabilities = _local_capabilities(ref.affinity)
        #: attempt key -> (spec digest, absolute cwd, built environment)
        self._launch_facts: dict[str, tuple[str, str, dict[str, str]]] = {}

    @property
    def ref(self) -> SandboxRef:
        return self._ref

    @property
    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    def resolve(self, ref: SandboxRef) -> "LocalSandbox":
        if not isinstance(ref, SandboxRef) or ref != self._ref:
            raise CompositionRejected(
                CompositionErrorCode.INVALID_BINDING,
                "local sandbox resolves only its own exact ref",
            )
        return self

    # -- wrapping ----------------------------------------------------------
    def _map_cwd(self, guest: str) -> str:
        """Map a canonical absolute guest path under the environment root."""
        if guest == "/":
            # The environment root itself is the only guest path whose canonical
            # spelling is not accepted by ``guest_path`` (it would end in "/").
            return self._root
        try:
            normalized = guest_path(guest)
        except ValueError as error:
            raise ProjectionRejected(
                "guest working directory must be a canonical absolute path"
            ) from error
        candidate = os.path.normpath(os.path.join(self._root, normalized.lstrip("/")))
        if candidate != self._root and not candidate.startswith(self._root + os.sep):
            raise ProjectionRejected("guest working directory escapes the environment root")
        return candidate

    def _local_cwd(self, cwd: object) -> str:
        if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
            raise ProjectionRejected("local launch requires an absolute working directory")
        if cwd != self._root and not cwd.startswith(self._root + os.sep):
            raise ProjectionRejected("local launch working directory escapes the environment root")
        return cwd

    def _argv(self, command: CommandInput) -> tuple[str, ...]:
        argv = getattr(command, "argv", None)
        if not isinstance(argv, (tuple, list)) or not argv:
            raise EnvironmentRefused("local sandbox requires a non-empty command argv")
        for item in argv:
            if not isinstance(item, str) or not item or len(item) > _MAX_ARGV or "\0" in item:
                raise EnvironmentRefused("local sandbox requires bounded non-empty argv entries")
        return tuple(argv)

    def _environment(self, command: CommandInput) -> dict[str, str]:
        environment = getattr(command, "environment", None)
        if not isinstance(environment, Mapping) or len(environment) > _MAX_ENV_ENTRIES:
            raise EnvironmentRefused("local sandbox requires a bounded command environment")
        result: dict[str, str] = {}
        for key, value in environment.items():
            if (not isinstance(key, str) or not key or len(key) > _MAX_ENV_KEY or "\0" in key
                    or not isinstance(value, str) or len(value) > _MAX_ENV_VALUE or "\0" in value):
                raise EnvironmentRefused("local sandbox requires bounded string environment entries")
            result[key] = value
        return result

    def _io_mode(self, command: CommandInput) -> str:
        io_mode = getattr(command, "io_mode", "stdio")
        if not isinstance(io_mode, str) or not io_mode or len(io_mode) > _MAX_IO_MODE or "\0" in io_mode:
            raise EnvironmentRefused("local sandbox requires a bounded io_mode")
        return io_mode

    def wrap(
        self, mount_plan: MountPlanInput, command: CommandInput, *, attempt_key: str,
    ) -> IsolatedProcessSpec:
        attempt_key = _require_attempt_key(attempt_key)
        argv = self._argv(command)
        cwd = self._map_cwd(getattr(command, "cwd_token", None))
        environment = self._environment(command)
        io_mode = self._io_mode(command)
        spec_digest = digest({
            "argv": argv,
            "cwd": cwd,
            "env": dict(sorted(environment.items())),
            "io": io_mode,
            "attempt_key": attempt_key,
            "command": getattr(command, "command_digest", ""),
            "mount_plan": getattr(mount_plan, "digest", ""),
        })
        # The local cwd/env are provider-private launch facts. They are recorded
        # here, keyed by the attempt, and deliberately kept out of the frozen
        # public IsolatedProcessSpec projection.
        self._launch_facts[attempt_key] = (spec_digest, cwd, environment)
        return IsolatedProcessSpec(
            spawn_token=digest({"attempt_key": attempt_key, "spec_digest": spec_digest}),
            attempt_key=attempt_key,
            spec_digest=spec_digest,
            io_mode=io_mode,
            local_argv=argv,
        )

    # -- launching ---------------------------------------------------------
    def launch(self, spec: IsolatedProcessSpec, *, attempt_key: str) -> ProcessHandle:
        attempt_key = _require_attempt_key(attempt_key)
        if not isinstance(spec, IsolatedProcessSpec):
            raise EnvironmentRefused("local sandbox launches an IsolatedProcessSpec only")
        if spec.local_argv is None:
            raise SandboxUnsupported("local sandbox launches only the local argv representation")
        if spec.attempt_key != attempt_key:
            raise CompositionRejected(
                CompositionErrorCode.ATTEMPT_REPLAY,
                "launch attempt key does not match the wrapped spec",
            )
        facts = self._launch_facts.get(attempt_key)
        if facts is None:
            raise CompositionRejected(
                CompositionErrorCode.INVALID_BINDING,
                "no wrapped local launch facts for this attempt",
            )
        recorded_digest, cwd, environment = facts
        if spec.spec_digest != recorded_digest:
            raise CompositionRejected(
                CompositionErrorCode.INVALID_BINDING,
                "spec digest does not match the wrapped local launch facts",
            )
        return spawn(ProcessRequest(
            argv=tuple(spec.local_argv), cwd=self._local_cwd(cwd), env=dict(environment),
        ))

    def cleanup(self, spec: IsolatedProcessSpec) -> Mapping[str, object]:
        if not isinstance(spec, IsolatedProcessSpec):
            raise EnvironmentRefused("local sandbox cleans up an IsolatedProcessSpec only")
        # Cleanup clears the private launch facts for this attempt; a later
        # launch of the same spec therefore refuses rather than re-spawning.
        self._launch_facts.pop(spec.attempt_key, None)
        # A receipt, not an exit claim: the process owner still observes/cancels.
        return {
            "provider": self._ref.provider,
            "sandbox": self._ref.native_id,
            "specDigest": spec.spec_digest,
            "attemptKey": spec.attempt_key,
            "exitClaimed": False,
            "state": "no-op",
        }


class LocalCompositionProvider:
    """Pairs one exact local host and sandbox for one environment root.

    The refs are derived deterministically from the root unless the caller
    supplies them; supplied refs must be consistent (same ``local`` provider and
    the same affinity) or the factory refuses. Provider selection policy stays
    outside this package: this is a plugin-local factory only.
    """

    provider = PROVIDER_ID

    def __init__(
        self, *, root: str,
        host_ref: RuntimeHostRef | None = None,
        sandbox_ref: SandboxRef | None = None,
    ):
        if not isinstance(root, str) or not os.path.isabs(root):
            raise EnvironmentRefused("local composition requires an absolute environment root")
        self._root = os.path.normpath(root)
        derived_host, derived_sandbox = _derive_refs(self._root)
        host_ref = derived_host if host_ref is None else host_ref
        sandbox_ref = derived_sandbox if sandbox_ref is None else sandbox_ref
        self._require_consistent(host_ref, sandbox_ref)
        self._host = LocalRuntimeHost(host_ref, root=self._root)
        self._sandbox = LocalSandbox(sandbox_ref, root=self._root)

    @staticmethod
    def _require_consistent(host_ref: RuntimeHostRef, sandbox_ref: SandboxRef) -> None:
        if not isinstance(host_ref, RuntimeHostRef) or not isinstance(sandbox_ref, SandboxRef):
            raise EnvironmentRefused("local composition requires exact host and sandbox refs")
        if host_ref.provider != PROVIDER_ID or sandbox_ref.provider != PROVIDER_ID:
            raise EnvironmentRefused("local composition refs must both name the local provider")
        if host_ref.affinity != sandbox_ref.affinity:
            raise EnvironmentRefused("local composition host and sandbox refs must share an affinity")

    @property
    def root(self) -> str:
        return self._root

    @property
    def host(self) -> LocalRuntimeHost:
        return self._host

    @property
    def sandbox(self) -> LocalSandbox:
        return self._sandbox

    @property
    def refs(self) -> tuple[RuntimeHostRef, SandboxRef]:
        return (self._host.ref, self._sandbox.ref)

    def resolve(self, host_ref: RuntimeHostRef, sandbox_ref: SandboxRef) -> tuple[LocalRuntimeHost, LocalSandbox]:
        return (self._host.resolve(host_ref), self._sandbox.resolve(sandbox_ref))


def _derive_refs(root: str) -> tuple[RuntimeHostRef, SandboxRef]:
    affinity = f"local-root/{digest({'provider': PROVIDER_ID, 'root': root})}"
    host_ref = RuntimeHostRef(
        PROVIDER_ID,
        f"local-host/{digest({'root': root, 'kind': 'host'})}",
        digest({'root': root, 'kind': 'host-identity'}),
        affinity,
    )
    sandbox_ref = SandboxRef(
        PROVIDER_ID,
        f"local-sandbox/{digest({'root': root, 'kind': 'sandbox'})}",
        digest({'root': root, 'kind': 'sandbox-policy', 'isolation': ISOLATION}),
        affinity,
        network_mode="inherit",
    )
    return host_ref, sandbox_ref


@dataclass(frozen=True)
class _LocalCommand:
    """The minimal structural ``CommandInput`` one managed Use wraps.

    It carries only what ``LocalSandbox.wrap`` reads: the argv, the guest cwd
    token, the built environment, the io mode, a content digest and the
    projector identity. The empty runtime-source tuple and the false
    control-plane requirement are explicit facts: a Use start declares no
    projected sources and needs no control-plane network.
    """

    argv: tuple[str, ...]
    cwd_token: str
    environment: Mapping[str, str]
    io_mode: str
    command_digest: str
    runtime_sources: tuple = ()
    requires_control_plane_network: bool = False
    tool_network_requirement: str = "none"
    projector_id: str = "local-use"

    @property
    def digest(self) -> str:
        return self.command_digest


def _guest_cwd(cwd: object, root: str) -> str:
    """Derive the guest cwd token for a request cwd under the environment root.

    A cwd outside the root is refused rather than silently remapped: the local
    sandbox maps guest paths under one root, so a foreign cwd would otherwise
    launch the process somewhere the caller did not ask for.
    """
    if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        raise EnvironmentRefused("local Use requires an absolute process request cwd")
    normalized = os.path.normpath(cwd)
    if normalized == root:
        return "/"
    if not normalized.startswith(root + os.sep):
        raise EnvironmentRefused("process request cwd is outside the local environment root")
    return "/" + os.path.relpath(normalized, root).replace(os.sep, "/")


class _LocalUseExecution:
    """The real ``start`` seam of one managed local Use.

    Each start builds a fresh minimal command, wraps it through the exact local
    sandbox and launches it under a unique attempt key. The returned value is
    the real managed :class:`ProcessHandle`; the Use keeps the attempt facts so
    it can report what it owns.
    """

    def __init__(self, use: "LocalUse"):
        self._use = use
        self._attempts = itertools.count(1)
        self._launched: list[tuple[str, IsolatedProcessSpec, ProcessHandle]] = []

    def start(self, request: ProcessRequest) -> ProcessHandle:
        if self._use.released:
            raise EnvironmentRefused(
                f"environment use {self._use.identity!r} was released; acquire a new use"
            )
        if not isinstance(request, ProcessRequest):
            raise EnvironmentRefused("local Use accepts a ProcessRequest only")
        sandbox = self._use.composition.sandbox
        attempt_key = f"local-use/{self._use.identity}/{next(self._attempts)}"
        environment = dict(request.env)
        command = _LocalCommand(
            argv=tuple(request.argv),
            cwd_token=_guest_cwd(request.cwd, self._use.root),
            environment=environment,
            io_mode="stdio",
            command_digest=digest(
                {
                    "argv": tuple(request.argv),
                    "cwd": os.path.normpath(request.cwd),
                    "env": dict(sorted(environment.items())),
                    "io": "stdio",
                }
            ),
        )
        spec = sandbox.wrap(MountPlan(), command, attempt_key=attempt_key)
        handle = sandbox.launch(spec, attempt_key=attempt_key)
        self._launched.append((attempt_key, spec, handle))
        return handle

    def owned(self) -> tuple[ProcessHandle, ...]:
        return tuple(handle for _, _, handle in self._launched)

    def attempts(self) -> tuple[str, ...]:
        return tuple(attempt_key for attempt_key, _, _ in self._launched)


class LocalUse:
    """The managed Use of one local (``isolation=none``) resource.

    A Use is a recorded use, not an isolation boundary or a lease: it owns the
    bounded file area, the managed :class:`CapabilityReport` and the real
    launch seam for one generation. ``release`` is idempotent, preserves the
    resource and never deletes files or stops a process.
    """

    def __init__(self, identity: str, root: str, *, generation: int = 0):
        if not isinstance(identity, str) or not identity:
            raise EnvironmentRefused("local Use requires a non-empty identity")
        if not isinstance(root, str) or not os.path.isabs(root):
            raise EnvironmentRefused("local Use requires an absolute environment root")
        self._identity = identity
        self.generation = generation
        self._root = os.path.normpath(root)
        self._files = LocalFileArea(self._root)
        self._capabilities = CapabilityReport(
            dict(MANAGED_VALUES),
            ISOLATION,
            "provider_self_report",
            "",
            {"resourceKind": "directory", "provider": PROVIDER_ID},
        )
        self._composition = LocalCompositionProvider(root=self._root)
        self._execution = _LocalUseExecution(self)
        self.released = False
        self._release_receipt: Mapping[str, object] | None = None

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def root(self) -> str:
        return self._root

    @property
    def composition(self) -> LocalCompositionProvider:
        return self._composition

    @property
    def capabilities(self) -> CapabilityReport:
        return self._capabilities

    @property
    def files(self) -> LocalFileArea:
        return self._files

    @property
    def execution(self) -> _LocalUseExecution:
        return self._execution

    def release(self) -> Mapping[str, object]:
        """Release this Use idempotently; never destroys the resource or files."""
        if self._release_receipt is not None:
            return dict(self._release_receipt)
        self.released = True
        self._release_receipt = {
            "useIdentity": self._identity,
            "isolation": ISOLATION,
            "root": self._root,
            "rootPreserved": os.path.isdir(self._root),
            "resourcePreserved": True,
            "attempts": list(self._execution.attempts()),
        }
        return dict(self._release_receipt)


__all__ = [
    "COMPOSITION_CAPABILITIES",
    "ISOLATION",
    "MANAGED_VALUES",
    "PROVIDER_ID",
    "LocalCompositionProvider",
    "LocalRuntimeHost",
    "LocalSandbox",
    "LocalUse",
]
