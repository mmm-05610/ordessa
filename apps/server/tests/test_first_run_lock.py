"""Order 80: the per-library first-run lock (order 66's measured cold start).

First-hand (order 66's real-harness race, 2026-09-18): a fresh shared library
plus two concurrent *first* runs with the real OpenCode binary fails 6/7
(`database is locked` and one workspace foreign-key race, exit 1 in ~0.7 s),
while concurrency after initialisation is 3/3 green. The lock serialises only
that creation window: the first run is exclusive, everyone else passes through
once it reached its terminal.

The three layers under test:

1. the gate itself - exclusive first run, bounded wait, typed timeout;
2. the Server wiring - two Profiles' first turns on one fresh library do not
   overlap, and bypassing the gate makes them overlap again (counter-example);
3. the real harness - seven cold two-process races with the real OpenCode
   binary stay green with the gate (skipped when the binary is absent).
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time

import pytest

from ordessa_server_compat.execution.first_run_lock import (
    FirstRunGate,
    FirstRunLockTimeout,
    first_run_gate,
)

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _shared_store_tests():
    """Order 66's test module, by path: its runtime builder, peer deployment
    and wire helpers are exactly the fixture face this order's gate reuses
    (pytest test modules are not an importable package)."""
    spec = importlib.util.spec_from_file_location(
        "shared_store_tests", HERE / "test_shared_session_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# 1. the gate itself
# --------------------------------------------------------------------------

def test_the_first_run_is_exclusive_and_everything_after_passes_through():
    gate = FirstRunGate(wait_seconds=5.0)
    hold = gate.acquire("local:kilo")
    assert hold is not None, "the first caller must own the library"
    assert gate.in_flight("local:kilo")

    waited: list[float] = []

    def second():
        started = time.monotonic()
        assert gate.acquire("local:kilo") is None
        waited.append(time.monotonic() - started)

    thread = threading.Thread(target=second)
    thread.start()
    time.sleep(0.2)
    assert thread.is_alive(), "the second first-run must wait for the owner"
    hold.release()
    thread.join(5.0)
    assert not thread.is_alive()
    assert waited and waited[0] >= 0.15, waited
    assert not gate.in_flight("local:kilo")
    # Ready: the next acquisition passes through immediately, and idempotent
    # releases are what every exit path may call.
    hold.release()
    assert gate.acquire("local:kilo") is None


def test_a_wait_that_expires_is_a_typed_failure_not_a_silent_entry():
    gate = FirstRunGate(wait_seconds=0.05)
    hold = gate.acquire("local:kilo")
    try:
        with pytest.raises(FirstRunLockTimeout) as caught:
            gate.acquire("local:kilo")
        assert caught.value.code == "FIRST_RUN_LOCK_TIMEOUT"
        assert "local:kilo" in str(caught.value)
    finally:
        hold.release()


# --------------------------------------------------------------------------
# 2. the Server wiring, through the real runtime
# --------------------------------------------------------------------------

def _two_profile_first_runs(tmp_path, *, prompt_prefix: str) -> list[tuple[str, int, int]]:
    """Two Profiles' first turns on one fresh whole-db library, at once.

    Returns the peer-recorded (label, start, end) spans; the peer writes them
    into the shared `windows.txt`, which is the one artifact both rooms see.
    """
    from fastapi.testclient import TestClient

    from ordessa_server.transport.http import create_app

    shared = _shared_store_tests()
    first_run_gate().reset()
    deployment = json.loads(json.dumps(shared.G1_DEPLOYMENT))
    deployment["harnesses"][0]["sessionStore"]["shared"].append(
        {"name": "windows.txt", "kind": "file"})
    runtime, data_root = shared._build_whole_db_runtime(
        tmp_path, deployment, shared.STATEFUL_PEER_SOURCE, shared.STATEFUL_PEER_BYTES)
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token
        opened = shared._wire(client, token, "workspaces.open", {
            "requestId": "first-run-open", "path": str(tmp_path / "project"),
            "environment": {"kind": "local", "host": None, "user": None},
        })["result"]
        profiles = {}
        for name in ("role-a", "role-b"):
            created = client.post("/api/v1/profiles", headers={
                "Authorization": f"Bearer {token}", "Idempotency-Key": f"first-run-{name}",
            }, json={"name": name, "harness_type": "kilo",
                     "configuration": {}, "credential_id": None})
            profiles[name] = created.json()["profile_id"]

        started: dict[str, dict] = {}
        errors: list[str] = []

        def send(name: str) -> None:
            try:
                started[name] = shared._wire(client, token, "sessions.createAndSend", {
                    "requestId": f"first-run-{name}", "workspaceId": opened["workspace"]["id"],
                    "profileId": profiles[name], "overrides": [],
                    "message": {"text": f"{prompt_prefix}{name} hold-for-window",
                                "attachments": []},
                })["result"]
            except BaseException as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")

        threads = [threading.Thread(target=send, args=(name,))
                   for name in ("role-a", "role-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == [], errors
        for name, value in started.items():
            session = shared._wait_session(runtime, value["session"]["id"], 1, timeout=60.0)
            assert session["turns"][0]["state"] == "completed", (name, session["turns"][0])

    windows = (data_root / "profiles" / "_sessions" / "kilo" / "windows.txt").read_text()
    spans: dict[str, list[int]] = {}
    for line in windows.splitlines():
        edge, label, stamp = line.split(":")
        spans.setdefault(label, []).append(int(stamp))
    return [(label, min(marks), max(marks)) for label, marks in spans.items()]


def _overlap(spans: list[tuple[str, int, int]]) -> bool:
    (_, start_a, end_a), (_, start_b, end_b) = spans
    return start_a < end_b and start_b < end_a


class _Section:
    """One trip through the guard's seam; `release` is what the Server calls."""

    def __init__(self, spy: "_SeamSpy", hold):
        self._spy = spy
        self._hold = hold

    def release(self) -> None:
        self._spy.leave(self._hold)


class _SeamSpy:
    """Count how many first-runs are inside the creation window at once.

    Order 119 replaced the wall-clock judge with this one: an interval
    comparison can only see an overlap that happened to occur, so a loaded
    machine turned the counter-example red without any product change (`QA-011`).
    `events` is program order under a lock and `peak` is the maximum number of
    sections open simultaneously, so the verdict is a property of the code path.

    `hold_first_open` (bypass leg) keeps the first section open until a second
    one arrives - the overlap is produced, not sampled.
    `defer_second_until_first_left` (the reproduction leg) does the opposite: it
    models a machine that scheduled the second run after the first finished,
    which is exactly the condition that made the old judge lie.
    """

    def __init__(self, *, bypass: bool, hold_first_open: bool = False,
                 defer_second_until_first_left: bool = False):
        self.bypass = bypass
        self.hold_first_open = hold_first_open
        self.defer_second = defer_second_until_first_left
        self.inner = None if bypass else first_run_gate()
        self.mu = threading.Lock()
        self.events: list[str] = []
        self.consults = 0
        self.inside = 0
        self.peak = 0
        self.second_arrived = threading.Event()
        self.first_left = threading.Event()

    def acquire(self, key):
        with self.mu:
            self.consults += 1
        if self.defer_second and not self.first_left.wait(timeout=60):
            raise AssertionError("the first first-run never finished - not a load question")
        hold = None if self.inner is None else self.inner.acquire(key)
        with self.mu:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            self.events.append("in")
            if self.inside >= 2:
                self.second_arrived.set()
        return _Section(self, hold)

    def leave(self, hold) -> None:
        if hold is not None:
            hold.release()
        # The forcing goes here, not inside `acquire`: the guard's seam is on the
        # dispatcher thread, so waiting in `acquire` would block the very
        # dispatch that has to bring the second run in (measured that way - the
        # first version of this spy deadlocked and timed out at 60 s). Leaving is
        # what the run's own completion thread does, so holding it open forces
        # the overlap without serialising anything.
        with self.mu:
            waiting = self.hold_first_open and self.inside == 1 and not self.second_arrived.is_set()
        if waiting:
            # A liveness bound, never the judge: if no partner shows up, the
            # product serialised the two runs by itself and this leg has to say
            # so loudly instead of quietly passing.
            assert self.second_arrived.wait(timeout=60), (
                "the second first-run never entered while the first was inside, even "
                "with the guard bypassed - investigate before trusting this green")
        with self.mu:
            self.inside -= 1
            self.events.append("out")
            if self.inside == 0:
                self.first_left.set()


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_two_profiles_first_runs_do_not_overlap_through_the_server(tmp_path):
    """Order 80 G1, at the Server: the lock serialises the creation window."""
    spans = _two_profile_first_runs(tmp_path, prompt_prefix="window:")
    assert len(spans) == 2, spans
    assert not _overlap(spans), spans
    assert not first_run_gate().in_flight("local:kilo")


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_without_the_gate_the_same_first_runs_overlap(tmp_path, monkeypatch):
    """The gate's counter-example, judged by program order (order 119).

    Order 80 wrote this as a comparison of wall-clock intervals, so a busy
    machine could push the two windows apart and turn "the guard is what
    serialises them" into a false red - `QA-011` measured exactly that
    (5 passed isolated, 1 failed under eight busy loops, same sha). The judge
    here is the seam the Server actually uses: how many first-runs were inside
    the creation window at once, read off an ordered event log. The overlap is
    *produced* (the bypassed first section stays open until a second arrives)
    instead of sampled, so no amount of machine load can make it go away.
    """
    import ordessa_server_compat.execution.sidecar_backend as backend_module

    spy = _SeamSpy(bypass=True, hold_first_open=True)
    monkeypatch.setattr(backend_module, "first_run_gate", lambda: spy)
    spans = _two_profile_first_runs(tmp_path, prompt_prefix="window:")
    assert len(spans) == 2, spans
    assert spy.consults == 2, spy.events
    assert spy.peak == 2, spy.events
    assert spy.events == ["in", "in", "out", "out"], spy.events


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_the_guard_keeps_one_first_run_inside_the_window_at_a_time(tmp_path, monkeypatch):
    """The positive half, load-free: the guard is on the path, and it never has
    two exclusive sections open. `Order 80 G1` above still compares timestamps,
    which can only be wrong in the safe direction - this cannot be wrong at all
    by timing, and it is what bites if the product stops consulting the guard
    (`consults` falls to 0, which no clock-based reading would ever notice).
    """
    import ordessa_server_compat.execution.sidecar_backend as backend_module

    spy = _SeamSpy(bypass=False)
    monkeypatch.setattr(backend_module, "first_run_gate", lambda: spy)
    spans = _two_profile_first_runs(tmp_path, prompt_prefix="window:")
    assert len(spans) == 2, spans
    assert spy.consults == 2, spy.events
    assert spy.peak == 1, spy.events
    assert spy.events == ["in", "out", "in", "out"], spy.events


def test_the_old_judge_was_a_function_of_timing_not_of_the_product():
    """QA-011's false red, made deterministic instead of by machine load.

    Two clock shapes of *one* product outcome ("the guard was not consulted and
    nothing serialised the two runs"): an idle machine reported them as
    overlapping, a busy one would not. `_overlap` reads only the numbers, so its
    verdict about the product flips with the scheduler. The seam judge reads
    event order, and `hold_first_open` makes the overlap happen instead of
    waiting to catch it - so repeated runs cannot disagree.

    The historical experiment (needs CPU burners, so it is a command here rather
    than a test - `QA-011` ran it on the pre-119 file):

        for i in 1 2 3 4 5 6 7 8; do (timeout 240 python3 -c 'while True: pass' &) ; done
        python3 -m pytest tests/server/test_first_run_lock.py -q   # 1 failed, 4 passed
        python3 -m pytest tests/server/test_first_run_lock.py -q   # isolated: 5 passed
    """
    separated = [("role-a", 0, 5), ("role-b", 10, 15)]
    together = [("role-a", 0, 12), ("role-b", 10, 15)]
    assert _overlap(together) and not _overlap(separated), "the judge keyed on the clock"

    spy = _SeamSpy(bypass=True, hold_first_open=True)
    for _attempt in range(3):
        first = spy.acquire("local:kilo")
        second = spy.acquire("local:kilo")
        first.release()
        second.release()
    assert spy.peak == 2, spy.events
    assert spy.events == ["in", "in", "out", "out"] * 3, spy.events


def test_the_new_judges_never_reach_for_the_clock():
    """G3 (order 119): the verdict must be a property of the code path.

    A scan of this file's own text is enough here because the thing being
    forbidden is a *kind* of judgement - `time.sleep`, or an interval comparison
    in a gate that is supposed to be falsifiable about the product.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    spy_block = source[source.index("class _Section:"):source.index(
        "@pytest.mark.skipif", source.index("class _SeamSpy:"))]
    assert "time.sleep" not in spy_block, "the seam spy started measuring time"
    for name in ("test_without_the_gate_the_same_first_runs_overlap",
                 "test_the_guard_keeps_one_first_run_inside_the_window_at_a_time"):
        body = source.split(f"def {name}(", 1)[1].split("\n\n\n", 1)[0]
        assert "time.sleep" not in body, name
        assert "_overlap(" not in body, f"{name} went back to comparing intervals"
        assert "spy.peak" in body and "spy.events" in body, name


# --------------------------------------------------------------------------
# 3. the real harness: seven cold races, gated
# --------------------------------------------------------------------------

#: Fixed, obviously fake, never a credential.
FAKE_TOKEN = "first-run-gate-fake-token-non-secret"
OPENCODE = shutil.which("opencode")


def _config_document(base_url: str) -> dict:
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "deepseek": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "DeepSeek official (loopback fake)",
                "options": {"baseURL": base_url, "apiKey": FAKE_TOKEN},
                "models": {"deepseek-flash": {
                    "name": "DeepSeek Flash (bounded acceptance)",
                    "reasoning": False,
                    "options": {"thinking": {"type": "disabled"}},
                    "limit": {"context": 1000, "output": 64},
                }},
            },
        },
    }


class _FakeEndpoint:
    """The smallest loopback OpenAI stream that lets `opencode run` finish."""

    def __init__(self) -> None:
        endpoint = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:
                pass

            def _chunk(self, payload: bytes) -> None:
                self.wfile.write(f"{len(payload):X}\r\n".encode() + payload + b"\r\n")
                self.wfile.flush()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                body = json.dumps({"id": "c", "object": "chat.completion.chunk",
                                   "choices": [{"index": 0, "delta": {"role": "assistant"},
                                                "finish_reason": None}]})
                self._chunk(f"data: {body}\n\n".encode())
                for word in ("FIRST", "RUN", "ACK"):
                    body = json.dumps({"id": "c", "object": "chat.completion.chunk",
                                       "choices": [{"index": 0, "delta": {"content": word + " "},
                                                    "finish_reason": None}]})
                    self._chunk(f"data: {body}\n\n".encode())
                    time.sleep(0.02)
                body = json.dumps({"id": "c", "object": "chat.completion.chunk",
                                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 3, "completion_tokens": 3,
                                             "total_tokens": 6}})
                self._chunk(f"data: {body}\n\n".encode())
                self._chunk(b"data: [DONE]\n\n")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()


def _run_opencode(root: pathlib.Path, project: pathlib.Path, config: pathlib.Path,
                  prompt: str, timeout: float = 120.0) -> dict:
    environment = dict(os.environ)
    environment.update({
        "HOME": str(root / "home"), "XDG_DATA_HOME": str(root / "data"),
        "XDG_CONFIG_HOME": str(root / "config"), "OPENCODE_CONFIG": str(config),
        "OPENCODE_DISABLE_AUTOUPDATE": "1", "PWD": str(project),
    })
    result = subprocess.run(
        [OPENCODE, "run", prompt, "--model", "deepseek/deepseek-flash"],
        cwd=project, env=environment, capture_output=True, text=True, timeout=timeout)
    return {"exit": result.returncode, "stderr": (result.stderr or "")[-2000:]}


@pytest.mark.skipif(
    OPENCODE is None or shutil.which("bwrap") is None,
    reason="the real opencode binary and bwrap are required")
def test_seven_cold_library_first_run_races_stay_green_with_the_gate(tmp_path):
    """Order 80 G1: the measured 6/7 failure becomes 7/7 under the gate.

    The gate is the product's own primitive; the racers are the real OpenCode
    binary, two processes, one fresh library, seven times. The counter-example
    (the same shape with the gate bypassed still fails) is order 66's gate,
    which is lock-free by construction - re-run by the report, not here, so a
    designed-to-fail case never flakes this suite.
    """
    root = tmp_path / "run"
    (root / "project-a").mkdir(parents=True)
    (root / "project-b").mkdir(parents=True)
    for name in ("home", "config"):
        (root / name).mkdir()

    with _FakeEndpoint() as endpoint:
        config = root / "opencode.json"
        config.write_text(json.dumps(_config_document(endpoint.base_url)), encoding="utf-8")
        warm = _run_opencode(root, root / "project-a", config, "order 80 warm-up")
        assert warm["exit"] == 0, warm

        failures: list[dict] = []
        for iteration in range(7):
            # A fresh library per iteration is a fresh first run: the gate is
            # per library, so it is rebuilt here (a state the product reaches
            # when a data root is recreated).
            gate = FirstRunGate(wait_seconds=120.0)
            library = root / "data" / "opencode"
            library.mkdir(parents=True, exist_ok=True)
            for name in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
                candidate = library / name
                if candidate.exists():
                    candidate.unlink()
            (library / "opencode.db").write_bytes(b"")
            snapshot = library / "snapshot"
            if snapshot.exists():
                shutil.rmtree(snapshot)

            results: dict[str, dict] = {}

            def race(name: str, project: pathlib.Path) -> None:
                hold = gate.acquire("opencode:cold-start")
                try:
                    results[name] = _run_opencode(
                        root, project, config, f"order 80 iteration {iteration} {name}")
                finally:
                    if hold is not None:
                        hold.release()

            threads = [
                threading.Thread(target=race, args=("alpha", root / "project-a")),
                threading.Thread(target=race, args=("bravo", root / "project-b")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            for name, result in results.items():
                if result["exit"] != 0 or "database is locked" in result["stderr"]:
                    failures.append({"iteration": iteration, "name": name, **result})
        assert failures == [], failures

        import sqlite3

        connection = sqlite3.connect(f"file:{root / 'data/opencode/opencode.db'}?mode=ro", uri=True)
        try:
            projects = connection.execute("select id, worktree from project").fetchall()
            duplicates = connection.execute(
                "select count(*) - count(distinct project_id || ':' || directory) "
                "from project_directory").fetchone()[0]
        finally:
            connection.close()
        assert len(projects) == len({row[1] for row in projects}), projects
        assert duplicates == 0, duplicates
