"""T023 (SC-006): no fixture state may touch the real home.

Every T023 root is under ``tmp_path``/``/tmp`` by construction; this file is
the guard that makes the claim bite. It runs the T023 legacy-data fixture
sequence with ``AGENT_BOX_HOME`` pointing at an empty canary directory (the
exact env the historical leak symptom went through, see
``pacthold.work_core.runtime.agent_box_home``): any code path that opens the
kernel database WITHOUT the host binding an instance store — i.e.
`db.get_conn()` on the default — writes into the canary, and these tests then
fail.

026 T006-01 (second half) upgraded the rebinding audit: the host no longer
configures the process-global kernel DB AT ALL (``LegacyCoreBinding`` opens
the round's own instance connection), so the audit demands ZERO
``configure_database`` calls across a whole round, plus the instance-side
equivalent facts — every product round held its OWN legacy binding, on a
scratch path, whose connection really resolves to that scratch file.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

import test_platform_t023_legacy_data as t023_fixture

from ordessa_server.bootstrap import build_runtime
from ordessa_server.bootstrap import runtime as bootstrap_runtime
from ordessa_server.transport.http import create_app
from pacthold.work_core import db as core_db


def _run_a_full_t023_round(tmp_path: Path) -> None:
    """The same byte sequence every T023 legacy-data test performs."""
    old_root = t023_fixture.synthesize_historical_root(
        tmp_path, "sc006-old", through_version=9)
    t023_fixture.open_serve_and_stop(old_root, rounds=2)
    fresh = tmp_path / "sc006-new"
    t023_fixture.open_serve_and_stop(fresh, rounds=1)
    assert t023_fixture.legacy_versions(old_root) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_all_t023_fixture_roots_are_constructed_under_the_scratch_area(tmp_path):
    """Structural half of SC-006: the shared fixture helper refuses to build
    anywhere else — a name outside tmp_path is a hard failure, not a note."""
    _run_a_full_t023_round(tmp_path)
    built = sorted(p.name for p in tmp_path.iterdir())
    assert {"sc006-old", "sc006-new"} <= set(built), built
    for root in (tmp_path / "sc006-old", tmp_path / "sc006-new"):
        assert t023_fixture._under(root.resolve(), tmp_path.resolve())


def test_the_agent_box_home_canary_stays_empty_through_a_full_round(
        tmp_path, monkeypatch):
    """Leak counterexample: with AGENT_BOX_HOME redirected to an empty canary
    directory, a complete open/serve/restart round must leave it EMPTY. The
    historical defect this guards (test_stage_a_server's home-file symptom)
    created `agent-box.db` under exactly this env; one byte there now is a
    red, not a warning."""
    canary = tmp_path / "home-canary"
    monkeypatch.setenv("AGENT_BOX_HOME", str(canary))
    _run_a_full_t023_round(tmp_path)
    leaked = sorted(os.listdir(canary)) if canary.exists() else []
    assert leaked == [], f"fixture state escaped into the legacy home: {leaked}"


def test_no_round_configures_the_global_kernel_db_and_instance_bindings_are_scratch(
        tmp_path, monkeypatch):
    """The rebinding audit, upgraded (026 T006-01 second half): wrap the
    kernel's ``configure_database`` AND the host's ``LegacyCoreBinding`` for
    a whole round and demand
    - ZERO configure calls — any startup path handing the kernel module a
      home path is a red, even if the canary env happened to be unset;
    - the instance-side equivalent facts: every product round built its OWN
      legacy binding on a scratch path, and after ``connect()`` that
      binding's own connection resolves (``PRAGMA database_list``) to that
      scratch file — the fact the old audit checked through the global."""
    recorded: list[Path] = []
    original = core_db.configure_database

    def spy(path):
        # forwards, so a regression behaves exactly like the code it replaced
        # and the zero-call assertion below names it precisely
        recorded.append(None if path is None else Path(path).resolve())
        return original(path)

    monkeypatch.setattr(core_db, "configure_database", spy)

    instance_paths: list[Path] = []
    instance_targets: list[Path] = []
    original_binding = bootstrap_runtime.LegacyCoreBinding

    class ObservedLegacyBinding(original_binding):
        def __init__(self, database_path):
            super().__init__(database_path)
            instance_paths.append(Path(database_path).resolve())

        def connect(self):
            super().connect()
            row = self.connection.execute("PRAGMA database_list").fetchone()
            instance_targets.append(Path(row[2]).resolve())

    monkeypatch.setattr(bootstrap_runtime, "LegacyCoreBinding", ObservedLegacyBinding)
    monkeypatch.setenv("AGENT_BOX_HOME", str(tmp_path / "home-canary-audit"))
    _run_a_full_t023_round(tmp_path)
    # the global kernel DB was never configured, by any startup path
    assert recorded == [], (
        f"a startup path configured the process-global kernel DB: {recorded}")
    # non-vacuity: the rounds DID hold instance bindings (the spy is not blind)
    assert instance_paths, "no legacy binding was built — the instance spy is blind"
    scratch = tmp_path.resolve()
    strays = [p for p in instance_paths if not t023_fixture._under(p, scratch)]
    assert strays == [], f"legacy binding bound outside the scratch area: {strays}"
    # and each round's own connection really resolved to its scratch file
    assert instance_targets == instance_paths, (
        f"instance legacy connections resolved off their own files: "
        f"{list(zip(instance_paths, instance_targets))}")


def test_the_served_token_never_leaves_its_own_root(tmp_path):
    """SC-006 covering the credential half: the bearer token the loopback
    authenticates with is the per-root file under state/../secrets, and a
    second root mints a different one — no shared home-level secret."""
    root_a = tmp_path / "token-a"
    root_b = tmp_path / "token-b"
    runtime = build_runtime(root_a)
    try:
        runtime.start()
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        answer = client.get("/live")
        assert answer.status_code == 200, answer.text
        assert runtime.token_path.parent == root_a / "secrets"
    finally:
        runtime.stop()
    second = build_runtime(root_b)
    try:
        assert second.token != runtime.token
    finally:
        second.stop()
