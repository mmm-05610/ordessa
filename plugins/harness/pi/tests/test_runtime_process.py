"""P: real pi binary, real process, ZERO MODEL runtime sequence.

Evidence level P (not C). Every test in this file launches the REAL local pi
binary pinned below as ``pi --mode rpc`` in a fully isolated child process
(slice-scoped authorisation: isolated process, zero model), under a temporary
unit-private HOME/PI_CODING_AGENT_DIR, with inherited credential-shaped
environment variables dropped and ``--offline``/``PI_OFFLINE=1`` asserted on
the real child. NO prompt, steer, follow-up or any model request is ever
issued and никогда a model is called: the exercised native edges are exactly
``get_state`` round trips (handshake/readback), one ``set_thinking_level``
configuration write confirmed from native readback through the REAL
``harness_unit_configuration_attempts`` journal, the unified termination
face (real process stop with exit-code evidence through the production
``PiTerminationEvidencePort``) and the release of this side's owned records.
The zero-model boundary is asserted per test: the native state stays at
``messageCount == 0`` / ``pendingMessageCount == 0`` / ``isStreaming false``,
no session event of a run is ever observed and no run state is entered.

Installation (observed 2026-10-06, isolated probes recorded in this slice):
- pinned package protocol source: pi-rpc/1 (N003, official 0.86.1 rpc docs);
  observed managed launcher: /home/maoqh/.local/bin/pi ->
  /home/maoqh/.pi/agent/bin/pi (SHA-256
  99142ef3d4cd5ce154cc568c6e915930632808dd7010666e514551c1430ffd3d),
  resolved managed release 0.86.1 (matching the package pin).
- the exercised edges (launch, get_state, set_thinking_level with clamped
  level space {"off"}, managed writer fence, stdin-EOF exit code 0) are
  VERIFIED COMPATIBLE against the observed 0.86.1 binary; other commands
  (prompt/turn edges) are NOT exercised and not claimed.

Real UnitRecords + real OperationJournal (temporary SQLite) carry the unit;
the authority/activation/epoch ports are this fixture's controlled issuer
(same style as the existing vertical tests). Projection reads go only through
the records owner reads (owner_read_*), consume no invocation and issue no
ticket; those boundaries are asserted explicitly. The configuration evidence
store stays a controlled deployment double (owner infra, same as codex);
every pi-native fact checked by it is real.

Cleanup contract: every opened channel is closed explicitly through the
factory in teardown, waiting for process exit; the private-root process
liveness is re-scanned through /proc so no residual child remains; no skip is
used anywhere.
"""
from __future__ import annotations

import copy
import os

import pytest

from ordessa_environment_api.operations import safe_json
from pacthold.agents.nodes.directory import DirectoryBindingRef
from ordessa_harness_records.operation_journal import OperationJournal
from ordessa_harness_records.unit_records import (
    UnitRecords, UnitRecordsRefused,
)
from ordessa_harness_transport.channel import _TOKEN_ENV_KEYS
from ordessa_harness_pi import (
    ChannelRecord, LeasedConnection, PiChannelRefused, PiConnectionLeasePort,
    PiGrant, PiLeaseRefused, PiLifecycleRefused, PiProjectionRefused, PiProviderRefused,
    PiRuntimeProvider, PiTerminationEvidencePort, PiRpcChannelFactory,
    PiUnitProjection, rpc_argv, verified_private_roots,
)
from ordessa_harness_pi.client import PI_PROTOCOL_ID
from test_termination_records import (
    ControlledEpoch, ControlledIssuer, ControlledScope,
    DEFINITION, DIGEST, ENVIRONMENT, NODE, PROVIDER, REQUEST, SCOPE,
)
from test_configuration_journal import JournallingEvidence, change, declaration, query_context

#: Real local installation observed 2026-10-06: managed launcher -> 0.86.1.
EXECUTABLE = "/home/maoqh/.local/bin/pi"
# The P harness shares the controlled harness's environment namespace constants
# (see test_termination_records) so every imported helper and the issuer stamp
# the same objects. Only the temp SQLite journal and the real process are new.


def child_processes_of(pihome: str, home: str) -> list[tuple[int, str]]:
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
        if entries.get("PI_CODING_AGENT_DIR") == pihome or entries.get("HOME") == home:
            pid = int(name)
            if pid != os.getpid():
                found.append((pid, entries.get("PI_CODING_AGENT_DIR", "")))
    return found


class Flow:
    """One P harness: real journal/records/provider/factory/lease/termination ports."""

    def __init__(self, tmp_path, *, timeouts=None):
        self.tmp_path = tmp_path
        self.private = tmp_path / "private"
        self.roots = {"cwd": str(self.private / "cwd"),
                      "home": str(self.private / "home"),
                      "piHome": str(self.private / "pihome")}
        for name in ("cwd", "home", "pihome"):
            (self.private / name).mkdir(parents=True, exist_ok=True)
        self.epoch = ControlledEpoch()
        self.issuer = ControlledIssuer(self.epoch)
        self.evidence = JournallingEvidence()
        self.factory = PiRpcChannelFactory(EXECUTABLE, timeouts=timeouts)
        self.port = PiTerminationEvidencePort(self.factory)
        # Composition order: projection first (owner attach after records);
        # the projection itself is the records' native session evidence port.
        self.projection = PiUnitProjection(
            None, start_authority=self.issuer.verify_start_continuation,
            configuration_authority=self.issuer.verify_configuration_continuation,
            publication_owner=lambda unit, binding: {
                "directoryBindingRef": DirectoryBindingRef(ENVIRONMENT, "directory", 1, "sha256:" + "a" * 64),
                "evidenceRef": {"environmentNamespace": ENVIRONMENT, "evidenceId": "owner"}})
        self.journal = OperationJournal(tmp_path / "owner.sqlite")
        self.records = UnitRecords(self.journal, scope_authority=ControlledScope(),
                                   native_evidence=self.projection, verifier=self.issuer,
                                   epoch_port=self.epoch, configuration_evidence=self.evidence,
                                   termination_evidence=self.port)
        self.projection.attach_owner(self.records)
        self.lease_port = PiConnectionLeasePort()
        self.provider = PiRuntimeProvider(
            definition_ref=DEFINITION, implementation_digest=DIGEST, unit_records=self.records,
            projection=self.projection, verifier=self.issuer, channel_factory=self.factory,
            lease_port=self.lease_port, configuration_evidence=self.evidence, termination_evidence=self.port)
        self.unit = None

    def prepare(self, *, digest="input"):
        context = self.issuer.issue("prepare", "prepare", digest)
        plan = {"context": {"nodeRef": NODE, "privateRootFacts": dict(self.roots)}}
        result = self.provider.prepare(plan, context)
        self.unit = self.records.owner_read_unit(result["unitRef"]["unitId"])
        return result, self.unit

    def start(self, *, digest="start-input"):
        assert self.unit is not None
        context = self.issuer.issue("start", "start", digest)
        return self.provider.start({"unitRef": self.unit.public_ref}, context)

    def binding(self):
        return self.records.owner_read_session(self.unit.unit_ref)

    def channel_record(self) -> ChannelRecord:
        records = list(self.factory._records.values())
        assert len(records) == 1
        return records[0]

    def private_child_pids(self):
        return [pid for pid, _ in child_processes_of(self.roots["piHome"], self.roots["home"])]

    def close(self):
        return self.factory.close_all()


@pytest.fixture
def flow(tmp_path):
    harness = Flow(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


def zero_model_assertions(flow):
    record = flow.channel_record()
    # native-observed zero-model state through the REAL process
    data = record.client.command("get_state").get("data")
    assert data["messageCount"] == 0 and data["pendingMessageCount"] == 0
    assert data["isStreaming"] is False
    live_events = [event.get("type") for event in record.client.events()]
    assert not any(name in live_events
                   for name in ("message_update", "agent_end", "agent_settled",
                                "bash_execution_update", "tool_execution_update",
                                "compaction_start", "compaction_end"))
    assert record.client._run_state is None  # no prompt ledger entry, ever
    assert record.client.pending == {}


# -- P: real confirmed creation, native identity, isolation and readback -------


def test_real_start_confirms_original_session_identity_and_readback(flow):
    prepared, unit = flow.prepare()
    assert prepared["created"] is True
    assert prepared["unitRef"]["ownerProviderRef"]["providerId"] == "pi"
    result = flow.start()
    assert result["state"] == "confirmed"
    binding = flow.binding()
    session_id = binding.native_facts["sessionId"]
    assert binding.native_facts["nativeRealm"] == PI_PROTOCOL_ID
    assert binding.native_facts["evidenceRef"].startswith("pi-native-session/")
    assert isinstance(session_id, str) and session_id
    # fresh get_state round trip against the REAL process carries the same identity
    record = flow.channel_record()
    live = record.client.command("get_state").get("data")
    assert live["sessionId"] == session_id
    assert record.spec.argv == rpc_argv(EXECUTABLE)
    assert record.spec.argv[0] == EXECUTABLE and "--offline" in record.spec.argv
    assert flow.factory.opens == 1
    zero_model_assertions(flow)


def test_real_environment_is_isolated_under_the_unit_private_root(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    private_home = os.path.abspath(flow.roots["home"])
    private_pihome = os.path.abspath(flow.roots["piHome"])
    assert record.spec.cwd == flow.roots["cwd"]
    for key in _TOKEN_ENV_KEYS:
        assert key not in record.spec.env, key
    assert record.spec.env["HOME"] == private_home
    assert record.spec.env["PI_CODING_AGENT_DIR"] == private_pihome
    assert record.spec.env["PI_OFFLINE"] == "1"
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert record.spec.env[key].startswith(private_home), key
    # the REAL child process was actually started with the isolated identity
    pid = record.channel._process.pid
    environ = {}
    with open(f"/proc/{pid}/environ", "rb") as handle:
        for raw in handle.read().split(b"\x00"):
            if b"=" in raw:
                name, value = raw.split(b"=", 1)
                environ[name.decode()] = value.decode()
    assert environ["HOME"] == private_home and environ["PI_CODING_AGENT_DIR"] == private_pihome
    assert environ["PI_OFFLINE"] == "1"
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "DEEPSEEK_API_KEY"):
        assert key not in environ
    # the pinned installation never read user configuration: the isolated
    # session's model identity stays the offline default observed natively
    data = record.client.command("get_state").get("data")
    assert data["model"]["provider"] == "unknown" and data["model"]["id"] == "unknown"
    assert data["thinkingLevel"] == "off"
    # no CHILD was ever given a writable identity outside the unit private root
    child_written = [path for path in flow.tmp_path.rglob("*")
                     if path.is_file() and not path.name.startswith("owner.sqlite")]
    assert child_written and all(str(path).startswith(str(flow.private)) for path in child_written)


def test_real_projection_reads_and_query_consume_no_invocation_and_issue_no_ticket(flow):
    flow.prepare()
    flow.start()
    ref = flow.unit.public_ref
    before = len(flow.issuer.issued)
    assert flow.projection.read_unit(ref) is flow.unit or \
        flow.projection.read_unit(ref).public_ref == ref
    assert flow.projection.read_session(ref).state == "confirmed"
    correlation = flow.binding().creation_correlation
    outcome = flow.provider.query_step(correlation, flow.issuer.issue("query", "start", "start-input", query=True))
    assert outcome["state"] == "confirmed" and safe_json(outcome["unitRef"]) == safe_json(ref)
    assert len(flow.issuer.issued) == before + 1  # only the query context was issued
    assert list(flow.records._tickets) == [] and list(flow.records._termination_tickets) == []
    consumed = [entry for entry in flow.issuer.issued.values() if entry["state"] == "consumed"]
    assert len(consumed) == 2  # exactly the two effect claims (prepare, start)
    verified = [entry for entry in flow.issuer.issued.values() if entry["verified"]]
    assert len(verified) == 3  # the read-only query was verified, never consumed
    assert flow.channel_record().client._request_seq == 2  # the query wrote no RPC at all


def test_real_forged_unit_reference_is_refused_before_any_native_launch(flow):
    flow.prepare()
    original = flow.unit.public_ref
    ref = dict(original)
    ref["sourceRevision"] = "sha256:" + "d" * 64
    owner_only = dict(original)
    owner_only["ownerProviderRef"] = dict(original["ownerProviderRef"])
    owner_only["ownerProviderRef"]["generation"] = 2
    raw = {"environmentNamespace": ENVIRONMENT, "unitId": original["unitId"]}
    for candidate in (ref, owner_only, raw):
        context = flow.issuer.issue("start", "start-forged", "start-input")
        with pytest.raises((PiProviderRefused, PiProjectionRefused, UnitRecordsRefused)):
            flow.provider.start({"unitRef": candidate}, context)
        assert flow.factory.opens == 0
        assert list(flow.records._tickets) == []
    assert flow.binding().state == "notCreated"


def projection_refused_surface(unit, context):  # pragma: no cover - authority surface only
    raise PiProjectionRefused("original start authority unavailable")


def test_projection_refuses_forged_references(flow):
    flow.prepare()
    ref = flow.unit.public_ref
    projection = flow.projection
    before = len(flow.issuer.issued)
    with pytest.raises(UnitRecordsRefused, match="unit missing"):
        projection.read_unit({**ref, "unitId": "different-unit"})
    with pytest.raises(PiProjectionRefused, match="owner source"):
        projection.read_unit({**ref, "sourceRevision": "sha256:" + "d" * 64})
    with pytest.raises(PiProjectionRefused, match="owner-bound"):
        projection.read_unit({"environmentNamespace": ENVIRONMENT, "unitId": ref["unitId"]})
    assert len(flow.issuer.issued) == before  # owner reads consumed no invocation
    bare = PiUnitProjection(None, start_authority=projection_refused_surface)
    with pytest.raises(PiProjectionRefused, match="journal owner"):
        bare.read_unit(ref)


def test_real_channel_refuses_bad_roots_queries_and_missing_install(flow, tmp_path):
    factory = flow.factory
    roots = dict(flow.roots)
    start_facts = {"action": "start", "query": False}
    with pytest.raises(PiChannelRefused):
        factory.open(roots, {"action": "query", "query": True})  # read-only never opens
    with pytest.raises(PiChannelRefused):
        factory.open(roots, {"action": "start", "query": None})
    relative = dict(roots)
    relative["cwd"] = "relative/path"
    with pytest.raises(PiChannelRefused):
        factory.open(relative, start_facts)
    escape = dict(roots)
    escape["home"] = str(tmp_path / "elsewhere")
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(PiChannelRefused):
        factory.open(escape, start_facts)  # one common private root parent is real
    assert factory.opens == 0
    with pytest.raises(PiChannelRefused):
        PiRpcChannelFactory("relative-pi")
    with pytest.raises(PiChannelRefused):
        PiRpcChannelFactory(str(tmp_path / "missing-pi"))


def test_verified_private_roots_accepts_only_the_layout(tmp_path):
    good = {"cwd": str(tmp_path / "cwd"), "home": str(tmp_path / "home"), "piHome": str(tmp_path / "pihome")}
    assert dict(verified_private_roots(good)) == good
    for bad in (None,
                {"cwd": "x", "home": "/a", "piHome": "/b"},
                {"cwd": "/a", "home": "/a", "piHome": "/b"},
                {"cwd": "/a", "home": "/a/home", "piHome": "/somewhere/pi"},
                {"cwd": "/a", "home": "/b/home", "piHome": "/c/pi", "extra": 1},
                {"cwd": "/etc/passwd", "home": "/shadow", "piHome": "/usr"},
                {"cwd": None, "home": "/a/home", "piHome": "/a/pi"},
                {"cwd": "/a", "home": "/a/home", "piHome": "/a/pi", "codexHome": "/a/codex"}):
        with pytest.raises(PiChannelRefused):
            verified_private_roots(bad)


# -- P: real lease seam (connect / revoke / disconnect-is-not-stop) -------------


def test_real_connect_binds_original_lease_and_revoke_cuts_every_write(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    unit_ref = flow.unit.public_ref
    session_id = flow.binding().native_facts["sessionId"]
    grant = flow.lease_port.grant(unit_ref)
    assert isinstance(grant, PiGrant) and grant.epoch == 0
    with pytest.raises(TypeError):
        copy.copy(grant)
    connection = flow.provider.connect(unit_ref, grant)
    assert isinstance(connection, LeasedConnection)
    # zero-model consumer write through the lease: identity round trip only
    observed = connection.command("get_state")["data"]
    assert observed["sessionId"] == session_id and observed["messageCount"] == 0
    # forged, foreign and copied authorizations can never bind this connection
    for foreign in ({}, "lease", flow.lease_port.grant(
            {"environmentNamespace": "other", "unitId": "u", "ownerProviderRef": PROVIDER,
             "sourceRevision": "sha256:" + "b" * 64})):
        with pytest.raises(PiLeaseRefused, match="absent, revoked or of an old activation"):
            flow.provider.connect(unit_ref, foreign)
    pending_grant = flow.lease_port.grant(unit_ref)
    with pytest.raises(PiLeaseRefused, match="already granted to another writer"):
        flow.provider.connect(unit_ref, pending_grant)
    # typed revoke: this connection and the underlying original lease both die
    flow.lease_port.revoke(unit_ref)
    with pytest.raises(PiLeaseRefused, match="absent, revoked or of an old activation"):
        connection.command("get_state")
    record = flow.channel_record()
    with pytest.raises(Exception, match="writer is absent, revoked"):
        record.client.command("get_state", timeout=2)
    assert record.channel._process.poll() is None  # disconnect is not stop
    with pytest.raises(PiLeaseRefused, match="absent, revoked or of an old activation"):
        flow.provider.connect(unit_ref, grant)  # old activation can never rebind
    # no native run was ever observed through the lease: the event stream stays empty
    record = flow.channel_record()
    assert record.client.events() == () and record.client._run_state is None


def test_real_connection_disconnect_fences_only_the_view_not_the_process(flow):
    flow.prepare()
    flow.start()
    unit_ref = flow.unit.public_ref
    session_id = flow.binding().native_facts["sessionId"]
    record = flow.channel_record()
    connection = flow.provider.connect(unit_ref, flow.lease_port.grant(unit_ref))
    assert connection.command("get_state")["data"]["sessionId"] == session_id
    process = record.channel._process
    assert connection.close() is None
    assert connection.close() is None  # idempotent entry disconnect
    with pytest.raises(PiLeaseRefused, match="fenced, disconnected or stale"):
        connection.command("get_state")
    assert process.poll() is None              # the entry disconnect did NOT stop the unit
    assert flow.close() == 0                   # the owner's explicit shutdown reaps it
    assert process.poll() is not None          # explicitly waited, reaped by identity
    assert flow.private_child_pids() == []     # no residual process


def test_real_channel_shutdown_reaps_every_owned_process_and_ps_stays_clean(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    process = record.channel._process
    assert process.poll() is None
    assert len(flow.private_child_pids()) == 1  # exactly this private root's process
    assert flow.close() == 0
    assert process.poll() is not None  # explicitly waited, reaped by identity
    assert record.client.close() is None  # idempotent view close after the reap
    assert flow.private_child_pids() == []     # ps-equivalent /proc scan: no residual
    with pytest.raises(PiChannelRefused):
        flow.factory.record(record.entry)  # the channel record was released


def test_real_descriptor_advertises_only_wired_family_capabilities(flow):
    methods = flow.provider.descriptor.supported_methods
    assert "stop" in methods and "release" in methods
    assert "apply_configuration" in methods and "query_change" in methods
    assert "connect" in methods and "recover" not in methods
    with pytest.raises(PiProviderRefused):
        flow.provider.recover({}, None)
    definition = flow.provider.describe_definition(DEFINITION)
    assert definition["familyId"] == "pi" and definition["channel"] == "pi-rpc/1"
    assert definition["runtimeReady"] == "unknown"  # readiness is never claimed


# -- P: real configuration confirmation through the NativeConfigurationAttempt journal


def test_real_configuration_write_confirms_from_native_readback(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    request, context = change(flow, declaration(payload={"level": "off"}))
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "applied"
    assert result.confirmed_snapshot.configuration["pi.thinking"] == {"level": "off"}
    attempt = flow.records.query_configuration_change(flow.unit.unit_ref, "operation-config",
                                                      query_context(flow, declarations=request.declarations),
                                                      input_digest="apply-digest")
    assert attempt.state == "confirmed" and attempt.native_request_id is not None
    assert attempt.native_request_digest.startswith("sha256:")
    assert flow.evidence.next == 1
    assert record.client.pending == {}  # the one write was receipt-resolved
    zero_model_assertions(flow)
    assert len(flow.private_child_pids()) == 1 and record.channel._process.poll() is None


def test_real_ack_without_native_readback_effect_never_applies(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    # pi's offline level space is {"off"}: the "high" write is ACK-clamped natively
    request, context = change(flow, declaration(payload={"level": "high"}))
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "unknown" and result.confirmed_snapshot is None
    assert flow.evidence.captured == {}  # no confirmation evidence was captured
    attempt = flow.records.query_configuration_change(flow.unit.unit_ref, "operation-config",
                                                      query_context(flow, declarations=request.declarations),
                                                      input_digest="apply-digest")
    assert attempt.state == "unknown" and attempt.native_request_id is not None
    data = record.client.command("get_state").get("data")  # native observation: level is off
    assert data["thinkingLevel"] == "off" and data["messageCount"] == 0
    zero_model_assertions(flow)


def test_real_multi_setter_batch_is_refused_before_any_journal_claim(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    with_lock = flow.binding()
    request, context = change(flow, declaration(), declaration(
        kind="pi.model", payload={"provider": "native", "model": "new"}, declaration_id="model"))
    with pytest.raises(PiProviderRefused, match="distinct native writes"):
        flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    record = flow.channel_record()
    assert record.client.pending == {}  # not one native write was sent
    assert flow.evidence.captured == {}


def test_real_lost_configuration_receipt_keeps_unknown_and_never_resents(tmp_path):
    flow = Flow(tmp_path, timeouts={"rpc": 0.001})  # controlled receipt-loss deadline
    try:
        flow.prepare()
        assert flow.start()["state"] == "confirmed"
        record = flow.channel_record()
        request, context = change(flow, declaration())
        # pi 0.86.1 handles the queued write immediately: the 0.001s deadline only
        # loses the RECEIPT wait, never the write; the confirm readback then races
        # the late arrival. Either branch is honest: without the ORIGINAL receipt
        # the journal must stay unknown, with it the readback decides the effect.
        result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
        attempt = flow.records.query_configuration_change(flow.unit.unit_ref, "operation-config",
                                                          query_context(flow, declarations=request.declarations),
                                                          input_digest="apply-digest")
        if result.overall_outcome == "unknown":
            # the late receipt is still owned by the original dispatch ledger
            assert attempt.state == "unknown" and attempt.native_request_id is not None
        else:
            assert result.confirmed_snapshot is not None
            assert attempt.state == "confirmed"
        assert attempt.native_request_id is not None  # exactly one dispatch, known
        assert attempt.native_request_id not in record.client._pending  # receipt resolved
        # exactly ONE native config write was ever frozen on the wire: the deadline
        # loss never triggers a re-send, the confirm readback re-observes only
        assert record.client.events() == () and record.client._prepared._closed is False
        queries = flow.provider.query_change(flow.unit.public_ref, "operation-config",
                                             query_context(flow, declarations=request.declarations))
        assert queries.overall_outcome == result.overall_outcome  # query reads the same journal
        assert record.client.events() == ()  # still no native run event of any kind
        assert flow.evidence.next <= 1
        assert record.channel._process.poll() is None  # the real process keeps running
        # the pi stop face is exactly what can conclude a lost receipt later: real exit evidence
        result = flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
        assert result["state"] == "confirmed"
        stop_record = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
        assert stop_record["state"] == "confirmed"
        assert stop_record["outcome"]["exitRef"].startswith("exit/")
        process_none = flow.provider.release(flow.unit.public_ref,
                                             flow.issuer.issue("release", "release", "release-input"))
        assert process_none["state"] == "confirmed"
        assert record.channel._process.poll() is not None
        assert flow.private_child_pids() == []  # double-checked /proc scan, reaped
    finally:
        flow.close()


# -- P: real unified termination face on the real process ------------------------


def test_real_stop_terminates_the_process_with_exit_evidence(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    process = flow.channel_record().channel._process
    assert process.poll() is None
    result = flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    assert result["state"] == "confirmed" and result["action"] == "stop"
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
    assert record["state"] == "confirmed" and record["projection"] == "owner-read"
    outcome = record["outcome"]
    assert outcome["nativeRealm"] == PI_PROTOCOL_ID and outcome["action"] == "stop"
    assert outcome["processRef"] == "pi-process/" + str(process.pid)
    assert outcome["exitRef"].startswith("exit/")
    assert outcome["exitRef"] == "exit/" + str(int(process.returncode))
    # the exit evidence is the real subprocess's own exit code, reaped by identity
    assert process.poll() is not None
    assert flow.private_child_pids() == []  # no residual process anywhere
    binding = flow.binding()
    assert binding.state == "confirmed"  # stop never rewrites the original session truth


def test_real_release_after_stop_frees_all_owned_records_and_revokes_grants(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    unit_ref = flow.unit.public_ref
    grant = flow.lease_port.grant(unit_ref)
    assert flow.provider.stop(unit_ref, flow.issuer.issue("stop", "stop", "stop-input"))["state"] == "confirmed"
    process = flow.channel_record().channel._process
    result = flow.provider.release(unit_ref, flow.issuer.issue("release", "release", "release-input"))
    assert result["state"] == "confirmed" and result["action"] == "release"
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "release")
    assert record["state"] == "confirmed"
    assert record["outcome"]["processRef"] == "pi-process/" + str(process.pid)
    assert flow.provider._channels == {}  # owned live handles are gone
    assert flow.private_child_pids() == []  # no residual process
    with pytest.raises(PiProviderRefused):
        flow.provider.describe_access(unit_ref)  # released owner grants no access
    with pytest.raises(PiLeaseRefused):
        flow.provider.lease_port.bind(unit_ref, grant, object())  # revoked grant can never rebind
    with pytest.raises(UnitRecordsRefused, match="already"):
        flow.provider.release(unit_ref, flow.issuer.issue("release", "release-2", "x"))


def test_real_release_refuses_live_owned_unit_and_never_kills(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    release = flow.issuer.issue("release", "release", "release-input")
    with pytest.raises(PiLifecycleRefused, match="requires stop before release"):
        flow.provider.release(flow.unit.public_ref, release)
    assert flow.provider._channels != {}          # nothing was taken away
    assert len(flow.private_child_pids()) == 1    # the process is still running
    assert flow.records.owner_read_termination(flow.unit.unit_ref, "release") is None


def test_real_second_stop_is_refused_single_attempt_holds(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    result = flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    assert result["state"] == "confirmed"
    replay = flow.issuer.issue("stop", "stop-2", "other")
    with pytest.raises(UnitRecordsRefused, match="already"):
        flow.provider.stop(flow.unit.public_ref, replay)
    assert flow.issuer.issued[replay]["state"] == "consumed"  # journal-consumed inside its admission cut
    rows = [action for action in ("stop", "release")
            if flow.records.owner_read_termination(flow.unit.unit_ref, action) is not None]
    assert rows == ["stop"]


def test_real_stop_expires_when_activation_epoch_moves_mid_effect(tmp_path):
    flow = Flow(tmp_path)
    try:
        flow.prepare()
        assert flow.start()["state"] == "confirmed"
        original_close = flow.factory.close

        def bumping_close(entry, timeout=15.0):
            flow.epoch.value = 1  # activation epoch moves while the effect runs
            return original_close(entry, timeout=timeout)

        flow.factory.close = bumping_close
        with pytest.raises(PiLifecycleRefused, match="unknown"):
            flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
        record = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
        assert record["state"] == "opening" and record["outcome"] is None  # the hold stays
        flow.factory.close = original_close
    finally:
        flow.close()
