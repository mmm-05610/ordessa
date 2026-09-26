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
import csv
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Any, Mapping
from uuid import uuid4

from ordessa_server.credentials import CredentialRecords
from ordessa_server.events import EventNotifier
from ordessa_server.idempotency import IdempotentRecords
from pacthold.storage import Database, ObjectStore, SecretStore


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


def _builtin_connector(server_instance_id: str) -> Any | None:
    manifest = os.environ.get("AGENT_BOX_WSL_WORKER_MANIFEST")
    worker = os.environ.get("AGENT_BOX_WSL_WORKER_LINUX_PATH")
    if os.name != "nt" or not manifest or not worker:
        return None
    # A host connector is resolved by name here, exactly as the sandbox
    # provider is: the installed plugin entry point first, the importable
    # package as the PYTHONPATH-runtime fallback. Bindings left unset compose
    # no connector, which `resolve_placement` then refuses out loud.
    bindings = {
        "manifest_path": manifest, "linux_worker_path": worker,
        "server_instance_id": server_instance_id,
    }
    factory = _entry_point_factory("runtime-wsl")
    if factory is not None:
        try:
            return factory(**bindings)
        except TypeError:
            pass
    try:
        from agent_box_runtime_wsl import WslConnector
    except ImportError:
        return None
    return WslConnector(**bindings)


def _entry_point_factory(name: str):
    """The callable a plugin entry point registers under ``name``, if any."""
    from importlib import metadata

    from pacthold.extensions.loader import ENTRY_POINT_GROUP

    discovered = metadata.entry_points()
    group = (
        discovered.select(group=ENTRY_POINT_GROUP)
        if hasattr(discovered, "select") else discovered.get(ENTRY_POINT_GROUP, ())
    )
    wanted = name.strip().lower().replace("-", "_")
    for entry_point in group:
        if entry_point.name.lower().replace("-", "_") == wanted:
            return entry_point.load()
    return None


def _builtin_ssh_connector(server_instance_id: str):
    """Compose the SSH connector from process bindings, the way WSL's is.

    Like the WSL connector's bindings, these name machine-local facts the
    deployment document must not carry: which manifest pins the Worker, where
    the Worker already lives on the remote host, and the locator of the identity
    that may reach it. A binding left unset simply means that placement is not
    composed here - which `resolve_placement` then says out loud.
    """
    manifest = os.environ.get("AGENT_BOX_SSH_WORKER_MANIFEST")
    worker = os.environ.get("AGENT_BOX_SSH_WORKER_REMOTE_PATH")
    identity = os.environ.get("AGENT_BOX_SSH_IDENTITY_FILE")
    if not manifest or not worker or not identity:
        return None
    from ordessa_server.connectors import SshConnector

    port = os.environ.get("AGENT_BOX_SSH_PORT")
    return SshConnector(
        manifest_path=manifest, remote_worker_path=worker,
        identity_file=identity, server_instance_id=server_instance_id,
        port=int(port) if port else 22,
    )


@dataclass
class ServerRuntime:
    data_root: Path
    database: Database
    objects: ObjectStore
    repository: Any | None
    service: Any | None
    owner: DataRootOwner
    token: str = field(repr=False)
    token_path: Path
    notifier: EventNotifier
    secret_store: SecretStore | None = None
    harnesses: Any | None = None
    execution: Any | None = None
    wire: Any | None = None
    approvals: Any | None = None
    queue: Any | None = None
    model_configs: Any | None = None
    #: Credential declarations from the deployment document, imported on start
    #: (the store and the records table both exist only once the schema is up).
    declared_credentials: tuple[dict[str, str], ...] = ()
    native_harness_id: str | None = None
    native_profile_id: str | None = None
    #: Managed ACP channel registry (owned transports and their run records);
    #: composed only where a transport provider is injected.
    acp_channels: Any | None = None
    #: The plugin host (batch 1): the one wire/1 dispatch registry and the
    #: activation/lifecycle of the Server's plugins.
    plugin_host: Any | None = None
    #: The explicit selection this runtime was composed with, kept so a
    #: start() after a stop() re-activates the same plugins (a wire surface
    #: that loses its domains on restart is a broken restart).
    plugin_selection: Any | None = None
    started: bool = False

    def start(self) -> None:
        if self.started:
            return
        if not self.owner.acquired:
            self.owner.acquire()
        try:
            # Re-activation after a stop is inside the cleanup: a flaky plugin
            # failing its second build must not keep the data-root lock.
            if (self.plugin_host is not None and self.plugin_selection
                    and not self.plugin_host.active_ids()):
                self.plugin_host.activate_all(self.plugin_selection)
                # The facades follow the live activation round: a restart
                # must expose THIS round's ports, not the disposed round's.
                _bind_runtime_facades(self)
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
            from pacthold.work_core import db as core_db
            core_db.configure_database(self.database.path)
            core_db.get_conn()
        except BaseException:
            from pacthold.work_core import db as core_db
            core_db.configure_database(None)
            # A failed start must not leave the round active with the lock
            # gone: the next process could own the same data root while this
            # round's plugin resources are still alive. Dispose the round
            # (reverse order, every plugin exactly once), keep the start
            # error primary with any disposal failures attached, then release.
            if self.plugin_host is not None and self.plugin_host.active_ids():
                try:
                    self.plugin_host.shutdown()
                except BaseException as cleanup_failure:
                    _attach_shutdown_cleanup(cleanup_failure)
                _bind_runtime_facades(self)
            self.owner.release()
            raise
        self.started = True

    def stop(self) -> None:
        # Owned ACP channel transports stop first: their run records are
        # closed with the honest server-stop reason while the ledger is up.
        channels = getattr(self, "acp_channels", None)
        if channels is not None:
            channels.stop_all()
        if self.execution is not None and hasattr(self.execution, "stop"):
            if not self.execution.stop():
                raise RuntimeError("SERVER_STOP_TIMEOUT")
        if self.started:
            from pacthold.work_core import db as core_db
            core_db.configure_database(None)
        # Plugins release what they own exactly once, reverse activation
        # order. A plugin whose disposal raises must not keep the data root:
        # the lock is released no matter how the shutdown ends, and the
        # collected disposal failures surface to the caller.
        try:
            if self.plugin_host is not None:
                self.plugin_host.shutdown()
        finally:
            # The facades follow the live activation round: with every plugin
            # disposed they resolve to None — a stopped runtime must not keep
            # references to a disposed round's objects.
            _bind_runtime_facades(self)
            self.owner.release()
            self.started = False


def _server_id(database: Database) -> str:
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

def _bind_runtime_facades(runtime: "ServerRuntime") -> None:
    """(Re-)bind the runtime's port facades to the live activation round.

    Called at composition, after every re-activation, and after every
    shutdown: a facade must never outlive the round it was bound to — the
    reviewer's stop→start counterexample had `runtime.acp_channels` pointing
    at the disposed first round's registry, and `stop()` then operating on a
    dead object."""
    for facade_field, port_name in _RUNTIME_PORT_FACADES.items():
        setattr(runtime, facade_field,
                runtime.plugin_host.provided_port(port_name)
                if runtime.plugin_host is not None else None)
    if runtime.execution is None and getattr(runtime, "_injected_execution", None) is not None:
        runtime.execution = runtime._injected_execution


def _attach_shutdown_cleanup(cleanup_failure: BaseException) -> None:
    """Attach a failed shutdown's per-plugin cleanup errors to the start
    error in flight (the start failure stays primary)."""
    import sys

    primary = sys.exc_info()[1]
    if primary is None:
        return
    errors = getattr(cleanup_failure, "errors", ())
    try:
        existing = getattr(primary, "cleanup_errors", ())
        primary.cleanup_errors = tuple(existing) + tuple(errors)
    except (AttributeError, TypeError):
        pass


#: The runtime fields that are facades over what the active plugins provide.
#: One row per port; a plugin-absent field stays None — the honest absence
#: the wire already answers with.
_RUNTIME_PORT_FACADES: Mapping[str, str] = {
    "service": "product.service",
    "repository": "product.repository",
    "harnesses": "harness.directory",
    "execution": "execution.port",
    "approvals": "approvals.records",
    "queue": "queue.records",
    "model_configs": "provider.models",
    "account_records": "account.records",
    "account_assets": "account.assets",
    "asset_records": "asset.records",
    "skill_assets": "asset.skills",
    "mcp_assets": "asset.mcp",
    "asset_catalogs": "asset.catalogs",
    "plugin_assets": "asset.plugins",
    "hook_records": "hook.records",
    "hook_triggers": "hook.triggers",
    "delegation_service": "delegation.service",
    "delegation_tokens": "delegation.tokens",
    "acp_channels": "acp.channels",
    "events_stream_source": "events.stream_source",
    #: The compatibility core's composed handlers — the injection point the
    #: order-098/101/147 counter-examples use to swap one service face.
    "compat_handlers": "compat.handlers",
}

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
    harnesses: Any | None = None,
    connector: Any | None = None,
    ssh_connector=None,
    secret_store: SecretStore | None = None,
    execution: Any | None = None,
    execution_factory=None,
    home_concurrency: Mapping[str, str] | None = None,
    shared_store_guards: Mapping[str, Any] | None = None,
    subscription_files_for=None,
    local_workspace_provider=None,
    declared_credentials: "tuple[dict[str, str], ...]" = (),
    server_plugins: "tuple[Any, ...] | list[Any] | None" = None,
) -> ServerRuntime:
    """Assemble a Server runtime: the generic host plus the selected plugins.

    The host composes the data root, the storage primitives (database,
    object store, notifier, idempotency, credentials, secret store, machine
    connectors) and the plugin host; what business capability is enabled is
    the deployment's decision:

    - `server_plugins=None` (the production default) resolves the selection
      through the product seam — exactly one installed product answers the
      `ordessa.server_product` entry point, or startup refuses typed;
    - an explicit sequence composes exactly those plugins (the boundary
      gates' bare host is `()`);
    - installing a plugin distribution never enables it silently.

    `harnesses` carries only descriptors for implementations registered for
    this deployment. `execution` is an explicit port injection (tests, or a
    composition that has already built one); the production default stays
    None so capability answers stay honest.
    """
    root = Path(data_root).resolve()
    owner = DataRootOwner(root)
    owner.acquire()
    try:
        token, token_path = _ensure_token(root)
    except BaseException:
        owner.release()
        raise
    database = Database(root)
    objects = ObjectStore(root)
    notifier = EventNotifier()
    connector_instance = connector if connector is not None else _builtin_connector(owner.instance_id)
    ssh_instance = ssh_connector if ssh_connector is not None else _builtin_ssh_connector(owner.instance_id)
    # The composition's connectors, keyed by the placement that consumes them.
    # Everything downstream reads this mapping, so "which environments can this
    # Server actually reach" is one fact stated once.
    connectors = {"wsl": connector_instance, "ssh": ssh_instance}
    secrets_store = secret_store
    if secrets_store is None and os.name == "nt":
        from pacthold.storage import WindowsDpapiSecretStore
        secrets_store = WindowsDpapiSecretStore(root)

    idempotency = IdempotentRecords(database)
    credentials = CredentialRecords(database)

    # -- the plugin-host boundary --------------------------------------------
    # One dispatch truth: the host's method registry. The host registers
    # `server.hello`; every business row arrives through a plugin.
    from server_plugin_api import StreamRouteDescriptor  # noqa: F401  (admission type)
    from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
    from ordessa_server.wire.envelope import CursorCodec
    from ordessa_server.wire.handlers import WireService

    method_registry = MethodRegistry()
    stream_route_registry = StreamRouteRegistry()
    plugin_host = ServerPluginHost(
        methods=method_registry, stream_routes=stream_route_registry, data_root=root,
        host_ports={
            "database": database,
            "objects": objects,
            "notifier": notifier,
            "idempotency": idempotency,
            "credentials": credentials,
            "secret_store": secrets_store,
            "connectors": connectors,
            "cursor.codec": CursorCodec(token.encode("utf-8")),
            "workspace.wsl_connector": connector_instance,
            "workspace.ssh_connector": ssh_instance,
            "workspace.local_provider": local_workspace_provider,
        },
    )
    wire = WireService(
        server_id_provider=lambda: _server_id(database),
        cursor_secret=token.encode("utf-8"),
        method_registry=method_registry, stream_routes=stream_route_registry,
        harness_resolver=lambda: plugin_host.provided_port("harness.directory"),
    )
    # Explicit selection only: None means the product composition answers; an
    # empty sequence is the bare host the boundary gates require. Activation
    # failure here fails startup — never a half-composed wire surface.
    if server_plugins is None:
        composition = _resolve_product_composition()
        selected_plugins: "tuple[Any, ...]" = tuple(composition.default_plugins(
            harnesses=harnesses, execution=execution,
            execution_factory=execution_factory,
            home_concurrency=home_concurrency,
            shared_store_guards=shared_store_guards,
            subscription_files_for=subscription_files_for,
            declared_credentials=declared_credentials,
        ))
    else:
        selected_plugins = tuple(server_plugins)
    try:
        plugin_host.activate_all(selected_plugins)
    except BaseException:
        # An activation failure must not keep the data-root lock: composing
        # the same root again in this process is the retry path.
        owner.release()
        raise
    # Resolved through the host on every read: unloading the Workspace plugin
    # unbinds its port for the compatibility domains too — never a stale
    # snapshot.
    wire.bind_workspace_resolution(
        lambda: plugin_host.provided_port("workspace.service"))
    runtime = ServerRuntime(
        data_root=root, database=database, objects=objects,
        repository=None, service=None, owner=owner, token=token,
        token_path=token_path, notifier=notifier, secret_store=secrets_store,
        harnesses=None, execution=None, wire=wire,
        declared_credentials=tuple(declared_credentials),
        plugin_host=plugin_host, plugin_selection=selected_plugins,
    )
    # An explicitly injected execution port (tests, or a composition that has
    # already built one) is composition-owned, not round-owned: it survives
    # facades re-binding and re-applies whenever no plugin provides one.
    runtime._injected_execution = execution
    # Runtime fields are facades over what the active plugins provide: the
    # product surface (runtime.service, runtime.repository, ...) keeps its
    # shape, and a plugin's absence reads as None instead of a second
    # composition hiding inside the host.
    _bind_runtime_facades(runtime)
    return runtime
