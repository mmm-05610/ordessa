from pathlib import Path

import pytest

from ordessa_server_product.harness_adapters.generic.profile_store import ProfileStore


def test_unified_profile_store_revisions_are_exact_and_execution_local(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    first = store.put("codex", {"profile_id": "main", "name": "Main", "native_payload": {"model": "offline"}})
    second = store.put("codex", {"profile_id": "main", "name": "Main", "native_payload": {"model": "offline-2"}}, expected_revision=1)
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert store.get("codex", "main", 1)["native_payload"]["model"] == "offline"
    ref = store.ref("codex", "main", 1)
    assert store.resolve("agent-box.profile@1", ref).name == "Main"
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        store.put("codex", {"profile_id": "main", "native_payload": {}}, expected_revision=1)


def test_unified_profile_store_rejects_secret_shaped_native_fields(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    with pytest.raises(ValueError, match="SECRET_FIELD_FORBIDDEN"):
        store.put("codex", {"profile_id": "unsafe", "native_payload": {"api_key": "never"}})
