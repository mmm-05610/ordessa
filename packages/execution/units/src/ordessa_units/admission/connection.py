"""Shared ``ConnectionLeasePort``: per-write authority cut on one channel.

``bind`` ties the consumer entry to two identities: the deployment-issued
write authorization (:class:`ConnectionGrant`) and the ORIGINAL transport writer
lease of that unit's channel. Every subsequent write is validated first by
this port's own gate (grant identity, revocation, current activation epoch)
and then again by the transport, inside the actual write lock/lease barrier —
so revocation, an old activation epoch, disconnect or a forged grant deny all
subsequent writes even on an already-held view.

Closing a consumer entry only disconnects/fences its view; it never terminates
the unit process and never claims stop. Raw client/channel handles are never
exposed by these objects to product callers.
"""
from __future__ import annotations

import threading
from typing import Any, Mapping

from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_execution_agents.harness.transport import LeaseBoundChannel, ProcessChannel, WriterLease

COMPLETE_UNIT_FIELDS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


class ConnectionLeaseRefused(RuntimeError):
    code = "PI_LEASE_REFUSED"


def _complete_unit_ref(unit_ref) -> Mapping:
    if (not isinstance(unit_ref, Mapping) or set(unit_ref) != COMPLETE_UNIT_FIELDS
            or not isinstance(unit_ref.get("unitId"), str) or not unit_ref["unitId"]):
        raise ConnectionLeaseRefused("complete owner-bound unit reference required")
    try:
        safe_json(unit_ref)
    except (TypeError, ValueError) as error:
        raise ConnectionLeaseRefused("complete owner-bound unit reference required") from error
    return unit_ref


class ConnectionGrant:
    """Opaque deployment-issued write authorization; process-local, copy-proof.

    Epoch facts are visible bookkeeping, not a capability: a stale or revoked
    grant is useless even in the hands of its original holder.
    """

    __slots__ = ("_epoch", "_unit")

    def __init__(self, *args, **kwargs):
        raise TypeError("connection grants are issued by the lease port")

    def __setattr__(self, name, value):
        raise AttributeError("connection grants are immutable")

    def __copy__(self):
        raise TypeError("connection grants cannot be copied")

    __deepcopy__ = __copy__

    def __reduce__(self):
        raise TypeError("connection grants cannot be serialized")

    @property
    def epoch(self):
        return self._epoch

    @property
    def unit_ref(self):
        return self._unit


class _BoundLease:
    """Trusted binding facts of one granted connection (never consumer-visible)."""

    __slots__ = ("unit_key", "unit_ref", "grant", "view", "lease", "channel")

    def __init__(self, unit_key, unit_ref, grant, view, lease, channel):
        self.unit_key, self.unit_ref, self.grant = unit_key, unit_ref, grant
        self.view, self.lease, self.channel = view, lease, channel


class LeasedConnection:
    """Consumer entry behind the per-write authority cut.

    The connected client/channel handles stay hidden. ``command`` preserves the
    native payload verbatim and refuses whenever the grant or the original
    transport lease is no longer current. ``close`` disconnects this entry's
    view only and never stops the unit process.
    """

    __slots__ = ("_port", "_binding")

    def __init__(self, port, binding: _BoundLease):
        try:
            object.__setattr__(self, "_port", port)
            object.__setattr__(self, "_binding", binding)
        except (AttributeError, TypeError) as error:
            raise TypeError(f"leased connection could not be issued by its port: {error}") from None

    def __setattr__(self, name, value):
        raise AttributeError("leased connections are immutable consumer entries")

    def command(self, command_type: str, **fields: Any) -> Any:
        self._port._require_writable(self)
        return self._binding.view.command(command_type, **fields)

    def prompt(self, **fields):
        self._port._require_writable(self)
        return self._binding.view.prompt(**fields)

    def request(self, method, params, **controls):
        self._port._require_writable(self)
        return self._binding.view.request(method, params, **controls)

    def next_event(self, *, timeout=10):
        self._port._require_writable(self)
        return self._binding.view.next_event(timeout=timeout)

    def cancel(self, **fields):
        self._port._require_writable(self)
        return self._binding.view.cancel(**fields)

    def close(self):
        """Disconnect this entry and fence its view; the unit keeps running."""
        self._port._disconnect(self)
        # The bound view fences the writer lease; the unit process keeps running.
        # The SDK IO loop still owns the process channel and is needed by the
        # original Unit stop. Disconnect fences its writer, without detaching
        # the process owner or cancelling its continuous native session.
        with self._binding.channel._write_lock:
            if self._binding.channel._active_writer is self._binding.lease:
                self._binding.channel.fence_all()
        return None

    def __copy__(self):
        raise TypeError("leased connections cannot be copied")

    __deepcopy__ = __copy__

    def __reduce__(self):
        raise TypeError("leased connections cannot be serialized")


class ConnectionLeasePort:
    """Original managed connection lease, shared across native protocols.

    Provided revoke semantics: :meth:`revoke` (typed) invalidates every grant
    of the unit AND fences the original transport writer, cutting all further
    writes under the actual barrier. Grant expiry maps onto the same
    activation-epoch gate; a closed/disconnected channel denies writes by
    transport identity. Consumers never receive raw client/channel handles.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._grants: dict[str, dict[int, dict]] = {}   # unit key -> grant id -> {grant, revoked}
        self._epochs: dict[str, int] = {}               # unit key -> current activation epoch
        self._bound: dict[str, list[_BoundLease]] = {}  # unit key -> live bindings

    # -- deployment authority side --------------------------------------------
    def grant(self, unit_ref, *, revalidate=None) -> ConnectionGrant:
        unit_ref = _complete_unit_ref(unit_ref)
        if revalidate is not None and not callable(revalidate):
            raise ConnectionLeaseRefused('Explicit current write authority required')
        key = safe_json(unit_ref)
        with self._lock:
            instance = object.__new__(ConnectionGrant)
            object.__setattr__(instance, "_epoch", self._epochs.get(key, 0))
            object.__setattr__(instance, "_unit", key)
            self._grants.setdefault(key, {})[id(instance)] = {"grant": instance, "revoked": False,
                                                           "revalidate": revalidate}
            return instance

    def revoke(self, unit_ref) -> None:
        """Typed revoke: dead grants plus a fenced original transport writer."""
        unit_ref = _complete_unit_ref(unit_ref)
        key = safe_json(unit_ref)
        with self._lock:
            self._epochs[key] = self._epochs.get(key, 0) + 1
            for entry in self._grants.get(key, {}).values():
                entry["revoked"] = True
            bindings = list(self._bound.get(key, ()))
        for binding in bindings:  # outside the port lock: the barrier owns the write lock
            with binding.channel._write_lock:
                try:
                    if binding.channel._active_writer is binding.lease:
                        binding.channel.fence_all()
                except Exception:
                    pass  # already fenced; every further write is denied either way

    # -- provider connect seam --------------------------------------------------
    def bind(self, unit_ref, authorized_lease, client) -> LeasedConnection:
        """Bind the native connection behind the granted per-write authority cut."""
        unit_ref = _complete_unit_ref(unit_ref)
        key = safe_json(unit_ref)
        with self._lock:
            self._live_grant_entry(key, authorized_lease)
            check = self._grants[key][id(authorized_lease)]['revalidate']
        if check is not None:
            check()
            attach = getattr(client, 'bind_write_authority', None)
            if not callable(attach):
                raise ConnectionLeaseRefused('Native client cannot retain current write authority')
            attach(check)
        lease, channel = self._original_writer(client)
        with self._lock:
            for binding in self._bound.get(key, ()):
                if binding.grant is authorized_lease:
                    raise ConnectionLeaseRefused("original connection grant is already bound")
                if binding.channel is channel:
                    raise ConnectionLeaseRefused("native connection is already granted to another writer")
            binding = _BoundLease(key, unit_ref, authorized_lease, client, lease, channel)
            self._bound.setdefault(key, []).append(binding)
            return LeasedConnection(self, binding)

    # -- internals ------------------------------------------------------------
    def _live_grant_entry(self, key, lease) -> None:
        entries = self._grants.get(key)
        entry = entries.get(id(lease)) if isinstance(entries, dict) else None
        if (entry is None or entry["grant"] is not lease or entry["revoked"]
                or self._epochs.get(key, 0) != lease.epoch):
            raise ConnectionLeaseRefused("connection lease is absent, revoked or of an old activation")
        check = entry.get('revalidate')
        if check is not None:
            check()

    def _require_writable(self, connection: LeasedConnection) -> None:
        """Pre-write gate; the transport's own lease check stays the hard cut."""
        if not isinstance(connection, LeasedConnection) or connection._port is not self:
            raise ConnectionLeaseRefused("leased connection belongs to another port")
        binding = connection._binding
        with self._lock:
            self._live_grant_entry(binding.unit_key, binding.grant)
        with binding.channel._write_lock:
            if (binding.channel._active_writer is not binding.lease
                    or binding.channel._writer_epoch != binding.lease.epoch):
                raise ConnectionLeaseRefused("original writer lease is fenced, disconnected or stale")

    def _disconnect(self, connection: LeasedConnection) -> None:
        binding = connection._binding
        with self._lock:
            bindings = self._bound.get(binding.unit_key, [])
            if binding in bindings:
                bindings.remove(binding)

    @staticmethod
    def _original_writer(client):
        """Resolve the client's bound original transport writer (trusted internal)."""
        view = getattr(client, "_channel", None)
        if not isinstance(view, LeaseBoundChannel):
            raise ConnectionLeaseRefused("native connection has no managed writer view")
        channel = view._channel
        lease = view._lease
        if (not isinstance(channel, ProcessChannel) or not channel._managed
                or not isinstance(lease, WriterLease)
                or channel._active_writer is not lease
                or channel._writer_epoch != lease.epoch):
            raise ConnectionLeaseRefused(
                "native connection writer is absent, revoked or of an old activation")
        return lease, channel
