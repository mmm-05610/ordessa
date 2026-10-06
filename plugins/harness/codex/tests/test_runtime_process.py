"""P: real codex binary, real process, ZERO MODEL runtime sequence.

Evidence level P (not C). Every test in this file launches the REAL local
binary pinned below as ``<binary> app-server`` in a fully isolated child
process (slice-scoped authorisation: isolated process, zero model), under a
temporary unit-private HOME/CODEX_HOME, with inherited credential-shaped
environment variables dropped. NO turn/start, prompt, model call or
configuration write is ever issued: the sequence is exactly ``initialize`` ->
(revalidate before every native edge) -> ``thread/start`` ->
``thread/read`` readback. The zero-model boundary is asserted per test (no
turn events, empty native ``turns``, empty native turn ledger).

Binary and protocol compatibility (observed 2026-10-05, see
runtime-process-evidence.md):
- pinned package protocol source: 0.157.1; observed binary: codex-cli 0.159.0
  (SHA-256 d2752c52353401f7f6efbfcea68796f4f7a3d3e4769f5d1da53fa49d4856b72f).
- the exercised edges (initialize / thread/start / thread/read, wire without
  the jsonrpc header, managed writer fence) are VERIFIED COMPATIBLE against
  0.159.0; ``thread/list`` without a params field is a real protocol
  difference (typed -32600 "Invalid request: missing field `params`") and is
  recorded, not faked or patched.

Real UnitRecords + real OperationJournal (temporary SQLite) carry the unit;
the authority/activation/epoch ports are this fixture's controlled issuer
(same style as the existing vertical tests). Projection reads go only through
the records owner reads (owner_read_*), consume no invocation and issue no
ticket; those boundaries are asserted explicitly.

The unified termination face is exercised on the real process too: stop
terminates the owned app-server through the factory's real reap and stores
the ``CodexTerminationEvidencePort``-verified exit evidence in the records
``harness_unit_terminations`` ledger; release refuses a live owned unit,
never kills, and frees this side's owned records only.

Observed binary behaviour (registered, not faked): on startup the 0.159.0
app-server spawns its OWN short-lived ``git`` children (plugins ls-remote/
fetch against github.com) under the isolated CODEX_HOME; they inherit the
isolated environment and outlive a stop by at most a few seconds. The
private-root liveness scan therefore awaits a clean scan within a bounded
deadline instead of assuming it is instantaneous.

Cleanup contract: every opened channel is closed explicitly through the
factory in teardown, waiting for process exit; no skip is used anywhere.
"""
from __future__ import annotations

import copy
import os
import time

import pytest

from ordessa_environment_api.operations import safe_json
from ordessa_harness_codex import (
    CodexAppServerChannelFactory,
    CodexCapabilityUnsupported,
    CodexChannelRefused,
    CodexConnectionLeasePort,
    CodexGrant,
    CodexLeaseRefused,
    CodexProjectionRefused,
    CodexProviderRefused,
    CodexRuntimeProvider,
    CodexTerminationEvidencePort,
    CodexUnitProjection,
    LeasedConnection,
    app_server_argv,
    verified_private_roots,
)
from ordessa_harness_codex.client import PROTOCOL
from ordessa_harness_records.operation_journal import OperationJournal
from ordessa_harness_records.unit_records import (
    CanonicalConfigurationScopeRef, UnitRecords, UnitRecordsRefused,
)
from ordessa_harness_transport.channel import _TOKEN_ENV_KEYS

#: Real local installation observed 2026-10-05: `--version` -> codex-cli 0.159.0.
EXECUTABLE = "/usr/lib/chatgpt/resources/codex"

ENVIRONMENT = "codex-p"
DIGEST = "sha256:" + "a" * 64
PROVIDER = {"environmentNamespace": ENVIRONMENT, "providerId": "codex", "implementationDigest": DIGEST,
            "contractVersion": "agent-runtime/2", "generation": 1,
            "ownerActivationRef": {"environmentNamespace": ENVIRONMENT, "pluginId": "codex-plugin", "generation": 1}}
NODE = {"environmentNamespace": ENVIRONMENT, "nodeId": "node", "generation": 1}
REQUEST = {"environmentNamespace": ENVIRONMENT, "principalScope": "principal", "requestId": "request"}
SCOPE = CanonicalConfigurationScopeRef(ENVIRONMENT, "codex-p-physical", "1")
ISOLATED_ENV_KEYS = {"HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                     "XDG_CACHE_HOME", "TMPDIR", "LANG", "LC_ALL", "TERM", "NO_COLOR",
                     "PATH", "CODEX_HOME"}


def child_processes_of(codex_home: str, home: str) -> list[int]:
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
        if entries.get("CODEX_HOME") == codex_home or entries.get("HOME") == home:
            pid = int(name)
            if pid != os.getpid():
                found.append(pid)
    return found


def wait_private_root_clean(flow, *, timeout: float = 60.0) -> None:
    """Await a fully clean private-root process scan within a bounded deadline.

    The pinned app-server itself is reaped by identity at close. The observed
    0.159.0 binary additionally spawns its OWN short-lived ``git`` children
    under the isolated CODEX_HOME during startup (registered in
    runtime-process-evidence.md), so a clean scan may lag the close by a few
    seconds. The wait never masks a residue: past the deadline this fails.
    """
    deadline = time.monotonic() + timeout
    while True:
        residual = flow.private_child_pids()
        if not residual:
            return
        if time.monotonic() > deadline:
            pytest.fail(f"residual processes remain under the unit private root: {residual}")
        time.sleep(0.5)


class ControlledContext:
    __slots__ = ("facts",)

    def __init__(self, facts):
        self.facts = facts


class ControlledIssuer:
    """Controlled authority/activation/directory/epoch + verifier port.

    Same fixture style as the existing vertical tests: only objects explicitly
    issued inside this test are verified; an effect claim is consumed exactly
    once. ``verify_start_continuation`` re-checks CURRENT facets without
    consuming anything (the original start claim was consumed by the journal).
    """

    def __init__(self, epoch):
        self.allowed = True         # authority facet
        self.active = True          # owner activation facet
        self.permitted = True       # directory permission facet
        self.epoch = epoch
        self.issued = {}

    def epoch_value(self):
        return self.epoch.value

    def issue(self, action, step, digest, node=NODE, *, query=False):
        facts = {"query": query, "action": action, "providerRef": PROVIDER, "targetRef": node,
                 "inputDigest": digest, "managementEpoch": self.epoch_value(),
                 "request": dict(REQUEST), "operationRef": "operation", "stepId": step}
        context = ControlledContext(facts)
        self.issued[context] = {"facts": facts, "state": "issued", "verified": False}
        return context

    def verify_and_consume(self, context, action, provider, node, digest):
        entry = self.issued.get(context)
        if entry is None:
            raise UnitRecordsRefused("unissued or consumed invocation")
        facts = entry["facts"]
        if (entry["state"] != "issued" or facts.get("action") != action
                or safe_json(facts.get("providerRef")) != safe_json(provider)
                or safe_json(facts.get("targetRef")) != safe_json(node)
                or facts.get("inputDigest") != digest):
            raise UnitRecordsRefused("verified invocation identity differs")
        for allowed, facet in ((self.allowed, "authority revoked"),
                               (self.active, "owner activation revoked"),
                               (self.permitted, "directory permission revoked")):
            if allowed is not True:
                raise UnitRecordsRefused(f"current {facet}")
        if not facts["query"]:
            entry["state"] = "consumed"
        entry["verified"] = True
        return dict(facts)

    def verify_start_continuation(self, unit, context):
        entry = self.issued.get(context)
        if (entry is None or entry["verified"] is not True
                or entry["state"] != "consumed" or entry["facts"] is not context.facts):
            raise UnitRecordsRefused("original start has no successful verification on this issuer")
        facts = entry["facts"]
        if (facts.get("action") != "start" or facts.get("query") is not False
                or safe_json(facts.get("providerRef")) != safe_json(unit.facts["providerRef"])
                or safe_json(facts.get("targetRef")) != safe_json(unit.facts["nodeRef"])
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]):
            raise UnitRecordsRefused("current start authority identity differs")
        for allowed, facet in ((self.allowed, "authority revoked"),
                               (self.active, "owner activation revoked"),
                               (self.permitted, "directory permission revoked")):
            if allowed is not True:
                raise UnitRecordsRefused(f"current {facet}")
        if self.epoch.value != facts["managementEpoch"]:
            raise UnitRecordsRefused("management epoch changed")
        return dict(facts)


class RevokingAuthority:
    """P harness authority wrapper: after N successful revalidations the
    named CURRENT facet (or the epoch) is moved before the next edge."""

    def __init__(self, issuer, *, facet, revoke_after):
        self.issuer, self.facet, self.revoke_after, self.calls = issuer, facet, revoke_after, 0

    def __call__(self, unit, context):
        self.calls += 1
        if self.calls > self.revoke_after:
            if self.facet == "epoch":
                self.issuer.epoch.value += 1
            else:
                setattr(self.issuer, self.facet, False)
        return self.issuer.verify_start_continuation(unit, context)


class ControlledEpoch:
    def __init__(self):
        self.value = 0

    def current_epoch(self, node):
        return self.value


class ControlledScope:
    def issue_scope(self, provider, node, roots):
        assert safe_json(provider) == safe_json(PROVIDER)
        return SCOPE

    def verify_scope(self, scope, roots):
        return scope == SCOPE

    def map_legacy_scope(self, target):
        raise AssertionError("no legacy fixture operations in the P harness")


class Flow:
    """One P harness: real journal/records/provider + real channel factory."""

    def __init__(self, tmp_path, *, timeouts=None):
        self.tmp_path = tmp_path
        self.private = tmp_path / "private"
        self.roots = {"cwd": str(self.private / "cwd"),
                      "home": str(self.private / "home"),
                      "codexHome": str(self.private / "codex")}
        for name in ("cwd", "home", "codex"):
            (self.private / name).mkdir(parents=True, exist_ok=True)
        self.epoch = ControlledEpoch()
        self.issuer = ControlledIssuer(self.epoch)
        self.scope = ControlledScope()
        self.journal = OperationJournal(tmp_path / "owner.sqlite")
        # Composition order: projection first (owner attach after records),
        # the projection itself is the records' native evidence port.
        self.projection = CodexUnitProjection(None, start_authority=self.issuer.verify_start_continuation)
        self.factory = CodexAppServerChannelFactory(EXECUTABLE, timeouts=timeouts)
        # The termination evidence owner binds every opened channel; the SAME
        # instance is the records journal's NativeTerminationEvidencePort.
        self.port = CodexTerminationEvidencePort(self.factory)
        self.records = UnitRecords(self.journal, scope_authority=self.scope,
                                   native_evidence=self.projection, verifier=self.issuer,
                                   epoch_port=self.epoch, termination_evidence=self.port)
        self.projection.attach_owner(self.records)
        self.lease_port = CodexConnectionLeasePort()
        self.provider = CodexRuntimeProvider(
            definition_ref={"environmentNamespace": ENVIRONMENT, "definitionId": "codex", "revision": "1"},
            implementation_digest=DIGEST, unit_records=self.records, projection=self.projection,
            verifier=self.issuer, channel_factory=self.factory, lease_port=self.lease_port,
            termination_evidence=self.port)
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

    def query_context(self, *, digest="start-input"):
        return self.issuer.issue("query", "start", digest, query=True)

    def binding(self):
        return self.records.owner_read_session(self.unit.unit_ref)

    def channel_record(self):
        records = list(self.factory._records.values())
        assert len(records) == 1
        return records[0]

    def private_child_pids(self):
        return child_processes_of(self.roots["codexHome"], self.roots["home"])

    def close(self):
        return self.factory.close_all()


@pytest.fixture
def flow(tmp_path):
    harness = Flow(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


# -- P: real confirmed creation, native identity and readback ------------------


def test_real_start_confirms_original_thread_identity_and_readback(flow):
    prepared, unit = flow.prepare()
    assert prepared["created"] is True
    assert prepared["unitRef"]["ownerProviderRef"]["providerId"] == "codex"
    result = flow.start()
    assert result["state"] == "confirmed"
    binding = flow.binding()
    session_id = binding.native_facts["sessionId"]
    assert binding.native_facts["nativeRealm"] == PROTOCOL
    assert binding.native_facts["evidenceRef"].startswith("codex-native-thread/")
    # fresh readback round trip against the REAL process carries the same identity
    record = flow.channel_record()
    live = record.client.command("thread/read", threadId=session_id, includeTurns=False, timeout=10)
    assert live["thread"]["id"] == session_id
    # zero-model boundary on the real process: no turn of any kind exists
    assert live["thread"]["turns"] == []
    assert [event["method"] for event in record.client.events()
            if (event.get("method") or "").startswith("turn/")] == []
    assert record.client._turn_requests == {} and record.client._last_turn is None
    assert flow.factory.opens == 1 and record.client._initialized is True
    assert record.spec.argv == tuple(app_server_argv(EXECUTABLE))


def test_real_projection_reads_and_query_consume_no_invocation_and_issue_no_ticket(flow):
    flow.prepare()
    flow.start()
    ref = flow.unit.public_ref
    before = len(flow.issuer.issued)
    assert flow.projection.read_unit(ref) is flow.unit or flow.projection.read_unit(ref).public_ref == ref
    assert flow.projection.read_session(ref).state == "confirmed"
    correlation = flow.binding().creation_correlation
    outcome = flow.provider.query_step(correlation, flow.query_context())
    assert outcome["state"] == "confirmed"
    assert outcome["unitRef"] == ref
    assert len(flow.issuer.issued) == before + 1  # only the query context was issued
    assert list(flow.records._tickets) == []  # no ticket is issued or left for a read
    consumed = [entry for entry in flow.issuer.issued.values() if entry["state"] == "consumed"]
    assert len(consumed) == 2  # exactly the two effect claims (prepare, start) were consumed
    verified = [entry for entry in flow.issuer.issued.values() if entry["verified"]]
    assert len(verified) == 3  # the read-only query was verified + observed, never consumed
    assert flow.channel_record().client._request_seq == 3  # query never wrote an RPC


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
        with pytest.raises((CodexProviderRefused, CodexProjectionRefused)):
            flow.provider.start({"unitRef": candidate}, context)
        assert flow.issuer.issued[context]["state"] == "issued"  # claim unconsumed
        assert flow.factory.opens == 0
    assert flow.binding().state == "notCreated"


def test_real_lost_thread_start_receipt_keeps_unknown_and_is_never_resent(tmp_path):
    flow = Flow(tmp_path, timeouts={"create_thread": 0.001})  # controlled receipt-loss deadline
    try:
        flow.prepare()
        with pytest.raises(CodexProviderRefused, match="unknown"):
            flow.start()
        binding = flow.binding()
        assert binding.state == "unknown" and binding.native_facts is None
        record = flow.channel_record()
        client = record.client
        # req-1 initialize, req-2 thread/start; the timeout consumed no extra id
        assert list(client._pending) == ["req-2"] and client._request_seq == 2
        # real process: the thread WAS created. Recover the LATE original receipt
        # read-only (recover_request never writes), then confirm its identity.
        thread_id = client.recover_request("req-2", timeout=30)["thread"]["id"]
        observed = client.command("thread/read", threadId=thread_id, includeTurns=False, timeout=10)
        assert observed["thread"]["id"] == thread_id
        # the original opening owns the fence: a second start cannot dispatch
        context = flow.issuer.issue("start", "second-start", "start-input")
        with pytest.raises(UnitRecordsRefused, match="cannot be dispatched again"):
            flow.provider.start({"unitRef": flow.unit.public_ref}, context)
        assert flow.factory.opens == 1
        # the only native writes ever were req-1 and req-2 plus this q read: no resend
        assert client._request_seq == 3
        outcome = flow.provider.query_step(binding.creation_correlation, flow.query_context())
        assert outcome == {"unitRef": dict(flow.unit.public_ref), "state": "unknown"}
        assert client._pending == {} and flow.issuer.allowed is True
    finally:
        flow.close()


@pytest.mark.parametrize("facet,revoke_after,expect_initialize", [
    ("allowed", 1, False),        # revoke after open: initialize never sent
    ("active", 2, True),          # revoke after initialize: thread/start never sent
    ("epoch", 2, True),           # epoch moved after initialize: journal record expires too
])
def test_real_revocation_between_start_edges_never_creates_a_thread(flow, facet, revoke_after, expect_initialize):
    flow.prepare()
    flow.projection._start_authority = RevokingAuthority(flow.issuer, facet=facet, revoke_after=revoke_after)
    with pytest.raises(CodexProviderRefused, match="unknown"):
        flow.start()
    record = flow.channel_record()
    client = record.client
    assert flow.factory.opens == 1
    assert client._request_seq == (1 if expect_initialize else 0)
    assert client._initialized is expect_initialize
    assert client._turn_requests == {} and client._last_turn is None
    binding = flow.records.owner_read_session(flow.unit.unit_ref)
    # an epoch move also expires the record ticket itself: opening is retained
    assert binding.state == ("opening" if facet == "epoch" else "unknown")
    assert binding.native_facts is None  # no native thread identity was ever recorded


def test_real_revoked_authority_before_start_never_consumes_or_opens(flow):
    flow.prepare()
    flow.issuer.allowed = False
    context = flow.issuer.issue("start", "start-revoked", "start-input")
    with pytest.raises(UnitRecordsRefused, match="current authority revoked"):
        flow.provider.start({"unitRef": flow.unit.public_ref}, context)
    assert flow.factory.opens == 0
    assert flow.binding().state == "notCreated"
    assert flow.issuer.issued[context]["state"] == "issued"  # unconsumed claim


def test_real_environment_is_isolated_under_the_unit_private_root(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    env = record.spec.env
    private_home = os.path.abspath(flow.roots["home"])
    private_codex = os.path.abspath(flow.roots["codexHome"])
    assert record.spec.cwd == flow.roots["cwd"]
    assert set(env) == ISOLATED_ENV_KEYS
    assert env["HOME"] == private_home and env["CODEX_HOME"] == private_codex
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert env[key].startswith(private_home), key
    for key in _TOKEN_ENV_KEYS:
        assert key not in env
    # the REAL child process was actually started with the isolated identity
    pid = record.channel._process.pid
    environ = {}
    with open(f"/proc/{pid}/environ", "rb") as handle:
        for raw in handle.read().split(b"\x00"):
            if b"=" in raw:
                name, value = raw.split(b"=", 1)
                environ[name.decode()] = value.decode()
    assert environ["HOME"] == private_home and environ["CODEX_HOME"] == private_codex
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "COPILOT_TOKEN"):
        assert key not in environ
    session_id = flow.binding().native_facts["sessionId"]
    live = record.client.command("thread/read", threadId=session_id, includeTurns=False, timeout=10)
    assert live["thread"]["cwd"] == flow.roots["cwd"]
    assert live["thread"]["turns"] == []  # zero model, zero turns


def test_real_connect_binds_original_lease_and_revoke_cuts_every_write(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    unit_ref = flow.unit.public_ref
    session_id = flow.binding().native_facts["sessionId"]
    grant = flow.lease_port.grant(unit_ref)
    assert isinstance(grant, CodexGrant) and grant.epoch == 0
    with pytest.raises(TypeError):
        copy.copy(grant)
    connection = flow.provider.connect(unit_ref, grant)
    assert isinstance(connection, LeasedConnection)
    # zero-model consumer write through the lease: identity round trip only
    observed = connection.command("thread/read", threadId=session_id, includeTurns=False)
    assert observed["thread"]["id"] == session_id and observed["thread"]["turns"] == []
    # forged, foreign and copied authorizations can never bind this connection
    for foreign in ({}, "lease", flow.lease_port.grant({"environmentNamespace": "other", "unitId": "u",
                                                        "ownerProviderRef": PROVIDER,
                                                        "sourceRevision": "sha256:" + "b" * 64})):
        with pytest.raises(CodexLeaseRefused, match="absent, revoked or of an old activation"):
            flow.provider.connect(unit_ref, foreign)
    pending_grant = flow.lease_port.grant(unit_ref)
    with pytest.raises(CodexLeaseRefused, match="already granted to another writer"):
        flow.provider.connect(unit_ref, pending_grant)
    # typed revoke: this connection and the underlying original lease both die
    flow.lease_port.revoke(unit_ref)
    with pytest.raises(CodexLeaseRefused, match="absent, revoked or of an old activation"):
        connection.command("thread/read", threadId=session_id, includeTurns=False)
    record = flow.channel_record()
    with pytest.raises(Exception, match="writer is absent, revoked"):
        record.client.command("thread/read", threadId=session_id, includeTurns=False, timeout=2)
    assert record.channel._process.poll() is None  # disconnect is not stop
    with pytest.raises(CodexLeaseRefused, match="absent, revoked or of an old activation"):
        flow.provider.connect(unit_ref, grant)  # old activation can never rebind
    assert record.client._turn_requests == {}  # no native turn was ever written


def test_real_connection_disconnect_fences_only_the_view_not_the_process(flow):
    flow.prepare()
    flow.start()
    unit_ref = flow.unit.public_ref
    session_id = flow.binding().native_facts["sessionId"]
    record = flow.channel_record()
    connection = flow.provider.connect(unit_ref, flow.lease_port.grant(unit_ref))
    assert connection.command("thread/read", threadId=session_id, includeTurns=False)["thread"]["id"] == session_id
    process = record.channel._process
    assert connection.close() is None
    assert connection.close() is None  # idempotent entry disconnect
    with pytest.raises(CodexLeaseRefused, match="fenced, disconnected or stale"):
        connection.command("thread/read", threadId=session_id, includeTurns=False)
    assert process.poll() is None              # the entry disconnect did NOT stop the unit
    assert flow.close() == 0                   # the owner's explicit shutdown reaps it
    assert process.poll() is not None          # explicitly waited, reaped by identity


def test_real_channel_shutdown_reaps_every_owned_process(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    process = record.channel._process
    assert process.poll() is None
    assert flow.close() == 0
    assert process.poll() is not None  # explicitly waited, reaped by identity
    assert record.client.close() is None  # idempotent view close after the reap
    with pytest.raises(CodexChannelRefused):
        flow.factory.record(record.entry)  # the channel record was released


# -- real factory/projection/lease contract counter-examples -------------------


def test_real_factory_refuses_queries_bad_paths_and_missing_install(flow, tmp_path):
    factory = flow.factory
    roots = dict(flow.roots)
    start_facts = {"action": "start", "query": False}
    with pytest.raises(CodexChannelRefused):
        factory.open(roots, {"action": "query", "query": True})  # read-only never opens
    with pytest.raises(CodexChannelRefused):
        factory.open(roots, {"action": "start", "query": None})
    relative = dict(roots)
    relative["cwd"] = "relative/path"
    with pytest.raises(CodexChannelRefused):
        factory.open(relative, start_facts)
    escape = dict(roots)
    escape["home"] = str(tmp_path / "elsewhere")
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(CodexChannelRefused):
        factory.open(escape, start_facts)  # one common private root parent is real
    assert factory.opens == 0
    with pytest.raises(CodexChannelRefused):
        CodexAppServerChannelFactory("relative-codex")
    with pytest.raises(CodexChannelRefused):
        CodexAppServerChannelFactory(str(tmp_path / "missing-binary"))


def test_verified_private_roots_accepts_only_the_layout(tmp_path):
    good = {"cwd": str(tmp_path / "cwd"), "home": str(tmp_path / "home"),
            "codexHome": str(tmp_path / "codex")}
    assert dict(verified_private_roots(good)) == good
    for bad in (None,
                {"cwd": "x", "home": "/a", "codexHome": "/b"},
                {"cwd": "/a", "home": "/a", "codexHome": "/b"},
                {"cwd": "/a", "home": "/a/home", "codexHome": "/somewhere/codex"},
                {"cwd": "/a", "home": "/b/home", "codexHome": "/c/codex", "extra": 1},
                {"cwd": "/etc/passwd", "home": "/shadow", "codexHome": "/usr"},
                {"cwd": None, "home": "/a/home", "codexHome": "/a/codex"}):
        with pytest.raises(CodexChannelRefused):
            verified_private_roots(bad)


def test_projection_refuses_forged_references_and_absent_publication_owner(flow):
    flow.prepare()
    ref = flow.unit.public_ref
    projection = flow.projection
    before = len(flow.issuer.issued)
    with pytest.raises(UnitRecordsRefused, match="unit missing"):
        projection.read_unit({**ref, "unitId": "different-unit"})
    with pytest.raises(CodexProjectionRefused, match="owner source"):
        projection.read_unit({**ref, "sourceRevision": "sha256:" + "d" * 64})
    with pytest.raises(CodexProjectionRefused, match="owner-bound"):
        projection.read_unit({"environmentNamespace": ENVIRONMENT, "unitId": ref["unitId"]})
    assert len(flow.issuer.issued) == before  # owner reads consumed no invocation
    with pytest.raises(CodexProjectionRefused, match="core publication owner"):
        projection.publication_facts(ref)


def test_projection_records_and_descriptor_composition(flow):
    flow.prepare()
    with pytest.raises(CodexProjectionRefused, match="another journal owner"):
        flow.projection.attach_owner(object())
    methods = flow.provider.descriptor.supported_methods
    assert methods[-2:] == ("connect", "query_step")
    assert "apply_configuration" not in methods
    with pytest.raises(CodexCapabilityUnsupported):
        flow.provider.apply_configuration(flow.unit.public_ref, object(),
                                          flow.issuer.issue("applyConfiguration", "config", "x"))


def test_projection_query_refuses_foreign_correlations(flow):
    flow.prepare()
    flow.start()
    with pytest.raises(CodexProjectionRefused, match="not observed by this projection owner"):
        flow.provider.query_step("not-a-creation-correlation", flow.query_context())
    flow.issuer.permitted = False
    with pytest.raises(UnitRecordsRefused, match="current directory permission revoked"):
        flow.provider.query_step(flow.binding().creation_correlation, flow.query_context())
    assert flow.channel_record().client._request_seq == 3  # queries never wrote RPCs


# -- P: real unified termination face on the real process ------------------------


def test_real_stop_terminates_the_process_with_exit_evidence(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    record = flow.channel_record()
    process = record.channel._process
    assert process.poll() is None
    # zero-model boundary on the real process before the stop effect
    assert record.client._turn_requests == {} and record.client._last_turn is None
    assert [event["method"] for event in record.client.events()
            if (event.get("method") or "").startswith("turn/")] == []
    result = flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    assert result["state"] == "confirmed" and result["action"] == "stop"
    termination = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
    assert termination["state"] == "confirmed" and termination["projection"] == "owner-read"
    outcome = termination["outcome"]
    assert outcome["nativeRealm"] == PROTOCOL and outcome["action"] == "stop"
    assert outcome["processRef"] == "codex-process/" + str(process.pid)
    # the exit evidence is the real subprocess's own exit code, reaped by identity
    assert outcome["exitRef"] == "exit/" + str(int(process.returncode))
    assert process.poll() is not None
    assert not os.path.exists(f"/proc/{process.pid}")
    wait_private_root_clean(flow)  # no residual process anywhere under the private root
    assert flow.private_child_pids() == []
    assert flow.binding().state == "confirmed"  # stop never rewrites the original session truth


def test_real_release_after_stop_frees_owned_records_and_revokes_grants(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    unit_ref = flow.unit.public_ref
    grant = flow.lease_port.grant(unit_ref)
    process = flow.channel_record().channel._process
    assert flow.provider.stop(unit_ref, flow.issuer.issue("stop", "stop", "stop-input"))["state"] == "confirmed"
    result = flow.provider.release(unit_ref, flow.issuer.issue("release", "release", "release-input"))
    assert result["state"] == "confirmed" and result["action"] == "release"
    termination = flow.records.owner_read_termination(flow.unit.unit_ref, "release")
    assert termination["state"] == "confirmed"
    assert termination["outcome"]["processRef"] == "codex-process/" + str(process.pid)
    assert termination["outcome"]["exitRef"] == "exit/" + str(int(process.returncode))
    assert flow.provider._channels == {}  # owned live handles are gone
    wait_private_root_clean(flow)  # no residual process under the private root
    assert flow.private_child_pids() == []
    with pytest.raises(CodexProviderRefused):
        flow.provider.describe_access(unit_ref)  # released owner grants no access
    with pytest.raises(CodexLeaseRefused):
        flow.provider.lease_port.bind(unit_ref, grant, object())  # revoked grant can never rebind
    with pytest.raises(UnitRecordsRefused, match="already"):
        flow.provider.release(unit_ref, flow.issuer.issue("release", "release-2", "x"))


def test_real_release_refuses_live_owned_unit_and_never_kills(flow):
    flow.prepare()
    assert flow.start()["state"] == "confirmed"
    process = flow.channel_record().channel._process
    release = flow.issuer.issue("release", "release", "release-input")
    with pytest.raises(CodexProviderRefused, match="requires stop before release"):
        flow.provider.release(flow.unit.public_ref, release)
    assert flow.provider._channels != {}          # nothing was taken away
    assert process.poll() is None                 # the owned unit was not killed
    assert process.pid in flow.private_child_pids()  # it still lives under the private root
    assert flow.records.owner_read_termination(flow.unit.unit_ref, "release") is None
    assert flow.issuer.issued[release]["state"] == "issued"  # authority never consumed


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
        with pytest.raises(CodexProviderRefused, match="unknown"):
            flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
        termination = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
        assert termination["state"] == "opening" and termination["outcome"] is None  # the hold stays
        flow.factory.close = original_close
    finally:
        flow.close()
