"""Product identity wiring between Profile storage and confirmed Harness owners.

No client-supplied canonical UID, guessed native identity, or application claim.
Resuming a historical conversation is a separate, explicit binding operation.
"""
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from ordessa_profile.contracts import SessionRef
from ordessa_profile.errors import ProfileError


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

    def register(self, *, connection_id: str, native_session_id: str, profile_id: str):
        """Register only a session/new owner actually observed by this backend."""
        with self._lock:
            channel = self.channels.get(connection_id)
            owner = self.channels.native_session_observation(connection_id, native_session_id)
            if channel is None or channel.ended or owner is None:
                raise ProfileError("SESSION_NOT_FOUND", "Live native session owner unavailable", status=404)
            profile = self.core.profiles.get(profile_id)
            if profile["harness_id"] != channel.harness_id:
                raise ProfileError("HARNESS_MISMATCH", "Profile belongs to another Harness", status=409)
            key = (connection_id, native_session_id)
            existing = self._bindings.get(key)
            if existing is not None:
                if existing.snapshot.owner is not owner:
                    raise ProfileError("SWITCH_BLOCKED", "Native owner has been replaced", status=409)
                snapshot = self.owners.readback(existing.snapshot.target)
                return ProfileNativeBinding(existing.session_ref, snapshot)
            if len(self._bindings) >= 4096:
                raise ProfileError("SWITCH_BLOCKED", "Session registration capacity exhausted", status=409)
            uid = "profile-session-" + uuid4().hex
            snapshot = self.owners.bind(canonical_session_id=uid, harness_id=channel.harness_id,
                workspace_id=channel.workspace_id, connection_id=connection_id,
                native_session_id=native_session_id)
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
