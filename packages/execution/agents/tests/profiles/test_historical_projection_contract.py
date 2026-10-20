import hashlib
import json
from dataclasses import dataclass

import pytest

from ordessa_execution_agents.profiles import (
    AgentBoxProfileV1,
    exact_historical_envelope,
)


@dataclass(frozen=True)
class HistoricalRef:
    harness_type: str
    profile_id: str
    revision: int
    digest: str


@dataclass(frozen=True)
class HistoricalView:
    historical_ref: HistoricalRef
    value: dict

    def envelope(self):
        return dict(self.value)


def historical_view():
    value = {
        "profile_id": "profile-old",
        "harness_type": "fixture",
        "provider_id": "harness-profile",
        "name": "Historical profile",
        "schema_version": 1,
        "revision": 2,
        "disabled": False,
        "credential_source_ref": None,
        "capability_refs": [],
        "session_overlay_policy": {"mode": "execution-local"},
        "import_provenance": None,
        "native_payload": {"model": "fixture"},
    }
    body = {key: child for key, child in value.items() if key != "revision"}
    digest = "sha256:" + hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()
    value["digest"] = digest
    ref = HistoricalRef("fixture", "profile-old", 2, digest)
    return HistoricalView(ref, value)


def test_historical_projection_keeps_legacy_identity_separate_from_modern_profile():
    assert AgentBoxProfileV1.contract_id == "agent-box.profile@1"
    view = historical_view()
    result = exact_historical_envelope(
        view,
        harness_type="fixture",
        profile_id="profile-old",
        revision=2,
        digest=view.historical_ref.digest,
    )
    assert result["native_payload"] == {"model": "fixture"}
    assert result["digest"] == view.historical_ref.digest


def test_historical_projection_refuses_a_different_old_revision():
    view = historical_view()
    with pytest.raises(ValueError, match="PROFILE_REF_MISMATCH"):
        exact_historical_envelope(
            view,
            harness_type="fixture",
            profile_id="profile-old",
            revision=1,
            digest=view.historical_ref.digest,
        )
