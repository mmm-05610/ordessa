"""T10 integration-chain fixtures: the cross-domain controlled proof stack.

Everything in the chain is the REAL component; the only substitutions are
the two the dispatch names explicitly:

* the MCP *peer* — a controlled loopback fake server (own copy,
  ``integration_fake_stdio_server.py`` / ``integration_fake_http_server.py``,
  the ``tests/managed_client``/``tests/managed_http`` fixture SHAPE reused,
  their internals NOT imported) — the product may not talk to a real
  external MCP service in a controlled test (report.md §三);
* the harness *runtime* of the C4 chain — the in-memory controlled runtime
  of the harness's own controlled-test precedent
  (tests/harness_wiring/test_controlled_chain.py), clearly labelled, plus
  the labelling ChainProbe adapter double for wiring coverage ONLY (it
  proves the WIRING, never the brand route; the brand adapter's honesty
  refusal is a separate cell that runs the REAL adapter).

The host pieces are the real ones (tests/service precedent):
``ServerPluginHost`` + ``WireService.dispatch`` + ``McpAssetServerPlugin``
activation; the domain stores are the real on-disk ones (definition,
assignment, lease, catalog). The managed clients are the real limited-
substitute stdio/HTTP clients; the permission authority is the REAL
``ordessa_permissions_backend`` over a seeded throwaway database
(t06-wiring usage); the C4 service is the REAL
``ordessa_harness.application.ConfigurationApplicationService`` over the
real contribution carrier and sqlite ``OperationJournal``
(tests/harness_wiring precedent).

What the TEST side owns (and labels as such): the composition glue the
product assembly will own after C0 lands (integration-request 1/6/9) —
``TransportRouter`` picks the real per-transport factory for a lease, the
Q5 authority / launch-plan ports are attached to the composed service.
No production behaviour is stubbed here; every gate lives in production
code and the refusals are witnessed server-side.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_TESTS = PACKAGE_ROOT / "tests"
REPO_ROOT = PACKAGE_ROOT.parents[2]
for _directory in (PACKAGE_ROOT, _TESTS / "adapters", _TESTS / "harness_wiring"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))
_Q5_SUPPORT = REPO_ROOT / "plugins" / "permissions" / "backend" / "tests"
if str(_Q5_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_Q5_SUPPORT))

import ordessa_permissions_api as q5                       # noqa: E402
import ordessa_permissions_backend as q5_backend           # noqa: E402

# T009 relocation (t06-wiring D6, same in-process path adaptation): the
# product Database facade ships in pacthold_runtime_compat.storage; bind it
# onto the old spelling BEFORE ``import support``. Real class, zero mock.
import pacthold.storage                                    # noqa: E402
if not hasattr(pacthold.storage, "Database"):
    from pacthold_runtime_compat.storage import Database as _ProductDatabase
    pacthold.storage.Database = _ProductDatabase

import support                                             # noqa: E402 (real Q5 DB helpers)

from ordessa_harness.application import (                  # noqa: E402
    ConfigurationApplicationService, NativeReadback, OperationJournal,
    RuntimeSnapshot,
)
from ordessa_harness.contributions import (                # noqa: E402
    CONFIGURATION_POINT, POINT_API_VERSION, HarnessContributionRegistry,
)
from ordessa_harness.materialization import (               # noqa: E402
    MergeAuthority, TargetAuthority,
)
from ordessa_harness_api import (                          # noqa: E402
    AdapterContext, ApplicationTarget, Assessment, Installation,
    TargetDescriptor, TargetHandle,
)
from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost  # noqa: E402
from ordessa_server.wire.handlers import WireService       # noqa: E402
from server_plugin_api import WireError                    # noqa: E402

import native_helpers as nh                                # noqa: E402
import wiring_helpers as wh                                # noqa: E402
from adapters import claude as claude_mod                  # noqa: E402
from backend.definition import (                           # noqa: E402
    RemoteTransport, StdioTransport, definition_digest,
)
from backend.managed.client_http import (                  # noqa: E402
    HttpClientPolicy, make_http_client_factory,
)
from backend.managed.client_stdio import (                 # noqa: E402
    StdioClientPolicy, make_stdio_client_factory,
)
from backend.managed.lease import LeaseCaller              # noqa: E402
from backend import native_binding as nb                   # noqa: E402
from backend.permission_adapter import Q5RequestBinding    # noqa: E402
from backend.plugin import McpAssetServerPlugin            # noqa: E402
from backend.secret import (                                # noqa: E402
    CredentialBinding, LaunchPlan, host_credential_port,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)

SERVER_SCOPE = "s1"
FAKE_STDIO_SCRIPT = str(Path(__file__).resolve().parent
                        / "integration_fake_stdio_server.py")

#: the credential-layer doubles use one fixed sentinel; every test asserts
#: the sentinel never appears in a wire response / fact / event surface.
SENTINEL = "s3ntin3l-chain-secret-4a71"

#: the ApplicationTarget the C4 chain service owns (tests/harness_wiring
#: shape); ``mcp.planForSubmission`` params are chosen so
#: ``backend.native_binding.application_target`` lands on exactly this.
PLAN_TARGET = ApplicationTarget(SERVER_SCOPE, "session-a", "mcp-plan", 7)


# -- controlled host credential layers (labelled host-facade doubles, -------
# tests/service FakeCredentialRecords/FakeSecretStore precedent; the adapter
# under chain IS the real backend.secret.HostCredentialPort) ------------------

class FakeCredentialRecords:
    """The shape of the host's CredentialRecords the adapter reads."""

    def __init__(self, ids=("cred-1",)):
        self.rows = {cid: {"secret_locator": f"loc-{cid}"} for cid in ids}

    def exists(self, credential_id):
        return credential_id in self.rows

    def get(self, credential_id):
        return dict(self.rows[credential_id])


class FakeSecretStore:
    """Platform SecretStore double with MUTABLE bytes: ``rotate()`` changes
    what the store hands out, which changes the HostCredentialPort's derived
    content digest — exactly the FR-08 rotation a frozen plan must catch."""

    def __init__(self, content: bytes = SENTINEL.encode()):
        self.content = content

    def read(self, locator):
        return self.content

    def rotate(self) -> None:
        self.content = ("rotated-" + str(time.time_ns())).encode()


class FakeSubmissionGate:
    """The placeholder SubmissionGate port (tests/service precedent); used
    ONLY for the one-gate conflict cell — composing it next to the real C4
    port must refuse SUBMISSION_GATE_AMBIGUOUS."""

    def plan_submission(self, *, principal, server_scope, session_ref,
                        runtime_generation, snapshot_digest,
                        credential_references):
        return {"status": "planned-by-gate", "snapshotDigest": snapshot_digest}


# -- the composition -----------------------------------------------------------

class TransportRouter:
    """Test-side composition seam (what the product assembly will wire):
    a managed lease -> the transport-correct REAL limited-substitute client
    factory. One fresh client per lease (no pooling: the real factories hold
    no cache and ``produced`` proves the count)."""

    def __init__(self, *, stdio_policy=None, http_policy=None,
                 http_launch_plan=None, http_credential_port=None):
        self.stack = None
        self.stdio_policy = stdio_policy or StdioClientPolicy()
        self.http_policy = http_policy or HttpClientPolicy(
            request_timeout=5.0, initialize_timeout=5.0, connect_timeout=5.0)
        self.http_launch_plan = http_launch_plan
        self.http_credential_port = http_credential_port
        self.wrap = None  # optional test OBSERVER wrapper (delegation only)
        self.produced: list = []

    def __call__(self, lease):
        definitions = self.stack.service.definitions
        model = definitions.read_revision(
            server_scope=lease.server_scope, definition_id=lease.definition_id,
            revision=lease.revision)
        transport = model.transport
        if isinstance(transport, StdioTransport):
            factory = make_stdio_client_factory(
                definitions, policy=self.stdio_policy,
                secret_resolver=lambda cid: self.stack.service.credential_port.read(cid)[0])
        elif isinstance(transport, RemoteTransport):
            factory = make_http_client_factory(
                definitions, policy=self.http_policy,
                launch_plan=self.http_launch_plan,
                credential_port=self.http_credential_port)
        else:  # pragma: no cover - the revision model has exactly two transports
            raise AssertionError("the test router covers no other transport")
        client = factory(lease)
        if self.wrap is not None:
            client = self.wrap(lease, client)
        self.produced.append((lease.lease_id, client))
        return client


class IntegrationStack:
    """One live composition: real host + real WireService + the Q4 plugin.

    ``server.wire.dispatch`` drives the mcp.* face (saveRevision / approve /
    assign / resolvePreview / planForSubmission / inspectConnection /
    listTools); the managed lease face is driven through the composed
    service (``service.sessions``) because no ``mcp.openSession`` wire row
    exists in the first version (contracts §1) — the stores underneath are
    the same real objects either way.
    """

    def __init__(self, tmp_path, *, plugin=None, host_ports=None) -> None:
        self.root = tmp_path
        self.registry = MethodRegistry()
        self.host_ports = dict(host_ports or {})
        self.host = ServerPluginHost(
            methods=self.registry, data_root=tmp_path / "host",
            host_ports=self.host_ports)
        # the same facade the production composition binds (runtime.py):
        # the plugin resolves MCP codes through ITS composition's aggregate
        self.host_ports.setdefault(
            "wire.error_family_resolver",
            lambda code: self.host.wire_error_families.family_for(code))
        self.plugin = plugin or McpAssetServerPlugin()
        self.active = self.host.activate(self.plugin)
        for hook in self.active.registration.start_hooks:
            hook()
        self.wire = WireService(
            server_id_provider=lambda: "t10-proof-server",
            cursor_secret=b"c" * 16, method_registry=self.registry,
            error_family_resolver=lambda code:
                self.host.wire_error_families.family_for(code))
        self.router: TransportRouter | None = None

    # -- wire face ------------------------------------------------------------

    def call(self, method, **params):
        return self.wire.dispatch(method, params)

    def expect_refusal(self, method, *, family, internal_code, **params):
        with pytest.raises(WireError) as info:
            self.wire.dispatch(method, params)
        error = info.value
        assert error.family == family, f"{method}: {error.family} != {family} ({error.message})"
        assert error.details.get("internalCode") == internal_code, error.details
        assert error.message.startswith(f"{internal_code}: "), error.message
        return error

    @property
    def service(self):
        return self.host.provided_port("asset.mcp.v2")

    # -- definitions / assignments via the wire ---------------------------------

    def install_stdio(self, definition_id: str, *, mode: str = "normal",
                      principal: str = "user-1", env: dict | None = None,
                      state_name: str | None = None) -> tuple:
        state = self.root / f"witness-{state_name or definition_id}.jsonl"
        definition = {
            "name": definition_id,
            "transport": {"stdio": {
                "command": sys.executable,
                "args": [FAKE_STDIO_SCRIPT, mode, str(state)],
                "env": (None if not env else
                        {k: {"literal": v} for k, v in env.items()}),
            }},
        }
        self.call("mcp.saveRevision", serverScope=SERVER_SCOPE,
                  principal=principal, definitionId=definition_id,
                  definition=definition, expectedVersion=0,
                  operationKey=f"op-save-{definition_id}")
        self.call("mcp.approveRevision", serverScope=SERVER_SCOPE,
                  principal=principal, definitionId=definition_id, revision=1)
        return 1, state

    def install_remote(self, definition_id: str, url: str, *,
                       headers: dict | None = None,
                       principal: str = "user-1") -> int:
        definition = {"name": definition_id,
                      "transport": {"remote": {"url": url, "headers": headers or {}}}}
        self.call("mcp.saveRevision", serverScope=SERVER_SCOPE,
                  principal=principal, definitionId=definition_id,
                  definition=definition, expectedVersion=0,
                  operationKey=f"op-save-{definition_id}")
        self.call("mcp.approveRevision", serverScope=SERVER_SCOPE,
                  principal=principal, definitionId=definition_id, revision=1)
        return 1

    def assign_enable(self, definition_id: str, *, catalog_digest: str,
                      names, principal: str = "user-1",
                      scope_kind: str = "user-default",
                      scope_id: str | None = None, revision: int = 1,
                      row_version: int = 0) -> dict:
        return self.call(
            "mcp.assign", serverScope=SERVER_SCOPE, principal=principal,
            scopeKind=scope_kind, scopeId=scope_id or principal,
            definitionId=definition_id, decision="enable",
            approvedRevision=revision,
            toolSelection={"mode": "allowNames", "names": list(names),
                           "catalogDigest": catalog_digest},
            expectedRowVersion=row_version,
            operationKey=f"op-assign-{scope_kind}-{scope_id or principal}-{definition_id}")

    # -- managed leases (through the composed service's real stores) ------------

    @staticmethod
    def caller(principal: str = "user-1", session: str = "session-1",
               generation: int = 1) -> LeaseCaller:
        return LeaseCaller(principal=principal, session_ref=session,
                           runtime_generation=generation)

    def bring_up(self, caller, definition_id: str, revision: int, *,
                 submission_id: str = "sub-1"):
        """open -> plan -> start -> observe over the REAL client factory."""
        mgr = self.service.sessions
        lease = mgr.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                              definition_id=definition_id, revision=revision)
        mgr.plan_connection(caller=caller, lease_id=lease.lease_id,
                            submission_id=submission_id)
        mgr.start_connection(caller=caller, lease_id=lease.lease_id)
        catalog = mgr.observe_catalog(caller=caller, lease_id=lease.lease_id)
        return lease, catalog

    # -- server-side witnesses ---------------------------------------------------

    @staticmethod
    def witness(state: Path) -> list:
        if not state.is_file():
            return []
        return [json.loads(line) for line in
                state.read_text(encoding="utf-8").splitlines() if line.strip()]

    @classmethod
    def calls(cls, state: Path) -> list:
        return [e for e in cls.witness(state) if e.get("event") == "call"]

    @classmethod
    def child_pids(cls, state: Path) -> list:
        return [e for e in cls.witness(state) if e.get("event") == "pid"]

    def close_service(self) -> None:
        """Test teardown: idempotent client closes (stdio clients reap
        their whole process group; http clients drop the local session)."""
        if self.router is None:
            return
        for _lease_id, client in self.router.produced:
            try:
                client.close()
            except BaseException:
                pass  # cleanup path; residual processes are killed by conftest


def make_stack(tmp_path, *, host_ports=None, plugin_kwargs=None) -> IntegrationStack:
    """The L2 chain stack: real plugin + real per-transport client router."""
    router = TransportRouter()
    kwargs = dict(plugin_kwargs or {})
    kwargs.setdefault("client_factory", router)
    stack = IntegrationStack(tmp_path, plugin=McpAssetServerPlugin(**kwargs),
                             host_ports=host_ports)
    stack.router = router
    router.stack = stack
    return stack


# -- the REAL Q5 permissions world (t06-wiring seeded-DB usage) ----------------


class MutableClock:
    """The Authorizer's injectable clock (real backend takes a clock port)."""

    def __init__(self, moment: dt.datetime) -> None:
        self.moment = moment

    def __call__(self) -> dt.datetime:
        return self.moment

    def advance(self, delta: dt.timedelta) -> None:
        self.moment = self.moment + delta


class RecordingAuthorizer(q5_backend.Authorizer):
    """The REAL backend Authorizer, keeping every (inputs, outcome) pair so
    tests assert on genuine Q5 outcome objects and the zero-consultation
    asymmetry."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.consultations: list = []

    def evaluate(self, **kwargs):
        outcome = super().evaluate(**kwargs)
        self.consultations.append((dict(kwargs), outcome))
        return outcome


def q5_binding(session_id: str, execution_id: str, native_request_id: str):
    return Q5RequestBinding(
        server_instance_id="srv-1", session_id=session_id,
        native_session_id=f"native-session-{session_id}",
        execution_id=execution_id, native_generation="gen-1",
        native_request_id=native_request_id)


def table_provider(table):
    def provider(*, session_ref, lease_id, tool_name, args_digest):
        del lease_id, tool_name, args_digest
        return table.get(session_ref)
    return provider


def map_tool_key(mapping):
    def provider(tool_name):
        return mapping.get(tool_name, tool_name)
    return provider


def intent_allowing(*, rules, intent_id="intent-t10", revision=1):
    return q5.PermissionIntent.of(intent_id=intent_id, revision=revision,
                                  harness_id="codex", scope=q5.Scope.SESSION,
                                  rules=rules)


def read_allow_intent():
    """The Q5 intent that allows the mapped MCP tools (tool_key ``read`` is
    inside Q5's closed TOOL_KEYS vocabulary)."""
    return intent_allowing(rules=(q5.TypedRule(
        tool=q5.ToolIdentity("read"), action=q5.RuleAction.ALLOW),))


@dataclass
class Q5World:
    """The real Q5 backend composed on a throwaway database (t06-wiring)."""

    root: Path
    database: object = None
    facts: object = None
    policies: object = None
    clock: MutableClock = field(default_factory=lambda: MutableClock(NOW))

    @classmethod
    def build(cls, root: Path) -> "Q5World":
        world = cls(root=root)
        world.database = support.seeded_database(root / "q5-data")
        support.seed_session(world.database, session_id="session-1",
                             execution_id="turn-1")
        support.seed_session(world.database, session_id="session-2",
                             execution_id="turn-2")
        world.facts = q5_backend.ApprovalFacts(world.database)
        world.facts.ensure_schema()
        world.policies = q5_backend.PolicyRepository(world.database)
        world.policies.ensure_schema()
        world.policies.store_ceiling(support.admin_ceiling())
        return world

    def default_bindings(self):
        return {"session-1": q5_binding("session-1", "turn-1", "nr-s1"),
                "session-2": q5_binding("session-2", "turn-2", "nr-s2")}

    def make_authorizer(self, *, intent=None) -> RecordingAuthorizer:
        provider = (lambda: intent) if intent is not None else None
        return RecordingAuthorizer(
            facts=self.facts, policies=self.policies, clock=self.clock,
            **({} if provider is None else {"intent_provider": provider}))

    def make_adapter(self, *, authorizer, intent=None, tool_key_map=None,
                     bindings=None):
        from backend.permission_adapter import Q5PermissionAuthority

        return Q5PermissionAuthority(
            authorizer=authorizer,
            binding_provider=table_provider(
                bindings if bindings is not None else self.default_bindings()),
            ceiling_provider=self.policies.ceilings_current,
            intent_provider=None if intent is None else (lambda: intent),
            tool_key_provider=None if tool_key_map is None
            else map_tool_key(tool_key_map))

    def expected_operation(self, *, tool_key, argument_digest,
                           native_request_id, session_id="session-1",
                           execution_id="turn-1", intent=None):
        """The Q5 operation the adapter must have built, via the SAME support
        builders the published proof uses (digests match symbol-for-symbol)."""
        return support.make_operation(
            ceilings=self.policies.ceilings_current(), intent=intent,
            tool_key=tool_key, argument_digest=argument_digest,
            principal="user-1", session_id=session_id,
            execution_id=execution_id, native_request_id=native_request_id)

    def settle_allow(self, *, tool_key, argument_digest, native_request_id,
                     session_id="session-1", execution_id="turn-1"):
        """Drive the REAL approval loop for one operation: the pending row
        (already written by Q5) -> user allow decision -> native receipt.
        Returns the approval id."""
        op = self.expected_operation(tool_key=tool_key,
                                     argument_digest=argument_digest,
                                     native_request_id=native_request_id,
                                     session_id=session_id,
                                     execution_id=execution_id)
        approval_id = q5.approval_id_for(
            operation_digest=op.operation_digest,
            native_request_id=native_request_id)
        recorded = self.facts.decide(approval_id=approval_id, decision="allow",
                                     scope={"kind": "once"}, expected_version=1,
                                     request_id=f"decide-{native_request_id}",
                                     now=NOW)
        assert isinstance(recorded, q5.Recorded), recorded
        self.facts.record_native_receipt(approval_id, q5.NativeReceipt.of(
            native_request_id=native_request_id, approval_id=approval_id,
            confirmed=True, observed_at=NOW))
        return approval_id


def wire_q5(stack: IntegrationStack, world: Q5World, *, intent=None,
            tool_key_map=None):
    """Compose the REAL Q5 authority into the managed lane (the product
    assembly injection point; the seam itself is production code
    ``backend.permissions.PermissionAuthority``)."""
    authorizer = world.make_authorizer(intent=intent)
    adapter = world.make_adapter(authorizer=authorizer, intent=intent,
                                 tool_key_map=tool_key_map)
    stack.service.sessions.permission_authority = adapter
    return adapter, authorizer


def args_digest_for(tool_name: str, arguments: dict) -> str:
    """The exact digest the manager books (backend/managed/session_manager)."""
    return definition_digest({"tool": tool_name, "arguments": dict(arguments)})


# -- the REAL Harness C4 chain (tests/harness_wiring precedent) ----------------


class ControlledRuntime:
    """The fake harness instance: real private-generation materialization,
    zero process, zero network. LABELLED evidence double of the runtime —
    same shape as tests/harness_wiring + the harness's own controlled test;
    everything else in the chain (adapters, merge, journal, permits) is the
    real thing."""

    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        self.root.chmod(0o700)
        self.activate_count = 0
        self.revision = "base-1"
        self.bytes = None

    def capture(self, target):
        descriptor = TargetDescriptor(
            TargetHandle(nb.instance_target_id("claude-code"), 7),
            "file", "json", "instance", (("mcpServers",),))
        context = AdapterContext(
            (descriptor,),
            Installation("claude-code", (1, 0, 0), (1, 0, 0), "ev:installed"),
            "acp", "instance", "ev:capability")
        resource = ("mcp", "config.json")
        authority = MergeAuthority(
            (TargetAuthority(descriptor, resource, array_fields=(("mcpServers",),)),),
            scope="instance")
        return RuntimeSnapshot(target, context, authority, {}, {}, self.root,
                               {}, self.revision, "native-version-1", 1,
                               "auth-1", "secret-ref-1")

    def activate_generation(self, target, lease):
        self.activate_count += 1
        self.bytes = lease.read_bytes(resource := ("mcp", "config.json"))
        self.revision = "applied-1"

    def observe(self, target):
        import hashlib
        assert self.bytes is not None
        digest = hashlib.sha256(self.bytes).hexdigest()
        return NativeReadback(target, "native-session-1", self.revision,
                              json.loads(self.bytes), ((("mcp", "config.json"),
                                                        digest),),
                              "ev:readback:" + digest, ("private-generation",))


class SignedPermit:
    def __init__(self):
        self.calls = 0

    def verify(self, principal, target, plan, operation_key, permit):
        self.calls += 1
        return (principal == "alice" and target == PLAN_TARGET
                and permit == "signed:mcp-permit")


class ChainProbeAdapter(claude_mod.configuration_adapter().__class__):
    """Labelling double of the claude MCP adapter for chain coverage ONLY
    (same documented pattern as tests/harness_wiring): ``assess`` is forced
    to ``supported`` so the REAL C4 machinery executes the MCP intents end
    to end. It proves the WIRING; it proves nothing about the claude route —
    the brand adapter keeps answering unknown (separate honesty cell), and
    ``proven_routes`` stays empty everywhere."""

    def assess(self, context, request):
        base = super().assess(context, request)
        if base.status == "unknown":
            return Assessment("supported", evidence_ref="controlled:fake-harness-chain")
        return base


def compose_c4(tmp_path, adapter):
    """carrier host + registry + journal: the harness_wiring compose() shape."""
    registry = HarnessContributionRegistry()
    carrier = ServerPluginHost(methods=MethodRegistry(),
                               data_root=tmp_path / "carrier")
    carrier.register_contribution_point(CONFIGURATION_POINT, POINT_API_VERSION,
                                        handler=registry.configuration_handler,
                                        exclusive=False)
    carrier.activate(wh.AdapterContributionPlugin("ordessa.asset.mcp", adapter))
    runtime = ControlledRuntime(tmp_path / "generations")
    permits = SignedPermit()
    journal = OperationJournal(tmp_path / "operations.sqlite")
    service = ConfigurationApplicationService(
        principal="alice", target=PLAN_TARGET, carrier=carrier, runtime=runtime,
        permits=permits, journal=journal)
    return runtime, permits, journal, service


def make_plan_stack(tmp_path, *, chain_double: bool = True,
                    with_placeholder_gate: bool = False,
                    host_ports=None) -> dict:
    """A stack whose ``harness.configuration_service`` port IS the real C4
    service; the native planner seam is the real brand compile over the real
    definition store (what the product assembly wires)."""
    adapter = (ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)
               if chain_double else claude_mod.configuration_adapter())
    runtime, permits, journal, c4 = compose_c4(tmp_path, adapter)
    ports = dict(host_ports or {})
    ports["harness.configuration_service"] = c4
    if with_placeholder_gate:
        ports["harness.submission_gate"] = FakeSubmissionGate()
    holder: dict = {}

    def planner(snapshot, harness):
        holder.setdefault("planner_calls", []).append(harness)

        def provide(definition_id, revision):
            return holder["stack"].service.definitions.read_revision(
                server_scope=SERVER_SCOPE, definition_id=definition_id,
                revision=revision)

        return claude_mod.compile(snapshot, nh.instance_target("claude"),
                                  nh.DictProvenance({}), revision_provider=provide,
                                  expected_catalog_digests={})

    stack = make_stack(tmp_path / "mcp-host", host_ports=ports,
                       plugin_kwargs={"native_planner": planner,
                                      "lane_by_definition": {"natsrv": "native",
                                                             "mansrv": "managed"}})
    holder["stack"] = stack
    return {"stack": stack, "runtime": runtime, "permits": permits,
            "journal": journal, "c4": c4, "planner_calls": holder.setdefault(
                "planner_calls", [])}


PLAN_PARAMS = {  # the submission params that land on PLAN_TARGET (native_binding)
    "sessionRef": "session-a", "runtimeGeneration": 7,
    "targetSession": "mcp-plan", "harness": "claude-code",
}


def plan_full_setup(stack) -> dict:
    """Save/approve both definitions, observe the managed one for its
    catalog, enable both assignments — the snapshot a real plan freezes."""
    _rev, state = stack.install_stdio("mansrv", mode="normal", principal="alice")
    _rev2, state2 = stack.install_stdio("natsrv", mode="normal",
                                        principal="alice", state_name="natsrv")
    caller = stack.caller(principal="alice", session="session-9", generation=9)
    lease, catalog = stack.bring_up(caller, "mansrv", 1)
    _lease2, catalog2 = stack.bring_up(caller, "natsrv", 1)
    stack.assign_enable("mansrv", catalog_digest=catalog.catalog_digest,
                        names=list(catalog.tool_names), principal="alice")
    stack.assign_enable("natsrv", catalog_digest=catalog2.catalog_digest,
                        names=list(catalog2.tool_names), principal="alice")
    closed = stack.service.sessions.close_lease(caller=caller,
                                                lease_id=lease.lease_id,
                                                owner_id=lease.owner_id)
    stack.service.sessions.close_lease(caller=caller, lease_id=_lease2.lease_id,
                                       owner_id=_lease2.owner_id)
    assert closed["state"] == "closed"
    return {"state": state, "state2": state2}
