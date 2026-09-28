"""LNX-002 — the default Linux credential composition, measured offline.

I's `control/LNX-003-review.md` item 3 asks for two things that a
`MemorySecretStore`-injected test cannot stand in for:

1. the **default Linux composition's refusal path with no store injected**;
2. a **synthetic non-secret record read back after a reopen**.

Scope, stated honestly (I's item 3 and item 5): this file measures the
*composition* fact and the *record* layer's persistence. It does **not** provide
or test a persistent Linux SecretStore — that stays a later runtime task — and
nothing here claims this Server can resolve a secret on Linux today. It also does
not restate LNX-003's "no entry point across 64 wire methods" as "the product has
no credential-entry chain": the chain exists and is exercised below, it is the
*default store* that is missing.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from pacthold.storage import MemorySecretStore


def create_app(runtime):
    from ordessa_server.transport.http import create_app as build_app

    return build_app(runtime)


def headers(runtime) -> dict[str, str]:
    return {"Authorization": f"Bearer {runtime.token}"}


def source_file(tmp_path: Path, content: bytes = b"fixture-secret-value-not-a-credential") -> Path:
    source = tmp_path / "source-key"
    source.write_bytes(content)
    return source


def _import(client, runtime, source: Path, key: str):
    return client.post(
        "/api/v1/credentials",
        headers={**headers(runtime), "Idempotency-Key": key},
        json={"kind": "api-key", "source_path": str(source),
              "confirm_source_path": str(source)},
    )


# -- 1. the default Linux composition ------------------------------------

def test_default_linux_composition_composes_with_no_secret_store(tmp_path):
    """The core gap, asserted as the *current* fact rather than as a wish.

    `bootstrap/runtime.py` installs a platform store for exactly one platform:

        secrets_store = secret_store
        if secrets_store is None and os.name == "nt":
            secrets_store = WindowsDpapiSecretStore(root)

    So on Linux a composition that injects nothing gets `secret_store is None`.
    This is a pin: the day a Linux store lands here, this test goes red and the
    replacement is "which store, and what it guarantees", which is a decision
    nobody has written down yet.
    """
    assert os.name == "posix", "this file measures the non-Windows composition"

    runtime = build_runtime(tmp_path / "data")
    try:
        assert runtime.secret_store is None
    finally:
        runtime.stop()


def test_the_import_route_refuses_with_a_typed_code_without_a_store(tmp_path):
    """The refusal is loud **and typed** — measured, not assumed.

    I's item 3 asks for the default Linux refusal path. Measured on this host:
    the route answers **503** with `error.code == "CREDENTIAL_STORE_UNAVAILABLE"`
    and `retryable: true`, and no credential record is created. That is the
    behaviour a client can branch on; the *gap* is that no store is composed on
    Linux in the first place, not that the failure is untyped.
    """
    runtime = build_runtime(tmp_path / "data")  # no store injected
    runtime.start()
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            response = _import(client, runtime, source_file(tmp_path), "lnx002-nostore")

            assert response.status_code == 503, response.json()
            assert response.json()["error"]["code"] == "CREDENTIAL_STORE_UNAVAILABLE"
            assert response.json()["error"]["retryable"] is True
            # Nothing may claim a credential exists that no store can resolve.
            assert runtime.plugin_host.provided_port('product.service').list_credentials() == []
    finally:
        runtime.stop()


# -- 2. the non-secret record layer survives a reopen ---------------------

def test_a_non_secret_credential_record_is_readable_after_a_reopen(tmp_path):
    """The record is the non-secret half and it persists; the store is not.

    A `MemorySecretStore` cannot survive a reopen, so this pins exactly the part
    that *can*: the credential record (id, kind, locator) written through the
    real route into the real database, read back by a **second composition** over
    the same data root. The new composition gets a fresh empty store on purpose —
    which is also the honest picture of the gap: the reference survives, the
    thing it points at does not.
    """
    root = tmp_path / "data"
    first_store = MemorySecretStore(values={})
    runtime = build_runtime(root, secret_store=first_store)
    runtime.start()
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            response = _import(client, runtime, source_file(tmp_path), "lnx002-reopen")
            assert response.status_code == 201, response.json()
            credential_id = response.json()["credentialId"]
    finally:
        runtime.stop()

    reopened_store = MemorySecretStore(values={})
    reopened = build_runtime(root, secret_store=reopened_store)
    reopened.start()
    try:
        listed = {row["credentialId"]: row for row in reopened.plugin_host.provided_port('product.service').list_credentials()}
        assert credential_id in listed, sorted(listed)

        record = reopened.plugin_host.provided_port('product.repository').credentials.get(credential_id, kind="api-key")
        assert record["kind"] == "api-key"
        # The reference survived the reopen and its locator is intact...
        assert record["secret_locator"], "the record's locator must survive the reopen"
        # ...while the *new* store cannot answer for it. This is the Memory-vs-
        # persistent distinction I's item 3 says must not be papered over.
        with pytest.raises(Exception):
            reopened_store.read(record["secret_locator"])
    finally:
        reopened.stop()
