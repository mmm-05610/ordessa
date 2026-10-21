"""OpenCode renders only a current historical view from one real Environment.

Real temporary Pacthold SQLite and ProfileService; no native process or model.
"""
from __future__ import annotations

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

import hashlib
import json

import pytest

from ordessa_agents.profiles import ProfileAccessRefused, ProfileRevisionConflict
from ordessa_units.public import unit_services
from ordessa_server.bootstrap.migrations.harness_profile_history import (
    CapturedHarnessProfile, validated_capture,
)
from ordessa_server.bootstrap.migrations.harness_profile_import import (
    PROVENANCE_FIELD, import_harness_profile,
)
from ordessa_server.bootstrap.migrations.harness_profile_projection import HistoricalHarnessRef
from ordessa_server.composition.profile_history_views import historical_profile_views
from ordessa_harness_opencode.profiles import OpenCodeProfileRef
from ordessa_harness_opencode.projection import OpenCodeProjector
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment


class _Policy:
    allowed = True

    def admit_invoke(self, *args):
        return self.allowed

    def admit_object_access(self, *args):
        return self.allowed


@pytest.fixture
def owner(tmp_path):
    store = SqliteStorePort(tmp_path / "state" / "core.sqlite")
    policy = _Policy()
    environment = Environment("opencode-history", store=store, policy=policy,
        principal_scope="local", fingerprint_port=ProtectedFingerprintHmac(
            {"fixture": b"controlled-profile-key"}, active_key_id="fixture"), resource_extension_snapshot=_test_resource_snapshot)
    try:
        profiles = unit_services(environment).profiles
        views = historical_profile_views(environment)
        assert views._profiles is profiles
        yield environment, profiles, views, policy
    finally:
        environment.close()
        store.close()


def _capture(profile_id: str, revision: int, model: str, *, disabled: bool = False):
    envelope = {
        "profile_id": profile_id, "harness_type": "opencode",
        "provider_id": "harness-profile", "name": "Controlled",
        "schema_version": 1, "revision": revision, "disabled": disabled,
        "credential_source_ref": None, "capability_refs": [],
        "session_overlay_policy": {"mode": "execution-local"},
        "import_provenance": None,
        "native_payload": {"model": model, "instructions": ["controlled-only"]},
    }
    body = {key: value for key, value in envelope.items() if key != "revision"}
    digest = "sha256:" + hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    envelope["digest"] = digest
    captured = CapturedHarnessProfile("opencode", profile_id, revision, digest,
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
    return captured, HistoricalHarnessRef("opencode", profile_id, revision, digest)


def _content(environment_id: str, intent: str):
    return {"schemaVersion": "1", "harnessDefinitionRef": {
        "environmentNamespace": environment_id, "definitionId": "accepted-controlled"},
        "declarations": [], "metadata": {"intent": intent}}


def test_current_opencode_projection_uses_original_profile_service_cas_and_acl(owner, tmp_path):
    environment, profiles, views, policy = owner
    captured_one, historical_one = _capture("main", 1, "controlled-one")
    first = import_harness_profile(profiles=profiles, captured=captured_one,
        profile_id="main", name="Main", content=_content(environment.environment_id, "one"),
        request=profiles.request_key("create-main"))
    projector = OpenCodeProjector(tmp_path / "render")
    old_ref = OpenCodeProfileRef("main", 1, historical_one.digest)
    projected = projector.materialize_current("current-one", old_ref,
        modern_ref=first.current_revision, historical_ref=historical_one, profile_views=views)
    assert json.loads(projected.config_path.read_text())["model"] == "controlled-one"
    assert json.loads(projected.config_path.read_text())["instructions"] == ["controlled-only"]
    manifest = json.loads(projected.manifest_path.read_text())
    assert manifest["profile_ref"] == {"id": "main", "revision": 1,
                                      "digest": historical_one.digest}
    assert manifest["config_digest"] == projected.source_digests["config"]
    assert first.current_revision.digest != historical_one.digest

    captured_two, historical_two = _capture("main", 2, "controlled-two")
    second = import_harness_profile(profiles=profiles, captured=captured_two,
        profile_id="main", name=None, content=_content(environment.environment_id, "two"),
        expected_version=1, base_revision=first.current_revision,
        request=profiles.request_key("revise-main"))
    with pytest.raises(ProfileRevisionConflict):
        profiles.revise("main", content=_content(environment.environment_id, "stale"),
            expected_version=1, base_revision=first.current_revision,
            request=profiles.request_key("stale-main"))
    with pytest.raises(ProfileAccessRefused, match="no longer current"):
        projector.materialize_current("stale-current", old_ref,
            modern_ref=first.current_revision, historical_ref=historical_one,
            profile_views=views)
    assert not (tmp_path / "render" / "stale-current").exists()

    current_ref = OpenCodeProfileRef("main", 2, historical_two.digest)
    policy.allowed = False
    with pytest.raises(ProfileAccessRefused):
        projector.materialize_current("denied", current_ref,
            modern_ref=second.current_revision, historical_ref=historical_two,
            profile_views=views)
    assert not (tmp_path / "render" / "denied").exists()
    policy.allowed = True
    with pytest.raises(ValueError, match="PROFILE_DIGEST_DRIFT"):
        projector.materialize_current("wrong-old-digest", current_ref,
            modern_ref=second.current_revision,
            historical_ref=HistoricalHarnessRef("opencode", "main", 2, "sha256:" + "0" * 64),
            profile_views=views)
    assert not (tmp_path / "render" / "wrong-old-digest").exists()

    archived = profiles.archive("main", expected_version=2,
        request=profiles.request_key("archive-main"))
    assert archived.archived
    assert profiles.get_revision(second.current_revision).ref == second.current_revision
    with pytest.raises(ProfileAccessRefused, match="archived"):
        projector.materialize_current("archived", current_ref,
            modern_ref=second.current_revision, historical_ref=historical_two,
            profile_views=views)
    assert not (tmp_path / "render" / "archived").exists()
    assert not (tmp_path / "profiles").exists()


def test_disabled_historical_provenance_cannot_render_even_if_same_service_holds_it(owner, tmp_path):
    environment, profiles, views, _policy = owner
    disabled_capture, historical = _capture("disabled", 1, "controlled", disabled=True)
    with pytest.raises(ValueError, match="PROFILE_DISABLED"):
        import_harness_profile(profiles=profiles, captured=disabled_capture,
            profile_id="disabled", name="Disabled",
            content=_content(environment.environment_id, "disabled"),
            request=profiles.request_key("disabled-import"))
    assert profiles.list() == ()

    # A controlled pre-existing metadata row exercises the view's separate
    # fail-closed disabled check. The only write remains ProfileService.create;
    # this fixture does not open a legacy directory or forge an import receipt.
    content = _content(environment.environment_id, "disabled-preexisting")
    content["metadata"][PROVENANCE_FIELD] = validated_capture(disabled_capture)
    entry = profiles.create(profile_id="disabled", name="Disabled", content=content,
        request=profiles.request_key("disabled-preexisting"))
    projector = OpenCodeProjector(tmp_path / "render")
    with pytest.raises(ProfileAccessRefused, match="disabled"):
        projector.materialize_current("disabled", OpenCodeProfileRef("disabled", 1, historical.digest),
            modern_ref=entry.current_revision, historical_ref=historical, profile_views=views)
    assert not (tmp_path / "render" / "disabled").exists()
    assert not (tmp_path / "profiles").exists()
