"""`ExtensionsServerPlugin` — the `ordessa.extensions` Server plugin
(016 EXT-1: 域骨架).

Implements the `server_plugin_api.ServerPlugin` protocol and contributes:

* the descriptor: id ``ordessa.extensions``, no declared requires-edge
  (the domain reads no other plugin's ports);
* the `extensions.approvals.*` method family — the EXT-3 approval-state
  diagnosability/revocation face over the one ApprovalLedger the
  composition owns;
* the wire-refusal family rows through the `wire.error-families`
  point (a per-batch exclusive row, same seam as every other plugin —
  only the harness configuration point is declared open);
* the `assets.hooks` facet's C2 registration: one
  `ConfigurationAdapter` per implemented brand (codex, claude — brand
  priority ruling) through the published `harness.configuration-adapters`
  point, the same multi-owner point the Skills domain rides (AR-2). The
  registration refuses activation when the point is not bound (fail
  closed); a bare test host passes `contribute_harness_adapters=False`.

Loader access: the composition-facing provided port `extensions.service`
exposes the `HookLoader` + `ApprovalLedger` pair — the load boundary
where「未批准定义=不装载」is enforced. Product assembly into the default
plugin selection is C0's integration job (api-requests).
"""
from __future__ import annotations

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from . import FACET_ID, PLUGIN_ID
from .adapters.contribution import CONFIGURATION_POINT, POINT_API_VERSION
from .approval import ApprovalLedger
from .error_families import EXTENSIONS_ERROR_FAMILIES
from .loader import HookLoader
from .wire import build_methods


class ExtensionsService:
    """The one composition-owned pair: approval truth + the load gate."""

    def __init__(self) -> None:
        self.ledger = ApprovalLedger()
        self.loader = HookLoader(self.ledger)


class ExtensionsServerPlugin:
    def __init__(self, *,
                 contribute_harness_adapters: bool = True) -> None:
        self._service: ExtensionsService | None = None
        #: ON by default. What THIS side controls is the declaration:
        #: the rows are contributed with the point named in
        #: `open_points`; the stage-time refusal when a composition
        #: selects the plugin WITHOUT binding the point is the HOST's
        #: published behavior (ordessa_harness.contributions + contracts
        #: .md §C2 — "a contribution to an unbound point refuses
        #: activation"), relied on here and exercised by the host's own
        #: tests, not re-implemented in this package. The wire
        #: error-families rows are unconditional (every plugin carries
        #: them); only the harness adapter rows are switched by this
        #: flag — a bare test host that wants no adapter rows passes
        #: False.
        self._contribute_harness_adapters = contribute_harness_adapters

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID,
            display_name="Executable extensions domain (hooks)",
            version="1",
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        service = ExtensionsService()
        self._service = service
        methods = build_methods(service.ledger, owner=PLUGIN_ID)
        adapter_rows: tuple[Contribution, ...] = ()
        if self._contribute_harness_adapters:
            from .adapters import hooks_adapters
            adapter_rows = tuple(
                Contribution(point_id=CONFIGURATION_POINT,
                             api_version=POINT_API_VERSION,
                             payload=adapter)
                for adapter in hooks_adapters())
        #: The point is declared open ONLY when this registration actually
        #: contributes rows to it — an open declaration with zero rows
        #: would be a claim without content (review round 8).
        open_points = (frozenset({CONFIGURATION_POINT})
                       if adapter_rows else frozenset())
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"extensions.service": service},
            contributions=ContributionBatch(
                (Contribution(
                    point_id=WIRE_ERROR_FAMILIES_POINT_ID,
                    api_version=WIRE_ERROR_FAMILIES_API_VERSION,
                    payload=EXTENSIONS_ERROR_FAMILIES,
                ),) + adapter_rows,
                open_points=open_points,
            ),
        )


__all__ = ["FACET_ID", "ExtensionsServerPlugin", "ExtensionsService"]
