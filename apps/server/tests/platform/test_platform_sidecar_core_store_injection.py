"""026 T006-01 (first half): the sidecar execution chain rides the instance store.

The third parallel root the order removes: ``SidecarExecutionBackend`` used to
build a private ``CoreRepository()`` with no store, so every legacy-chain
statement resolved through the ``pacthold.work_core.db`` process-global
singleton — during activation that is the foreign ``AGENT_BOX_HOME``
mis-binding the S1c entry in ``docs/known-issues.md`` reports. The host now
hands the chain its own C1 instance store (``state/core.sqlite``, the
``CoreBinding`` seam) through the ``core_store`` host port, and the backend
routes every statement onto that ONE connection.

Positive face: the injected store IS the binding's store (one connection, no
copy), the kernel's neutral work-core schema lands on it once, and filed work
rows land in the instance file — never in the global. Counterexample face: no
injection keeps the historical default byte-for-byte (the connection provider
IS ``db.get_conn`` and the write lock IS ``db.write_lock``).

0 real model calls, 0 credential content: every store is a ``tmp_path`` file
(or the isolated ``AGENT_BOX_HOME`` the shared fixture provides).
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

from ordessa_server.bootstrap import build_runtime
from ordessa_server.core_binding import CoreBinding
from ordessa_server_compat.composition import _injected_core_store
from ordessa_server_compat.execution.sidecar_backend import SidecarExecutionBackend
from ordessa_server_compat.plugin import ServerCompatPlugin
from ordessa_workspace.plugin import WorkspaceServerPlugin
from pacthold.work_core import db as core_db
from pacthold_runtime_compat.bootstrap import build_product_registry

#: No native turn runs in these gates: the port factory must never be called.
def _idle_port_factory(context, on_event):
    raise RuntimeError("no native turn runs in this gate")


def _unbound_backend(**kwargs):
    """A backend whose records/objects/approvals are inert sentinels.

    The constructor only stores them; these gates exercise the Core seams,
    not the turn paths that read them.
    """
    return SidecarExecutionBackend(
        object(), object(), object(), port_factory=_idle_port_factory, **kwargs)


def test_injected_store_is_the_binding_instance_store(tmp_path, tmp_agent_box_home):
    """The one connection: what the host injects resolves to the binding's
    own store, the kernel's neutral work-core schema lands there, and a
    legacy-chain filing lands in the instance store — the process-global
    singleton stays unconfigured and unopened."""
    binding = CoreBinding(tmp_path / "state" / "core.sqlite")
    provider = lambda: binding.store  # the host's own lazy carrier shape

    backend = _unbound_backend(store=provider)
    # the raw injected value is kept for identity assertions; resolution is
    # lazy (the round opens on the first core statement, never at composition)
    assert backend.store is provider
    assert binding.ever_opened is False
    assert backend.store() is binding.store

    work = backend.work_service.create_work("T006-01 injection probe")
    row = binding.store.execute(
        "SELECT objective FROM core_works WHERE id = ?", (work.id,)).fetchone()
    assert row is not None and row["objective"] == "T006-01 injection probe"
    # the durable fact is in the instance FILE, not only the connection cache
    with sqlite3.connect(str(binding.store_path)) as conn:
        filed = conn.execute(
            "SELECT COUNT(*) FROM core_works WHERE id = ?", (work.id,)).fetchone()
    assert filed[0] == 1
    # the global singleton was never configured and never opened on this path
    assert core_db._database_override is None
    assert core_db._conn is None


def test_injected_registry_receives_the_backend_registrations(tmp_agent_box_home):
    """The registry seam: an injected ExtensionRegistry is used as-is (the
    backend's resource/execution providers register into IT), while absent
    injection still builds a fresh per-activation product registry."""
    registry = build_product_registry()
    backend = _unbound_backend(registry=registry)
    assert backend.registry is registry
    assert registry.get_resource_provider(
        backend.resources.provider_id) is backend.resources
    assert backend.provider in registry.execution_providers()

    default = _unbound_backend()
    assert default.registry is not registry
    from pacthold.work_core.registry import ExtensionRegistry
    assert isinstance(default.registry, ExtensionRegistry)


def test_without_injection_the_global_default_is_unchanged(tmp_agent_box_home):
    """Counterexample face: no injected store keeps the historical default
    byte-for-byte — the connection provider IS ``db.get_conn`` and the write
    lock IS ``db.write_lock``, and a filing resolves through the global."""
    backend = _unbound_backend()
    assert backend.store is None
    assert backend.core_repository._conn_provider is core_db.get_conn
    assert backend.core_repository._write_lock is core_db.write_lock

    work = backend.work_service.create_work("default path unchanged")
    row = core_db.get_conn().execute(
        "SELECT objective FROM core_works WHERE id = ?", (work.id,)).fetchone()
    assert row is not None and row["objective"] == "default path unchanged"


def test_build_runtime_hands_the_instance_store_to_the_execution_chain(
        tmp_path, tmp_agent_box_home):
    """Host composition end to end (host-only: no product composition, no
    legacy binding): ``host_ports["core_store"]`` rides the host wall into
    the plugin's ``TurnInputs.ports``, the composition's factory passes it on,
    and the chain's store IS ``runtime.core_binding.store``. The global stays
    ``None`` on this path — nothing configured it and nothing opened it."""
    backends = []

    def execution_factory(records, objects, approvals, notifier, _connectors,
                          _credentials, _secrets, turn_inputs):
        backend = SidecarExecutionBackend(
            records, objects, approvals, port_factory=_idle_port_factory,
            on_event=notifier.notify,
            store=_injected_core_store(turn_inputs),
        )
        backends.append(backend)
        return backend

    from pacthold_runtime_compat.storage import Database

    runtime = build_runtime(
        tmp_path / "server",
        server_plugins=[
            WorkspaceServerPlugin(),
            ServerCompatPlugin(execution_factory=execution_factory),
        ],
        database_factory=Database,
    )
    try:
        assert runtime.legacy_core is None
        runtime.start()
        assert len(backends) == 1
        backend = backends[0]
        assert callable(backend.store)
        # S1c target state: the execution chain's store IS the host's C1
        # instance store — one connection, never a second one on the file.
        assert backend.store() is runtime.core_binding.store
        assert (Path(runtime.core_binding.store_path).resolve()
                == (tmp_path / "server" / "state" / "core.sqlite").resolve())
        # the global singleton was never configured and never opened
        assert core_db._database_override is None
        assert core_db._conn is None
        # a legacy-chain filing lands in the instance store file
        work = backend.work_service.create_work("S1c instance-store filing")
        with sqlite3.connect(str(runtime.core_binding.store_path)) as conn:
            filed = conn.execute(
                "SELECT objective FROM core_works WHERE id = ?",
                (work.id,)).fetchone()
        assert filed is not None and filed[0] == "S1c instance-store filing"
    finally:
        runtime.stop()
