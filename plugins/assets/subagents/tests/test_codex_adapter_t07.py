"""T07 — Codex adapter triad at pin codex-acp 1.1.14 / CLI 0.147.0 (G12, G13).

The capability-matrix finding — the pinned adapter's `.agents` root is the
SKILLS root and it has zero subagent-discovery hits — is encoded here as
an `unsupported` real `Assessment` (with per-cell detail kept apart for the
un-installed CLI), a whole-collection `NATIVE_DISCOVERY_UNCONTROLLED`
compile refusal, and a `verify` that cannot reach `loaded` at all. The
target is now the contract's `AdapterContext`/`TargetHandle`; the empty
`FieldClaim` tuple on the descriptor is the contract-side spelling of the
old "slot exists but nothing is claimable" fact. Negative columns
throughout.
"""
from __future__ import annotations

import tomllib

import pytest
from ordessa_harness_api import (
    AdapterContext, Installation, IntentSource, Mismatch, TargetDescriptor,
    TargetHandle, VerificationUnknown,
)

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.adapters import base, codex, intents, tomlwriter

CODEX_HANDLE = TargetHandle("assets-native-subagents-codex-generation", 5)
CODEX_CONTEXT = AdapterContext(
    (TargetDescriptor(CODEX_HANDLE, "directory", "content", "instance",
                     (("agents",),)),),
    Installation("codex", codex.CODEX_CLI_SEMVER, codex.CODEX_ADAPTER_SEMVER,
                 "fixture:install"),
    "acp", "instance", "fixture:capability",
)
SOURCE = IntentSource(intents.FACET_ID, "def-codex", "v1")
SHA = "sha256:" + "ab" * 32
ADAPTER = codex.CodexAdapter()


def make_item(slug: str = "planner", *, definition_id: str = "d1",
              description: str = "plans work",
              body: str = "You plan the work step by step.",
              **revision_kwargs) -> intents.ManagedItem:
    source = revision_kwargs.pop("source", dto.SourceApproval(
        "user-upload", "file:seed.md", SHA, "principal-a", "2026-09-28T00:00:00Z"))
    revision = dto.DefinitionRevision(definition_id, 1, SHA, body, source=source,
                                      **revision_kwargs)
    definition = dto.AgentDefinition("server-a", definition_id, slug,
                                     "Planner", description, "public", "owner-a")
    return intents.ManagedItem(definition, revision)


# -- assess: proven-absent vs unmeasured are named apart -------------------------


def test_assess_discovery_unsupported_with_adapter_evidence():
    assessment = ADAPTER.assess(CODEX_CONTEXT)
    assert assessment.status == "unsupported"      # the REAL Assessment DTO
    assert assessment.reason                       # contract requires one
    assert "1.1.14" in (assessment.evidence_ref or "")
    detail = ADAPTER.assess_detail(CODEX_CONTEXT)
    cell = detail.verdict("adapter-native-discovery")
    assert cell.state is base.AssessmentState.UNSUPPORTED
    assert "skills" in cell.reason          # the .agents-is-skills finding
    assert cell.evidence                    # a verdict never rides on nothing


def test_assess_cli_honouring_stays_unknown_not_flattened():
    detail = ADAPTER.assess_detail(CODEX_CONTEXT)
    cli_cell = detail.verdict("cli-honours-agents-toml")
    assert cli_cell.state is base.AssessmentState.UNKNOWN
    assert "0.147.0" in cli_cell.reason or "CLI" in cli_cell.reason
    # the unsupported discovery verdict must not masquerade as a CLI verdict:
    assert "discovery" in detail.verdict("adapter-native-discovery").reason
    assert detail.verdict("acp-path-invocation").state is base.AssessmentState.UNSUPPORTED


def test_assess_refuses_foreign_harness():
    foreign = AdapterContext(
        CODEX_CONTEXT.targets,
        Installation("claude", codex.CODEX_CLI_SEMVER, codex.CODEX_ADAPTER_SEMVER,
                     "fixture:install"),
        "acp", "instance", "fixture:capability")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.assess(foreign)
    assert excinfo.value.code == errors.TARGET_CONFLICT


def test_assess_refuses_out_of_pin_adapter_version():
    drifted = AdapterContext(
        CODEX_CONTEXT.targets,
        Installation("codex", codex.CODEX_CLI_SEMVER, (2, 0, 0), "fixture:install"),
        "acp", "instance", "fixture:capability")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.assess(drifted)
    assert excinfo.value.code == errors.NATIVE_VERSION_UNKNOWN


# -- descriptor honesty: no claims while discovery is proven absent ---------------


def test_codex_descriptor_claims_nothing():
    assert ADAPTER.descriptor is not None
    assert ADAPTER.descriptor.claims == ()
    assert ADAPTER.descriptor.native_versions.contains(codex.CODEX_CLI_SEMVER) is True
    assert ADAPTER.descriptor.native_versions.contains((0, 99, 0)) is False


# -- compile: whole-collection refusal before any intent --------------------------


def test_compile_refuses_entire_collection_as_uncontrolled():
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CODEX_CONTEXT, [make_item()], SOURCE)
    assert excinfo.value.code == errors.NATIVE_DISCOVERY_UNCONTROLLED
    # refusal — not an (empty) IntentSet — so nothing can reach a target:
    assert excinfo.value.detail


def test_compile_refuses_even_with_a_host_granted_source():
    # the host granting a source does NOT unlock Codex: the refusal is the
    # measured absence, not a missing credential (anti-vacuity for the next
    # line: Claude with the same source DOES compile — see t06).
    with pytest.raises(errors.DomainError):
        ADAPTER.compile(CODEX_CONTEXT, [make_item()], SOURCE,
                        native_names=frozenset())


def test_compile_sandbox_mode_refused_as_grant():
    item = make_item(isolation={"sandbox_mode": "danger-full-access"})
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CODEX_CONTEXT, [item], SOURCE)
    assert excinfo.value.code == errors.PERMISSION_EXCEEDS_CEILING
    assert "sandbox_mode" in excinfo.value.detail


def test_compile_refuses_fields_without_entry():
    cases = [
        (make_item(declared_model_ref=dto.ModelRef("m-owner")), errors.REFERENCE_UNRESOLVED),
        (make_item(tool_refs=(dto.ToolRef("bash"),)), errors.REFERENCE_UNRESOLVED),
        (make_item(mcp_refs=(dto.McpRef("s"),)), errors.PERMISSION_EXCEEDS_CEILING),
        (make_item(requested_permission="allow-all"), errors.PERMISSION_EXCEEDS_CEILING),
        (make_item(retained_native_fields={"developer_instructions_x": 1}),
         errors.DEFINITION_INVALID),
        (make_item(slug="Bad Name"), errors.DEFINITION_INVALID),
    ]
    for item, code in cases:
        with pytest.raises(errors.DomainError) as excinfo:
            ADAPTER.compile(CODEX_CONTEXT, [item], SOURCE)
        assert excinfo.value.code == code, item.definition.definition_id


def test_compile_wrong_entry_refused():
    bad_entry = AdapterContext(
        CODEX_CONTEXT.targets, CODEX_CONTEXT.installation, "inproc", "instance",
        "fixture:capability")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(bad_entry, [make_item()], SOURCE)
    assert excinfo.value.code == errors.TARGET_CONFLICT


# -- the pure document builder: L1 format evidence --------------------------------


def test_render_agent_document_toml_parses_back_to_intended_shape():
    item = make_item(body='He said "plan:\\nnow"\n\tand non-BMP 𝓧 🜲, ]#} chars')
    text = codex.render_agent_document(item)
    parsed = tomllib.loads(text)
    assert parsed == {
        "name": "planner",
        "description": "plans work",
        "developer_instructions": 'He said "plan:\\nnow"\n\tand non-BMP 𝓧 🜲, ]#} chars',
    }


@pytest.mark.parametrize("body", [
    "\x01 control in body", "ends with backslash\\", '"""triple quote',
    "mixed ] # \" \\ \t \n stuff 😀",
])
def test_render_agent_document_survives_adversarial_bodies(body: str):
    parsed = tomllib.loads(codex.render_agent_document(make_item(body=body)))
    assert parsed["developer_instructions"] == body


def test_render_agent_document_refuses_nul_body():
    with pytest.raises(errors.DomainError):
        codex.render_agent_document(make_item(body="a\x00b"))


# -- verify: loaded is unreachable for Codex at this pin ---------------------------


EMPTY_SET = intents.IntentSet(())


@pytest.mark.parametrize("observation", [
    base.NativeLoaderObservation("planner", "cli-scan"),
    base.ControlEntryObservation("planner", "menu"),
    base.InvocationEventObservation("planner", "event-1"),
])
def test_verify_refuses_loader_class_claims_outright(observation):
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.verify_observations(observation, EMPTY_SET)
    assert excinfo.value.code == errors.NATIVE_DISCOVERY_UNCONTROLLED


def test_verify_refuses_loader_inside_bundle_too():
    bundle = base.ObservationSet((
        base.FileExistenceObservation("planner"),
        base.NativeLoaderObservation("planner", "claimed"),
    ))
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.verify_observations(bundle, EMPTY_SET)
    assert excinfo.value.code == errors.NATIVE_DISCOVERY_UNCONTROLLED


def test_verify_file_existence_never_becomes_loaded():
    result = ADAPTER.verify_observations(base.FileExistenceObservation("planner"), EMPTY_SET)
    assert result.state_of("planner") is not base.VerifyState.LOADED
    assert result.max_state in (base.VerifyState.UNKNOWN, base.VerifyState.PROJECTED)


def test_contract_verify_cannot_produce_match_for_codex():
    # the same three facts in the real Verification shapes:
    loader = ADAPTER.verify(CODEX_CONTEXT, {"kind": "loader", "native_name": "planner",
                                            "ref": "cli-scan"})
    assert isinstance(loader, Mismatch)          # never Match -> never Confirmed
    assert "cannot be attributed" in loader.reason
    file_only = ADAPTER.verify(CODEX_CONTEXT, {"kind": "file-existence",
                                               "native_name": "planner", "ref": "x"})
    assert isinstance(file_only, VerificationUnknown)
    assert isinstance(ADAPTER.verify(CODEX_CONTEXT, {"kind": "nonsense"}),
                      VerificationUnknown)


def test_no_invoke_intent_can_be_produced_for_codex():
    # an InvokeAction needs invokable evidence; the adapter offers no path
    # to mint one, and claiming one through the ACP route is exactly G12's
    # counter-example:
    with pytest.raises(errors.DomainError) as excinfo:
        intents.build_invoke_action(SOURCE, native_name="planner",
                                    action_id="assets.native-subagents.invoke",
                                    schema_version="v1", invokable_evidence=())
    assert excinfo.value.code == errors.NATIVE_ENTRY_UNAVAILABLE
