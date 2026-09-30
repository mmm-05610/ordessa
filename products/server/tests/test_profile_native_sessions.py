"""Real Profile storage with controlled, explicitly observed native owners."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ordessa_profile.core import ProfileCore, StaticHarnessCatalog
from ordessa_profile.errors import ProfileError
from ordessa_profile.contracts import SessionRef
from ordessa_server_product.profile_sessions import ProfileNativeSessions


def test_canonical_registration_is_backend_minted_isolated_and_owner_pinned(tmp_path):
    core = ProfileCore(tmp_path / "profiles.sqlite", harnesses=StaticHarnessCatalog({"pi": frozenset()}))
    profile = core.profiles.create("profile", harness_id="pi", display_name="Review")
    owner_a, owner_b = object(), object()
    actual = {"a": owner_a, "b": owner_b}
    channels = Mock()
    channels.get.return_value = SimpleNamespace(ended=False, harness_id="pi", workspace_id="project")
    channels.native_session_observation.side_effect = lambda connection, native: actual.get(connection)
    owners = Mock()
    owners.bind.side_effect = lambda **kw: SimpleNamespace(owner=actual[kw["connection_id"]], target=kw["canonical_session_id"])
    owners.readback.side_effect = lambda target: SimpleNamespace(owner=owner_a, target=target)
    sessions = ProfileNativeSessions(core=core, channels=channels, owners=owners, realm="backend-realm")
    try:
        a = sessions.register(connection_id="a", native_session_id="same", profile_id=profile["profile_id"])
        b = sessions.register(connection_id="b", native_session_id="same", profile_id=profile["profile_id"])
        assert a.session_ref.session_uid != b.session_ref.session_uid
        assert a.session_ref.native_session_key == b.session_ref.native_session_key == "same"
        assert a.session_ref.realm == "backend-realm"
        assert sessions.register(connection_id="a", native_session_id="same", profile_id=profile["profile_id"]).session_ref == a.session_ref
        actual["a"] = object()
        with pytest.raises(ProfileError, match="replaced"):
            sessions.register(connection_id="a", native_session_id="same", profile_id=profile["profile_id"])
        actual["b"] = None
        with pytest.raises(ProfileError):
            sessions.register(connection_id="b", native_session_id="same", profile_id=profile["profile_id"])
        with core.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM profile_sessions").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM profile_applied_receipts").fetchone()[0] == 0
    finally:
        core.db.close()
