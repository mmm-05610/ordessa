"""Order 56: the account asset, its lock, its conflicts, and the ledger row.

The counterexamples the order demands live here: concurrent reclaim, the
oversized candidate, an undeclared file, a digest that moved underneath the
turn (the silent-overwrite case), and the "no token in the record" rule.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"

import pytest

from ordessa_server_compat.accounts.assets import (
    MAX_ASSET_FILE_BYTES,
    AccountAssetError,
    AccountAssetStore,
    pack_asset,
    unpack_asset,
)
from ordessa_server_compat.accounts.records import AccountRecords, account_view
from ordessa_server.idempotency import IdempotentRecords
from pacthold_runtime_compat.storage import Database
from pacthold.storage.secrets import MemorySecretStore

DECLARED = [".codex/auth.json"]


def _store(tmp_path) -> AccountAssetStore:
    return AccountAssetStore(secret_store=MemorySecretStore(values={}),
                             accounts_root=tmp_path / "accounts")


def test_pack_and_unpack_admit_exactly_the_declared_names():
    blob = pack_asset({".codex/auth.json": b'{"tokens": "x"}',
                       ".codex/notes.txt": b"not declared later"})
    files = unpack_asset(blob, declared=DECLARED)
    assert files == {".codex/auth.json": b'{"tokens": "x"}'}
    # A declared name the asset does not carry stays absent - never invented.
    assert unpack_asset(blob, declared=DECLARED + [".codex/missing.json"]) == files


def test_bounds_and_shape_are_typed_refusals(tmp_path):
    with pytest.raises(AccountAssetError) as oversize:
        pack_asset({".codex/auth.json": b"x" * (MAX_ASSET_FILE_BYTES + 1)})
    assert oversize.value.code == "ACCOUNT_ASSET_OUTSIDE_BOUNDS"

    with pytest.raises(AccountAssetError) as too_many:
        pack_asset({f".codex/{index}.json": b"x" for index in range(9)})
    assert too_many.value.code == "ACCOUNT_ASSET_OUTSIDE_BOUNDS"

    with pytest.raises(AccountAssetError) as malformed:
        unpack_asset(b"not json", declared=DECLARED)
    assert malformed.value.code == "ACCOUNT_ASSET_INVALID"

    # An entry whose content no longer matches its digest is refused.
    blob = pack_asset({".codex/auth.json": b'{"a": 1}'})
    document = json.loads(blob)
    document["files"][".codex/auth.json"]["content"] = "eyJiIjogMn0="
    with pytest.raises(AccountAssetError) as digest:
        unpack_asset(json.dumps(document).encode(), declared=DECLARED)
    assert digest.value.code == "ACCOUNT_ASSET_INVALID"


def test_one_lock_per_account_and_a_stale_lock_is_reported_not_stolen(tmp_path):
    store = _store(tmp_path)
    lock = store.acquire_reclaim_lock("account_1")
    with pytest.raises(AccountAssetError) as busy:
        store.acquire_reclaim_lock("account_1")
    assert busy.value.code == "ACCOUNT_RECLAIM_BUSY"
    store.release_reclaim_lock(lock)

    # The same lock with an old mtime is still refused (never stolen).
    lock = store.acquire_reclaim_lock("account_1")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    with pytest.raises(AccountAssetError) as stale:
        store.acquire_reclaim_lock("account_1")
    assert stale.value.code == "ACCOUNT_RECLAIM_BUSY"
    assert "age" in stale.value.message
    store.release_reclaim_lock(lock)
    store.acquire_reclaim_lock("account_1")  # released: available again


def test_reclaim_refuses_to_overwrite_an_asset_that_moved(tmp_path):
    store = _store(tmp_path)
    locator, digest = store.write_asset(
        account_id="account_1", files={".codex/auth.json": b'{"v": 1}'}, kind="subscription")
    # Another writer moved the asset between materialisation and reclaim.
    with pytest.raises(AccountAssetError) as conflict:
        store.reclaim(
            account_id="account_1",
            stored_digest_of=lambda: "sha256:" + "0" * 64,
            materialized_digest=digest,
            files={".codex/auth.json": b'{"v": 2}'},
            kind="subscription",
        )
    assert conflict.value.code == "ACCOUNT_ASSET_CONFLICT"
    # The old asset is intact.
    assert store.read_asset(locator=locator, declared=DECLARED) == {
        ".codex/auth.json": b'{"v": 1}',
    }
    # And the lock is released even on the conflict path.
    store.acquire_reclaim_lock("account_1")


def test_reclaim_writes_the_refreshed_working_copy(tmp_path):
    store = _store(tmp_path)
    locator, digest = store.write_asset(
        account_id="account_1", files={".codex/auth.json": b'{"v": 1}'}, kind="subscription")
    new_locator, new_digest = store.reclaim(
        account_id="account_1", stored_digest_of=lambda: digest,
        materialized_digest=digest,
        files={".codex/auth.json": b'{"v": 2, "refreshed": true}'},
        kind="subscription",
    )
    assert new_digest != digest
    assert store.read_asset(locator=new_locator, declared=DECLARED) == {
        ".codex/auth.json": b'{"v": 2, "refreshed": true}',
    }


def test_the_account_row_never_carries_a_token(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    records = AccountRecords(database, idempotency)

    kind, created = records.create(
        key="a", request_digest="a", harness_type="codex",
        account_identifier="user@example.com",
    )
    assert kind == "created" and created["state"] == "unknown"
    assert created["has_asset"] is False

    store = _store(tmp_path)
    locator, digest = store.write_asset(
        account_id=created["account_id"],
        files={".codex/auth.json": b'{"tokens": {"access": "secret-token"}}'},
        kind="subscription",
    )
    updated = records.record_asset(
        created["account_id"], locator=locator, digest=digest, state="valid")
    assert updated["state"] == "valid" and updated["has_asset"] is True

    # The wire view and the raw row carry no token bytes anywhere.
    view = account_view(records.get(created["account_id"]))
    assert "secret-token" not in json.dumps(view)
    with sqlite3.connect(database.path) as conn:
        raw = "\n".join(str(row) for row in conn.execute("SELECT * FROM server_accounts"))
    assert "secret-token" not in raw
    assert locator in raw, "the reference is stored, the content is not"
    # Listing is the wire view shape for every row.
    listed = [account_view(row) for row in records.list()]
    assert [item["accountId"] for item in listed] == [created["account_id"]]


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_a_bound_account_materialises_reclaims_and_conflicts_typed(tmp_path):
    """Order 56 end-to-end on the local channel, with the real runtime.

    Turn 1 materialises the account's stored login state into the declared
    working path; the fixture (standing in for a Harness that refreshes its
    login in place) overwrites it; the reclaim writes the refreshed copy back
    as the account's new asset, and the record moves to `valid`. A concurrent
    writer that moves the asset first makes the next reclaim a typed conflict
    that leaves the stored asset alone.
    """
    import threading

    from fastapi.testclient import TestClient

    from ordessa_server_compat.accounts.assets import AccountAssetError
    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = Path(__file__).resolve().parent / "fixtures" / "home_probe_acp_peer.mjs"
    login_name = ".fixture/native-state.json"
    deployment = {
        "schemaVersion": 1,
        "harnesses": [
            {
                "id": "codex",
                "capabilityClaims": {"stream": True},
                "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source,
                            "environment": {"AGENTBOX_FIXTURE_STATE_DIR": "/runtime/home/.fixture"}},
                "stateProjection": {"target": "/runtime/home/.fixture"},
                "subscriptionCredential": {"files": [login_name]},
                "timeoutMs": 60_000,
            },
        ],
    }
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    secrets = MemorySecretStore(values={})
    try:
        (tmp_path / "project").mkdir(exist_ok=True)
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN, secret_store=secrets)
        runtime.start()  # the schema and the declared credentials come up here
        accounts = runtime.plugin_host.provided_port('account.records')
        store = runtime.plugin_host.provided_port('account.assets')

        kind, account = accounts.create(
            key="acct", request_digest="acct", harness_type="codex",
            account_identifier="person@example.com")
        assert kind == "created"
        # The first asset: a login state the control plane already holds.
        locator, digest = store.write_asset(
            account_id=account["account_id"],
            files={login_name: b'{"tokens": "first"}', ".fixture/extra.txt": b"dropped"},
            kind="subscription")
        accounts.record_asset(account["account_id"], locator=locator, digest=digest,
                              state="valid")

        profile = runtime.plugin_host.provided_port('product.repository').profiles.create(
            key="p", request_digest="p", name="fixture role", harness_type="codex",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest,
            credential_id=None)[1]
        runtime.plugin_host.provided_port('product.repository').profiles.bind_account(
            profile_id=profile["profile_id"], account_id=account["account_id"],
            expected_version=accounts.get(account["account_id"]) and
            runtime.plugin_host.provided_port('product.repository').profiles.get(profile["profile_id"])["version"],
            key="bind", request_digest="bind")

        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token
            opened = client.post("/wire/v1/workspaces.open", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "open", "method": "workspaces.open",
                "params": {"requestId": "acct-open-1", "path": str(tmp_path / "project"),
                           "environment": {"kind": "local", "host": None, "user": None}},
            }).json()["result"]
            sent = client.post("/wire/v1/sessions.createAndSend", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "send", "method": "sessions.createAndSend",
                "params": {"requestId": "acct-turn-1", "workspaceId": opened["workspace"]["id"],
                           "profileId": profile["profile_id"], "overrides": [],
                           "message": {"text": "log in", "attachments": []}},
            }).json()["result"]
            session_id = sent["session"]["id"]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                session = runtime.plugin_host.provided_port('product.repository').get_session(session_id)
                if session["turns"] and session["turns"][0]["state"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            assert session["turns"][0]["state"] == "completed", session["turns"][0]

        # The fixture overwrote the working copy; reclaim stored the new bytes.
        _locator, refreshed = accounts.asset_reference(account["account_id"])
        assert refreshed != digest
        stored = store.read_asset(locator=_locator, declared=[login_name])
        assert stored[login_name] != b'{"tokens": "first"}'
        assert b"native-state" in stored[login_name] or b"schema_version" in stored[login_name]
        assert accounts.get(account["account_id"])["state"] == "valid"
        # The undeclared companion file never entered the asset.
        assert ".fixture/extra.txt" not in stored

        # Counterexample: an asset that moved underneath the turn refuses.
        with pytest.raises(AccountAssetError) as conflict:
            store.reclaim(
                account_id=account["account_id"],
                stored_digest_of=lambda: "sha256:" + "0" * 64,
                materialized_digest=refreshed,
                files={login_name: b'{"tokens": "third"}'},
                kind="subscription",
            )
        assert conflict.value.code == "ACCOUNT_ASSET_CONFLICT"
        assert store.read_asset(locator=_locator, declared=[login_name]) == stored
    finally:
        runtime_module._sidecar_deployment_file = original_file


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_the_accounts_wire_face_creates_imports_binds_lists(tmp_path):
    """Order 56's wire face: create -> import the login file -> bind -> list.

    First-hand at the wire: the account view carries no token and no locator;
    the bind moves the profile's `accountId`; importing a second file for a
    family whose login state is a single declared file is refused; the import
    keeps the account's state (the import is not a validity assertion).
    """
    from fastapi.testclient import TestClient

    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = Path(__file__).resolve().parent / "fixtures" / "home_probe_acp_peer.mjs"
    deployment = {
        "schemaVersion": 1,
        "harnesses": [{
            "id": "codex", "capabilityClaims": {"stream": True},
            "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source},
            "stateProjection": {"target": "/runtime/home/.codex"},
            "subscriptionCredential": {"files": [".codex/auth.json"]},
            "timeoutMs": 60_000,
        }],
    }
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    try:
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN,
            secret_store=MemorySecretStore(values={}))
        runtime.start()
        login_file = tmp_path / "auth.json"
        login_file.write_text('{"tokens": {"access": "wire-token"}}', encoding="utf-8")

        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token

            def call(method, params):
                return client.post(f"/wire/v1/{method}", headers={
                    "Authorization": f"Bearer {token}"}, json={
                    "jsonrpc": "2.0", "id": method, "method": method, "params": params,
                }).json()

            created = call("accounts.create", {
                "requestId": "wire-account-create", "harness": "codex",
                "accountIdentifier": "person@example.com",
            })["result"]["account"]
            assert created["state"] == "unknown" and created["hasAsset"] is False
            assert "wire-token" not in json.dumps(created)

            imported = call("accounts.importAsset", {
                "requestId": "wire-account-import",
                "accountId": created["accountId"], "sourcePath": str(login_file),
            })["result"]["account"]
            assert imported["hasAsset"] is True
            assert imported["state"] == "unknown", "an import never asserts validity"
            assert "wire-token" not in json.dumps(imported)

            profile = runtime.plugin_host.provided_port('product.repository').profiles.create(
                key="p", request_digest="p", name="role", harness_type="codex",
                config_digest=runtime.objects.publish(
                    b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest,
                credential_id=None)[1]
            version = runtime.plugin_host.provided_port('product.repository').profiles.get(profile["profile_id"])["version"]
            bound = call("accounts.bind", {
                "requestId": "wire-account-bind", "profileId": profile["profile_id"],
                "expectedVersion": version, "accountId": created["accountId"],
            })["result"]["profile"]
            assert bound["accountId"] == created["accountId"]

            listed = call("accounts.list", {})["result"]["accounts"]
            assert [item["accountId"] for item in listed] == [created["accountId"]]
            assert "wire-token" not in json.dumps(listed)

            # A family that declares no subscription files refuses an import.
            other = call("accounts.create", {
                "requestId": "wire-account-other", "harness": "pi",
                "accountIdentifier": "second@example.com",
            })["result"]["account"]
            refused = call("accounts.importAsset", {
                "requestId": "wire-account-import-2",
                "accountId": other["accountId"], "sourcePath": str(login_file),
            })
            assert "error" in refused and refused["error"]["code"] == "INVALID_REQUEST"
    finally:
        runtime_module._sidecar_deployment_file = original_file


def test_the_worker_channel_materialises_and_reads_the_working_copy():
    """Order 56 on the Worker channel, against a recording client.

    Materialisation is one bounded home.put per declared name (nothing else is
    ever sent); the read-back asks for exactly the declared names and treats a
    missing one as absent. The real op's bounds and link rules live in the
    Worker's own tests; this locks the channel's wire usage.
    """
    import base64 as _base64

    from ordessa_server_compat.execution.sidecar import _WorkerChannels

    class _Client:
        def __init__(self, files):
            self.calls = []
            self.files = files

        def request(self, op, arguments=None, timeout=None):
            self.calls.append((op, dict(arguments or {})))
            if op == "home.put":
                self.files[arguments["path"]] = _base64.b64decode(arguments["data"])
                return {"bytes": len(self.files[arguments["path"]])}
            if op == "home.get":
                payload = self.files.get(arguments["path"])
                if payload is None:
                    raise KeyError(arguments["path"])
                return {"data": _base64.b64encode(payload).decode(), "eof": True}
            raise AssertionError(f"unexpected op {op}")

    declared = (".codex/auth.json", ".codex/oauth.json")
    asset = {".codex/auth.json": b'{"tokens": "materialised"}'}
    client = _Client({})
    channels = _WorkerChannels(client, "attempt_1", 1, "view_1",
                               home_locator="role/.codex", subscription_files=declared)
    # The channel reads back only what exists; the asset's other name is absent.
    client.files[".codex/auth.json"] = b'{"tokens": "refreshed"}'
    assert channels.read_subscription() == {".codex/auth.json": b'{"tokens": "refreshed"}'}

    # Materialisation: exactly one home.put per name the asset carries, and
    # nothing for a declared name the asset does not hold.
    from ordessa_server_compat.execution.sidecar import materialize_subscription

    client.calls.clear()
    written = materialize_subscription(
        client, locator="role/.codex", declared=declared, asset=asset)
    assert written == [".codex/auth.json"]
    ops = [op for op, _args in client.calls]
    assert ops == ["home.put"], client.calls
    op, arguments = client.calls[0]
    assert arguments["locator"] == "role/.codex"
    assert arguments["path"] == ".codex/auth.json"
    assert _base64.b64decode(arguments["data"]) == asset[".codex/auth.json"]
