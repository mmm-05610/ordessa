"""Controlled native renderers consume explicit history views, never FS lookup."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from ordessa_execution_agents.profiles import exact_historical_envelope
from ordessa_server.bootstrap.migrations.harness_profile_projection import HistoricalHarnessRef, HistoricalProfileView
from ordessa_harness_claude_code.profile import ClaudeProfileRef, ClaudeProjection
from ordessa_harness_hermes.projection import HermesProjection
from ordessa_harness_opencode.profiles import OpenCodeProfileRef
from ordessa_harness_opencode.projection import OpenCodeProjector
from ordessa_execution_agents.harness.definitions import NativeProfileRef


def _view(harness_type, native, *, disabled=False):
    value = {"profile_id": "fixture", "harness_type": harness_type,
             "provider_id": "harness-profile", "name": "Fixture", "schema_version": 1,
             "revision": 1, "disabled": disabled, "credential_source_ref": None,
             "capability_refs": [], "session_overlay_policy": {"mode": "execution-local"},
             "import_provenance": None, "native_payload": native}
    body = {k: v for k, v in value.items() if k != "revision"}
    value["digest"] = "sha256:" + hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    ref = HistoricalHarnessRef(harness_type, "fixture", 1, value["digest"])
    return HistoricalProfileView(None, ref, json.dumps(value, sort_keys=True))


def test_exact_old_ref_and_disabled_are_checked_before_native_directory_write(tmp_path):
    view = _view("claude-code", {"settings": {"model": "controlled"}})
    ref = ClaudeProfileRef("fixture", 1, view.historical_ref.digest)
    projection = ClaudeProjection(tmp_path / "render")
    with pytest.raises(ValueError, match="EXPLICIT_HISTORICAL_PROFILE_VIEW_REQUIRED"):
        projection.materialize("e1", ref, historical_view=None)
    assert not (tmp_path / "render").exists()
    with pytest.raises(ValueError, match="PROFILE_REF_MISMATCH"):
        projection.materialize("e1", ClaudeProfileRef("fixture", 1, "sha256:" + "0" * 64),
                               historical_view=view)
    assert not (tmp_path / "render").exists()
    home = projection.materialize("e1", ref, historical_view=view)
    assert json.loads((home / ".claude" / "settings.json").read_text())["model"] == "controlled"
    disabled = _view("claude-code", {"settings": {}}, disabled=True)
    with pytest.raises(ValueError, match="PROFILE_DISABLED"):
        projection.materialize("e2", ClaudeProfileRef("fixture", 1, disabled.historical_ref.digest),
                               historical_view=disabled)
    assert not (tmp_path / "render" / "e2").exists()


def test_hermes_and_opencode_render_explicit_old_payload_without_provider_lookup(tmp_path):
    hermes = _view("hermes", {"model": "controlled"})
    href = NativeProfileRef("harness-profile", "fixture",
               metadata={"harness_type": "hermes", "revision": "1", "digest": hermes.historical_ref.digest})
    home = HermesProjection(tmp_path / "hermes").materialize("e1", href, historical_view=hermes)
    assert "controlled" in (home / "config.yaml").read_text()
    opencode = _view("opencode", {"model": "controlled"})
    oref = OpenCodeProfileRef("fixture", 1, opencode.historical_ref.digest)
    rendered = OpenCodeProjector(tmp_path / "opencode").materialize("e1", oref, historical_view=opencode)
    assert json.loads(rendered.config_path.read_text())["model"] == "controlled"


def test_old_digest_is_not_modern_digest_or_unverified_view(tmp_path):
    view = _view("opencode", {"model": "controlled"})
    raw = view.envelope()
    raw["native_payload"]["model"] = "tampered"
    forged = HistoricalProfileView(None, view.historical_ref, json.dumps(raw, sort_keys=True))
    with pytest.raises(ValueError, match="PROFILE_DIGEST_DRIFT"):
        exact_historical_envelope(forged, harness_type="opencode", profile_id="fixture",
                                  revision=1, digest=view.historical_ref.digest)
