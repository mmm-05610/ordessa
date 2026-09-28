"""Order 129: `accounts.importAsset` has to actually read its `requestId`.

`AUD-B-012` measured the shape-vs-use gap: the locked contract requires the key
(`_PARAM_SHAPES` above the handler), the shape gate refused a request without it,
and the handler never looked at it - so a retried import executed a second time,
and because `write_asset` names a fresh locator on every call the retry also
moved the account's asset reference. No `CONFLICT_REQUEST` was ever possible.

The family rule this order is checked against is "one path, not three":
`accounts.create` and `accounts.bind` already de-duplicate through
`IdempotentRecords`, so the gates below compare the three methods rather than
asserting an invention.

Every gate drives the real wire over a `TestClient` with
`raise_server_exceptions=False`. The replay claim is measured by counting the
side effect (`write_asset`), not by reading a log line.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
REPORT = REPO / "docs/server-round1/import-asset-request-id-129.md"

from ordessa_server_compat.accounts.assets import AccountAssetStore
from ordessa_server.wire import handlers as handlers_module
from ordessa_server_compat import core_wire as compat_wire

PEER_SOURCE = "tests/harness_remote/home_probe_acp_peer.mjs"
PEER_BYTES = REPO / "tests" / "server" / "fixtures" / "home_probe_acp_peer.mjs"

DEPLOYMENT = {
    "schemaVersion": 1,
    "harnesses": [{
        "id": "codex", "capabilityClaims": {"stream": True},
        "adapter": {"command": "/usr/bin/node", "args": [], "source": PEER_SOURCE},
        "stateProjection": {"target": "/runtime/home/.codex"},
        "subscriptionCredential": {"files": [".codex/auth.json"]},
        "timeoutMs": 60_000,
    }],
}


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A wire composition with a real secret store and one declared login file."""
    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    original_file = runtime_module._sidecar_deployment_file  # noqa: SLF001

    def deployment_file(root, relative):
        if relative == PEER_SOURCE:
            return PEER_BYTES.read_bytes()
        return original_file(root, relative)

    monkeypatch.setattr(runtime_module, "_sidecar_deployment_file", deployment_file)  # noqa: SLF001
    (tmp_path / "deployment.json").write_text(json.dumps(DEPLOYMENT), encoding="utf-8")
    runtime = build_runtime_from_sidecar_deployment(
        tmp_path / "server", tmp_path / "deployment.json", plugin_root=PLUGIN,
        secret_store=MemorySecretStore(values={}))
    runtime.start()
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                        raise_server_exceptions=False) as client:
            yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}, tmp_path
    finally:
        runtime.stop()


def call(client, headers, method, params):
    return client.post(f"/wire/v1/{method}", headers=headers, json={
        "jsonrpc": "2.0", "id": method, "method": method, "params": params})


def new_account(server, key="acct-create-1"):
    _runtime, client, headers, _tmp = server
    body = call(client, headers, "accounts.create", {
        "requestId": key, "harness": "codex",
        "accountIdentifier": "person@example.com"}).json()
    return body["result"]["account"]["accountId"]


def login_file(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def counted_asset_writes(server, monkeypatch):
    """Count the real side effect: how many times an asset was written.

    Counting the response would prove nothing - the pre-129 handler answered
    `hasAsset: true` on both attempts, which is exactly why the defect survived.
    """
    runtime = server[0]
    writes = []
    original = AccountAssetStore.write_asset

    def counting(self, **kwargs):
        result = original(self, **kwargs)
        writes.append((kwargs["account_id"], result[0]))
        return result

    monkeypatch.setattr(AccountAssetStore, "write_asset", counting)
    return writes


# -- G1: a retry replays, and the side effect happens once ------------------

def test_a_retry_of_one_import_replays_and_writes_the_asset_once(server, monkeypatch):
    runtime, client, headers, tmp_path = server
    writes = counted_asset_writes(server, monkeypatch)
    account_id = new_account(server)
    params = {"requestId": "import-retry-1", "accountId": account_id,
              "sourcePath": str(login_file(tmp_path, "auth-1.json", '{"tokens":"first"}'))}

    first = call(client, headers, "accounts.importAsset", params)
    second = call(client, headers, "accounts.importAsset", params)

    assert first.status_code == 200 and "result" in first.json(), first.text
    assert second.status_code == 200 and "result" in second.json(), second.text
    assert len(writes) == 1, f"the import executed {len(writes)} times for one requestId"
    assert second.json() == first.json(), "a replay did not answer identically"
    assert runtime.plugin_host.provided_port('compat.handlers').accounts.asset_reference(account_id)[0] == writes[0][1], (
        "the account's asset reference moved under a retry")


def test_a_replayed_import_leaves_exactly_one_idempotency_row_and_one_asset(server, monkeypatch):
    runtime, client, headers, tmp_path = server
    writes = counted_asset_writes(server, monkeypatch)
    account_id = new_account(server)
    params = {"requestId": "import-retry-2", "accountId": account_id,
              "sourcePath": str(login_file(tmp_path, "auth-2.json", '{"tokens":"second"}'))}
    for _attempt in range(3):
        call(client, headers, "accounts.importAsset", params)
    locators = {locator for _account, locator in writes}
    assert len(locators) == 1, locators
    with runtime.plugin_host.provided_port('compat.handlers').accounts.database.read() as conn:
        rows = conn.execute(
            "SELECT key, request_digest FROM server_idempotency WHERE scope=?",
            ("accounts.importAsset",)).fetchall()
    assert len(rows) == 1, [dict(row) for row in rows]


def test_a_different_key_for_the_same_bytes_is_a_new_request_not_a_replay(server, monkeypatch):
    """Idempotency is per request, not per content: the siblings behave this way
    (two `accounts.create` keys make two accounts), and the order asks for the
    same rule here rather than a content-addressed de-duplication."""
    _runtime, client, headers, tmp_path = server
    writes = counted_asset_writes(server, monkeypatch)
    account_id = new_account(server)
    path = str(login_file(tmp_path, "auth-3.json", '{"tokens":"third"}'))
    first = call(client, headers, "accounts.importAsset",
                 {"requestId": "import-new-1", "accountId": account_id, "sourcePath": path})
    second = call(client, headers, "accounts.importAsset",
                  {"requestId": "import-new-2", "accountId": account_id, "sourcePath": path})
    assert "result" in first.json() and "result" in second.json()
    assert len(writes) == 2, writes
    assert writes[0][1] != writes[1][1], "write_asset stopped naming a fresh locator"


# -- G2: the same key with different bytes is a typed conflict --------------

def test_the_same_key_with_a_changed_file_is_a_conflict_request(server, monkeypatch):
    runtime, client, headers, tmp_path = server
    counted_asset_writes(server, monkeypatch)
    account_id = new_account(server)
    call(client, headers, "accounts.importAsset", {
        "requestId": "import-conflict-1", "accountId": account_id,
        "sourcePath": str(login_file(tmp_path, "auth-4.json", '{"tokens":"one"}'))})
    response = call(client, headers, "accounts.importAsset", {
        "requestId": "import-conflict-1", "accountId": account_id,
        "sourcePath": str(login_file(tmp_path, "auth-5.json", '{"tokens":"two"}'))})
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert error["code"] == "CONFLICT_REQUEST", error
    assert error["details"]["internalCode"] == "IDEMPOTENCY_CONFLICT", error
    assert runtime.plugin_host.provided_port('compat.handlers').accounts.asset_reference(account_id)[0] is not None


def test_the_conflict_family_matches_the_sibling_that_uses_the_same_layer(server):
    """"同族不许三套" measured, not asserted from a table: `accounts.create`
    hits the same `IDEMPOTENCY_CONFLICT` and must surface the same family."""
    _runtime, client, headers, _tmp = server
    call(client, headers, "accounts.create", {
        "requestId": "create-conflict-1", "harness": "codex",
        "accountIdentifier": "one@example.com"})
    theirs = call(client, headers, "accounts.create", {
        "requestId": "create-conflict-1", "harness": "codex",
        "accountIdentifier": "two@example.com"})
    assert theirs.status_code == 200, theirs.text
    error = theirs.json()["error"]
    assert error["code"] == "CONFLICT_REQUEST", error
    assert error["details"]["internalCode"] == "IDEMPOTENCY_CONFLICT", error


def test_one_key_cannot_import_into_two_different_accounts(server, monkeypatch):
    """The digest covers the target, so re-using a key on another account is a
    conflict rather than a second write. The refusal is the point; which check
    answers first is recorded in the report (shape and existence come earlier)."""
    _runtime, client, headers, tmp_path = server
    writes = counted_asset_writes(server, monkeypatch)
    first_account = new_account(server, key="acct-pair-1")
    second_account = new_account(server, key="acct-pair-2")
    params = {"requestId": "import-two-targets", "sourcePath":
              str(login_file(tmp_path, "auth-8.json", '{"tokens":"eight"}'))}
    ok = call(client, headers, "accounts.importAsset",
              {**params, "accountId": first_account})
    assert "result" in ok.json(), ok.text
    conflict = call(client, headers, "accounts.importAsset",
                    {**params, "accountId": second_account})
    assert conflict.json()["error"]["code"] == "CONFLICT_REQUEST", conflict.text
    assert len(writes) == 1, writes


def test_a_request_without_the_key_is_refused_by_the_shape_before_any_write(server, monkeypatch):
    """The contract required `requestId` all along (this is the declared half);
    129 is about the used half. Both are pinned so neither can quietly go."""
    runtime = server[0]
    required, optional = compat_wire._PARAM_SHAPES["accounts.importAsset"]  # noqa: SLF001
    assert "requestId" in required and "requestId" not in optional
    _runtime, client, headers, tmp_path = server
    writes = counted_asset_writes(server, monkeypatch)
    account_id = new_account(server)
    response = call(client, headers, "accounts.importAsset", {
        "accountId": account_id,
        "sourcePath": str(login_file(tmp_path, "auth-6.json", '{"tokens":"six"}'))})
    assert response.status_code == 200, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST", response.text
    assert writes == []


# -- G4: the siblings did not move -----------------------------------------

def test_a_retry_of_accounts_create_still_makes_exactly_one_account(server):
    _runtime, client, headers, _tmp = server
    params = {"requestId": "create-replay-1", "harness": "codex",
              "accountIdentifier": "replay@example.com"}
    first = call(client, headers, "accounts.create", params).json()
    second = call(client, headers, "accounts.create", params).json()
    assert first["result"]["account"]["accountId"] == second["result"]["account"]["accountId"]
    listed = call(client, headers, "accounts.list", {}).json()["result"]["accounts"]
    assert [item["accountId"] for item in listed] == [first["result"]["account"]["accountId"]]


# -- the counter-example: the pre-129 handler, restored ---------------------

def _pre_129_import_asset(self, params):
    """The handler exactly as `AUD-B-012` found it: the key is validated and dropped.

    Kept short and literal - everything else about the old code path is still
    reached through the real service, so the reproduction is measured rather
    than assumed.
    """
    from pathlib import Path as _Path

    accounts, assets = self._require_accounts()
    account_id = handlers_module._bounded(params["accountId"], "accountId")  # noqa: SLF001
    account = accounts.get(account_id)
    source = _Path(handlers_module._bounded(  # noqa: SLF001
        params["sourcePath"], "sourcePath", 4096))
    if source.is_symlink() or not source.is_file():
        raise handlers_module.WireError("INVALID_REQUEST", "sourcePath must be a regular file")
    size = source.stat().st_size
    if size <= 0 or size > 256 * 1024:
        raise handlers_module.WireError(
            "INVALID_REQUEST", "the login-state file is empty or oversized")
    name = self._subscription_files_for(str(account["harness_type"]))[0]
    locator, digest_value = assets.write_asset(
        account_id=account_id, files={name: source.read_bytes()}, kind="subscription")
    accounts.record_asset(account_id, locator=locator, digest=digest_value,
                          state=str(account["state"]))
    from ordessa_server_compat.accounts.records import account_view
    return {"account": account_view(accounts.get(account_id))}


def test_counter_example_the_pre_129_handler_writes_twice_and_moves_the_locator(
        server, monkeypatch):
    runtime, client, headers, tmp_path = server
    writes = counted_asset_writes(server, monkeypatch)
    # The registry captured the *bound* method when the plugin registered it
    # (the same lesson order 123 learned: patching the class after startup
    # changes nothing), so the revert has to go where the wire actually looks:
    # the live method registry, through `replace_handler`. A registry mutation
    # is not monkeypatch-undoable, so the original handler is re-bound before
    # the gate returns.
    original = runtime.wire._handlers["accounts.importAsset"]  # noqa: SLF001
    try:
        runtime.wire.replace_handler(
            "accounts.importAsset", lambda params: _pre_129_import_asset(runtime.wire, params))
        account_id = new_account(server)
        params = {"requestId": "import-old-1", "accountId": account_id,
                  "sourcePath": str(login_file(tmp_path, "auth-7.json", '{"tokens":"seven"}'))}
        first = call(client, headers, "accounts.importAsset", params).json()
        second = call(client, headers, "accounts.importAsset", params).json()
        assert len(writes) == 2, "the old shape did not reproduce: it wrote only once"
        assert writes[0][1] != writes[1][1], "the locator did not move - not the defect"
        assert "error" not in second, "the old handler never conflicted - that was the defect"
        assert first["result"]["account"]["hasAsset"] and second["result"]["account"]["hasAsset"], (
            "both attempts answered successfully, which is how this survived")
    finally:
        runtime.wire.replace_handler("accounts.importAsset", original)
    assert runtime.wire._handlers["accounts.importAsset"] == original  # noqa: SLF001
    assert runtime.wire.accounts_import_asset.__func__ is not _pre_129_import_asset


def test_the_report_carries_the_three_method_comparison(server):
    """G3's evidence is the report itself: `create` / `bind` / `importAsset`
    side by side, with any difference explained. A gate on prose is weak, but
    the order asked for the table and 097 is the reason "we'll write it later"
    does not survive."""
    assert REPORT.exists(), f"{REPORT} is missing"
    text = REPORT.read_text(encoding="utf-8")
    table = [line for line in text.splitlines() if line.startswith("|")]
    for method in ("accounts.create", "accounts.bind", "accounts.importAsset"):
        assert any(method in line for line in table), method
    assert "回放" in text and "CONFLICT_REQUEST" in text
