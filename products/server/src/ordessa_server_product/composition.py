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

CLI composition mapping: the host CLI parses the same arguments it always
has and asks this product what they mean — default (isolated), native
adapter, or sidecar deployment.
"""
from __future__ import annotations

from typing import Any


class ServerProductComposition:
    """The deployment's plugin selection and CLI composition mapping."""

    #: The composition facts that flow into the compatibility core; the
    #: workspace and ACP facets take none of them.
    _COMPAT_KWARGS = (
        "harnesses", "execution", "execution_factory", "home_concurrency",
        "shared_store_guards", "subscription_files_for", "declared_credentials",
    )

    def default_plugins(self, **composition_kwargs: Any) -> "tuple[Any, ...]":
        """The plugin selection a default (isolated) deployment composes."""
        from ordessa_harness.server_acp.plugin import AcpChannelServerPlugin
        from ordessa_server_compat.plugin import ServerCompatPlugin
        from ordessa_workspace.plugin import WorkspaceServerPlugin

        compat_kwargs = {
            name: composition_kwargs[name]
            for name in self._COMPAT_KWARGS
            if composition_kwargs.get(name) is not None
        }
        return (
            WorkspaceServerPlugin(),
            ServerCompatPlugin(**compat_kwargs),
            AcpChannelServerPlugin(),
        )

    # -- the host CLI's composition mapping ----------------------------------

    def default_runtime(self, data_root: Any) -> Any:
        from ordessa_server.bootstrap import build_runtime

        return build_runtime(data_root)

    def native_runtime(
        self, data_root: Any, *, plugin_root: Any, harness_id: str,
        adapter_command: str, adapter_args: "tuple[str, ...]" = (),
        native_continuation: bool = False,
    ) -> Any:
        from ordessa_server_compat.composition import build_runtime_from_native_adapter

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

        return build_runtime_from_sidecar_deployment(
            data_root, deployment_path, secret_store=secret_store,
            plugin_root=plugin_root, mount_bindings=mount_bindings,
        )


def create_composition() -> ServerProductComposition:
    """The entry-point factory the host resolves the product through."""
    return ServerProductComposition()
