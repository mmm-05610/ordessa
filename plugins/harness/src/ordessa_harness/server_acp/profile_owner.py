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
from uuid import uuid4

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


@dataclass(frozen=True)
class RestorationTicket:
    """Process-local backend capability; cannot be reconstructed from a DTO."""
    ticket_id: str
    operation_id: str
    before: ProfileConfigurationSnapshot


@dataclass(frozen=True)
class RestoredConfiguration:
    previous_target: ApplicationTarget
    snapshot: ProfileConfigurationSnapshot
    operation_id: str
    evidence_ref: str


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
        self._restorations: dict[str, RestorationTicket] = {}
        self._restoration_results: dict[str, RestoredConfiguration] = {}

    def begin_restoration(self, target: ApplicationTarget, *, operation_id: str,
                          timeout: float = 10) -> RestorationTicket:
        """Reserve before a backend-owned resume, not after discovering drift.

        This does not authorize native effects or make an application receipt.
        It pins the old instance so completion must prove this exact transition.
        """
        if (type(operation_id) is not str or not operation_id or len(operation_id) > 128
                or operation_id != operation_id.strip()):
            raise ProfileOwnerUnavailable('bounded restoration operation required')
        with self._lock:
            previous = self._restorations.get(operation_id)
            if previous is not None:
                if previous.before.target != target:
                    raise ProfileOwnerUnavailable('restoration operation already bound')
                return previous
            if len(self._restorations) >= 256:
                raise ProfileOwnerUnavailable('restoration capacity exhausted')
            if any(saved.before.target.session_id == target.session_id
                   and saved.operation_id not in self._restoration_results
                   for saved in self._restorations.values()):
                raise ProfileOwnerUnavailable('session restoration already pending')
            snapshot = self.readback(target, timeout=timeout)
            ticket = RestorationTicket(uuid4().hex, operation_id, snapshot)
            self._restorations[operation_id] = ticket
            return ticket

    def complete_restoration(self, ticket: RestorationTicket, *, timeout: float = 10) -> RestoredConfiguration:
        """Explicitly renew only from retained resume evidence + independent read.

        Ordinary readback still refuses a stale target. No new execution,
        replacement ledger owner or different native conversation is accepted.
        Failed/unknown completion performs no second resume.
        """
        with self._lock:
            if (not isinstance(ticket, RestorationTicket)
                    or self._restorations.get(ticket.operation_id) is not ticket):
                raise ProfileOwnerUnavailable('unknown restoration ticket')
            first = ticket.before
            binding = self._bindings.get(first.target.session_id)
            if binding is None or binding.owner is not first.owner:
                raise ProfileOwnerUnavailable('restoration owner changed')
            self._check_owner(binding)
            owner, record = self._registry.query_native_operation(first.owner.connection_id,
                first.owner.native_session_id, ticket.operation_id, timeout=timeout)
            expected_target = dict(server_id=first.target.server_id, session_id=first.target.session_id,
                channel_id=first.target.channel_id, runtime_generation=first.target.runtime_generation)
            if (owner is not first.owner or not isinstance(record, dict)
                    or record.get('operationId') != ticket.operation_id
                    or record.get('sessionId') != first.owner.native_session_id
                    or record.get('kind') != 'provider-resume' or record.get('state') != 'observed'
                    or not isinstance(record.get('target'), dict)
                    or set(record['target']) != set(expected_target)
                    or any(type(record['target'][key]) is not type(expected_target[key]) for key in expected_target)
                    or record.get('target') != expected_target
                    or type(record.get('evidenceRef')) is not str or not record['evidenceRef']
                    or len(record['evidenceRef']) > 4096):
                raise ProfileOwnerUnavailable('verified restoration record unavailable')
            before, after = record.get('before'), record.get('after')
            if (not isinstance(before, dict) or not isinstance(after, dict)
                    or before.get('sessionId') != first.owner.native_session_id
                    or before.get('generation') != first.native_generation or before.get('busy') is not False
                    or before.get('configOptions') != first.config_options
                    or after.get('sessionId') != first.owner.native_session_id or after.get('busy') is not False
                    or type(after.get('generation')) is not str or not after['generation']
                    or after['generation'] == first.native_generation):
                raise ProfileOwnerUnavailable('restoration instance evidence mismatch')
            snapshot = self._observe(first.target.session_id, binding, timeout=timeout)
            if (snapshot.native_generation != after['generation']
                    or snapshot.config_options != after.get('configOptions')):
                raise ProfileOwnerUnavailable('independent restored configuration differs')
            cached = self._restoration_results.get(ticket.operation_id)
            if cached is not None:
                if snapshot.target != cached.snapshot.target:
                    raise ProfileOwnerUnavailable('restored instance has changed again')
                return cached
            result = RestoredConfiguration(first.target, snapshot, ticket.operation_id, record['evidenceRef'])
            self._restoration_results[ticket.operation_id] = result
            return result

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
