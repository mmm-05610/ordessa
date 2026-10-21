"""Current product selection over the original Agent owner and the F1 capabilities.

Two composition paths exist and they are deliberately exclusive:

* **zero configuration (production default)** — the entry point creates this object
  with no arguments; `prepare_http_runtime(config_path=None)` derives the instance
  selection from the C-01 data root (token locator, grants,Profile namespace,
  installed Harness providers) and everything inside the data root is created only
  after the host has locked it.
* **injected inputs (controlled host)** — a caller supplies `AgentOwnerInputs` and
  `HttpOwnerBindings` itself. This is process composition, never an environment
  import or a network-selected callback.

Both paths end in the same assembly: one original Agent owner, one capability list,
one RegistryRuntime, one close order. Missing trusted inputs refuse before any root
write; no token, grant, server id or noop guard is manufactured here.
"""
from pathlib import Path
from dataclasses import dataclass

from ordessa_interfaces_contracts import validate_capability
from ordessa_server.composition.agent_owner import (
    AgentOwnerInputs, AssembledAgentOwner, AgentOwnerUnavailable, _validate_inputs,
    assemble_agent_owner,
)


@dataclass(frozen=True)
class _StoreLocation:
    store_path: Path


class ServerProductComposition:
    def __init__(self, *, agent_owner_inputs=None, http_bindings=None, configuration=None):
        if configuration is not None and (agent_owner_inputs is not None or http_bindings is not None):
            raise AgentOwnerUnavailable(
                'either explicit owner inputs or a service configuration is required, not both')
        if agent_owner_inputs is not None:
            _validate_inputs(agent_owner_inputs)
        from ordessa_server.composition.http_bindings import HttpOwnerBindings
        if http_bindings is not None and type(http_bindings) is not HttpOwnerBindings:
            raise TypeError('explicit original HTTP owner bindings required')
        if configuration is not None:
            from .service_configuration import ServiceConfiguration
            if type(configuration) is not ServiceConfiguration:
                raise TypeError('explicit service configuration required')
        self._agent_owner_inputs = agent_owner_inputs
        self._http_bindings = http_bindings
        self._configuration = configuration

    # -- host CLI seam -------------------------------------------------------

    def server_cli_contributions(self):
        from .service_cli import server_cli_contributions
        return server_cli_contributions()

    def plan_server_cli(self, values):
        from .service_cli import plan_server_cli
        return plan_server_cli(values)

    # -- startup -------------------------------------------------------------

    def require_trusted_startup(self):
        """Refuse before the host creates a root when no trusted selection exists."""
        if self._configuration is not None:
            return self._configuration
        if self._agent_owner_inputs is None:
            raise AgentOwnerUnavailable('original Agent/Profile/catalog/authority bindings required')
        _validate_inputs(self._agent_owner_inputs)
        return self._agent_owner_inputs

    def require_agent_inputs(self):
        """The injected path's validation (kept for the controlled host)."""
        if self._agent_owner_inputs is None:
            raise AgentOwnerUnavailable('original Agent/Profile/catalog/authority bindings required')
        _validate_inputs(self._agent_owner_inputs)
        return self._agent_owner_inputs

    def prepare_http_runtime(self, *, config_path=None):
        """Validate the selection before the transport creates/adopts a root."""
        if config_path is not None:
            return self._prepare_configured_runtime(config_path)
        self.require_agent_inputs()
        if self._http_bindings is None:
            raise AgentOwnerUnavailable('original HTTP authority/context/Server identity required')
        from ordessa_server.composition.packages_convergence import build_product_registry_runtime
        bindings = self._http_bindings

        def build(data_root):
            return build_product_registry_runtime(
                data_root, self, bindings.authority,
                context_factory=bindings.context_factory, server_id=bindings.server_id)

        return build

    def prepare_default_http_runtime(self):
        """Zero-configuration startup: derive the whole selection from the data root.

        The data root is a host-owned flag, so the configuration can only be built
        inside the factory; everything before that point is inert.
        """
        from .service_composition import default_harness_allowlist
        from .service_configuration import default_service_configuration

        def build(data_root):
            configuration = default_service_configuration(
                Path(data_root), harness_allowlist=default_harness_allowlist())
            self._configuration = configuration
            return self._configured_runtime(configuration)(data_root)

        return build

    def _configured_runtime(self, configuration):
        from .service_composition import (
            ServiceStartupError, build_authority, build_context_factory,
            provision_instance_token,
        )
        from ordessa_server.composition.packages_convergence import build_product_registry_runtime

        def authority_factory(root):
            # Runs inside the locked data root: the token file is created here.
            try:
                created = provision_instance_token(configuration.access.token_file)
            except ServiceStartupError as error:
                raise AgentOwnerUnavailable(error.code) from None
            _announce_startup(root, configuration, created)
            return build_authority(configuration)

        def build(data_root):
            return build_product_registry_runtime(
                data_root, self, None,
                authority_factory=authority_factory,
                context_factory=build_context_factory(configuration),
                server_id=configuration.server_id,
                deadline_seconds=configuration.access.request_deadline_seconds)

        return build

    def _prepare_configured_runtime(self, config_path):
        from .service_composition import (
            ServiceStartupError, build_authority, build_context_factory,
            installed_provider_names, provision_instance_token,
        )
        from .service_configuration import ServiceConfigurationError, load_service_configuration
        from ordessa_server.composition.packages_convergence import build_product_registry_runtime

        try:
            configuration = load_service_configuration(
                Path(config_path), harness_default=installed_provider_names())
        except ServiceConfigurationError as error:
            raise AgentOwnerUnavailable("service configuration: " + error.reason) from None
        self._configuration = configuration
        return self._configured_runtime(configuration)

    # -- assembly ------------------------------------------------------------

    def assemble_owner(self, store_path, root_ownership, *, authority=None):
        if self._configuration is not None:
            return self._assemble_configured_owner(store_path, root_ownership, authority)
        inputs = self.require_agent_inputs()
        return assemble_agent_owner(_StoreLocation(Path(store_path)), inputs, root_ownership)

    def _assemble_configured_owner(self, store_path, root_ownership, authority):
        from ordessa_interfaces.system_access.access_control.authentication import (
            InstanceAccessAuthority,
        )
        from .service_composition import build_root_inputs

        if type(authority) is not InstanceAccessAuthority:
            raise AgentOwnerUnavailable('original instance authority required for the configured product')
        store = Path(store_path)
        root = store.parent.parent
        inputs, _profile_owner = build_root_inputs(
            root, self._configuration, authority=authority, root_ownership_proof=root_ownership)
        return assemble_agent_owner(_StoreLocation(store), inputs, root_ownership)

    def build_capabilities(self, owner):
        if (type(owner) is not AssembledAgentOwner or owner._revoked
                or owner.manager.records is not owner.records
                or owner.interactions.records is not owner.records):
            raise AgentOwnerUnavailable('single live original Agent owner required')
        capabilities = tuple(owner.method_factory(owner))
        if not capabilities:
            raise AgentOwnerUnavailable('current product capability bindings required')
        for capability in capabilities:
            validate_capability(capability)
        return capabilities


def create_composition(*, agent_owner_inputs=None, http_bindings=None, configuration=None):
    return ServerProductComposition(
        agent_owner_inputs=agent_owner_inputs, http_bindings=http_bindings,
        configuration=configuration)


def _announce_startup(root, configuration, token_created: bool) -> None:
    """Say what this instance resolved, before the transport starts serving.

    The listening handshake owns stdout (C-02 §3.1), so the banner goes to stderr.
    """
    import sys

    state = "generated" if token_created else "reused"
    print(f"ordessa-server: data root {root}", file=sys.stderr)
    print(f"ordessa-server: instance token {configuration.access.token_file} ({state}, 0600)",
          file=sys.stderr)
    print("ordessa-server: capabilities " + ", ".join(configuration.capabilities), file=sys.stderr)
    admitted = ", ".join(configuration.harness_allowlist) or "(none)"
    print(f"ordessa-server: harness admitted {admitted}", file=sys.stderr)
