"""One adapter for legacy/native Harness profile manager shapes."""
from __future__ import annotations

from collections.abc import Mapping
import inspect
from typing import Any

from .api import ProfileEnvelope

_SECRET_KEYS = ("secret", "token", "api_key", "apikey", "password", "private_key", "authorization", "cookie")


def _safe(value: Any, path: str = "profile") -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            name = str(key).lower().replace("-", "_")
            if any(word in name for word in _SECRET_KEYS) or name in {"credential_value", "host_path", "runtime_path"}:
                raise ValueError("SECRET_FIELD_FORBIDDEN")
            result[str(key)] = _safe(child, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError("FIELD_LIMIT_EXCEEDED")
        return tuple(_safe(child, f"{path}[]") for child in value)
    if isinstance(value, str) and len(value) > 8192:
        raise ValueError("FIELD_TOO_LARGE")
    return value


def to_profile_envelope(value: Mapping[str, Any] | ProfileEnvelope, *, harness_type: str, provider_id: str) -> ProfileEnvelope:
    """Boundedly normalize one legacy revision without changing its digest."""
    if isinstance(value, ProfileEnvelope):
        if value.harness_type != harness_type or value.provider_id != provider_id:
            raise ValueError("PROFILE_ENVELOPE_IDENTITY_MISMATCH")
        return value
    if not isinstance(value, Mapping):
        raise TypeError("profile manager must return a mapping or ProfileEnvelope")
    native = value.get("native_payload", value.get("config", value.get("profile", {})))
    credential = value.get("credential_source_ref")
    if credential is not None:
        credential = _safe(credential)
        if not isinstance(credential, Mapping) or set(credential) - {"provider", "native_locator", "kind"}:
            raise ValueError("CREDENTIAL_LOCATOR_INVALID")
    refs = tuple(_safe(value.get("capability_refs", ())))
    provenance = value.get("import_provenance")
    return ProfileEnvelope(
        profile_id=str(value.get("profile_id", "")), harness_type=harness_type,
        provider_id=provider_id, name=str(value.get("name", value.get("profile_id", ""))),
        schema_version=str(value.get("schema_version", "1")), revision=int(value.get("revision", 0)),
        digest=str(value.get("digest", "")), disabled=bool(value.get("disabled", False)),
        credential_source_ref=credential, capability_refs=refs,
        session_overlay_policy=_safe(value.get("session_overlay_policy") or {}),
        import_provenance=_safe(provenance) if provenance is not None else None,
        native_payload=_safe(native),
    )


class ProfileEnvelopeManager:
    """Host-neutral adapter; the wrapped manager remains native-payload owner."""
    def __init__(self, manager: object, *, harness_type: str, provider_id: str):
        self._manager = manager
        self.harness_id = harness_type
        self._harness_type = harness_type
        self._provider_id = provider_id

    def descriptor(self): return self._manager.descriptor()
    def _wrap(self, value):
        if isinstance(value, Mapping) and not value.get("digest"):
            provider = getattr(self._manager, "provider", None)
            make_ref = getattr(provider, "make_ref", None)
            if callable(make_ref):
                profile_id = value.get("profile_id", "")
                revision = int(value.get("revision", 0))
                ref = make_ref(profile_id, revision)
                value = {**value, "digest": ref.digest}
        return to_profile_envelope(value, harness_type=self._harness_type, provider_id=self._provider_id)
    def list_profiles(self): return tuple(self._wrap(value) for value in self._manager.list_profiles())
    def get_profile(self, profile_id, revision=None): return self._wrap(self._manager.get_profile(profile_id, revision))
    def __getattr__(self, name): return getattr(self._manager, name)
    def _native_write(self, profile_id, data, expected=None):
        pid = profile_id or data.get("profile_id") or str(data.get("name", "")).strip().lower().replace(" ", "-")
        if hasattr(self._manager, "create") and profile_id is None:
            return self._manager.create(data)
        if hasattr(self._manager, "update"):
            return self._manager.update(profile_id, data, expected)
        provider = getattr(self._manager, "provider", None)
        if provider is not None and hasattr(provider, "save"):
            payload = dict(data); payload["profile_id"] = profile_id or payload.get("profile_id")
            if expected is not None:
                current = self._wrap(self._manager.get_profile(pid))
                if current.revision != int(expected): raise ValueError("REVISION_CONFLICT")
            if "expected_revision" in inspect.signature(provider.save).parameters:
                return provider.save(payload, expected_revision=expected)
            return provider.save(payload)
        authority = getattr(provider, "authority", None)
        if authority is not None and hasattr(authority, "save"):
            payload = dict(data); payload["profile_id"] = pid
            authority.save(payload, expected_revision=expected)
            return self._manager.get_profile(pid)
        if provider is not None and hasattr(provider, "put"):
            payload = dict(data.get("native_payload", data.get("config", data)))
            target_revision = 1 if expected is None else int(expected) + 1
            provider.put(pid, payload, target_revision)
            return self._manager.get_profile(pid, target_revision)
        raise RuntimeError("PROFILE_MUTATION_UNSUPPORTED")
    def create(self, data): return self._wrap(self._native_write(None, data))
    def update(self, profile_id, data, expected): return self._wrap(self._native_write(profile_id, data, expected))
    def disable(self, profile_id, revision):
        current = self.get_profile(profile_id, revision)
        data = {"profile_id": current.profile_id, "name": current.name, "config": dict(current.native_payload), "disabled": True,
                "capability_refs": list(current.capability_refs), "credential_source_ref": current.credential_source_ref,
                "session_overlay_policy": dict(current.session_overlay_policy)}
        return self.update(profile_id, data, revision)
    def confirm_import(self, *args, **kwargs): return self._wrap(self._manager.confirm_import(*args, **kwargs))
