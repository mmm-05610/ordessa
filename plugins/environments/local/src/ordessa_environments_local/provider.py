"""Local ``isolation=none`` environment resource provider.

This is the only environment implementation required for v1. It reports its real
isolation level honestly (``"none"``), refuses a configuration reference that
asks for anything it does not actually provide, and never claims a guarantee it
cannot check. Managed consumers acquire a :class:`LocalUse` (the v1 composition
Use); the retired ``LocalEnvironmentHandle``/``LocalEnvironmentProvider`` path
no longer exists.

``release`` is not ``destroy``: releasing a use leaves the working directory,
the file area and every shared resource intact. Nothing in this module deletes a
project directory, and nothing removes a user resource.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping

from ordessa_environments import (
    BackendNotFound,
    BackendObservation,
    CapabilityReport,
    EnvironmentRefused,
)

from .composition import ISOLATION, MANAGED_VALUES, LocalUse

#: Reference keys this provider accepts. Anything else is refused, never ignored.
REFERENCE_KEYS = frozenset({"isolation", "root"})


def resolve_reference(reference: Mapping[str, Any] | None, *, default_root: str) -> Mapping[str, Any]:
    """Turn a configuration reference into concrete, checked settings.

    A reference asking for a different isolation level, or carrying an unknown
    key, is refused — never silently downgraded to ``none``.
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
    root = reference.get("root", default_root)
    if not isinstance(root, str) or not root or not os.path.isabs(root):
        raise EnvironmentRefused("environment root must be an absolute path")
    return {"isolation": ISOLATION, "root": os.path.normpath(root)}


def probe_local(*, default_root: str) -> Mapping[str, object]:
    """Report what the local provider can really do here, without opening anything.

    ``capabilities`` is the derived proven view of the managed report; the
    explicit terminal non-claim is reported through the composition
    ``CapabilitySet`` instead of being advertised as a local capability.
    """
    if not isinstance(default_root, str) or not os.path.isabs(default_root):
        raise EnvironmentRefused("local probe requires an absolute default root")
    return {
        "provider": "local",
        "available": True,
        "isolation": ISOLATION,
        "capabilities": sorted(
            key for key, status in MANAGED_VALUES.items() if status.value == "supported"
        ),
        "defaultRoot": os.path.normpath(default_root),
    }


class LocalEnvironmentResourceProvider:
    """Development adapter over existing Local mechanics; never an isolation fallback.

    Immutable backend identity is the physical directory root. A directory has
    no isolated runtime stop/start/delete; these effects explicitly refuse.
    Each use returns the managed :class:`LocalUse`, which preserves files and
    owns the real launch seam.
    """
    identity = 'local'
    binding_id = 'local-development-process-v1'
    operations = frozenset()

    def __init__(self, *, default_root):
        if not isinstance(default_root, str) or not os.path.isabs(default_root):
            raise EnvironmentRefused('local provider requires an absolute default root')
        self._default_root = os.path.normpath(default_root)

    def create(self, reference, *, operation_id):
        settings = resolve_reference(reference, default_root=self._default_root)
        root = str(settings['root'])
        try:
            os.makedirs(root, exist_ok=True)
        except OSError as error:
            raise EnvironmentRefused(f'environment root could not be provisioned: {error}') from error
        return self.inspect(os.path.realpath(root))

    def inspect(self, backend_id):
        if not isinstance(backend_id, str) or not os.path.isabs(backend_id):
            raise EnvironmentRefused('local backend identity must be an absolute root')
        if os.path.realpath(backend_id) != backend_id:
            raise EnvironmentRefused('local backend root identity changed')
        if not os.path.isdir(backend_id):
            raise BackendNotFound('local backend directory is absent')
        return BackendObservation(backend_id, 'running',
            CapabilityReport(dict(MANAGED_VALUES), ISOLATION, 'provider_self_report', '',
                {'resourceKind':'directory', 'provider':'local'}),
            datetime.now(timezone.utc).isoformat())

    def open_use(self, backend_id, *, use_id, generation):
        self.inspect(backend_id)
        return LocalUse(use_id, backend_id, generation=generation)

    def recover_creation(self, operation_id):
        raise EnvironmentRefused('Local has no external creation-correlation authority')

    def start(self, backend_id):
        raise EnvironmentRefused('Local directory resource has no isolated start operation')

    def stop(self, backend_id):
        raise EnvironmentRefused('Local directory resource cannot stop external processes')

    def delete(self, backend_id):
        raise EnvironmentRefused('Local resource deletion is unavailable; user files are preserved')


__all__ = [
    "ISOLATION",
    "MANAGED_VALUES",
    "REFERENCE_KEYS",
    "LocalEnvironmentResourceProvider",
    "probe_local",
    "resolve_reference",
]
