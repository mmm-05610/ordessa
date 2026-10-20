"""T023 (FR-011 / SC-006): the 70-method wire/1 composed loopback.

The method list is re-collected IN THIS RUN from the live composed registry
(``build_runtime`` default product → ``runtime.wire._registry.method_ids()``)
— tasks.md pins "数量以 T002 现场为准", so the parametrization is driven by
the registry, never by a typed-out list. Each id is then driven through the
composed transport: ``POST /wire/v1/{method}`` with the data root's bearer
token over the in-process App.

Answering discipline: a typed refusal (envelope error from the published
FAMILIES set) counts as answered; what does NOT count is the registry not
knowing the method ("is not a wire/1 method") or a wall-caught crash
(the third wall stamps ``data.internalCode`` — that is the crash signature,
distinguished from a handler's own typed UNAVAILABLE refusal).
Handlers that need a real harness / real model stop at the typed boundary
here and are listed in the report's untested set; the WS leg of the loopback
is ``test_platform_t023_ws_loopback.py``.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ordessa_server.composition.runtime import build_runtime
from ordessa_interfaces.http import create_app
from server_plugin_api.wire_errors import FAMILIES

T002_BASELINE_METHOD_COUNT = 70  # AR-1/W-1 后 53；S-03 装配：providerModels 6 + modelProvider 7 + permissions 4
# （旧注 “PermissionsBackendPlugin 17 方法” 是误记：17 是这三个面之和，
# PermissionsBackendPlugin 本身只声明 permissions 4 方法。）
#
# 032 (server-compat 退役)：默认装配不再含 ordessa.server-compat 的业务面
#（sessions.*、accounts.*、assets.*、providerArtifacts.*、approvals.*、
# sendOutcome.* 等随旧超级 owner 一并退役），也不再含 skills 面；
# modelProvider 面由 7 扩展到 9（import 对 + beginTurnApplication）。
# 下面的 C0_METHOD_COUNT 按当前真实装配重算：以 59 个实测方法为基准，
# 各命名面只做存在性断言，不再做加法算术。
ACP_ADMISSION_METHOD_IDS = frozenset({
    "acp.submission.authorize", "acp.permission.authorize",
})
SANDBOX_DESCRIBE_METHOD_ID = "sandbox.describe"
#: The default Environment publishes the Pacthold-owned `/3` contract through
#: the reserved core method owner. Pin all method ids by name so a changed
#: schema cannot silently balance the live count.
AGENT_CORE_METHOD_IDS = frozenset({
    "agents.capabilities",
    "agents.profiles.list", "agents.profiles.read", "agents.profiles.readEntry",
    "agents.profiles.create", "agents.profiles.edit", "agents.profiles.clone",
    "agents.profiles.rename", "agents.profiles.archive", "agents.profiles.restore",
    "agents.profiles.preview",
    "agents.providers.list", "agents.providers.describe",
    "agents.nodes.prepare", "agents.nodes.queryPreparation",
    "agents.nodes.list", "agents.nodes.read",
    "agents.nodes.configuration.describe", "agents.nodes.configuration.inspect",
    "agents.nodes.configuration.apply", "agents.nodes.configuration.query",
    "agents.nodes.applyProfile", "agents.nodes.acquireAccess",
    "agents.nodes.recover", "agents.nodes.stop", "agents.nodes.release",
    "agents.operations.read",
})
MODEL_PROVIDER_IMPORT_METHOD_IDS = frozenset({
    "modelProvider.importApiKey", "modelProvider.queryApiKeyImport",
})
#: The two pin-drift ids 002 froze (identity-map `wireMethods.pinDrift`):
#: the live default composition is 88 while the old pin arithmetic stopped
#: at 86. Pinned here by name like every face above.
MODEL_PROVIDER_TURN_APPLICATION_METHOD_IDS = frozenset({
    "modelProvider.beginTurnApplication",
})
ACP_SESSION_HISTORY_METHOD_ID = "acp.sessions.list"
#: Current recomputation: 1 host + 5 workspace + 5 ACP + 16 model-provider
#: + 1 sandbox + 4 permissions + 27 Pacthold Agent `/3` methods.
#: Every face is asserted by name in the gate below, so a drift fails HERE
#: as a missing/unexpected id, not as silent re-balancing of arithmetic.
C0_METHOD_COUNT = 59


def _collect_live_method_ids() -> tuple[str, ...]:
    """Build the real composition once at collection and read its registry."""
    scratch = Path(tempfile.mkdtemp(prefix="ordessa-t023-registry-"))
    try:
        runtime = build_runtime(scratch / "data")
        try:
            runtime.start()
            return tuple(sorted(runtime.wire._registry.method_ids()))
        finally:
            runtime.stop()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


LIVE_METHOD_IDS = _collect_live_method_ids()


@pytest.fixture(scope="module")
def loopback():
    """The composed default-product Server on the in-process App."""
    scratch = Path(tempfile.mkdtemp(prefix="ordessa-t023-loopback-"))
    runtime = build_runtime(scratch / "data")
    try:
        runtime.start()
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        yield runtime, client
    finally:
        runtime.stop()


def _post_wire(client, headers, method, params, request_id="t023-loop"):
    return client.post(
        f"/wire/v1/{method}", headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def test_the_live_registry_holds_t002_baseline_acp_and_sandbox_describe_ids():
    """The loopback count is re-measured in this run and pinned against the
    032 recomputation of 57: the compat business faces (sessions.*,
    accounts.*, assets.*, providerArtifacts.*, approvals.*, sendOutcome.*)
    retired with ordessa.server-compat, so the old T002-baseline-plus-faces
    arithmetic no longer applies. Every remaining face is asserted BY NAME —
    a registry drift must fail HERE loudly, not silently shrink
    parametrization. The retired faces are asserted ABSENT (compat leaves no
    hidden fallback); their guarantee moved to the per-domain suites."""
    assert len(LIVE_METHOD_IDS) == C0_METHOD_COUNT, (
        f"live registry collected {len(LIVE_METHOD_IDS)} method ids this run; "
        f"032 recomputation is {C0_METHOD_COUNT}")
    assert len(set(LIVE_METHOD_IDS)) == len(LIVE_METHOD_IDS)
    assert ACP_ADMISSION_METHOD_IDS <= set(LIVE_METHOD_IDS)
    assert SANDBOX_DESCRIBE_METHOD_ID in LIVE_METHOD_IDS
    # The count alone would still balance if a pinned id were dropped and an
    # unpinned one added in its place, so the added faces are asserted by name.
    assert AGENT_CORE_METHOD_IDS <= set(LIVE_METHOD_IDS)
    assert MODEL_PROVIDER_IMPORT_METHOD_IDS <= set(LIVE_METHOD_IDS)
    assert MODEL_PROVIDER_TURN_APPLICATION_METHOD_IDS <= set(LIVE_METHOD_IDS)
    assert ACP_SESSION_HISTORY_METHOD_ID in LIVE_METHOD_IDS
    assert not any(method.startswith(("profiles.v2.", "agent.")) for method in LIVE_METHOD_IDS)
    for retired in ("sessions.list", "sessions.createAndSend", "sendOutcome.query",
                    "accounts.importAsset", "assets.publishSkill",
                    "providerArtifacts.install", "approvals.decide"):
        assert retired not in LIVE_METHOD_IDS, (
            f"{retired} survived the server-compat retirement")


def test_sandbox_describe_is_owned_by_the_selected_backend(loopback):
    runtime, _client = loopback
    descriptor = runtime.wire._registry.lookup(SANDBOX_DESCRIBE_METHOD_ID)
    assert descriptor is not None and descriptor.owner == "ordessa.sandbox"


def test_acp_admission_methods_are_owned_but_unavailable_in_default_product(loopback):
    runtime, client = loopback
    headers = {"Authorization": f"Bearer {runtime.token}"}
    hello = _post_wire(client, headers, "server.hello", {
        "clientVersions": ["wire/1"], "clientPresentationSupports": []}).json()
    assert "result" in hello, hello
    capabilities = {entry["id"]: entry for entry in hello["result"]["capabilities"]}
    for method in ACP_ADMISSION_METHOD_IDS:
        descriptor = runtime.wire._registry.lookup(method)
        assert descriptor is not None and descriptor.owner == "ordessa.harness.acp"
        supported, reason = descriptor.availability()
        assert supported is False and reason
        assert capabilities[method] == {"id": method, "supported": False, "reason": reason}
        field = "submission" if method == "acp.submission.authorize" else "decision"
        body = _post_wire(client, headers, method, {"connectionId": "absent", field: {}}).json()
        assert body["result"] == {"kind": "refused", "code": "CAPABILITY_UNSUPPORTED",
                                  "reason": "ACP channel or admission authority is unavailable"}


@pytest.mark.parametrize("method", LIVE_METHOD_IDS)
def test_every_registered_method_dispatches_and_answers_typed(loopback, method):
    """Drive one live registry id end-to-end through POST /wire/v1/{method}.

    Params are the empty object: methods with required params answer the
    typed params-shape refusal (dispatched, envelope-shaped — a refusal
    counts), the zero-required-param rows (accounts.list, assets.list) run
    their handler for real. Either way the method must be KNOWN to the
    registry and the answer must be a typed JSON-RPC envelope — never the
    unknown-method refusal, never a wall-caught crash.
    """
    _runtime, client = loopback
    headers = {"Authorization": f"Bearer {_runtime.token}"}
    response = _post_wire(client, headers, method, {})
    assert response.status_code == 200, (method, response.status_code, response.text[:200])
    body = response.json()
    assert body.get("jsonrpc") == "2.0", (method, body)
    assert body.get("id") == "t023-loop", (method, body)
    assert ("result" in body) ^ ("error" in body), (method, body)
    if "error" in body:
        error = body["error"]
        assert error["code"] in FAMILIES, (method, error)
        assert isinstance(error.get("message"), str) and error["message"], (method, error)
        assert "is not a wire/1 method" not in error["message"], \
            f"{method} is in the live registry but the dispatcher denied knowing it"
        data = error.get("data") or {}
        assert "internalCode" not in data, \
            f"{method} crashed inside its handler (third-wall signature): {error}"


def test_an_unregistered_method_name_is_the_discriminating_control(loopback):
    """Non-vacuity for the parametrized gate above: an id NOT in the registry
    must answer with exactly the refusal the gate forbids for real ids. If
    this ever returns anything else, the gate's assertions stopped biting."""
    _runtime, client = loopback
    headers = {"Authorization": f"Bearer {_runtime.token}"}
    body = _post_wire(client, headers, "t023.notARegisteredMethod", {}).json()
    assert "error" in body, body
    assert body["error"]["code"] == "INVALID_REQUEST", body
    assert "is not a wire/1 method" in body["error"]["message"], body


def test_the_wire_route_requires_the_bearer_token(loopback):
    """The loopback went through the same auth wall the contract names:
    without it every method is a 401 UNAUTHENTICATED envelope, so the
    parametrized passes above cannot have skipped authentication."""
    _runtime, client = loopback
    response = _post_wire(client, {}, "server.hello", {
        "clientVersions": ["wire/1"], "clientPresentationSupports": []})
    assert response.status_code == 401, response.text[:200]
    assert response.json()["error"]["code"] == "UNAUTHENTICATED", response.json()


def test_server_hello_answers_with_result_and_declares_every_registered_method(loopback):
    """A real RESULT (not a refusal) through the same route: the discovery
    answer must cover the exact registry the loopback parametrized over —
    the count and the ids are the same live fact, not two lists."""
    runtime, client = loopback
    headers = {"Authorization": f"Bearer {runtime.token}"}
    body = _post_wire(client, headers, "server.hello", {
        "clientVersions": ["wire/1"], "clientPresentationSupports": []}).json()
    assert "result" in body, body
    declared = {item["id"] for item in body["result"]["capabilities"]}
    assert declared == set(LIVE_METHOD_IDS), (
        sorted(declared ^ set(LIVE_METHOD_IDS)))
