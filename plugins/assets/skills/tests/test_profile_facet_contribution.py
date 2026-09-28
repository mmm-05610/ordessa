"""Real profile-api consumption pins for the `assets.skills` facet.

The profile-api checkpoint (specs/011-plugin-rollout/checkpoints/
profile-api.json) publishes `ordessa_profile.contracts` and
`ordessa_profile.plugin.ProfilePluginServices.register_v2_facet /
describe_facets / resolve_preview`; the intended usage is the proof chain
in `plugins/profile/tests/test_v2_extension.py`. These tests run OUR facet
through that same public surface — registration happens through the
published API and nowhere else, reads go through `resolve_preview`, and no
Profile writer is ever called by this domain.

Tree-state note (registered for the lead, honestly, not hidden): as of the
merge of foundation, `import ordessa_profile` fails in this tree because
`plugins/profile/src/ordessa_profile/plugin.py:17` still imports
`AgentBoxProfileV1` from `pacthold.resource_contracts`, and the foundation
checkpoint emptied that module tree (the symbol now lives at
`pacthold_runtime_compat.resource_contracts.agent_box_profile_v1`). The
profile package is upstream code this workstream may not edit, so the
integration tests below are RED with exactly that upstream cause; the pure
mapping tests (which need no upstream import) stay green. Nothing here is
skipped or xfailed to disguise the count.

Test-side `sys.path` additions follow the established convention in
tests/conftest.py + tests/skills_wire_support.py: repo `src/` roots are
added ONLY when the module is not importable, so the in-tree venv (where
these distributions are not pip-installed) keeps working while the G21
package-isolation run resolves everything from installed wheels in
site-packages. The ordessa_profile IMPORT itself happens inside the
fixture, so this module collects even while the upstream import is broken.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
for _module, _src in (("ordessa_profile", REPO_ROOT / "plugins" / "profile" / "src"),
                      ("pacthold_runtime_compat",
                       REPO_ROOT / "plugins" / "runtime-compat" / "src")):
    if (importlib.util.find_spec(_module) is None
            and _src.is_dir() and str(_src) not in sys.path):
        sys.path.append(str(_src))

from ordessa_skills.api.errors import AssetDomainError  # noqa: E402
from ordessa_skills.plugin import PLUGIN_ID  # noqa: E402
from ordessa_skills.profile_contribution import (  # noqa: E402
    DISABLE_VALUE,
    FACET_API_MAJOR,
    FACET_ID,
    FACET_SCHEMA_VERSION,
    ProfileApiLayerPort,
    SkillsFacetProvider,
    decision_value,
    entry_from_value,
    register_skills_facet,
)


# -- the pure mapping layer (no upstream imports) -------------------------------


def test_tristate_encoding_round_trip():
    assert entry_from_value(decision_value(7)) == ("enable", 7)
    assert entry_from_value(DISABLE_VALUE) == ("disable", None)
    # inherit is the ABSENCE of a value — there is no third stored spelling,
    # and nothing decodes to "latest": the enable half is always a pin.
    assert entry_from_value({"decision": "enable"}) is None
    assert entry_from_value({"decision": "enable", "revision": 0}) is None
    assert entry_from_value({"decision": "enable", "revision": True}) is None
    assert entry_from_value({"decision": "whatever"}) is None
    assert entry_from_value("enable") is None
    with pytest.raises(ValueError):
        decision_value(0)


def test_facet_identity_is_the_contracts_documented_id():
    """docs/design/skills-v2/contracts.md §Profile names the facet
    `assets.skills`; a drifted id would register a second, unrelated face."""
    assert FACET_ID == "assets.skills"
    assert FACET_API_MAJOR == 2
    assert FACET_SCHEMA_VERSION.count(".") == 2


# -- the real profile-api chain --------------------------------------------------


@pytest.fixture
def profile_services(tmp_path):
    """A REAL composed `ProfilePluginServices` over a `ProfileCore` (the
    checkpoint's own facade construction — same as the proof test), or an
    honest failure naming the upstream symbol that blocks it."""
    try:
        from ordessa_profile.core import ProfileCore, StaticHarnessCatalog
        from ordessa_profile.plugin import ProfilePluginServices
    except Exception as exc:  # noqa: BLE001 - RED by upstream, see docstring
        pytest.fail(
            "profile-api is not importable in this tree — upstream gap: "
            "plugins/profile/src/ordessa_profile/plugin.py imports "
            "'AgentBoxProfileV1' from 'pacthold.resource_contracts' (module "
            "emptied by the foundation checkpoint; the symbol now lives at "
            "pacthold_runtime_compat.resource_contracts."
            "agent_box_profile_v1). Q1 may not edit plugins/profile. "
            f"underlying error: {exc!r}")
    core = ProfileCore(
        str(tmp_path / "profile-store.sqlite"),
        # the controlled fixture catalog (mirrors plugins/profile's own
        # make_core: pi/codex exist, required-item sets empty) — marked
        # controlled-fixture per the checkpoint's evidence discipline.
        harnesses=StaticHarnessCatalog({"pi": frozenset(),
                                        "codex": frozenset()}),
    )
    return ProfilePluginServices(core)


def _make_profile(services, name="A", harness="pi"):
    return services.core.profiles.create(
        name, harness_id=harness, display_name=name)["profile_id"]


def test_registration_uses_the_published_facet_api_only(profile_services):
    """Registration goes through `ProfilePluginServices.register_v2_facet`
    with the host-injected owner; afterwards Profile's own catalog sees the
    facet under OUR plugin id — no core module was touched (PV-06 proof
    pattern)."""
    services = profile_services
    provider = register_skills_facet(
        services, owner_plugin_id=PLUGIN_ID,
        asset_ids=lambda: ["demo-skill", "other-skill"])
    catalog = services.describe_facets("pi")
    entry = {e["facet_id"]: e for e in catalog}.get(FACET_ID)
    assert entry is not None, catalog
    assert entry["owner_plugin_id"] == PLUGIN_ID
    assert entry["api_major"] == FACET_API_MAJOR
    assert {i["item_id"] for i in entry["items"]} == {
        "demo-skill", "other-skill"}
    # three-valued applicability, honest for the composed brands and never
    # promoted for others (research/brand-matrix.md is the only evidence):
    assert entry["applicability"] in ("supported", "unknown", "unsupported")
    pi_entry = entry
    assert pi_entry["applicability"] == "supported"
    unknown = services.describe_facets("hermes")
    assert {e["facet_id"]: e for e in unknown}[FACET_ID]["applicability"] \
        == "unknown"
    # duplicate id under another owner is THEIR refusal, not our shadow:
    from ordessa_profile import ProfileError
    with pytest.raises(ProfileError) as info:
        services.register_v2_facet(provider, owner_plugin_id="someone.else")
    assert info.value.code == "FACET_ID_CONFLICT"


def test_provider_compile_declares_zero_config_intents(profile_services):
    """The facet never speaks for an application it does not perform: skill
    projection runs through the Skills harness adapters (§G2), so compile
    answers a clean, EMPTY `CompileResult` — a fake set-intent would let
    Profile's journal claim `port-confirmed` for content nothing applied
    (evidence.py: no rung above its own proof). Asserted against the REAL
    contract type from the published checkpoint surface."""
    from ordessa_profile.contracts import CompileResult

    provider = SkillsFacetProvider(asset_ids=lambda: ["demo-skill"])
    result = provider.compile({"demo-skill": decision_value(1)},
                              {"harness_id": "pi"})
    assert isinstance(result, CompileResult)
    assert result.ok
    assert result.intents == ()
    assert result.violations == ()


def test_real_resolve_round_trip(profile_services):
    """A Profile editor writes the facet values through Profile's own API;
    our `ProfileApiLayerPort` reads the tri-state back through
    `resolve_preview` — enable keeps its FIXED revision, disable stays an
    explicit off, and an asset without a row is inherit (no entry)."""
    services = profile_services
    register_skills_facet(
        services, owner_plugin_id=PLUGIN_ID,
        asset_ids=lambda: ["demo-skill", "other-skill"])
    core = services.core
    profile = core.profiles.create("ka", harness_id="pi",
                                   display_name="Agent A")
    pid = profile["profile_id"]
    core.profiles.set_facet_values(
        "f1", profile_id=pid, expected_version=1,
        values=[
            {"facet_id": FACET_ID, "item_id": "demo-skill",
             "value": decision_value(3)},
            {"facet_id": FACET_ID, "item_id": "other-skill",
             "value": dict(DISABLE_VALUE)},
        ])
    layer = ProfileApiLayerPort(services)
    entries = {e["assetId"]: e for e in layer.skill_entries(pid)}
    assert entries["demo-skill"]["decision"] == "enable"
    assert entries["demo-skill"]["revision"] == 3
    assert entries["other-skill"]["decision"] == "disable"
    # inherit is the absence of a row (data-model 三态) — never a fake entry:
    assert layer.harness_id(pid) == "pi"
    identity = layer.revision_identity(pid)
    preview = services.resolve_preview(pid)
    assert identity == {
        "profileId": preview["profile_id"],
        "configRevision": preview["revision"],
        "configObjectDigest": preview["digest"],
    }
    assert identity["configRevision"] >= 1
    assert identity["configObjectDigest"]


def test_profile_layer_is_read_only_no_writes_behind_the_back(
        profile_services, monkeypatch):
    """Every method of `ProfileApiLayerPort` must be a read through the
    facade: this spies ALL writer-shaped calls on the composition-owned
    services object and proves the skills domain never reaches one."""
    services = profile_services
    register_skills_facet(
        services, owner_plugin_id=PLUGIN_ID,
        asset_ids=lambda: ["demo-skill"])
    core = services.core
    pid = core.profiles.create("ka", harness_id="pi",
                               display_name="A")["profile_id"]
    core.profiles.set_facet_values(
        "f1", profile_id=pid, expected_version=1,
        values=[{"facet_id": FACET_ID, "item_id": "demo-skill",
                 "value": decision_value(1)}])
    touched: list[str] = []
    for name in ("set_facet_values", "create", "rename", "archive",
                 "select_profile", "begin_turn"):
        service = None
        for holder in (core.profiles, core.sessions):
            if hasattr(holder, name):
                service = holder
                break
        if service is None:
            continue
        original = getattr(service, name)

        def spy(*args, _orig=original, _name=name, **kwargs):
            touched.append(_name)
            return _orig(*args, **kwargs)
        monkeypatch.setattr(service, name, spy)

    layer = ProfileApiLayerPort(services)
    list(layer.skill_entries(pid))
    layer.harness_id(pid)
    layer.revision_identity(pid)
    assert touched == [], f"the profile layer wrote through: {touched}"


def test_absent_profile_refuses_with_a_type(profile_services):
    """An unknown profileId answers the domain's typed refusal (the Profile
    service said so) — never an empty list pretending everything inherits."""
    layer = ProfileApiLayerPort(profile_services)
    with pytest.raises(AssetDomainError) as info:
        layer.skill_entries("no-such-profile")
    assert info.value.code in ("PROFILE_UNKNOWN", "PROFILE_LAYER_OUTAGE")


def test_harness_port_absence_keeps_their_typed_block(profile_services):
    """HarnessConfigPort absence is Profile's own typed block: a session
    switch application refuses with APPLICATION_PORT_ABSENT and NOTHING is
    journalled as applied, while the skills facet layer above it still
    resolves for planning (reads never depend on the application port)."""
    services = profile_services
    assert services.core.config_port is None  # no Harness composed
    register_skills_facet(
        services, owner_plugin_id=PLUGIN_ID,
        asset_ids=lambda: ["demo-skill"])
    core = services.core
    pid_a = _make_profile(services, "A")
    pid_b = _make_profile(services, "B")
    core.profiles.set_facet_values(
        "f1", profile_id=pid_b, expected_version=1,
        values=[{"facet_id": FACET_ID, "item_id": "demo-skill",
                 "value": decision_value(2)}])
    layer = ProfileApiLayerPort(services)
    # the resolver's layer read works without the port (it is a plan-time
    # fact, not an application claim):
    assert list(layer.skill_entries(pid_b))[0]["revision"] == 2
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=pid_a)
    core.sessions.select_profile("sel", session_id="S", profile_id=pid_b)
    from ordessa_profile import ProfileError
    with pytest.raises(ProfileError) as info:
        core.sessions.begin_turn("t1", session_id="S")
    assert info.value.code == "APPLICATION_PORT_ABSENT"
    # nothing was ever claimed applied: the journal's latest fact for the
    # session is the PLANNED attempt, not a confirmed receipt (their
    # absence semantics consumed, not reimplemented).
    config = core.sessions.session_config("S")
    journal_state = ((config.get("evidence") or {}).get("journal") or {}).get("state")
    assert journal_state in (None, "planned")
