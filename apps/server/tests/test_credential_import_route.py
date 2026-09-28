"""Importing a credential into a *running* Server, and listing what it resolves.

The one-shot CLI cannot do this while the product is up: the data root is held
by a non-blocking exclusive lock, so a second process asking for it fails with
`DATA_ROOT_IN_USE`. An interface that lets a user add a credential therefore has
to go through the running Server, which is what these two routes are for.

What matters here is that the import never carries credential material in the
request: the body names a *path*, this Server's own store reads it, and the
answer is the opaque id. The other properties are the ones an interface depends
on - the caller must repeat the path, a retry with the same key is one import,
and the listing says which ids exist without saying where their secrets live.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from pacthold.storage import MemorySecretStore


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins"  / "harness"


@pytest.fixture
def running(tmp_path):
    store = MemorySecretStore(values={})
    runtime = build_runtime(tmp_path / "data", secret_store=store)
    runtime.start()
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            yield runtime, store, client
    finally:
        runtime.stop()


def create_app(runtime):
    from ordessa_server.transport.http import create_app as build_app

    return build_app(runtime)


def headers(runtime) -> dict[str, str]:
    return {"Authorization": f"Bearer {runtime.token}"}


def source_file(tmp_path: Path, content: bytes = b"fixture-secret-value-not-a-credential") -> Path:
    source = tmp_path / "source-key"
    source.write_bytes(content)
    return source


def test_an_import_returns_the_id_and_stores_the_secret_out_of_the_request(tmp_path, running):
    runtime, store, client = running
    source = source_file(tmp_path)

    response = client.post(
        "/api/v1/credentials",
        headers={**headers(runtime), "Idempotency-Key": "cred-1"},
        json={"kind": "api-key", "source_path": str(source), "confirm_source_path": str(source)},
    )

    assert response.status_code == 201, response.json()
    credential_id = response.json()["credentialId"]
    assert credential_id.startswith("credential_")
    # The secret is in the Server's store, reachable by the record's locator -
    # and the response itself carried no material.
    record = runtime.plugin_host.provided_port('product.repository').credentials.get(credential_id, kind="api-key")
    assert store.read(record["secret_locator"]) == source.read_bytes()
    assert source.read_bytes().decode() not in json.dumps(response.json())


def test_a_mistyped_source_must_be_confirmed_before_anything_is_read(tmp_path, running):
    runtime, store, client = running
    source = source_file(tmp_path)

    response = client.post(
        "/api/v1/credentials",
        headers={**headers(runtime), "Idempotency-Key": "cred-2"},
        json={"kind": "api-key", "source_path": str(source), "confirm_source_path": str(tmp_path / "other")},
    )

    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "CREDENTIAL_SOURCE_UNCONFIRMED"
    assert runtime.plugin_host.provided_port('product.service').list_credentials() == []


def test_the_same_key_replays_one_import(tmp_path, running):
    runtime, store, client = running
    source = source_file(tmp_path)
    body = {"kind": "api-key", "source_path": str(source), "confirm_source_path": str(source)}

    first = client.post("/api/v1/credentials", headers={
        **headers(runtime), "Idempotency-Key": "cred-3"}, json=body)
    replay = client.post("/api/v1/credentials", headers={
        **headers(runtime), "Idempotency-Key": "cred-3"}, json=body)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert len(runtime.plugin_host.provided_port('product.service').list_credentials()) == 1


def test_an_unreadable_source_is_refused_without_leaving_a_record(tmp_path, running):
    runtime, store, client = running
    missing = tmp_path / "not-there"

    response = client.post(
        "/api/v1/credentials",
        headers={**headers(runtime), "Idempotency-Key": "cred-4"},
        json={"kind": "api-key", "source_path": str(missing), "confirm_source_path": str(missing)},
    )

    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "CREDENTIAL_SOURCE_UNREADABLE"
    assert runtime.plugin_host.provided_port('product.service').list_credentials() == []


def test_a_store_refusal_is_reported_without_leaving_a_record(tmp_path):
    """A refused source must not leave a credential behind.

    The symlink/type/size rules themselves live in the platform store (the
    Windows DPAPI store refuses a symlinked source); this pins the route's half
    of that contract - whatever the store refuses, the client sees 422 and no
    record appears.
    """
    class RefusingStore(MemorySecretStore):
        def import_file(self, source, kind):
            del source, kind
            raise ValueError("CREDENTIAL_SOURCE_INVALID")

    runtime = build_runtime(tmp_path / "data", secret_store=RefusingStore(values={}))
    runtime.start()
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            source = source_file(tmp_path)
            response = client.post(
                "/api/v1/credentials",
                headers={**headers(runtime), "Idempotency-Key": "cred-5"},
                json={"kind": "api-key", "source_path": str(source),
                      "confirm_source_path": str(source)},
            )

            assert response.status_code == 422, response.json()
            assert response.json()["error"]["code"] == "CREDENTIAL_SOURCE_UNREADABLE"
            assert runtime.plugin_host.provided_port('product.service').list_credentials() == []
    finally:
        runtime.stop()


def test_the_listing_offers_ids_and_kinds_but_never_the_locator(tmp_path, running):
    runtime, store, client = running
    source = source_file(tmp_path)
    created = client.post(
        "/api/v1/credentials",
        headers={**headers(runtime), "Idempotency-Key": "cred-6"},
        json={"kind": "api-key", "source_path": str(source), "confirm_source_path": str(source)},
    ).json()["credentialId"]

    listed = client.get("/api/v1/credentials", headers=headers(runtime)).json()["items"]

    assert [item["credentialId"] for item in listed] == [created]
    assert listed[0]["kind"] == "api-key"
    assert set(listed[0]) == {"credentialId", "kind", "createdAt"}


def test_the_routes_require_the_instance_token(tmp_path, running):
    runtime, store, client = running
    source = source_file(tmp_path)
    body = {"kind": "api-key", "source_path": str(source), "confirm_source_path": str(source)}

    assert client.get("/api/v1/credentials").status_code == 401
    assert client.post("/api/v1/credentials", json=body).status_code == 401
