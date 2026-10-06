"""Opt-in Profile service with explicit v2 registry reads using existing Server storage.

No plugins, native providers, ambient credentials or daemon are selected by default.
Provider plugins may be explicitly selected through the existing Server host;
this selection supplies no native authority and cold reactivation is refused
without the durable activation-generation evidence this composition writes when
it creates a brand-new persistent Environment on its own exclusive root.

Explicit production owner wiring (``policy_factory`` + ``owner_ports_factory``,
paired, agent-assembly/2 only) assembles the one invocation issuer on the
environment's original store, one verifier consumed by the original records
owner and providers, and the original canonical journal — before the wire can
first obtain agent services. The default Profile/discovery deployment neither
imports nor creates a records owner.

The existing Server database closure is reused; it includes sealed historical
schema support, but no historical Profile/Agent coordinator is activated.
"""
from __future__ import annotations

from pathlib import Path
from functools import partial
from contextlib import closing
import json
import sqlite3
from threading import RLock, get_ident
from uuid import uuid4

from ordessa_environment_api import EnvironmentId, GuaranteeUnavailableError
from ordessa_persistence_sqlite import SqliteStorePort
from pacthold.public import Environment
from pacthold.core.activation_generation import (
    ACTIVATION_SEED_NAMESPACE, ACTIVATION_SEED_RECORD,
    seed_fresh_environment, validate_fresh_basis, bind_journal, verify_journal_binding,
)

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
    def __init__(self, *, fingerprint_port, agent_contract_version="agent-assembly/1",
                 provider_plugins=(), policy_factory=None, owner_ports_factory=None):
        if agent_contract_version not in ("agent-assembly/1", "agent-assembly/2"):
            raise GuaranteeUnavailableError("unsupported Agent public contract")
        if not isinstance(provider_plugins, tuple):
            raise TypeError("explicit provider plugin tuple required")
        if provider_plugins and agent_contract_version != "agent-assembly/2":
            raise GuaranteeUnavailableError("provider selection requires agent-assembly/2")
        if (policy_factory is None) != (owner_ports_factory is None):
            raise GuaranteeUnavailableError(
                "policy and owner ports factories must be supplied together")
        if policy_factory is not None:
            if agent_contract_version != "agent-assembly/2":
                raise GuaranteeUnavailableError(
                    "explicit owner wiring requires agent-assembly/2")
            if not callable(policy_factory) or not callable(owner_ports_factory):
                raise TypeError("policy and owner ports factories must be callable")
        self.provider_plugins = provider_plugins
        self.policy_factory = policy_factory
        self.owner_ports_factory = owner_ports_factory
        self.agent_contract_version = agent_contract_version
        if fingerprint_port is None:
            raise GuaranteeUnavailableError("Agent Tools service requires an explicit protected fingerprint port")
        descriptor = getattr(fingerprint_port, "describe", None)
        if not callable(descriptor) or not callable(getattr(fingerprint_port, "fingerprint", None)):
            raise GuaranteeUnavailableError("protected fingerprint capability is unavailable")
        descriptor()
        self.fingerprint_port = fingerprint_port

    def _policy_for(self, identity):
        if self.policy_factory is not None:
            policy = self.policy_factory(EnvironmentId(identity))
            if (not callable(getattr(policy, "admit_invoke", None))
                    or not callable(getattr(policy, "admit_object_access", None))):
                raise GuaranteeUnavailableError(
                    "policy factory result is not a usable policy port")
            bound = getattr(policy, "environment_id", None)
            if bound is not None and bound != identity:
                raise GuaranteeUnavailableError(
                    "policy is bound to a foreign environment or realm")
            return policy
        policy = _ProfilePolicy(provider_discovery=self.agent_contract_version == "agent-assembly/2")
        policy.environment_id = identity
        return policy

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
            # Reopening an existing root with providers requires the durable
            # activation-generation evidence written in this composition's
            # birth transaction. Historical roots without it are refused
            # before store takeover: nothing is seeded, guessed or migrated,
            # and no journal is deleted to fake a rollback.
            self._require_generation_basis(path, identity)
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
                    # Fresh-environment basis commits together with the
                    # deployment identity: only a brand-new persistent
                    # Environment on this exclusive root is ever seeded.
                    seed_fresh_environment(connection, identity)
            policy = self._policy_for(identity)
            owner_wiring = self.owner_ports_factory is not None

            class OwnedEnvironment(Environment):
                def __init__(self, environment_id, **kwargs):
                    super().__init__(environment_id, **kwargs)
                    self._close_lock = RLock()
                    self._close_active_thread = None
                    self._store_released = False
                    self.owner_ports = None

                @property
                def store_port(self):
                    return store

                def close(self):
                    # Revoke live permission, then settle observation detaches
                    # (re-attempted on every call; never skipped via _closed),
                    # and only then release the store writer lock. Failures
                    # are preserved and raised after the necessary steps; a
                    # failing close keeps the writer lock so the pending
                    # obligations can be retried instead of being swallowed
                    # into a silent success.
                    with self._close_lock:
                        if self._close_active_thread == get_ident():
                            raise GuaranteeUnavailableError(
                                "environment close is already in progress")
                        self._close_active_thread = get_ident()
                        first_error = None
                        try:
                            owner = self.owner_ports
                            if owner is not None:
                                try:
                                    owner.revoke()
                                except BaseException as exc:  # noqa: BLE001
                                    first_error = exc
                            try:
                                super().close()
                            except BaseException as exc:  # noqa: BLE001
                                first_error = first_error or exc
                            else:
                                if not self._store_released:
                                    self._store_released = True
                                    store.close()
                        finally:
                            self._close_active_thread = None
                    if first_error is not None:
                        raise first_error

            env = OwnedEnvironment(identity, store=store, policy=policy,
                                   fingerprint_port=self.fingerprint_port,
                                   principal_scope="local",
                                   activation_generation="durable")
            if owner_wiring:
                self._wire_owner(env, store, identity, path)
            return env
        except BaseException:
            store.close()
            raise

    @staticmethod
    def _require_generation_basis(path, identity):
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                row = connection.execute(
                    "SELECT payload FROM env_domain_records WHERE environment=? AND namespace=? "
                    "AND record_id=?", (identity, ACTIVATION_SEED_NAMESPACE,
                                        ACTIVATION_SEED_RECORD)).fetchone()
            if row is None:
                raise GuaranteeUnavailableError(
                    "durable provider activation generation unavailable on reopen")
            validate_fresh_basis(json.loads(row[0]), identity)
        except GuaranteeUnavailableError:
            raise
        except Exception:
            raise GuaranteeUnavailableError(
                "durable provider activation generation unavailable on reopen") from None

    def _wire_owner(self, env, store, identity, core_path):
        """Assemble the single owner and inject agent services before use.

        The records owner is imported only here: the default Profile/discovery
        deployment never reaches this code and never imports or creates it.
        """
        from .owner_ports import assemble_owner, validate_owner_ports, canonical_journal_path
        from ordessa_harness_records import OperationJournal

        if getattr(env, "owner_ports", None) is not None:
            # One owner per environment instance: a second assembly would mix
            # a second issuer/verifier/scope authority onto the same objects.
            raise GuaranteeUnavailableError("owner already assembled for this environment")
        ports = validate_owner_ports(self.owner_ports_factory(env))
        if getattr(env, "_agent_services", None) is not None:
            raise GuaranteeUnavailableError(
                "owner factory cached agent services before owner assembly")
        journal_path = canonical_journal_path(core_path)
        _guard_core_path(journal_path)
        journal_key = "plugins/profile/native-configuration.sqlite"
        if journal_path.exists():
            # An existing journal (including an empty file) is only adopted
            # with matching trusted ownership evidence; it is never deleted.
            verify_journal_binding(store, identity, journal_key)
        else:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            _guard_core_path(journal_path)
            bind_journal(store, identity, journal_key)
        journal = OperationJournal(journal_path)
        owner = assemble_owner(env, ports, journal)
        env.owner_ports = owner
        try:
            from pacthold.agents.public import agent_services
            agent_services(env, invocation_issuer=owner.issuer,
                           node_evidence_port=ports.node_evidence_port,
                           preparation_context_port=ports.preparation_context_port,
                           preparation_observation_port=ports.preparation_observation_port)
        except ValueError:
            # A cached default service would freeze an issuer-less authority
            # set; fail loudly instead of silently downgrading permissions.
            raise GuaranteeUnavailableError(
                "agent services were cached before owner injection") from None

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
