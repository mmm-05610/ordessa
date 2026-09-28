"""Third-party facet extensibility proof (PV-03/PV-06, G01/G16/G19 backend).

A test-domain v2 facet provider registers through the public surface and
runs the full chain — register → describe → save → resolve → compile —
with **zero core changes**.  The core-source assertion below is the proof:
no core module may mention the test facet's business name.
"""
from __future__ import annotations

import pytest

from conftest import ScriptedConfigPort, ScriptedV2Provider, make_core
from ordessa_profile import ProfileError

TEST_FACET = "acme_widget"
TEST_ITEMS = (("widget_mode", {"type": "string", "enum": ["fast", "slow"]}),
              ("widget_count", {"type": "integer", "minimum": 0}))


def third_party_world(tmp_path, *, with_port=True):
    provider = ScriptedV2Provider(TEST_FACET, TEST_ITEMS,
                                  capability_rule="yes")
    core = make_core(
        tmp_path,
        v2_providers=((provider, "acme-corp.plugin"),),
        config_port=ScriptedConfigPort() if with_port else None,
    )
    return core, provider


def test_registration_requires_host_injected_owner(tmp_path):
    provider = ScriptedV2Provider(TEST_FACET, TEST_ITEMS)
    core = make_core(tmp_path)
    with pytest.raises(ProfileError) as exc:
        core.register_v2_provider(provider, owner_plugin_id="")
    assert exc.value.code == "FACET_INVALID_PROVIDER"


def test_duplicate_facet_id_refused_across_owners(tmp_path):
    core, provider = third_party_world(tmp_path)
    impostor = ScriptedV2Provider(TEST_FACET, TEST_ITEMS)
    with pytest.raises(ProfileError) as exc:
        core.register_v2_provider(impostor, owner_plugin_id="other.plugin")
    assert exc.value.code == "FACET_ID_CONFLICT"
    assert core.registry.owner_of(TEST_FACET) == "acme-corp.plugin"


def test_full_chain_through_public_surface(tmp_path):
    core, provider = third_party_world(tmp_path)
    # 1. describe: sanitized catalog entry, applicability from capability facts
    catalog = core.describe_facets("pi")
    entry = {e["facet_id"]: e for e in catalog}[TEST_FACET]
    assert entry["owner_plugin_id"] == "acme-corp.plugin"
    assert entry["applicability"] == "supported"
    assert {i["item_id"] for i in entry["items"]} == {
        "widget_mode", "widget_count"}
    assert entry["items"][0]["effect"] in (
        "configuration", "capability-selection", "permission", "instruction")
    # 2. save onto a profile (typed schema validation on the way in)
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    core.profiles.set_facet_values(
        "f1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": TEST_FACET, "item_id": "widget_mode",
                 "value": "fast"},
                {"facet_id": TEST_FACET, "item_id": "widget_count",
                 "value": 0}])
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "f2", profile_id=a["profile_id"],
            expected_version=core.profiles.get(a["profile_id"])["version"],
            values=[{"facet_id": TEST_FACET, "item_id": "widget_count",
                     "value": -1}])
    assert exc.value.code == "FACET_VALUE_INVALID"
    # 3. resolve preview: source facts, zero side effects
    preview = core.resolve_preview(a["profile_id"])
    sources = {(i["facet_id"], i["item_id"]): i["source"]
               for i in preview["items"]}
    assert sources[(TEST_FACET, "widget_mode")] == "profile"
    # 4. compile reaches the port as typed intents, including resets
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "f3", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": TEST_FACET, "item_id": "widget_mode",
                 "value": "slow"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    core.sessions.begin_turn("t1", session_id="S")
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == b["profile_id"]
    assert config["evidence"]["journal"]["state"] == "confirmed"


def test_zero_facet_core_removes_nothing_g01(tmp_path):
    """Zero registered facets: management works; no fake business cards."""
    core = make_core(tmp_path, config_port=None)
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    assert core.describe_facets("pi") == []
    assert core.profiles.list()[0]["profile_id"] == a["profile_id"]
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    config = core.sessions.session_config("S")
    assert config["items"] == []
    assert core.profiles.rename("r1", profile_id=a["profile_id"],
                                expected_version=1,
                                display_name="重命名")["display_name"] == "重命名"


def test_core_source_has_no_facet_business_names():
    """The extensibility proof: core modules carry no third-party facet
    names and no business if-branches (PV-06)."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src" / "ordessa_profile"
    core_files = ["core.py", "sessions.py", "profiles.py", "resolution.py",
                  "policy.py", "storage.py", "repository.py",
                  "application_journal.py", "plugin.py"]
    pattern = re.compile(r"acme_widget|model_selection|output_style|"
                         r"v2_model|clashing", re.I)
    for name in core_files:
        text = (src / name).read_text(encoding="utf-8")
        assert not pattern.search(text), f"business name leaked into {name}"


def test_unregister_hides_and_preserves_then_reregister_migrates(tmp_path):
    core, provider = third_party_world(tmp_path)
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    core.profiles.set_facet_values(
        "f1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": TEST_FACET, "item_id": "widget_mode",
                 "value": "fast"}])
    generation_before = core.registry.generation
    core.unregister_provider(provider)
    assert core.registry.generation > generation_before
    # values are retained while the provider is away (G13)
    assert core.profiles.facet_values(a["profile_id"])[0]["value"] == "fast"
    assert core.describe_facets("pi") == []
    # a re-registered provider (same owner) rules on the stored values
    core.register_v2_provider(provider, owner_plugin_id="acme-corp.plugin")
    report = core.reload_v2_provider(provider)
    assert report.accepted + report.migrated >= 1
