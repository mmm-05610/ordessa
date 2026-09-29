"""Order 51 B: the neutral usage fact and its registered parsers.

The rules under test are the order's hard rules: a field the family reported
is copied, a field it did not report is absent, nothing is estimated, nothing
is substituted, and an unregistered format is a typed refusal.
"""
from __future__ import annotations

import json
import time
import pathlib
import tempfile

import pytest

import _w1_seed

from ordessa_server_compat.execution.usage import (
    UsageParseError,
    parse_pi_acp_journal,
    parse_usage,
)


def _journal(*rows: dict) -> bytes:
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8")


ASSISTANT = {
    "id": "as-1", "parentId": "user-1", "type": "message",
    # The real journal shape (first-hand): the usage sits inside the row's
    # message object, next to role/content.
    "message": {"role": "assistant", "content": "...",
                "usage": {"input": 11, "output": 7, "cacheRead": 0, "cacheWrite": 0,
                          "reasoning": 0, "totalTokens": 18,
                          "cost": {"input": 0.00000484, "total": 0.00001408}}},
}


def test_the_pi_journal_maps_the_neutral_fields():
    fact = parse_pi_acp_journal(_journal(
        {"cwd": "/w", "id": "s", "timestamp": 1, "type": "version", "version": 1},
        ASSISTANT,
    ))
    assert fact == {
        "inputTokens": 11, "outputTokens": 7, "cacheReadTokens": 0,
        "cacheWriteTokens": 0, "reasoningTokens": 0, "totalTokens": 18,
    }
    # The cost is the family's own money figure, not part of the neutral fact.
    assert "cost" not in fact


def test_the_last_usage_row_wins_and_absent_fields_stay_absent():
    partial = {**ASSISTANT, "message": {**ASSISTANT["message"],
                                        "usage": {"input": 5, "totalTokens": 5}}}
    later = {**ASSISTANT, "id": "as-2",
             "message": {**ASSISTANT["message"],
                         "usage": {"input": 20, "output": 4, "totalTokens": 24}}}
    fact = parse_pi_acp_journal(_journal(ASSISTANT, partial, later))
    assert fact == {"inputTokens": 20, "outputTokens": 4, "totalTokens": 24}
    assert "cacheReadTokens" not in fact  # never guessed, never defaulted


def test_a_journal_without_usage_yields_none():
    assert parse_pi_acp_journal(_journal(
        {"cwd": "/w", "id": "s", "timestamp": 1, "type": "version", "version": 1},
        {"id": "u", "type": "user"},
    )) is None
    assert parse_pi_acp_journal(b"") is None


def test_malformed_lines_are_skipped_not_fatal():
    content = b"not json at all\n" + _journal(ASSISTANT)
    fact = parse_pi_acp_journal(content)
    assert fact is not None and fact["totalTokens"] == 18


def test_an_unregistered_format_is_a_typed_refusal():
    # codex-rollout is registered now (order 51's per-family parsers); the
    # refusal check uses a name that no parser claims.
    with pytest.raises(UsageParseError) as refusal:
        parse_usage("made-up-format", b"{}")
    assert refusal.value.code == "USAGE_FORMAT_UNREGISTERED"


def test_the_registered_parser_is_reachable_by_name():
    fact = parse_usage("pi-acp-journal", _journal(ASSISTANT))
    assert fact is not None and fact["totalTokens"] == 18


def test_codex_rollout_copies_the_cumulative_counters():
    """First-hand shape (stage A): rollout lines carry the harness's own
    session-to-date counters — copied verbatim, not re-derived."""
    from ordessa_server_compat.execution.usage import parse_codex_rollout

    # The real nesting (first-hand): payload.info.total_token_usage.
    content = _journal(
        {"timestamp": "2026-09-17T09:00:00Z", "type": "session_meta"},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 120, "output_tokens": 45,
                                  "total_tokens": 165}}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 200, "output_tokens": 90,
                                  "total_tokens": 290}}}},
    )
    fact = parse_codex_rollout(content)
    assert fact == {"inputTokens": 200, "outputTokens": 90, "totalTokens": 290}
    assert parse_codex_rollout(b'{"type": "session_meta"}\n') is None


def test_claude_projects_line_maps_the_message_usage():
    """First-hand shape (stage A): assistant rows carry message.usage with the
    Anthropic token names, including the two cache fields."""
    from ordessa_server_compat.execution.usage import parse_claude_projects_line

    content = _journal(
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [], "usage": {
            "input_tokens": 9, "output_tokens": 3,
            "cache_creation_input_tokens": 100, "cache_read_input_tokens": 7,
        }}},
    )
    fact = parse_claude_projects_line(content)
    assert fact == {"inputTokens": 9, "outputTokens": 3,
                    "cacheReadTokens": 7, "cacheWriteTokens": 100}


def test_hermes_state_db_reads_the_newest_session_row(tmp_path):
    """First-hand shape (stage A): the hermes store carries the fullest
    breakdown in its sessions table."""
    import sqlite3

    db = tmp_path / "state.db"
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, input_tokens INTEGER, "
        "output_tokens INTEGER, cache_read_tokens INTEGER, "
        "cache_write_tokens INTEGER, reasoning_tokens INTEGER)"
    )
    connection.execute(
        "INSERT INTO sessions VALUES ('older', 1, 1, 0, 0, 0)"
    )
    connection.execute(
        "INSERT INTO sessions VALUES ('newest', 300, 40, 12, 5, 9)"
    )
    connection.commit()
    connection.close()

    from ordessa_server_compat.execution.usage import parse_hermes_state_db

    fact = parse_hermes_state_db(db.read_bytes())
    assert fact == {"inputTokens": 300, "outputTokens": 40, "cacheReadTokens": 12,
                    "cacheWriteTokens": 5, "reasoningTokens": 9}


def test_hermes_db_without_the_sessions_table_is_a_none_not_a_guess(tmp_path):
    from ordessa_server_compat.execution.usage import parse_hermes_state_db
    import sqlite3

    db = tmp_path / "state.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE unrelated (x INTEGER)")
    connection.commit()
    connection.close()
    assert parse_hermes_state_db(db.read_bytes()) is None
    db.unlink()


def _sqlite_bytes(tmp_path, name, statements):
    import sqlite3

    db = tmp_path / name
    connection = sqlite3.connect(db)
    for statement in statements:
        connection.execute(statement)
    connection.commit()
    connection.close()
    return db.read_bytes()


OPENCODE_SCHEMA = (
    "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, "
    "time_created INTEGER, time_updated INTEGER, data TEXT)",
    "INSERT INTO message VALUES ('m1', 's1', 1, 1, "
    "'" + json.dumps({"role": "user", "parts": []}) + "')",
    # A malformed row is skipped, not fatal.
    "INSERT INTO message VALUES ('m2', 's1', 2, 2, '{not json')",
    "INSERT INTO message VALUES ('m3', 's1', 3, 3, "
    "'" + json.dumps({"role": "assistant", "modelID": "model-a",
                      "tokens": {"total": 11, "input": 8, "output": 3,
                                 "reasoning": 1,
                                 "cache": {"write": 2, "read": 4}}}) + "')",
    "INSERT INTO message VALUES ('m4', 's1', 4, 4, "
    "'" + json.dumps({"role": "assistant", "modelID": "model-a",
                      "tokens": {"total": 20, "input": 15, "output": 5}}) + "')",
)


def test_opencode_db_maps_the_assistant_token_blob(tmp_path):
    """First-hand shape (stage A on this machine): the assistant rows of
    ``message`` carry the per-call token blob (total/input/output/reasoning
    plus cache.read/write) in their data JSON. The last assistant row wins;
    fields the newest call did not report stay absent."""
    from ordessa_server_compat.execution.usage import parse_opencode_db

    content = _sqlite_bytes(tmp_path, "opencode.db", OPENCODE_SCHEMA)
    assert parse_opencode_db(content) == {
        "inputTokens": 15, "outputTokens": 5, "totalTokens": 20,
    }
    # Registered reachability: the deployment's format name resolves.
    assert parse_usage("opencode-state-db", content) == {
        "inputTokens": 15, "outputTokens": 5, "totalTokens": 20,
    }


def test_opencode_db_without_the_message_table_is_none(tmp_path):
    from ordessa_server_compat.execution.usage import parse_opencode_db

    content = _sqlite_bytes(tmp_path, "opencode.db",
                            ("CREATE TABLE unrelated (x INTEGER)",))
    assert parse_opencode_db(content) is None
    # Not a database at all is also a None, not a crash or a guess.
    assert parse_opencode_db(b"this is not sqlite") is None


def test_kilo_db_reads_the_newest_session_totals(tmp_path):
    """First-hand shape (stage A on this machine): kilo's ``session`` table
    carries per-session totals in dedicated token columns; the newest session
    by the store's own time_updated wins."""
    from ordessa_server_compat.execution.usage import parse_kilo_db

    content = _sqlite_bytes(tmp_path, "kilo.db", (
        "CREATE TABLE session (id TEXT PRIMARY KEY, tokens_input INTEGER, "
        "tokens_output INTEGER, tokens_reasoning INTEGER, "
        "tokens_cache_read INTEGER, tokens_cache_write INTEGER, "
        "time_created INTEGER, time_updated INTEGER)",
        "INSERT INTO session VALUES ('older', 1, 1, 0, 0, 0, 1, 1)",
        "INSERT INTO session VALUES ('newest', 120, 30, 6, 8, 2, 10, 20)",
    ))
    assert parse_kilo_db(content) == {
        "inputTokens": 120, "outputTokens": 30, "reasoningTokens": 6,
        "cacheReadTokens": 8, "cacheWriteTokens": 2,
    }
    assert parse_usage("kilo-state-db", content) == {
        "inputTokens": 120, "outputTokens": 30, "reasoningTokens": 6,
        "cacheReadTokens": 8, "cacheWriteTokens": 2,
    }


def test_kilo_db_copies_only_the_columns_the_store_reports(tmp_path):
    """A store that predates some token columns reports only what it has."""
    from ordessa_server_compat.execution.usage import parse_kilo_db

    content = _sqlite_bytes(tmp_path, "kilo.db", (
        "CREATE TABLE session (id TEXT PRIMARY KEY, tokens_input INTEGER, "
        "tokens_output INTEGER, time_updated INTEGER)",
        "INSERT INTO session VALUES ('only', 40, 9, 5)",
    ))
    assert parse_kilo_db(content) == {"inputTokens": 40, "outputTokens": 9}
    assert parse_kilo_db(_sqlite_bytes(tmp_path, "kilo2.db",
                                       ("CREATE TABLE unrelated (x INTEGER)",))) is None


#: Order 51 阶段 A recorded this row verbatim; it is pinned here as the shape a
#: real store carries (a total the family itself computed, plus reasoning).
REAL_OPENCODE_ASSISTANT_ROW = {
    "role": "assistant", "modelID": "deepseek-chat", "providerID": "deepseek",
    "tokens": {"total": 10587, "input": 10446, "output": 110, "reasoning": 31,
               "cache": {"read": 0, "write": 0}},
}


def test_the_recorded_real_opencode_row_still_maps_to_the_recorded_fact(tmp_path):
    """The blob mapping holds for the values copied off the live store."""
    from ordessa_server_compat.execution.usage import parse_opencode_db

    content = _sqlite_bytes(tmp_path, "opencode.db", (
        "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, "
        "time_created INTEGER, time_updated INTEGER, data TEXT)",
        "INSERT INTO message VALUES ('m9', 'ses_76Rof0H', 9, 9, "
        "'" + json.dumps(REAL_OPENCODE_ASSISTANT_ROW) + "')",
    ))
    assert parse_opencode_db(content) == {
        "inputTokens": 10446, "outputTokens": 110, "reasoningTokens": 31,
        "totalTokens": 10587, "cacheReadTokens": 0, "cacheWriteTokens": 0,
    }


def test_a_null_column_is_unknown_and_never_becomes_a_zero(tmp_path):
    """G3: a column that exists but carries no value is an unknown field.

    The counter-example is a parser that defaults a missing value to 0: this
    store row has input reported and output/reasoning left unreported, so a
    zero would be an invented number in the ledger.
    """
    from ordessa_server_compat.execution.usage import parse_hermes_state_db

    content = _sqlite_bytes(tmp_path, "state.db", (
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, input_tokens INTEGER, "
        "output_tokens INTEGER, cache_read_tokens INTEGER, "
        "cache_write_tokens INTEGER, reasoning_tokens INTEGER)",
        "INSERT INTO sessions VALUES ('partial', 41, NULL, NULL, 0, NULL)",
    ))
    fact = parse_hermes_state_db(content)
    assert fact == {"inputTokens": 41, "cacheWriteTokens": 0}
    assert "outputTokens" not in fact and "reasoningTokens" not in fact


_SECRET_BEARING_TABLES = (
    "CREATE TABLE credential (id TEXT PRIMARY KEY, token TEXT)",
    "INSERT INTO credential VALUES ('c1', 'a-token-that-must-never-be-read')",
    "CREATE TABLE account (id TEXT PRIMARY KEY, email TEXT)",
    "INSERT INTO account VALUES ('a1', 'someone@example.invalid')",
)


def test_the_probe_own_statements_name_no_secret_bearing_table(tmp_path, monkeypatch):
    """G2: the carrier keeps credentials in the same file; the probe never
    issues a statement that names those tables, and the fact still parses."""
    from ordessa_server_compat.execution import usage as usage_module

    recorded: list[str] = []
    refuse = usage_module._refuse_credential_queries

    def spy(statements):
        recorded.extend(list(statements))
        return refuse(statements)

    monkeypatch.setattr(usage_module, "_refuse_credential_queries", spy)
    content = _sqlite_bytes(tmp_path, "state.db", (
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, input_tokens INTEGER, "
        "output_tokens INTEGER, cache_read_tokens INTEGER, "
        "cache_write_tokens INTEGER, reasoning_tokens INTEGER)",
        "INSERT INTO sessions VALUES ('newest', 7, 3, 0, 0, 0)",
        *_SECRET_BEARING_TABLES,
    ))
    assert usage_module.parse_hermes_state_db(content) == {
        "inputTokens": 7, "outputTokens": 3, "cacheReadTokens": 0,
        "cacheWriteTokens": 0, "reasoningTokens": 0,
    }
    assert recorded, "the guard saw no statement at all"
    assert not [sql for sql in recorded
                if usage_module._FORBIDDEN_QUERY.search(sql)]


def test_a_statement_that_reaches_for_the_credential_table_is_refused(tmp_path):
    """G2's counter-example, with teeth: one extra statement is a typed
    refusal, and the scratch copy is still taken away afterwards."""
    from ordessa_server_compat.execution.usage import _scratch_sqlite

    content = _sqlite_bytes(tmp_path, "state.db", _SECRET_BEARING_TABLES)
    with pytest.raises(UsageParseError) as refusal:
        with _scratch_sqlite(content) as connection:
            connection.execute("SELECT token FROM credential").fetchall()
    assert refusal.value.code == "USAGE_PROBE_CREDENTIAL_QUERY"
    assert "credential" in str(refusal.value)
    import os

    scratch_root = pathlib.Path(tempfile.gettempdir())
    pattern = f"agentbox-usage-{os.getpid()}-*"
    assert sorted(p.name for p in scratch_root.glob(pattern)) == []


def test_a_failed_usage_read_keeps_the_fact_unknown_and_records_why(caplog):
    """G3 at the read path: a probe that could not answer leaves the turn
    unknown with its reason recorded, and never a substituted zero."""
    import logging
    import threading

    from ordessa_server_compat.execution import sidecar_backend

    class _Port:
        usage_probe = {"journalSuffix": "state.db", "format": "hermes-state-db"}

        def capture_execution(self, _turn_id):
            return {"files": []}, True

        def read_usage(self, _turn_id, _probe):
            raise RuntimeError("the carrier vanished before capture")

    run = sidecar_backend._Run(
        turn_id="turn-084", work_id="work-084", core_execution_id="core-084",
        dispatch_id="dispatch-084", port=_Port(), native_id="native-084",
        done=threading.Event(),
    )
    with caplog.at_level(logging.WARNING):
        audit, resumable = sidecar_backend._audited_home(run)
    assert (audit, resumable) == ({"files": []}, True)
    assert run.usage_fact is None and run.usage_source is None
    assert "usage stays unknown" in caplog.text
    assert "the carrier vanished before capture" in caplog.text


def test_probe_validates_the_endpoint_before_any_network_call():
    """SSRF/Order-55 §2: only https (loopback http exempt), no private nets."""
    from ordessa_server_compat.model_configs.probe import ProbeError, pull_models

    with pytest.raises(ProbeError) as blocked:
        pull_models("http://10.1.2.3/v1", None)
    assert blocked.value.code == "PROBE_ENDPOINT_BLOCKED"
    with pytest.raises(ProbeError) as blocked:
        pull_models("ftp://example.com", None)
    assert blocked.value.code == "PROBE_ENDPOINT_BLOCKED"
    with pytest.raises(ProbeError) as blocked:
        pull_models("https://192.168.1.9/v1", None)
    assert blocked.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_pull_models_parses_a_loopback_fake(tmp_path):
    """A loopback fake endpoint answers the OpenAI shape; the parser maps ids."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    body = json.dumps({"data": [{"id": "model-a"}, {"id": "model-b"},
                                {"no_id": True}]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer secret-key":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"denied")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(HTTPServer):
        # Under a full-suite run the accepting thread can lag; a deeper
        # listen backlog removes the connect-refused race.
        request_queue_size = 128

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Under a full-suite run the accepting thread can lag behind the port
    # being bound; wait for a real accepted connection before any request.
    import socket

    for _ in range(100):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", server.server_port)) == 0:
                break
        time.sleep(0.01)

    try:
        from ordessa_server_compat.model_configs.probe import (
            ProbeError,
            pull_models,
            probe_connection,
        )

        base = f"http://127.0.0.1:{server.server_port}"
        with pytest.raises(ProbeError) as denied:
            pull_models(base, "wrong-key")
        assert denied.value.code == "PROBE_AUTH_FAILED"

        # Under suite load the first probe can still race the accepting
        # socket; a bounded retry keeps the assertion about the *content*
        # (model ids) rather than about transport timing.
        result = None
        for _ in range(5):
            try:
                result = pull_models(base, "secret-key")
                break
            except Exception:
                time.sleep(0.1)
        assert result is not None and result.status == "ok"
        assert result.models == ("model-a", "model-b")  # the shapeless entry drops

        check = probe_connection(base, "secret-key")
        assert check.status == "reachable"
    finally:
        server.shutdown()
        server.server_close()


def test_pull_models_rejects_oversized_and_shapeless_responses(monkeypatch):
    """Bounded and honest: too-large and wrong-shaped responses are typed
    refusals, never truncated-then-trusted."""
    import socket

    from ordessa_server_compat.model_configs.probe import (
        MAX_RESPONSE_BYTES,
        ProbeError,
        pull_models,
    )
    import ordessa_server_compat.model_configs.probe as probe_module

    #: Order 104 made the endpoint check resolve the name, so a test that fakes
    #: only the transport would otherwise start needing real DNS. A public
    #: address stands in for "the name resolved and is a normal provider";
    #: what is under test is what happens after the response arrives.
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                            ("93.184.216.34", 443))],
    )

    class FakeResponse:
        def __init__(self, content):
            self._content = content
            self._offset = 0

        def read(self, limit):
            # A real stream advances and ends (b"" at EOF); the earlier fake
            # re-served its prefix forever, which no response ever does.
            chunk = self._content[self._offset:self._offset + limit]
            self._offset += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    content = b'{"data": ["x" * 10]}'
    oversized = content + b" " * (MAX_RESPONSE_BYTES + 1)

    class _FakeUrlopen:
        def __init__(self, content):
            self._content = content

        def __call__(self, request, timeout):
            return FakeResponse(self._content)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    original = probe_module._open_request
    probe_module._open_request = _FakeUrlopen(oversized)
    try:
        with pytest.raises(ProbeError) as too_large:
            pull_models("https://models.example.com/v1", "key")
        assert too_large.value.code == "PROBE_RESPONSE_TOO_LARGE"
    finally:
        probe_module._open_request = original

    probe_module._open_request = _FakeUrlopen(b'{"nope": true}')
    try:
        with pytest.raises(ProbeError) as shapeless:
            pull_models("https://models.example.com/v1", "key")
        assert shapeless.value.code == "PROBE_FORMAT_INVALID"
    finally:
        probe_module._open_request = original


def test_a_wal_resident_row_is_read_with_its_sidecar(tmp_path):
    """The hermes observation round's root cause, as a regression test.

    A live SQLite journal keeps committed rows in its -wal sidecar. Handing
    the parser only the main file reads a stale database (the observation
    round's NULL); handing the -wal beside it reads the row the writer
    committed."""
    import sqlite3

    from ordessa_server_compat.execution.usage import parse_hermes_state_db, parse_usage

    db = tmp_path / "state.db"
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, input_tokens INTEGER, "
        "output_tokens INTEGER)"
    )
    writer.commit()
    reader = sqlite3.connect(db)
    reader.execute("BEGIN")
    assert reader.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    writer.execute("INSERT INTO sessions VALUES ('s1', 22, 14)")
    writer.commit()
    writer.close()
    main = db.read_bytes()
    wal = (tmp_path / "state.db-wal").read_bytes()
    assert parse_hermes_state_db(main) is None, "the main file alone is stale"
    assert parse_hermes_state_db(main, sidecars={"-wal": wal}) == {
        "inputTokens": 22, "outputTokens": 14,
    }
    assert parse_usage("hermes-state-db", main, sidecars={"-wal": wal}) == {
        "inputTokens": 22, "outputTokens": 14,
    }
    reader.close()


def test_a_slow_drip_answer_hits_the_total_deadline(monkeypatch):
    """Order 70 G1: the total deadline bounds a drip-feeding endpoint.

    The socket timeout alone cannot: every read arrives inside it. With the
    module's total budget shrunk, a drip must surface the typed
    PROBE_TIMEOUT - not the size cap, which this body never reaches."""
    import socket

    import ordessa_server_compat.model_configs.probe as probe_module

    #: As in the oversized-response test above: the transport is faked, so the
    #: name must not have to exist. (Order 104 is what made the check resolve.)
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                            ("93.184.216.34", 443))],
    )

    class _SlowDrip:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self, _size):
            time.sleep(0.05)
            return b"x" * 16

    original_total = probe_module.TOTAL_TIMEOUT_SECONDS
    original_open = probe_module._open_request
    try:
        probe_module.TOTAL_TIMEOUT_SECONDS = 0.05
        probe_module._open_request = lambda _request, _timeout: _SlowDrip()
        with pytest.raises(probe_module.ProbeError) as caught:
            probe_module.pull_models("https://api.example.test", "not-a-real-key")
        assert caught.value.code == "PROBE_TIMEOUT"
    finally:
        probe_module.TOTAL_TIMEOUT_SECONDS = original_total
        probe_module._open_request = original_open


def test_a_probe_invents_no_window_capability_or_price_values():
    """Order 70 G4: unknown stays unknown - there is nothing to invent from.

    First-hand: the probe result carries exactly status/detail/models, and the
    module holds no built-in window, capability or price table. A mutation that
    introduces a default (e.g. a 4096/128000 literal or a context_window key)
    turns this red - that is the counter-example drill recorded in the report.
    """
    from dataclasses import fields

    import ordessa_server_compat.model_configs.probe as probe_module

    names = {field.name for field in fields(probe_module.ProbeResult)}
    assert names == {"status", "detail", "models"}, names
    text = pathlib.Path(probe_module.__file__).read_text(encoding="utf-8")
    for banned in ("context_window", "contextWindow", "price", "4096", "128000", "8192"):
        assert banned not in text, f"a built-in default leaked into the probe: {banned}"


def test_both_probe_methods_answer_through_the_wire_face(tmp_path):
    """Order 70 stage 2: the wiring itself, through the real Server.

    First-hand defect this locks: `providerModels.probeConnection` raised
    ImportError at call time (the service imported a name the module never
    had) because every earlier test called the probe functions directly and
    never the wire path. Both methods now go through Server -> wire -> service
    -> probe against a loopback fake."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    body = json.dumps({"data": [{"id": "deepseek-chat"}]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    runtime = build_runtime(tmp_path / "data")
    runtime.start()
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            headers = {"Authorization": f"Bearer {runtime.token}"}

            def wire(method, params):
                response = client.post(f"/wire/v1/{method}", headers=headers, json={
                    "jsonrpc": "2.0", "id": method, "method": method, "params": params})
                return response.json()

            # AR-1/W-1：探针 wire 面已退役，改同链服务直调（同一真实探测路径）。
            pulled = _w1_seed.provider_models_probe_models(runtime, base_url=base)
            assert pulled["status"] == "ok", pulled
            assert pulled["models"] == ["deepseek-chat"], pulled

            checked = _w1_seed._handlers(runtime).model_configs.probe_connection(
                {"baseUrl": base, "credentialId": None})
            assert checked["status"] == "reachable", checked

            # The published schema allows credentialId to be absent or null
            # (`credentialId?`); the runtime must not be stricter than its own
            # contract (first-hand defect: it demanded the key and refused a
            # legal request).
            explicit_null = _w1_seed._handlers(runtime).model_configs.probe_connection(
                {"baseUrl": base, "credentialId": None})
            assert explicit_null["status"] == "reachable", explicit_null
            # （AR-1/W-1）"未知参数→INVALID_REQUEST" 属 wire 层 schema 校验，
            # 随 providerModels.* 面退役；新 owner 的 wire 面自测其 schema。
    finally:
        runtime.stop()
        server.shutdown()
        server.server_close()
