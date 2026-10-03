"""026 T006-09: the startup native-Profile bootstrap is an injected control.

``bootstrap_native_profile=None`` (the default) keeps the historical
behaviour — pinned by the existing suites and not re-asserted here;
``False`` starts a native composition without creating, binding or asserting
an auto-Profile; ``True`` is the explicit form of the historical behaviour.
No Agent process, model call or managed channel is launched: the adapter is
a never-launched path, exactly like the identity pins in apps/server.
"""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from ordessa_server_compat.composition import build_runtime_from_native_adapter
from ordessa_server_compat.plugin import ServerCompatPlugin
from ordessa_server_compat.sessions.service import SessionService


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "harness"

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}


def _build(tmp_path, *, bootstrap_native_profile=None):
    return build_runtime_from_native_adapter(
        tmp_path / "data", plugin_root=PLUGIN, harness_id="pi",
        adapter_command=shutil.which("node"), adapter_args=("/not-launched.mjs",),
        bootstrap_native_profile=bootstrap_native_profile,
    )


@pytest.fixture
def profile_executable_calls(monkeypatch):
    """Record every SessionService executability assertion (a startup one is
    exactly the bootstrap's bind-and-assert leg; acceptance-time calls only
    happen on a send, which these tests never issue)."""
    calls = []
    original = SessionService._assert_profile_executable

    def spy(self, profile_id, **kwargs):
        calls.append(profile_id)
        return original(self, profile_id, **kwargs)

    monkeypatch.setattr(SessionService, "_assert_profile_executable", spy)
    return calls


def _profile_rows(runtime) -> "list[tuple[str, ...]]":
    with runtime.database.transaction() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT harness_type FROM server_profiles ORDER BY id").fetchall()]


def _bound_identity(runtime):
    service = runtime.plugin_host.provided_port("product.service")
    identity = service.sessions.native_profile_identity
    return None if identity is None else (identity[0], identity[1])


def test_explicit_false_starts_without_native_profile(tmp_path, profile_executable_calls):
    runtime = _build(tmp_path, bootstrap_native_profile=False)
    try:
        runtime.start()
        # no auto-Profile: nothing created, nothing bound, nothing asserted
        assert profile_executable_calls == []
        assert _profile_rows(runtime) == []
        assert runtime.native_profile_id is None
        assert _bound_identity(runtime) is None
        service = runtime.plugin_host.provided_port("product.service")
        assert service.sessions.native_profile_identities == {}
        # an absent identity is typed absence, not a broken hello
        assert "nativeExecution" not in runtime.wire.hello(HELLO)
    finally:
        runtime.stop()


def test_explicit_true_equals_the_legacy_default_bootstrap(tmp_path, profile_executable_calls):
    facts = {}
    for name, control in (("legacy_default", None), ("explicit_true", True)):
        runtime = _build(tmp_path / name, bootstrap_native_profile=control)
        try:
            runtime.start()
            hello = runtime.wire.hello(HELLO)
            identity = runtime.plugin_host.provided_port(
                "product.service").sessions.native_profile_identity
            facts[name] = {
                "rows": _profile_rows(runtime),
                "has_profile": runtime.native_profile_id is not None,
                "asserted_count": len(profile_executable_calls),
                "asserted_is_profile":
                    profile_executable_calls == [runtime.native_profile_id],
                "native_execution": {
                    **hello["nativeExecution"], "profileId": "<id>",
                },
                "identity_is_profile": identity is not None and (
                    identity[0] == runtime.native_profile_id and identity[1] == "pi"),
            }
        finally:
            runtime.stop()
            profile_executable_calls.clear()
    assert facts["explicit_true"] == facts["legacy_default"]
    assert facts["legacy_default"]["rows"] == [("pi",)]
    assert facts["legacy_default"]["asserted_count"] == 1


def test_bootstrap_control_refuses_non_boolean_before_creating_data(tmp_path):
    with pytest.raises(RuntimeError, match="NATIVE_PROFILE_SELECTION_INVALID"):
        _build(tmp_path, bootstrap_native_profile="yes")
    assert not (tmp_path / "data").exists()


def test_plugin_constructor_refuses_non_boolean_control():
    with pytest.raises(ValueError):
        ServerCompatPlugin(bootstrap_native_profile="yes")
