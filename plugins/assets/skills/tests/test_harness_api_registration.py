"""The three brand adapters registered through the REAL published seam.

Proves, against the merged harness-api (publication `d3f026904e`) and the
harness's own contribution handler:

1. the point identity we contribute to equals the published constants
   (`ordessa_harness.contributions`), and the default product declares
   that point (cite);
2. the adapters ride the host's C2 transaction into the harness handler
   in a live composed runtime (fixture binds the real handler; the plugin
   never touches a registry itself);
3. overlapping facet/harness/entry/version ranges and overlapping field
   claims REFUSE at registration (contracts.md §C2 — no priority, no
   last-wins);
4. `assess`/`compile`/`verify` answer with the published DTOs and keep
   the conservative rules: unknown vs unsupported distinct, version
   mismatch fail-closed, host-path payloads refused BEFORE any DTO
   exists, placement-only observations never reach Match's ceiling as a
   load claim, model claims unknown, unknown capability never offered.
"""
from __future__ import annotations

import pytest

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapter,
    ConfigurationCapabilities, ContractError, ErrorCode, FieldClaim,
    Installation, IntentSet, Match, Mismatch, MountContent, TargetDescriptor,
    TargetHandle, VerificationUnknown,
)
# TEST-side imports of the harness internals are allowed (the src-side
# direction is pinned by test_dependency_direction.py): these are exactly
# the published point constants and the handler the default product binds.
from ordessa_harness.contributions import (
    CONFIGURATION_POINT as PUBLISHED_CONFIGURATION_POINT,
    HarnessContributionError,
    HarnessContributionRegistry,
    POINT_API_VERSION as PUBLISHED_POINT_API_VERSION,
)
from server_plugin_api import Contribution

from ordessa_skills.harness_adapters import codex as codex_module
from ordessa_skills.harness_adapters import contribution as V
from ordessa_skills.harness_adapters import pi as pi_module
from ordessa_skills.harness_adapters.capabilities import pin_for
from ordessa_skills.profile_contribution.provider import FACET_ID

DIGEST_HEX = "a" * 64
DIGEST = "sha256:" + DIGEST_HEX

ADAPTERS = V.configuration_adapters()


def _payload(*, name="demo-skill", asset="demo-skill", revision=1,
             size=128, extra_assets=()):
    assets = [{"assetId": asset, "revision": revision,
               "treeDigest": DIGEST, "nativeName": name,
               "sizeBytes": size}]
    assets += [dict(item) for item in extra_assets]
    return {"assets": assets, "runtimeGeneration": "gen-1",
            "projectId": "proj-1", "profileRevision": 1,
            "assignmentRevision": 2}


def _context(harness_id="pi", *, native=(0, 84, 2), adapter=(0, 5, 0),
             entry="acp", with_target=True):
    installation = Installation(harness_id=harness_id,
                                native_version=native,
                                adapter_version=adapter,
                                evidence_ref="specs/011-q1-skills/research/brand-matrix.md:40")
    targets = ()
    if with_target:
        targets = (TargetDescriptor(
            handle=TargetHandle(handle_id=f"srv-issued-{harness_id}",
                                generation=1),
            kind="directory", codec="content", scope="instance"),)
    return AdapterContext(targets=targets, installation=installation,
                          entry=entry, scope="instance",
                          capability_evidence_ref="specs/011-q1-skills/research/brand-matrix.md:40")


# -- 1. the seam identity --------------------------------------------------------


def test_the_point_identity_matches_the_published_constants():
    assert V.CONFIGURATION_POINT == PUBLISHED_CONFIGURATION_POINT
    assert V.POINT_API_VERSION == PUBLISHED_POINT_API_VERSION
    # the facet side is one facet: the profile-api facet and the harness
    # IntentSource facet are the SAME id (contracts §C2/C3 attribution).
    assert V.SKILLS_FACET_ID == FACET_ID == "assets.skills"


def test_descriptors_are_valid_and_unique_across_the_three_brands():
    ids = [adapter.descriptor.adapter_id for adapter in ADAPTERS]
    assert len(ids) == len(set(ids)) == 3
    for adapter in ADAPTERS:
        d = adapter.descriptor
        assert d.api_version == "v1"
        assert d.facet_id == FACET_ID
        assert d.entries == (V.SKILL_ENTRY,)
        pin = pin_for(d.harness_id)
        assert d.native_versions.minimum == V.version_tuple(pin.native_version)
        assert d.adapter_versions.maximum == V.version_tuple(pin.adapter_version)
        assert all(isinstance(claim, FieldClaim) for claim in d.claims)
        # the registered schema accepts the controlled payload and
        # refuses a malformed one (typed, not silent):
        d.payload_schema.validate(_payload())
        with pytest.raises(ContractError):
            d.payload_schema.validate({"assets": [{"assetId": "x"}]})


def test_adapters_structurally_satisfy_the_published_protocol():
    for adapter in ADAPTERS:
        for name in ("descriptor", "assess", "compile", "verify"):
            assert hasattr(adapter, name), name
        # not isinstance-checkable (the Protocol is not runtime_checkable),
        # but the three methods carry the published arity (bound: context,
        # before/desired... — assess 2 + self, compile 3 + self...):
        import inspect
        assert len(inspect.signature(adapter.compile).parameters) == 3
        assert len(inspect.signature(adapter.assess).parameters) == 2
        assert len(inspect.signature(adapter.verify).parameters) == 2


# -- 2. registration through the real host transaction ----------------------------


def _plugin_rows(tmp_path):
    """The registration OUR plugin builds when the composition binds the
    point (`contribute_harness_adapters=True`, the default): three adapter
    rows on the open point plus the error-family row."""
    from pacthold_runtime_compat.storage import Database
    from server_plugin_api import ServerPluginContext

    from ordessa_skills.plugin import SkillsServerPlugin
    context = ServerPluginContext(
        plugin_id="ordessa.skills", data_root=tmp_path,
        ports={"database": Database(tmp_path / "db.sqlite3")})
    plugin = SkillsServerPlugin()
    registration = plugin.build(context)
    try:
        batch = registration.contributions
        rows = [c for c in batch.contributions
                if c.point_id == V.CONFIGURATION_POINT]
        assert len(rows) == 3
        assert V.CONFIGURATION_POINT in batch.open_points  # multi-owner
        assert [r.payload.descriptor.adapter_id for r in rows] == [
            "assets.skills.pi", "assets.skills.codex",
            "assets.skills.claude-code"]
        assert all(isinstance(r.payload, V.SkillsConfigurationAdapter)
                   for r in rows)
        return registration
    finally:
        if registration.disposal is not None:
            registration.disposal()


def test_the_plugin_declares_the_adapter_rows_on_the_published_point(tmp_path):
    _plugin_rows(tmp_path)


def test_the_real_host_publishes_the_rows_through_the_harness_handler():
    """A live `ServerPluginHost` round (apps/server's own host, TEST-side
    import) with the point bound to the harness's published handler —
    exactly the shape `products/server.server_contribution_points()` +
    `build_runtime` create in the default product: stage/commit run, the
    owner is host-injected, and the harness registry publishes our three
    descriptors."""
    from ordessa_harness.contributions import HarnessContributionRegistry
    from ordessa_server.plugin_host import ServerPluginHost
    from server_plugin_api import (
        Contribution, ContributionBatch, ServerPluginDescriptor,
        ServerPluginRegistration,
    )

    registry = HarnessContributionRegistry()
    host = ServerPluginHost()
    host.register_contribution_point(V.CONFIGURATION_POINT, V.POINT_API_VERSION,
                                     handler=registry.configuration_handler,
                                     exclusive=False)

    class _Carrier:
        """A minimal plugin whose ONLY registration fact is our real batch
        rows — the host's own transaction carries them; nothing private is
        reached."""

        def descriptor(self):
            return ServerPluginDescriptor(id="ordessa.skills.carrier",
                                          display_name="carrier", version="1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch(
                tuple(Contribution(point_id=V.CONFIGURATION_POINT,
                                   api_version=V.POINT_API_VERSION,
                                   payload=adapter)
                      for adapter in V.configuration_adapters()),
                open_points=frozenset({V.CONFIGURATION_POINT})))

    host.activate_all((_Carrier(),))
    assert {d.adapter_id for d in registry.configuration_descriptors()} == {
        "assets.skills.pi", "assets.skills.codex",
        "assets.skills.claude-code"}
    views = host.contributions(V.CONFIGURATION_POINT)
    assert {v.owner for v in views} == {"ordessa.skills.carrier"}

    # a second carrier with an overlapping range is refused AT REGISTRATION
    # and publishes nothing (no priority, no last-wins — §C2):
    clash = V.SkillsConfigurationAdapter(harness_id="pi", target_slot="skills")
    object.__setattr__(clash.descriptor, "adapter_id", "skills.pi.rival")

    class _Rival:
        def descriptor(self):
            return ServerPluginDescriptor(id="ordessa.rival",
                                          display_name="rival", version="1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch(
                (Contribution(point_id=V.CONFIGURATION_POINT,
                              api_version=V.POINT_API_VERSION, payload=clash),)))

    with pytest.raises(HarnessContributionError):
        host.activate_all((_Rival(),))
    assert len(registry.configuration_descriptors()) == 3
    host.shutdown()


def test_an_unbound_point_refuses_the_batch_fail_closed(tmp_path):
    """The documented refusal: a contribution to a point the composition
    never declared/binds is a typed activation failure, not a drop. A bare
    `ServerPluginHost` without the point is that state."""
    from ordessa_server.plugin_host import ServerPluginHost
    from server_plugin_api import (
        ContributionPointUnboundError, ServerPluginDescriptor,
        ServerPluginRegistration,
    )

    host = ServerPluginHost()

    class _Carrier:
        def descriptor(self):
            return ServerPluginDescriptor(id="ordessa.skills.carrier",
                                          display_name="carrier", version="1")

        def build(self, context):
            registration_rows = _plugin_rows_batch()
            return ServerPluginRegistration(contributions=registration_rows)

    def _plugin_rows_batch():
        from server_plugin_api import Contribution, ContributionBatch
        return ContributionBatch(
            tuple(Contribution(point_id=V.CONFIGURATION_POINT,
                               api_version=V.POINT_API_VERSION,
                               payload=adapter)
                  for adapter in V.configuration_adapters()),
            open_points=frozenset({V.CONFIGURATION_POINT}))

    with pytest.raises(ContributionPointUnboundError):
        host.activate_all((_Carrier(),))


# -- 3. overlap refuses at registration -------------------------------------------


def _stage_and_commit(registry, payload, owner):
    from server_plugin_api import ContributionBatch, stage_contributions
    contribution = Contribution(point_id=V.CONFIGURATION_POINT,
                                api_version="v1", payload=payload)
    staged = stage_contributions(
        registry.configuration_handler, owner,
        ContributionBatch((contribution,),
                          open_points=frozenset({V.CONFIGURATION_POINT})))
    staged.commit()
    return staged


def _registry_with_ours():
    registry = HarnessContributionRegistry()
    for adapter in ADAPTERS:
        _stage_and_commit(registry, adapter, "ordessa.skills")
    return registry


def test_duplicate_adapter_id_refuses_at_registration():
    registry = _registry_with_ours()
    with pytest.raises(HarnessContributionError):
        _stage_and_commit(registry, pi_module.ADAPTER, "another.plugin")


def test_overlapping_facet_entry_version_range_refuses():
    registry = _registry_with_ours()
    # same facet, same harness, same entry, version range overlapping the
    # pinned pi range: contracts §C2 — refuse, no priority, no last-wins.
    clash = V.SkillsConfigurationAdapter(harness_id="pi", target_slot="skills")
    object.__setattr__(clash.descriptor, "adapter_id", "skills.pi.rival")
    with pytest.raises(HarnessContributionError) as info:
        _stage_and_commit(registry, clash, "rival.plugin")
    assert "overlap" in str(info.value)
    # the refusal published NOTHING:
    assert len(registry.configuration_descriptors()) == 3


def test_overlapping_field_claims_refuse_across_facets():
    registry = _registry_with_ours()
    clash = V.SkillsConfigurationAdapter(harness_id="pi", target_slot="skills")
    object.__setattr__(clash.descriptor, "adapter_id", "other.facet.pi")
    object.__setattr__(clash.descriptor, "facet_id", "assets.other")
    with pytest.raises(HarnessContributionError) as info:
        _stage_and_commit(registry, clash, "rival.plugin")
    assert "claim" in str(info.value)


# -- 4. published assess/compile/verify semantics ----------------------------------


def test_assess_version_mismatch_fails_closed_as_unsupported():
    adapter = pi_module.ADAPTER
    got = adapter.assess(_context(native=(0, 99, 0)), None)
    assert got.status == "unsupported"
    assert "pinned" in got.reason


def test_assess_uninspected_version_is_unknown_not_unsupported():
    # unknown != unsupported (the registry's distinct meanings survive at
    # the published boundary): an uninspected native version is unknown.
    got = pi_module.ADAPTER.assess(_context(native=None), None)
    assert isinstance(got, Assessment)
    assert got.status == "unknown"
    assert "not inspected" in got.reason


def test_assess_unevidenced_entry_is_unknown_and_never_grants_capability():
    got = pi_module.ADAPTER.assess(_context(entry="cli"), None)
    assert got.status == "unknown"
    # entry alone never promotes:
    ok = pi_module.ADAPTER.assess(_context(entry="acp"), None)
    assert ok.status == "supported"


def test_compile_uses_the_server_issued_handle_and_published_mounts():
    got = pi_module.ADAPTER.compile(_context(), None, _payload())
    assert isinstance(got, IntentSet)
    (mount,) = got.intents
    assert isinstance(mount, MountContent)
    assert mount.target.handle_id == "srv-issued-pi"  # NOT self-chosen
    assert mount.relative_name == "skills/demo-skill"
    assert mount.immutable_content_ref.sha256 == DIGEST_HEX
    assert mount.source.facet_id == FACET_ID


def test_compile_refuses_a_host_path_payload_before_any_dto():
    smuggled = _payload()
    smuggled["assets"][0]["nativeName"] = "x"
    smuggled["projectId"] = "/home/maoqh/.claude/skills"
    got = pi_module.ADAPTER.compile(_context(), None, smuggled)
    assert isinstance(got, AdapterRefusal)
    assert got.code == ErrorCode.INVALID_FRAGMENT


def test_compile_without_a_content_target_refuses_instead_of_choosing():
    got = pi_module.ADAPTER.compile(_context(with_target=False), None,
                                    _payload())
    assert isinstance(got, AdapterRefusal)
    assert got.code == ErrorCode.ADAPTER_MISSING


def test_compile_refuses_a_version_mismatch_installation():
    got = pi_module.ADAPTER.compile(_context(adapter=(9, 9, 9)), None,
                                    _payload())
    assert isinstance(got, AdapterRefusal)
    assert got.code in (ErrorCode.VERSION_UNVERIFIED,
                        ErrorCode.CAPABILITY_UNSUPPORTED)


def test_verify_placement_match_is_match_but_never_a_load_claim():
    adapter = pi_module.ADAPTER
    got = adapter.verify(_context(), {"source": "projection_digest",
                                      "expectedDigest": DIGEST,
                                      "observedDigest": DIGEST})
    assert isinstance(got, Match)
    assert "placement-only" in got.evidence_ref
    assert "projected" in got.evidence_ref


def test_verify_digest_mismatch_is_mismatch():
    got = pi_module.ADAPTER.verify(_context(), {"source": "projection_digest",
                                                "expectedDigest": DIGEST,
                                                "observedDigest": "b" * 64})
    assert isinstance(got, Mismatch)


@pytest.mark.parametrize("observed", [
    {"source": "model_claim", "expectedDigest": DIGEST,
     "observedDigest": DIGEST},
    {"source": "something_else", "expectedDigest": DIGEST},
    {"source": "projection_digest"},
    "not-an-object",
])
def test_verify_unknown_never_reports_success(observed):
    got = pi_module.ADAPTER.verify(_context(), observed)
    assert isinstance(got, VerificationUnknown)


def test_load_or_invocation_events_stay_unknown_for_every_brand():
    # capabilities say unknown -> the published boundary answers
    # VerificationUnknown, never Match, for load/invocation observations.
    for adapter in ADAPTERS:
        for source in ("native_load_event", "invocation_event"):
            brand = adapter.descriptor.harness_id
            pin = pin_for(brand)
            ctx = _context(harness_id=brand,
                           native=V.version_tuple(pin.native_version),
                           adapter=V.version_tuple(pin.adapter_version))
            got = adapter.verify(ctx,
                                 {"source": source, "expectedDigest": DIGEST,
                                  "observedDigest": DIGEST})
            assert isinstance(got, VerificationUnknown), (
                adapter.descriptor.harness_id, source)


def test_inspected_capabilities_never_offer_an_unknown_cell():
    from ordessa_harness_api import ApplicationTarget
    target = ApplicationTarget(server_id="s", session_id="sess",
                               channel_id="ch", runtime_generation=1)
    for adapter in ADAPTERS:
        caps: ConfigurationCapabilities = adapter.configuration_capabilities(target)
        for cell in caps.capabilities:
            if cell.status == "supported":
                assert cell.evidence_ref  # a supported row cites evidence
        # today NO operation cell is offered (discovery/reload/reset are
        # unknown; set is unsupported by the facet's own contract):
        assert all(cell.status != "supported" for cell in caps.capabilities)
        assert {cell.operation for cell in caps.capabilities} == \
            {"content", "set", "reset", "secret", "action"}
