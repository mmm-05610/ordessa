"""Z3 T02 conformance gates for the brand configuration adapters (E1).

Authored in this line against ``docs/implementation/design/harness-v2/contracts.md`` C2/C3 and
``docs/implementation/design/model-provider/harness-adapters.md``. Every gate listed in the
dispatch (``docs/implementation/specifications/011-z3-model-provider/dispatch/t02-adapters.md``) is driven
here; all were red before the adapter modules existed.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from ordessa_agents.harness.definitions import ConfigurationAdapterDescriptor, VersionRange
from ordessa_server.composition.configuration.contributions import HarnessContributionError
from ordessa_server.composition.configuration.contributions import HarnessContributionRegistry
from ordessa_server_plugin_api import Contribution, ContributionBatch, stage_contributions

from ordessa_harness_codex import acp_model_facts as codex_facts
from ordessa_harness_pi import acp_model_facts as pi_facts
from ordessa_agents.harness.definitions.model_compilation import parse_version
from _brand_c2 import adapter_for, c2_module, descriptor_for, owner_for_brand
from ordessa_harness_claude_code.acp_model_configuration import ClaudeAdapter
from ordessa_harness_codex.acp_model_configuration import CodexAdapter
from ordessa_harness_pi.acp_model_configuration import PiAdapter
from ordessa_agents.harness.definitions.model_compilation import (
    AdapterContext, ChoiceRequest, CompileIntent, Refusal, TargetHandle,
)

ADAPTERS = (PiAdapter, CodexAdapter, ClaudeAdapter)

#: 014 PB-2 declaration surface facts
CONFIGURATION_POINT = "harness.configuration-adapters"
SECOND_CLIENT = "second.client.probe"


def common_brands():
    return ("pi", "codex", "claude-code")

#: pinned upstream versions (t00-freeze.md §5) that must assess `supported`
SUPPORTED_VERSIONS = {"pi": "0.5.0", "codex": "1.1.14", "claude-code": "0.81.2"}


_CURRENT = {"harness": "pi"}


def _harness_of_request(brand):
    return _CURRENT["harness"]


def _ctx(harness, version=None, scope="instance"):
    _CURRENT["harness"] = harness

    return AdapterContext(
        target_handle=TargetHandle(harness_id=harness, scope=scope, identity="inst-1"),
        harness_version=version if version is not None else SUPPORTED_VERSIONS[harness],
        capabilities={"native_session_id": "nat-7"},
        generation="gen-1",
    )


#: each brand's own supported protocol (claude speaks anthropic only)
HARNESS_PROTOCOLS = {"pi": "openai-chat", "codex": "openai-responses",
                     "claude-code": "anthropic-messages"}


def _request(protocol=None, model="m1", endpoint="https://api.acme.test/v1",
             credential_ref="ref://cred-1", brand=None):
    protocol = protocol or HARNESS_PROTOCOLS[_harness_of_request(brand)]
    return ChoiceRequest(
        provider_config_id="p-1", model_id=model, endpoint=endpoint,
        protocol=protocol, credential_ref=credential_ref,
        brand_fields=({"before_provider": "acme", **dict(brand or {})}
                      if _CURRENT["harness"] == "codex" else
                      {"provider_in_instance": False, **dict(brand or {})} if _CURRENT["harness"] == "pi" else dict(brand or {})), provider_name="acme",
    )


# -- public brand descriptors + contribution conflict discipline --------------
# Each descriptor and adapter below comes from its brand-owned public C2 factory.
# The production contribution registry still enforces adapter/range/facet/claim
# conflicts at stage time; conflicts are never resolved by registration order.

def test_manifests_are_real_harness_api_descriptors_with_frozen_facet():
    expected = {"pi": "assets.model-provider.pi", "codex": "assets.model-provider.codex",
                "claude-code": "assets.model-provider.claude"}
    for brand in common_brands():
        descriptor = descriptor_for(brand)
        assert isinstance(descriptor, ConfigurationAdapterDescriptor)
        assert descriptor.adapter_id == expected[brand]
        assert descriptor.harness_id == brand
        assert descriptor.facet_id == "assets.model-provider"
        assert descriptor.facet_schema_version == "1"
        assert descriptor.api_version == "v1"
        assert descriptor.entries == ("acp",)
        assert descriptor.claims
        assert descriptor.payload_schema.kind == "object"


def test_descriptor_native_ranges_match_the_pinned_supported_versions():
    for brand, pinned in SUPPORTED_VERSIONS.items():
        parsed = tuple(int(part) for part in pinned.split("."))
        padded = parsed + (0,) * (3 - len(parsed))
        assert descriptor_for(brand).native_versions.contains(padded) is True
        low = parse_version(c2_module(brand).supported_native_versions()[0])
        low_padded = low + (0,) * (3 - len(low))
        assert descriptor_for(brand).native_versions.contains(low_padded) is True


def _batch(brand):
    return ContributionBatch((
        Contribution(CONFIGURATION_POINT, "v1", adapter_for(brand), required=True),
    ), open_points=frozenset({CONFIGURATION_POINT}))


def test_brand_c2_providers_have_distinct_host_owner_ids():
    assert {brand: owner_for_brand(brand) for brand in common_brands()} == {
        "pi": "ordessa.model-provider.pi",
        "codex": "ordessa.model-provider.codex",
        "claude-code": "ordessa.model-provider.claude-code",
    }


def test_three_brands_register_into_the_real_c2_registry():
    registry = HarnessContributionRegistry()
    for brand in common_brands():
        stage_contributions(registry.configuration_handler, owner_for_brand(brand),
                            _batch(brand)).commit()
    assert sorted(d.adapter_id for d in registry.configuration_descriptors()) == [
        "assets.model-provider.claude", "assets.model-provider.codex",
        "assets.model-provider.pi"]


def test_identical_registration_overlap_is_refused_by_real_registry():
    registry = HarnessContributionRegistry()
    for brand in common_brands():
        stage_contributions(registry.configuration_handler, owner_for_brand(brand),
                            _batch(brand)).commit()
    second = ContributionBatch((
        Contribution(CONFIGURATION_POINT, "v1", adapter_for("pi")),
    ))
    with pytest.raises(HarnessContributionError, match="adapter_id already registered"):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_same_harness_overlapping_native_range_refused_by_real_registry():
    """MP-11 production shape: a second client may claim the same facet only
    outside the first owner's native version range; an overlapping range with a
    shared entry is a stage-time refusal."""
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, owner_for_brand("pi"),
                        _batch("pi")).commit()

    overlap = descriptor_for("pi")
    object.__setattr__(overlap, "adapter_id", "assets.model-provider.pi-alt")
    intruder = adapter_for("pi")
    intruder.descriptor = overlap
    second = ContributionBatch((Contribution(CONFIGURATION_POINT, "v1", intruder),))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_disjoint_native_range_accepted_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, owner_for_brand("pi"),
                        _batch("pi")).commit()

    next_range = descriptor_for("pi")
    object.__setattr__(next_range, "adapter_id", "assets.model-provider.pi-next")
    object.__setattr__(next_range, "native_versions", VersionRange((0, 6, 0)))
    successor = adapter_for("pi")
    successor.descriptor = next_range
    second = ContributionBatch((Contribution(CONFIGURATION_POINT, "v1", successor),))
    stage_contributions(registry.configuration_handler, SECOND_CLIENT, second).commit()
    assert {d.adapter_id for d in registry.configuration_descriptors()} >= {
        "assets.model-provider.pi", "assets.model-provider.pi-next"}


# -- version gates -------------------------------------------------------------

@pytest.mark.parametrize("cls", ADAPTERS)
def test_supported_pin_assesses_supported(cls):
    harness = cls.registration_manifest()["harness_id"]
    assessment = cls().assess(_ctx(harness), _request())
    assert assessment.verdict == "supported", assessment.reason


@pytest.mark.parametrize("cls", ADAPTERS)
def test_unrecognized_version_is_unknown_never_guessed(cls):
    harness = cls.registration_manifest()["harness_id"]
    assessment = cls().assess(_ctx(harness, version="not-a-version"), _request())
    assert assessment.verdict == "unknown"
    assert "version" in assessment.reason.lower()


@pytest.mark.parametrize("cls", ADAPTERS)
def test_out_of_range_version_is_unsupported(cls):
    harness = cls.registration_manifest()["harness_id"]
    assessment = cls().assess(_ctx(harness, version="0.1.0"), _request())
    assert assessment.verdict == "unsupported"


# -- brand dialect discipline (golden, provenance: harness family native.py) ---

def test_pi_only_pins_openai_chat():
    with pytest.raises(pi_facts.ProtocolUnsupported):
        pi_facts.translate_protocol("pi", "anthropic-messages")
    field, dialect = pi_facts.translate_protocol("pi", "openai-chat")
    assert (field, dialect) == ("api", "openai-completions")


def test_codex_never_writes_a_project_scope_provider():
    adapter = CodexAdapter()
    refusal = adapter.compile(
        _ctx("codex", scope="project"), {}, _request(protocol="openai-responses"))
    assert isinstance(refusal, Refusal)
    assert refusal.code == "target-conflict"
    assert ".codex/config.toml" in refusal.message


def test_codex_cross_provider_declares_restart_resume_with_same_thread():
    adapter = CodexAdapter()
    result = adapter.compile(
        _ctx("codex"), {},
        _request(protocol="openai-responses", model="gpt-x",
                 brand={"before_provider": "other"}))
    assert result.reconfiguration == "restart-resume"
    assert result.resume_expectation == {"native_session_id": "nat-7"}
    fields = {(i.field_path, i.typed_value) for i in result.intents
              if isinstance(i, CompileIntent)}
    assert (("model_provider",), "acme") in fields
    assert (("model",), "gpt-x") in fields


def test_codex_model_only_change_is_session_local():
    adapter = CodexAdapter()
    result = adapter.compile(
        _ctx("codex"), {},
        _request(protocol="openai-responses", model="gpt-y",
                 brand={"before_provider": "acme"}))
    assert result.reconfiguration == "session-local"


def test_codex_provider_section_is_byte_stable_toml():
    section = codex_facts.render_codex_provider_section(
        provider="acme", base_url="https://api.acme.test/v1",
        protocol="openai-responses")
    assert section == (
        "[model_providers.acme]\n"
        "name = \"acme\"\n"
        "base_url = \"https://api.acme.test/v1\"\n"
        "wire_api = \"responses\"\n"
        "env_key = \"CODEX_API_KEY\"\n"
    )


def test_pi_rpc_success_is_not_evidence_of_effect():
    adapter = PiAdapter()
    observed = {"projected": {"model": "m1"}, "rpc_ack": True,
                "desired_model": "m1",
                "readback": {"model": "m0"}, "native_session_id": "nat-7"}
    verdict = adapter.verify(_ctx("pi"), observed)
    assert verdict.verdict == "mismatch"


def test_pi_session_local_needs_provider_already_in_instance():
    adapter = PiAdapter()
    result = adapter.compile(
        _ctx("pi"), {}, _request(protocol="openai-chat", brand={
            "provider_in_instance": True, "credential_changed": False}))
    assert result.reconfiguration == "session-local"
    # a provider NOT yet present in the instance is a reload/restart path
    result = adapter.compile(
        _ctx("pi"), {}, _request(protocol="openai-chat", brand={
            "provider_in_instance": False, "credential_changed": False}))
    assert result.reconfiguration == "restart-resume"
    # an auth change is never session-local either
    result = adapter.compile(
        _ctx("pi"), {}, _request(protocol="openai-chat", brand={
            "provider_in_instance": True, "credential_changed": True}))
    assert result.reconfiguration == "restart-resume"


def test_claude_model_and_endpoint_are_two_different_things():
    adapter = ClaudeAdapter()
    result = adapter.compile(
        _ctx("claude-code"), {}, _request(
            protocol="anthropic-messages", model="claude-y"))
    intents = {i.field_path: i.typed_value for i in result.intents
               if isinstance(i, CompileIntent)}
    assert intents.get(("session", "model")) == "claude-y"
    assert not any(path == ("env", "ANTHROPIC_BASE_URL") for path in intents)
    assert result.reconfiguration == "session-local"

    # changing the endpoint IS a provider change -> controlled restart-resume
    result = adapter.compile(
        _ctx("claude-code"), {},
        _request(protocol="anthropic-messages", brand={"endpoint_changed": True}))
    assert result.reconfiguration == "restart-resume"


def test_claude_session_new_instead_of_resume_is_mismatch():
    adapter = ClaudeAdapter()
    verdict = adapter.verify(_ctx("claude-code"), {
        "projected": {"model": "m1"},
        "desired_model": "m1",
        "readback": {"model": "m1"},
        "native_session_id": "nat-OTHER",
    })
    assert verdict.verdict == "mismatch"
    assert "resume" in (verdict.reason or "").lower()


# -- verify layering ------------------------------------------------------------

@pytest.mark.parametrize("cls", ADAPTERS)
def test_projected_digest_alone_is_never_applied(cls):
    harness = cls.registration_manifest()["harness_id"]
    observed = {"projected": {"model": "m1"}, "desired_model": "m1"}  # no readback
    verdict = cls().verify(_ctx(harness), observed)
    assert verdict.verdict == "unknown"


@pytest.mark.parametrize("cls", ADAPTERS)
def test_readback_match_with_same_session_is_match(cls):
    harness = cls.registration_manifest()["harness_id"]
    verdict = cls().verify(_ctx(harness), {
        "projected": {"model": "m1"},
        "desired_model": "m1",
        "readback": {"model": "m1"},
        "native_session_id": "nat-7",
    })
    assert verdict.verdict == "match"


# -- secrets and intent typing --------------------------------------------------

BINDING_BRANDS = {
    "PiAdapter": {"provider_in_instance": False},
    "CodexAdapter": {"before_provider": "other"},
    "ClaudeAdapter": {"endpoint_changed": True},
}


@pytest.mark.parametrize("cls", ADAPTERS)
def test_compile_output_never_carries_secret_content(cls):
    harness = cls.registration_manifest()["harness_id"]
    result = cls().compile(_ctx(harness), {},
                           _request(brand=BINDING_BRANDS[cls.__name__]))
    assert not isinstance(result, Refusal), result
    blob = repr(dataclasses.asdict(result))
    assert "sk-live-secret" not in blob
    assert "ref://cred-1" in blob  # the reference travels; nothing else does


@pytest.mark.parametrize("cls", ADAPTERS)
def test_bind_secret_only_travels_as_reference(cls):
    harness = cls.registration_manifest()["harness_id"]
    result = cls().compile(_ctx(harness), {}, _request(brand=BINDING_BRANDS[cls.__name__]))
    assert not isinstance(result, Refusal), result
    assert any(hasattr(intent, "secret_ref") and intent.secret_ref is not None for intent in result.intents)
    for intent in result.intents:
        if hasattr(intent, "secret_ref") and intent.secret_ref is not None:
            assert intent.secret_ref.startswith("ref://")


# -- S-08② golden consistency (PB-7): retain the pinned comparison between
# brand-owned common rendering and the established native-materialization golden.

def test_codex_provider_section_matches_the_harness_golden_byte_for_byte():
    from ordessa_server_product.native_materialization import (
        render_codex_provider_section as harness_render,
    )

    for protocol in ("openai-responses", "openai-chat"):
        ours = codex_facts.render_codex_provider_section(
            provider="acme", base_url="https://api.acme.test/v1", protocol=protocol)
        theirs = harness_render(
            provider="acme", base_url="https://api.acme.test/v1", protocol=protocol)
        assert ours == theirs


def test_pi_provider_object_matches_the_harness_golden():
    from ordessa_server_product.native_materialization import render_pi_provider

    theirs = render_pi_provider(provider="acme", base_url="https://api.acme.test/v1",
                                protocol="openai-chat")
    field, dialect = pi_facts.translate_protocol("pi", "openai-chat")
    ours = {"baseUrl": "https://api.acme.test/v1", field: dialect}
    assert ours == {key: theirs[key] for key in ours}


def test_claude_env_matches_the_harness_golden():
    from ordessa_server_product.native_materialization import render_claude_env

    theirs = render_claude_env(base_url="https://api.acme.test/v1",
                               protocol="anthropic-messages")
    assert theirs == {"ANTHROPIC_BASE_URL": "https://api.acme.test/v1"}


def test_pinned_dialects_equal_the_harness_family_facts():
    """Registration path: every (brand, protocol) pair the registered
    descriptors can accept carries the SAME first-hand native field the
    harness family module pins — the adapters' DIALECTS are a transcription,
    never an independent guess."""
    from ordessa_server_product.native_materialization import (
        _FAMILY_DIALECTS as harness_dialects,
    )

    for brand in common_brands():
        pairs = c2_module(brand).declared_dialects()
        for protocol, dialect in pairs.items():
            assert harness_dialects[brand][protocol] == dialect, (brand, protocol)


def test_brand_descriptor_native_targets_match_the_harness_pins():
    from ordessa_server_product.native_materialization import _NATIVE_TARGET

    for brand in common_brands():
        descriptor = descriptor_for(brand)
        harness_target = _NATIVE_TARGET[brand]
        assert descriptor.harness_id == brand
        # the descriptor's file claim is the same native target the harness
        # family writes (the E2 runtime resources carry the identical name)
        file_claims = [c for c in descriptor.claims if c.target_kind == "file"]
        assert file_claims
        assert next(c.target_id for c in descriptor.claims if c.target_kind == "file").split(".", 1)[1] == harness_target


# -- purity boundary ------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"expanduser|environ\[|getenv|socket|urllib|http\.client|requests|"
    r"subprocess|Popen|os\.system|path\.write|open\(.*'w'|shutil",
)

def test_brand_c2_factories_are_public_and_stay_pure():
    import ast

    # types supplies an immutable projection; no IO or host/provider dependency.
    allowed_roots = {"ordessa_agents", "tomllib", "types"}
    for brand in common_brands():
        module = c2_module(brand)
        source = Path(module.__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in allowed_roots, (brand, name)
        match = _FORBIDDEN.search(source)
        assert match is None, f"{brand} C2 factory references {match.group(0)!r}"
        assert adapter_for(brand).descriptor == descriptor_for(brand)



def test_neutral_ranges_use_explicit_provider_facts_and_refuse_overlap():
    from ordessa_agents.harness.configuration.validation.version_ranges import (
        version_in_range, parse_range, ranges_provably_disjoint,
        RegistrationConflict, check_registration_conflicts,
    )
    bounds = c2_module('codex').supported_native_versions()
    assert version_in_range(bounds[0], bounds) == 'supported'
    assert version_in_range(bounds[1], bounds) == 'unsupported'
    assert version_in_range(None, bounds) == 'unknown'
    assert parse_range('>=1.0 <2.0') == ((1, 0), (2, 0))
    assert ranges_provably_disjoint('>=1.0 <2.0', '>=2.0 <3.0')
    assert not ranges_provably_disjoint('unknown', '>=2.0 <3.0')
    manifest = {'facet_id': 'facet', 'harness_id': 'selected',
                'supported_native_versions': '>=1.0 <2.0', 'entries': ['acp']}
    with pytest.raises(RegistrationConflict):
        check_registration_conflicts([manifest, dict(manifest)])
