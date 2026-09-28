"""Shared fixtures for the Prompts plugin tests.

Deliberately *fixture-only*: no test module imports this file as a module
(``import conftest``), because the sibling domain package
(``plugins/assets/command-templates``) ships a conftest under the same
basename and both suites are collected in one pytest run by the line gate.
Everything a test needs comes from ``ordessa_prompts.*`` or from these
fixtures.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore
from ordessa_prompts.plugin import PromptsServerPlugin

from server_plugin_api import ServerPluginContext


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


class AllowProfiles:
    """Fixture stand-in for the public Profile authorisation port:
    authorises exactly the profile ids it is told to expect and records
    every call it received (so tests can prove the port — not a client
    claim — is what decided the answer)."""

    def __init__(self, allowed: "set[str] | None" = None) -> None:
        self.allowed = set(allowed or ())
        self.calls: list[tuple[str, str]] = []

    def is_authorized(self, caller_subject: str, profile_id: str) -> bool:
        self.calls.append((caller_subject, profile_id))
        return profile_id in self.allowed


class Clients:
    """Two independent Prompts clients over ONE database file: separate
    ``PromptsStore`` instances (own connections, own in-process write lock),
    separate service contexts. This is the shape a CAS race needs — a single
    store would only race the service layer, not SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.store_a = PromptsStore(path)
        self.store_b = PromptsStore(path)
        self.service_a = PromptsService(PromptRecords(self.store_a),
                                        server_scope="server-A",
                                        subject_provider=lambda: "subject-a")
        self.service_b = PromptsService(PromptRecords(self.store_b),
                                        server_scope="server-A",
                                        subject_provider=lambda: "subject-b")

    def close(self) -> None:
        self.store_a.close()
        self.store_b.close()


@pytest.fixture()
def store(tmp_path: Path) -> "PromptsStore":
    return PromptsStore(tmp_path / "prompts" / "prompts.db")


@pytest.fixture()
def records(store: PromptsStore) -> PromptRecords:
    return PromptRecords(store)


@pytest.fixture()
def library_service(store: PromptsStore) -> PromptsService:
    """The bare public-library service: no Profile authorisation port, no
    Harness, no Server internals — exactly what SC01 must survive."""
    return PromptsService(PromptRecords(store), server_scope="server-A",
                          subject_provider=lambda: "operator-1")


@pytest.fixture()
def authorized_service(store: PromptsStore) -> "tuple[PromptsService, AllowProfiles]":
    port = AllowProfiles({"alpha", "beta"})
    service = PromptsService(PromptRecords(store), server_scope="server-A",
                             subject_provider=lambda: "operator-1",
                             profile_authorization=port)
    return service, port


@pytest.fixture()
def two_clients(tmp_path: Path) -> "Clients":
    clients = Clients(tmp_path / "shared" / "prompts.db")
    try:
        yield clients
    finally:
        clients.close()


@pytest.fixture()
def db_rows():
    """``(store, sql, params) -> [row, ...]`` — raw reads for the counter-
    examples that must look *inside* the store (receipts, revision rows)."""
    def query(store: PromptsStore, sql: str, params: "tuple" = ()):
        return list(store.connection.execute(sql, params).fetchall())
    return query


@pytest.fixture()
def step_trace():
    """Run a fault-injected write at every step index of one operation.

    Returns a factory: ``trace(store, thunk) -> list[int]`` (the step indices
    a successful run executes) and ``fail_at(store, step)`` which arms
    ``PromptsStore.fault_after`` so the transaction aborts right after that
    step. The sweep is step-count agnostic on purpose: it keeps proving the
    rollback invariant when the repository adds or removes a statement.
    """
    class Tracer:
        def steps_of(self, store: PromptsStore, thunk) -> "list[int]":
            seen: list[int] = []
            store.fault_after = seen.append
            try:
                thunk()
            finally:
                store.fault_after = None
            return sorted(seen)

        def arm(self, store: PromptsStore, step: int) -> None:
            def fault(completed_step: int) -> None:
                if completed_step == step:
                    raise RuntimeError(f"injected abort after write step {step}")
            store.fault_after = fault

        def disarm(self, store: PromptsStore) -> None:
            store.fault_after = None

    return Tracer()


@pytest.fixture()
def log_capture():
    logger = logging.getLogger("ordessa.prompts")
    handler = RecordingHandler()
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


@pytest.fixture()
def plugin_registration(tmp_path: Path):
    """The built registration + a `{method_id: handler}` wire view."""
    plugin = PromptsServerPlugin(store_path=tmp_path / "wire" / "prompts.db")
    context = ServerPluginContext(
        plugin_id=PromptsServerPlugin().descriptor().id,
        data_root=tmp_path, ports={})
    registration = plugin.build(context)
    handlers = {descriptor.method_id: descriptor.handler
                for descriptor in registration.methods}
    return plugin, registration, handlers
