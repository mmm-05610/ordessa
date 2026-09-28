"""Z3 T02 conformance gates for the brand configuration adapters (E1).

Authored in this line against ``docs/design/harness-v2/contracts.md`` C2/C3 and
``docs/design/model-provider/harness-adapters.md``. Every gate listed in the
dispatch (``specs/011-z3-model-provider/dispatch/t02-adapters.md``) is driven
here; all were red before the adapter modules existed.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from ordessa_harness_api import ConfigurationAdapterDescriptor, VersionRange
from ordessa_harness.contributions import HarnessContributionError, HarnessContributionRegistry
from server_plugin_api import Contribution, ContributionBatch, stage_contributions

from ordessa_model_provider_adapters import bridge, common
from ordessa_model_provider_adapters.claude import ClaudeAdapter
from ordessa_model_provider_adapters.codex import CodexAdapter
from ordessa_model_provider_adapters.pi import PiAdapter
from ordessa_model_provider_adapters.types import (
    AdapterContext, ChoiceRequest, CompileIntent, Refusal, TargetHandle,
)

ADAPTERS = (PiAdapter, CodexAdapter, ClaudeAdapter)

#: 014 PB-2 declaration surface facts
CONFIGURATION_POINT = "harness.configuration-adapters"
OWNER = "ordessa.model-provider.adapters"
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
        brand_fields=dict(brand or {}), provider_name="acme",
    )


# -- registration manifests + conflict discipline -----------------------------
# 014 PB-2: the manifests ARE real harness-api ``ConfigurationAdapterDescriptor``s
# now; the overlap gates below drive the real C2 registry
# (``ordessa_harness.contributions``) instead of the 011-era local stand-in, so
# the refusal semantics are the production ones (adapter_id / range / facet /
# claim conflicts at stage time, never order-resolved).

def test_manifests_are_real_harness_api_descriptors_with_frozen_facet():
    expected = {"pi": "assets.model-provider.pi", "codex": "assets.model-provider.codex",
                "claude-code": "assets.model-provider.claude"}
    for brand in common_brands():
        descriptor = bridge.descriptor_for(brand)
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
        assert bridge.descriptor_for(brand).native_versions.contains(padded) is True
        low = common.parse_version(common.SUPPORTED_VERSION_RANGES[brand][0])
        low_padded = low + (0,) * (3 - len(low))
        assert bridge.descriptor_for(brand).native_versions.contains(low_padded) is True


def _batch():
    return ContributionBatch(tuple(
        Contribution(CONFIGURATION_POINT, "v1", bridge.BridgeConfigurationAdapter(brand),
                     required=True)
        for brand in common_brands()
    ), open_points=frozenset({CONFIGURATION_POINT}))


def test_three_brands_register_into_the_real_c2_registry():
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler, OWNER, _batch())
    staged.commit()
    assert sorted(d.adapter_id for d in registry.configuration_descriptors()) == [
        "assets.model-provider.claude", "assets.model-provider.codex",
        "assets.model-provider.pi"]


def test_identical_registration_overlap_is_refused_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _batch()).commit()
    second = ContributionBatch((
        Contribution(CONFIGURATION_POINT, "v1", bridge.BridgeConfigurationAdapter("pi")),
    ))
    with pytest.raises(HarnessContributionError, match="adapter_id already registered"):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_same_harness_overlapping_native_range_refused_by_real_registry():
    """MP-11 production shape: a second client may claim the same facet only
    outside the first owner's native version range; an overlapping range with a
    shared entry is a stage-time refusal."""
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _batch()).commit()

    overlap = bridge.descriptor_for("pi")
    object.__setattr__(overlap, "adapter_id", "assets.model-provider.pi-alt")
    intruder = bridge.BridgeConfigurationAdapter("pi")
    intruder.descriptor = overlap
    second = ContributionBatch((Contribution(CONFIGURATION_POINT, "v1", intruder),))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_disjoint_native_range_accepted_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _batch()).commit()

    next_range = bridge.descriptor_for("pi")
    object.__setattr__(next_range, "adapter_id", "assets.model-provider.pi-next")
    object.__setattr__(next_range, "native_versions", VersionRange((0, 6, 0)))
    successor = bridge.BridgeConfigurationAdapter("pi")
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
    with pytest.raises(common.ProtocolUnsupported):
        common.translate_protocol("pi", "anthropic-messages")
    field, dialect = common.translate_protocol("pi", "openai-chat")
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
    section = common.render_codex_provider_section(
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
    result = cls().compile(_ctx(harness), {}, _request())
    if isinstance(result, Refusal):
        pytest.skip("compile refused; no intents to scan")
    for intent in result.intents:
        if hasattr(intent, "secret_ref") and intent.secret_ref is not None:
            assert intent.secret_ref.startswith("ref://")


# -- purity boundary ------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"expanduser|environ\[|getenv|socket|urllib|http\.client|requests|"
    r"subprocess|Popen|os\.system|path\.write|open\(.*'w'|shutil",
)

#: 014 PB-2: the bridge/plugin modules may import the two public contract
#: packages (direction adapters→harness-api) but stay pure otherwise; the
#: brand modules must not even name them.
_BRIDGE_ALLOWED_ROOTS = {"__future__", "json", "tomllib", "typing", "hashlib",
                         "ordessa_harness_api", "server_plugin_api",
                         "ordessa_model_provider_adapters"}


def _module_source(cls):
    import importlib.util

    origin = importlib.util.find_spec(cls.__module__).origin
    return Path(origin).read_text()


@pytest.mark.parametrize("cls", ADAPTERS)
def test_brand_modules_never_touch_home_network_or_spawn(cls):
    match = _FORBIDDEN.search(_module_source(cls))
    assert match is None, f"{cls.__module__} references {match.group(0)!r}"


@pytest.mark.parametrize("cls", ADAPTERS)
def test_brand_modules_do_not_import_the_bridge_or_harness(cls):
    for module_line in _module_source(cls).splitlines():
        stripped = module_line.strip()
        if stripped.startswith(("import ", "from ")):
            root = stripped.split()[1].split(".")[0]
            assert root not in {"ordessa_harness_api", "ordessa_harness",
                                "server_plugin_api"}, module_line


def test_bridge_and_plugin_import_only_contract_packages_and_stay_pure():
    import ast

    for module_name in ("bridge", "plugin"):
        spec = importlib_spec("ordessa_model_provider_adapters", module_name)
        tree = ast.parse(spec)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root in _BRIDGE_ALLOWED_ROOTS, f"{module_name}: imports {name}"
        match = _FORBIDDEN.search(spec)
        assert match is None, f"{module_name} references {match.group(0)!r}"


def importlib_spec(package: str, module: str) -> str:
    import importlib.util

    origin = importlib.util.find_spec(f"{package}.{module}").origin
    return Path(origin).read_text()
