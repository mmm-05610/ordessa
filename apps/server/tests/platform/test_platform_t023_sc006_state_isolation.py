"""T023 (SC-006): no fixture state may touch the real home.

Every T023 root is under ``tmp_path``/``/tmp`` by construction; this file is
the guard that makes the claim bite. It runs the T023 legacy-data fixture
sequence with ``AGENT_BOX_HOME`` pointing at an empty canary directory (the
exact env the historical leak symptom went through, see
``pacthold.work_core.runtime.agent_box_home``): any code path that opens the
kernel database WITHOUT the host rebinding — i.e. `db.get_conn()` on the
default — writes into the canary, and these tests then fail. It also records
every ``configure_database`` target during a full round and demands it stays
inside the scratch area.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

import test_platform_t023_legacy_data as t023_fixture

from ordessa_server.bootstrap import build_runtime
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


def test_every_configure_database_target_is_a_scratch_path(tmp_path, monkeypatch):
    """The rebinding itself is audited: wrap the kernel's configure_database
    and demand every non-None target live under tmp_path for a whole round —
    a host that ever hands the kernel a home path fails here even if the
    canary env happened to be unset."""
    recorded: list[Path] = []
    original = core_db.configure_database

    def spy(path):
        if path is not None:
            recorded.append(Path(path).resolve())
        return original(path)

    monkeypatch.setattr(core_db, "configure_database", spy)
    monkeypatch.setenv("AGENT_BOX_HOME", str(tmp_path / "home-canary-audit"))
    _run_a_full_t023_round(tmp_path)
    assert recorded, "the round never bound the kernel DB — the spy is blind"
    strays = [p for p in recorded if not t023_fixture._under(p, tmp_path.resolve())]
    assert strays == [], f"kernel DB bound outside the scratch area: {strays}"


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
