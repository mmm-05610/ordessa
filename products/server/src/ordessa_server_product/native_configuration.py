"""Product assembly of existing Harness native ownership and C4 services.

This port is independent of optional preset consumers. It holds only live
identity bindings; application results stay in the existing Harness journal.
"""
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

from server_plugin_api import ServerPluginDescriptor, ServerPluginRegistration
from ordessa_harness.configuration.model.backend import NativeModelServices
from ordessa_harness.server_acp.profile_owner import ProfileSessionOwner
from ordessa_harness.server_acp.registry import NativeConfigurationUnavailable

PLUGIN_ID = 'ordessa.product.native-configuration'
PORT = 'native.configuration'


@dataclass
class _Binding:
    uid: str
    owner: object
    snapshot: object = None


class NativeConfigurationAuthority:
    def __init__(self, *, channels, owners, services):
        self.channels, self.owners, self.services = channels, owners, services
        self._bindings = {}
        self._lock = RLock()
        self._active = True

    def require_active(self):
        if not self._active:
            raise NativeConfigurationUnavailable('native configuration authority is inactive')

    def close(self):
        # ACP owns transport teardown. Preset disposal never closes this port.
        with self._lock:
            self._active = False

    def register_native(self, *, connection_id, native_session_id):
        """Return one backend-minted identity for this observed live owner."""
        with self._lock:
            self.require_active()
            channel = self.channels.get(connection_id)
            owner = self.channels.native_session_observation(connection_id, native_session_id)
            if channel is None or channel.ended or owner is None:
                raise NativeConfigurationUnavailable('live native session owner unavailable')
            key = (connection_id, native_session_id)
            binding = self._bindings.get(key)
            if binding is not None and binding.owner is not owner:
                raise NativeConfigurationUnavailable('native session owner replaced')
            if binding is None:
                if len(self._bindings) >= 4096:
                    raise NativeConfigurationUnavailable('native session registration capacity exhausted')
                # Preserve the existing canonical UID spelling; it is not a
                # request to create a Profile row or a second session ledger.
                binding = _Binding('profile-session-' + uuid4().hex, owner)
                self._bindings[key] = binding
            if binding.snapshot is None:
                snapshot = self.owners.bind(canonical_session_id=binding.uid,
                    harness_id=channel.harness_id, workspace_id=channel.workspace_id,
                    connection_id=connection_id, native_session_id=native_session_id)
            else:
                snapshot = self.owners.readback(binding.snapshot.target)
            if (snapshot.owner is not owner
                    or self.channels.native_session_observation(connection_id, native_session_id) is not owner):
                raise NativeConfigurationUnavailable('native owner changed during registration')
            binding.snapshot = snapshot
            return snapshot

    def resolve(self, target):
        with self._lock:
            self.require_active()
            return self.owners.readback(target)

    def ensure_native(self, *, harness_id, native_session_id):
        """The one live canonical binding for this backend-observed native session.

        Bound sessions already carry a binding (the Profile registration path
        used the same ``register_native`` entry). An unbound native session is
        registered here on first model use - through exactly the same public
        backend entry, so the canonical UID, the owner fence and the fresh
        readback are identical for both modes. The session is named exactly as
        the backend observed it (harness + native session id); zero live
        matches and ambiguous references are typed absences, never "the first
        match" (021 closeout B.1).
        """
        with self._lock:
            self.require_active()
            binding = self.observed_native(harness_id=harness_id,
                                           native_session_id=native_session_id)
            if binding is not None:
                return binding
            candidates = []
            for connection_id in sorted(str(key) for key in getattr(self.channels, '_by_id', {})):
                # The registry is a composition fact this product assembled; the
                # per-connection reads below are its public surface. An ended
                # channel is absence, never a candidate.
                channel = self.channels.get(connection_id)
                if channel is None or channel.ended or channel.harness_id != harness_id:
                    continue
                if self.channels.native_session_observation(connection_id, native_session_id) is not None:
                    candidates.append(connection_id)
            if len(candidates) > 1:
                raise NativeConfigurationUnavailable(
                    'native session reference is ambiguous across live channels')
            if not candidates:
                return None
            self.register_native(connection_id=candidates[0],
                                 native_session_id=native_session_id)
            # register_native answers the fresh snapshot; the canonical
            # binding it minted (or re-observed) for this exact owner is the
            # authority's own record - same UID, same owner fence.
            binding = self._bindings.get((candidates[0], native_session_id))
            if binding is None or binding.snapshot is None:
                raise NativeConfigurationUnavailable('native registration produced no binding')
            return binding

    def has_live_native(self, *, harness_id, native_session_id):
        """Whether the backend currently observes this native session live.

        A queue-time existence check that mints nothing: no binding, no
        canonical UID, no native round-trip - only the channel's own
        observation of its correlated session/new reply. Ambiguity across
        live channels is a typed unavailability, never a silent pick.
        """
        with self._lock:
            self.require_active()
            matches = 0
            for connection_id in sorted(str(key) for key in getattr(self.channels, '_by_id', {})):
                channel = self.channels.get(connection_id)
                if channel is None or channel.ended or channel.harness_id != harness_id:
                    continue
                if self.channels.native_session_observation(connection_id, native_session_id) is not None:
                    matches += 1
            if matches > 1:
                raise NativeConfigurationUnavailable(
                    'native session reference is ambiguous across live channels')
            return matches == 1

    def observed_native(self, *, harness_id, native_session_id):
        """The current binding for this native session, freshly re-observed.

        A read, not a registration: an unregistered session is ``None`` (an
        absence, never a guess) and a dead or replaced owner is a typed
        unavailability. Ambiguity across live channels refuses.
        """
        with self._lock:
            self.require_active()
            matches = {}
            for (connection_id, native_id), binding in self._bindings.items():
                if native_id != native_session_id:
                    continue
                channel = self.channels.get(connection_id)
                owner = self.channels.native_session_observation(connection_id, native_id)
                if (channel is None or channel.ended
                        or channel.harness_id != harness_id or owner is None
                        or binding.owner is not owner or binding.snapshot is None):
                    continue  # a dead owner is absence, never a candidate
                matches[connection_id] = binding
            if len(matches) > 1:
                raise NativeConfigurationUnavailable(
                    'native session reference is ambiguous across live channels')
            if not matches:
                return None
            binding = next(iter(matches.values()))
            snapshot = self.owners.readback(binding.snapshot.target)
            if snapshot.owner is not binding.owner:
                raise NativeConfigurationUnavailable('native owner changed during resolution')
            binding.snapshot = snapshot
            return binding

    def create_service(self, target, *, credential_binding=None):
        with self._lock:
            self.require_active()
            # The Harness factory performs the exact owner readback itself.
            return self.services.create_service(target, credential_binding=credential_binding)

    def begin_restoration(self, target, *, operation_id):
        with self._lock:
            self.require_active()
            return self.owners.begin_restoration(target, operation_id=operation_id)

    def complete_restoration(self, ticket):
        with self._lock:
            self.require_active()
            key = (ticket.before.owner.connection_id, ticket.before.owner.native_session_id)
            binding = self._bindings.get(key)
            if binding is None or binding.owner is not ticket.before.owner or binding.uid != ticket.before.target.session_id:
                raise NativeConfigurationUnavailable('restoration belongs to another native owner')
            result = self.owners.complete_restoration(ticket)
            if result.snapshot.owner is not binding.owner or result.snapshot.target.session_id != binding.uid:
                raise NativeConfigurationUnavailable('restoration changed native identity')
            binding.snapshot = result.snapshot
            return result


class NativeConfigurationPlugin:
    def __init__(self, *, carrier, roots):
        self.carrier, self.roots = carrier, dict(roots)

    def descriptor(self):
        return ServerPluginDescriptor(PLUGIN_ID, 'Native session configuration', '1',
            requires=('ordessa.harness.acp',))

    def build(self, context):
        channels = context.ports['acp.channels']
        if channels is None:
            raise NativeConfigurationUnavailable('native channels unavailable')
        owners = ProfileSessionOwner(channels, server_id='profile-incarnation-' + uuid4().hex)
        # Historical data path remains shared; no parallel operation ledger.
        journal_path = Path(context.data_root) / 'plugins/profile/native-configuration.sqlite'
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        services = NativeModelServices(roots=self.roots, channels=channels, owners=owners,
            carrier=self.carrier, journal_path=journal_path)
        authority = NativeConfigurationAuthority(channels=channels, owners=owners, services=services)
        return ServerPluginRegistration(provided_ports={PORT: authority}, disposal=authority.close)
