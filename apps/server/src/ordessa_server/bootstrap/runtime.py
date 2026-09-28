"""Bootstrap assembly: the generic host composition root.

The host composes only what it owns — the data root, the storage primitives,
the transport walls, the plugin host — and resolves the deployment's business
composition through the product seam: exactly one installed product package
answers the `ordessa.server_product` entry point with its plugin selection.
Business domains live in `plugins/*`; `products/server` decides which are
enabled. Nothing here imports a plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import closing
import csv
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
from typing import Any, Callable
from uuid import uuid4

from ordessa_server.credentials import CredentialRecords
from ordessa_server.core_binding import CoreBinding
from ordessa_server.events import EventNotifier
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.storage_port import DatabasePort
from pacthold.storage import ObjectStore, SecretStore


class LegacyMigrationProviderMissingError(RuntimeError):
    """A historical data root cannot be opened without its sealed SQL chain."""

    code = "LEGACY_MIGRATION_PROVIDER_MISSING"


class DataRootPathUnsafeError(RuntimeError):
    """A Server-owned database path must not traverse a symbolic link."""

    code = "DATA_ROOT_PATH_UNSAFE"


class StorageProviderMissingError(RuntimeError):
    """A selected composition has no database schema provider installed."""

    code = "SERVER_STORAGE_PROVIDER_MISSING"


def _reject_unsafe_data_root_links(root: Path) -> None:
    state = root / "state"
    database = state / "agentbox.sqlite"
    for path in (
        state,
        database,
        state / "agentbox.sqlite-wal",
        state / "agentbox.sqlite-shm",
    ):
        if path.is_symlink():
            raise DataRootPathUnsafeError(
                "DATA_ROOT_PATH_UNSAFE: Server state/database paths cannot be symlinks"
            )


def _require_legacy_provider_for_historical_root(root: Path) -> None:
    """Read the old database before marker, schema, or token writes.

    The legacy ledger itself marks a root that needs the historical chain.
    Inspecting via SQLite's immutable read-only URI does not create a missing
    database, lock file, or WAL sidecar. A fresh root has no database yet.
    """
    _reject_unsafe_data_root_links(root)
    database_path = root / "state" / "agentbox.sqlite"
    if not database_path.is_file():
        return
    uri = database_path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        historical = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('schema_versions', 'core_works') LIMIT 1"
        ).fetchone() is not None
    # Immutable reads intentionally ignore WAL. If one exists, do not infer
    # "fresh" from the main file alone and permit an unregistered migration
    # provider to touch an ambiguous historical root.
    historical = historical or database_path.with_name(database_path.name + "-wal").exists()
    if not historical:
        return
    from importlib.util import find_spec
    if find_spec("pacthold_runtime_compat") is None:
        raise LegacyMigrationProviderMissingError(
            "LEGACY_MIGRATION_PROVIDER_MISSING: historical data root requires "
            "the agent_box_legacy migration source before startup"
        )
    from pacthold_runtime_compat.legacy_migrations import (
        LEGACY_MIGRATION_NAMESPACE, legacy_migration_source, db as core_db,
    )
    expected = legacy_migration_source()
    present = any(
        source.namespace == LEGACY_MIGRATION_NAMESPACE
        and source.version_table == expected.version_table
        and source.directory.resolve() == expected.directory.resolve()
        for source in core_db.registered_migration_sources()
    )
    if not present:
        raise LegacyMigrationProviderMissingError(
            "LEGACY_MIGRATION_PROVIDER_MISSING: historical data root requires "
            "the agent_box_legacy migration source before startup"
        )


class LegacyCoreBinding:
    """Composition-owned binding of the LEGACY global Core connection (S1c).

    The S1c file-topology decision, landed with T015 in the same commit:
    the new C1 core instance gets **its own file inside the data root**
    (`<data root>/state/core.sqlite`, owned by :class:`CoreBinding`), not
    the legacy product database file — because ``CoreStore`` is self-owned
    (``sqlite3.connect(path, timeout=10.0, check_same_thread=False)``, no
    connection-injection seam) and the host's in-process write lock does
    not serialise a second OS-level connection over the same file. The
    counterexample witness is
    `apps/server/tests/platform/test_platform_core_instance_124.py::
    test_shared_file_topology_counterexample_double_applies_a_write`.

    What remains legacy is the process-global migration-runner connection
    the compatibility ``CoreRepository()`` still resolves through (it takes
    no store at the consumed A SHA), so the binding cannot be deleted this
    slice — it becomes composition-owned instead: built once per
    composition by ``build_runtime``, binding exactly the server-owned
    database file, and the only site of the host that touches the global.
    The legacy SQL chain itself is assembled by the PRODUCT before the
    first connection below (T022b: ``products/server`` →
    ``pacthold_runtime_compat.legacy_migrations.register_legacy_migrations()``,
    idempotent, plan §43 「B 默认产品显式装配旧迁移集」).
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def connect(self) -> None:
        from pacthold_runtime_compat.legacy_migrations import db as core_db
        core_db.configure_database(self.database_path)
        core_db.get_conn()

    def release(self) -> None:
        from pacthold_runtime_compat.legacy_migrations import db as core_db
        core_db.configure_database(None)


class DataRootOwner:
    """Exclusive process lock and identity marker for one data root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.instance_id = f"server_{uuid4().hex}"
        self._stream = None

    def acquire(self) -> None:
        marker = self.root / ".agentbox-server-root"
        if self.root.exists() and not marker.exists():
            raise RuntimeError("DATA_ROOT_UNOWNED: existing directory has no AgentBox owner marker")
        self.root.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            marker.write_text("agentbox-server-r1\n", encoding="utf-8")
        elif marker.read_text(encoding="utf-8") != "agentbox-server-r1\n":
            raise RuntimeError("DATA_ROOT_MARKER_INVALID")
        lock_path = self.root / "server.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError("DATA_ROOT_IN_USE") from exc
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, (self.instance_id + "\n").encode("ascii"))
        os.fsync(descriptor)
        self._stream = stream

    def release(self) -> None:
        if self._stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(self._stream.fileno(), 0, os.SEEK_SET)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._stream = None

    @property
    def acquired(self) -> bool:
        return self._stream is not None


def _ensure_token(root: Path) -> tuple[str, Path]:
    path = root / "secrets" / "http-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text(encoding="ascii").strip()
        if len(token) < 32:
            raise RuntimeError("HTTP_TOKEN_INVALID")
        _protect_token(path)
        return token, path
    token = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(token + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _protect_token(path)
    return token, path


def _protect_token(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    # whoami/icacls answer in the console codepage (GBK on zh-CN hosts); the
    # only bytes this code reads back are the ASCII SID, so a lossy decode is
    # strictly better than dying on a localized machine or user name -
    # especially under PYTHONUTF8, where the default decode is always utf-8.
    identity = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        check=True, capture_output=True, text=True, errors="replace", timeout=5,
    )
    rows = list(csv.reader(io.StringIO(identity.stdout)))
    if len(rows) != 1 or len(rows[0]) < 2 or not rows[0][1].startswith("S-"):
        raise RuntimeError("WINDOWS_IDENTITY_UNAVAILABLE")
    sid = rows[0][1]
    subprocess.run(
        ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(F)"],
        check=True, capture_output=True, text=True, errors="replace", timeout=5,
    )


# T014-S2b: this file no longer builds machine connectors. The `_builtin_
# connector` / `_builtin_ssh_connector` builders, their AGENT_BOX_* process
# bindings and the connector entry-point lookup live in `plugins/workspace`
# (`ordessa_workspace.connectors`): the domain whose `kind ∈ {local, wsl,
# ssh}` decision gives a connector meaning composes them and provides them
# as plugin ports. The host resolves them through
# `plugin_host.provided_port(...)`, never by importing a builder.


@dataclass
class ServerRuntime:
    """The generic host's runtime: storage primitives, the transport, the plugin
    host.

    It carries no business attribute. What the plugins provide is read from the
    plugin host's declared ports (`plugin_host.provided_port(name)`, or the
    `context.ports` a plugin receives for the dependencies it declares), so the
    runtime cannot be a bag of domain objects and a stopped round cannot leave
    one of its objects bound here (FR-006).
    """
    data_root: Path
    database: DatabasePort
    objects: ObjectStore
    owner: DataRootOwner
    token: str = field(repr=False)
    token_path: Path
    notifier: EventNotifier
    secret_store: SecretStore | None = None
    wire: Any | None = None
    #: Credential declarations from the deployment document, imported on start
    #: (the store and the records table both exist only once the schema is up).
    declared_credentials: tuple[dict[str, str], ...] = ()
    native_harness_id: str | None = None
    native_profile_id: str | None = None
    #: The plugin host (batch 1): the one wire/1 dispatch registry and the
    #: activation/lifecycle of the Server's plugins.
    plugin_host: Any | None = None
    #: The explicit selection this runtime was composed with, kept so a
    #: start() after a stop() re-activates the same plugins (a wire surface
    #: that loses its domains on restart is a broken restart).
    plugin_selection: Any | None = None
    #: T015: this composition's single Pacthold seam — one CoreBinding per
    #: runtime, constructed by build_runtime, never a module global.
    core_binding: CoreBinding | None = None
    #: S1c: the composition-owned binding of the legacy global Core
    #: connection (the server-owned database file).
    legacy_core: LegacyCoreBinding | None = None
    #: The ShutdownReport the composition's stop() surfaced (T015: the
    #: report is a fact of the round, never a discarded return value).
    core_shutdown_report: Any | None = None
    started: bool = False

    def start(self) -> None:
        if self.started:
            return
        if not self.owner.acquired:
            self.owner.acquire()
        try:
            # T015/S1c: a stopped round's Core binding re-opens its instance
            # store BEFORE the plugins re-activate — a contribution round
            # that stages into a closed seam would abort the restart, and a
            # round that never used Core stays lazily closed: no core file
            # is grown by a composition that does not need it.
            if self.core_binding is not None and self.core_binding.ever_opened:
                self.core_binding.open()
            # Re-activation after a stop is inside the cleanup: a flaky plugin
            # failing its second build must not keep the data-root lock.
            if (self.plugin_host is not None and self.plugin_selection
                    and not self.plugin_host.active_ids()):
                self.plugin_host.activate_all(self.plugin_selection)
                # Nothing to re-bind: a port read after this point resolves
                # against THIS round, because it goes through the plugin host.
            self.database.initialize()
            # Each plugin's own startup recovery runs after the schema is up,
            # in activation order: the workspace domain marks its records
            # unverified, the compatibility core imports the deployment's
            # declared credentials, bootstraps a native profile when the
            # composition declares one, and seals the turns an interrupted
            # process left behind. Idempotent per start, each owned by the
            # domain whose records it touches.
            for plugin_id in self.plugin_host.active_ids():
                for hook in self.plugin_host.active(plugin_id).registration.start_hooks or ():
                    hook()
            if self.legacy_core is not None:
                self.legacy_core.connect()
        except BaseException as start_failure:
            # S1c: composition-owned release of the legacy global binding.
            if self.legacy_core is not None:
                self.legacy_core.release()
            # A failed start must not leave the round active with the lock
            # gone: the next process could own the same data root while this
            # round's plugin resources are still alive. Dispose the round
            # (reverse order, every plugin exactly once), keep the start
            # error primary with any disposal failures attached, then release.
            # The start failure is passed EXPLICITLY: reading sys.exc_info()
            # inside the inner except would capture the cleanup exception.
            try:
                if self.plugin_host is not None and self.plugin_host.active_ids():
                    try:
                        self.plugin_host.shutdown()
                    except BaseException as cleanup_failure:
                        _attach_shutdown_cleanup(start_failure, cleanup_failure)
            finally:
                # T015: the dead round's Core binding closes after the
                # plugins retired (their retirement unbinds their owners
                # through the seam) and before the data root is released.
                if self.core_binding is not None:
                    self.core_shutdown_report = self.core_binding.close()
                self.owner.release()
            raise
        self.started = True

    def stop(self) -> None:
        # What a running plugin owns, it stops itself. The active round's stop
        # hooks run in reverse activation order, so the plugin that sits on
        # top of the round tears its own resources down first, while
        # everything it declares — including the records its teardown writes
        # through — is still alive and undisposed. The order is the activation
        # DAG's, not a call sequence this file remembers, and the host names
        # no domain object to get it.
        if self.plugin_host is not None:
            self.plugin_host.run_stop_hooks()
        if self.started and self.legacy_core is not None:
            # S1c: composition-owned release of the legacy global binding.
            self.legacy_core.release()
        # Plugins release what they own exactly once, reverse activation
        # order. A plugin whose disposal raises must not keep the data root:
        # the lock is released no matter how the shutdown ends, and the
        # collected disposal failures surface to the caller.
        try:
            if self.plugin_host is not None:
                self.plugin_host.shutdown()
        finally:
            # A stopped plugin round has no channel owners, even when no ACP
            # WebSocket happened to be attached to receive its final event.
            if self.wire is not None and self.wire.acp_admission_gate is not None:
                self.wire.acp_admission_gate.forget_all()
            # T015: the Core round closes BEFORE the store teardown below
            # (the owner release) and AFTER the round's plugins retired —
            # their retirement is what unbinds their owners through the
            # seam — and the ShutdownReport is surfaced on the runtime,
            # never discarded.
            if self.core_binding is not None:
                self.core_shutdown_report = self.core_binding.close()
            # With every plugin disposed the host holds nothing of the round:
            # the ports a consumer resolved by name now answer None, so a
            # stopped runtime cannot keep a disposed round's objects alive.
            self.owner.release()
            self.started = False


def _server_id(database: DatabasePort) -> str:
    """Return the stable, opaque identity this Server presents to clients.

    It is generated once per data root and reused across restarts, so a client
    can tell "the same Server came back" from "a different Server is here".
    """
    with database.transaction() as conn:
        row = conn.execute("SELECT server_id FROM server_bootstrap WHERE singleton=1").fetchone()
        if row is not None:
            return str(row["server_id"])
        identity = f"server_{uuid4().hex}"
        conn.execute(
            "INSERT INTO server_bootstrap(singleton,server_id,created_at) VALUES (1,?,?)",
            (identity, datetime.now(timezone.utc).isoformat()),
        )
        return identity

def _attach_shutdown_cleanup(start_failure: BaseException,
                             cleanup_failure: BaseException) -> None:
    """Attach a failed shutdown's per-plugin cleanup errors to the START
    error (the start failure stays primary). The start error travels
    explicitly — sys.exc_info() inside the cleanup's own except would name
    the cleanup exception instead."""
    errors = getattr(cleanup_failure, "errors", ())
    try:
        existing = getattr(start_failure, "cleanup_errors", ())
        start_failure.cleanup_errors = tuple(existing) + tuple(errors)
    except (AttributeError, TypeError):
        pass


#: The entry-point group the product package registers its composition under.
#: Installing a *plugin* distribution never enables it; installing the
#: product selection package is the deployment decision itself.
SERVER_PRODUCT_ENTRY_POINT = "ordessa.server_product"


def _resolve_product_composition() -> Any:
    """The deployment's composition, resolved once per build.

    Exactly one installed product may answer. Zero is a typed refusal — a
    bare host is a deliberate choice (`server_plugins=()`), never the
    accident of a missing package; several candidates are a refusal too.
    The composition object exposes `default_plugins(**composition_kwargs)`
    returning the plugin selection for this deployment.
    """
    from importlib import metadata

    discovered = metadata.entry_points()
    group = list(
        discovered.select(group=SERVER_PRODUCT_ENTRY_POINT)
        if hasattr(discovered, "select")
        else discovered.get(SERVER_PRODUCT_ENTRY_POINT, ())
    )
    if not group:
        raise RuntimeError(
            "SERVER_PRODUCT_MISSING: no installed product provides the "
            f"{SERVER_PRODUCT_ENTRY_POINT!r} composition; pass server_plugins=() "
            "explicitly to compose a bare host")
    if len(group) > 1:
        raise RuntimeError(
            f"SERVER_PRODUCT_AMBIGUOUS: {len(group)} products provide the "
            f"{SERVER_PRODUCT_ENTRY_POINT!r} composition")
    return group[0].load()()


def build_runtime(
    data_root: Path | str, *,
    secret_store: SecretStore | None = None,
    local_workspace_provider=None,
    server_plugins: "tuple[Any, ...] | list[Any] | None" = None,
    database_factory: Callable[[Path], DatabasePort] | None = None,
) -> ServerRuntime:
    """Assemble a Server runtime: the generic host plus the selected plugins.

    The host composes the data root, the storage primitives (database,
    object store, notifier, idempotency, credentials, secret store) and the
    plugin host; what business capability is enabled is the deployment's
    decision:

    - `server_plugins=None` (the production default) resolves the selection
      through the product seam — exactly one installed product answers the
      `ordessa.server_product` entry point, or startup refuses typed;
    - an explicit sequence composes exactly those plugins (the boundary
      gates' bare host is `()`);
    - installing a plugin distribution never enables it silently.

    Since T014-S2b the host composes no machine connector: the workspace
    plugin builds the WSL/SSH connectors from its own module and provides
    them as ports, so `build_runtime` neither accepts a connector nor reads
    a connector binding.

    Since T014-S1d the host carries no business composition bag either:
    `harnesses`, `execution`, `execution_factory`, `home_concurrency`,
    `shared_store_guards`, `subscription_files_for` and
    `declared_credentials` are no longer parameters here. Those facts are
    handed to the plugin that owns them through the product's composition
    funnel (`products/server`: `default_plugins(**composition_kwargs)` →
    `ServerCompatPlugin`), which is the same route the production
    composition already used — the copy of that list that lived on
    `build_runtime` existed for tests and made the host name domains it
    does not own (FR-006). A caller that needs one of those injections
    asks the product composition for its plugin selection and passes it as
    `server_plugins`; `secret_store` and `local_workspace_provider` stay:
    the credential seam is the host's own and the local provider names a
    storage location, not a domain.
    """
    root = Path(data_root).resolve()
    _reject_unsafe_data_root_links(root)
    # The default product registers its sealed migration source while
    # selecting plugins. Resolve it before any data-root marker, lock, token,
    # or schema write so a partial historical root cannot be silently stamped
    # as current when that source is absent. Explicit bare compositions do
    # not gain the migration provider before the historical-root guard.
    from server_plugin_api import (
        ContributionDeclarationError, ContributionPointSpec,
        PACTHOLD_CONTRIBUTIONS_POINT_ID, WIRE_DISCOVERY_FACETS_POINT_ID,
        WIRE_ERROR_FAMILIES_POINT_ID, unique_contribution_point_specs,
    )

    selected_plugins: tuple[Any, ...]
    if server_plugins is None:
        composition = _resolve_product_composition()
        selected_plugins = tuple(composition.default_plugins())
        selected_product = True
    else:
        selected_plugins = tuple(server_plugins)
        selected_product = False
        # An explicit selection with an injected database is a host-only
        # composition. Otherwise an installed product may supply storage,
        # while the explicit plugin list still controls capabilities.
        composition = None
        if database_factory is None:
            try:
                composition = _resolve_product_composition()
            except RuntimeError as exc:
                if selected_plugins or not str(exc).startswith("SERVER_PRODUCT_MISSING:"):
                    raise

    # The product selection had its chance to assemble the sealed historical
    # migration source. Reject an old root before accepting any factory that
    # could stamp it, including an explicit bare-host factory.
    _require_legacy_provider_for_historical_root(root)
    if database_factory is None:
        if composition is None or not callable(getattr(composition, "database_type", None)):
            raise StorageProviderMissingError(
                "SERVER_STORAGE_PROVIDER_MISSING: selected composition has no database provider"
            )
        database_factory = composition.database_type()
    if not callable(database_factory):
        raise StorageProviderMissingError(
            "SERVER_STORAGE_PROVIDER_MISSING: database_factory must be callable"
        )

    # Check the complete product list before registering even the fixed core
    # point. This is a pure preflight: no host registry, token or data file has
    # been written yet. The owner/handler still belong to the host and product
    # respectively, never to an author contribution.
    if not selected_product:
        product_points: tuple[ContributionPointSpec, ...] = ()
    else:
        point_provider = getattr(composition, "server_contribution_points", None)
        if not callable(point_provider):
            raise ContributionDeclarationError("selected product has no server_contribution_points()")
        product_points = unique_contribution_point_specs(point_provider())
        host_owned_points = frozenset((
            PACTHOLD_CONTRIBUTIONS_POINT_ID,
            WIRE_ERROR_FAMILIES_POINT_ID,
            WIRE_DISCOVERY_FACETS_POINT_ID,
        ))
        if any(spec.point_id in host_owned_points for spec in product_points):
            raise ContributionDeclarationError("product cannot redeclare a host-owned point")
    owner = DataRootOwner(root)
    owner.acquire()
    core_binding: CoreBinding | None = None
    plugin_host = None
    try:
        token, token_path = _ensure_token(root)
        database = database_factory(root)
        objects = ObjectStore(root)
        notifier = EventNotifier()
        # T014-S2b: no connector is built here. The `server.instance_id` port
        # below is the only fact the host still hands the connector builders'
        # owner (the workspace plugin), and it names the data-root lock, not a
        # machine binding.
        secrets_store = secret_store
        if secrets_store is None and os.name == "nt":
            from pacthold.storage import WindowsDpapiSecretStore
            secrets_store = WindowsDpapiSecretStore(root)

        idempotency = IdempotentRecords(database)
        credentials = CredentialRecords(database)

        # -- the plugin-host boundary --------------------------------------------
        # One dispatch truth: the host's method registry. The host registers
        # `server.hello`; every business row arrives through a plugin.
        from server_plugin_api import ACP_ADMISSION_PORT, StreamRouteDescriptor  # noqa: F401  (admission type)
        from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
        from ordessa_server.wire.envelope import CursorCodec
        from ordessa_server.wire.handlers import WireService
        from ordessa_server.acp_admission import AcpAdmissionGate, AcpAdmissionPortAdapter

        method_registry = MethodRegistry()
        stream_route_registry = StreamRouteRegistry()
        acp_admission_gate = AcpAdmissionGate()
        acp_admission_port = AcpAdmissionPortAdapter(acp_admission_gate, stream_route_registry)
        # T015/S1c: ONE CoreBinding per composition (never a module global), owning
        # the C1 instance store at its own file inside the data root (topology
        # decision: `state/core.sqlite`, see core_binding.py's docstring), and the
        # legacy global binding as a composition-owned object. Both are handed to
        # consumers through the existing host wall: `host_ports` for declaring
        # plugins (the same wall the harness/ssh ports cross), construction-time
        # references for host-side consumers (the per-composition accessor shape).
        core_binding = CoreBinding(root / "state" / "core.sqlite")
        # The process-global legacy connection belongs to a selected product's
        # historical database. A host-only composition with its own DatabasePort
        # must be able to start without the compatibility distribution installed.
        legacy_core = LegacyCoreBinding(database.path) if composition is not None else None
        plugin_host = ServerPluginHost(
            methods=method_registry, stream_routes=stream_route_registry, data_root=root,
            host_ports={
                "database": database,
                "objects": objects,
                "notifier": notifier,
                "idempotency": idempotency,
                "credentials": credentials,
                "secret_store": secrets_store,
                # T014-S2b: the data root's process identity — the one fact the
                # workspace plugin's connector builders need and the host still
                # owns (it names the lock, not a machine binding). The
                # connectors / workspace.*_connector ports are no longer host
                # bindings: the workspace plugin provides them.
                "server.instance_id": owner.instance_id,
                "cursor.codec": CursorCodec(token.encode("utf-8")),
                "workspace.local_provider": local_workspace_provider,
                "core.binding": core_binding,
                ACP_ADMISSION_PORT: acp_admission_port,
                # T014-S2c: the same per-composition resolver the transport gets
                # below, handed to the one plugin that converts errors inside its
                # own handlers. A callable, never the aggregate object: compat
                # resolves codes, it does not read or write the table.
                "wire.error_family_resolver": (
                    lambda code: plugin_host.wire_error_families.family_for(code)),
            },
        )
        # T015 (联合注册 seam): the fixed core contribution point
        # `pacthold.contributions` v1 is declared by the composition and bound
        # to this composition's CoreBinding as its handler — plugins contribute
        # C1 payloads only, never the registry; the host round stages through
        # the binding's T012/T013-shaped stage/commit/rollback (a raising stage
        # aborts with zero leaked contributions).
        from server_plugin_api import (
            PACTHOLD_CONTRIBUTIONS_API_VERSION,
            PACTHOLD_CONTRIBUTIONS_POINT_ID,
        )
        plugin_host.register_contribution_point(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            handler=core_binding)
        for spec in product_points:
            plugin_host.register_contribution_point(
                spec.point_id, spec.api_version,
                handler=spec.handler, exclusive=spec.exclusive)
        wire = WireService(
            server_id_provider=lambda: _server_id(database),
            cursor_secret=token.encode("utf-8"),
            method_registry=method_registry, stream_routes=stream_route_registry,
            acp_admission_gate=acp_admission_gate,
            # T014-S3: `server.hello`'s domain members are facet PROJECTORS the
            # composed domains publish, resolved against THIS host's own aggregate
            # (the `wire.discovery-facets` point's per-host handler writes it, and
            # a projector is called per hello because the fact is live). The host
            # no longer names a business port here: before this line the
            # composition root handed the transport the harness directory and the
            # transport read it — deployment knowledge wearing a host parameter.
            discovery_facets_resolver=lambda: plugin_host.wire_discovery_facets.facets(),
            # T014-S2a-R: the error-family table a request resolves against is
            # THIS composition's aggregate (a per-host object owned by the
            # declaring plugin host), handed to the transport once at
            # construction — the per-composition accessor shape. S1c/S1d/S2b build
            # on this line; no other consumer reads the aggregate.
            error_family_resolver=lambda code: plugin_host.wire_error_families.family_for(code),
        )
        # Explicit selection only: None means the product composition answers; an
        # empty sequence is the bare host the boundary gates require. Activation
        # failure here fails startup — never a half-composed wire surface.
        # S1d: the product answers its OWN composition kwargs (the compat funnel
        # in `products/server`); the host forwards no business fact through.
        plugin_host.activate_all(selected_plugins)
        # Resolved through the host on every read: unloading the Workspace plugin
        # unbinds its port for the compatibility domains too — never a stale
        # snapshot.
        wire.bind_workspace_resolution(
            lambda: plugin_host.provided_port("workspace.service"))
        runtime = ServerRuntime(
            data_root=root, database=database, objects=objects, owner=owner,
            token=token, token_path=token_path, notifier=notifier,
            secret_store=secrets_store, wire=wire,
            plugin_host=plugin_host, plugin_selection=selected_plugins,
            core_binding=core_binding, legacy_core=legacy_core,
        )
        return runtime
    except BaseException as failure:
        cleanup_errors: list[BaseException] = []
        if plugin_host is not None and plugin_host.active_ids():
            try:
                plugin_host.shutdown()
            except BaseException as cleanup_failure:
                cleanup_errors.append(cleanup_failure)
        if core_binding is not None:
            try:
                core_binding.close()
            except BaseException as cleanup_failure:
                cleanup_errors.append(cleanup_failure)
        try:
            owner.release()
        except BaseException as cleanup_failure:
            cleanup_errors.append(cleanup_failure)
        if cleanup_errors:
            try:
                existing = getattr(failure, "cleanup_errors", ())
                failure.cleanup_errors = tuple(existing) + tuple(cleanup_errors)
            except (AttributeError, TypeError):
                pass
        raise
