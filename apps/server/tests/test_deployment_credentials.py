"""Deployment-declared credentials: a path in the document, never a secret.

The product Server learns about a credential from the deployment that started
it. That document is a non-secret artifact by construction - it names an
identity, a kind and a *path* - so the interesting cases are all refusals: a
document that tries to carry the secret itself, an id that is not the product's
opaque shape, a source that is not an ordinary readable file, and a restart that
must not duplicate or re-read what it already imported.

The store is injected (`MemorySecretStore`), so no test here touches DPAPI, a
real credential or a real file outside its tmp path.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
from pacthold.storage import MemorySecretStore


_CALLS = itertools.count()


def build(document: Path, *, secret_store, data_root: Path | None = None):
    """The loader takes (data_root, deployment_path); a fresh data root per call
    keeps each case's records and lock to itself (one root, one owner).

    These cases never run a turn, so the WSL connector is a stub: what is under
    test is which credentials the Server ends up able to resolve, not the chain
    that would use them.
    """
    import ordessa_server_compat.composition as runtime_module
    import ordessa_server.bootstrap.runtime as host_module

    original = host_module._builtin_connector
    host_module._builtin_connector = lambda _instance_id: object()
    try:
        return build_runtime_from_sidecar_deployment(
            data_root if data_root is not None else document.parent / f"data-{next(_CALLS)}",
            document, secret_store=secret_store, plugin_root=PLUGIN_ROOT,
        )
    finally:
        host_module._builtin_connector = original


CREDENTIAL_ID = "credential_0123456789abcdef0123456789abcdef"
REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins"  / "harness"


def deployment_document(tmp_path: Path, credentials: list[dict] | None = None) -> Path:
    document: dict = {
        "schemaVersion": 1,
        "harnesses": [
            {
                "id": "fixture",
                "adapter": {"args": ["/workspace/peer.mjs"], "command": "/usr/bin/node"},
                "capabilityClaims": {"stream": True},
                "timeoutMs": 30000,
            }
        ],
    }

    if credentials is not None:
        document["credentials"] = credentials

    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def secret_file(tmp_path: Path, content: bytes = b"fixture-secret-value-not-a-credential") -> Path:
    source = tmp_path / "source-key"
    source.write_bytes(content)
    return source


def test_a_declared_credential_is_imported_and_resolves_by_its_declared_id(tmp_path):
    source = secret_file(tmp_path)
    document = deployment_document(tmp_path, [
        {"credentialId": CREDENTIAL_ID, "kind": "api-key", "label": "Fixture", "sourcePath": str(source)},
    ])
    store = MemorySecretStore(values={})

    runtime = build(document, secret_store=store)
    runtime.start()
    try:
        record = runtime.repository.credentials.get(CREDENTIAL_ID)
        assert record["kind"] == "api-key"
        # The declared id resolves to bytes the *store* owns, and the source is
        # not the store: the deployment named where to read, nothing more.
        assert store.read(record["secret_locator"]) == source.read_bytes()
    finally:
        runtime.stop()


def test_a_restart_with_the_same_deployment_does_not_duplicate_or_reread(tmp_path):
    source = secret_file(tmp_path)
    document = deployment_document(tmp_path, [
        {"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": str(source)},
    ])
    store = MemorySecretStore(values={})
    # One data root for both builds: a restart re-opens the same Server root.
    root = tmp_path / "data"
    first = build(document, secret_store=store, data_root=root)
    first.start()
    locator = first.repository.credentials.get(CREDENTIAL_ID)["secret_locator"]
    first.stop()

    # The source is gone and the id is already registered: a restart must not
    # need it again, and must not create a second record.
    source.unlink()
    second = build(document, secret_store=store, data_root=root)
    second.start()
    try:
        assert second.repository.credentials.get(CREDENTIAL_ID)["secret_locator"] == locator
    finally:
        second.stop()


def test_the_document_may_not_carry_the_secret_itself(tmp_path):
    source = secret_file(tmp_path)
    document = deployment_document(tmp_path, [
        {"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": str(source),
         "value": "sk-inline-secret-that-must-be-refused"},
    ])

    with pytest.raises(RuntimeError) as refused:
        build(document, secret_store=MemorySecretStore(values={}))

    assert "credentialId, kind, sourcePath and optional label" in str(refused.value)


@pytest.mark.parametrize("entry,expected", [
    ({"credentialId": "cred-1", "kind": "api-key", "sourcePath": "/tmp/x"}, "credentialId must be"),
    ({"credentialId": CREDENTIAL_ID, "kind": "", "sourcePath": "/tmp/x"}, "kind is required"),
    ({"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": "relative/key"}, "must be absolute"),
    ({"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": "/tmp/x", "label": "x" * 65},
     "at most 64 characters"),
])
def test_a_malformed_declaration_is_a_typed_refusal(tmp_path, entry, expected):
    document = deployment_document(tmp_path, [entry])

    with pytest.raises(RuntimeError) as refused:
        build(document, secret_store=MemorySecretStore(values={}))

    assert expected in str(refused.value)


def test_duplicate_ids_and_an_oversized_section_are_refused(tmp_path):
    source = secret_file(tmp_path)
    entry = {"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": str(source)}

    with pytest.raises(RuntimeError) as duplicate:
        build(deployment_document(tmp_path, [entry, dict(entry)]),
              secret_store=MemorySecretStore(values={}))
    assert "duplicate credentialId" in str(duplicate.value)

    many = [
        {"credentialId": f"credential_{index:032x}", "kind": "api-key", "sourcePath": str(source)}
        for index in range(17)
    ]
    with pytest.raises(RuntimeError) as too_many:
        build(deployment_document(tmp_path, many), secret_store=MemorySecretStore(values={}))
    assert "at most 16 entries" in str(too_many.value)


def test_an_unreadable_source_fails_the_start_rather_than_the_harness(tmp_path):
    missing = tmp_path / "not-there"
    document = deployment_document(tmp_path, [
        {"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": str(missing)},
    ])

    runtime = build(document, secret_store=MemorySecretStore(values={}))
    with pytest.raises(RuntimeError) as refused:
        runtime.start()

    assert "SIDECAR_DEPLOYMENT_CREDENTIAL_UNREADABLE" in str(refused.value)
    assert CREDENTIAL_ID in str(refused.value)


def test_a_declared_credential_without_a_store_is_refused(tmp_path):
    source = secret_file(tmp_path)
    document = deployment_document(tmp_path, [
        {"credentialId": CREDENTIAL_ID, "kind": "api-key", "sourcePath": str(source)},
    ])
    runtime = build(document, secret_store=None)
    # build_runtime picks the platform default store; where there is none (this
    # Linux CI host has no DPAPI), declaring a credential must fail loudly
    # rather than start a Server whose harness cannot resolve it.
    runtime.secret_store = None

    with pytest.raises(RuntimeError) as refused:
        runtime.start()

    assert "SIDECAR_DEPLOYMENT_CREDENTIAL_STORE_MISSING" in str(refused.value)


def test_a_deployment_without_credentials_still_starts(tmp_path):
    runtime = build(deployment_document(tmp_path, None), secret_store=MemorySecretStore(values={}))
    runtime.start()
    try:
        assert not runtime.repository.credentials.exists(CREDENTIAL_ID)
        assert runtime.declared_credentials == ()
    finally:
        runtime.stop()
