from pathlib import Path
import pytest

from pacthold.extensions import PluginContext
from pacthold_runtime_compat.resource_contracts import CredentialRefV1
from pacthold.work_core import Ref, RefType
from ordessa_harness.codex.credentials import CodexCredentialSource


def test_codex_credential_is_exact_locator_only_and_materializes_without_reading(tmp_path):
    source = tmp_path / "home/.codex/auth.json"
    source.parent.mkdir(parents=True); source.write_text("SECRET_MUST_NEVER_APPEAR")
    provider = CodexCredentialSource(home=tmp_path / "home", binary="/missing/codex")
    ref = Ref(RefType.ARTIFACT, "codex-login", "codex-login/default", metadata={"revision": "1", "schema_version": "1"})
    value = provider.resolve("agent-box.credential@1", ref)
    assert isinstance(value, CredentialRefV1)
    assert "SECRET_MUST_NEVER_APPEAR" not in repr(value)
    mount = provider.prepare_mount(value, "execution:E1", "/runtime/home/auth.json", "ro")
    assert mount.credential_ref == value and mount.access == "ro"
    assert "SECRET_MUST_NEVER_APPEAR" not in repr(mount)
    assert source.read_text() == "SECRET_MUST_NEVER_APPEAR"


@pytest.mark.parametrize("ref", [
    Ref(RefType.ARTIFACT, "codex-login", "arbitrary-path"),
    Ref(RefType.ARTIFACT, "file", "codex-login/default"),
])
def test_codex_credential_rejects_arbitrary_locator(ref, tmp_path):
    provider = CodexCredentialSource(home=tmp_path / "home")
    with pytest.raises(ValueError): provider.resolve("agent-box.credential@1", ref)


def test_codex_source_rejects_directory_and_symlink(tmp_path):
    home = tmp_path / "home"; (home / ".codex").mkdir(parents=True)
    provider = CodexCredentialSource(home=home)
    source = home / ".codex/auth.json"; source.mkdir()
    value = CredentialRefV1("codex-login", "codex-login/default", "codex")
    with pytest.raises(ValueError): provider.prepare_mount(value, "execution:E1", "/runtime/home/auth.json", "ro")
    source.rmdir(); source.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError): provider.prepare_mount(value, "execution:E1", "/runtime/home/auth.json", "ro")
