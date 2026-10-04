"""Server's compatibility facade for the composition's single Environment.

This module only forwards identity and contribution registration to the
Environment supplied by the selected product. It owns no registry, SQLite
connection, execution runtime, or effect-dispatch fallback. In particular,
legacy Core ``ExecutionPlan`` verbs are intentionally absent: the frozen
Environment activity contract is not a signature-compatible substitute for
that older execution API.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from ordessa_environment_api import GuaranteeUnavailableError
from pacthold.public import CoreContributionSet, Environment, InstallationRecord
from server_plugin_api import ServerPluginDescriptor


def _as_contribution_set(payload: Any) -> CoreContributionSet:
    """Translate the plugin contribution payload through the frozen C1 DTO."""
    if isinstance(payload, CoreContributionSet):
        return payload
    if isinstance(payload, Mapping):
        return CoreContributionSet(**payload)
    return CoreContributionSet(
        contracts=payload.contracts,
        resource_providers=payload.resource_providers,
        execution_providers=payload.execution_providers,
    )


@dataclass
class _OwnerActivation:
    """Per-host-round bookkeeping, subordinate to Environment authority."""

    descriptor: ServerPluginDescriptor
    enabled_here: bool
    activation_ref: Any = None


class CoreBinding:
    """A thin per-composition facade over a product-created Environment.

    The factory is product supplied because the product owns concrete storage
    construction. Server and Pacthold never import a concrete SQLite adapter.
    A missing factory is an explicit unavailable capability; it does not
    create an in-memory substitute that could be mistaken for the composition
    authority.
    """

    def __init__(
        self,
        store_path: Path | str,
        *,
        environment_factory: Callable[[Path], Environment] | None = None,
        ownership_probe: Callable[[], bool] | None = None,
    ) -> None:
        if not isinstance(store_path, (Path, str)):
            raise TypeError(f"CoreBinding store_path must be Path or str, got {store_path!r}")
        self._store_path = Path(store_path)
        self._environment_factory = environment_factory
        self._ownership_probe = ownership_probe
        self._environment: Environment | None = None
        self._closed = False
        self._ever_opened = False
        self._owner_activations: dict[str, _OwnerActivation] = {}

    @property
    def owns_data_root(self) -> bool:
        return self._ownership_probe is not None and self._ownership_probe() is True

    @property
    def store_path(self) -> str:
        """Path passed to the product factory; Server never opens it itself."""
        return str(self._store_path)

    @property
    def ever_opened(self) -> bool:
        return self._ever_opened

    @property
    def environment(self) -> Environment:
        return self.open()

    @property
    def shutdown_report(self) -> None:
        """The frozen Environment API has no shutdown-report contract."""
        return None

    def open(self) -> Environment:
        """Return this round's exact product Environment.

        After close, a new round can only be created by the product factory,
        which is responsible for reopening the same durable environment.
        """
        if self._environment is not None and not self._closed:
            return self._environment
        if self._environment_factory is None:
            raise GuaranteeUnavailableError(
                "the selected product did not provide an Environment factory; "
                "Server effects are unavailable"
            )
        environment = self._environment_factory(self._store_path)
        if not isinstance(environment, Environment):
            raise TypeError("environment_factory must return pacthold.public.Environment")
        self._environment = environment
        self._closed = False
        self._ever_opened = True
        return environment

    def close(self) -> None:
        """Close the Environment without inventing a shutdown success report."""
        if self._owner_activations:
            owners = ", ".join(sorted(self._owner_activations))
            raise GuaranteeUnavailableError(
                "cannot close the Environment while owner lifecycle retirement "
                f"is unsettled: {owners}"
            )
        if self._environment is None or self._closed:
            return None
        environment = self._environment
        self._closed = True
        environment.close()
        return None

    # -- registration: one Environment registry and activation authority ----

    def bind_owner(self, owner: str, contributions: Any) -> Any:
        """Convenience activation for callers outside the host transaction."""
        prepared = self.environment.stage_activation(owner, _as_contribution_set(contributions))
        prepared.commit()
        return prepared

    def unbind_owner(self, owner: str) -> None:
        del owner
        raise GuaranteeUnavailableError(
            "owner-only unbind is unavailable; retirement requires the Environment activation ref"
        )

    def snapshot(self) -> Any:
        return self.environment.registry_snapshot

    # -- pacthold.contributions point handler -------------------------------

    def begin_owner_activation(self, descriptor: ServerPluginDescriptor) -> Any:
        """Explicitly install/enable the selected owner before C2 staging.

        The host calls this only after method, stream and HTTP declarations
        have passed preflight. Environment remains the enablement and
        activation authority; this facade records only which enablement this
        host round introduced so rollback cannot disable another owner's
        prior selection.
        """
        if not isinstance(descriptor, ServerPluginDescriptor):
            raise TypeError("owner activation requires a trusted ServerPluginDescriptor")
        owner = descriptor.id
        if owner in self._owner_activations:
            raise RuntimeError(f"owner {owner!r} already has an unsettled activation token")
        environment = self.environment
        manifest = json.dumps(
            {
                "id": descriptor.id,
                "version": descriptor.version,
                "api_version": descriptor.api_version,
                "requires": list(descriptor.requires),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_digest = hashlib.sha256(manifest).hexdigest()
        if owner not in environment.installed:
            environment.install(InstallationRecord(owner, manifest_digest))
        enabled_here = owner not in environment.enabled
        if enabled_here:
            environment.enable(owner)
        token = _OwnerActivation(descriptor=descriptor, enabled_here=enabled_here)
        self._owner_activations[owner] = token
        return token

    def rollback_owner_activation(self, descriptor: ServerPluginDescriptor,
                                  token: Any) -> None:
        """Undo only this host round's enablement after exact retirement."""
        tracked = self._owner_token(descriptor, token)
        environment = self.environment
        if tracked.activation_ref is not None:
            status, blockers = environment.retire_activation(tracked.activation_ref)
            if status != "retired":
                raise RuntimeError(
                    f"Environment activation retirement remains {status}: {blockers}"
                )
        if tracked.enabled_here and descriptor.id in environment.enabled:
            environment.disable(descriptor.id)
        self._owner_activations.pop(descriptor.id, None)

    def retire_owner_activation(self, descriptor: ServerPluginDescriptor,
                                token: Any) -> None:
        """Retire the exact Environment generation before host unpublishes it."""
        tracked = self._owner_token(descriptor, token)
        if tracked.activation_ref is None:
            raise RuntimeError(
                f"owner {descriptor.id!r} has no committed Environment activation ref"
            )
        status, blockers = self.environment.retire_activation(tracked.activation_ref)
        if status != "retired":
            raise RuntimeError(
                f"Environment activation retirement remains {status}: {blockers}"
            )
        if tracked.enabled_here and descriptor.id in self.environment.enabled:
            self.environment.disable(descriptor.id)
        self._owner_activations.pop(descriptor.id, None)

    def _owner_token(self, descriptor: ServerPluginDescriptor, token: Any) -> _OwnerActivation:
        if not isinstance(descriptor, ServerPluginDescriptor):
            raise TypeError("owner lifecycle requires a trusted ServerPluginDescriptor")
        tracked = self._owner_activations.get(descriptor.id)
        if tracked is None or tracked is not token or tracked.descriptor is not descriptor:
            raise RuntimeError(f"owner lifecycle token mismatch for {descriptor.id!r}")
        return tracked

    def stage(self, contribution: Any, owner: str) -> Any:
        """Reserve a contribution in the same Environment CoreRegistry."""
        return self.environment.stage_activation(
            owner, _as_contribution_set(contribution.payload)
        )

    def commit(self, contribution: Any, prepared: Any, owner: str) -> None:
        del contribution, owner
        receipt = prepared.commit()
        tracked = self._owner_activations.get(getattr(receipt.activation, "plugin_id", ""))
        if tracked is not None:
            tracked.activation_ref = receipt.activation

    def rollback(self, contribution: Any, prepared: Any, owner: str) -> None:
        """Delegate rollback/retirement to the Environment's staged handle."""
        del contribution, owner
        state = getattr(prepared, "state", None)
        if state in ("rolled_back", "retired"):
            return
        if state == "staged":
            prepared.rollback()
            return
        if state == "committed":
            status, blockers = self.environment.retire_activation(prepared.receipt.activation)
            if status != "retired":
                raise RuntimeError(
                    f"Environment activation retirement remains {status}: {blockers}"
                )
            return
        raise RuntimeError(f"unknown Environment registration state: {state!r}")
