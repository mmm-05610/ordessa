"""T06 — Claude adapter triad at pin 0.81.2 (G11, G13), contract-typed.

Positive: assess refuses to claim `supported` (real `Assessment`, unknown +
pin + evidence); compile produces the complete private-generation set as
REAL `MountContent` intents with parseable documents and bound digests;
verify lifts only on the right observation kinds. Negative: silently-ignored
fields (permissionMode / mcpServers / hooks / skills / isolation) are
refused, not dropped; reserved/colliding/bad names are diagnosed before any
intent; every intent provably aims at the host-issued private target and
nothing path-shaped leaves the adapter. The old `TargetDescriptor`/
`TargetSlot` fixtures are replaced by the contract's own
`AdapterContext`/`TargetHandle` — same guard, real type.
"""
from __future__ import annotations

import dataclasses
import re

import pytest
from ordessa_harness_api import (
    AdapterContext, Installation, IntentSource, Match, Mismatch,
    TargetDescriptor, TargetHandle, VerificationUnknown,
)

from ordessa_assets_subagents import digest, dto, errors
from ordessa_assets_subagents.adapters import base, claude, frontmatter, intents

CLAUDE_HANDLE = TargetHandle(claude.CLAUDE_GENERATION_HANDLE, 3)
CLAUDE_CONTEXT = AdapterContext(
    (TargetDescriptor(CLAUDE_HANDLE, "directory", "content", "instance",
                     (("agents",),), ("restore-owned-baseline",)),),
    Installation("claude", None, claude.CLAUDE_ADAPTER_SEMVER, "fixture:install"),
    "acp", "instance", "fixture:capability",
)
SOURCE = IntentSource(intents.FACET_ID, "def-claude", "v1")
SHA = "sha256:" + "ab" * 32

#: The test-side stand-in for the host content map C0 resolves ContentRef
#: against (`RuntimeSnapshot.content` / `private_generation._preflight`).
STAGED_CONTENT: dict[str, bytes] = {}


def _stage(reference: str, data: bytes) -> None:
    STAGED_CONTENT[reference] = data


def make_item(slug: str = "code-reviewer", *, definition_id: str = "d1",
              description: str = "reviews pull requests",
              body: str = "You review pull requests carefully.",
              **revision_kwargs) -> intents.ManagedItem:
    source = revision_kwargs.pop("source", dto.SourceApproval(
        "user-upload", "file:seed.md", SHA, "principal-a", "2026-09-28T00:00:00Z"))
    revision = dto.DefinitionRevision(definition_id, 1, SHA, body, source=source,
                                      **revision_kwargs)
    definition = dto.AgentDefinition("server-a", definition_id, slug,
                                     "Code Reviewer", description, "public", "owner-a")
    return intents.ManagedItem(definition, revision)


ADAPTER = claude.ClaudeAdapter()

# -- assess: unknown at this pin, per cell, citing the pin ----------------------


def test_assess_is_unknown_never_supported():
    assessment = ADAPTER.assess(CLAUDE_CONTEXT)
    assert assessment.status == "unknown"
    assert "0.81.2" in (assessment.evidence_ref or "")
    detail = ADAPTER.assess_detail(CLAUDE_CONTEXT)
    claimed = [cell for cell in detail.cells
               if cell.state in (base.AssessmentState.SUPPORTED,
                                 base.AssessmentState.EXTENSION_BACKED)]
    assert claimed == []  # not one cell may be claimed at this pin (G01/G11)
    assert detail.evidence  # unknown still carries its facts


def test_assess_cells_reason_cite_pin_and_sr3b():
    detail = ADAPTER.assess_detail(CLAUDE_CONTEXT)
    names = {cell.cell for cell in detail.cells}
    assert {"invocation", "reload", "resume", "isolation"} <= names
    for cell in detail.cells:
        assert "0.81.2" in cell.reason
    assert "rebuild" in detail.verdict("reload").reason
    assert "SR-3b" in detail.verdict("invocation").reason


def test_assess_refuses_wrong_pin():
    bad = AdapterContext(
        CLAUDE_CONTEXT.targets,
        Installation("claude", None, (9, 9, 9), "fixture:install"),
        "acp", "instance", "fixture:capability")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.assess(bad)
    assert excinfo.value.code == errors.NATIVE_VERSION_UNKNOWN


def test_assessment_supported_without_evidence_is_constructor_error():
    with pytest.raises(base.AssessmentError):
        base.Assessment(state=base.AssessmentState.SUPPORTED, pinned_version="x@1")
    with pytest.raises(base.AssessmentError):
        base.CellVerdict(cell="format", state=base.AssessmentState.UNSUPPORTED,
                         reason="proven absent", evidence=())
    # an 'unknown' may honestly carry no evidence of its own beyond the pin
    base.Assessment(state=base.AssessmentState.UNKNOWN, pinned_version="x@1")


def test_to_real_maps_the_contract_assessment_shape():
    from ordessa_harness_api import Assessment as ContractAssessment
    real = ADAPTER.assess_detail(CLAUDE_CONTEXT).to_real()
    assert type(real) is ContractAssessment
    assert real.status in {"supported", "unsupported", "unknown"}
    # capability: an 'unknown' internal record maps cleanly because the
    # contract only forces a reason on non-supported states, which brands
    # always record:
    base.Assessment(state=base.AssessmentState.UNKNOWN, pinned_version="x@1",
                    reasons=("named",)).to_real()
    # and a non-supported record WITHOUT a reason refuses to map (the
    # contract would accept it; Q3 does not):
    silent = base.Assessment(state=base.AssessmentState.UNKNOWN, pinned_version="x@1")
    with pytest.raises(base.AssessmentError):
        silent.to_real()


# -- compile: complete private set ----------------------------------------------


def test_compile_happy_produces_complete_private_set():
    items = [make_item("alpha"), make_item("beta", definition_id="d2")]
    STAGED_CONTENT.clear()
    set_ = ADAPTER.compile(CLAUDE_CONTEXT, items, SOURCE, native_names=frozenset(),
                           stage_content=_stage)
    kinds = {type(i).__name__ for i in set_.intents}
    assert kinds == {"MountContent"}
    assert [i.relative_name for i in set_.intents] == ["agents/alpha.md", "agents/beta.md"]
    for mount in set_.intents:
        assert mount.target == CLAUDE_HANDLE
        assert mount.mode == "read-only"
        content = STAGED_CONTENT[mount.immutable_content_ref.reference]
        assert digest.bytes_digest(content) == \
            "sha256:" + mount.immutable_content_ref.sha256
    # rebuild-class option is NOT in the set: the contract cannot express it
    # and the refusal below proves it (C-6 / SR-3b-2).
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.rebuild_class_option("agents", True)
    assert excinfo.value.code == errors.DEFINITION_INVALID
    assert "rebuild-class" in excinfo.value.detail


def test_compile_happy_stamps_content_and_frontmatter():
    items = [make_item("alpha"), make_item("beta", definition_id="d2")]
    STAGED_CONTENT.clear()
    set_ = ADAPTER.compile(CLAUDE_CONTEXT, items, SOURCE, native_names=frozenset(),
                           stage_content=_stage)
    for mount in set_.intents:
        content = STAGED_CONTENT[mount.immutable_content_ref.reference]
        fields, body = frontmatter.parse_frontmatter(content.decode("utf-8"))
        assert fields["name"] == intents.mount_native_name(mount, suffix=".md")
        assert body  # role text carried


def test_compile_declares_model_and_tools_without_claiming_effect():
    item = make_item(declared_model_ref=dto.ModelRef("model-owner"),
                     tool_refs=(dto.ToolRef("grep"), dto.ToolRef("read")))
    STAGED_CONTENT.clear()
    set_ = ADAPTER.compile(CLAUDE_CONTEXT, [item], SOURCE, native_names=frozenset(),
                           stage_content=_stage)
    mount = set_.intents[0]
    content = STAGED_CONTENT[mount.immutable_content_ref.reference].decode("utf-8")
    fields, _ = frontmatter.parse_frontmatter(content)
    assert fields["model"] == "model-owner"
    assert fields["tools"] == ("grep", "read")
    supported = {entry.key for entry in claude.CLAUDE_SUPPORTED_KEYS}
    assert set(fields) <= supported


def test_compile_refuses_wrong_harness_or_missing_target():
    foreign = AdapterContext(
        CLAUDE_CONTEXT.targets,
        Installation("codex", None, claude.CLAUDE_ADAPTER_SEMVER, "fixture:install"),
        "acp", "instance", "fixture:capability")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(foreign, [], SOURCE)
    assert excinfo.value.code == errors.TARGET_CONFLICT
    no_target = AdapterContext((), Installation("claude", None,
                                                 claude.CLAUDE_ADAPTER_SEMVER, "f"),
                               "acp", "instance", "fixture:cap")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(no_target, [make_item()], SOURCE)
    assert excinfo.value.code == errors.TARGET_CONFLICT


# -- field refusals: nothing silently ignored, nothing silently dropped ----------

REMOVALS = [
    ("permissionMode", lambda: make_item(requested_permission="bypassPermissions"),
     errors.PERMISSION_EXCEEDS_CEILING, "permission"),
    ("mcpServers", lambda: make_item(mcp_refs=(dto.McpRef("evil-server"),)),
     errors.PERMISSION_EXCEEDS_CEILING, "mcp"),
    ("skills", lambda: make_item(skill_refs=(dto.SkillRef("s"),)),
     errors.REFERENCE_UNRESOLVED, "skill"),
    ("isolation", lambda: make_item(isolation={"mode": "own-process"}),
     errors.REFERENCE_UNRESOLVED, "isolation"),
    ("retained-hooks", lambda: make_item(retained_native_fields={"hooks": [{"x": 1}]}),
     errors.DEFINITION_INVALID, "hooks"),
    ("retained-unknown-key", lambda: make_item(retained_native_fields={"disallowedTools": "z"}),
     errors.DEFINITION_INVALID, "disallowedtools"),
]


@pytest.mark.parametrize("name,factory,code,needle", REMOVALS,
                         ids=[r[0] for r in REMOVALS])
def test_compile_refuses_by_name_before_any_intent(name, factory, code, needle):
    items = [make_item("good-one"), factory()]  # refusal on item 2 must veto item 1 too
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CLAUDE_CONTEXT, items, SOURCE)
    assert excinfo.value.code == code
    assert needle in (excinfo.value.detail or "").lower()
    assert excinfo.value.item_id in (None, "d1", "d2") or "d" in (excinfo.value.item_id or "")


def test_compile_refuses_the_offending_item_id():
    bad = make_item("beta", definition_id="culprit", requested_permission="x")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CLAUDE_CONTEXT, [make_item("alpha"), bad], SOURCE)
    assert excinfo.value.item_id == "culprit"


# -- name rules and collisions (G13) ---------------------------------------------


@pytest.mark.parametrize("bad_slug", ["Reviewer", "a b", "~/x", "a/b", "", "x" * 65, "-a"])
def test_agent_name_grammar_enforced(bad_slug: str):
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CLAUDE_CONTEXT, [make_item(bad_slug)], SOURCE)
    assert excinfo.value.code == errors.DEFINITION_INVALID


def test_reserved_name_refused_as_conflict():
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CLAUDE_CONTEXT, [make_item("general-purpose")], SOURCE)
    assert excinfo.value.code == errors.NATIVE_NAME_CONFLICT


def test_managed_duplicate_and_native_collision_diagnosed():
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CLAUDE_CONTEXT, [make_item("twin"), make_item("twin", definition_id="d2")],
                        SOURCE)
    assert excinfo.value.code == errors.NATIVE_NAME_CONFLICT
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.compile(CLAUDE_CONTEXT, [make_item("user-said")], SOURCE,
                        native_names=frozenset({"user-said"}))
    assert excinfo.value.code == errors.NATIVE_NAME_CONFLICT


def test_unknown_native_discovery_recorded_never_assumed_absent():
    ADAPTER.compile(CLAUDE_CONTEXT, [make_item()], SOURCE)  # native_names=None
    assert any("unknown" in d for d in intents.discovery_diagnostics(None))
    assert intents.discovery_diagnostics(frozenset()) == ()


# -- isolation: private target only, nothing user/project ------------------------

_PATHISH = re.compile(r"[/\\~]|\.(claude|codex)\b|/\.|\$HOME")


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, (bytes,)):
        return
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _walk_strings(getattr(obj, f.name))
    elif isinstance(obj, (tuple, list, set, frozenset)):
        for entry in obj:
            yield from _walk_strings(entry)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk_strings(key)
            yield from _walk_strings(value)


def test_every_produced_intent_targets_the_private_handle_only():
    items = [make_item("alpha"), make_item("beta", definition_id="d2")]
    set_ = ADAPTER.compile(CLAUDE_CONTEXT, items, SOURCE, native_names=frozenset())
    for intent in set_.intents:
        assert intent.target == CLAUDE_HANDLE  # the host-issued private target
        # no path-shaped string anywhere: since the refactor the mounted
        # document is NOT in the intent at all (it is content-addressed), so
        # only tokens are walkable. `relative_name` is the contract's own
        # normalized relative layout (its `_relative_name` validator refuses
        # absolute paths, `\`, "" / "." / ".." segments — pinned by
        # test_real_constructors_cannot_be_lured_into_a_path_target):
        for text in _walk_strings(intent):
            if text == type(intent).__name__ or text == "read-only":
                continue
            if text == intent.relative_name:
                continue
            assert _PATHISH.search(text) is None, text
        assert not intent.relative_name.startswith("/")
        assert "\\" not in intent.relative_name
    # capability: without the compile path, the raw constructor would ACCEPT
    # a `~` single-segment name — Q3's grammar layer is load-bearing:
    from ordessa_harness_api import ContentRef, MountContent as RealMount
    RealMount(SOURCE, CLAUDE_HANDLE, "~x.md",
              ContentRef("a" * 64, "a" * 64, 1), "read-only")
    with pytest.raises(errors.DomainError):
        intents.mount_relative_name("~x")


def test_reset_is_an_owned_removal_under_the_host_handle():
    remove = intents.build_remove(SOURCE, CLAUDE_HANDLE, native_name="alpha")
    assert isinstance(remove, intents.RemoveOwnedContent)
    assert remove.relative_name == "agents/alpha.md"
    # FR09 ownership scoping is C0's snapshot keyed on the host-granted
    # owner (intent_merge.py:218-220 / private_generation.py:278-287):
    # Q3 cannot address anything outside the managed layout:
    for hostile in ("~/.claude/agents", ".claude/agents", "agents/../../x"):
        with pytest.raises(errors.DomainError):
            intents.build_remove(SOURCE, CLAUDE_HANDLE, native_name=hostile)


# -- invoke & verify (G11) ---------------------------------------------------------


def test_invoke_intent_cannot_be_emitted_at_this_pin():
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.invoke("code-reviewer")
    assert excinfo.value.code == errors.NATIVE_ENTRY_UNAVAILABLE
    # capability: the SAME builder channel does work once evidence exists
    # (SR-3b-3's future path), proving the refusal is the evidence gate and
    # not a broken code path:
    action = intents.build_invoke_action(
        SOURCE, native_name="code-reviewer",
        action_id="assets.native-subagents.invoke", schema_version="v1",
        invokable_evidence=("subagent-capability-negotiated-ref",))
    assert action.source == SOURCE


def _compiled_set() -> base.IntentSet:
    return ADAPTER.compile(CLAUDE_CONTEXT, [make_item()], SOURCE, native_names=frozenset())


def test_verify_file_existence_never_lifts_to_loaded():
    result = ADAPTER.verify_observations(base.FileExistenceObservation("code-reviewer"),
                                         _compiled_set())
    assert result.state_of("code-reviewer") is base.VerifyState.PROJECTED
    assert result.max_state is base.VerifyState.PROJECTED


def test_verify_needs_three_different_observation_kinds():
    name = "code-reviewer"
    cases = {
        base.ProjectedArtifactObservation(name, "gen-1"): base.VerifyState.PROJECTED,
        base.NativeLoaderObservation(name, "loader-scan-obs"): base.VerifyState.LOADED,
        base.ObservationSet((base.NativeLoaderObservation(name, "l"),
                             base.ControlEntryObservation(name, "c"))):
            base.VerifyState.INVOKABLE,
        base.ObservationSet((base.NativeLoaderObservation(name, "l"),
                             base.ControlEntryObservation(name, "c"),
                             base.InvocationEventObservation(name, "subagent_spawned-1"))):
            base.VerifyState.USED,
    }
    for observation, expected in cases.items():
        result = ADAPTER.verify_observations(observation, _compiled_set())
        assert result.state_of(name) is expected, observation


def test_require_state_refuses_unattested_claims():
    only_file = base.FileExistenceObservation("code-reviewer")
    with pytest.raises(errors.DomainError) as excinfo:
        base.require_state(only_file, base.VerifyState.LOADED)
    assert excinfo.value.code == errors.LOAD_UNVERIFIED
    base.require_state(only_file, base.VerifyState.PROJECTED)  # ok


def test_verify_unobserved_items_stay_unknown():
    set_ = ADAPTER.compile(CLAUDE_CONTEXT, [make_item("alpha"), make_item("beta", definition_id="d2")],
                           SOURCE, native_names=frozenset())
    result = ADAPTER.verify_observations(base.NativeLoaderObservation("alpha", "obs"), set_)
    assert result.state_of("alpha") is base.VerifyState.LOADED
    assert result.state_of("beta") is base.VerifyState.UNKNOWN


def test_verify_rejects_foreign_facet_intent_set():
    from ordessa_harness_api import IntentSet as RealIntentSet
    # empty set: nothing managed — observed "x" stays UNKNOWN, no crash
    # (capability probe that verify works on sets without managed members):
    result = ADAPTER.verify_observations(base.FileExistenceObservation("x"),
                                         RealIntentSet(()))
    assert result.state_of("x") is base.VerifyState.UNKNOWN
    # a set whose intents carry a FOREIGN facet is refused — the same rule
    # C0's merge enforces against the authorized submission
    # (`intent_merge.py:166-173`):
    foreign = IntentSource("assets.skills", "s", "v1")
    mount = intents.build_mount(foreign, CLAUDE_HANDLE, native_name="x", content="y")
    with pytest.raises(errors.DomainError) as excinfo:
        ADAPTER.verify_observations(base.FileExistenceObservation("x"),
                                    RealIntentSet((mount,)))
    assert excinfo.value.code == errors.TARGET_CONFLICT
    # and the builder layer itself refuses to compile for a foreign facet:
    with pytest.raises(errors.DomainError):
        intents.validate_source(foreign)


def test_contract_verify_match_requires_loader_evidence():
    # the state machine, expressed in the real Verification types:
    loaded = ADAPTER.verify(CLAUDE_CONTEXT, {"kind": "loader", "native_name": "code-reviewer",
                                             "ref": "obs-1"})
    assert isinstance(loaded, Match) and loaded.evidence_ref == \
        "NativeLoaderObservation:code-reviewer@obs-1"
    file_only = ADAPTER.verify(CLAUDE_CONTEXT, {"kind": "file-existence",
                                                 "native_name": "code-reviewer", "ref": "sighting"})
    assert isinstance(file_only, VerificationUnknown)  # never Match (G11)
    garbage = ADAPTER.verify(CLAUDE_CONTEXT, {"kind": "magic", "x": 1})
    assert isinstance(garbage, VerificationUnknown)
    assert isinstance(ADAPTER.verify(CLAUDE_CONTEXT, "not-an-observation"),
                      VerificationUnknown)


def test_domain_refusals_map_to_the_contract_refusal_shape():
    try:
        ADAPTER.compile(CLAUDE_CONTEXT, [make_item("general-purpose")], SOURCE)
    except errors.DomainError as exc:
        refusal = base.adapter_refusal_for(exc)
        assert isinstance(refusal, base.AdapterRefusal)
        assert refusal.code.value == "target-conflict"
    else:  # pragma: no cover
        raise AssertionError("reserved name must refuse")
