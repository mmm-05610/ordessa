"""`SkillsServerPlugin` — the `ordessa.skills` Server plugin (requirement: §G1 slice).

Implements the `server_plugin_api.ServerPlugin` protocol and contributes:

* the descriptor: id ``ordessa.skills``, ``requires=("ordessa.workspace",)``
  — the declared edge is the access grant for the `workspace.records` port,
  which is what the project-layer identity check (G07) consults as its
  :class:`~ordessa_skills.assignments.ports.WorkspaceLookup`;
* the whole `skills.*` method family (`wire.build_methods`), each row with
  its bounded param shape, `owner` and a truthful availability predicate —
  `skills.discoverNative` and `skills.invokeDescriptor` still report
  `unknown` (the merged harness-api publishes the apply-side seam but no
  plugin-readable native-target seam, §G2 read half; and every brand's
  invocation route remains unverified per research/brand-matrix.md),
  everything else the domain actually serves reports `supported`;
* one provided port, ``skills.service`` — the single `SkillsService`
  instance the composition's other consumers address (生产实体只认一份).

The retired `assets.*` compat owner is not composed: this plugin registers
only the `skills.*` namespace, and its live-host registration test asserts
that no `assets.*` method is present. Product assembly into the default
plugin selection is api-requests.md §G1 — C0's integration.

Scope injection (contracts.md: 请求 principal/serverScope 由鉴权注入): the
host hands the plugin its scoped `data_root` and `database`; the service's
server scope is that data root's instance identity and the principal is
the local data-root principal — the Server has no multi-principal auth
concept yet (api-requests.md §G5, 低紧急), so §G5's arrival replaces the
constant below, not any request-handling code.
"""
from __future__ import annotations

from pathlib import Path

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .error_families import SKILLS_ERROR_FAMILIES
from .harness_adapters.contribution import (
    CONFIGURATION_POINT, POINT_API_VERSION,
)
from .service import SkillsService
from .wire import build_methods

PLUGIN_ID = "ordessa.skills"


class WorkspaceRegistryLookup:
    """Adapt the workspace plugin's records port to the domain's
    :class:`~ordessa_skills.assignments.ports.WorkspaceLookup`.

    `WorkspaceRecords.get` raises the host's `ServerError` with code
    ``WORKSPACE_NOT_FOUND`` for an unknown id, while the domain port answers
    `None` and the domain turns that into the typed ``WORKSPACE_UNKNOWN``
    refusal (G07). The adapter duck-types the `code` attribute instead of
    importing `server_plugin_api.internal_errors` — this package's purity pin
    (tests/test_dependency_direction.py) forbids the host import, and the
    mismatch is recorded in the C0 integration report. Any other exception
    propagates unchanged: an outage is never flattened into "unknown id".
    """

    def __init__(self, records) -> None:
        self._records = records

    def get(self, workspace_id: str):
        try:
            return self._records.get(workspace_id)
        except Exception as exc:  # noqa: BLE001 - narrow on the known code
            if getattr(exc, "code", None) == "WORKSPACE_NOT_FOUND":
                return None
            raise

#: §G5 adjudication: one data-root bearer token answers as one local
#: principal until the permissions-api lands. Never taken from a request.
LOCAL_DATA_ROOT_PRINCIPAL = "local-data-root"

#: The domain-owned content root under the injected data root. Kept apart
#: from the legacy compat `assets/` tree so the retirement (C0) can map
#: one into the other explicitly (docs/migration/).
SKILLS_DATA_DIRECTORY = "skills-v2"


class SkillsServerPlugin:
    """The Skills domain: library + assignments + discovery, one service."""

    def __init__(self, *, mandatory_policy=None,
                 permissions=None,
                 contribute_harness_adapters: bool = True) -> None:
        self._service: SkillsService | None = None
        #: The Profile projection remains explicitly unavailable until a
        #: current owner and public input contract are wired.
        self._mandatory_policy = mandatory_policy
        #: the published permissions surface (the `permissions-api`
        #: checkpoint's provided port object — an `Authorizer`, a
        #: `PolicyRepository`, or any callable returning the ceilings in
        #: force). It arrives HERE rather than through `context.ports`
        #: because the host grants another plugin's ports only along a
        #: declared dependency (server_plugin_api/contract.py:258-270) and
        #: Skills must not hard-require permissions
        #: (contracts.md 可选注册不能反转依赖); `ports` is still consulted
        #: first when a composition does declare the edge. Wiring this
        #: argument into the default product is C0's assembly job (§G1,
        #: `plugin_host.provided_port("permissions.authorizer@1")`).
        self._permissions = permissions
        #: the three brand configuration adapters ride the open
        #: `harness.configuration-adapters` point — ON by default, because
        #: a contribution to an unbound point refuses activation (fail
        #: closed, never silently dropped): a composition that selects this
        #: plugin MUST declare and bind the point the way the default
        #: product does (`products/server` `server_contribution_points()`).
        #: A bare test host without the binding passes False explicitly.
        self._contribute_harness_adapters = contribute_harness_adapters

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID,
            display_name="Skills domain (v2)",
            version="1",
            requires=("ordessa.workspace",),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        data_root = Path(context.data_root)
        #: The mandatory port needs the catalogue's asset ids (a ceiling
        #: pattern is a glob over targets; a MandatoryRule names one assetId),
        #: and the catalogue lives on the service that consumes the port — so
        #: the read is late-bound through this holder.
        assembled: dict[str, SkillsService] = {}
        mandatory_policy = self._resolve_mandatory_policy(
            ports,
            asset_id_source=lambda: [
                row["id"] for row in assembled["service"].records.list(
                    kind="skill")])
        service = SkillsService(
            database=ports["database"],
            assets_root=data_root / SKILLS_DATA_DIRECTORY,
            server_scope=str(data_root),
            principal=LOCAL_DATA_ROOT_PRINCIPAL,
            workspace_lookup=(WorkspaceRegistryLookup(ports["workspace.records"])
                              if ports.get("workspace.records") is not None
                              else None),
            mandatory_policy=mandatory_policy,
        )
        assembled["service"] = service
        self._service = service
        methods = build_methods(service, owner=PLUGIN_ID)
        adapter_rows: tuple[Contribution, ...] = ()
        if self._contribute_harness_adapters:
            from .harness_adapters import configuration_adapters
            adapter_rows = tuple(
                Contribution(
                    point_id=CONFIGURATION_POINT,
                    api_version=POINT_API_VERSION,
                    payload=adapter,
                )
                for adapter in configuration_adapters()
            )
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"skills.service": service},
            start_hooks=(service.ensure_schema,),
            disposal=self._dispose,
            # Foundation seam: the wire/1 families of the codes this domain
            # raises are published through the host's open
            # `wire.error-families` point (the C2 contribution transaction),
            # exactly as `ordessa.server-compat` and `ordessa.workspace`
            # declare theirs — the owner is injected by the host at stage
            # time and a conflicting row refuses the whole activation round.
            #
            # Harness-api seam: the three brand configuration adapters ride
            # the published open point `harness.configuration-adapters`
            # (v1, multi-owner); the host binds the harness handler and
            # injects the owner, and the handler's overlap/claim conflict
            # authority refuses a colliding registration (contracts.md
            # §C2) — this plugin never touches the registry itself.
            contributions=ContributionBatch(
                (
                    Contribution(
                        point_id=WIRE_ERROR_FAMILIES_POINT_ID,
                        api_version=WIRE_ERROR_FAMILIES_API_VERSION,
                        payload=SKILLS_ERROR_FAMILIES,
                    ),
                ) + adapter_rows,
                # the Harness point is multi-owner; three rows for it are
                # legitimate only when the batch declares it open.
                open_points=frozenset({CONFIGURATION_POINT}),
            ),
        )

    def _resolve_mandatory_policy(self, ports, *, asset_id_source):
        """Prefer the real published permissions surface; never fake one.

        Order (mandatory_policy.py module docstring owns the why): an explicit
        injection (test seam / a composition that already assembled the
        adapter), then the composed surface — `context.ports` under the
        published port name when the composition declared the dependency edge,
        else the `permissions=` constructor argument — then the typed
        "layer unreadable" default, which keeps every resolve view and every
        assignment write honest about the fact that NO admin constraint was
        consulted (it is not "everything is allowed").

        A surface that cannot be read (permissions-api not importable in this
        install) is reported through the typed unavailable path with its exact
        reason, not swallowed: the adapter's first read raises
        `MANDATORY_POLICY_UNAVAILABLE` at resolution time either way.
        """
        if self._mandatory_policy is not None:
            return self._mandatory_policy
        from .api.errors import AssetDomainError
        from .mandatory_policy import (
            PERMISSIONS_AUTHORIZER_PORT,
            NotConfiguredMandatoryPolicyPort,
            PermissionsCeilingMandatoryPolicyPort,
        )

        surface = None
        try:
            surface = ports.get(PERMISSIONS_AUTHORIZER_PORT)
        except Exception:  # noqa: BLE001 - a non-mapping port view is not an outage
            surface = None
        surface = surface if surface is not None else self._permissions
        if surface is None:
            return NotConfiguredMandatoryPolicyPort()
        try:
            return PermissionsCeilingMandatoryPolicyPort(
                ceiling_source=surface, asset_id_source=asset_id_source)
        except AssetDomainError as exc:
            return NotConfiguredMandatoryPolicyPort(
                reason=f"the composed permissions surface is unusable: {exc}")

    def _dispose(self) -> None:
        self._service = None


__all__ = ["PLUGIN_ID", "LOCAL_DATA_ROOT_PRINCIPAL", "SKILLS_DATA_DIRECTORY",
           "SkillsServerPlugin"]
