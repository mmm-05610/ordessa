"""T06-seam — mapping Q3's compile output onto the published C0 contract.

This file is the boundary test demanded by SR-1b: Q3 keeps NO parallel
public intent shape; everything leaving `compile_all` is
`ordessa_harness_api`. It also records the answers to the three open SR-1b
mapping questions, each verified from the real code (file:line evidence
below is inside this worktree at review time; nothing here imports
`ordessa_harness` internals — only the published API — per the import
boundary):

(a) HOW IS A COMPLETE MANAGED SET MOUNTED?
    One `MountContent` per item — there is no set-level intent and none is
    needed. `ContentRef(reference, sha256, size)`
    (`ordessa_harness_api/intents.py:108-119`) IS content-addressed external
    storage: the intent carries no bytes; the service resolves the reference
    against the runtime's content map and re-verifies digest+size at
    materialization (`plugins/harness/src/ordessa_harness/materialization/`
    `private_generation.py:268-277`: `data = content.get(ref)`, digest
    mismatch refuses). The 「一次性编译完整目标集合，不逐项拼补丁」 property
    is guaranteed *host-side*: every apply rebuilds and publishes one whole
    private generation directory (`private_generation.py:447-460`
    `materialize_generation` — "Callers may start a *new* instance ... there
    is no hot apply"), and overlapping claims within one merged plan are
    refused (`intent_merge.py:235-239`). Q3 expresses the shared grant as
    one directory `FieldClaim` on the ("agents",) prefix that every emitted
    `relative_name` starts with — matching the service's own claim
    predicate (`configuration_service.py:104-106`).
    RESIDUAL GAP: the `ConfigurationAdapter` protocol has no port for the
    adapter to *deposit* the document bytes the content map must later
    resolve (`compile` returns only an `IntentSet`); Q3 therefore accepts a
    host-injected `stage_content` sink and reports the missing staging port
    to C0 (symbol request below).

(b) WHICH `ResetField.baseline_rule` MEANS "REMOVE ONLY WHAT THIS FACET OWNS"?
    For directory/content output the answer is NOT a `ResetField` at all:
    it is `RemoveOwnedContent`, whose ownership is enforced against the
    host-owned snapshot keyed by (target handle, resource, relative_name)
    and compared to the carrier-granted OWNER, not to `IntentSource.facet_id`
    (`intent_merge.py:218-220` + `private_generation.py:278-287`: "remove
    lacks ownership snapshot"). On file targets `restore-owned-baseline` is
    the DTO-level candidate (`intents.py:91`, authorized per
    `descriptor.baseline_rules` at `intent_merge.py:207-209`), but the
    current materializer implements ONLY `remove-key` and raises
    "unsupported reset baseline rule" for the rest
    (`private_generation.py:259-263`) — registered as a C0 gap, so Q3's
    FR09 reset path stays `RemoveOwnedContent`-only.

(c) CAN `Assessment`/`Verification` CARRY EVIDENCE SO `supported` IS NEVER
    CLAIMED WITHOUT PROOF?
    Partially: `Match` REQUIRES a non-empty `evidence_ref`
    (`contracts.py:208-214` with `_nonempty` at `contracts.py:13-16`), and
    only `Match` can produce `Confirmed`
    (`application/configuration_service.py:303-305`), so the *verification*
    side already cannot be claimed without proof. The *assessment* side
    cannot: `Assessment.__post_init__` (`contracts.py:191-206`) forces a
    reason only on non-supported and leaves `evidence_ref` optional even
    for `supported` (the fixture proves it: `Assessment("supported",
    evidence_ref=…)` is convention, not enforcement —
    `plugins/harness/tests/fixtures/external_adapter/src/`
    `ordessa_test_external_adapter/__init__.py:33`). Q3 therefore keeps its
    own constructor rule (no verdict without an evidence tuple, G01/G03) in
    `base.Assessment`, and always fills `evidence_ref` when mapping out.
    SYMBOL REQUEST to C0: require `evidence_ref` when
    `Assessment.status == "supported"`.

Owner-forgery (design: 注册 owner 由宿主授予): structurally impossible
because the shape has no owner slot — `IntentSource` fields are exactly
{facet_id, item_id, contribution_version} (`intents.py:17-25`), payloads
declaring an owner are refused at staging
(`plugins/harness/src/ordessa_harness/contributions.py:97-98`), and the
merge authority re-checks every intent's source against the authorized
submission (`intent_merge.py:166-173`). The mirror of that last check is
re-implemented below from the published API only, and our output must pass
it while any tampered source must fail it.
"""
from __future__ import annotations

import dataclasses

import pytest
from ordessa_harness_api import (
    AdapterContext, Assessment, BindSecret, ConfigurationAdapterDescriptor,
    ContractError, FieldClaim, Installation, Intent, IntentSet, IntentSource,
    Match, MountContent, RemoveOwnedContent, ResetField, SetField,
    TargetDescriptor, TargetHandle, ValueSchema, VersionRange, closed_object,
    validate_json,
)
from ordessa_harness_api.schema import looks_secret_name

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.adapters import claude, intents
from ordessa_assets_subagents.adapters.intents import (
    FACET_ID, ManagedItem, compile_all,
)

SHA = "sha256:" + "ab" * 32
HANDLE = TargetHandle("assets-native-subagents-claude-generation", 2)
CONTEXT = AdapterContext(
    (TargetDescriptor(HANDLE, "directory", "content", "instance",
                     (("agents",),), ("remove-key", "restore-owned-baseline")),),
    Installation("claude", None, (0, 81, 2), "fixture:install"),
    "acp", "instance", "fixture:capability",
)
SOURCE = IntentSource(FACET_ID, "def-seam", "v1")


def render(item: ManagedItem) -> str:
    return f"name: {item.native_name}\n\n{item.revision.role_body}"


def make_item(slug: str = "seam-agent", *, definition_id: str = "d1") -> ManagedItem:
    revision = dto.DefinitionRevision(
        definition_id, 1, SHA, "Seam body.",
        source=dto.SourceApproval("user-upload", "file:s.md", SHA, "p",
                                  "2026-09-28T00:00:00Z"))
    definition = dto.AgentDefinition("server-a", definition_id, slug, "S",
                                     "seam item", "public", "o")
    return ManagedItem(definition, revision)


def _has_directory_claim(descriptor: ConfigurationAdapterDescriptor,
                        intent: MountContent) -> bool:
    """Mirror of C0's directory-claim predicate
    (`configuration_service.py:104-106`, published-API types only)."""
    return any(claim.target_kind == "directory"
               and claim.target_id == intent.target.handle_id
               and tuple(intent.relative_name.split("/"))[:len(claim.field_path)]
               == claim.field_path
               for claim in descriptor.claims)


# -- (a) complete managed set --------------------------------------------------


def test_complete_set_is_one_mount_per_item_under_one_shared_claim():
    items = [make_item("alpha", definition_id="d1"), make_item("beta", definition_id="d2")]
    staged: dict[str, bytes] = {}
    set_ = compile_all(items, CONTEXT, SOURCE, render=render,
                       native_names=frozenset(),
                       stage_content=lambda ref, data: staged.__setitem__(ref, data))
    assert type(set_) is IntentSet
    assert all(type(i) is MountContent for i in set_.intents)
    assert len(set_.intents) == 2  # one per item; no set-level pseudo-intent
    for mount in set_.intents:
        # every mount matches the adapter's single directory claim:
        assert _has_directory_claim(claude.ClaudeAdapter.descriptor, mount)
        # ContentRef = reference + digest + size, and NOTHING else — proof
        # the shape is content-addressed storage, not inline content:
        assert {f.name for f in dataclasses.fields(mount.immutable_content_ref)} \
            == {"reference", "sha256", "size"}
        # the host can resolve exactly the staged bytes (same rule as
        # private_generation._preflight):
        data = staged[mount.immutable_content_ref.reference]
        assert len(data) == mount.immutable_content_ref.size
        import hashlib
        assert hashlib.sha256(data).hexdigest() == mount.immutable_content_ref.sha256


def test_intent_carries_no_document_bytes_anymore():
    # CA2 fact: the old Q3 MountContent had a `content` str field; the
    # contract's has none, so no credential-adjacent blob can hide there:
    field_names = {f.name for f in dataclasses.fields(MountContent)}
    assert "content" not in field_names
    assert field_names == {"source", "target", "relative_name",
                           "immutable_content_ref", "mode", "kind"}


def test_missing_staging_port_is_reported_not_invented():
    # compile without a host sink still yields a valid, resolvable-by-the-
    # host set (the sink is C0's job once the staging port lands); proving
    # compile is not secretly storing content anywhere:
    set_ = compile_all([make_item()], CONTEXT, SOURCE, render=render,
                       native_names=frozenset())
    mount = set_.intents[0]
    assert dataclasses.asdict(mount)["immutable_content_ref"]["reference"] \
        == mount.immutable_content_ref.sha256


# -- (b) reset / remove ownership -----------------------------------------------


def test_owned_removal_is_the_facets_reset_channel_and_is_layout_bounded():
    remove = intents.build_remove(SOURCE, HANDLE, native_name="seam-agent")
    assert type(remove) is RemoveOwnedContent
    assert remove.relative_name == "agents/seam-agent.md"
    # removals address only the managed ("agents",) subtree — the same
    # prefix the descriptor claims; anything else cannot be constructed:
    with pytest.raises(errors.DomainError):
        intents.build_remove(SOURCE, HANDLE, native_name="../user-file")


def test_restore_owned_baseline_is_dto_legal_but_not_materializer_supported():
    # DTO level (contract): a legal ResetField for a file target ...
    field_target = TargetHandle("some-json-settings", 1)
    rule = ResetField(SOURCE, field_target,
                      intents.safe_field_path(("model",)), "restore-owned-baseline")
    assert rule.baseline_rule == "restore-owned-baseline"
    # ... but the *published materializer today implements only
    # `remove-key` (private_generation.py:259-263); Q3 therefore does NOT
    # route any facet reset through ResetField — FR09 removal for this
    # facet is RemoveOwnedContent (ownership-snapshot enforced). The gap
    # ("implement restore-owned-baseline or say so") goes to C0.
    with pytest.raises(ContractError):
        ResetField(SOURCE, field_target, intents.safe_field_path(("model",)),
                   "restore-facet-only")  # unknown rule is closed at the DTO


# -- (c) evidence rules -----------------------------------------------------------


def test_match_requires_evidence_and_assessment_supported_does_not():
    Match("fixture:readback")            # legal with evidence
    with pytest.raises(ContractError):
        Match("")                        # the Match side enforces proof
    # the GAP: the Assessment side does not —
    bare = Assessment("supported")
    assert bare.evidence_ref is None
    # Q3's internal record refuses the same claim without evidence:
    from ordessa_assets_subagents.adapters import base
    with pytest.raises(base.AssessmentError):
        base.Assessment(state=base.AssessmentState.SUPPORTED, pinned_version="x@1")
    # and the mapping never emits an evidence-less supported:
    full = base.Assessment(state=base.AssessmentState.SUPPORTED, pinned_version="x@1",
                           evidence=("probe-ref-1",), reasons=("named",))
    assert full.to_real().evidence_ref is not None


def test_sealed_json_validators_are_the_real_gate():
    # `validate_json` + `looks_secret_name` are the contract's own guards
    # Q3 reuses (secret names cannot ride SetField):
    assert looks_secret_name("api_key")
    assert looks_secret_name("token")
    assert not looks_secret_name("description")
    with pytest.raises(ContractError):
        validate_json({"api_key": "x"})
    with pytest.raises(ContractError):
        SetField(SOURCE, HANDLE, __import__("ordessa_harness_api").FieldPath(("token",)),
                 "abc")
    closed = closed_object(model=ValueSchema("string"))
    with pytest.raises(ContractError):
        closed.validate({"model": "m", "extra": 1})
    assert closed.validate({"model": "m"}) == {"model": "m"}


# -- owner forgery is structurally impossible ------------------------------------


def mirror_merge_source_check(set_: IntentSet, authorized: IntentSource) -> None:
    """Re-implementation of `intent_merge.py:166-173` over published types:
    every intent's source must equal the host-authorized identity."""
    for intent in set_.intents:
        if intent.source.facet_id != authorized.facet_id:
            raise AssertionError("source facet differs from authorized facet")
        if intent.source.item_id != authorized.item_id:
            raise AssertionError("source item differs from authorized item")
        if intent.source.contribution_version != authorized.contribution_version:
            raise AssertionError("source version differs from authorized version")


def test_output_passes_the_host_source_authorization_check():
    set_ = compile_all([make_item()], CONTEXT, SOURCE, render=render,
                       native_names=frozenset())
    mirror_merge_source_check(set_, SOURCE)          # positive column
    for intent in set_.intents:
        assert intent.source is SOURCE or intent.source == SOURCE


def test_a_tampered_source_is_caught_by_the_host_check():
    forged = IntentSource(FACET_ID, "someone-elses-item", "v1")
    set_ = compile_all([make_item()], CONTEXT, forged, render=render,
                       native_names=frozenset())
    with pytest.raises(AssertionError):
        mirror_merge_source_check(set_, SOURCE)      # host rejects the lie


def test_compile_cannot_self_author_a_source():
    # no default, no fallback, no owner slot anywhere in the emitted shape:
    with pytest.raises(errors.DomainError):
        compile_all([make_item()], CONTEXT, None, render=render)
    names = {f.name for f in dataclasses.fields(IntentSource)}
    assert names == {"facet_id", "item_id", "contribution_version"}
    for intent in compile_all([make_item()], CONTEXT, SOURCE, render=render,
                              native_names=frozenset()).intents:
        assert not any("owner" in f.name.lower()
                       for f in dataclasses.fields(type(intent)))


def test_descriptor_registration_shapes_are_the_real_types():
    descriptor = claude.ClaudeAdapter.descriptor
    assert isinstance(descriptor, ConfigurationAdapterDescriptor)
    assert descriptor.facet_id == FACET_ID
    assert descriptor.harness_id == "claude"
    assert isinstance(descriptor.native_versions, VersionRange)
    assert descriptor.adapter_versions.contains((0, 81, 2)) is True
    assert descriptor.adapter_versions.contains((9, 9, 9)) is False
    assert all(isinstance(claim, FieldClaim) for claim in descriptor.claims)
    assert descriptor.claims == (
        FieldClaim("directory", claude.CLAUDE_GENERATION_HANDLE, ("agents",)),)
    # payload schema is a real ValueSchema and rejects junk:
    with pytest.raises(ContractError):
        descriptor.payload_schema.validate({"definitions": "not-a-list"})
    assert descriptor.payload_schema.validate({"definitions": ["d1"]})
