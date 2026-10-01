"""Product composition of Profile's port and domain-owned model resolution.

No native fields or brand switching strategy live here. Harness supplies the
application service; ModelProvider resolves business references. Every call
uses a backend-registered SessionRef and a current, independently read owner.
"""
from dataclasses import replace
from threading import RLock

from ordessa_profile.errors import ProfileError
from ordessa_profile.harness_port_adapter import HarnessApiConfigPort


class NativeProfileConfigPort:
    native_turn_application = True

    def __init__(self, sessions, *, service_factory, resolver_factory):
        self.sessions = sessions
        self.service_factory, self.resolver_factory = service_factory, resolver_factory
        self._ports, self._plans = {}, {}
        self._lock = RLock()

    def complete_restoration(self, ref, ticket):
        """Explicit trusted renewal, never automatic repair of arbitrary drift.

        Restore evidence is separate from a C4 application receipt. A fresh
        application must be planned against the new instance before prompting.
        """
        with self._lock:
            cached = self._ports.get(ref.session_uid)
            binding = self.sessions.require_registered(ref)
            if cached is not None and cached[0] != binding.snapshot.target:
                raise ProfileError('SWITCH_BLOCKED', 'Restoration does not match cached owner', status=409)
            result = self.sessions.complete_restoration(ref, ticket)
            if cached is not None and cached[0] not in (result.previous_target, result.snapshot.target):
                raise ProfileError('SWITCH_BLOCKED', 'Restoration does not match cached owner', status=409)
            if cached is not None and cached[0] == result.previous_target:
                self._ports.pop(ref.session_uid)
            for key, saved in tuple(self._plans.items()):
                if saved[0] == ref:
                    self._plans.pop(key)
            return result

    def _port(self, ref):
        binding = self.sessions.resolve(ref)
        if ref.harness_id != "pi":
            raise ProfileError("SWITCH_BLOCKED", "Native application not yet available for this Harness", status=409)
        cached = self._ports.get(ref.session_uid)
        if cached is not None:
            if cached[0] != binding.snapshot.target:
                raise ProfileError("SWITCH_BLOCKED", "Native owner generation changed", status=409)
            return cached[1]
        try:
            service, native = self.service_factory(binding.snapshot.target)
        except Exception as exc:
            raise ProfileError("APPLICATION_PORT_ABSENT", "Verified native application unavailable", status=409) from exc
        port = HarnessApiConfigPort(service, owner_application=True,
            target_resolver=lambda target_ref: self.sessions.resolve(target_ref).snapshot.target,
            revision_provider=lambda target_ref: native.capture(
                self.sessions.resolve(target_ref).snapshot.target).before_revision)
        self._ports[ref.session_uid] = (binding.snapshot.target, port)
        return port

    def inspect(self, ref):
        with self._lock:
            return self._port(ref).inspect(ref)

    def _resolve(self, ref, desired):
        if (len(desired) != 1 or desired[0].facet_id != "assets.model-provider"
            or desired[0].item_id != "choice" or desired[0].op != "set"):
            raise ProfileError("SWITCH_BLOCKED", "This native route requires one supported model choice", status=409)
        try:
            resolved = self.resolver_factory().resolve(desired[0].value, harness_id=ref.harness_id)
        except Exception as exc:
            raise ProfileError("SWITCH_BLOCKED", "Current model choice cannot be resolved", status=409) from exc
        return (replace(desired[0], value=resolved.payload),), resolved.revisions

    def plan(self, ref, desired, operation_key):
        with self._lock:
            port = self._port(ref)
            mapped, revisions = self._resolve(ref, desired)
            plan = port.plan(ref, mapped, operation_key)
            if not plan.blocked:
                if len(self._plans) >= 4096:
                    raise ProfileError("SWITCH_BLOCKED", "Native plan capacity exhausted", status=409)
                self._plans[operation_key] = (ref, desired, mapped, revisions, plan)
            return plan

    def apply(self, plan, desired):
        with self._lock:
            saved = self._plans.get(plan.operation_key)
            if saved is None or saved[0] != plan.session_ref or saved[1] != desired or saved[4] != plan:
                raise ProfileError("SWITCH_BLOCKED", "Unknown or changed prepared Profile plan", status=409)
            mapped, revisions = self._resolve(plan.session_ref, desired)
            if mapped != saved[2] or revisions != saved[3]:
                raise ProfileError("SWITCH_BLOCKED", "Model catalogue changed after planning", status=409)
            return self._port(plan.session_ref).apply(plan, mapped)

    def reconcile(self, operation_key, ref):
        with self._lock:
            return self._port(ref).reconcile(operation_key, ref)
