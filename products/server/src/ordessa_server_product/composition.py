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

    def __init__(self, *, native_submit_port=None, fingerprint_port=None,
                 submission_policy=None, submission_contributions=None) -> None:
        self._point_lock = Lock()
        self._point_specs: tuple[ContributionPointSpec, ...] | None = None
        self._native_submit_port = native_submit_port
        self._fingerprint_port = fingerprint_port
        self._submission_policy = submission_policy
        self._submission_contributions = submission_contributions
        self._native_channels_selected = False
        self._native_closure_lock = Lock()
        self._native_closure_records: dict[str, dict[str, Any]] = {}
        self._native_closure_blockers: set[tuple[str, str, int]] = set()

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
        """T022b / specs/026 T006-09: the PRODUCT registers the sealed set.

        Post-convergence the kernel no longer seeds the historical
        ``agent-box.*`` chain implicitly: the refusal raised at
        ``pacthold/work_core/registry.py`` for an un-assembled product is
        correct behaviour, and plan §43 assigns the assembly to this
        composition (「B 默认产品显式装配旧迁移集」).  The registration
        point is this product package's explicit
        ``sealed_migrations.register_sealed_legacy_migrations()`` — invoked
        here on the default and native assembly paths, never as an import
        side effect of ``pacthold_runtime_compat`` (the compat module stays
        the thin carrier of the sealed SQL directory, namespace and version
        table; SQL bytes, order, namespace and version table are unchanged).

        Registration is idempotent, and this runs at composition time —
        before the host's first Core/legacy connection
        (``ServerRuntime.start()``), which is when the runner applies the
        registered namespaces.
        """
        from .sealed_migrations import register_sealed_legacy_migrations

        register_sealed_legacy_migrations()

    def owned_environment_factory(self, store_path, ownership_probe):
        if ownership_probe() is not True:
            raise RuntimeError('DATA_ROOT_IN_USE: exclusive ownership is required')
        return self.environment_factory(store_path, _exclusive_owner=ownership_probe)

    def environment_factory(self, store_path, *, _exclusive_owner=None):
        """The product supplies concrete persistence; host/kernel stay neutral.

        No real secret is read at construction. Reliable effects require a
        separately injected protected key/policy/native condition capability.
        Existing historical tables retain their identifiers and are not run.
        """
        from uuid import uuid4
        from ordessa_persistence_sqlite import SqliteStorePort
        from pacthold.environment import Environment

        # The host holds the OS process lock before constructing this store.
        # Acquiring it proves the previous product process released ownership;
        # a stale SQL marker alone never authorizes dispatch or a takeover.
        store = SqliteStorePort(store_path, allow_takeover=(
            _exclusive_owner is not None and _exclusive_owner() is True))
        with store.transaction() as connection:
            row = connection.execute("SELECT value FROM env_meta WHERE key='environment_id'").fetchone()
            identity = row[0] if row else 'environment-' + uuid4().hex
            if row is None:
                connection.execute("INSERT INTO env_meta VALUES('environment_id', ?)", (identity,))

        class ProductEnvironment(Environment):
            @property
            def store_port(self):
                return store

            def close(self):
                if self._closed:
                    return
                super().close()
                store.close()

        class LocalProductPolicy:
            # The product is one authenticated local-user realm. Transport
            # authenticates before entering its business method registry.
            def admit_invoke(self, principal, surface, guarantee):
                return principal == 'local' and (surface in ('agent.configuration-intent', 'agent.configuration-observation')
                    or (self_native_channels and surface in ('native.channel-start', 'native.channel-write', 'native.channel-release')
                        and guarantee == 'raw'))
            def admit_object_access(self, principal, object_ref, mode):
                return principal == 'local'

        self_native_channels = self._native_channels_selected
        from ordessa_agent.contributions import configuration_contributions
        from pacthold.environment import InstallationRecord
        environment = ProductEnvironment(identity, store=store,
            policy=self._submission_policy or LocalProductPolicy(),
            fingerprint_port=self._fingerprint_port)
        environment.install(InstallationRecord('ordessa.agent', 'agent-domain-0.1.0'))
        environment.enable('ordessa.agent')
        agent_receipt = environment.activate('ordessa.agent', configuration_contributions())
        environment.agent_activation = agent_receipt.activation
        if self_native_channels:
            from .native_transport_contributions import native_transport_contributions
            environment.install(InstallationRecord('ordessa.native-channel', 'public-access-entry-transport'))
            environment.enable('ordessa.native-channel')
            channel_receipt = environment.activate('ordessa.native-channel', native_transport_contributions())
            environment.native_channel_activation = channel_receipt.activation
        if self._submission_contributions is not None:
            environment.install(InstallationRecord('ordessa.native-submit', 'declared-native-submit'))
            environment.enable('ordessa.native-submit')
            environment.activate('ordessa.native-submit', self._submission_contributions)
        return environment

    def _submission_service_factory(self, context, owners):
        from pathlib import Path
        from ordessa_persistence_sqlite import SqliteStorePort
        from ordessa_agent.submission_journal import SubmissionJournal, ReliableSubmissionUnsupported
        from ordessa_agent.submission_service import AgentSubmissionService
        if self._native_submit_port is None or self._fingerprint_port is None:
            raise ReliableSubmissionUnsupported('declared native conditional submit/fingerprint capability absent')
        environment = context.ports['core.binding'].environment
        binding = context.ports['core.binding']
        if not binding.owns_data_root:
            raise ReliableSubmissionUnsupported('exclusive data-root ownership is unavailable')
        domain_store = SqliteStorePort(Path(context.data_root) / 'plugins/agent/submissions.sqlite',
                                     allow_takeover=True)
        try:
            journal = SubmissionJournal(domain_store, fingerprint_port=self._fingerprint_port)
            service = AgentSubmissionService(environment=environment, journal=journal,
                owners=owners, native_submit_port=self._native_submit_port)
        except BaseException:
            domain_store.close()
            raise
        service.close = domain_store.close
        return service

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
        """The full default product selection with its bound Harness points.

        S-03 (2026-09-29): ModelProviderPlugin joins the default chain —
        the compat writer retired in W-1 (same batch), so no double-write.
        """
        from ordessa_model_provider.plugin import ModelProviderPlugin
        from ordessa_profile.server_plugin import ProfileServerPlugin
        from ordessa_permissions_adapters import PolicyAdaptersPlugin
        from ordessa_permissions_backend.plugin import PermissionsBackendPlugin
        from ordessa_sandbox_adapters import SandboxAdaptersServerPlugin
        from ordessa_sandbox_backend import build_sandbox_plugin
        from ordessa_agent.plugin import AgentDomainPlugin

        model_provider_kwargs = {
            name: composition_kwargs[name]
            for name in ("harnesses", "secret_store")
            if composition_kwargs.get(name) is not None
        }
        return (
            *self.compatibility_plugins(**composition_kwargs),
            ModelProviderPlugin(**model_provider_kwargs),
            ProfileServerPlugin(),
            build_sandbox_plugin(),
            SandboxAdaptersServerPlugin(),
            PermissionsBackendPlugin(),
            PolicyAdaptersPlugin(),
            # T010-01 (A1): the Agent domain owner serves the 010 consumer
            # migration; one owner set per canonical target, wire projections
            # only — it never becomes a second writer.
            AgentDomainPlugin(submission_service_factory=self._submission_service_factory),
        )

    def bind_contribution_points(self, host) -> None:
        """Pre-bind the harness C2 point so C2-contributing plugins admit.

        The handler is the harness's real ``HarnessContributionRegistry``;
        without this binding the host refuses every C2 batch with
        ``ContributionPointUnboundError`` (the point is declared but nobody
        holds the handler — the composition must wire it).
        """
        from ordessa_harness.contributions import (
            CONFIGURATION_POINT, HarnessContributionRegistry,
        )
        registry = HarnessContributionRegistry()
        host.register_contribution_point(
            CONFIGURATION_POINT, "v1", handler=registry.configuration_handler,
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

    def default_runtime(self, data_root: Any, *, include_profile: bool = True) -> Any:
        from ordessa_server.bootstrap import build_runtime

        self._assemble_legacy_chain()
        from .platform_secrets import product_secret_store
        if type(include_profile) is not bool:
            raise ValueError('include_profile must be boolean')
        plugins = self.default_plugins()
        if not include_profile:
            plugins = tuple(plugin for plugin in plugins if plugin.descriptor().id != 'ordessa.profile')
        runtime = build_runtime(data_root, secret_store=product_secret_store(data_root),
            server_plugins=plugins, product_composition=self)
        return runtime

    def native_runtime(
        self, data_root: Any, *, plugin_root: Any, harness_id: str,
        adapter_command: str, adapter_args: "tuple[str, ...]" = (),
        native_continuation: bool = False,
        installed_artifact_root: str | None = None,
        pi_profile_bridge: bool = False,
        native_profile_harnesses: tuple[str, ...] = (),
        additional_adapters: tuple = (),
        include_profile: bool = True,
    ) -> Any:
        from ordessa_server_compat.composition import build_runtime_from_native_adapter
        from ordessa_model_provider.plugin import ModelProviderPlugin
        from .native_configuration import NativeConfigurationPlugin, PLUGIN_ID as NATIVE_CONFIGURATION_ID
        from ordessa_harness.configuration.model.plugin import ModelProviderAdaptersPlugin
        from ordessa_harness.configuration.model.catalog import ModelConfigurationCatalog

        if type(include_profile) is not bool:
            raise ValueError('include_profile must be boolean')

        self._native_channels_selected = True
        self._assemble_legacy_chain()
        def channel_selection_resolver(*, profile_id, harness_id):
            # Resolve the current activation round; never retain a stopped port.
            sessions = runtime.plugin_host.provided_port('profile.native-sessions')
            if sessions is None:
                from ordessa_profile.errors import ProfileError
                raise ProfileError('APPLICATION_PORT_ABSENT', 'Profile launch service unavailable', status=409)
            return sessions.resolve_launch_selection(profile_id=profile_id, harness_id=harness_id)
        runtime = build_runtime_from_native_adapter(
            data_root, plugin_root=plugin_root, harness_id=harness_id,
            adapter_command=adapter_command, adapter_args=adapter_args,
            native_continuation=native_continuation,
            installed_artifact_root=installed_artifact_root,
            pi_profile_bridge=pi_profile_bridge,
            native_profile_harnesses=native_profile_harnesses,
            additional_adapters=additional_adapters,
            secret_store=self._native_secret_store(data_root),
            channel_selection_resolver=channel_selection_resolver,
            product_composition=self,
            native_transport_admitter=lambda transport: self._admit_native_transport(runtime, transport),
            # 026 T006-09: the product's native assembly does not make a
            # startup-created native Profile its mandatory basis. Native
            # session creation is driven by the first send or an explicit
            # profile selection; the SessionService first-send semantics
            # (NATIVE_FIRST_SEND_REQUIRED, bound-mode identity fences) stand
            # on their own whenever an identity is in fact bound.
            
        )
        pi_artifact_root = installed_artifact_root if harness_id == "pi" else next(
            (binding.get("installedArtifactRoot", installed_artifact_root)
             for binding in additional_adapters if binding["harnessId"] == "pi"), None)
        profile_roots = {hid: (installed_artifact_root if hid == harness_id else next(
            binding.get('installedArtifactRoot', installed_artifact_root)
            for binding in additional_adapters if binding['harnessId'] == hid))
            for hid in native_profile_harnesses}
        if pi_profile_bridge:
            profile_roots['pi'] = pi_artifact_root
        # The independent model application route (021 FR-01) needs the same
        # verified installation routes the Profile route uses; a harness with
        # an artifact root gets its C2 model adapters published even when no
        # Profile route is assembled (include_profile=False, M01).
        model_roots = dict(profile_roots)
        if installed_artifact_root:
            model_roots.setdefault(harness_id, installed_artifact_root)
        for binding in additional_adapters:
            root = binding.get("installedArtifactRoot")
            if root:
                model_roots.setdefault(binding["harnessId"], root)
        def current_ceilings():
            authority = runtime.plugin_host.provided_port("permissions.authorizer@1")
            if authority is None:
                raise RuntimeError("permissions authority is not active")
            return authority.ceiling_provider()

        try:
            profile_plugins = ()
            if include_profile:
                from dataclasses import replace
                from ordessa_profile.server_plugin import ProfileServerPlugin
                from ordessa_model_provider_profile.profile_glue import ModelProviderFacetProvider
                from .skills import ProductSkillsPlugin
                from .profile_sessions import bind_native_profile_sessions

                class NativeProfilePlugin(ProfileServerPlugin):
                    def descriptor(self):
                        original = super().descriptor()
                        return replace(original, requires=(*original.requires, NATIVE_CONFIGURATION_ID))

                profile_plugins = (NativeProfilePlugin(providers=(("ordessa.model-provider-profile",
                    ModelProviderFacetProvider()),),
                    native_registration_factory=lambda core: bind_native_profile_sessions(
                        core, runtime, profile_roots=profile_roots)),
                    # This Skills assembly currently requires Profile. Omitting
                    # it here does not claim Skills has already been decoupled.
                    ProductSkillsPlugin(permissions=current_ceilings))

            def provided_port(port_id):
                return runtime.plugin_host.provided_port(port_id)

            # The one real application seam of the independent model route
            # (021 appendix §3.3) and its queue-time verdict port; both
            # resolve the neutral authority lazily, so injection is identical
            # with and without Profile (FR-01).
            from .turn_application import (
                NativeModelEligibilityPort, ProductTurnApplication,
            )
            turn_application = ProductTurnApplication(
                authority_of=lambda: provided_port("native.configuration"),
                catalog_of=lambda: provided_port("model_provider.catalog"))
            model_eligibility = NativeModelEligibilityPort(
                authority_of=turn_application._authority_of)
            # Bound-mode intent bridge: only a Profile assembly can answer
            # "this native session is a registered Profile session"; without
            # Profile the sink is absent and every session is unbound (FR-01).
            intent_sink = None
            if include_profile:
                from .turn_application import ProfileTurnIntentSink
                intent_sink = ProfileTurnIntentSink(
                    core_of=lambda: provided_port("profile.core"),
                    sessions_of=lambda: provided_port("profile.native-sessions"))
            from ordessa_agent.plugin import AgentDomainPlugin
            agent_bindings = {}
            def resolve_agent_session(location):
                from server_plugin_api import WireError
                authority = provided_port('native.configuration')
                if authority is None:
                    raise WireError('CAPABILITY_UNSUPPORTED', 'native session authority unavailable')
                if location.get('kind') != 'session':
                    raise WireError('INVALID_REQUEST', 'existing native session required')
                try:
                    snapshot = authority.register_native(
                        connection_id=str(location.get('connectionId') or ''),
                        native_session_id=str(location.get('sessionId') or ''))
                except Exception as error:
                    raise WireError('FORBIDDEN', str(error), {'internalCode':'AUTHORIZATION_REFUSED'}) from error
                target = snapshot.target.session_id
                agent_bindings[target] = snapshot.target
                return {'target':target, 'generation':snapshot.target.runtime_generation}

            def validate_agent_target(target):
                authority = provided_port('native.configuration')
                native_target = agent_bindings.get(target)
                if authority is None or native_target is None:
                    return None
                try:
                    snapshot = authority.resolve(native_target)
                    return target if snapshot.target == native_target else None
                except Exception:
                    return None

            extras = (AgentDomainPlugin(target_resolver=validate_agent_target,
                                        session_resolver=resolve_agent_session,
                                        submission_service_factory=self._submission_service_factory),
                      *((ModelProviderAdaptersPlugin(),) if model_roots else ()),
                      NativeConfigurationPlugin(carrier=runtime.plugin_host, roots=model_roots),
                      ModelProviderPlugin(harnesses=ModelConfigurationCatalog(
                          runtime.plugin_host.provided_port("harness.directory")),
                          secret_store=runtime.secret_store,
                          harness_config_port=model_eligibility,
                          turn_application_port=turn_application,
                          turn_intent_sink=intent_sink),
                      *profile_plugins)
            # Native composition uses an explicit base selection. The product,
            # not the host or business plugins, declares its additional points.
            # The host bound this explicit composition's points before
            # activating its selected base; there is one handler per point.
            runtime.plugin_host.activate_all(extras)
            runtime.plugin_selection = (*runtime.plugin_selection, *extras)
        except BaseException as activation_failure:
            try:
                runtime.stop()
            except BaseException as cleanup_failure:
                activation_failure.cleanup_errors = (
                    *getattr(activation_failure, "cleanup_errors", ()), cleanup_failure)
            raise
        return runtime

    def _admit_native_transport(self, runtime, transport):
        from uuid import uuid4
        from .managed_transport import EnvironmentManagedTransport
        from .managed_transport import ManagedTransportStartUnknown

        environment = runtime.core_binding.environment
        activation = getattr(environment, 'native_channel_activation', None)
        if activation is None:
            raise RuntimeError('native channel activation is unavailable; transport start refused')
        blocker_key = (environment.environment_id, activation.plugin_id, activation.generation)
        token = 'native-opening-' + uuid4().hex
        with self._native_closure_lock:
            if blocker_key not in self._native_closure_blockers:
                environment.note_unclassified_delivery(activation)
                self._native_closure_blockers.add(blocker_key)
            self._native_closure_records[token] = {
                'environment': environment,
                'activation': activation,
                'blocker_key': blocker_key,
                'state': 'starting',
                'closure': None,
            }
        try:
            managed = EnvironmentManagedTransport.open(environment, transport)
        except ManagedTransportStartUnknown as exc:
            with self._native_closure_lock:
                record = self._native_closure_records[token]
                record['state'] = 'unknown'
                record['closure'] = exc.pending_closure
                environment.register_settlement(
                    activation.plugin_id,
                    activation.generation,
                    'native-channel-start-unknown:' + exc.pending_closure.request.request_id,
                )
            raise
        except BaseException:
            self._finish_native_closure_record(token)
            raise
        self._finish_native_closure_record(token)
        return managed

    def _finish_native_closure_record(self, token: str) -> None:
        """Remove a start that has a known outcome; clear its shared blocker last."""
        with self._native_closure_lock:
            record = self._native_closure_records.pop(token, None)
            if record is None:
                return
            key = record['blocker_key']
            if not any(item['blocker_key'] == key for item in self._native_closure_records.values()):
                if key in self._native_closure_blockers:
                    record['environment'].resolve_unclassified(record['activation'])
                    self._native_closure_blockers.discard(key)

    def release_pending_native_transport(self, request_id: str) -> Any:
        """Explicitly ask the public transport owner to release an unknown start.

        An unconfirmed receipt or exception keeps the retirement blocker and
        owner handle. Only a truthful confirmed receipt removes the record.
        This is cleanup of an already-owned ambiguous start, not a new
        start/write admission. It remains available after drain and only a
        truthful confirmed receipt removes the blocker. It is never retried
        automatically.
        """
        with self._native_closure_lock:
            match = next((
                (token, record) for token, record in self._native_closure_records.items()
                if record['state'] == 'unknown'
                and record['closure'].request.request_id == request_id
            ), None)
            if match is None:
                raise KeyError('unknown pending native transport request')
            token, record = match
            if record.get('cleaning'):
                raise RuntimeError('pending native transport cleanup is already in progress')
            record['cleaning'] = True
            closure = record['closure']
        try:
            receipt = closure.transport.release_owned_after_unknown_start()
        except BaseException:
            with self._native_closure_lock:
                current = self._native_closure_records.get(token)
                if current is not None:
                    current['cleaning'] = False
            raise
        if not isinstance(receipt, Mapping) or receipt.get('confirmed') is not True:
            with self._native_closure_lock:
                current = self._native_closure_records.get(token)
                if current is not None:
                    current['cleaning'] = False
            return receipt
        closure.environment.register_settlement(
            closure.activation.plugin_id,
            closure.activation.generation,
            'native-channel-release-confirmed:' + closure.request.request_id,
        )
        self._finish_native_closure_record(token)
        return receipt

    @staticmethod
    def _native_secret_store(data_root):
        from .platform_secrets import product_secret_store
        return product_secret_store(data_root)

    def sidecar_runtime(
        self, data_root: Any, deployment_path: Any, *, plugin_root: Any,
        mount_bindings: "dict[str, str] | None" = None,
        secret_store: Any | None = None,
    ) -> Any:
        from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment

        self._assemble_legacy_chain()
        if secret_store is None:
            from .platform_secrets import product_secret_store
            secret_store = product_secret_store(data_root)
        return build_runtime_from_sidecar_deployment(
            data_root, deployment_path, secret_store=secret_store,
            plugin_root=plugin_root, mount_bindings=mount_bindings,
        )


def create_composition() -> ServerProductComposition:
    """The entry-point factory the host resolves the product through."""
    return ServerProductComposition()
