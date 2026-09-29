"""Order 086: the last lap of 65 - a real parent Harness issuing the call.

Stage 1 measures whether the synthesized bridge entry can reach a
production-shaped claude-code turn at all: the family declares its reviewed
`settings.json` as a read-only projection and the bridge's declared MCP target
is that same path, so the two either merge or the round is impossible.
"""
from __future__ import annotations

from pathlib import Path

import json
import pathlib
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
PEER_SOURCE = "tests/harness_remote/home_probe_acp_peer.mjs"
PEER_BYTES = Path(__file__).resolve().parent / "fixtures" / "home_probe_acp_peer.mjs"

CONFIG = b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}'
LOOPBACK_BASE_URL = "http://127.0.0.1:1"


def _profile_spec(harness: str):
    from ordessa_harness.registry import load_builtin_registry

    definition = load_builtin_registry().get(harness)
    return getattr(definition, "profile", None)


def _wire(client, runtime, method: str, params: dict) -> dict:
    body = client.post(f"/wire/v1/{method}", headers={
        "Authorization": f"Bearer {runtime.token}"},
        json={"jsonrpc": "2.0", "id": method, "method": method, "params": params}).json()
    assert "result" in body, f"{method}: {json.dumps(body)[:400]}"
    return body["result"]


def _claude_deployment(*, projected: bool) -> dict:
    """The claude-code production entry, adapter swapped to the reviewed peer.

    Everything else - notably `projectionFiles` - is what production declares,
    because the collision this order has to settle is between the projection
    and the bridge's MCP target, not between the bridge and a test fixture.
    The one exception is the model control: the fixture peer advertises no
    config options, so a frozen `deepseek-flash` is refused inside the sidecar
    ("Harness model is not available") exactly as the hermes note documents for
    an adapter without a model control. Stage 2 runs the control for real.
    """
    from ordessa_harness.claude import production

    entry = production.harness_deployment(
        artifact_token=production.ARTIFACT_NAME, tree_digest="sha256:" + ("0" * 64),
        adapter_environment=dict(production.ADAPTER_ENVIRONMENT))
    entry["adapter"] = {"command": "/usr/bin/node", "args": [], "source": PEER_SOURCE}
    entry["runtimeArtifactMounts"] = []
    del entry["modelControlId"]
    del entry["controlOptions"]
    if not projected:
        entry["projectionFiles"] = []
    return {"schemaVersion": 1, "harnesses": [entry]}


def _runtime_root(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "server"


@pytest.fixture()
def granted_parent(tmp_path, monkeypatch):
    """A Server on the claude production deployment with one delegation edge."""
    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore
    from fastapi.testclient import TestClient

    import ordessa_server_compat.composition as runtime_module

    from ordessa_harness.claude import production

    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == PEER_SOURCE:
            return PEER_BYTES.read_bytes()
        if relative == production.SETTINGS_SOURCE:
            return json.dumps(
                production.loopback_settings_document(LOOPBACK_BASE_URL),
                indent=2, sort_keys=True).encode() + b"\n"
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    monkeypatch.setenv("AGENT_BOX_HTTP_PORT", "18991")
    (tmp_path / "project").mkdir(exist_ok=True)
    document = tmp_path / "deployment.json"
    document.write_text(json.dumps(_claude_deployment(projected=True)), encoding="utf-8")
    store = MemorySecretStore(values={})
    runtime = build_runtime_from_sidecar_deployment(
        _runtime_root(tmp_path), document, plugin_root=PLUGIN, secret_store=store)
    runtime.start()
    try:
        from ordessa_server.credentials import CredentialRecords

        token_file = tmp_path / "086-fake-token"
        token_file.write_bytes(b"086-fake-key-not-a-secret")
        token_file.chmod(0o600)
        credential_id, locator = store.import_file(token_file, "api-key")
        CredentialRecords(runtime.database).register(credential_id, "api-key", locator)
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            opened = client.post("/wire/v1/workspaces.open", headers={
                "Authorization": f"Bearer {runtime.token}"}, json={
                "jsonrpc": "2.0", "id": "o", "method": "workspaces.open",
                "params": {"requestId": "086-open", "path": str(tmp_path / "project"),
                           "environment": {"kind": "local", "host": None,
                                           "user": None}}}).json()["result"]
            # No provider/model wiring here: the peer in this entry carries no
            # model control (see _claude_deployment), so a Profile needs only a
            # credential. The real control and the real model run in stage 2.
            def make(name: str, key: str) -> dict:
                return runtime.plugin_host.provided_port('product.repository').profiles.create(
                    key=key, request_digest=key, name=name, harness_type="claude-code",
                    config_digest=runtime.objects.publish(CONFIG).digest,
                    credential_id=credential_id)[1]

            parent = make("alpha", "p")
            child = make("beta", "c")
            runtime.plugin_host.provided_port('product.repository').profiles.grant_subagent(
                parent_id=parent["profile_id"], child_id=child["profile_id"])
            yield (runtime, client, parent, child, opened["workspace"]["id"],
                   _runtime_root(tmp_path))
    finally:
        runtime_module._sidecar_deployment_file = original_file
        runtime.stop()


def _send(client, runtime, workspace_id: str, profile_id: str, request_id: str) -> dict:
    return client.post("/wire/v1/sessions.createAndSend", headers={
        "Authorization": f"Bearer {runtime.token}"}, json={
        "jsonrpc": "2.0", "id": request_id, "method": "sessions.createAndSend",
        "params": {"requestId": request_id, "workspaceId": workspace_id,
                   "profileId": profile_id, "overrides": [],
                   "message": {"text": "hello", "attachments": []}}}).json()


def _settled_turn(runtime, session_id: str, timeout: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = runtime.plugin_host.provided_port('product.repository').get_session(session_id)
        if session["turns"] and session["turns"][0]["state"] in {"completed", "failed"}:
            return session["turns"][0]
        time.sleep(0.05)
    return runtime.plugin_host.provided_port('product.repository').get_session(session_id)["turns"][0]


def _materialized_documents(root: pathlib.Path, name: str) -> list[dict]:
    documents = []
    for candidate in sorted((root / "profiles").rglob(name)):
        text = candidate.read_text(encoding="utf-8")
        try:
            documents.append(json.loads(text))
        except ValueError:
            raise AssertionError(f"{candidate}: {text[:200]!r}") from None
    return documents


def _raw(root: pathlib.Path, name: str) -> dict[pathlib.Path, str]:
    return {candidate: candidate.read_text(encoding="utf-8")
            for candidate in sorted((root / "profiles").rglob(name))}


def test_a_granted_claude_parent_on_the_production_deployment_carries_the_bridge(
        granted_parent):
    """G1 precondition: the entry reaches the file the real harness reads.

    The reviewed claude-code deployment projects `settings.json` read-only, so
    the bridge cannot live there; after 086 moved the family's slot to
    `.claude.json` (the file the CLI demonstrably reads for `mcpServers`) a
    granted parent assembles, and the provider projection is left alone.
    """
    runtime, client, parent, _child, workspace_id, root = granted_parent
    result = _send(client, runtime, workspace_id, parent["profile_id"], "086-granted")
    assert "result" in result, json.dumps(result)[:500]
    turn = _settled_turn(runtime, result["result"]["session"]["id"])
    assert turn["state"] == "completed", json.dumps(turn.get("error"))[:500]
    with_entry = [document for document in _materialized_documents(root, ".claude.json")
                  if "agentbox-subagents" in document.get("mcpServers", {})]
    assert with_entry, (
        "a granted parent materialises no bridge entry: the round is impossible")
    entry = with_entry[-1]["mcpServers"]["agentbox-subagents"]
    assert entry["args"][0].endswith("subagent-bridge.mjs")
    assert entry["env"]["AGENTBOX_BRIDGE_TOKEN"], "the attempt token is minted"
    # The read-only projection is untouched by the assembly: outside a sandbox
    # the target is a placeholder the Server never writes into, and in no case
    # does the bridge land there.
    projection = _raw(root, "settings.json")
    assert projection, "the reviewed projection is gone"
    assert not any("agentbox-subagents" in text for text in projection.values()), (
        "the bridge leaked into the read-only projection")


def test_a_profile_with_no_outgoing_grant_carries_no_bridge_entry(granted_parent):
    """The counter-example: the entry is caused by the grant, not by the family.

    The child in the same deployment, on the same slot, with the same
    projection, gets no `.claude.json` at all - so the granted parent's entry
    is not something every claude-code turn receives.
    """
    runtime, client, _parent, child, workspace_id, root = granted_parent
    before = len(_materialized_documents(root, ".claude.json"))
    result = _send(client, runtime, workspace_id, child["profile_id"], "086-ungranted")
    assert "result" in result, json.dumps(result)[:500]
    turn = _settled_turn(runtime, result["result"]["session"]["id"])
    assert turn["state"] == "completed", json.dumps(turn.get("error"))[:500]
    assert len(_materialized_documents(root, ".claude.json")) == before, (
        "a Profile with zero grants materialised the bridge anyway")


def test_codex_still_collides_and_is_excluded_from_this_round():
    """The remaining gap, stated as a fact rather than hidden by a fixture.

    claude's slot moved to a file outside its projection; codex declares its
    MCP document as the very file its own production template projects
    read-only, so a granted codex parent still refuses at assembly with
    `ASSET_SLOT_CONFLICT`. 65's end-to-end test never met this because its
    fixture deployment declared no projections at all.
    """
    from ordessa_harness.codex import production as codex_production

    spec = _profile_spec("codex")
    assert spec.mcp_target in {item["target"] for item in codex_production.projection_files()}
    # claude, by contrast, no longer collides - that is the fix this round runs on.
    claude_spec = _profile_spec("claude-code")
    from ordessa_harness.claude import production as claude_production

    assert claude_spec.mcp_target not in {
        item["target"] for item in claude_production.projection_files()}


def test_the_other_registered_families_declare_no_mcp_target_at_all():
    """Stage 1 exclusion: only three families can carry an MCP document.

    The order names `pi` as the cheapest candidate; `pi` declares no MCP target,
    so it structurally cannot carry the bridge. The exclusion list is derived
    from the registry so a family that gains a target is noticed.
    """
    from ordessa_harness.registry import load_builtin_registry

    with_target, without_target = {}, {}
    for definition in load_builtin_registry().all():
        target = getattr(_profile_spec(definition.harness_type), "mcp_target", None)
        (with_target if target else without_target)[definition.harness_type] = target
    # qwen 族已退役（官方转向 qoder，本产品不再使用；注册表亦不再加载它），
    # 故它不再是"有 MCP target"的族。断言仍从注册表推导——将来某个族获得 target
    # 时，这里照样会红。
    assert sorted(with_target) == ["claude-code", "codex"]
    assert set(without_target) == {"dsh", "hermes", "kilo", "opencode", "pi"}
