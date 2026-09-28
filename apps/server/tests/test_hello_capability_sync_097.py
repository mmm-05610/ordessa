"""Order 097: `server.hello`'s capability table *is* the dispatch table.

Every gate here is about one sentence: a method this Server can dispatch must be
declared, and one it cannot dispatch must not be. The hand-maintained list had
fallen 37 methods behind, so the question worth testing is not "is the table
long enough today" but "can it go quiet again tomorrow" - which is what the
counter-example below answers, rather than decorates.
"""
from __future__ import annotations

from test_wire_v1 import Wire, registry

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server.transport.http import create_app
from ordessa_workspace.local_environment import LocalEnvironmentProvider

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

#: The 27 ids the hand-maintained `CAPABILITY_IDS` declared at this order's
#: baseline, kept as data on purpose: the growth must not flip one `supported`
#: bit of what was already honest, and a test cannot say that without naming
#: what "before" was.
DECLARED_AT_BASELINE = (
    "workspaces.browse", "workspaces.open", "workspaces.list", "workspaces.archive",
    "profiles.list", "profiles.create", "profiles.update", "profiles.updateConfig",
    "profiles.archive", "providerModels.list", "providerModels.create",
    "providerModels.update", "providerModels.archive", "config.describe",
    "config.resolve", "sessions.list", "sessions.update", "sessions.archive",
    "sessions.createAndSend", "sessions.send", "sessions.switchProfile",
    "sendOutcome.query", "queue.get", "queue.withdraw", "runs.stop",
    "approvals.decide", "history.snapshot",
)

#: The 37 methods that existed on the Server and were declared as absent,
#: measured against one real hello at this order's baseline.
MISSING_AT_BASELINE = (
    "server.hello", "workspaces.gitStatus", "executions.list", "profiles.clone",
    "profiles.setPermissions", "profiles.memory", "profiles.subagentGrants",
    "profiles.grantSubagent", "profiles.revokeSubagent", "providerModels.probeModels",
    "providerModels.probeConnection", "assets.list", "assets.publishSkill",
    "assets.publishMcp", "assets.publishPlugin", "assets.bind", "assets.unbind",
    "assets.bindings", "assets.syncCatalog", "assets.catalog",
    "assets.installFromCatalog", "assets.probe", "hooks.list", "hooks.create",
    "hooks.update", "hooks.setEnabled", "hooks.delete", "hooks.triggers",
    "accounts.list", "accounts.create", "accounts.bind", "accounts.importAsset",
    "providerArtifacts.list", "providerArtifacts.install", "providerArtifacts.rollback",
    "usage.aggregate", "usage.export",
)

#: The methods this tree added *after* the baseline measurement, by name. The
#: 097 rule is "a hand-maintained list cannot rot in silence", so growth is
#: allowed only when it is named here: an unnamed new method still fails the
#: gate below, and a dropped one leaves a hole in this tuple.
#: (HD003, `docs/acp-channel-minimal-seam.md` §1: the managed ACP channel pair
#: and the single-run-record read that closes it.)
ADDED_SINCE_BASELINE = (
    "acp.channel.open", "acp.channel.release", "executions.get",
)
ACP_ADMISSION_METHODS = (
    "acp.submission.authorize", "acp.permission.authorize",
)


@pytest.fixture
def hello(tmp_path, request):
    """One real `server.hello` through the transport, on the composition asked for.

    The client context closes in teardown instead of being abandoned mid-test,
    so a mutated dispatch table cannot leak into the next case.
    """
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(
                                harnesses=registry() if request.param == "harnessed" else None))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        api = Wire(client, {"Authorization": f"Bearer {runtime.token}"})
        yield runtime, api, api.ok("server.hello", HELLO)


def _hello_on_composition(root, *, sandbox_status):
    """A real `server.hello` on a composition whose only knob is the sandbox probe.

    The other cases in this file inherit whatever this host can run; here the
    blocker rows are the thing under test, so the probe is pinned explicitly, and
    the answer is taken through the transport because the Server's own startup -
    schema and all - is part of what makes the answer reachable.
    """
    runtime = build_runtime(root / "data")
    runtime.plugin_host.provided_port('compat.handlers').workspaces.local = LocalEnvironmentProvider(
        sandbox_probe=lambda: {"status": sandbox_status, "code": "binary_missing"})
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        api = Wire(client, {"Authorization": f"Bearer {runtime.token}"})
        return api.ok("server.hello", HELLO)


@pytest.mark.parametrize("hello", ["plain"], indirect=True)
def test_the_table_is_the_dispatch_table_and_nothing_more(hello):
    """G1: three statements of "what exists" have to agree, without duplicates.

    The dispatch registry answers a call, each plugin's declared shape
    validates it, and hello advertises it. Requiring all three to agree is
    what makes "handler added, everything else forgotten" fail loudly: the
    registry refuses a descriptor whose shape and handler do not arrive
    together, and a declaration that never reached the registry (or a
    registry row with no declaration behind it) shows up as a difference
    against `plugin_host.declared_shapes()`.
    """
    runtime, _, result = hello
    declared = [item["id"] for item in result["capabilities"]]
    dispatched = list(runtime.wire._handlers)
    shapes = list(runtime.plugin_host.declared_shapes())

    duplicates = sorted({name for name in declared if declared.count(name) > 1})
    assert duplicates == [], f"the table declares a method twice: {duplicates}"
    assert set(declared) == set(dispatched), (
        f"hello lags or invents: undeclared={set(dispatched) - set(declared)} "
        f"invented={set(declared) - set(dispatched)}")
    assert set(declared) == set(shapes), (
        f"the shape table and the outward table diverge: "
        f"no_shape={set(declared) - set(shapes)} no_handler={set(shapes) - set(declared)}")
    assert declared == dispatched, "the table's order is the dispatch table's own order"


@pytest.mark.parametrize("hello", ["plain"], indirect=True)
def test_the_37_methods_missing_at_baseline_are_all_declared_now(hello):
    """The point of the order, checked by name rather than by count.

    "64 = 27 + 37" is arithmetic a future change can satisfy while dropping two
    methods and adding two others, so both halves are asserted by membership.
    """
    _, _, result = hello
    declared = {item["id"] for item in result["capabilities"]}
    assert len(MISSING_AT_BASELINE) == 37, "the baseline measurement is part of this gate"
    assert sorted(declared - set(DECLARED_AT_BASELINE) - set(ADDED_SINCE_BASELINE)
                  - set(ACP_ADMISSION_METHODS)) == sorted(
        MISSING_AT_BASELINE), "post-baseline growth must be named explicitly"
    assert set(DECLARED_AT_BASELINE) <= declared
    assert set(ADDED_SINCE_BASELINE) <= declared
    assert set(ACP_ADMISSION_METHODS) <= declared
    entries = {item["id"]: item for item in result["capabilities"]}
    for method in ACP_ADMISSION_METHODS:
        assert entries[method]["supported"] is False
        assert entries[method]["reason"] == "ACP admission authority is unavailable"


@pytest.mark.parametrize("hello", ["plain"], indirect=True)
def test_a_method_dropped_from_dispatch_diverges_and_the_gate_bites(hello):
    """The counter-example the whole order exists for.

    Derivation alone cannot catch a missing handler - both sides of that
    equality shrink together. The gate that bites is the one against the *other*
    statement: retire `usage.export` from the live registry and hello honestly
    follows it down to 66 while the plugin's declaration still says 67. If
    this case ever stops reporting the hole, the registry has stopped being
    the one table hello is fed from.
    """
    runtime, _, result = hello
    service = runtime.wire
    shapes = set(runtime.plugin_host.declared_shapes())
    before = {item["id"] for item in result["capabilities"]}
    assert before == shapes, "the two tables must agree before a mutation means anything"

    service.retire("usage.export")
    after = {item["id"] for item in service.hello(HELLO)["capabilities"]}

    assert after == before - {"usage.export"}, (
        "hello did not follow the dispatch table - it is being fed from somewhere else")
    assert shapes - after == {"usage.export"}, (
        f"the divergence against the shape table is no longer visible: {shapes ^ after}")
    assert len(after) == len(shapes) - 1


@pytest.mark.parametrize("hello", ["plain"], indirect=True)
def test_hello_now_declares_its_own_discovery_method(hello):
    """The stage-2 decision, pinned: the table is never blind to its own entry.

    `server.hello` was in the difference set, so declaring it is a choice. Left
    undeclared, a client that gates a control on the table would have to
    special-case the one method it read the table with.
    """
    _, _, result = hello
    entries = {item["id"]: item for item in result["capabilities"]}
    assert entries.get("server.hello") == {"id": "server.hello", "supported": True}


@pytest.mark.parametrize("hello", ["harnessed"], indirect=True)
def test_the_two_probe_methods_are_declared_and_supported(hello):
    """G2: what the trial run bought, answered from the table rather than by luck.

    `Test connection` / `Refresh from provider` are gated on these two ids, so a
    declared-but-false row leaves the button dead for a reason nobody can act on,
    and an absent row leaves it dead in silence.
    """
    _, _, result = hello
    entries = {item["id"]: item for item in result["capabilities"]}
    for method in ("providerModels.probeModels", "providerModels.probeConnection"):
        entry = entries.get(method)
        assert entry is not None, f"{method} is not declared at all"
        assert entry["supported"] is True, f"{method} dispatches but is not offered: {entry}"
        assert "reason" not in entry, entry
    assert entries["providerModels.list"]["supported"] is True


def test_the_baseline_deployment_answers_the_pre_existing_27_verbatim(tmp_path):
    """G3: the blocker semantics are reproduced entry by entry, both branches.

    The stage-1 observation saw eleven honest `false`s on a composition with no
    harnesses and no execution port; both knobs are pinned here instead of
    inherited, so the case says the same thing on a host that can run a sandbox
    and on one that cannot.
    """
    blocked = {
        **dict.fromkeys(("workspaces.browse", "workspaces.open", "workspaces.list",
                         "workspaces.archive"), "LOCAL_SANDBOX_UNAVAILABLE"),
        **dict.fromkeys(("sessions.list", "sessions.update", "sessions.archive",
                         "sessions.createAndSend", "sessions.send",
                         "sessions.switchProfile", "sendOutcome.query"),
                        "EXECUTION_CAPABILITY_UNAVAILABLE"),
    }
    closed = _hello_on_composition(tmp_path / "closed", sandbox_status="unavailable")
    entries = {item["id"]: item for item in closed["capabilities"]}
    for method, code in blocked.items():
        assert entries[method] == {"id": method, "supported": False, "reason": code}
    moved = [method for method in DECLARED_AT_BASELINE
             if entries[method]["supported"] is (method in blocked)]
    assert moved == [], f"blocker semantics moved on {moved}"
    stray = [method for method in DECLARED_AT_BASELINE
             if "reason" in entries[method] and method not in blocked]
    assert stray == [], f"a supported method started carrying a reason: {stray}"

    opened = _hello_on_composition(tmp_path / "opened", sandbox_status="available")
    after = {item["id"]: item for item in opened["capabilities"]}
    for method, code in blocked.items():
        if method.startswith("sessions.") or method == "sendOutcome.query":
            assert after[method] == {"id": method, "supported": False, "reason": code}, (
                f"{method} moved without the execution port changing")
        else:
            assert after[method] == {"id": method, "supported": True}, (
                f"{method} stayed blocked with an available sandbox: {after[method]}")


@pytest.mark.parametrize("hello", ["plain"], indirect=True)
def test_an_id_that_no_rule_covers_still_answers_supported(hello):
    """The fallback is pinned, not inherited by accident.

    Most of the 67 rows carry no availability predicate, so the registry
    answers `(True, None)` for them - right for support state, wrong for
    existence, which is why an id outside the registry is answered `False`
    by `_capability` and refused by dispatch: the two questions stay in two
    places.
    """
    runtime, api, _ = hello
    assert runtime.wire._capability("queue.get") == (True, None)
    assert runtime.wire._capability("nothing.here") == (False, "UNKNOWN_METHOD")
    refused = api.err("nothing.here", {})
    assert refused["code"] == "INVALID_REQUEST", refused
    assert "nothing.here" in refused["message"], refused
