"""Opt-in Profile service with explicit v2 registry reads using existing Server storage.

No plugins, native providers, ambient credentials or daemon are selected by default.
Provider plugins may be explicitly selected through the existing Server host;
this selection supplies no native authority and cold reactivation is refused.
The existing Server database closure is reused; it includes sealed historical
schema support, but no historical Profile/Agent coordinator is activated.
"""
from __future__ import annotations

from pathlib import Path
from functools import partial
from contextlib import closing
import sqlite3
from uuid import uuid4

from ordessa_environment_api import EnvironmentId, GuaranteeUnavailableError
from ordessa_persistence_sqlite import SqliteStorePort
from pacthold.public import Environment

from .configuration import AgentServiceConfiguration


def _guard_core_path(path):
    path = Path(path)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise GuaranteeUnavailableError("core storage path cannot traverse symlinks")
    for suffix in ("-wal", "-shm"):
        if path.with_name(path.name + suffix).is_symlink():
            raise GuaranteeUnavailableError("core storage sidecars cannot be symlinks")


class _ProfilePolicy:
    def __init__(self, *, provider_discovery=False):
        self.provider_discovery = provider_discovery

    def admit_invoke(self, principal, surface, guarantee):
        return (principal == "local" and guarantee == "reliable" and surface in {
            "pacthold.agents.profiles.create", "pacthold.agents.profiles.edit",
            "pacthold.agents.profiles.clone", "pacthold.agents.profiles.rename",
            "pacthold.agents.profiles.archive", "pacthold.agents.profiles.restore",
        })

    def admit_object_access(self, principal, object_ref, mode):
        if (self.provider_discovery and principal == "local" and mode == "read"
                and object_ref == self.environment_id + ":agents.runtime"):
            return True  # Registry description only; no invocation/execute authority.
        return (principal == "local" and mode in {"read", "write"}
                and object_ref.startswith(self.environment_id + ":agents.profile:"))


class AgentToolsDeployment:
    """Service composition whose key capability must be explicitly supplied."""
    def __init__(self, *, fingerprint_port, agent_contract_version="agent-assembly/1", provider_plugins=()):
        if agent_contract_version not in ("agent-assembly/1", "agent-assembly/2"):
            raise GuaranteeUnavailableError("unsupported Agent public contract")
        if not isinstance(provider_plugins, tuple):
            raise TypeError("explicit provider plugin tuple required")
        if provider_plugins and agent_contract_version != "agent-assembly/2":
            raise GuaranteeUnavailableError("provider selection requires agent-assembly/2")
        self.provider_plugins = provider_plugins
        self.agent_contract_version = agent_contract_version
        if fingerprint_port is None:
            raise GuaranteeUnavailableError("Agent Tools service requires an explicit protected fingerprint port")
        descriptor = getattr(fingerprint_port, "describe", None)
        if not callable(descriptor) or not callable(getattr(fingerprint_port, "fingerprint", None)):
            raise GuaranteeUnavailableError("protected fingerprint capability is unavailable")
        descriptor()
        self.fingerprint_port = fingerprint_port

    def owned_environment_factory(self, store_path, ownership_probe):
        if not callable(ownership_probe) or ownership_probe() is not True:
            raise GuaranteeUnavailableError("exclusive Server data-root ownership is required")
        path = Path(store_path)
        _guard_core_path(path)
        # Refuse adoption of an unrelated database before creating/migrating
        # Environment tables. Only this explicit composition's files qualify.
        identity = None
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "env_meta" not in tables:
                    raise GuaranteeUnavailableError("unowned existing core database requires explicit migration")
                marker = connection.execute("SELECT value FROM env_meta WHERE key='agent_tools_product'").fetchone()
                row = connection.execute("SELECT value FROM env_meta WHERE key='environment_id'").fetchone()
                if marker != ("agent-tools/1",) or row is None:
                    raise GuaranteeUnavailableError("existing core database is not an Agent Tools deployment")
                identity = row[0]
                EnvironmentId(identity)
        if identity is not None and self.provider_plugins:
            # Existing Environment cold activation would reuse its in-memory
            # owner generation. Until durable allocation/bootstrap is composed,
            # refuse before store takeover or provider publication; never guess.
            raise GuaranteeUnavailableError("durable provider activation generation unavailable on reopen")
        # Recheck the OS owner proof immediately before permitting SQL marker
        # takeover. No timeout or stale SQL marker grants ownership.
        if ownership_probe() is not True:
            raise GuaranteeUnavailableError("Server data-root ownership changed")
        _guard_core_path(path)
        store = SqliteStorePort(path, allow_takeover=True)
        try:
            if identity is None:
                identity = "environment-" + uuid4().hex
                with store.transaction() as connection:
                    connection.execute("INSERT INTO env_meta VALUES ('environment_id', ?)", (identity,))
                    connection.execute("INSERT INTO env_meta VALUES ('agent_tools_product', 'agent-tools/1')")
            policy = _ProfilePolicy(provider_discovery=self.agent_contract_version == "agent-assembly/2")
            policy.environment_id = identity
            class OwnedEnvironment(Environment):
                @property
                def store_port(self):
                    return store
                def close(self):
                    if self._closed:
                        return
                    try:
                        super().close()
                    finally:
                        store.close()
            return OwnedEnvironment(identity, store=store, policy=policy,
                                    fingerprint_port=self.fingerprint_port, principal_scope="local")
        except BaseException:
            store.close()
            raise

    def build_runtime(self, configuration: AgentServiceConfiguration):
        if not isinstance(configuration, AgentServiceConfiguration):
            raise TypeError("explicit AgentServiceConfiguration required")
        if configuration.agent_contract_version != self.agent_contract_version:
            raise GuaranteeUnavailableError("service contract selection differs from composition")
        root = configuration.data_root
        if root.exists() and any(root.iterdir()) and not (root / "state" / "core.sqlite").is_file():
            raise GuaranteeUnavailableError("nonempty data root requires an existing Agent Tools deployment")
        core_path = root / "state" / "core.sqlite"
        _guard_core_path(core_path)
        if core_path.exists():
            with closing(sqlite3.connect(core_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "env_meta" not in tables:
                    raise GuaranteeUnavailableError("existing root requires explicit migration")
                marker = connection.execute("SELECT value FROM env_meta WHERE key='agent_tools_product'").fetchone()
                if marker != ("agent-tools/1",):
                    raise GuaranteeUnavailableError("existing root is not an Agent Tools deployment")
        # These imports belong to optional deployment only, never the client.
        from ordessa_server.bootstrap import build_runtime
        from ordessa_server.agent_core_wire import agent_core_methods
        from ordessa_server_product.composition import ServerProductComposition
        from server_plugin_api import ServerPluginSelection
        selection = ServerPluginSelection(plugins=self.provider_plugins, contribution_points=(),
            owned_environment_factory=self.owned_environment_factory,
            core_method_factory=partial(agent_core_methods, contract_version=self.agent_contract_version))
        # Only the public database closure is selected. default_plugins and
        # the default product's Agent/native Environment factory are not used.
        database_factory = ServerProductComposition().database_type()
        return build_runtime(root, server_plugins=selection, database_factory=database_factory)


def build_agent_runtime(configuration: AgentServiceConfiguration, *, fingerprint_port):
    return AgentToolsDeployment(fingerprint_port=fingerprint_port, agent_contract_version=configuration.agent_contract_version).build_runtime(configuration)


def create_agent_app(runtime):
    from ordessa_server.transport.http.app import create_app
    return create_app(runtime)
