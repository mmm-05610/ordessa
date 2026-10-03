"""005 gates for the E4 platform adapters (T005-10 data areas, T005-12 secrets)."""
from __future__ import annotations

import pytest

from ordessa_platform_services import DataAreaError, FileDataAreaAdapter, SecretRefAdapter
from ordessa_environment_api import EnvironmentError, SecretAvailability, SecretRef


def test_data_area_namespace_is_stable_and_close_keeps_bytes(tmp_path):
    adapter = FileDataAreaAdapter(tmp_path / "root")
    adapter.claim("ordessa.skills.store", "write", "1-3")
    area = adapter.open("area.ordessa.skills.store")
    (area / "skill-a.json").write_text("{}")
    adapter.close("area.ordessa.skills.store")
    # closing released the ACCESS relation; the bytes survive (uninstall keeps data)
    assert (tmp_path / "root/ordessa/skills/store/skill-a.json").read_text() == "{}"


def test_old_binary_schema_refuses_to_write_new_range(tmp_path):
    import json

    adapter = FileDataAreaAdapter(tmp_path / "root")
    adapter.claim("ordessa.skills.store", "write", "1-2")
    adapter.write_schema_marker("area.ordessa.skills.store", "2")
    adapter.close("area.ordessa.skills.store")
    # a newer writer advances the area to schema 3…
    marker = tmp_path / "root/ordessa/skills/store/data-area.json"
    marker.write_text(json.dumps({"schema": "3"}))
    # …an old binary supporting only 1-2 re-opens: the claim reads the newer
    # evidence and every write refuses (never a silent up/downgrade)
    adapter.claim("ordessa.skills.store", "write", "1-2")
    with pytest.raises(DataAreaError, match="never silently"):
        adapter.write_schema_marker("area.ordessa.skills.store", "2")


def test_purge_requires_explicit_authorization(tmp_path):
    adapter = FileDataAreaAdapter(tmp_path / "root")
    adapter.claim("ordessa.x", "write", "1-1")
    area = adapter.open("area.ordessa.x")
    (area / "f").write_text("data")
    with pytest.raises(DataAreaError, match="explicit authorization"):
        adapter.purge("area.ordessa.x", authorization=None)
    assert (area / "f").exists()


def test_namespace_identity_is_rejected_for_window_ids_and_paths():
    adapter = FileDataAreaAdapter("/tmp/oe-area-test-root")
    with pytest.raises(DataAreaError):
        adapter.claim("Window-1", "write", "1-1")  # window id is not a namespace
    with pytest.raises(DataAreaError):
        adapter.claim("../escape", "write", "1-1")  # path traversal is not identity


def _ref(rev: str = "r-1") -> SecretRef:
    return SecretRef(ref="sec-1", revision=rev, owner_namespace="ordessa.model-provider",
                     access_purpose="provider-auth")


def test_secret_borrow_verifies_every_time_and_locked_refuses():
    adapter = SecretRefAdapter()
    adapter.store(_ref(), b"material", "provider-auth")
    assert adapter.borrow_for_use(_ref(), "user:a", "provider-auth", "codex") == b"material"
    adapter2 = SecretRefAdapter(locked=True)
    assert adapter2.describe(_ref()) is SecretAvailability.LOCKED
    with pytest.raises(EnvironmentError, match="no fallback"):
        adapter2.borrow_for_use(_ref(), "user:a", "provider-auth", "codex")


def test_rotation_mints_revision_and_old_revision_goes_unknown():
    adapter = SecretRefAdapter()
    adapter.store(_ref(), b"material", "provider-auth")
    new = adapter.rotate(_ref(), "r-2", b"material-2")
    assert new.revision == "r-2"
    assert adapter.describe(_ref()) is SecretAvailability.UNKNOWN  # old revision gone
    assert adapter.describe(new) is SecretAvailability.AVAILABLE


def test_delete_refuses_inflight_borrows_and_keeps_tombstone():
    adapter = SecretRefAdapter()
    adapter.store(_ref(), b"material", "provider-auth")
    adapter.borrow_for_use(_ref(), "user:a", "provider-auth", "codex")
    with pytest.raises(EnvironmentError, match="in-flight borrows"):
        adapter.delete(_ref(), evidence={})
    adapter.revoke_access(_ref(), "user:a")
    adapter.delete(_ref(), evidence={"settled": True})
    assert adapter.has_tombstone("sec-1")  # tombstone survives deletion
    assert adapter.describe(_ref()) is SecretAvailability.UNKNOWN
