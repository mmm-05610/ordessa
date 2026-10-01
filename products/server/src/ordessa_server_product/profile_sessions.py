"""Product identity wiring between Profile storage and confirmed Harness owners.

No client-supplied canonical UID, guessed native identity, or application claim.
Resuming a historical conversation is a separate, explicit binding operation.
"""
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from ordessa_profile.contracts import SessionRef
from ordessa_profile.errors import ProfileError


def bind_native_profile_sessions(core, runtime, *, artifact_root=None, artifact_roots=None):
    """Product-owned live composition; no client-supplied UID/incarnation.

    Called again for each Profile activation round, resolving the current ACP
    registry rather than retaining a stopped round's port. Local is the
    product's existing Profile realm, not a new persistent layout identifier.
    """
    from ordessa_harness.server_acp.profile_owner import ProfileSessionOwner

    channels = runtime.plugin_host.provided_port("acp.channels")
    if channels is None:
        raise ProfileError("APPLICATION_PORT_ABSENT", "Native channels unavailable", status=409)
    owners = ProfileSessionOwner(channels, server_id="profile-incarnation-" + uuid4().hex)
    sessions = ProfileNativeSessions(core=core, channels=channels, owners=owners, realm="local")
    from ordessa_harness.configuration.model.backend import NativeModelServices, installation_routes
    roots = installation_routes(artifact_root=artifact_root, artifact_roots=artifact_roots)
    native_services = NativeModelServices(roots=roots, channels=channels, owners=owners,
        carrier=runtime.plugin_host, journal_path=runtime.data_root / 'plugins/profile/native-configuration.sqlite')
    if roots:
        from .profile_configuration import NativeProfileConfigPort
        from ordessa_harness.configuration.model.bridge import choice_payload_schema
        from ordessa_model_provider.profile_resolution import ProfileModelChoiceResolver
        def service_factory(target):
            return native_services.create_service(target,
                credential_binding=credential_binding)
        def credential_resolver(ref, desired):
            return preparation_catalog().application_credential(desired.get('credentialRef'), harness_id=ref.harness_id)
        def credential_binding(snapshot, desired):
            channel = channels.get(snapshot.owner.connection_id)
            if channel is None:
                return False
            credential = preparation_catalog().application_credential(
                desired.get('credentialRef'), harness_id=channel.harness_id)
            if native_services.restoration.credential_binding(snapshot, desired, credential=credential):
                return True
            return sessions.preparation.credential_binding(snapshot, desired)
        def resolver_factory():
            catalog = runtime.plugin_host.provided_port("model_provider.catalog")
            if catalog is None:
                raise ProfileError("APPLICATION_PORT_ABSENT", "Model catalogue unavailable", status=409)
            return ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema())
        core.config_port = NativeProfileConfigPort(sessions, service_factory=service_factory,
            resolver_factory=resolver_factory, supported_harnesses=tuple(roots),
            restoration_service=native_services.restoration, credential_resolver=credential_resolver)
    from .profile_preparation import NativeProfilePreparation
    def preparation_catalog():
        catalog = runtime.plugin_host.provided_port('model_provider.catalog')
        if catalog is None:
            raise ProfileError('APPLICATION_PORT_ABSENT', 'Model catalogue unavailable', status=409)
        return catalog
    def preparation_resolver():
        from ordessa_model_provider.profile_resolution import ProfileModelChoiceResolver
        from ordessa_harness.configuration.model.bridge import choice_payload_schema
        return ProfileModelChoiceResolver(preparation_catalog(), payload_schema=choice_payload_schema())
    sessions.preparation = NativeProfilePreparation(core, channels, roots=roots,
        verify=native_services.verify,
        resolver_factory=preparation_resolver, catalog_factory=preparation_catalog,
        managed_account_factory=native_services.managed_account)
    return sessions


@dataclass(frozen=True)
class ProfileNativeBinding:
    session_ref: SessionRef
    snapshot: object


class ProfileNativeSessions:
    def __init__(self, *, core, channels, owners, realm: str):
        if not isinstance(realm, str) or not realm.strip():
            raise ValueError("backend-owned realm required")
        self.core, self.channels, self.owners, self.realm = core, channels, owners, realm
        self._bindings = {}
        self._lock = RLock()

    def prepare_native_creation(self, *, connection_id, profile_id, operation_id):
        preparation = getattr(self, 'preparation', None)
        if preparation is None:
            raise ProfileError('APPLICATION_PORT_ABSENT', 'Native preparation unavailable', status=409)
        return preparation.prepare(connection_id=connection_id, profile_id=profile_id, operation_id=operation_id)

    def resolve_launch_selection(self, *, profile_id, harness_id):
        preparation = getattr(self, 'preparation', None)
        if preparation is None:
            raise ProfileError('APPLICATION_PORT_ABSENT', 'Profile launch preparation unavailable', status=409)
        return preparation.resolve_launch_selection(profile_id=profile_id, harness_id=harness_id)

    def require_registered(self, ref):
        """Identity-only fence: recording a selection must not query a busy agent."""
        with self._lock:
            for (connection_id, native_id), binding in self._bindings.items():
                if binding.session_ref != ref:
                    continue
                channel = self.channels.get(connection_id)
                owner = self.channels.native_session_observation(connection_id, native_id)
                if channel is None or channel.ended or owner is not binding.snapshot.owner:
                    raise ProfileError("SWITCH_BLOCKED", "Native owner no longer active", status=409)
                return binding
            raise ProfileError("SESSION_NOT_FOUND", "Backend session registration unavailable", status=404)

    def resolve(self, ref):
        """Never resolve a guessed UID or silently bind a different native owner."""
        with self._lock:
            binding = None
            for candidate in self._bindings.values():
                if candidate.session_ref == ref:
                    binding = candidate
                    break
            if binding is None:
                raise ProfileError("SESSION_NOT_FOUND", "Backend session registration unavailable", status=404)
            snapshot = self._observe(lambda: self.owners.readback(binding.snapshot.target))
            if snapshot.owner is not binding.snapshot.owner:
                raise ProfileError("SWITCH_BLOCKED", "Native owner changed", status=409)
            return ProfileNativeBinding(ref, snapshot)

    def begin_restoration(self, ref, *, operation_id):
        """Backend-only reservation before a Harness-owned provider resume."""
        with self._lock:
            binding = self.require_registered(ref)
            return self._observe(lambda: self.owners.begin_restoration(
                binding.snapshot.target, operation_id=operation_id))

    def complete_restoration(self, ref, ticket):
        """Keep the saved conversation identity; replace only its runtime fence.

        The owner performs both native operation query and fresh readback.
        This is not Profile application confirmation and writes no receipt.
        """
        with self._lock:
            binding = self.require_registered(ref)
            if (ticket.before.owner is not binding.snapshot.owner
                    or ticket.before.target.session_id != ref.session_uid):
                raise ProfileError('SWITCH_BLOCKED', 'Restoration belongs to another session', status=409)
            result = self._observe(lambda: self.owners.complete_restoration(ticket))
            if (result.snapshot.owner is not binding.snapshot.owner
                    or result.snapshot.target.session_id != ref.session_uid):
                raise ProfileError('SWITCH_BLOCKED', 'Restoration changed conversation owner', status=409)
            key = (binding.snapshot.owner.connection_id, ref.native_session_key)
            self._bindings[key] = ProfileNativeBinding(ref, result.snapshot)
            return result

    def register(self, *, connection_id: str, native_session_id: str, profile_id: str):
        """Register only a session/new owner actually observed by this backend."""
        with self._lock:
            channel = self.channels.get(connection_id)
            owner = self.channels.native_session_observation(connection_id, native_session_id)
            if channel is None or channel.ended or owner is None:
                raise ProfileError("SESSION_NOT_FOUND", "Live native session owner unavailable", status=404)
            profile = self.core.profiles.get(profile_id)
            if profile["realm"] != self.realm:
                raise ProfileError("REALM_MISMATCH", "Profile belongs to another realm", status=409)
            if profile["harness_id"] != channel.harness_id:
                raise ProfileError("HARNESS_MISMATCH", "Profile belongs to another Harness", status=409)
            key = (connection_id, native_session_id)
            existing = self._bindings.get(key)
            if existing is not None:
                if existing.snapshot.owner is not owner:
                    raise ProfileError("SWITCH_BLOCKED", "Native owner has been replaced", status=409)
                snapshot = self._observe(lambda: self.owners.readback(existing.snapshot.target))
                return ProfileNativeBinding(existing.session_ref, snapshot)
            if len(self._bindings) >= 4096:
                raise ProfileError("SWITCH_BLOCKED", "Session registration capacity exhausted", status=409)
            uid = "profile-session-" + uuid4().hex
            snapshot = self._observe(lambda: self.owners.bind(canonical_session_id=uid, harness_id=channel.harness_id,
                workspace_id=channel.workspace_id, connection_id=connection_id,
                native_session_id=native_session_id))
            if snapshot.owner is not owner:
                raise ProfileError("SWITCH_BLOCKED", "Native owner changed during registration", status=409)
            ref = SessionRef(self.realm, channel.harness_id, native_session_id, uid)
            self.core.sessions.open_session("register:" + uid, session_id=uid, session_uid=uid,
                native_session_key=native_session_id, harness_id=channel.harness_id,
                profile_id=profile_id, realm=self.realm)
            binding = ProfileNativeBinding(ref, snapshot)
            self._bindings[key] = binding
            if self.channels.native_session_observation(connection_id, native_session_id) is not owner:
                raise ProfileError("SWITCH_BLOCKED", "Native owner ended during registration", status=409)
            return binding

    @staticmethod
    def _observe(callback):
        from ordessa_harness.server_acp.registry import NativeConfigurationUnavailable

        try:
            return callback()
        except NativeConfigurationUnavailable as exc:
            raise ProfileError("SWITCH_BLOCKED", "Native configuration observation unavailable",
                               status=409) from exc
