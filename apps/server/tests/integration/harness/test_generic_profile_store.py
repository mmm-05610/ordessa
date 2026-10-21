"""Original Profile behaviors now belong to the selected Environment service."""
from __future__ import annotations

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

import hashlib
import json
from types import SimpleNamespace

import pytest

from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_units.public import unit_services, composed_profile_service
from ordessa_agents.profiles import (
    ProfileAccessRefused, ProfileRevisionConflict, ProfileValidationError,
)
from ordessa_server.bootstrap.migrations.harness_profile_history import CapturedHarnessProfile
from ordessa_server.bootstrap.migrations.harness_profile_import import import_harness_profile
from ordessa_server.bootstrap.migrations.harness_profile_projection import (
    HistoricalHarnessRef, read_captured_historical,
    read_imported_historical_revision, resolve_captured_historical,
)
from ordessa_server.composition.profile_history_views import historical_profile_views
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment
from pacthold.work_core import Ref, RefType
from ordessa_harness_hermes.projection import HermesProjection
from ordessa_harness_hermes.launch import HermesLaunchAdapter


class _Policy:
    def admit_invoke(self, *args): return True
    def admit_object_access(self, *args): return True


def _captured(revision, model, *, disabled=False, secret=False):
    native = {"model": model}
    if secret:
        native["api_key"] = "never"
    body = {"profile_id": "main", "harness_type": "hermes",
            "provider_id": "harness-profile", "name": "Main", "schema_version": 1,
            "revision": revision, "disabled": disabled, "credential_source_ref": None,
            "capability_refs": [], "session_overlay_policy": {"mode": "execution-local"},
            "import_provenance": None, "native_payload": native}
    digest_body = {k: v for k, v in body.items() if k != "revision"}
    digest = "sha256:" + hashlib.sha256(json.dumps(
        digest_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    body["digest"] = digest
    captured = CapturedHarnessProfile("hermes", "main", revision, digest,
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return captured, HistoricalHarnessRef("hermes", "main", revision, digest)


def _content(environment, intent):
    return {"schemaVersion": "1", "harnessDefinitionRef": {
        "environmentNamespace": environment, "definitionId": "accepted-controlled"},
        "declarations": [], "metadata": {"intent": intent}}


def test_one_environment_keeps_cas_replay_disabled_and_exact_old_digest(tmp_path):
    store = SqliteStorePort(tmp_path / "state" / "core.sqlite")
    env = Environment("profile-test", store=store, policy=_Policy(),
        principal_scope="local", fingerprint_port=ProtectedFingerprintHmac(
            {"fixture": b"controlled-profile-key"}, active_key_id="fixture"), resource_extension_snapshot=_test_resource_snapshot)
    try:
        with pytest.raises(UnitGuaranteeUnavailable, match="not composed"):
            historical_profile_views(env)
        with pytest.raises(UnitGuaranteeUnavailable, match="not composed"):
            composed_profile_service(env)
        service = unit_services(env).profiles
        assert composed_profile_service(env) is service
        first_capture, first_old = _captured(1, "offline")
        first = import_harness_profile(profiles=service, captured=first_capture,
            profile_id="main", name="Main", content=_content(env.environment_id, "one"),
            request=service.request_key("create"))
        assert import_harness_profile(profiles=service, captured=first_capture,
            profile_id="main", name="Main", content=_content(env.environment_id, "one"),
            request=service.request_key("create")) == first
        second_capture, second_old = _captured(2, "offline-2")
        second = import_harness_profile(profiles=service, captured=second_capture,
            profile_id="main", name=None, content=_content(env.environment_id, "two"),
            expected_version=1, base_revision=first.current_revision,
            request=service.request_key("revise"))
        assert first.current_revision.revision == 1
        assert second.current_revision.revision == 2
        assert service.get_revision(first.current_revision).ref == first.current_revision
        assert read_imported_historical_revision(profiles=service,
            modern_ref=first.current_revision, expected=first_old).envelope()["native_payload"]["model"] == "offline"
        assert second.current_revision.digest != second_old.digest
        assert historical_profile_views(env).select_current(
            second.current_revision, second_old).historical_ref == second_old
        old_wire = Ref(RefType.ARTIFACT, "harness-profile", "main", metadata={
            "harness_type": "hermes", "revision": "2", "digest": second_old.digest})
        rendered = HermesProjection(tmp_path / "render").materialize_current(
            "controlled", old_wire, modern_ref=second.current_revision,
            historical_ref=second_old, profile_views=historical_profile_views(env))
        assert "offline-2" in (rendered / "config.yaml").read_text()
        binary = tmp_path / "hermes-controlled"
        binary.write_bytes(b"controlled-binary-not-executed")
        binary.chmod(0o700)
        helper = tmp_path / "helper"
        launcher = HermesLaunchAdapter(HermesProjection(tmp_path / "plan"),
                                       binary=str(binary), helper=helper)
        plan = launcher.plan(execution_id="hermes-plan", profile_ref=old_wire,
            modern_ref=second.current_revision, historical_ref=second_old,
            profile_views=historical_profile_views(env),
            workspace=SimpleNamespace(path=tmp_path / "workspace"), profile=None)
        assert plan.argv == (str(plan.executable / "hermes"),)
        assert (plan.executable / "hermes").read_bytes() == binary.read_bytes()
        assert plan.home == tmp_path / "plan" / "hermes-plan" / "hermes"
        assert plan.cwd == tmp_path / "workspace"
        assert plan.helper == helper
        assert plan.env["HERMES_HOME"] == "/runtime/home"
        assert plan.env["PATH"] == "/usr/bin:/bin"
        wrong_old = HistoricalHarnessRef("hermes", "main", 2, "sha256:" + "0" * 64)
        with pytest.raises(ValueError, match="PROFILE_DIGEST_DRIFT"):
            launcher.plan(execution_id="wrong-digest-plan", profile_ref=old_wire,
                modern_ref=second.current_revision, historical_ref=wrong_old,
                profile_views=historical_profile_views(env),
                workspace=SimpleNamespace(path=tmp_path / "workspace"), profile=None)
        assert not (tmp_path / "plan" / "wrong-digest-plan").exists()
        with pytest.raises(ProfileRevisionConflict):
            service.revise("main", content=_content(env.environment_id, "stale"),
                expected_version=1, base_revision=first.current_revision,
                request=service.request_key("stale"))
        archived = service.archive("main", expected_version=2,
                                   request=service.request_key("disable"))
        assert archived.archived
        assert service.list() == ()
        assert service.list(include_archived=True) == (archived,)
        with pytest.raises(ProfileAccessRefused):
            historical_profile_views(env).select_current(second.current_revision, second_old)
        with pytest.raises(ProfileAccessRefused):
            launcher.plan(execution_id="archived-plan", profile_ref=old_wire,
                modern_ref=second.current_revision, historical_ref=second_old,
                profile_views=historical_profile_views(env),
                workspace=SimpleNamespace(path=tmp_path / "workspace"), profile=None)
        assert not (tmp_path / "plan" / "archived-plan").exists()
        assert read_imported_historical_revision(profiles=service,
            modern_ref=second.current_revision, expected=second_old).historical_ref == second_old
        with pytest.raises(ValueError, match="PROFILE_DIGEST_DRIFT"):
            read_imported_historical_revision(profiles=service,
                modern_ref=second.current_revision, expected=wrong_old)
        restored = service.restore("main", expected_version=3,
                                   request=service.request_key("restore"))
        assert service.list() == (restored,)
        assert historical_profile_views(env).select_current(
            second.current_revision, second_old).historical_ref == second_old
        assert not (tmp_path / "profiles").exists()
    finally:
        env.close()
        store.close()


def test_disabled_history_and_secret_shaped_payload_refuse(tmp_path):
    store = SqliteStorePort(tmp_path / "state" / "core.sqlite")
    env = Environment("profile-test", store=store, policy=_Policy(),
        principal_scope="local", fingerprint_port=ProtectedFingerprintHmac(
            {"fixture": b"controlled-profile-key"}, active_key_id="fixture"), resource_extension_snapshot=_test_resource_snapshot)
    try:
        service = unit_services(env).profiles
        disabled, old_ref = _captured(1, "offline", disabled=True)
        audited = read_captured_historical(captured=disabled, expected=old_ref)
        assert audited.historical_ref == old_ref
        assert audited.envelope()["disabled"] is True
        with pytest.raises(ValueError, match="PROFILE_DISABLED"):
            import_harness_profile(profiles=service, captured=disabled,
                profile_id="main", name="Main", content=_content(env.environment_id, "disabled"),
                request=service.request_key("disabled"))
        with pytest.raises(ValueError, match="PROFILE_DISABLED"):
            resolve_captured_historical(captured=disabled, expected=old_ref)
        secret, _ = _captured(1, "offline", secret=True)
        with pytest.raises(ProfileValidationError, match="plaintext credentials"):
            import_harness_profile(profiles=service, captured=secret,
                profile_id="main", name="Main", content=_content(env.environment_id, "secret"),
                request=service.request_key("secret"))
        assert service.list() == ()
    finally:
        env.close()
        store.close()
