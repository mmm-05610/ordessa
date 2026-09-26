"""The compatibility core plugin — the not-yet-split business domains.

`ordessa.server-compat` is the batch-1 transitional adapter's successor, with
one decisive difference: it is no longer an adapter over host-constructed
services. It **owns** the domains it registers (profiles, provider models,
assets, hooks, accounts, provider artifacts, usage, config, sessions, queue,
approvals, history, executions, delegation) — the records, the services, the
59 wire methods, the business REST routes and the startup recovery work are
built here, from the host's storage ports, exactly once.

Domain retirement path: each domain listed in
`docs/server-core-cleanup-baseline.md` leaves this plugin for its own plugin
in a later batch; its rows leave `_COMPAT_METHODS`/`_PARAM_SHAPES` at the same
time, and the method list may only ever shrink.

Declared edges (pinned by `test_server_compat_boundary.py`):

- host generic vocabulary: `ordessa_server.errors`, `.records`, `.ids`,
  `.wire.{errors,envelope,projection,handlers helpers}` — the shared wire/1
  surface, never host business modules;
- `ordessa_workspace` — the declared `requires` dependency: workspace
  resolution arrives as the `workspace.service` port, and the execution
  domain's native leg reuses the workspace domain's local-path provider;
- `ordessa_harness` — the harness registry lookups the deployment
  compositions already performed at this layer.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_server.wire.errors import WireError
from ordessa_server.wire.envelope import CursorCodec

from ordessa_server_compat.core_wire import (
    _COMPAT_METHODS,
    _EXECUTION_GATE_FAMILY,
    CoreWireHandlers,
    _PARAM_SHAPES,
)

PLUGIN_ID = "ordessa.server-compat"


class ServerCompatPlugin:
    """The compatibility core: every not-yet-split business domain, one plugin."""

    def __init__(
        self, *,
        harnesses: Any | None = None,
        execution: Any | None = None,
        execution_factory: Callable | None = None,
        home_concurrency: Mapping[str, str] | None = None,
        shared_store_guards: Mapping[str, Any] | None = None,
        subscription_files_for: Callable | None = None,
        declared_credentials: "tuple[dict[str, str], ...]" = (),
        native_harness_id: str | None = None,
        native_profile_sink: "Callable[[str], None] | None" = None,
    ) -> None:
        self._harnesses = harnesses
        self._execution = execution
        self._execution_factory = execution_factory
        self._home_concurrency = home_concurrency
        self._shared_store_guards = shared_store_guards
        self._subscription_files_for = subscription_files_for
        self._declared_credentials = tuple(declared_credentials)
        self._native_harness_id = native_harness_id
        #: Composition-injected write-back channel (set after build_runtime
        #: returns, before start runs): the composition owns the runtime, the
        #: plugin owns the fact its start hook records.
        self.native_profile_sink = native_profile_sink
        #: The fact the start hook records in native mode.
        self.native_profile_id: str | None = None
        self._handlers: CoreWireHandlers | None = None
        self._session_records = None
        self._credential_records = None
        self._ports_secret_store = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Compatibility core (domains pending split)",
            version="1", requires=("ordessa.workspace",),
        )

    # -- activation ---------------------------------------------------------

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        database = ports["database"]
        objects = ports["objects"]
        notifier = ports["notifier"]
        idempotency = ports["idempotency"]
        credentials = ports["credentials"]
        secrets_store = ports.get("secret_store")
        connectors = ports.get("connectors") or {"wsl": None, "ssh": None}
        registry = self._harnesses
        if registry is None:
            from ordessa_server_compat.execution import HarnessRegistry

            registry = HarnessRegistry()

        from ordessa_server_compat.approvals import ApprovalRecords
        from ordessa_server_compat.accounts.assets import AccountAssetStore
        from ordessa_server_compat.accounts.records import AccountRecords
        from ordessa_server_compat.assets.catalog import CatalogStore
        from ordessa_server_compat.assets.mcp import McpAssetStore
        from ordessa_server_compat.assets.plugins import PluginAssetStore
        from ordessa_server_compat.assets.records import AssetRecords
        from ordessa_server_compat.assets.skills import SkillAssetStore
        from ordessa_server_compat.hooks.records import HookRecords
        from ordessa_server_compat.hooks.triggers import HookTriggerRecords
        from ordessa_server_compat.model_configs import (
            ProviderModelRecords, ProviderModelService,
        )
        from ordessa_server_compat.profiles import ProfileRecords, ProfileService
        from pacthold.service.sessions import SessionRecords, SessionService
        from pacthold.service.sessions.queue import QueueRecords

        assets_root = context.data_root / "assets"
        profile_records = ProfileRecords(database, idempotency)
        provider_model_records = ProviderModelRecords(database, idempotency)
        session_records = SessionRecords(
            database, idempotency,
            home_concurrency=self._home_concurrency,
            shared_store_guards=self._shared_store_guards,
        )
        account_records = AccountRecords(database, idempotency)
        hook_records = HookRecords(database, idempotency)
        hook_triggers = HookTriggerRecords(database)
        asset_records = AssetRecords(database, idempotency)
        skill_assets = SkillAssetStore(assets_root)
        mcp_assets = McpAssetStore(assets_root)
        plugin_assets = PluginAssetStore(assets_root)
        asset_catalogs = CatalogStore(assets_root / "catalogs")
        # Order 56's encryption-at-rest requirement is the platform SecretStore's:
        # without one, a bound subscription account is a typed refusal at the turn
        # boundary rather than an unencrypted asset.
        account_assets = (
            AccountAssetStore(
                secret_store=secrets_store,
                accounts_root=context.data_root / "accounts",
            )
            if secrets_store is not None else None
        )
        queue_records = QueueRecords(
            database, idempotency, append_event=session_records._append_session_event,
            objects=objects,
        )
        approval_records = ApprovalRecords(
            database, append_event=session_records._append_session_event,
        )

        execution = self._execution
        if execution is None and self._execution_factory is not None:
            execution = self._execution_factory(
                session_records, objects, approval_records, notifier, connectors,
                credentials, secrets_store,
            )
        if execution is not None and hasattr(execution, "bind_queue"):
            execution.bind_queue(queue_records)

        from pacthold.service.facade import ProductService

        workspace_service = ports["workspace.service"]
        profile_service = ProfileService(profile_records, idempotency, objects,
                                         harnesses=registry, credentials=credentials)
        provider_model_service = ProviderModelService(
            provider_model_records, objects, harnesses=registry,
            credentials=credentials, profiles=profile_records,
            secret_store=secrets_store,
        )
        profile_service.bind_model_configs(provider_model_service)
        from ordessa_server_compat.execution.sidecar_backend import (
            SidecarExecutionBackend as _SidecarBackendCls,
        )

        session_service = SessionService(
            session_records, idempotency, objects,
            harnesses=registry, profiles=profile_records,
            credentials=credentials, queue=queue_records,
            execution=execution, on_event=notifier.notify,
            secret_store=secrets_store,
            # a-3 gate fix (C unlock 06:30Z, t52-verified): the filer is
            # composed only when the port is the real sidecar backend -
            # test stacks injecting stand-in ports keep the filing seam
            # dormant exactly as before the flip; production build always
            # composes (the "production must compose" pin stands).
            core_filer=(_core_filer(execution)
                        if isinstance(execution, _SidecarBackendCls)
                        else None))
        session_service.bind_model_configs(provider_model_service)
        service = ProductService(
            workspace_service, profile_service, session_service,
            harnesses=registry, credentials=credentials, execution=execution,
            notifier=notifier,
        )
        from ordessa_server_compat.persistence import ProductRepositoryView

        repository = ProductRepositoryView(
            database=database, idempotency=idempotency, credentials=credentials,
            workspaces=ports["workspace.records"], profiles=profile_records,
            sessions=session_records,
        )
        # Order 65 C: the delegation service and the per-attempt token registry
        # the bridge's loopback calls resolve through.
        from ordessa_server_compat.execution.delegation import DelegationService

        delegation_service = DelegationService(
            records=session_records, profiles=profile_records, sessions=session_service,
            execution=execution, registry=registry, data_root=context.data_root,
            objects=objects,
        )
        delegation_tokens: dict[str, dict[str, str]] = {}

        handlers = CoreWireHandlers(
            profiles=profile_service, sessions=session_service,
            queue=queue_records, approvals=approval_records, harnesses=registry,
            objects=objects, execution=execution,
            codec=ports["cursor.codec"],
            model_configs=provider_model_service,
            accounts=account_records, account_assets=account_assets,
            subscription_files_for=self._subscription_files_for,
            asset_records=asset_records, skill_assets=skill_assets,
            mcp_assets=mcp_assets, plugin_assets=plugin_assets,
            catalogs=asset_catalogs,
            hooks=hook_records, hook_triggers=hook_triggers,
            connectors=connectors, data_root=context.data_root,
            workspaces=workspace_service,
        )
        self._handlers = handlers
        self._session_records = session_records
        self._credential_records = credentials
        self._ports_secret_store = secrets_store

        def execution_gate() -> "tuple[bool, str | None]":
            if handlers.execution is None:
                return False, "EXECUTION_CAPABILITY_UNAVAILABLE"
            return True, None

        methods = []
        for method_id, attribute in _COMPAT_METHODS.items():
            required, optional = _PARAM_SHAPES[method_id]
            methods.append(ServerMethodDescriptor(
                method_id=method_id,
                required_params=frozenset(required),
                optional_params=frozenset(optional),
                handler=getattr(handlers, attribute),
                owner=PLUGIN_ID,
                availability=(execution_gate
                              if method_id in _EXECUTION_GATE_FAMILY else None),
            ))
        methods = tuple(methods)

        from ordessa_server_compat.http import compat_http_routes

        return ServerPluginRegistration(
            methods=methods,
            http_routes=compat_http_routes(
                service=service, repository=repository, notifier=notifier,
                delegation_service=delegation_service,
                delegation_tokens=delegation_tokens,
            ),
            provided_ports={
                "product.service": service,
                "product.repository": repository,
                "harness.directory": registry,
                "execution.port": execution,
                "approvals.records": approval_records,
                "queue.records": queue_records,
                "provider.models": provider_model_service,
                "account.records": account_records,
                "account.assets": account_assets,
                "asset.records": asset_records,
                "asset.skills": skill_assets,
                "asset.mcp": mcp_assets,
                "asset.plugins": plugin_assets,
                "asset.catalogs": asset_catalogs,
                "hook.records": hook_records,
                "hook.triggers": hook_triggers,
                "delegation.service": delegation_service,
                "delegation.tokens": delegation_tokens,
                "sessions.records": session_records,
                "profiles.records": profile_records,
                "events.stream_source": handlers.event_stream_batch,
                "compat.handlers": handlers,
            },
            start_hooks=(self._on_start,),
            disposal=self._dispose,
        )

    # -- startup work that used to live in the host's start() ----------------

    def _on_start(self) -> None:
        """Startup recovery, in the baseline start() order.

        Credential import from the deployment declarations, the native
        profile bootstrap (native compositions only), then sealing the turns
        an interrupted process left behind. Idempotent per start, exactly as
        the host's own recovery steps always were.
        """
        self._import_declared_credentials(
            self._credential_records, self._ports_secret_store,
            self._declared_credentials,
        )
        if self._native_harness_id is not None:
            self._bootstrap_native_profile()
        self._session_records.seal_interrupted_turns()

    def _bootstrap_native_profile(self) -> None:
        import json

        handlers = self._handlers
        harness_id = self._native_harness_id
        profile = handlers.profiles.create_wire(
            f"native-agent-profile:{harness_id}",
            display_name=f"Native {harness_id}",
            harness=harness_id,
        )
        stored = json.loads(handlers.objects.read(profile["config_object_digest"]))
        if (profile["harness_type"] != harness_id
                or profile["archived_at"] is not None
                or profile["credential_id"] is not None
                or profile["account_id"] is not None
                or profile["recovery_pending"]
                or stored.get("configuration") != {}):
            raise RuntimeError("NATIVE_PROFILE_CONFLICT")
        handlers.sessions._assert_profile_executable(profile["id"])
        self.native_profile_id = str(profile["id"])
        if self.native_profile_sink is not None:
            self.native_profile_sink(self.native_profile_id)
        handlers.sessions.bind_native_profile(
            self.native_profile_id, harness_id,
            profile["config_object_digest"],
        )

    @staticmethod
    def _import_declared_credentials(records, store, declarations) -> None:
        """Import each declared source into the Server's own store, once.

        A restart with the same deployment must not duplicate records or
        re-read the source: the declaration names an identity, and an
        identity that already resolves is already satisfied. A declaration
        whose source has since become unreadable fails the start rather than
        quietly leaving a harness without the credential it was declared with.
        """
        for declaration in declarations:
            if records.exists(declaration["credentialId"]):
                continue
            if store is None:
                raise RuntimeError(
                    "SIDECAR_DEPLOYMENT_CREDENTIAL_STORE_MISSING: the deployment "
                    "declares a credential but this Server was composed without "
                    "a secret store"
                )
            from pathlib import Path

            try:
                _store_id, locator = store.import_file(
                    Path(declaration["sourcePath"]), declaration["kind"],
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    f"SIDECAR_DEPLOYMENT_CREDENTIAL_UNREADABLE: "
                    f"{declaration['credentialId']}: {type(exc).__name__}: {exc}"
                ) from exc
            records.register(declaration["credentialId"], declaration["kind"], locator)

    # -- misc ----------------------------------------------------------------

    def _dispose(self) -> None:
        self._handlers = None
        self.native_profile_id = None


def _core_filer(port):
    """a-3 K2-S' flip - central proxy filing authorization
    (`C-notice-S-proxy-two-lines.md` 05:16Z): the two record-filing calls the
    E leg removes from the sidecar accept, re-composed on the Session side.
    The post-commit step (`SessionService.file_core_records`) calls this with
    the Turn's own `execution_key`; dispatch stays in the port."""
    def _file(turn_id: str, session_id: str, execution_key: str):
        work = port.work_service.create_work(
            "AgentBox Session Turn",
            metadata={"session_id": session_id, "turn_id": turn_id},
        )
        core_execution = port.execution_service.create_execution(
            work.id, port.provider.provider_id,
            responsibility_intent="execute one accepted Session Turn through its Harness extension",
            provenance={"session_id": session_id, "turn_id": turn_id},
        )
        return {"work_id": work.id, "core_execution_id": core_execution.id,
                "dispatch_id": None}
    return _file
