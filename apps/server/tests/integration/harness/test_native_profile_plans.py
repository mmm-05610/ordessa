"""Local launch plans retain their outputs without granting Unit dispatch."""

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.profiles import ProfileAccessRefused
from ordessa_units.public import unit_services
from ordessa_server.bootstrap.migrations.harness_profile_history import CapturedHarnessProfile
from ordessa_server.bootstrap.migrations.harness_profile_import import import_harness_profile
from ordessa_server.bootstrap.migrations.harness_profile_projection import HistoricalHarnessRef
from ordessa_server.composition.profile_history_views import historical_profile_views
from ordessa_harness_claude_code.profile import ClaudeProjection
from ordessa_harness_claude_code.launch import ClaudeLaunchAdapter
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment
from pacthold.work_core import Ref, RefType


class _Policy:
    def admit_invoke(self, *args): return True
    def admit_object_access(self, *args): return True


def _claude_capture():
    body = {"profile_id": "main", "harness_type": "claude-code",
            "provider_id": "harness-profile", "name": "Main", "schema_version": 1,
            "revision": 1, "disabled": False, "credential_source_ref": None,
            "capability_refs": [], "session_overlay_policy": {"mode": "execution-local"},
            "import_provenance": None,
            "native_payload": {"settings": {"model": "controlled"}}}
    digest_body = {k: v for k, v in body.items() if k != "revision"}
    digest = "sha256:" + hashlib.sha256(json.dumps(digest_body,
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    body["digest"] = digest
    captured = CapturedHarnessProfile("claude-code", "main", 1, digest,
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return captured, HistoricalHarnessRef("claude-code", "main", 1, digest)


def test_claude_plan_keeps_hooks_prompt_resume_env_and_exact_profile(tmp_path):
    store = SqliteStorePort(tmp_path / "state" / "core.sqlite")
    env = Environment("claude-plan", store=store, policy=_Policy(),
        principal_scope="local", fingerprint_port=ProtectedFingerprintHmac(
            {"fixture": b"controlled-claude-key"}, active_key_id="fixture"), resource_extension_snapshot=_test_resource_snapshot)
    try:
        service = unit_services(env).profiles
        captured, old_ref = _claude_capture()
        modern = import_harness_profile(profiles=service, captured=captured,
            profile_id="main", name="Main", content={
                "schemaVersion": "1", "harnessDefinitionRef": {
                    "environmentNamespace": env.environment_id, "definitionId": "controlled"},
                "declarations": []}, request=service.request_key("create"))
        wire_ref = Ref(RefType.ARTIFACT, "harness-profile", "main", metadata={
            "harness_type": "claude-code", "revision": "1", "digest": old_ref.digest})
        launcher = ClaudeLaunchAdapter(ClaudeProjection(tmp_path / "render"),
                                       binary="claude-controlled")
        spec = launcher.plan(execution_id="plan-1", profile_ref=wire_ref,
            modern_ref=modern.current_revision, historical_ref=old_ref,
            profile_views=historical_profile_views(env), profile=None,
            workspace=SimpleNamespace(path=tmp_path / "workspace"),
            prompt="controlled prompt", continuation="thread-1",
            resources=(("instruction", "AGENTS.md", "instruction"),
                       ("mcp", "controlled", {"command": "none"}),
                       ("skill", "controlled", "# skill")))
        assert spec.argv == ("claude-controlled", "--print", "--resume", "thread-1", "controlled prompt")
        assert spec.cwd == tmp_path / "workspace"
        assert spec.profile_home == tmp_path / "render" / "plan-1"
        assert (spec.profile_home / ".claude" / "settings.json").is_file()
        assert (spec.profile_home / "AGENTS.md").read_text() == "instruction"
        assert (spec.profile_home / ".mcp.json").is_file()
        assert (spec.profile_home / ".claude" / "skills" / "controlled" / "SKILL.md").is_file()
        assert (spec.helper_dir / "session-start").is_file()
        assert set(spec.env) <= {"LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
        assert all(spec.env[k] == os.environ[k] for k in spec.env)
        assert spec.executable == "claude-controlled"
        archived = service.archive("main", expected_version=1,
                                   request=service.request_key("archive"))
        assert archived.archived
        with pytest.raises(ProfileAccessRefused):
            launcher.plan(execution_id="plan-archived", profile_ref=wire_ref,
                modern_ref=modern.current_revision, historical_ref=old_ref,
                profile_views=historical_profile_views(env), profile=None,
                workspace=SimpleNamespace(path=tmp_path / "workspace"), prompt="blocked")
        assert not (tmp_path / "render" / "plan-archived").exists()
    finally:
        env.close()
        store.close()
