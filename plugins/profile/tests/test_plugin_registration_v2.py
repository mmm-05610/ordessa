"""v2 plugin registration (PV-05): real contributions, lazy store, bare
host untouched.  The provider resolves the platform-owned
``agent-box.profile@1`` contract from the plugin's own store.
"""
from __future__ import annotations

import pytest
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1
from pacthold.work_core.models import Ref, RefType

from ordessa_profile import create_plugin
from ordessa_profile.plugin import ProfileResourceProvider


def _ctx(tmp_path):
    return type("Ctx", (), {"agent_box_version": "test",
                            "agent_box_home": tmp_path,
                            "plugin_data_dir": tmp_path / "data"})()


def test_build_contributes_resource_provider_without_writing(tmp_path):
    plugin = create_plugin()
    registration = plugin.build(_ctx(tmp_path))
    assert registration.resource_providers, "empty registration is a v1 bug"
    assert registration.contracts == (AgentBoxProfileV1,)
    assert registration.execution_providers == ()
    # discovery/build must not touch the filesystem (PluginContext contract)
    assert not (tmp_path / "data").exists() or \
        not any((tmp_path / "data").iterdir())


def test_provider_resolves_profile_contract(tmp_path):
    from ordessa_profile import StaticHarnessCatalog
    provider = ProfileResourceProvider(
        tmp_path / "data",
        harnesses=StaticHarnessCatalog({"pi": frozenset()}))
    core = provider.core()
    profile = core.profiles.create("k1", harness_id="pi", display_name="开发助手")
    ref = Ref(RefType.ARTIFACT, "ordessa-profile", profile["profile_id"],
              metadata={"revision": str(profile["current_revision"])})
    value = provider.resolve(AgentBoxProfileV1.contract_id, ref)
    assert isinstance(value, AgentBoxProfileV1)
    assert value.name == "开发助手"
    assert value.agent_type == "pi"
    assert value.digest.startswith("sha256:")
    assert value.revision == 1


def test_provider_refuses_foreign_refs(tmp_path):
    provider = ProfileResourceProvider(tmp_path / "data")
    foreign = Ref(RefType.ARTIFACT, "someone-else", "p1")
    with pytest.raises(ValueError):
        provider.resolve(AgentBoxProfileV1.contract_id, foreign)


def test_services_facade_exposes_policy_and_catalog(tmp_path):
    plugin = create_plugin()
    services = plugin.services(_ctx(tmp_path))
    policy = services.get_mechanism_policy("local")
    assert policy["revision"] == 1
    updated = services.update_mechanism_policy(
        "k1", realm="local", expected_revision=1,
        patch={"allow_user_override_writes_global": False}, caller="test")
    assert updated["policy"]["revision"] == 2
    assert services.describe_facets(None) == []
