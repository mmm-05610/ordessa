"""P: real claude binary, real process, ZERO MODEL runtime evidence.

Evidence level P (not C). Every test in this file runs the REAL local Claude
Code binary pinned below as a bidirectional stream-json child — the exact
subprocess seam the official Claude Agent SDK itself spawns (pinned upstream
``subprocess_cli.py``; the SDK package is NOT installed in this environment,
so the direct stdio channel is the exercised production seam). Slice-scoped
authorisation: isolated process, zero model. The child runs under a temporary
unit-private root — ``HOME``/``XDG_*``/``TMPDIR`` pinned inside it,
``CLAUDE_CONFIG_DIR`` pointed at the unit-private config directory, every
credential-shaped environment key dropped by the transport, telemetry/
auto-update/nonessential-traffic assertions re-asserted. The user's real
``~/.claude`` (login, OAuth, history, global config) is NEVER read or written:
the child never receives the user HOME in any identity key, proven from
``/proc/<pid>/environ``. Nothing is installed or updated.

The exercised native edges are exactly the login-free ones:
- ``--version`` fact probe (captured, isolated child),
- controlled launch + managed stdin writer fence,
- the native ``control_request``/``control_response`` handshake
  (``initialize``; receipt carries ``account.tokenSource: "none"`` — the
  process's OWN no-login fact),
- real stop (stdin close → exit, terminate/kill never needed) with the
  subprocess's own exit code as evidence, and release of the exited record,
- the production termination face (``ClaudeTerminationEffects`` +
  ``ClaudeTerminationCoordinator`` + real ``ClaudeTerminationEvidence`` port)
  consuming the REAL process handle through the owned-channel registry.

The zero-model boundary is asserted per test: no user message is ever written
(stdin carries exactly the one control_request), no ``system/init`` session
record, no ``assistant``/``user``/``result``/``stream_event`` record, no
native session identity, no session transcript under the private config dir,
and the native receipt itself reports ``tokenSource: "none"``. Without login
credentials no model call is even possible; none is attempted. One honest
nuance is recorded: the child keeps its own IDLE process-registry entry under
the private ``config/sessions/<pid>.json`` (internally generated UUID, peer
socket inside the private root, no message content; removed by the child at
close). It is process bookkeeping for the never-messaged session, not a
conversation, and the wire records stay empty of any model event.

NOT exercised (no login state; recorded honestly as ABSENT, never mocked):
session initialize (``system/init``), any model turn, ``can_use_tool``
permission callbacks, ``set_model``/configuration write readback (the C-level
typed refusal stands; no native readback edge exists without a turn).

Cleanup contract: every opened channel is closed explicitly through the
factory in teardown, waiting for process exit; the private-root liveness is
re-scanned through /proc so no residual child remains; no skip is used
anywhere.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ordessa_execution_agents.harness.transport import ChannelFailure, WriterLeaseRefused
from ordessa_execution_agents.harness.transport.channel import _TOKEN_ENV_KEYS
from ordessa_harness_claude_code import (
    ClaudeChannelRefused, ClaudeRuntimeRefused, ClaudeStreamChannelFactory,
    ClaudeTerminationCoordinator, ClaudeTerminationEffects, ClaudeTerminationRefused,
    RealProcessHandle, stream_json_argv, verified_private_roots, version_facts,
)
import claude_production_fixture as fx
from ordessa_harness_claude_code.native_evidence import ClaudeEvidenceRefused

#: Real local installation observed 2026-10-06: managed launcher (symlink)
#: -> native ELF release binary; pinned and re-verified by the factory.
EXECUTABLE = "/home/maoqh/.local/bin/claude"
PINNED_SHA256 = "078fad28d0297c9a25d306b635b2d8816c6839347520f29eb54ffea5d56142fb"
PINNED_DIGEST = "sha256:" + PINNED_SHA256
PINNED_REALPATH = "/home/maoqh/.local/share/claude/versions/2.1.291"
PINNED_VERSION_LINE = "2.1.291 (Claude Code)"


def child_processes_of(config_dir: str, home: str) -> list[int]:
    """Every live process whose consumed environment points at THIS private root."""
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/environ", "rb") as handle:
                entries = {}
                for raw in handle.read().split(b"\x00"):
                    if b"=" in raw:
                        key, value = raw.split(b"=", 1)
                        entries[key.decode()] = value.decode()
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if entries.get("CLAUDE_CONFIG_DIR") == config_dir or entries.get("HOME") == home:
            pid = int(name)
            if pid != os.getpid():
                found.append(pid)
    return sorted(found)


def child_environ(pid: int) -> dict[str, str]:
    environ: dict[str, str] = {}
    with open(f"/proc/{pid}/environ", "rb") as handle:
        for raw in handle.read().split(b"\x00"):
            if b"=" in raw:
                key, value = raw.split(b"=", 1)
                environ[key.decode()] = value.decode()
    return environ


def child_cmdline(pid: int) -> tuple[str, ...]:
    with open(f"/proc/{pid}/cmdline", "rb") as handle:
        parts = handle.read().decode().split("\x00")
    return tuple(part for part in parts if part)


class Flow:
    """One P harness: pinned factory over a temporary unit-private root."""

    def __init__(self, base, *, expected_sha256=PINNED_DIGEST):
        self.base = base
        self.private = base / "private"
        self.roots = {"cwd": str(self.private / "cwd"),
                      "home": str(self.private / "home"),
                      "config": str(self.private / "claude-config")}
        for name in ("cwd", "home", "claude-config"):
            (self.private / name).mkdir(parents=True, exist_ok=True)
        self.factory = ClaudeStreamChannelFactory(EXECUTABLE, expected_sha256=expected_sha256)
        self.entry = None

    def open(self):
        self.entry = self.factory.open(dict(self.roots), {"action": "start", "query": False})
        return self.entry

    def handshake(self):
        assert self.entry is not None
        return self.entry.initialize_control()

    def record(self):
        return self.factory.record(self.entry)

    def process(self):
        return self.record().channel._process

    def child_pids(self) -> list[int]:
        return child_processes_of(self.roots["config"], self.roots["home"])

    def close(self) -> int:
        return self.factory.close_all()


@pytest.fixture
def flow(tmp_path):
    harness = Flow(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


def zero_model_assertions(flow):
    """The native zero-model boundary, observed from the REAL child."""
    record = flow.record()
    kinds = [raw.get("type") for raw in record.client.records()]
    # exactly one stdin frame was ever written: the initialize control_request
    assert kinds == ["control_response"]
    assert not any(name in kinds for name in
                   ("system", "assistant", "user", "result", "stream_event"))
    assert record.client._init is None          # system/init session never observed
    assert record.client.session_id is None     # no native session identity ever bound
    assert record.client._result is None
    assert record.client._active_turn is False  # no turn was ever opened
    assert record.client._permissions == {}     # no permission callback was ever pending
    assert record.client._initialize_sent is True  # exactly the one admitted control write
    # No conversation transcript exists anywhere under the unit-private config
    # directory. (The CLI does keep its own IDLE process-registry entry under
    # config/sessions/<pid>.json — internally generated bookkeeping for the
    # never-messaged process, observed and recorded; it is not a conversation,
    # carries no message, and is removed by the child itself at close.)
    assert not list(Path(flow.roots["config"]).rglob("*.jsonl"))


# -- P: pinned installation identity and the real --version fact ---------------


def test_pinned_installation_identity_is_verified(tmp_path):
    factory = ClaudeStreamChannelFactory(EXECUTABLE, expected_sha256=PINNED_DIGEST)
    assert factory.artifact_sha256 == PINNED_DIGEST
    assert factory.realpath == PINNED_REALPATH
    for bad_digest in ("sha256:" + "0" * 64, "deadbeef", "sha256:zz"):
        with pytest.raises(ClaudeRuntimeRefused, match="digest"):
            ClaudeStreamChannelFactory(EXECUTABLE, expected_sha256=bad_digest)
    with pytest.raises(ClaudeRuntimeRefused, match="absolute path"):
        ClaudeStreamChannelFactory("claude")
    with pytest.raises(ClaudeRuntimeRefused, match="missing"):
        ClaudeStreamChannelFactory(str(tmp_path / "missing-claude"))


def test_real_version_fact_from_an_isolated_child(tmp_path):
    scratch = tmp_path / "probe"
    (scratch / "cwd").mkdir(parents=True)
    facts = version_facts(EXECUTABLE, home=str(scratch / "home"), cwd=str(scratch / "cwd"))
    assert facts["exitCode"] == 0
    assert facts["stdout"].strip() == PINNED_VERSION_LINE
    assert facts["stderr"] == ""
    # the version probe child wrote nothing anywhere under its scratch root
    assert not any(path.is_file() for path in scratch.rglob("*"))


# -- P: real launch, native handshake, isolation, zero model --------------------


def test_real_launch_and_native_control_handshake_without_login(flow):
    entry = flow.open()
    assert flow.factory.opens == 1
    record = flow.record()
    assert record.spec.argv == stream_json_argv(EXECUTABLE)
    assert record.spec.argv[0] == EXECUTABLE
    receipt = flow.handshake()
    # the REAL process answered the native initialize control request
    account = receipt.get("account")
    assert isinstance(account, dict) and account.get("tokenSource") == "none"
    assert account.get("apiProvider") == "firstParty"
    assert receipt.get("pid") == record.channel._process.pid  # the receipt is THIS process
    assert receipt.get("session_state") == "idle"
    assert isinstance(receipt.get("commands"), list) and receipt["commands"]
    assert isinstance(receipt.get("models"), list) and receipt["models"]
    # the pinned argv is what the kernel actually runs
    assert child_cmdline(record.channel._process.pid) == stream_json_argv(EXECUTABLE)
    # the child recorded its own release fact in the unit-private config dir
    state_file = Path(flow.roots["config"], ".claude.json")
    assert state_file.is_file()
    with state_file.open() as handle:
        assert json.load(handle).get("firstStartVersion") == "2.1.291"
    zero_model_assertions(flow)
    assert flow.child_pids() == [record.channel._process.pid]


def test_real_child_environment_is_isolated_and_credential_free(flow):
    flow.open()
    flow.handshake()
    record = flow.record()
    pid = record.channel._process.pid
    private_home = os.path.abspath(flow.roots["home"])
    private_config = os.path.abspath(flow.roots["config"])
    for key in _TOKEN_ENV_KEYS:
        assert key not in record.spec.env, key
    assert record.spec.env["HOME"] == private_home
    assert record.spec.env["CLAUDE_CONFIG_DIR"] == private_config
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert record.spec.env[key].startswith(private_home), key
    # the REAL child process was actually started with the isolated identity
    environ = child_environ(pid)
    assert environ["HOME"] == private_home and environ["CLAUDE_CONFIG_DIR"] == private_config
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert environ[key].startswith(private_home), key
    assert environ.get("DISABLE_TELEMETRY") == "1"
    assert environ.get("DISABLE_AUTOUPDATER") == "1"
    assert environ.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1"
    for key in _TOKEN_ENV_KEYS:
        assert key not in environ, key
    # no identity anywhere in the child equals the user's real HOME
    user_home = os.environ.get("HOME")
    assert user_home and all(value != user_home for value in environ.values())
    # every file the child ever created stays inside the unit private root
    written = [path for path in flow.base.rglob("*") if path.is_file()]
    assert written and all(str(path).startswith(str(flow.private)) for path in written)


def test_managed_writer_fence_cuts_every_native_write(flow):
    flow.open()
    flow.handshake()
    record = flow.record()
    channel = record.channel
    process = channel._process
    # managed mode: a raw un-leased write can never reach the native stdin
    with pytest.raises(WriterLeaseRefused):
        channel.send_raw({"type": "control_request", "request_id": "forged",
                          "request": {"subtype": "initialize"}})
    # one writer at a time: the factory's bound lease excludes any second writer
    with pytest.raises(WriterLeaseRefused):
        channel.acquire_writer()
    assert process.poll() is None  # the refusal did not touch the process
    # revocation denies all subsequent writes, including framed control writes
    channel.fence_all()
    with pytest.raises(WriterLeaseRefused, match="writer is absent, revoked, unresolved or disconnected"):
        record.client.interrupt(timeout=2)
    # a fresh lease epoch is possible, but the old bound view stays dead
    channel.acquire_writer()
    with pytest.raises(WriterLeaseRefused, match="writer is absent, revoked, unresolved or disconnected"):
        record.client.interrupt(timeout=2)
    assert process.poll() is None  # a fence is never a stop
    zero_model_assertions(flow)


def test_second_control_initialize_is_refused_no_resend(flow):
    flow.open()
    assert flow.handshake()["account"]["tokenSource"] == "none"
    with pytest.raises(ChannelFailure, match="already sent"):
        flow.entry.initialize_control()
    zero_model_assertions(flow)  # no second frame ever reached the wire


# -- P: real stop exit evidence, release refusal, /proc zero residue ------------


def test_real_stop_reaps_by_identity_with_exit_evidence_and_clean_proc(flow):
    flow.open()
    flow.handshake()
    process = flow.process()
    pid = process.pid
    assert process.poll() is None
    code = flow.factory.close(flow.entry)      # owner reap; the record stays for evidence
    assert type(code) is int
    assert process.poll() is not None          # explicitly waited, reaped by identity
    assert process.returncode == code          # the subprocess's own exit evidence
    assert flow.child_pids() == []             # /proc rescan: no residual process
    # release of the already-exited owned record carries the observed facts
    released = flow.factory.release(flow.entry)
    assert released == {"pid": pid, "exitCode": code}
    with pytest.raises(ClaudeRuntimeRefused, match="another factory view"):
        flow.factory.record(flow.entry)        # the record was released
    with pytest.raises(ClaudeRuntimeRefused):
        flow.factory.release(flow.entry)       # nothing left to release twice


def test_real_release_refuses_live_owned_process_and_never_kills(flow):
    flow.open()
    flow.handshake()
    process = flow.process()
    with pytest.raises(ClaudeRuntimeRefused, match="still running; stop the unit first"):
        flow.factory.release(flow.entry)
    assert process.poll() is None              # nothing was terminated
    assert flow.child_pids() == [process.pid]
    zero_model_assertions(flow)


def test_channel_factory_refuses_bad_roots_queries_and_missing_install(flow, tmp_path):
    factory = flow.factory
    roots = dict(flow.roots)
    start_facts = {"action": "start", "query": False}
    with pytest.raises(ClaudeRuntimeRefused):
        factory.open(roots, {"action": "query", "query": True})   # read-only never opens
    with pytest.raises(ClaudeRuntimeRefused):
        factory.open(roots, {"action": "start", "query": None})
    relative = dict(roots)
    relative["cwd"] = "relative/path"
    with pytest.raises(ClaudeRuntimeRefused):
        factory.open(relative, start_facts)
    extra = dict(roots, claudeHome=str(tmp_path / "elsewhere"))
    with pytest.raises(ClaudeRuntimeRefused):
        factory.open(extra, start_facts)
    escape = dict(roots)
    escape["home"] = str(tmp_path / "elsewhere")
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(ClaudeRuntimeRefused):
        factory.open(escape, start_facts)  # one common private root parent is real
    duplicate = {"cwd": roots["cwd"], "home": roots["cwd"], "config": roots["config"]}
    with pytest.raises(ClaudeRuntimeRefused):
        factory.open(duplicate, start_facts)
    assert factory.opens == 0
    assert flow.child_pids() == []
    with pytest.raises(ClaudeRuntimeRefused, match="digest"):
        ClaudeStreamChannelFactory(EXECUTABLE, expected_sha256="sha256:" + "0" * 64)


def test_verified_private_roots_accepts_only_the_layout(tmp_path):
    good = {"cwd": str(tmp_path / "cwd"), "home": str(tmp_path / "home"),
            "config": str(tmp_path / "claude-config")}
    assert dict(verified_private_roots(good)) == good
    for bad in (None,
                {"cwd": "x", "home": "/a", "config": "/b"},
                {"cwd": "/a", "home": "/a", "config": "/b"},
                {"cwd": "/a", "home": "/a/home", "config": "/somewhere/c"},
                {"cwd": "/a", "home": "/b/home", "config": "/c/c", "extra": 1},
                {"cwd": None, "home": "/a/home", "config": "/a/c"},
                {"cwd": "/a", "home": "/a/home", "config": "/a/c", "piHome": "/a/pi"}):
        with pytest.raises(ClaudeRuntimeRefused):
            verified_private_roots(bad)


# -- P: production termination face consuming the REAL process handle -----------


def wired(parts):
    channels = parts["ports"].channels
    effects = ClaudeTerminationEffects(channels, parts["records"].termination_evidence)
    coordinator = ClaudeTerminationCoordinator(records=parts["records"],
                                               verifier=parts["records"].verifier,
                                               projection=parts["projection"], effects=effects)
    return coordinator, channels


def test_real_release_refuses_live_owned_real_process(tmp_path):
    (tmp_path / "core").mkdir()
    parts = fx.family_core_parts(tmp_path / "core")
    coordinator, channels = wired(parts)
    flow = Flow(tmp_path / "claude")
    try:
        flow.open()
        flow.handshake()
        handle = flow.factory.handle(flow.entry)
        channels.register(parts["unit"].public_ref, handle,
                          facts={"pid": str(handle.pid), "configDir": flow.roots["config"],
                                 "argv0": flow.factory.executable})
        release = fx.cleanup_operation(parts, "release")
        refusal_context = release["issued"]()
        with pytest.raises(ClaudeTerminationRefused, match="stop the unit first"):
            coordinator.release(parts["unit"].public_ref, refusal_context)
        assert handle.is_alive() and flow.child_pids() == [handle.pid]  # never killed by release
        assert parts["issuer"].verified_consumption(refusal_context) is False
        assert parts["records"].owner_read_termination(parts["unit"].unit_ref, "release") is None
        zero_model_assertions(flow)
    finally:
        flow.close()


def test_real_termination_face_stops_the_real_process_with_exit_evidence(tmp_path):
    (tmp_path / "core").mkdir()
    parts = fx.family_core_parts(tmp_path / "core")
    coordinator, channels = wired(parts)
    flow = Flow(tmp_path / "claude")
    try:
        flow.open()
        flow.handshake()
        handle = flow.factory.handle(flow.entry)
        assert isinstance(handle, RealProcessHandle)
        channels.register(parts["unit"].public_ref, handle,
                          facts={"pid": str(handle.pid), "configDir": flow.roots["config"],
                                 "argv0": flow.factory.executable})
        stop = fx.cleanup_operation(parts, "stop")
        stop_context = stop["issued"]()
        reply = coordinator.stop(parts["unit"].public_ref, stop_context)
        assert reply["state"] == "confirmed" and reply["action"] == "stop"
        real_code = handle.exit_code
        assert type(real_code) is int and handle.is_alive() is False
        assert flow.child_pids() == []             # the real process is gone everywhere
        projection = parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")
        assert projection["state"] == "confirmed"
        assert projection["outcome"]["terminationEvidenceRef"].startswith("claude-termination/")
        # the stored evidence is the REAL observed exit: the port's birth record
        # re-verifies only against the subprocess's own exit code
        correlation = fx.safe_json({"request": stop_context.facts["request"],
                                    "operationRef": stop_context.facts["operationRef"],
                                    "stepId": stop_context.facts["stepId"]})
        refs = parts["records"].termination_evidence.verify_termination(
            parts["unit"], "stop", correlation,
            {"outcome": "confirmed", "exitCode": str(real_code), "reaped": "1"})
        assert refs["action"] == "stop"
        with pytest.raises(ClaudeEvidenceRefused, match="differs from the observed effect"):
            parts["records"].termination_evidence.verify_termination(
                parts["unit"], "stop", correlation,
                {"outcome": "confirmed", "exitCode": str(real_code + 1), "reaped": "1"})
        zero_model_assertions(flow)
        # release of the exited unit frees the owned registry entry only
        release = fx.cleanup_operation(parts, "release")
        reply = coordinator.release(parts["unit"].public_ref, release["issued"]())
        assert reply["state"] == "confirmed" and reply["action"] == "release"
        assert not channels.is_owned(parts["unit"].public_ref)
        assert flow.child_pids() == []
    finally:
        flow.close()


def test_unknown_stop_keeps_the_real_process_alive_until_explicit_reap(tmp_path):
    (tmp_path / "core").mkdir()
    parts = fx.family_core_parts(tmp_path / "core")
    coordinator, channels = wired(parts)
    flow = Flow(tmp_path / "claude")
    try:
        flow.open()
        flow.handshake()

        class BrokenCloseHandle(RealProcessHandle):
            def close(self, *, timeout=5.0):
                raise OSError("controlled closing refusal")

        broken = BrokenCloseHandle(flow.record().channel)
        channels.register(parts["unit"].public_ref, broken)
        stop = fx.cleanup_operation(parts, "stop")
        reply = coordinator.stop(parts["unit"].public_ref, stop["issued"]())
        assert reply["state"] == "unknown"
        assert broken.is_alive() and flow.child_pids() == [broken.pid]
        projection = parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")
        assert projection["state"] == "unknown" and projection["outcome"] is None
        # a late owner probe cannot conclude while the REAL process still runs
        assert coordinator.reconcile(parts["unit"].public_ref, "stop", stop["query"]())["state"] == "unknown"
        # the owner's explicit tool reaps the real process; cold recovery concludes
        assert flow.close() == 0
        assert flow.child_pids() == []
        reply = coordinator.reconcile(parts["unit"].public_ref, "stop", stop["query"]())
        assert reply["state"] == "confirmed"
        assert parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")["state"] == "confirmed"
    finally:
        flow.close()
