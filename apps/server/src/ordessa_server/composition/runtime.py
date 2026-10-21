"""Bootstrap assembly: the generic host composition root.

The host composes only what it owns — the data root, the storage primitives,
the transport walls, the plugin host — and resolves the deployment's business
composition through the product seam: exactly one installed product package
answers the `ordessa.server_product` entry point with its plugin selection.
Business domains live in `plugins/*`; `apps/server/deployment/default-product` decides which are
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
import stat
import subprocess
from collections.abc import Mapping
from typing import Any, Callable
from uuid import uuid4
from threading import RLock

from ordessa_server_plugin_api import OwnedRootBinding, RootOwnershipError
from ordessa_server.composition.root_ownership import (
    _issue_owned_root_binding, validate_owned_root_binding, DataRootOwner, DataRootPathUnsafeError, RuntimeCompositionUnavailable,
)
from ordessa_server.configuration.credentials import CredentialRecords
from ordessa_server.composition.unit_runtime import UnitRuntimeOwner
from ordessa_server.bootstrap.migrations.historical_preflight import (
    LegacyMigrationProviderMissingError, _reject_unsafe_data_root_links,
    _require_legacy_provider_for_historical_root,
)
from ordessa_server.composition.harness_registration import HarnessDefinitionHandler
from ordessa_server.bootstrap.events import EventNotifier
from ordessa_server.bootstrap.system_access.idempotent_records import IdempotentRecords
from ordessa_interfaces.system_access.contracts.storage import DatabasePort
from ordessa_infrastructure.filesystem.blobs import ObjectStore
from ordessa_infrastructure.security.secrets import SecretStore

from ordessa_server.bootstrap.data_root import (
    OWNER_MARKER_CONTENT,
    OWNER_MARKER_NAME,
    write_owner_marker,
)






def _unavailable_legacy_core_store() -> Any:
    """Fail closed instead of letting an old WorkCore chain use its global DB."""
    raise RuntimeCompositionUnavailable(
        "legacy WorkCore dispatch has no Environment-backed store adapter"
    )




class StorageProviderMissingError(RuntimeError):
    """A selected composition has no database schema provider installed."""

    code = "SERVER_STORAGE_PROVIDER_MISSING"






class LegacyCoreBinding:
    """Composition-owned instance connection to the LEGACY product database.

    Topology history: the S1c file-topology decision (T015) gave the new C1
    core instance its **own file inside the data root**
    (`<data root>/state/core.sqlite`, owned by :class:`UnitRuntimeOwner`), not the
    legacy product database file — because ``CoreStore`` is self-owned
    (``sqlite3.connect(path, timeout=10.0, check_same_thread=False)``, no
    connection-injection seam) and the host's in-process write lock does
    not serialise a second OS-level connection over the same file. The
    counterexample witness is
    `apps/server/tests/platform/test_platform_core_instance_124.py::
    test_shared_file_topology_counterexample_double_applies_a_write`.

    026 T006-01 (second half): this binding no longer goes through the
    process-global ``pacthold.work_core.db`` singleton AT ALL. The historical
    shape — ``configure_database(path)`` + ``get_conn()`` on start and
    ``configure_database(None)`` on stop, the last host site that configured
    the module global — is gone. The binding is an instance connection
    holder instead: built once per composition by ``build_runtime`` holding
    exactly the server-owned database file, ``connect()`` opens THIS round's
    own ``sqlite3`` connection to it (the same connection shape the global
    used, minus the module state), ``release()`` closes it. No module-level
    state is written: after a full round the global ``_database_override``
    and ``_conn`` are still ``None`` — never configured, never opened. (The
    ``work_core.db`` module itself is retired by order 012; this slice only
    severs the host from it.)

    What the connection is FOR: the registered (sealed legacy + kernel)
    migration chain is applied HERE, onto this instance connection, by the
    kernel runner's own applier — the application ``get_conn()`` used to
    perform when it opened the global, moved onto the instance connection
    byte-for-byte (idempotent: already-applied versions are skipped, so a
    historical root's ledger is neither renumbered nor rewritten). The host
    never re-binds the module: the registry read behind the applier is pure,
    and the runner writes only through the connection passed in. The legacy
    SQL chain itself is assembled by the PRODUCT before the first connection
    below (T022b: ``apps/server/deployment/default-product`` →
    ``pacthold_runtime_compat.legacy_migrations.register_legacy_migrations()``
    — sealed registration, idempotent, plan §43 「B 默认产品显式装配旧迁移集」).
    The old library's remaining build-time READ need (the historical-root
    preflight) goes through the migration REGISTRY
    (``registered_migration_sources()``, a pure registration read, no
    connection), which is why a full round leaves the global untouched.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open THIS round's own connection to the legacy database file.

        Applies the registered migration chain to that instance connection
        (the application ``get_conn()`` used to perform on the global —
        idempotent, so an applied ledger is only re-scanned, never
        renumbered). Idempotent within a round (a re-entrant connect keeps
        the open connection); ``release()`` between rounds closes it, so a
        restart re-opens fresh. Never touches ``pacthold.work_core.db``
        module state — no ``configure_database``, no ``get_conn``, no
        global; the runner writes only through the connection passed in.
        """
        if self._conn is not None:
            return
        from ordessa_infrastructure.database import migrations as migration_runner
        from ordessa_server.bootstrap.migrations import source_selection
        conn = sqlite3.connect(
            str(self.database_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # The same chain application get_conn() performed when it opened the
        # global, on THIS connection (the precedent is the sidecar backend's
        # _InstanceStore, which applies the kernel's namespace to its own
        # instance store the same way; the product file takes ALL registered
        # sources, because this file IS the legacy product database).
        migration_runner.apply_registered_migrations(conn, registry=source_selection.registry)
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        """The round's own legacy-database connection (never the global).

        Typed refusal before ``connect()`` or after ``release()``: a closed
        round must not hand out a connection that would silently re-open
        the file behind the released data-root lock.
        """
        if self._conn is None:
            raise RuntimeError(
                "LEGACY_CORE_NOT_CONNECTED: the legacy binding has no open "
                "connection; connect() opens it for the running round")
        return self._conn

    def release(self) -> None:
        """Close this round's own connection (idempotent)."""
        if self._conn is None:
            return
        try:
            self._conn.close()
        finally:
            self._conn = None




class _FailedBuildCleanup:
    """Hold the original round's OS lock, UnitRuntimeOwner and product Store."""

    def __init__(self, owner: DataRootOwner, plugin_host: Any,
                 unit_runtime: UnitRuntimeOwner | None, store: Any = None,
                 environment: Any = None) -> None:
        self.owner = owner
        self.plugin_host = plugin_host
        self.unit_runtime = unit_runtime
        self.environment = environment
        self.store = store
        self._plugin_failure: BaseException | None = None
        self._retry_lock = RLock()
        self._retry_active = False

    def retry(self) -> None:
        # Concurrent callers share this exact original cleanup obligation.
        # A callback may not recursively dispose it from the same thread.
        with self._retry_lock:
            if self._retry_active:
                raise RuntimeCompositionUnavailable("construction cleanup retry is already in progress")
            self._retry_active = True
            try:
                self._retry_original()
            finally:
                self._retry_active = False

    def _retry_original(self) -> None:
        # PluginHost disposes rows even when disposal raises. A failed
        # disposal cannot be replayed safely; keep the owner and surface it.
        if self._plugin_failure is not None:
            raise RuntimeCompositionUnavailable(
                "plugin disposal failed; explicit reconciliation required"
            ) from self._plugin_failure
        if self.plugin_host is not None and self.plugin_host.active_ids():
            try:
                self.plugin_host.shutdown()
            except BaseException as exc:
                self._plugin_failure = exc
                raise
        if self.unit_runtime is not None:
            self.unit_runtime.close()
            self.unit_runtime = None
        if self.environment is not None:
            self.environment.close()
            self.environment = None
        if self.store is not None:
            self.store.close()
            self.store = None
        self.owner.release()
        with DataRootOwner._pending_builds_lock:
            if DataRootOwner._pending_builds.get(self.owner.root) is self:
                del DataRootOwner._pending_builds[self.owner.root]

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
# bindings and the connector entry-point lookup live in `plugins/agents/workspace`
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
    #: T015: this composition's single Pacthold seam — one UnitRuntimeOwner per
    #: runtime, constructed by build_runtime, never a module global.
    unit_runtime: UnitRuntimeOwner | None = None
    #: S1c: the composition-owned legacy binding — 026 T006-01 (second half):
    #: an INSTANCE connection holder for the server-owned legacy database
    #: file, never the process-global work_core singleton.
    legacy_core: LegacyCoreBinding | None = None
    #: The ShutdownReport the composition's stop() surfaced (T015: the
    #: report is a fact of the round, never a discarded return value).
    core_shutdown_report: Any | None = None
    #: Optional core-owned descriptors share the host registry; no plugin or
    #: domain state is stored here. Each round receives a fenced resolver.
    core_method_factory: Callable[[Callable[[], Any]], tuple[Any, ...]] | None = None
    _core_method_ids: tuple[str, ...] = field(default=(), init=False, repr=False)
    _core_method_epoch: int = field(default=0, init=False, repr=False)
    _core_method_lock: Any = field(default_factory=RLock, init=False, repr=False)
    _lifecycle_lock: Any = field(default_factory=RLock, init=False, repr=False)
    _stop_status: str = field(default="idle", init=False, repr=False)
    _stop_blocked: bool = field(default=False, init=False, repr=False)
    _stop_was_started: bool = field(default=False, init=False, repr=False)
    _stop_unit_close_attempted: bool = field(default=False, init=False, repr=False)
    _stop_unit_close_result: Any = field(default=None, init=False, repr=False)
    _stop_epoch_invalidated: bool = field(default=False, init=False, repr=False)
    _stop_core_unbound: bool = field(default=False, init=False, repr=False)
    _stop_hooks_done: bool = field(default=False, init=False, repr=False)
    _stop_legacy_released: bool = field(default=False, init=False, repr=False)
    _stop_plugins_done: bool = field(default=False, init=False, repr=False)
    _stop_admission_forgotten: bool = field(default=False, init=False, repr=False)
    _stop_unit_runtime_closed: bool = field(default=False, init=False, repr=False)
    _stop_root_released: bool = field(default=False, init=False, repr=False)
    _selected_unit_owner_was_closed: bool = field(default=False, init=False, repr=False)
    started: bool = False

    @property
    def stop_state(self) -> str:
        """The current shutdown outcome: idle, pending, or completed."""
        return self._stop_status

    def _bind_core_methods(self) -> None:
        with self._core_method_lock:
            self._bind_core_methods_locked()

    def _bind_core_methods_locked(self) -> None:
        if self.core_method_factory is None:
            return
        from ordessa_server_plugin_api import InvalidDeclarationError, ServerMethodDescriptor
        if not callable(self.core_method_factory):
            raise InvalidDeclarationError("core_method_factory must be callable")
        if self.unit_runtime is None or self.plugin_host is None:
            raise RuntimeCompositionUnavailable("core methods require the current UnitRuntimeOwner and method registry")
        self._core_method_epoch += 1
        epoch = self._core_method_epoch
        environment = self.unit_runtime.context

        def current_environment():
            with self._core_method_lock:
                if epoch != self._core_method_epoch:
                    raise RuntimeCompositionUnavailable("core method resolver belongs to a retired runtime round")
                if self.unit_runtime is None:
                    raise RuntimeCompositionUnavailable("current UnitRuntimeOwner is unavailable")
                # The resolver never lazily opens a new round, even if stop
                # crosses the admission after this check. The captured old
                # Environment enforces its own close/admission ordering.
                return environment

        # A descriptor batch cannot advertise a fabricated substitute when
        # its selected Environment factory is absent or cannot open.
        current_environment()
        descriptors = self.core_method_factory(current_environment)
        if not isinstance(descriptors, tuple):
            raise InvalidDeclarationError("core method factory must return a tuple of descriptors")
        for descriptor in descriptors:
            if not isinstance(descriptor, ServerMethodDescriptor):
                raise InvalidDeclarationError("core method factory returned a non-descriptor")
            if descriptor.owner != "pacthold.agents" or not descriptor.method_id.startswith("agents."):
                raise InvalidDeclarationError("core methods require owner pacthold.agents and agents.* ids")
        if epoch != self._core_method_epoch:
            raise RuntimeCompositionUnavailable("core method factory retired its runtime round")
        self.plugin_host.methods.register_batch(descriptors)
        self._core_method_ids = tuple(item.method_id for item in descriptors)

    def _unbind_core_methods(self) -> None:
        with self._core_method_lock:
            self._unbind_core_methods_locked()

    def _unbind_core_methods_locked(self) -> None:
        # Invalidate even a resolver retained by a factory that failed before
        # publication. It must never lazily reopen a stopped Environment.
        self._core_method_epoch += 1
        if self.plugin_host is not None:
            for method_id in self._core_method_ids:
                self.plugin_host.methods.unregister(method_id, owner="pacthold.agents")
        self._core_method_ids = ()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.started:
                return
            if self._stop_status == "pending":
                raise RuntimeCompositionUnavailable(
                    "Server shutdown is pending; a new runtime round cannot start"
                )
            if self._stop_status == "completed" and self._selected_unit_owner_was_closed:
                raise RuntimeCompositionUnavailable(
                    "Selected Unit owner was closed; rebuild through product composition before restart"
                )
            self._start_round()

    def _start_round(self) -> None:
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
            if self.unit_runtime is not None and self.unit_runtime.ever_opened:
                context = self.unit_runtime.open()
                self.plugin_host.host_ports = dict(self.plugin_host.host_ports,
                    **{'execution.harness.catalog': context.harness_catalog})
            # Re-activation after a stop is inside the cleanup: a flaky plugin
            # failing its second build must not keep the data-root lock.
            # S-03/S-06: schema-first — plugins that ensure schemas (the
            # permissions backend, the model provider) activate only after the
            # database file and its migrations exist; the constructor stores
            # paths and opens nothing. Future-schema refusal stays at start().
            self.database.initialize()
            self._bind_core_methods()
            if (self.plugin_host is not None and self.plugin_selection
                    and not self.plugin_host.active_ids()):
                self.plugin_host.activate_all(self.plugin_selection)
                # Nothing to re-bind: a port read after this point resolves
                # against THIS round, because it goes through the plugin host.
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
            if self.wire is not None:
                reopen = getattr(self.wire, "reopen_admission", None)
                if not callable(reopen) or reopen() is not True:
                    raise RuntimeCompositionUnavailable(
                        "wire dispatch admission could not reopen for the new round"
                    )
        except BaseException as start_failure:
            try:
                self.stop()
            except BaseException as cleanup_failure:
                # Keep the startup failure primary. Shutdown owns all cleanup
                # sequencing and carries any refusal/teardown failure here.
                _attach_shutdown_cleanup(start_failure, cleanup_failure)
            raise
        self.started = True
        if self._stop_status == "completed":
            self._reset_stop_state()

    def _reset_stop_state(self) -> None:
        self._stop_status = "idle"
        self._stop_blocked = False
        self._stop_was_started = False
        self._stop_unit_close_attempted = False
        self._stop_unit_close_result = None
        self._stop_epoch_invalidated = False
        self._stop_core_unbound = False
        self._stop_hooks_done = False
        self._stop_legacy_released = False
        self._stop_plugins_done = False
        self._stop_admission_forgotten = False
        self._stop_unit_runtime_closed = False
        self._stop_root_released = False

    def stop(self) -> None:
        with self._lifecycle_lock:
            if self._stop_status == "completed":
                return
            if self._stop_blocked:
                raise RuntimeCompositionUnavailable(
                    "Server shutdown is pending after an unresolved owner result"
                )
            if self._stop_status == "idle":
                self._stop_was_started = self.started
            self._stop_status = "pending"
            # Close new external admission before checking the dispatcher's
            # public idle result. False is pending, not permission to invalidate
            # identity or close any owner.
            self.started = False
            if self.wire is not None:
                begin_shutdown = getattr(self.wire, "begin_shutdown", None)
                if not callable(begin_shutdown):
                    self._stop_blocked = True
                    raise RuntimeCompositionUnavailable(
                        "wire dispatch shutdown barrier is unavailable"
                    )
                try:
                    wire_idle = begin_shutdown() is True
                except BaseException as exc:
                    self._stop_blocked = True
                    raise RuntimeCompositionUnavailable(
                        "wire dispatch shutdown barrier failed"
                    ) from exc
                if not wire_idle:
                    raise RuntimeCompositionUnavailable(
                        "Server shutdown is pending while admitted wire calls remain"
                    )

            if not self._stop_unit_close_attempted:
                units = getattr(self, "units", None)
                unit_owner = getattr(self, "unit_execution_owner", None)
                if units is None and unit_owner is None:
                    self._stop_unit_close_attempted = True
                    self._stop_unit_close_result = {"state": "confirmed", "unresolved": False}
                elif units is None or unit_owner is None:
                    self._stop_blocked = True
                    raise RuntimeCompositionUnavailable(
                        "selected Unit manager and original owner are not both present"
                    )
                else:
                    permission = getattr(unit_owner, "permission", None)
                    authority = (getattr(self.wire, "identity_authority", None)
                                 if self.wire is not None else None)
                    authorization_factory = getattr(unit_owner, "authorization", None)
                    close = getattr(units, "close", None)
                    if (units is not getattr(unit_owner, "manager", None)
                            or getattr(permission, "access_authority", None) is not authority
                            or not callable(authorization_factory) or not callable(close)):
                        self._stop_blocked = True
                        raise RuntimeCompositionUnavailable(
                            "selected Unit shutdown is not bound to the original runtime owner"
                        )
                    # Record the single attempt before calling into Execution.
                    # An exception or unresolved result is retained; UNKNOWN is
                    # never converted into an automatic native retry.
                    self._stop_unit_close_attempted = True
                    try:
                        result = close(authorization_factory())
                    except BaseException as exc:
                        self._stop_unit_close_result = exc
                        self._stop_blocked = True
                        raise RuntimeCompositionUnavailable(
                            "original selected Unit close did not confirm"
                        ) from exc
                    self._stop_unit_close_result = result
                    if _is_confirmed_unit_close(result):
                        self._selected_unit_owner_was_closed = True
                    elif _is_retryable_unit_close_pending(result):
                        # Execution 94's all-pending report proves that it made
                        # no stop/release claim. Permit a later idle retry with
                        # the same owner, principal, records, and authorization.
                        self._stop_unit_close_attempted = False
                        raise RuntimeCompositionUnavailable(
                            "selected Unit close is pending; retry after original Units become idle"
                        )
                    else:
                        self._stop_blocked = True
                        raise RuntimeCompositionUnavailable(
                            "original selected Unit close is unknown, partial, or malformed"
                        )
            if not _is_confirmed_unit_close(self._stop_unit_close_result):
                self._stop_blocked = True
                raise RuntimeCompositionUnavailable(
                    "original selected Unit close has no confirmed result"
                )

            # Destructive teardown starts only after wire dispatch and the
            # original selected Unit owner have settled. Per-phase state keeps
            # a later cleanup error from replaying native close or completed
            # owner phases.
            if not self._stop_epoch_invalidated:
                if self.wire is not None and self.wire.identity_authority is not None:
                    self.wire.identity_authority.invalidate()
                self._stop_epoch_invalidated = True
            if not self._stop_core_unbound:
                self._unbind_core_methods()
                self._stop_core_unbound = True
            if (self._stop_was_started and self.plugin_host is not None
                    and not self._stop_hooks_done):
                try:
                    self.plugin_host.run_stop_hooks()
                except BaseException:
                    # The selected Unit close is already confirmed and stored.
                    # A general plugin hook may be repaired and retried; this
                    # does not replay native close or imply rollback of hook
                    # side effects.
                    raise
                self._stop_hooks_done = True
            else:
                self._stop_hooks_done = True
            if self.legacy_core is not None and not self._stop_legacy_released:
                self.legacy_core.release()
                self._stop_legacy_released = True

            # Preserve carry-not-swallow disposal behavior. The host visits all
            # active plugins even if one disposal reports a failure; original
            # context/root cleanup still runs in the finally path.
            plugin_failure = None
            if not self._stop_plugins_done:
                try:
                    if self.plugin_host is not None:
                        self.plugin_host.shutdown()
                except BaseException as exc:
                    plugin_failure = exc
                finally:
                    self._stop_plugins_done = True
            try:
                if not self._stop_admission_forgotten:
                    if self.wire is not None and self.wire.acp_admission_gate is not None:
                        self.wire.acp_admission_gate.forget_all()
                    self._stop_admission_forgotten = True
                if self.unit_runtime is not None and not self._stop_unit_runtime_closed:
                    self.core_shutdown_report = self.unit_runtime.close()
                    self._stop_unit_runtime_closed = True
                if not self._stop_root_released:
                    self.owner.release()
                    self._stop_root_released = True
            except BaseException:
                self._stop_blocked = True
                raise
            self._stop_status = "completed"
            self.started = False
            if plugin_failure is not None:
                raise plugin_failure


from ordessa_server.bootstrap.server_identity import _server_id


def _is_confirmed_unit_close(result: Any) -> bool:
    return (isinstance(result, Mapping)
            and result.get("state") == "confirmed"
            and result.get("unresolved") is False)


def _is_retryable_unit_close_pending(result: Any) -> bool:
    """Accept only Execution's explicit zero-effect all-Units-pending report."""
    if (not isinstance(result, Mapping)
            or set(result) != {"state", "units", "unresolved"}
            or result.get("state") != "pending"
            or result.get("unresolved") is not True):
        return False
    units = result.get("units")
    if type(units) is not tuple or not units:
        return False
    for unit in units:
        if (not isinstance(unit, Mapping)
                or set(unit) != {"identity", "state", "unresolved"}
                or not isinstance(unit.get("identity"), Mapping)
                or not unit.get("identity")
                or unit.get("state") != "pending"
                or unit.get("unresolved") is not True):
            return False
    return True


def _attach_shutdown_cleanup(start_failure: BaseException,
                             cleanup_failure: BaseException) -> None:
    """Attach a failed shutdown's per-plugin cleanup errors to the START
    error (the start failure stays primary). The start error travels
    explicitly — sys.exc_info() inside the cleanup's own except would name
    the cleanup exception instead."""
    errors = tuple(getattr(cleanup_failure, "errors", ()))
    if not errors:
        errors = (cleanup_failure,)
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
    composition = group[0].load()()
    bind_environment = getattr(composition, "bind_host_environment_ports", None)
    if callable(bind_environment):
        from ordessa_server.composition.product_unit_admission import create_product_unit_admission, create_owned_product_unit_admission
        from ordessa_server.bootstrap.security.secret_service import product_secret_store
        bind_environment(environment_factory=create_product_unit_admission,
                         owned_environment_factory=create_owned_product_unit_admission,
                         secret_store_factory=product_secret_store)
    bind_application = getattr(composition, "bind_host_application_ports", None)
    if callable(bind_application):
        from ordessa_system_access_bindings import agent_core_methods
        bind_application(runtime_builder=build_runtime, core_method_factory=agent_core_methods)
    bind_engineering = getattr(composition, 'bind_host_engineering_selection', None)
    if callable(bind_engineering):
        from ordessa_server.composition.engineering import select_engineering
        bind_engineering(select_engineering)
    bind = getattr(composition, "bind_host_execution_ports", None)
    if callable(bind):
        from ordessa_server.bootstrap.migrations.legacy_source import register_legacy_migrations
        from ordessa_units.assembly.runtime.assembler import assemble_runtime_composition
        from ordessa_server.bootstrap.storage.product_database import Database
        bind(migration_registrar=register_legacy_migrations,
             runtime_assembler=assemble_runtime_composition, database_factory=Database)
    bind_catalog = getattr(composition, "bind_harness_registry", None)
    if callable(bind_catalog):
        from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
        registry = getattr(composition, "bound_harness_registry", None)
        if registry is None:
            registry = capture_selected_harness_catalog().registry
        bind_catalog(registry)
    return composition


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
    funnel (`apps/server/deployment/default-product`: `default_plugins(**composition_kwargs)` →
    `ServerCompatPlugin`), which is the same route the production
    composition already used — the copy of that list that lived on
    `build_runtime` existed for tests and made the host name domains it
    does not own (FR-006). A caller that needs one of those injections
    asks the product composition for its plugin selection and passes it as
    `server_plugins`; `secret_store` and `local_workspace_provider` stay:
    the credential seam is the host's own and the local provider names a
    storage location, not a domain.
    """
    from ordessa_units.assembly.runtime.assembler import assemble_runtime_composition
    root = Path(data_root).resolve()
    _reject_unsafe_data_root_links(root)
    # The default product registers its sealed migration source while
    # selecting plugins. Resolve it before any data-root marker, lock, token,
    # or schema write so a partial historical root cannot be silently stamped
    # as current when that source is absent. Explicit bare compositions do
    # not gain the migration provider before the historical-root guard.
    from ordessa_server_plugin_api import (
        ContributionDeclarationError, ContributionPointSpec,
        WIRE_DISCOVERY_FACETS_POINT_ID,
        WIRE_ERROR_FAMILIES_POINT_ID, ServerPluginSelection,
        unique_contribution_point_specs,
    )

    selected_plugins: tuple[Any, ...]
    selection: ServerPluginSelection | None = None
    composition = None
    selected_product = False
    if server_plugins is None:
        composition = _resolve_product_composition()
        selection = ServerPluginSelection(
            plugins=tuple(composition.default_plugins()),
            contribution_points=tuple(composition.server_contribution_points()),
            environment_factory=getattr(composition, "environment_factory", None),
            owned_environment_factory=getattr(composition, "owned_environment_factory", None),
            core_method_factory=getattr(composition, "core_method_factory", None),
        )
        selected_plugins = tuple(selection)
        selected_product = True
        if database_factory is None:
            database_factory = (composition.database_type()
                if callable(getattr(composition, "database_type", None)) else None)
    elif isinstance(server_plugins, ServerPluginSelection):
        selection = server_plugins
        selected_plugins = tuple(selection)
        selected_product = True
    else:
        selected_plugins = tuple(server_plugins)
        # Plain sequences retain their old capability semantics. If the
        # installed product is needed only to supply the database factory,
        # carry its Environment factory neutrally while keeping product
        # contribution points absent for this explicit host selection.
        if database_factory is None:
            try:
                composition = _resolve_product_composition()
            except RuntimeError as exc:
                if selected_plugins or not str(exc).startswith("SERVER_PRODUCT_MISSING:"):
                    raise
            if composition is not None:
                selection = ServerPluginSelection(
                    plugins=selected_plugins,
                    contribution_points=(),
                    environment_factory=getattr(composition, "environment_factory", None),
                    owned_environment_factory=getattr(composition, "owned_environment_factory", None),
                )
                database_factory = (composition.database_type()
                if callable(getattr(composition, "database_type", None)) else None)

    if database_factory is None and selected_product and composition is None:
        # A detached explicit product selection still needs the selected
        # product's real storage provider; it never transfers product state
        # into the host.
        composition = _resolve_product_composition()
        database_factory = (composition.database_type()
                if callable(getattr(composition, "database_type", None)) else None)

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
    points = selection.contribution_points if selected_product and selection is not None else ()
    product_points: tuple[ContributionPointSpec, ...] = unique_contribution_point_specs(points)
    host_owned_points = frozenset((
        "execution.harness.definitions",
        WIRE_ERROR_FAMILIES_POINT_ID,
        WIRE_DISCOVERY_FACETS_POINT_ID,
    ))
    if any(spec.point_id in host_owned_points for spec in product_points):
        raise ContributionDeclarationError("product cannot redeclare a host-owned point")
    owner = DataRootOwner(root)
    unit_runtime: UnitRuntimeOwner | None = None
    plugin_host = None
    try:
        owner.acquire()
        token, token_path = _ensure_token(root)
        database = database_factory(root)
        # S-03/S-06: activate_all runs plugin build() which ensures schemas —
        # the database file and its migrations must exist first (constructor
        # stores paths, opens nothing). The future-schema refusal moves here,
        # to composition time, before any plugin code runs. Injected test
        # databases may manage their own lifecycle.
        if callable(getattr(database, "initialize", None)):
            database.initialize()
        objects = ObjectStore(root / "objects" / "sha256")
        notifier = EventNotifier()
        # T014-S2b: no connector is built here. The `server.instance_id` port
        # below is the only fact the host still hands the connector builders'
        # owner (the workspace plugin), and it names the data-root lock, not a
        # machine binding.
        secrets_store = secret_store
        if secrets_store is None and os.name == "nt":
            from ordessa_infrastructure.security.windows_dpapi import WindowsDpapiSecretStore
            secrets_store = WindowsDpapiSecretStore(root / "secrets" / "credentials",
                protect_description="AgentBox Server credential")

        idempotency = IdempotentRecords(database)
        credentials = CredentialRecords(database)

        # -- the plugin-host boundary --------------------------------------------
        # One dispatch truth: the host's method registry. The host registers
        # `server.hello`; every business row arrives through a plugin.
        from ordessa_server_plugin_api import ACP_ADMISSION_PORT, StreamRouteDescriptor  # noqa: F401  (admission type)
        from ordessa_server.composition.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
        from ordessa_interfaces.system_access.subscriptions.cursors import CursorCodec
        from ordessa_interfaces.system_access.services.invocation import WireService
        from ordessa_server.composition.acp_admission import AcpAdmissionGate, AcpAdmissionPortAdapter

        method_registry = MethodRegistry()
        stream_route_registry = StreamRouteRegistry()
        acp_admission_gate = AcpAdmissionGate(native_permissions=True)
        acp_admission_port = AcpAdmissionPortAdapter(acp_admission_gate, stream_route_registry)
        # One facade per composition forwards to the Environment factory
        # declared by the selected product. Server never creates a parallel
        # CoreRuntime or concrete store. A host-only composition has no
        # environment authority and its effect operations remain unavailable.
        environment_factory = selection.environment_factory if selection is not None else None
        owned_factory = selection.owned_environment_factory if selection is not None else None
        integrity_reference = root / 'state' / 'request-integrity.json'
        if integrity_reference.exists() or integrity_reference.is_symlink():
            from ordessa_server.composition.configuration.request_integrity import (
                load_request_integrity_port, RequestIntegrityConfigurationUnavailable,
            )
            if not callable(environment_factory) and not callable(owned_factory):
                raise RequestIntegrityConfigurationUnavailable('configured key requires a selected Unit admission factory')
            def fingerprint_factory(store):
                return load_request_integrity_port(data_root=root, records=credentials,
                    secret_store=secrets_store, unit_store=store)
            if callable(owned_factory):
                environment_factory = lambda path: owned_factory(path, owner,
                    fingerprint_factory=fingerprint_factory)
            else:
                selected_environment_factory = environment_factory
                environment_factory = lambda path: selected_environment_factory(path,
                    fingerprint_factory=fingerprint_factory)
        elif callable(owned_factory):
            environment_factory = lambda path: owned_factory(path, owner)
        unit_runtime = UnitRuntimeOwner(
            root / "state" / "core.sqlite",
            environment_factory=environment_factory,
            ownership_probe=lambda: owner.acquired,
            root_ownership_port=owner,
        )
        # The legacy database connection belongs to a selected product's
        # historical database as an INSTANCE holder (026 T006-01: it opens
        # its own sqlite3 connection in start(), never the process-global
        # work_core singleton). A host-only composition with its own
        # DatabasePort must be able to start without the compatibility
        # distribution installed.
        legacy_core = LegacyCoreBinding(database.path) if composition is not None or selected_product else None
        plugin_host = ServerPluginHost(
            methods=method_registry, stream_routes=stream_route_registry, data_root=root,
            host_ports={
                "runtime_composition_assembler": assemble_runtime_composition,
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
                # The legacy WorkCore connection seam cannot alias an
                # Environment StorePort. Keep the old caller fail-closed so
                # it cannot silently fall back to its process-global writer.
                "core_store": _unavailable_legacy_core_store,
                ACP_ADMISSION_PORT: acp_admission_port,
                # T014-S2c: the same per-composition resolver the transport gets
                # below, handed to the one plugin that converts errors inside its
                # own handlers. A callable, never the aggregate object: compat
                # resolves codes, it does not read or write the table.
                "wire.error_family_resolver": (
                    lambda code: plugin_host.wire_error_families.family_for(code)),
            },
        )
        if callable(environment_factory):
            plugin_host.host_ports = dict(plugin_host.host_ports,
                **{'execution.harness.catalog': unit_runtime.context.harness_catalog})
            plugin_host.register_contribution_point('execution.harness.definitions',
                'harness-definition/1', handler=HarnessDefinitionHandler(unit_runtime),
                exclusive=False)
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
        # in `apps/server/deployment/default-product`); the host forwards no business fact through.
        from ordessa_server.composition.configuration.contributions import bind_configuration_descriptor_admission
        bind_configuration_descriptor_admission(plugin_host, product_points)
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
            unit_runtime=unit_runtime, legacy_core=legacy_core,
            core_method_factory=selection.core_method_factory if selection is not None else None,
        )
        from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
        wire.identity_authority = InstanceAccessAuthority(lambda: runtime.token, grants=())
        # 026 T006-02: the wire round gate — dispatch answers business methods
        # only for a started round. Bound after the runtime exists and read
        # LIVE per dispatch (start() opens the gate, stop() closes it again);
        # `server.hello` stays answerable so discovery never lies about the
        # Server's existence. build_runtime internals (activate_all,
        # database.initialize) never pass through wire dispatch and are
        # unaffected.
        wire.bind_round_state(lambda: runtime.started)
        return runtime
    except BaseException as failure:
        pending = _FailedBuildCleanup(
            owner, plugin_host, unit_runtime,
            store=getattr(failure, "pending_store_close", None),
            environment=getattr(failure, "pending_environment_close", None),
        )
        try:
            pending.retry()
        except BaseException as cleanup_failure:
            # Strongly retain the original FD and Store even if the caller
            # drops the construction exception and runs GC.
            DataRootOwner._retain_failed_build(pending)
            try:
                existing = getattr(failure, "cleanup_errors", ())
                failure.cleanup_errors = tuple(existing) + (cleanup_failure,)
                failure.failed_construction = pending
            except (AttributeError, TypeError):
                pass
        raise
