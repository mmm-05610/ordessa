"""The real ConfigurationAdapter surface per brand (T013 需求1/需求5).

assess/compile/verify run against the REAL API DTOs (AdapterContext,
Assessment, IntentSet, SetField/BindSecret, Verification union), admitted
through the REAL harness contribution registry (contributions.py — facet/
entry/version/claim overlap conflict checks). Honesty line unchanged:
``proven_routes`` is empty, so no brand×destination cell assesses
``supported``; compile only ever emits intents the injected context
authorises; verify can only ever reach ``Match`` through an attesting
observer, never through content bytes.
"""
import pytest
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, BindSecret, Installation,
    IntentSet, Match, Mismatch, SetField, TargetDescriptor, TargetHandle,
    VerificationUnknown,
)
from wiring_helpers import (
    CANARY, api_context, claude_planned, codex_planned, environment_target,
    file_target,
)

from adapters import claude as claude_mod, codex as codex_mod
from backend import native_binding as nb
from backend.native_intents import (
    DESTINATION_INSTANCE_CONFIG, DESTINATION_SESSION_OVERRIDE,
)

BRANDS = [(claude_mod, claude_mod.CLAUDE), (codex_mod, codex_mod.CODEX)]


@pytest.fixture
def claude_adapter():
    return claude_mod.configuration_adapter()


@pytest.fixture
def codex_adapter():
    return codex_mod.configuration_adapter()


# -- registration as real adapters ------------------------------------------------


def test_adapters_are_real_descriptors_admitted_by_the_harness_registry():
    from ordessa_harness.contributions import (
        CONFIGURATION_POINT, POINT_API_VERSION, HarnessContributionRegistry,
    )
    from server_plugin_api import Contribution
    from wiring_helpers import AdapterContributionPlugin
    from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost

    host = ServerPluginHost(methods=MethodRegistry(), data_root="/tmp/unused")
    registry = HarnessContributionRegistry()
    host.register_contribution_point(CONFIGURATION_POINT, POINT_API_VERSION,
                                     handler=registry.configuration_handler,
                                     exclusive=False)
    a1 = codex_mod.configuration_adapter()
    a2 = claude_mod.configuration_adapter()
    host.activate(AdapterContributionPlugin("ordessa.asset.mcp.codex", a1))
    host.activate(AdapterContributionPlugin("ordessa.asset.mcp.claude", a2))
    descriptors = registry.configuration_descriptors()
    assert {d.facet_id for d in descriptors} == {nb.FACET_ID}
    assert {d.adapter_id for d in descriptors} == {
        "assets.mcp.codex.native", "assets.mcp.claude-code.native"}
    assert all(d.api_version == "v1" for d in descriptors)
    # same facet + same harness + overlapping ranges + shared entry = conflict
    with pytest.raises(Exception) as info:
        host.activate(AdapterContributionPlugin(
            "ordessa.asset.mcp.dup", codex_mod.configuration_adapter()))
    assert "already" in str(info.value).lower() or "overlap" in str(info.value).lower()


# -- assess: honesty preserved ----------------------------------------------------


@pytest.mark.parametrize("kind", [DESTINATION_INSTANCE_CONFIG,
                                  DESTINATION_SESSION_OVERRIDE])
@pytest.mark.parametrize("module,brand", BRANDS)
def test_assess_never_reports_supported_without_runtime_evidence(module, brand, kind):
    adapter = module.configuration_adapter()
    scope = "instance" if kind == DESTINATION_INSTANCE_CONFIG else "session"
    context = api_context(brand, scope=scope)
    verdict = adapter.assess(context, None)
    assert isinstance(verdict, Assessment)
    assert verdict.status != "supported", (brand.harness_type, kind)
    assert verdict.reason  # unknown/unsupported both carry the reason


def test_assess_structural_shapes(claude_adapter, codex_adapter):
    codex_ctx = api_context(codex_mod.CODEX, scope="session")
    payload = {**nb.facet_payload_of(codex_planned()),
               "destinationKind": DESTINATION_INSTANCE_CONFIG}
    verdict = codex_adapter.assess(codex_ctx, payload)
    assert verdict.status == "unsupported"  # R-Q4-3: blocked route
    assert "codex-instance-config-slot-conflict" in verdict.reason
    # a structurally possible route with no runtime evidence stays unknown
    ok = codex_adapter.assess(codex_ctx, nb.facet_payload_of(codex_planned()))
    assert ok.status == "unknown"
    assert "codex-session-override-runtime-unproven" in ok.reason
    # cross-brand payload: the claude adapter refuses codex words
    wrong = claude_adapter.assess(api_context(claude_mod.CLAUDE), payload)
    assert wrong.status == "unsupported"
    assert "harness-id-mismatch" in wrong.reason
    # no brand target in the context (wrong codec offered) -> unsupported
    ctx = AdapterContext((), Installation("claude-code", (1, 0, 0), (1, 0, 0), "e"),
                         "acp", "instance", "e")
    verdict = claude_adapter.assess(ctx, None)
    assert verdict.status == "unsupported"
    assert "no-brand-target" in verdict.reason


# -- compile: real IntentSet, real refusals ---------------------------------------


def test_claude_instance_config_compile_emits_real_setfields(claude_adapter):
    context = api_context(claude_mod.CLAUDE, scope="instance")
    planned = claude_planned(env=(("FOO", _literal("bar")),))
    outcome = claude_adapter.compile(context, {}, nb.facet_payload_of(planned))
    assert isinstance(outcome, IntentSet)
    (intent,) = outcome.intents
    assert isinstance(intent, SetField)
    assert intent.field_path.segments == ("mcpServers", "demo")
    assert intent.target == context.targets[0].handle
    assert intent.source.facet_id == nb.FACET_ID
    assert intent.typed_value == {"command": "/bin/true", "args": [],
                                  "env": {"FOO": "bar"}}
    # the written file value never contains plaintext-substitute material
    assert "secretRef" not in str(intent.typed_value)


def _literal(value):
    from backend.definition import Literal
    return Literal(value)


def test_codex_session_override_compile_targets_session_scope(codex_adapter):
    context = api_context(codex_mod.CODEX, scope="session")
    planned = codex_planned(session=True)
    outcome = codex_adapter.compile(context, {}, nb.facet_payload_of(planned))
    assert isinstance(outcome, IntentSet)
    (intent,) = outcome.intents
    assert intent.target.handle_id == nb.session_target_id("codex")
    assert intent.field_path.segments == ("mcp_servers", "demo")


def test_codex_instance_config_route_refused_typed(codex_adapter):
    context = api_context(codex_mod.CODEX, scope="instance")
    # the domain compile already blocks the route; shape the payload by
    # hand to prove the C2 door refuses it too (defense in depth)
    payload = dict(nb.facet_payload_of(codex_planned()),
                   destinationKind=DESTINATION_INSTANCE_CONFIG)
    outcome = codex_adapter.compile(context, {}, payload)
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "capability-unsupported"
    assert "codex-instance-config-slot-conflict" in outcome.reason


def test_compile_refusals_matrix(claude_adapter):
    context = api_context(claude_mod.CLAUDE)
    planned = claude_planned()
    payload = nb.facet_payload_of(planned)
    # cross-brand payload (a codex-shaped plan at the claude door)
    codex_payload = nb.facet_payload_of(codex_planned())
    outcome = claude_adapter.compile(context, {}, codex_payload)
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "target-conflict"
    # undeclared field injection
    outcome = claude_adapter.compile(context, {}, dict(payload, targetPath="/x"))
    assert isinstance(outcome, AdapterRefusal) and outcome.code.value == "invalid-fragment"
    # managed-definition leak: a native entry sharing a managed endpoint
    leaked = dict(payload, entries=[dict(payload["entries"][0])])
    leaked["excludedManaged"] = [{
        "definitionId": "m1", "revision": "1",
        "endpointFingerprint": payload["entries"][0]["endpointFingerprint"]}]
    outcome = claude_adapter.compile(context, {}, leaked)
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "target-conflict"
    # field not authorised by the target descriptor
    narrow_handle = TargetHandle(nb.instance_target_id("claude-code"), 7)
    narrow = AdapterContext(
        (TargetDescriptor(narrow_handle, "file", "json", "instance",
                          (("other",),)),),
        context.installation, "acp", "instance", "ev:capability")
    outcome = claude_adapter.compile(narrow, {}, payload)
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "target-conflict"
    # reset compilation (no owned-name enumeration in C2) -> typed refusal
    outcome = claude_adapter.compile(context, {}, None)
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "capability-unsupported"


def test_secretref_slot_requires_environment_target_or_refuses(claude_adapter):
    planned = claude_planned(secrets=(("TOKEN", "cred-1"),))
    payload = nb.facet_payload_of(planned)
    # without an environment target: typed refusal — never a plaintext write
    outcome = claude_adapter.compile(api_context(claude_mod.CLAUDE), {}, payload)
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "capability-unsupported"
    assert "plaintext" in outcome.reason
    assert CANARY not in outcome.reason
    # with an authorised environment target: real BindSecret, ref-only
    env = environment_target("claude-code", "instance", ("demo.TOKEN",))
    context = api_context(claude_mod.CLAUDE, extra_targets=(env,))
    outcome = claude_adapter.compile(context, {}, payload)
    assert isinstance(outcome, IntentSet)
    binds = [i for i in outcome.intents if isinstance(i, BindSecret)]
    assert [b.slot for b in binds] == ["demo.TOKEN"]
    assert binds[0].secret_ref == "cred-1"  # ref only — no revision, no value
    fields = [i for i in outcome.intents if isinstance(i, SetField)]
    # the secret slot left the file value; only the literal stays
    assert fields[0].typed_value["env"] == {"FOO": "bar"}
    assert "TOKEN" not in str(fields[0].typed_value)


def test_secret_named_literal_refused_before_setfield(claude_adapter):
    from backend.definition import Literal
    planned = claude_planned(env=(("TOKEN", Literal(CANARY)),))
    outcome = claude_adapter.compile(api_context(claude_mod.CLAUDE), {},
                                     nb.facet_payload_of(planned))
    assert isinstance(outcome, AdapterRefusal)
    assert outcome.code.value == "invalid-fragment"
    assert CANARY not in outcome.reason


# -- verify: projected/loaded honesty on the real union ---------------------------


def _bound_adapter(payload_planned=None):
    adapter = claude_mod.configuration_adapter()
    context = api_context(claude_mod.CLAUDE)
    planned = payload_planned or claude_planned()
    outcome = adapter.compile(context, {}, nb.facet_payload_of(planned))
    assert isinstance(outcome, IntentSet)
    return adapter, context, planned


def test_observer_attested_load_is_the_only_match_path():
    from backend import native_binding as nb2
    adapter, context, planned = _bound_adapter()
    observed = nb2.observation_payload_of(
        _observe("runtime-loaded"), evidence_ref="ev:observed-load-1")
    verdict = adapter.verify(context, observed)
    assert isinstance(verdict, Match)
    assert verdict.evidence_ref == "ev:observed-load-1"


def _observe(load_state, digest=None):
    from backend.native_intents import NativeObservation, ObservedServer
    return NativeObservation(observer="fake-harness-c3", session_ref="session-a",
                             runtime_generation=3,
                             servers=(ObservedServer(server_name="demo",
                                                     transport="stdio",
                                                     load_state=load_state,
                                                     catalog_digest=digest),))


def test_config_bytes_match_never_reaches_match():
    adapter, context, _ = _bound_adapter()
    observed = nb.observation_payload_of(_observe("config-bytes-match"),
                                         evidence_ref="ev:bytes")
    verdict = adapter.verify(context, observed)
    assert isinstance(verdict, VerificationUnknown)
    assert "projected" in verdict.reason


def test_unattested_runtime_load_stays_unknown():
    adapter, context, _ = _bound_adapter()
    observed = nb.observation_payload_of(_observe("runtime-loaded"), None)
    verdict = adapter.verify(context, observed)
    assert isinstance(verdict, VerificationUnknown)
    assert "attestation" in verdict.reason


def test_catalog_changed_and_identity_mismatch_are_mismatch():
    adapter, context, planned = _bound_adapter(claude_planned(catalog={"d1": "sha256:expected"}))
    observed = nb.observation_payload_of(_observe("runtime-loaded", "sha256-other"),
                                         evidence_ref="ev:1")
    verdict = adapter.verify(context, observed)
    assert isinstance(verdict, Mismatch)
    assert "catalog-changed" in verdict.reason
    # instance identity mismatch (generation moved) is a contradiction too
    stale = nb.observation_payload_of(_observe("runtime-loaded"), evidence_ref="ev:1")
    stale = dict(stale, runtimeGeneration=99)
    verdict = adapter.verify(context, stale)
    assert isinstance(verdict, Mismatch)
    assert "instance-identity-mismatch" in verdict.reason


def test_mismatch_cannot_be_dressed_as_loaded_by_garbage_input():
    adapter, context, _ = _bound_adapter()
    # observed DTO is closed: an undeclared "fact" key is refused before the
    # fact logic can run — and an unrecognized load state stays unknown
    garbage = dict(nb.observation_payload_of(_observe("runtime-loaded"),
                                             evidence_ref="ev:1"), confirmed=True)
    verdict = adapter.verify(context, garbage)
    assert isinstance(verdict, VerificationUnknown)
    assert "observation-shape-invalid" in verdict.reason
    weird = nb.observation_payload_of(_observe("fully-loaded-and-definitely"),
                                      evidence_ref="ev:1")
    verdict = adapter.verify(context, weird)
    assert isinstance(verdict, VerificationUnknown)


def test_content_readback_path_projects_never_confirms():
    adapter, context, planned = _bound_adapter()
    payload = nb.facet_payload_of(planned)
    content = {"mcpServers": {"demo": {"command": "/bin/true", "args": [],
                                       "env": {"FOO": "bar"}}}}
    verdict = adapter.verify(context, content)
    assert isinstance(verdict, VerificationUnknown)
    assert "projected-only" in verdict.reason
    missing = {"mcpServers": {}}
    verdict = adapter.verify(context, missing)
    assert isinstance(verdict, Mismatch)
    assert "planned-server-absent" in verdict.reason


def test_verify_bound_to_context_cross_instance_spoof_refused():
    adapter, context, _ = _bound_adapter()
    spoofed = api_context(claude_mod.CLAUDE, generation=8)  # other generation
    observed = nb.observation_payload_of(_observe("runtime-loaded"),
                                         evidence_ref="ev:1")
    verdict = adapter.verify(spoofed, observed)
    assert isinstance(verdict, VerificationUnknown)
    assert "no-compiled-plan-bound" in verdict.reason
    # another brand's context likewise
    other = api_context(codex_mod.CODEX, scope="session")
    assert isinstance(adapter.verify(other, observed), VerificationUnknown)
