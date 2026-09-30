"""Backend-owned Profile target fences over confirmed ACP ownership.

This read-only component is not product composition or an application receipt.
The host must register an authoritative canonical Profile UID; neither ledger
IDs nor native routing IDs establish that UID's provenance. A UID is pinned for
this owner's lifetime and cannot silently migrate to another live session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import threading

from ordessa_harness_api import ApplicationTarget
from .registry import (
    AcpChannelRegistry, NativeConfigurationObservation,
    NativeConfigurationUnavailable, NativeSessionObservation,
)


class ProfileOwnerUnavailable(NativeConfigurationUnavailable):
    """No current, independently read configuration for this exact target."""


@dataclass(frozen=True)
class ProfileConfigurationSnapshot:
    target: ApplicationTarget
    owner: NativeSessionObservation
    native_generation: str
    busy: bool
    config_options_json: str

    @property
    def config_options(self) -> list:
        return json.loads(self.config_options_json)


@dataclass
class _Binding:
    harness_id: str
    workspace_id: str
    owner: NativeSessionObservation
    snapshot: ProfileConfigurationSnapshot | None = None
    generations: set[str] = field(default_factory=set)
    invalidated: bool = False


class ProfileSessionOwner:
    """Read-only binding service. Fences are process-local, never restored.

    The host must supply a server incarnation ID or persist a fence authority
    across restarts; a stable server name alone cannot prevent restart ABA.
    Native generations are opaque equality tokens: their spelling or numeric
    appearance has no ordering meaning. Previously retired tokens are refused,
    preventing an ABA observation from reviving a prior target. Consumers must
    discard targets on service restart and obtain a fresh host registration.
    """

    def __init__(self, registry: AcpChannelRegistry, *, server_id: str) -> None:
        # Validate through the public DTO rather than duplicating its contract.
        ApplicationTarget(server_id, "validation", "validation", 0)
        self._registry = registry
        self._server_id = server_id
        self._bindings: dict[str, _Binding] = {}
        self._native_bindings: dict[NativeSessionObservation, str] = {}
        self._fence = 0
        self._lock = threading.RLock()

    def bind(self, *, canonical_session_id: str, harness_id: str,
             workspace_id: str, connection_id: str, native_session_id: str,
             timeout: float = 10) -> ProfileConfigurationSnapshot:
        """Pin a host-registered UID after session/new and idle readback.

        Arguments belong to the trusted host registration path, not a UI wire
        endpoint. Harness/project scope is verified against the live registry.
        A failed first read retains the identity pin but creates no target.
        """
        ApplicationTarget(self._server_id, canonical_session_id, connection_id, 0)
        with self._lock:
            binding = self._bindings.get(canonical_session_id)
            owner = self._registry.native_session_observation(connection_id, native_session_id)
            if owner is None:
                if (binding is not None and binding.owner.connection_id == connection_id
                    and binding.owner.native_session_id == native_session_id):
                    binding.invalidated = True
                raise ProfileOwnerUnavailable("confirmed native session owner unavailable")
            if binding is not None and (
                binding.owner is not owner or binding.harness_id != harness_id
                or binding.workspace_id != workspace_id
            ):
                binding.invalidated = True
                raise ProfileOwnerUnavailable("canonical session owner changed")
            if binding is None:
                binding = _Binding(harness_id, workspace_id, owner)
                self._check_owner(binding)
                if owner in self._native_bindings:
                    raise ProfileOwnerUnavailable("native owner already bound to another canonical session")
                self._bindings[canonical_session_id] = binding
                self._native_bindings[owner] = canonical_session_id
            return self._observe(canonical_session_id, binding, timeout=timeout)

    def readback(self, target: ApplicationTarget, *, timeout: float = 10) -> ProfileConfigurationSnapshot:
        """Read an exact current target; a generation change retires it.

        On change a fresh target can be obtained by trusted ``bind`` of the
        existing UID. The stale caller receives no configuration confirmation.
        """
        with self._lock:
            if not isinstance(target, ApplicationTarget) or target.server_id != self._server_id:
                raise ProfileOwnerUnavailable("foreign application target")
            binding = self._bindings.get(target.session_id)
            if binding is None or binding.snapshot is None or binding.snapshot.target != target:
                raise ProfileOwnerUnavailable("unbound or stale application target")
            snapshot = self._observe(target.session_id, binding, timeout=timeout)
            if snapshot.target != target:
                raise ProfileOwnerUnavailable("native generation changed; application target stale")
            return snapshot

    def _check_owner(self, binding: _Binding) -> None:
        if binding.invalidated:
            raise ProfileOwnerUnavailable("canonical session owner invalidated")
        owner = binding.owner
        channel = self._registry.get(owner.connection_id)
        if (channel is None or channel.ended or channel.harness_id != binding.harness_id
            or channel.workspace_id != binding.workspace_id
            or self._registry.native_session_observation(owner.connection_id, owner.native_session_id) is not owner):
            binding.invalidated = True
            raise ProfileOwnerUnavailable("live native session owner or scope changed")

    def _observe(self, uid: str, binding: _Binding, *, timeout: float) -> ProfileConfigurationSnapshot:
        self._check_owner(binding)
        owner = binding.owner
        observation = self._registry.query_native_configuration(
            owner.connection_id, owner.native_session_id, timeout=timeout)
        self._check_owner(binding)
        if not isinstance(observation, NativeConfigurationObservation) or observation.owner is not owner:
            binding.invalidated = True
            raise ProfileOwnerUnavailable("configuration readback belongs to another owner")
        previous = binding.snapshot
        changed = previous is None or previous.native_generation != observation.native_generation
        if changed and observation.native_generation in binding.generations:
            binding.invalidated = True
            raise ProfileOwnerUnavailable("retired native generation observed")
        if changed:
            self._fence += 1
            binding.generations.add(observation.native_generation)
        fence = self._fence if changed else previous.target.runtime_generation
        snapshot = ProfileConfigurationSnapshot(
            ApplicationTarget(self._server_id, uid, owner.connection_id, fence),
            owner, observation.native_generation, observation.busy, observation.config_options_json)
        # Even a busy observation retires the old generation. It cannot yield a
        # usable target until a separate idle query confirms the same token.
        binding.snapshot = snapshot
        if observation.busy:
            raise ProfileOwnerUnavailable("native configuration busy")
        return snapshot
