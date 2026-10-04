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
from pathlib import Path
from typing import Any

from ordessa_environment_api import GuaranteeUnavailableError
from pacthold.public import CoreContributionSet, Environment


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

    def stage(self, contribution: Any, owner: str) -> Any:
        """Reserve a contribution in the same Environment CoreRegistry."""
        return self.environment.stage_activation(
            owner, _as_contribution_set(contribution.payload)
        )

    def commit(self, contribution: Any, prepared: Any, owner: str) -> None:
        del contribution, owner
        prepared.commit()

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
