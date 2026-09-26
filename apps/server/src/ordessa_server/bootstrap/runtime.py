"""Bootstrap assembly: the only place concrete implementations are selected.

Production assembly is provider-neutral: no Harness is wired by default, so
unimplemented capabilities report honestly unavailable until Work Order 40
registers real extension implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import csv
from datetime import datetime, timezone
import io
import logging
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import time
from typing import Any, Mapping
from uuid import uuid4

from pacthold.extensions import capability
from ordessa_server.approvals import ApprovalRecords
from ordessa_server.credentials import CredentialRecords
from ordessa_server.events import EventNotifier
from ordessa_server.errors import ServerError
from ordessa_server.execution import HarnessRegistry, TurnExecutionPort
from ordessa_server.execution.sidecar_backend import SidecarExecutionBackend as _SidecarBackendCls
from pacthold.extensions.runtime_composition.sandbox_port import resolve_sandbox_port
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.model_configs import ProviderModelRecords, ProviderModelService
from ordessa_server.profiles import ProfileRecords, ProfileService
from ordessa_server.wire.handlers import WireService
from ordessa_server.workspaces import WorkspaceRecords, WorkspaceService, WslConnectionPort
from pacthold.service import ProductService
from pacthold.service.sessions import SessionRecords, SessionService
from pacthold.service.sessions.queue import QueueRecords
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


def _builtin_connector(server_instance_id: str) -> WslConnectionPort | None:
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
    from ordessa_server.execution.ssh_connector import SshConnector

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
    repository: "ProductRepositoryView"
    service: ProductService
    owner: DataRootOwner
    token: str = field(repr=False)
    token_path: Path
    notifier: EventNotifier
    secret_store: SecretStore | None = None
    harnesses: HarnessRegistry | None = None
    execution: TurnExecutionPort | None = None
    wire: Any | None = None
    approvals: ApprovalRecords | None = None
    queue: QueueRecords | None = None
    model_configs: ProviderModelService | None = None
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
            self.database.initialize()
            _import_declared_credentials(self, self.declared_credentials)
            if self.native_harness_id is not None:
                profile = self.service.profiles.create_wire(
                    f"native-agent-profile:{self.native_harness_id}",
                    display_name=f"Native {self.native_harness_id}",
                    harness=self.native_harness_id,
                )
                stored = json.loads(self.objects.read(profile["config_object_digest"]))
                if (profile["harness_type"] != self.native_harness_id
                        or profile["archived_at"] is not None
                        or profile["credential_id"] is not None
                        or profile["account_id"] is not None
                        or profile["recovery_pending"]
                        or stored.get("configuration") != {}):
                    raise RuntimeError("NATIVE_PROFILE_CONFLICT")
                self.service.sessions._assert_profile_executable(profile["id"])
                self.native_profile_id = str(profile["id"])
                self.service.sessions.bind_native_profile(
                    self.native_profile_id, self.native_harness_id,
                    profile["config_object_digest"],
                )
            self.repository.mark_workspaces_unverified()
            self.repository.recover_interrupted_turns()
            from pacthold.work_core import db as core_db
            core_db.configure_database(self.database.path)
            core_db.get_conn()
        except BaseException:
            from pacthold.work_core import db as core_db
            core_db.configure_database(None)
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
        # order, before the data root itself is given up.
        if self.plugin_host is not None:
            self.plugin_host.shutdown()
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


def build_runtime(
    data_root: Path | str, *,
    harnesses: HarnessRegistry | None = None,
    connector: WslConnectionPort | None = None,
    ssh_connector=None,
    secret_store: SecretStore | None = None,
    execution: TurnExecutionPort | None = None,
    execution_factory=None,
    home_concurrency: Mapping[str, str] | None = None,
    shared_store_guards: Mapping[str, Any] | None = None,
    subscription_files_for=None,
    local_workspace_provider=None,
    server_plugins: "tuple[Any, ...] | list[Any] | None" = None,
) -> ServerRuntime:
    """Assemble a provider-neutral Server runtime.

    `harnesses` carries only descriptors for implementations registered for
    this deployment. `execution` is an explicit port injection (tests, or a
    future bootstrap that composes the Work Order 40 Harness plugin); the
    production default stays None so capability answers stay honest.

    `server_plugins` is the explicit plugin selection (the composition decides
    what is enabled; installing a distribution never enables one silently).
    ``None`` — the production default — enables the batch-1 composition: the
    Workspace domain plugin followed by the transitional core adapter. An
    empty sequence composes a bare host: only `server.hello` is advertised.
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
    registry = harnesses if harnesses is not None else HarnessRegistry()
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
    workspace_records = WorkspaceRecords(database, idempotency)
    profile_records = ProfileRecords(database, idempotency)
    provider_model_records = ProviderModelRecords(database, idempotency)
    session_records = SessionRecords(database, idempotency,
                                     home_concurrency=home_concurrency,
                                     shared_store_guards=shared_store_guards)
    from ordessa_server.accounts.assets import AccountAssetStore
    from ordessa_server.accounts.records import AccountRecords

    account_records = AccountRecords(database, idempotency)
    from ordessa_server.assets.mcp import McpAssetStore
    from ordessa_server.assets.records import AssetRecords
    from ordessa_server.assets.skills import SkillAssetStore

    from ordessa_server.assets.catalog import CatalogStore

    from ordessa_server.hooks.records import HookRecords
    from ordessa_server.hooks.triggers import HookTriggerRecords

    hook_records = HookRecords(database, idempotency)
    hook_triggers = HookTriggerRecords(database)
    asset_records = AssetRecords(database, idempotency)
    assets_root = root / "assets"
    skill_assets = SkillAssetStore(assets_root)
    mcp_assets = McpAssetStore(assets_root)
    from ordessa_server.assets.plugins import PluginAssetStore

    plugin_assets = PluginAssetStore(assets_root)
    asset_catalogs = CatalogStore(assets_root / "catalogs")
    # Order 56's encryption-at-rest requirement is the platform SecretStore's:
    # without one, a bound subscription account is a typed refusal at the turn
    # boundary rather than an unencrypted asset.
    account_assets = (
        AccountAssetStore(secret_store=secrets_store, accounts_root=root / "accounts")
        if secrets_store is not None else None
    )
    queue_records = QueueRecords(
        database, idempotency, append_event=session_records._append_session_event,
        objects=objects,
    )
    approval_records = ApprovalRecords(database, append_event=session_records._append_session_event)

    if execution is None and execution_factory is not None:
        try:
            execution = execution_factory(
                session_records, objects, approval_records, notifier, connectors,
                credentials, secrets_store,
            )
        except BaseException:
            owner.release()
            raise
    if execution is not None and hasattr(execution, "bind_queue"):
        execution.bind_queue(queue_records)

    workspace_service = WorkspaceService(
        workspace_records, idempotency, connector=connector_instance,
        ssh_connector=ssh_instance,
        **({"local": local_workspace_provider} if local_workspace_provider is not None else {}),
    )
    profile_service = ProfileService(profile_records, idempotency, objects,
                                     harnesses=registry, credentials=credentials)
    provider_model_service = ProviderModelService(
        provider_model_records, objects, harnesses=registry,
        credentials=credentials, profiles=profile_records,
        secret_store=secret_store,
    )
    profile_service.bind_model_configs(provider_model_service)
    session_service = SessionService(session_records, idempotency, objects,
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
    from ordessa_server.persistence import ProductRepositoryView
    repository = ProductRepositoryView(
        database=database, idempotency=idempotency, credentials=credentials,
        workspaces=workspace_records, profiles=profile_records, sessions=session_records,
    )
    # -- the plugin-host boundary (batch 1) ---------------------------------
    # One dispatch truth: the host's method registry. WireService owns no
    # table of its own any more; the Workspace plugin and the transitional
    # core adapter register their methods on it, in that order, which
    # reproduces the baseline hello capability order byte for byte.
    from server_plugin_api import StreamRouteDescriptor
    from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
    from ordessa_server.plugin_host.transition_core import TransitionCorePlugin
    from ordessa_server.plugin_host.workspace_plugin import WorkspaceServerPlugin
    from ordessa_server.wire.handlers import HOST_OWNER_ID

    method_registry = MethodRegistry()
    stream_route_registry = StreamRouteRegistry()
    plugin_host = ServerPluginHost(
        methods=method_registry, stream_routes=stream_route_registry, data_root=root,
        host_ports={
            "workspaces.records": workspace_records,
            "idempotency": idempotency,
            "workspace.wsl_connector": connector_instance,
            "workspace.ssh_connector": ssh_instance,
            "workspace.local_provider": local_workspace_provider,
        },
    )
    wire = WireService(
        server_id_provider=lambda: _server_id(database),
        profiles=profile_service, sessions=session_service,
        queue=queue_records, approvals=approval_records, harnesses=registry,
        objects=objects, execution=execution, cursor_secret=token.encode("utf-8"),
        method_registry=method_registry, stream_routes=stream_route_registry,
        model_configs=provider_model_service,
        accounts=account_records, account_assets=account_assets,
        subscription_files_for=subscription_files_for,
        asset_records=asset_records, skill_assets=skill_assets,
        mcp_assets=mcp_assets, plugin_assets=plugin_assets,
        catalogs=asset_catalogs,
        hooks=hook_records, hook_triggers=hook_triggers,
        connectors=connectors, data_root=root,
    )
    # Explicit selection only: None means the batch-1 product composition
    # (Workspace domain, then the transitional adapter); an empty sequence is
    # the bare host the boundary gates require. The string
    # "ordessa.transition-core" references the adapter by id — the only way to
    # compose adapter-inclusive custom selections, since the adapter wraps the
    # WireService built here. Activation failure here fails startup — never a
    # half-composed wire surface.
    if server_plugins is None:
        selected_plugins: "tuple[Any, ...]" = (WorkspaceServerPlugin(), TransitionCorePlugin(wire))
    else:
        selected_plugins = tuple(
            TransitionCorePlugin(wire) if item == "ordessa.transition-core" else item
            for item in server_plugins
        )
    try:
        plugin_host.activate_all(selected_plugins)
    except BaseException:
        # An activation failure must not keep the data-root lock: composing
        # the same root again in this process is the retry path.
        owner.release()
        raise
    # Resolved through the host on every read: unloading the Workspace plugin
    # unbinds its port for the adapter too — never a stale snapshot.
    wire.bind_workspace_resolution(
        lambda: plugin_host.provided_port("workspace.service"))
    runtime = ServerRuntime(
        root, database, objects, repository, service, owner, token, token_path,
        notifier, secrets_store, registry, execution, wire,
        approval_records, queue_records,
        provider_model_service,
        plugin_host=plugin_host, plugin_selection=selected_plugins,
    )
    # Order 56: the managed-account half of the composition, reachable where
    # the product and the acceptance gates need it (records + assets).
    runtime.account_records = account_records
    runtime.account_assets = account_assets
    runtime.asset_records = asset_records
    runtime.skill_assets = skill_assets
    runtime.mcp_assets = mcp_assets
    runtime.asset_catalogs = asset_catalogs
    runtime.plugin_assets = plugin_assets
    runtime.hook_records = hook_records
    runtime.hook_triggers = hook_triggers
    # Order 65 C: the delegation service and the per-attempt token registry the
    # bridge's loopback calls resolve through.
    from ordessa_server.execution.delegation import DelegationService

    runtime.delegation_service = DelegationService(
        records=session_records, profiles=profile_records, sessions=session_service,
        execution=execution, registry=registry, data_root=root, objects=objects,
    )
    runtime.delegation_tokens = {}
    return runtime


def build_runtime_from_native_adapter(
    data_root: Path | str, *, plugin_root: Path | str, harness_id: str,
    adapter_command: str, adapter_args: tuple[str, ...] = (),
    native_continuation: bool = False,
) -> ServerRuntime:
    """Compose one current-user ACP Agent in an explicitly native Server.

    The adapter is a launch reference, never a credential or projected home.
    The plugin entry verifies its bundled bridge provenance at launch.
    """
    import shutil
    from ordessa_server.execution import HarnessDescriptor
    from ordessa_server.execution.sidecar import (
        NativeHarnessPort, NativeProcessLauncher,
    )
    from ordessa_server.workspaces.local_environment import LocalEnvironmentProvider

    if not re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", harness_id):
        raise RuntimeError("NATIVE_HARNESS_INVALID")
    if type(native_continuation) is not bool:
        raise RuntimeError("NATIVE_CONTINUATION_INVALID")
    if (not Path(adapter_command).is_absolute() or not Path(adapter_command).is_file()
            or not os.access(adapter_command, os.X_OK)
            or any(not isinstance(arg, str) or "\x00" in arg for arg in adapter_args)):
        raise RuntimeError("NATIVE_ADAPTER_INVALID")
    plugin = Path(plugin_root).resolve()
    entry = plugin / "runtime" / "worker-entry.mjs"  # retired old chain, launch-fail honest
    access_entry = plugin / "runtime" / "access-entry.mjs"
    provenance = plugin / "third_party" / "harness_remote" / "SOURCE.json"
    node = shutil.which("node")
    if not access_entry.is_file() or not provenance.is_file() or node is None:
        raise RuntimeError("NATIVE_HARNESS_ARTIFACT_MISSING")
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        harness_id, capability_claims=(
            {"native_continuation": True} if native_continuation else {}
        ),
    ))
    root = Path(data_root).resolve()
    adapter = {"command": adapter_command, "args": list(adapter_args)}

    def factory(records, objects, approvals, notifier, _connectors, _credentials, _secrets):
        def port_factory(context, on_event):
            if context.get("env_kind") != "local" or context.get("harness_type") != harness_id:
                raise RuntimeError("NATIVE_PLACEMENT_UNSUPPORTED")
            project = context.get("normalized_path")
            if not isinstance(project, str) or not project:
                raise RuntimeError("NATIVE_PROJECT_REQUIRED")
            environment = dict(os.environ)
            environment.pop("AGENTBOX_SIDECAR_ISOLATED", None)
            resume_native_id = None
            checkpoint_digest = context.get("checkpoint_object_digest")
            if checkpoint_digest and context.get("checkpoint_native_id"):
                try:
                    checkpoint = json.loads(objects.read(checkpoint_digest))
                except Exception:
                    checkpoint = None
                if (isinstance(checkpoint, dict) and checkpoint.get("resumable") is True
                        and checkpoint.get("harnessType") == harness_id
                        and checkpoint.get("nativeSessionId") == context["checkpoint_native_id"]):
                    resume_native_id = context["checkpoint_native_id"]
            return NativeHarnessPort(
                NativeProcessLauncher((node, str(entry), "--native"), cwd=project),
                environment=environment, profile=harness_id, adapter=adapter,
                directory=project, state_directory=str(root / "native-bridge" / harness_id),
                resume_native_id=resume_native_id,
                declared_capabilities=registry.canonical_claims(harness_id),
                on_event=on_event,
            )

        return _SidecarBackendCls(
            records, objects, approvals, port_factory=port_factory,
            on_event=notifier.notify,
        )

    runtime = build_runtime(
        root, harnesses=registry, execution_factory=factory,
        local_workspace_provider=LocalEnvironmentProvider(execution_mode="native"),
    )
    runtime.native_harness_id = harness_id
    def validate_native_workspace(workspace_id):
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ServerError("NATIVE_PROJECT_REQUIRED", "a selected project is required", status=422)
        workspace = runtime.service.workspaces.records.get(workspace_id)
        if workspace["env_kind"] != "local":
            raise ServerError("NATIVE_PLACEMENT_UNSUPPORTED", "native Server requires a local project", status=409)
        selected = workspace["normalized_path"]
        normalized = runtime.service.workspaces.local.validate(selected)
        if normalized != selected:
            raise ServerError("NATIVE_PROJECT_CHANGED", "selected project changed", status=409)
    runtime.service.sessions.bind_native_workspace_validator(validate_native_workspace)
    def native_identity():
        identity = runtime.native_profile_id
        try:
            profile = runtime.service.profiles.records.get(identity) if identity else None
            stored = (json.loads(runtime.objects.read(profile["config_object_digest"]))
                      if profile is not None else None)
        except Exception:
            profile = None
        valid = (profile is not None and profile["harness_type"] == harness_id
                 and profile["archived_at"] is None and profile["credential_id"] is None
                 and profile["account_id"] is None and not profile["recovery_pending"]
                 and stored.get("configuration") == {}
                 and runtime.service.sessions.native_profile_identity is not None
                 and profile["config_object_digest"] ==
                     runtime.service.sessions.native_profile_identity[2])
        return {
            "mode": "native", "harness": harness_id,
            "profileId": identity if valid else None,
        }
    runtime.wire.native_execution_provider = native_identity
    # -- managed ACP channels (seam doc §5: the composition's transport entry) --
    # The channel is carried by the Harness plugin's production access entry:
    # the entry connects (verifying provenance, launching the declared adapter
    # with the Server-resolved cwd as the authoritative directory) and only
    # then relays ACP lines transparently; release goes through the entry's
    # own close-with-OS-confirmation contract.  Nothing here spawns an Agent
    # directly.
    from ordessa_server.acp_channel import AcpChannelRegistry
    from ordessa_server.acp_channel.access_entry import AccessEntryTransport

    def launch_channel_transport(*, harness_id: str, cwd: str, on_line, on_exit):
        environment = dict(os.environ)
        environment.pop("AGENTBOX_SIDECAR_ISOLATED", None)
        return AccessEntryTransport(
            node=node, entry=str(access_entry), harness_id=harness_id,
            cwd=cwd, adapter=adapter, on_line=on_line, on_exit=on_exit,
            environment=environment,
        ).start()

    runtime.acp_channels = AcpChannelRegistry(
        session_records=runtime.service.sessions.records,
        profile_records=runtime.service.profiles.records,
        launch=launch_channel_transport,
    )
    runtime.wire.acp_channels = runtime.acp_channels
    # The stream route is admitted through the host transport (origin/bearer/
    # close stay host-owned); batch 1 holds it under the host owner — the
    # Harness server facet takes ownership when that domain moves (next batch).
    from server_plugin_api import StreamRouteDescriptor
    from ordessa_server.wire.handlers import HOST_OWNER_ID

    runtime.wire.stream_routes.register(StreamRouteDescriptor(
        route_id="acp-channel", resolver=runtime.acp_channels.get, owner=HOST_OWNER_ID,
    ))
    return runtime


def build_runtime_from_sidecar_deployment(
    data_root: Path | str, deployment_path: Path | str,
    secret_store: SecretStore | None = None, *,
    plugin_root: Path | str, mount_bindings: Mapping[str, str] | None = None,
) -> ServerRuntime:
    """Compose registered Harnesses from an explicit non-secret deployment file.

    `secret_store` is the same explicit injection `build_runtime` accepts: a
    deployment that declares a credential kind needs a store to read the
    credential from, and a caller that already owns one (Windows DPAPI, or an
    acceptance harness with an ephemeral store) passes it here rather than
    relying on the platform default.

    The document names no host path. `plugin_root` is the machine-local root its
    plugin-relative sources are read from - supplied by whoever runs the Server,
    never carried in the document - and every mount the document declares names a
    `token` whose machine-local path `mount_bindings` supplies. A document that
    still carries a host path, or a mount with no binding, is refused rather than
    half-used: that refusal is what keeps one document runnable on any machine.
    """
    path = Path(deployment_path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or not isinstance(value.get("harnesses"), list)):
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    if "pluginRoot" in value:
        raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH")
    root = Path(plugin_root).resolve()
    bindings = dict(mount_bindings or {})
    used_bindings: set[str] = set()
    from ordessa_server.execution import HarnessDescriptor, HarnessRegistry, SidecarExecutionBackend
    from ordessa_server.execution.local_channel import LocalSidecarLauncher
    from ordessa_server.execution.placement import SSH_CHANNEL, WSL_CHANNEL, resolve_placement
    from ordessa_server.execution.sidecar import (
        SidecarHarnessPort, WorkerSidecarLauncher, sidecar_bundle_files,
    )
    from pacthold.resource_contracts.harness_capabilities import (
        CapabilityDeclarationError, validate_claims,
    )

    deployments: dict[str, dict[str, Any]] = {}
    additional_bundle: dict[str, bytes] = {}
    registry = HarnessRegistry()
    for item in value["harnesses"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        harness_id = item["id"]
        adapter = item.get("adapter")
        model_control_id = item.get("modelControlId")
        credential_kind = item.get("credentialKind")
        credential_environment = item.get("credentialEnvironment")
        # Order 56 stage A: a family whose subscription login is a declared
        # file set names it here, guest-home-relative. The names are the whole
        # authority for materialisation and reclamation - the working copy is
        # exactly these files, never a directory walk.
        subscription_credential = item.get("subscriptionCredential")
        subscription_files: tuple[str, ...] = ()
        if subscription_credential is not None:
            if (not isinstance(subscription_credential, dict)
                    or set(subscription_credential) != {"files"}
                    or not isinstance(subscription_credential.get("files"), list)
                    or not subscription_credential["files"]
                    or len(subscription_credential["files"]) > 8):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            declared_files: list[str] = []
            for relative in subscription_credential["files"]:
                if not isinstance(relative, str):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                _home_projection_target(f"/runtime/home/{relative}", kind="file")
                declared_files.append(relative)
            if len(set(declared_files)) != len(declared_files):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            subscription_files = tuple(declared_files)
        timeout_ms = item.get("timeoutMs", 120_000)
        if (harness_id in deployments
                or re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", harness_id) is None
                or not isinstance(adapter, dict)
                or not isinstance(adapter.get("command"), str)
                or not isinstance(adapter.get("args", []), list)
                or any(not isinstance(argument, str) or len(argument) > 8192 or "\x00" in argument
                       for argument in adapter.get("args", []))
                or type(timeout_ms) is not int or not 1 <= timeout_ms <= 120_000):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if model_control_id is not None and (
            not isinstance(model_control_id, str) or not model_control_id
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if credential_kind is not None and (
            not isinstance(credential_kind, str) or not credential_kind
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if credential_environment is not None and (
            credential_kind is None
            or not isinstance(credential_environment, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", credential_environment) is None
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        deployment = dict(item)
        deployment["_timeout_ms"] = timeout_ms
        adapter = dict(adapter)
        adapter_source = adapter.pop("source", None)
        if adapter_source is not None:
            if adapter["command"] != "/usr/bin/node":
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            content = _sidecar_deployment_file(root, adapter_source)
            bundle_path = f"agentbox-sidecar/deployment/{harness_id}/adapter.mjs"
            additional_bundle[bundle_path] = content
            adapter["args"] = [f"/runtime/view/{bundle_path}", *adapter.get("args", [])]
        driver = adapter.pop("driver", None)
        if driver is not None:
            # A native Harness whose protocol is not ACP declares the module the
            # sidecar must load instead, as a plugin file named by the
            # deployment. Nothing here knows what that module speaks: the
            # declaration is carried into the reviewed bundle and the fixed view
            # path is what the sidecar loads, so no brand reaches this layer.
            if (not isinstance(driver, dict) or set(driver) != {"source"}
                    or not isinstance(driver.get("source"), str)):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            content = _sidecar_deployment_file(root, driver["source"])
            driver_bundle_path = f"agentbox-sidecar/deployment/{harness_id}/driver.mjs"
            additional_bundle[driver_bundle_path] = content
            adapter["driver"] = {"module": f"/runtime/view/{driver_bundle_path}"}
        environment = adapter.get("environment") or {}
        if not isinstance(environment, dict) or any(
            not isinstance(key, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) is None
            or re.search(r"TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH", key, re.I)
            or not isinstance(setting, str) or len(setting) > 8192 or "\x00" in setting
            or re.fullmatch(r"sk-[A-Za-z0-9_-]+", setting) is not None
            for key, setting in environment.items()
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        adapter["environment"] = dict(environment)
        deployment["adapter"] = adapter
        projection_mounts = []
        projection_targets: list[str] = []
        for index, projection in enumerate(item.get("projectionFiles") or ()):
            if not isinstance(projection, dict) or set(projection) != {"source", "target"}:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            source = projection.get("source")
            # 目标先校验（同一个 guest home 语法，与 bwrap 侧共用一套实现），
            # 再读源文件：一个越界/非规范的目标不该让 Server 先去读盘。
            target = _home_projection_target(projection.get("target"), kind="file")
            content = _sidecar_deployment_file(root, source)
            suffix = Path(str(source)).name
            bundle_path = f"agentbox-sidecar/deployment/{harness_id}/projection-{index}-{suffix}"
            additional_bundle[bundle_path] = content
            projection_mounts.append((bundle_path, target))
            projection_targets.append(target)
        deployment["_projection_mounts"] = tuple(projection_mounts)
        executable_authorizations = []
        executable_mounts = []
        for executable in item.get("executableMounts") or ():
            if not isinstance(executable, dict) or "source" in executable:
                raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH")
            target = executable.get("target")
            digest_value = executable.get("digest")
            source = _bound_mount_path(executable.get("token"), bindings, used_bindings)
            if (not isinstance(target, str)
                    or re.fullmatch(r"/runtime/bin/[A-Za-z0-9._-]+", target) is None
                    or not isinstance(digest_value, str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            executable_authorizations.append({"path": source, "digest": digest_value})
            executable_mounts.append((source, target))
        deployment["_executable_authorizations"] = tuple(executable_authorizations)
        deployment["_executable_mounts"] = tuple(executable_mounts)
        artifact_authorizations = _runtime_artifact_declarations(
            item.get("runtimeArtifactMounts"), bindings, used_bindings,
        )
        deployment["_runtime_artifact_authorizations"] = artifact_authorizations
        deployment["_runtime_artifact_mounts"] = tuple(
            (str(declaration["path"]), str(declaration["target"]))
            for declaration in artifact_authorizations
        )
        preferred_auth_method = item.get("preferredAuthMethod")
        if preferred_auth_method is not None and (
            not isinstance(preferred_auth_method, str)
            or re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", preferred_auth_method) is None
        ):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        state_projection = item.get("stateProjection")
        # §14 (session library independent of the profile home): a family whose
        # session subtree can be split from the rest of its home declares
        # `sessionStore.kind = "sessions-subtree"`; the declared state target is
        # then the *session subtree* inside the guest home and is bound to the
        # per-harness store on the host. The default ("profile-home") keeps the
        # pre-§14 binding byte for byte - shared-DB families (the library holds
        # credential/account tables next to its session tables) must stay there.
        # Order 66 adds `whole-db`: the family library owns the live session
        # files named in `shared` (db + wal + shm + the revert/diff lands) and
        # everything else in the state directory stays in the profile home.
        session_store = item.get("sessionStore")
        session_store_kind = "profile-home"
        session_store_shared: tuple[tuple[str, str], ...] = ()
        if session_store is not None:
            if (not isinstance(session_store, dict)
                    or not set(session_store) <= {"kind", "shared"}
                    or not isinstance(session_store.get("kind"), str)
                    or session_store["kind"] not in
                    {"profile-home", "sessions-subtree", "whole-db"}):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            session_store_kind = session_store["kind"]
            if session_store_kind == "whole-db":
                declared = session_store.get("shared")
                if (not isinstance(declared, list) or not declared
                        or len(declared) > 16):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                entries: list[tuple[str, str]] = []
                for entry in declared:
                    if (not isinstance(entry, dict)
                            or set(entry) != {"name", "kind"}
                            or not isinstance(entry.get("name"), str)
                            or entry.get("kind") not in {"file", "directory"}):
                        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                    # The same sandbox spelling rule as every other relative
                    # declaration: safe names, no escape, bounded depth.
                    _home_projection_target(
                        f"/runtime/home/{entry['name']}", kind="file",
                    )
                    entries.append((entry["name"], entry["kind"]))
                if len({name for name, _kind in entries}) != len(entries):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                session_store_shared = tuple(entries)
            elif "shared" in session_store:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        state_target: str | None = None
        state_ephemeral_paths: tuple[str, ...] = ()
        if state_projection is not None:
            if (not isinstance(state_projection, dict)
                    or not set(state_projection) <= {"target", "ephemeralPaths"}
                    or not isinstance(state_projection.get("target"), str)):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            state_target = _home_projection_target(
                state_projection["target"], kind="directory",
            )
            declared = state_projection.get("ephemeralPaths")
            if declared is None:
                declared = []
            if not isinstance(declared, list) or len(declared) > 8:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            for relative in declared:
                if not isinstance(relative, str):
                    raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
                # 与 target 同一套沙箱语法验证“可写 state 内的临时子路径”，
                # 由 bwrap 以 tmpfs 遮蔽：可写但不进 view/state/checkpoint。
                _home_projection_target(
                    f"{state_target}/{relative}", kind="directory",
                )
            state_ephemeral_paths = tuple(declared)
        # 受保护集合**派生**自这份声明本身：落在可写 state 子树里的只读投影文件
        # （按 state 目标的相对路径记名）。它既不按家硬编码，也不依赖"overlay 恰好
        # 遮住"——checkpoint 捕获按名字排除，恢复遇到同名相对路径直接类型化拒绝。
        deployment["_protected_state_paths"] = _protected_state_paths(
            tuple(projection_targets), state_target,
        )
        if session_store_kind in {"sessions-subtree", "whole-db"} and state_target is None:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        if state_target is not None:
            deployment["_state_target"] = state_target
        else:
            deployment["_state_target"] = None
        usage_probe = item.get("usageProbe")
        if usage_probe is not None:
            if (not isinstance(usage_probe, dict)
                    or not set(usage_probe) <= {"journalSuffix", "format"}
                    or not isinstance(usage_probe.get("journalSuffix"), str)
                    or not isinstance(usage_probe.get("format"), str)):
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            from ordessa_server.execution.usage import FORMATS

            if usage_probe["format"] not in FORMATS:
                raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
            deployment["_usage_probe"] = {
                "journalSuffix": usage_probe["journalSuffix"],
                "format": usage_probe["format"],
            }
        else:
            deployment["_usage_probe"] = None
        deployment["_session_store"] = session_store_kind
        deployment["_session_store_shared"] = session_store_shared
        deployment["_subscription_files"] = subscription_files
        # Order 67's narrowed lock: a family whose home cannot be certified for
        # concurrent writers declares `homeConcurrency = "exclusive"`, and
        # admission then admits one active Turn per Profile for that family
        # alone. The default stays "shared": the Session is the uniqueness
        # unit, and the lock is declared per family, never guessed.
        home_concurrency_value = item.get("homeConcurrency", "shared")
        if home_concurrency_value not in {"shared", "exclusive"}:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        deployment["_home_concurrency"] = home_concurrency_value
        deployment["_state_ephemeral_paths"] = state_ephemeral_paths
        deployments[harness_id] = deployment
        # 能力声明是部署座位上的唯一入口：canonical id + 真 bool，其它一律类型化拒绝。
        # 任何生产模板都只能经过这里，不能再各自手写一套不受校验的字典。
        raw_claims = item.get("capabilityClaims")
        try:
            capability_claims = {} if raw_claims is None else validate_claims(raw_claims)
        except CapabilityDeclarationError as exc:
            raise RuntimeError(f"SIDECAR_DEPLOYMENT_INVALID: {exc.code}") from exc
        # Order 092: the seat may declare the canonical protocols it speaks and
        # the family-native dialect value for each. Absent = undeclared (unknown,
        # never incompatible); an illegal declaration is a typed refusal.
        raw_wire_protocols = item.get("wireProtocols") or {}
        if not isinstance(raw_wire_protocols, dict):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        from ordessa_server.execution import HarnessDescriptorError
        try:
            descriptor = HarnessDescriptor(
                harness_id,
                credential_kind=credential_kind,
                model_control_id=model_control_id,
                credential_environment=credential_environment,
                capability_claims=capability_claims,
                control_options={
                    str(key): tuple(options)
                    for key, options in dict(item.get("controlOptions") or {}).items()
                },
                security_locked_controls=tuple(item.get("securityLockedControls") or ()),
                wire_protocols=raw_wire_protocols,
            )
        except HarnessDescriptorError as exc:
            raise RuntimeError(f"SIDECAR_DEPLOYMENT_INVALID: {exc}") from exc
        registry.register(descriptor)
    unused = sorted(set(bindings) - used_bindings)
    if unused:
        # A binding nobody asked for is a typo or a stale document, and silently
        # ignoring it would hide which artifact the deployment really uses.
        raise RuntimeError("SIDECAR_ARTIFACT_BINDING_UNUSED")

    # Each seat's native home comes from the Harness registry, never from the
    # document: the document describes how a room runs, the registry says where
    # a Harness's own state lives. A seat with no declared native home cannot
    # run in the native-home model and is refused when a turn asks for it.
    native_homes = _registry_native_homes()
    for harness_id, deployment in deployments.items():
        deployment["_native_home"] = native_homes.get(harness_id)

    bundle = sidecar_bundle_files(root, additional_files=additional_bundle)

    # Credential sources are *declared* here and read from their own files: the
    # deployment document stays a non-secret artifact, and this is the only
    # place the product server can learn about a credential the operator (or the
    # Desktop that owns the machine's credential records) has placed. The strict
    # key set below is what enforces "no secret in the document" - a `value` or
    # `secret` key is a typed refusal, not an ignored extra.
    declared_credentials = _deployment_credentials(value)

    # The local placement's home root is this Server's own data root: the
    # Server *is* the machine that runs those turns. It is a machine-local
    # fact, never a document field and never a recorded path.
    local_home_root = str(Path(data_root).resolve() / "profiles")

    # Order 66 stage B: per-family guards for the shared session library. The
    # guard reads the library's database files on this machine
    # read-only (through the WAL) and refuses a switch when any credential
    # table is non-empty; families without a whole-db store have no guard.
    shared_store_guards: dict[str, Any] = {}
    for harness_id, deployment in deployments.items():
        if deployment.get("_session_store") != "whole-db":
            continue
        database_files = [
            name for name, kind in deployment["_session_store_shared"]
            if kind == "file" and name.endswith(".db")
        ]
        if not database_files:
            continue
        library = Path(local_home_root) / "_sessions" / harness_id

        def guard(paths=tuple(library / name for name in database_files)):
            from ordessa_server.execution.session_store_guard import guard_shared_store

            for path in paths:
                guard_shared_store(path)

        shared_store_guards[harness_id] = guard

    def factory(records, objects, approvals, notifier, connectors, credentials, secret_store):
        # No gate here: whether a connector is required depends on the placement
        # the workspace names, and that is resolved per turn.
        def port_factory(context, on_event):
            try:
                deployment = deployments[context["harness_type"]]
            except KeyError as exc:
                raise RuntimeError("HARNESS_DEPLOYMENT_UNAVAILABLE") from exc
            frozen = json.loads(objects.read(context["config_object_digest"]))
            execution = dict(frozen.get("execution") or {})
            descriptor = registry.get(context["harness_type"])
            credential_id = execution.get("credentialId") or context.get("credential_id")
            credential = None
            if credential_id is not None:
                record = credentials.get(credential_id, kind=descriptor.credential_kind)
                if secret_store is None:
                    raise RuntimeError("CREDENTIAL_STORE_UNAVAILABLE")
                try:
                    credential = secret_store.read(record["secret_locator"])
                except Exception as exc:  # Order 120: resolve at this layer
                    # The credential cannot be read on this machine. Fail here,
                    # before the capability gate and any spawn, so the transcript
                    # gets a typed, actionable reason (``CREDENTIAL_NOT_AVAILABLE``)
                    # rather than a KeyError collapsing into EXECUTION_FAILED. The
                    # id is non-sensitive; the secret value is never logged.
                    _log = logging.getLogger(__name__)
                    _log.warning(
                        "credential %s is unavailable for execution (harness %s): %s",
                        credential_id, context.get("harness_type"), exc)
                    raise RuntimeError("CREDENTIAL_NOT_AVAILABLE") from exc
            # The native home: no restore, no upload. The Harness reopens its
            # own durable directory on the machine that runs this turn; the
            # record's locator (kept once a turn has run) survives renames,
            # and the first turn of a Session derives it from the role name.
            native_home = deployment.get("_native_home")
            if not native_home:
                raise RuntimeError(
                    f"HARNESS_NATIVE_HOME_UNDECLARED: {context['harness_type']}"
                )
            home_locator = context.get("home_locator") or _profile_home_locator(
                context.get("profile_name") or context["harness_type"], native_home,
                profile_id=context.get("profile_id"),
            )
            # The workspace record says where this turn belongs; that fact - and
            # only that fact - decides which channel stages and starts it.
            kind = context.get("env_kind")
            placement = resolve_placement(
                kind, has_connector=connectors.get(kind) is not None,
            )
            audit_window = _window_of_state_target(
                deployment["_state_target"], native_home,
            )
            # The sandbox is resolved by name, never imported here: the name
            # comes from the deployment, the process environment, or the one
            # documented default provider id. An unresolvable name is a typed
            # refusal, not a silent run without isolation.
            # The default provider follows the placement (the machine that runs
            # the turn), not the host: a WSL/SSH guest is Linux even when the
            # Server itself sits on Windows (order 090). The name is still
            # resolved, never imported.
            sandbox_port = resolve_sandbox_port(
                _sandbox_provider_name(deployment, placement.kind))
            asset_files: dict[str, bytes] = {}
            profile_id_for_assets = context.get("profile_id")
            # A composition whose ledger has never been opened cannot hold a
            # binding: the ownership check is the file itself, not a guess.
            if (profile_id_for_assets
                    and getattr(runtime, "asset_records", None) is not None
                    and Path(runtime.database.path).exists()):
                from ordessa_server.assets.rendering import McpRenderError, render_for_family
                from ordessa_server.hooks.rendering import (
                    HookRenderError,
                    hooks_target_for,
                    merge_fragments,
                    render_hooks_fragment,
                )

                profile_spec = _registry_profile_spec(context["harness_type"])
                # One document per declared target; JSON targets collect keyed
                # fragments and merge, TOML targets concatenate their tables.
                json_documents: dict[str, dict[str, dict]] = {}
                toml_fragments: dict[str, list[str]] = {}

                for binding in runtime.asset_records.bindings(
                        profile_id_for_assets, enabled_only=True):
                    if binding["kind"] != "mcp":
                        continue
                    definition = runtime.mcp_assets.read(
                        asset_id=binding["assetId"], revision=binding["revision"])
                    if not runtime.mcp_assets.verify(
                            asset_id=binding["assetId"], revision=binding["revision"],
                            expected_digest=binding["digest"]):
                        raise RuntimeError(
                            "ASSET_DIGEST_MISMATCH: the stored MCP definition "
                            "no longer matches its recorded digest"
                        )
                    stdio = definition.get("transport", {}).get("stdio")
                    references = dict((stdio or {}).get("env") or {})
                    if references:
                        raise RuntimeError(
                            "MCP_CREDENTIAL_INJECTION_UNVERIFIED: this server "
                            f"carries credential references {sorted(references)} "
                            "and this family's injection path is not pinned yet"
                        )
                    try:
                        target, rendered = render_for_family(
                            definition, profile_spec=profile_spec, resolved_env={})
                    except McpRenderError as refusal:
                        raise RuntimeError(f"{refusal.code}: {refusal.message}") from refusal
                    if not target.startswith("/runtime/home/"):
                        raise RuntimeError(
                            "ASSET_SLOT_UNSUPPORTED: the declared MCP target is "
                            "outside the guest home"
                        )
                    if target.endswith(".toml"):
                        toml_fragments.setdefault(target, []).append(rendered)
                    else:
                        key = getattr(profile_spec, "mcp_key", None) or "mcpServers"
                        document = json.loads(rendered)
                        json_documents.setdefault(target, {}).setdefault(key, {}).update(
                            document.get(key, {}))

                # Order 59: enabled hooks join the same assembly, in the
                # family's own document shape.
                hook_rows = getattr(runtime, "hook_records", None)
                if hook_rows is not None:
                    enabled = hook_rows.enabled_for_family(context["harness_type"])
                    if enabled:
                        target, key = hooks_target_for(profile_spec)
                        if target is None:
                            raise RuntimeError(
                                "HOOK_TARGET_UNSUPPORTED: this family declares "
                                "no hook document target"
                            )
                        fragment = render_hooks_fragment(
                            context["harness_type"],
                            [row["model"] for row in enabled],
                        )
                        if target.endswith(".json"):
                            json_documents.setdefault(target, {})[key or "hooks"] = fragment
                        else:
                            raise RuntimeError(
                                "HOOK_TARGET_UNSUPPORTED: hooks need a JSON target"
                            )

                # Order 65 C: a Profile that may delegate gets the bridge as a
                # synthesized MCP server entry, carrying an attempt-scoped
                # token. Zero grants: no entry (no always-failing tools).
                bridge_entry = None
                if profile_id_for_assets:
                    from ordessa_server.profiles.subagents import (
                        grant_edges, has_delegation,
                    )

                    edges = grant_edges(
                        runtime.delegation_service.profiles.subagent_grants())
                    if has_delegation(edges, profile_id_for_assets):
                        import uuid as _uuid

                        token = _uuid.uuid4().hex
                        runtime.delegation_tokens[token] = {
                            "turnId": context.get("id"),
                            "profileId": profile_id_for_assets,
                        }
                        bridge_command = [
                            "/usr/bin/node",
                            "/runtime/view/agentbox-sidecar/runtime/subagent-bridge.mjs",
                        ]
                        bridge_entry = {
                            "command": bridge_command[0],
                            "args": bridge_command[1:],
                            "env": {
                                "AGENTBOX_BRIDGE_URL": self_url_of(),
                                "AGENTBOX_BRIDGE_TOKEN": token,
                            },
                            "name": "agentbox-subagents",
                            "target": _bridge_target(profile_spec),
                        }

                # The bridge creates its own document when the turn has no
                # other MCP content: a granted Profile always gets the tools.
                if bridge_entry is not None:
                    bridge_target = str(bridge_entry["target"] or "")
                    if bridge_target.endswith(".json"):
                        key = getattr(profile_spec, "mcp_key", None) or "mcpServers"
                        json_documents.setdefault(bridge_target, {}).setdefault(key, {})[
                            bridge_entry["name"]
                        ] = {
                            "command": bridge_entry["command"],
                            "args": list(bridge_entry["args"]),
                            "env": dict(bridge_entry["env"]),
                        }
                    elif bridge_target.endswith(".toml"):
                        lines = [
                            f"[mcp_servers.{bridge_entry['name']}]",
                            f'command = "{bridge_entry["command"]}"',
                            "args = [" + ", ".join(
                                f'"{item}"' for item in bridge_entry["args"]) + "]",
                        ]
                        for env_name, env_value in sorted(bridge_entry["env"].items()):
                            lines.append(f'{env_name} = "{env_value}"')
                        toml_fragments.setdefault(bridge_target, []).append(
                            "\n".join(lines) + "\n")
                    else:
                        raise RuntimeError(
                            "SUBAGENT_BRIDGE_TARGET_UNSUPPORTED: this family "
                            "declares no MCP document for the bridge"
                        )

                projected = {
                    str(target_value)
                    for _source, target_value in deployment.get("_projection_mounts", ())
                }
                for target, fragments in sorted(json_documents.items()):
                    if target in projected:
                        raise RuntimeError(
                            "ASSET_SLOT_CONFLICT: a read-only projection already "
                            "covers the declared target " + target
                        )
                    try:
                        text = merge_fragments(
                            target, [(key, value) for key, value in fragments.items()])
                    except HookRenderError as refusal:
                        raise RuntimeError(f"{refusal.code}: {refusal.message}") from refusal
                    asset_files[target[len("/runtime/home/"):]] = text.encode("utf-8")
                for target, parts in sorted(toml_fragments.items()):
                    if target in projected:
                        raise RuntimeError(
                            "ASSET_SLOT_CONFLICT: a read-only projection already "
                            "covers the declared target " + target
                        )
                    asset_files[target[len("/runtime/home/"):]] = (
                        "\n".join(part.rstrip("\n") for part in parts) + "\n"
                    ).encode("utf-8")
            subscription = None
            subscription_asset: dict[str, bytes] = {}
            account_id = context.get("account_id")
            if account_id:
                declared = deployment.get("_subscription_files") or ()
                if not declared:
                    raise RuntimeError(
                        "SUBSCRIPTION_UNSUPPORTED: this Harness declares no "
                        "subscription login-state files"
                    )
                # The accounts half is attached to the runtime by
                # build_runtime; the closure reads it per turn.
                if getattr(runtime, "account_assets", None) is None:
                    raise RuntimeError("ACCOUNT_STORE_UNAVAILABLE")
                _record = runtime.account_records.get(account_id)
                locator, digest = runtime.account_records.asset_reference(account_id)
                if locator is not None:
                    subscription_asset = runtime.account_assets.read_asset(
                        locator=locator, declared=declared)
                subscription = {
                    "account_id": account_id,
                    "materialized_digest": digest,
                    "files": tuple(declared),
                }
            if placement.channel in {WSL_CHANNEL, SSH_CHANNEL}:
                launcher = WorkerSidecarLauncher(
                    connectors[placement.kind],
                    workspace={
                        "distribution": context["distribution"],
                        "remote_user": context["remote_user"],
                        "connection_id": context["connection_id"],
                        "remote_path": context["remote_path"],
                    },
                    bundle=bundle, credential=credential,
                    executable_authorizations=deployment["_executable_authorizations"],
                    executable_mounts=deployment["_executable_mounts"],
                    runtime_artifact_authorizations=deployment["_runtime_artifact_authorizations"],
                    runtime_artifact_mounts=deployment["_runtime_artifact_mounts"],
                    projection_mounts=deployment["_projection_mounts"],
                    home_locator=home_locator,
                    native_home=native_home,
                    profile_id=context["profile_id"],
                    harness_type=context["harness_type"],
                    audit_window=audit_window,
                    state_ephemeral_paths=deployment["_state_ephemeral_paths"],
                    protected_state_paths=deployment["_protected_state_paths"],
                    timeout_ms=deployment["_timeout_ms"],
                    sandbox_port=sandbox_port,
                    session_store_harness=(
                        context["harness_type"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_target=(
                        deployment["_state_target"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_shared=deployment["_session_store_shared"],
                    subscription_files=(subscription or {}).get("files", ()),
                    asset_files=asset_files,
                    usage_probe=deployment["_usage_probe"],
                )
            else:
                launcher = LocalSidecarLauncher(
                    workspace_path=context.get("normalized_path") or context["remote_path"],
                    bundle=bundle, credential=credential,
                    executable_mounts=deployment["_executable_mounts"],
                    runtime_artifact_mounts=deployment["_runtime_artifact_mounts"],
                    projection_mounts=deployment["_projection_mounts"],
                    home_root=local_home_root,
                    home_locator=home_locator,
                    native_home=native_home,
                    profile_id=context["profile_id"],
                    harness_type=context["harness_type"],
                    state_target=deployment["_state_target"],
                    state_ephemeral_paths=deployment["_state_ephemeral_paths"],
                    protected_state_paths=deployment["_protected_state_paths"],
                    sandbox_port=sandbox_port,
                    session_store_harness=(
                        context["harness_type"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_target=(
                        deployment["_state_target"]
                        if deployment["_session_store"] in {"sessions-subtree", "whole-db"} else None
                    ),
                    session_store_shared=deployment["_session_store_shared"],
                    subscription_files=(subscription or {}).get("files", ()),
                    subscription_asset=subscription_asset,
                    asset_files=asset_files,
                    usage_probe=deployment["_usage_probe"],
                )
            capability_documents, capability_grants, authorized, binding = (
                _capability_material(context, deployment)
            )
            return SidecarHarnessPort(
                launcher,
                subscription=subscription,
                account_plumbing=(
                    (runtime.account_records, runtime.account_assets)
                    if subscription is not None else None
                ),
                environment={"AGENTBOX_SIDECAR_ISOLATED": "1"},
                profile=context["harness_type"], adapter=deployment["adapter"],
                model=execution.get("model"),
                capability_documents=capability_documents,
                capability_grants=capability_grants,
                capability_authorized_providers=authorized,
                capability_binding=binding,
                credential_environment=(
                    descriptor.credential_environment if credential is not None else None
                ),
                preferred_auth_method=deployment.get("preferredAuthMethod"),
                # A recorded native id is reopened only when the harness
                # declares durable state (a native-home window) and a turn has
                # already recorded a locator under it. Anything less - a
                # pre-home Session, a seat with no declared window - opens a
                # fresh native session, and the changed native id says so
                # instead of pretending a reopen succeeded.
                resume_native_id=(
                    context.get("checkpoint_native_id")
                    if context.get("home_locator") and deployment["_state_target"]
                    else None
                ),
                # The sidecar's own working state (a bridge's session index)
                # lives inside the home window: it must survive the attempt,
                # because the next turn's resume reads it from the same durable
                # directory the room binds. It was an ephemeral /tmp path when
                # state travelled as bytes; the home replaces both.
                state_directory=deployment["_state_target"]
                or f"/runtime/home/{native_home}",
                directory="/workspace",
                native_platform=placement.kind if kind else None,
                home_locator=home_locator,
                # 静态上限只能来自已校验的注册声明（不依赖 port 的默认值）。
                declared_capabilities=descriptor.capability_claims,
                usage_probe=deployment["_usage_probe"],
                on_event=on_event,
            )

        return SidecarExecutionBackend(
            records, objects, approvals, port_factory=port_factory,
            on_event=notifier.notify,
        )

    runtime = build_runtime(data_root, harnesses=registry, execution_factory=factory,
                            secret_store=secret_store,
                            home_concurrency={
                                harness_id: deployment["_home_concurrency"]
                                for harness_id, deployment in deployments.items()
                            },
                            shared_store_guards=shared_store_guards,
                            subscription_files_for=lambda harness: (
                                deployments.get(harness, {}).get("_subscription_files") or ()
                            ))
    runtime.declared_credentials = tuple(declared_credentials)
    return runtime


#: 装配边界自有锁定允许映射：只有显式批准的能力声明提供者才能进入选择。
#: "已安装/已加载"本身不构成授权——声明文档的 provider 必须与这里的身份逐字相符。
_APPROVED_CAPABILITY_DECLARERS = frozenset({"sandbox-bwrap"})


def _capability_binding(context: Mapping[str, Any]) -> str:
    """本次执行的中立环境身份（canonical 串）：分发/连接/远端路径三元组。

    声明文档与匹配上下文都用这一处派生结果，保证声明、授权、需求与环境绑定
    绑定在同一次执行上；绑定不含品牌词，业务层与公共层不需要解释它。
    """
    return "|".join((
        str(context.get("distribution", "")),
        str(context.get("connection_id", "")),
        str(context.get("remote_path", "")),
    ))


def _sandbox_provider_name(deployment: Mapping[str, Any], placement_kind: str | None) -> str:
    """The sandbox provider that composes the room for THIS execution.

    The room runs on the machine that executes the turn, not the machine hosting
    the Server (R-0014: a Windows control plane drives Linux WSL/SSH workers).
    A WSL/SSH placement always lands in a Linux guest, so its default is the
    guest sandbox - even when the Server process itself sits on Windows. Only a
    native `local` placement may default to the Windows sandbox. A deployment may
    still name `sandboxProvider` explicitly, or the process may pin
    `AGENT_BOX_SANDBOX_PROVIDER`; neither is overridden here. Keying the default
    on the host alone is order 090's defect: it sent a WSL turn to
    `sandbox-windows`, unresolved in the guest, and the refusal came back as an
    ambiguous dispatch.
    """
    provider = deployment.get("sandboxProvider") or os.environ.get("AGENT_BOX_SANDBOX_PROVIDER")
    if provider:
        return str(provider)
    if placement_kind in {"wsl", "ssh"}:
        return "sandbox-bwrap"
    return "sandbox-windows" if os.name == "nt" else "sandbox-bwrap"


def _capability_material(
    context: Mapping[str, Any], deployment: Mapping[str, Any],
) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[str, ...], str]:
    """Build the neutral injectables for one execution at the assembly boundary.

    返回 (declaration documents, grants, authorized providers, binding)：
    * documents 由插件以本次部署派生的 targets 逐执行构造（与 launcher 同源）；
      插件拒绝或 provider 不在批准映射内时返回空集——门随后 fail-closed 拒绝；
    * grants 来自部署文档的显式授权字段（独立推导路径），provenance 锁定政策；
    * authorized providers 来自本模块常量映射，不取自声明文档自身。
    """
    binding = _capability_binding(context)
    executable_targets = tuple(
        target for _source, target in deployment.get("_executable_mounts", ())
    )
    projection_targets = tuple(
        target for _source, target in deployment.get("_projection_mounts", ())
    )
    artifact_targets = tuple(
        target for _source, target in deployment.get("_runtime_artifact_mounts", ())
    )
    state_target = deployment.get("_state_target")
    grants = capability.sidecar_grants(
        deployment_executable_targets=executable_targets,
        deployment_projection_targets=projection_targets,
        deployment_artifact_targets=artifact_targets,
        deployment_state_target=state_target,
    )
    documents: tuple[Any, ...] = ()
    try:
        # 身份独立核对：实际安装插件的 descriptor id 与声明自报的 provider 必须
        # 一致，且两者都落在本模块的锁定批准映射内。"已安装/已加载"本身不构成
        # 授权——descriptor 只是待比对的身份，批准集才是授权来源。
        # 声明文档由**已解析的沙箱端口**构造（上层不认识具体沙箱）。
        # 默认随放置走（`_sandbox_provider_name`），与本执行 port_factory 同源。
        port = resolve_sandbox_port(
            _sandbox_provider_name(deployment, context.get("env_kind")))
        descriptor_id = port.descriptor_id()
        document = port.declaration_document(
            readonly_targets=executable_targets + projection_targets + artifact_targets,
            writable_targets=((state_target,) if state_target else ()),
            environment_binding=binding,
            observed_at=int(time.time()),
        )
        if (
            descriptor_id in _APPROVED_CAPABILITY_DECLARERS
            and document.provider in _APPROVED_CAPABILITY_DECLARERS
            and document.provider == descriptor_id
        ):
            documents = (document,)
    except Exception:
        # 解析不到端口、或 provider 按自己的语法拒绝了声明的面：材料留空；
        # 能力门随后 fail-closed 拒绝本次执行——绝不把失败变成一份声明。
        documents = ()
    return documents, grants, tuple(sorted(_APPROVED_CAPABILITY_DECLARERS)), binding


#: The exact keys one credential declaration may use. `sourcePath` is a *path*;
#: a document that tried to carry the secret itself would have to invent a key,
#: and an invented key is a refusal here rather than a silently ignored extra.
_CREDENTIAL_DECLARATION_KEYS = frozenset({"credentialId", "kind", "label", "sourcePath"})
_CREDENTIAL_ID = re.compile(r"^credential_[0-9a-f]{32}$")


def _deployment_credentials(value: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate the optional `credentials` section of a deployment document.

    Returns the declarations in order; each is `{credentialId, kind, sourcePath,
    label}` with the label possibly empty. Nothing is read here - the file is
    opened by the secret store during import, which is also where the
    symlink/size/bounds rules live, so a declaration can only point at a real,
    ordinary file within the store's own limits.
    """
    raw = value.get("credentials")
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 16:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credentials must be at most 16 entries")
    declarations: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or set(item) - _CREDENTIAL_DECLARATION_KEYS:
            raise RuntimeError(
                "SIDECAR_DEPLOYMENT_INVALID: a credential declaration takes exactly "
                "credentialId, kind, sourcePath and optional label"
            )
        credential_id = item.get("credentialId")
        kind = item.get("kind")
        source = item.get("sourcePath")
        label = item.get("label", "")
        if not isinstance(credential_id, str) or _CREDENTIAL_ID.fullmatch(credential_id) is None:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credentialId must be credential_<32 hex>")
        if credential_id in seen:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: duplicate credentialId")
        if not isinstance(kind, str) or not (1 <= len(kind) <= 32):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credential kind is required")
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credential sourcePath must be absolute")
        if not isinstance(label, str) or len(label) > 64:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID: credential label is at most 64 characters")
        seen.add(credential_id)
        declarations.append({
            "credentialId": credential_id, "kind": kind, "label": label, "sourcePath": source,
        })
    return declarations


def _import_declared_credentials(runtime: Any, declarations: list[dict[str, str]]) -> None:
    """Import each declared source into the Server's own store, once.

    A restart with the same deployment must not duplicate records or re-read the
    source: the declaration names an identity, and an identity that already
    resolves is already satisfied. A declaration whose source has since become
    unreadable fails the start rather than quietly leaving a harness without the
    credential it was declared with.
    """
    records = runtime.repository.credentials
    for declaration in declarations:
        if records.exists(declaration["credentialId"]):
            continue
        store = runtime.secret_store
        if store is None:
            raise RuntimeError(
                "SIDECAR_DEPLOYMENT_CREDENTIAL_STORE_MISSING: the deployment declares a "
                "credential but this Server was composed without a secret store"
            )
        try:
            _store_id, locator = store.import_file(
                Path(declaration["sourcePath"]), declaration["kind"],
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"SIDECAR_DEPLOYMENT_CREDENTIAL_UNREADABLE: {declaration['credentialId']}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        records.register(declaration["credentialId"], declaration["kind"], locator)


def _home_projection_target(target: Any, *, kind: str) -> str:
    """Validate one declared guest-home target with the sandbox's own grammar.

    The Server does not own the guest layout: the one implementation lives with
    the sandbox that will actually create it, and this wrapper only translates
    its typed refusal into the deployment-level error this loader reports.  A
    deployment is therefore accepted here if and only if the compiler can mount
    it.
    """
    from pacthold.resource_contracts.home_projection import (
        HomeProjectionRejected, home_projection_target,
    )

    try:
        return home_projection_target(target, kind=kind)
    except HomeProjectionRejected:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None


def _protected_state_paths(
    projection_targets: tuple[str, ...], state_target: str | None,
) -> tuple[str, ...]:
    """Derive the read-only paths inside the writable state subtree."""
    from pacthold.resource_contracts.home_projection import (
        HomeProjectionRejected, protected_state_paths,
    )

    try:
        return protected_state_paths(projection_targets, state_target)
    except HomeProjectionRejected:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None


#: The token grammar shared by every mount a deployment declares.
MOUNT_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,31}")


def _bound_mount_path(
    token: Any, bindings: Mapping[str, str], used: set[str],
) -> str:
    """Resolve one mount token to the machine-local path the caller bound.

    A document that names a host path instead of a token, a token nobody bound,
    or a binding value that is not an absolute path is refused here: the same
    document has to run on WSL, on this machine and over SSH, and a path in the
    document is exactly what stops that from being true.
    """
    if not isinstance(token, str) or MOUNT_TOKEN.fullmatch(token) is None:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    bound = bindings.get(token)
    if not isinstance(bound, str) or not bound.startswith("/"):
        raise RuntimeError("SIDECAR_ARTIFACT_BINDING_MISSING")
    if "\\" in bound or "\x00" in bound or "//" in bound or bound.endswith("/"):
        raise RuntimeError("SIDECAR_ARTIFACT_BINDING_INVALID")
    used.add(token)
    return bound


def _runtime_artifact_declarations(
    value: Any, bindings: Mapping[str, str] | None = None, used: set[str] | None = None,
) -> tuple[dict[str, str], ...]:
    """Validate `runtimeArtifactMounts`, resolving each token to its binding.

    The document declares *which* artifact tree a Harness needs and its expected
    digest; where that tree lives on the machine running the Worker is the
    caller's binding, not the document's line.  Existence, link status, the tree
    digest and every overlap rule are still settled on that machine, inside the
    distribution that will read the tree; the Server refuses a declaration that
    could not be verified at all and carries the exact digests across unchanged.
    """
    from pacthold.resource_contracts.runtime_artifacts import (
        MAX_RUNTIME_ARTIFACT_TREES, RuntimeArtifactRejected,
        validate_runtime_artifact_target,
    )

    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_RUNTIME_ARTIFACT_TREES:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    declarations: list[dict[str, str]] = []
    paths: set[str] = set()
    targets: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"token", "target", "treeDigest"}:
            raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH" if "source" in item
                               else "SIDECAR_DEPLOYMENT_INVALID")
        source = _bound_mount_path(item["token"], bindings or {}, used if used is not None else set())
        target = item["target"]
        digest_value = item["treeDigest"]
        if (not isinstance(digest_value, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None):
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        try:
            validate_runtime_artifact_target(target)
        except RuntimeArtifactRejected:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None
        if source in paths or target in targets:
            raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
        paths.add(source)
        targets.add(target)
        declarations.append({"path": source, "target": target, "digest": digest_value})
    return tuple(declarations)


def _sidecar_deployment_file(root: Path, relative: Any) -> bytes:
    """Read one non-secret plugin artifact named by the deployment.

    `relative` is a plugin-relative name, never a host path: a drive letter, a
    leading separator or a UNC prefix is refused here, so a document written for
    one machine cannot half-work on another.
    """
    if (not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
            or ":" in relative or "\x00" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise RuntimeError("SIDECAR_DEPLOYMENT_HOST_PATH")
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID") from None
    if not resolved.is_file() or resolved.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("SIDECAR_DEPLOYMENT_INVALID")
    return resolved.read_bytes()


def _bridge_target(profile_spec) -> str | None:
    """The file the bridge entry belongs in, per the family's MCP declaration."""
    return getattr(profile_spec, "mcp_target", None)


def self_url_of() -> str:
    """The loopback URL the bridge dials back on.

    The Server's own bind address is a machine-local fact; the bridge runs in
    the same machine's network namespace, so the loopback address is the one
    that is always right. The port comes from the environment when the
    embedding process set one, and defaults to the documented port.
    """
    import os as _os

    port = _os.environ.get("AGENT_BOX_HTTP_PORT") or "8732"
    return f"http://127.0.0.1:{port}"


def _registry_profile_spec(harness_type: str):
    """The Harness's own `[harness.profile]` declaration, from the registry.

    Asset slots are the family's own facts (target path, key spelling), so
    they come from the registry the family ships - never from this module and
    never from the deployment, which describes a room, not a family.
    """
    try:
        from ordessa_harness.registry import load_builtin_registry
    except ImportError:
        return None
    try:
        definition = load_builtin_registry().get(harness_type)
        return getattr(definition, "profile", None)
    except BaseException:  # noqa: BLE001 - an unknown family has no slots
        return None


def _registry_native_homes() -> dict[str, str]:
    """The native home each registered Harness declares, keyed by seat id.

    Asked once per composition. The registry is the only place a Harness says
    where its own state lives; a deployment cannot invent one, and a seat the
    registry does not know has none (refused at dispatch, not guessed here).
    """
    try:
        from ordessa_harness.registry import load_builtin_registry
    except ImportError:
        return {}
    try:
        registry = load_builtin_registry()
    except Exception:
        return {}
    homes = {}
    for definition in registry.all():
        homes[definition.identity.harness_type] = definition.profile.native_home
    return homes


def _profile_home_locator(name: str, native_home: str, *, profile_id: str | None = None) -> str:
    """`<role>-<id suffix>/<native home>` - the locator a first Session records.

    The role directory is a normalized label chosen at creation; a later
    rename never recomputes it, because the Session (and the marker inside)
    keeps the locator that was recorded when the home was made.

    The eight-character suffix is the Profile's own identity, and it is what
    keeps two Profiles that share a display name on two different homes: the
    marker check compares identities, so a name-only directory would refuse
    the second Profile for good (the HOME_MARKER_CONFLICT the family gates
    kept hitting across runs). A first Session always records the resolved
    locator, so the rule stays stable for every later turn.
    """
    normalized = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")
    normalized = normalized[:40] or "role"
    suffix = ""
    if profile_id:
        tail = re.sub(r"[^a-z0-9]+", "", str(profile_id).lower())[-8:]
        if tail:
            suffix = f"-{tail}"
    return f"{normalized}{suffix}/{native_home}"


def _window_of_state_target(state_target: str | None, native_home: str) -> str | None:
    """The audit window relative to the role directory, or None.

    `stateProjection.target` stays a guest path under the guest home; the
    window is that path minus the guest home prefix, so it can name a subtree
    outside the native home as well as one inside it - whichever way the
    Harness family declares its own durable state. A target outside the guest
    home cannot be served by a home bind and is refused.
    """
    del native_home
    if not state_target:
        return None
    prefix = "/runtime/home/"
    if not state_target.startswith(prefix) or state_target == prefix:
        raise RuntimeError("SIDECAR_STATE_PROJECTION_INVALID")
    window = state_target[len(prefix):]
    if (not window or window.startswith("/")
            or any(part in {"", ".", ".."} for part in window.split("/"))
            or "\\" in window or "\x00" in window):
        raise RuntimeError("SIDECAR_STATE_PROJECTION_INVALID")
    return window
