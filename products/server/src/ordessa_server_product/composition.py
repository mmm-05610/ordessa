"""The default Ordessa Server product: which plugins a deployment enables.

This package is the assembly decision the plan reserves for the product
manifest: installing a plugin distribution never enables it; installing the
product selection package (and it alone) is what turns a bare Server into
the product. The host resolves exactly one answer from the
`ordessa.server_product` entry-point group — zero or several candidates are
typed startup refusals, never a silent choice.

Selection (core-cleanup stage 3):

- `ordessa.workspace` — the Workspace domain (records, environment
  authority, five `workspaces.*` wire methods, workspace REST surface);
- `ordessa.server-compat` — every not-yet-split business domain, one
  plugin, its wire method list frozen and only allowed to shrink
  (`docs/server-core-cleanup-baseline.md`);
- `ordessa.harness.acp` — the managed ACP channels; without a native
  composition the methods advertise and answer the same typed
  `CAPABILITY_UNSUPPORTED` as before, with no registry composed.
- Sandbox backend and Sandbox/Permissions configuration adapters — the Q5
  descriptive and fail-closed C2 surfaces. The Permissions approval backend
  remains unselected until the compatibility approval writer is retired.

CLI composition mapping: the host CLI keeps only its transport grammar
(`--data-root`, `--port`); this product contributes the business flag
grammar through the `cli.server-flags` point (T014-S4, `cli.py`) and answers
what the parsed values mean — which composition method runs with which
arguments (`plan_server_cli`), or which combination is refused.
"""
from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from server_plugin_api import ContributionPointSpec

from . import cli


class ServerProductComposition:
    """The deployment's plugin selection and CLI composition mapping."""

    def __init__(self) -> None:
        self._point_lock = Lock()
        self._point_specs: tuple[ContributionPointSpec, ...] | None = None

    #: The composition facts that flow into the compatibility core; the
    #: ACP facet takes none of them.
    _COMPAT_KWARGS = (
        "harnesses", "execution", "execution_factory", "home_concurrency",
        "shared_store_guards", "subscription_files_for", "declared_credentials",
    )

    #: T014-S2b: the machine-connector facts flow to the domain that
    #: composes them — the workspace plugin builds its own connectors from
    #: the deployment's machine bindings, and these explicit injections
    #: replace that build for a controlled composition (the former
    #: `build_runtime(connector=...)` path, re-homed through this funnel).
    _WORKSPACE_KWARGS = ("connector", "ssh_connector")

    @staticmethod
    def _assemble_legacy_chain() -> None:
        """T022b: the PRODUCT assembles the sealed legacy migration set.

        Post-convergence the kernel no longer seeds the historical
        ``agent-box.*`` chain implicitly: the refusal raised at
        ``pacthold/work_core/registry.py`` for an un-assembled product is
        correct behaviour, and plan §43 assigns the assembly to this
        composition (「B 默认产品显式装配旧迁移集」).  Both calls below go
        through ``pacthold_runtime_compat`` — the compat assembly seam —
        never by reviving implicit paths inside the kernel.

        ``register_legacy_migrations()`` is idempotent, and this runs at
        composition time — before the host's first Core/legacy connection
        (``ServerRuntime.start()``), which is when the runner applies the
        registered namespaces.
        """
        from pacthold_runtime_compat.legacy_migrations import (
            register_legacy_migrations,
        )

        register_legacy_migrations()

    def database_type(self) -> type:
        """The selected product's storage provider, before any DB is opened."""
        self._assemble_legacy_chain()
        from pacthold_runtime_compat.storage import Database

        return Database

    def server_contribution_points(self) -> tuple[ContributionPointSpec, ...]:
        """Declare the two open Harness points through the public carrier API.

        One registry backs both handlers within this composition. The Server
        host remains responsible for point admission, publication, owner
        injection and busy retirement; this method does not reach into it.
        """
        from ordessa_harness.contributions import (
            CONFIGURATION_POINT, POINT_API_VERSION, RUNTIME_POINT,
            HarnessContributionRegistry,
        )
        from server_plugin_api import (
            ContributionPointSpec, unique_contribution_point_specs,
        )

        with self._point_lock:
            if self._point_specs is None:
                registry = HarnessContributionRegistry()
                self._point_specs = unique_contribution_point_specs((
                    ContributionPointSpec(RUNTIME_POINT, POINT_API_VERSION,
                                          registry.runtime_handler, exclusive=False),
                    ContributionPointSpec(CONFIGURATION_POINT, POINT_API_VERSION,
                                          registry.configuration_handler, exclusive=False),
                ))
            return self._point_specs

    def compatibility_plugins(self, **composition_kwargs: Any) -> "tuple[Any, ...]":
        """Explicit legacy-only selection for controlled host compositions.

        Callers passing ``server_plugins`` bypass product point declarations.
        They may select this contribution-free set explicitly; the default
        product always adds the Q5 plugins through ``default_plugins``.
        """
        self._assemble_legacy_chain()
        from ordessa_harness.server_acp.plugin import AcpChannelServerPlugin
        from ordessa_server_compat.plugin import ServerCompatPlugin
        from ordessa_workspace.plugin import WorkspaceServerPlugin

        compat_kwargs = {
            name: composition_kwargs[name]
            for name in self._COMPAT_KWARGS
            if composition_kwargs.get(name) is not None
        }
        workspace_kwargs = {
            name: composition_kwargs[name]
            for name in self._WORKSPACE_KWARGS
            if composition_kwargs.get(name) is not None
        }
        return (
            WorkspaceServerPlugin(**workspace_kwargs),
            ServerCompatPlugin(**compat_kwargs),
            AcpChannelServerPlugin(),
        )

    def default_plugins(self, **composition_kwargs: Any) -> "tuple[Any, ...]":
        """The full default product selection with its bound Harness points."""
        from ordessa_permissions_adapters import PolicyAdaptersPlugin
        from ordessa_sandbox_adapters import SandboxAdaptersServerPlugin
        from ordessa_sandbox_backend import build_sandbox_plugin

        return (
            *self.compatibility_plugins(**composition_kwargs),
            build_sandbox_plugin(),
            SandboxAdaptersServerPlugin(),
            PolicyAdaptersPlugin(),
        )

    # -- the host CLI's grammar contribution and composition mapping ---------

    def server_cli_contributions(self) -> "cli.ContributionBatch":
        """The business flag grammar the host CLI registers on top of its
        transport flags (`--data-root`, `--port`), contributed through the
        `cli.server-flags` v1 point (T014-S4)."""
        return cli.server_cli_contributions()

    def plan_server_cli(self, values: Mapping[str, Any]) -> "cli.ServerCliPlan":
        """What the parsed CLI values mean: the composition method to call,
        with which arguments, or the refusal to report (T014-S4)."""
        return cli.plan_server_cli(values)

    def default_runtime(self, data_root: Any) -> Any:
        from ordessa_server.bootstrap import build_runtime

        self._assemble_legacy_chain()
        return build_runtime(data_root)

    def native_runtime(
        self, data_root: Any, *, plugin_root: Any, harness_id: str,
        adapter_command: str, adapter_args: "tuple[str, ...]" = (),
        native_continuation: bool = False,
    ) -> Any:
        from ordessa_server_compat.composition import build_runtime_from_native_adapter

        self._assemble_legacy_chain()
        return build_runtime_from_native_adapter(
            data_root, plugin_root=plugin_root, harness_id=harness_id,
            adapter_command=adapter_command, adapter_args=adapter_args,
            native_continuation=native_continuation,
        )

    def sidecar_runtime(
        self, data_root: Any, deployment_path: Any, *, plugin_root: Any,
        mount_bindings: "dict[str, str] | None" = None,
        secret_store: Any | None = None,
    ) -> Any:
        from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment

        self._assemble_legacy_chain()
        return build_runtime_from_sidecar_deployment(
            data_root, deployment_path, secret_store=secret_store,
            plugin_root=plugin_root, mount_bindings=mount_bindings,
        )


def create_composition() -> ServerProductComposition:
    """The entry-point factory the host resolves the product through."""
    return ServerProductComposition()
