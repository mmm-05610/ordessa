"""T06 negative+positive tests for the intent builders — now asserted over the
REAL `ordessa_harness_api` vocabulary (SR-1b refactor of the same guards).

Every guard this file owned before is kept with its original intent: no path,
`~` string, shell string or cwd is expressible; digests are bound to content;
the complete collection is compiled in one shot with refusals *before* any
intent object exists. What changed is the target: the builders emit the
published contract's `IntentSet`/`MountContent`/`RemoveOwnedContent`/
`BindSecret`/`InvokeAction`, so several closedness assertions are now
proven against C0's own constructors, which are *stricter in kind* but
*laxer in shape* than Q3's old enum — the module docstring of `intents.py`
records why Q3 layers its token grammar over them.
"""
from __future__ import annotations

import dataclasses

import pytest
from ordessa_harness_api import (
    AdapterContext, BindSecret, ContractError, ContentRef, FieldPath,
    Installation, IntentSet, IntentSource, InvokeAction, MountContent,
    RemoveOwnedContent, SetField, TargetDescriptor, TargetHandle,
)

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.adapters import intents
from ordessa_assets_subagents.adapters.intents import (
    FACET_ID, ManagedItem, build_invoke_action, build_mount,
    build_rebuild_class_option, build_remove, build_secret_binding,
    compile_all, discovery_diagnostics, mount_relative_name, safe_field_path,
)

DIGEST_BODY = "You are a reviewer."
SHA = "sha256:" + "ab" * 32
HANDLE = TargetHandle("assets.native-subagents.claude.generation", 3)


def directory_context(handle: TargetHandle = HANDLE, harness: str = "claude") -> AdapterContext:
    return AdapterContext(
        (TargetDescriptor(handle, "directory", "content", "instance",
                          (("agents",),), ("restore-owned-baseline",)),),
        Installation(harness, None, (0, 81, 2), "fixture:install"),
        "acp", "instance", "fixture:capability",
    )


def make_source(item_id: str = "def-1", *, facet: str = FACET_ID,
                version: str = "v1") -> IntentSource:
    return IntentSource(facet, item_id, version)


def render(item: ManagedItem) -> str:
    return f"name: {item.native_name}\n\n{item.revision.role_body}"


def make_item(slug: str = "code-reviewer", *, definition_id: str = "d1",
              description: str = "reviews code", body: str = DIGEST_BODY,
              retained: dict | None = None, with_source: bool = True,
              **revision_kwargs) -> ManagedItem:
    source = (dto.SourceApproval("user-upload", "file:seed.md", SHA,
                                 "principal-a", "2026-09-28T00:00:00Z")
              if with_source else None)
    revision = dto.DefinitionRevision(definition_id, 1, SHA, body,
                                      source=source,
                                      retained_native_fields=retained or {},
                                      **revision_kwargs)
    definition = dto.AgentDefinition("server-a", definition_id, slug,
                                     "Code Reviewer", description, "public", "owner-a")
    return ManagedItem(definition, revision)


# -- the old vocabulary is gone; the contract's closedness rules instead --------


def test_target_slot_enum_is_deleted_from_the_producing_surface():
    # SR-1b/CA2: two sealed vocabularies cannot both survive; the Q3 enum was
    # removed, not "kept as an alias".
    assert not hasattr(intents, "TargetSlot")
    assert not hasattr(intents, "SetRebuildClassOption")
    assert not hasattr(intents, "InvokeSubagent")
    # the produced intents ARE the contract's:
    mount = build_mount(make_source(), HANDLE, native_name="agent-a", content="body")
    assert type(mount) is MountContent
    assert mount.target is HANDLE  # copied, never derived


@pytest.mark.parametrize("raw", [
    "/home/u/.claude/agents", "~/.claude/agents", ".claude/agents",
    "/tmp/x", "private-generation-pi", "cwd", "", "HOME",
])
def test_the_old_slot_strings_are_not_targets_anymore(raw: str):
    # A slot string is not a target: targets are server-issued handles, and a
    # bare string is refused wherever a target is taken.
    with pytest.raises(errors.DomainError):
        build_mount(make_source(), raw, native_name="agent-a", content="body")
    with pytest.raises(errors.DomainError):
        build_remove(make_source(), raw, native_name="agent-a")


def test_real_constructors_cannot_be_lured_into_a_path_target():
    # structural fact of the contract itself (documented in SR-1b):
    with pytest.raises(ContractError):
        TargetHandle("", 1)                      # empty id
    with pytest.raises(ContractError):
        TargetHandle("gen", -1)                  # negative generation
    with pytest.raises(ContractError):
        MountContent(make_source(), HANDLE, "/etc/passwd",
                     ContentRef("r", "a" * 64, 1), "read-only")
    with pytest.raises(ContractError):
        MountContent(make_source(), HANDLE, "agents/../x.md",
                     ContentRef("r", "a" * 64, 1), "read-only")
    # ... while the contract WOULD accept a single `~x` segment — Q3's stricter
    # token layer is what refuses it (proven below):
    MountContent(make_source(), HANDLE, "~tilde.md",
                 ContentRef("r", "a" * 64, 1), "read-only")
    with pytest.raises(errors.DomainError):
        mount_relative_name("~x")


# -- path/shell strings cannot hide in any field -------------------------------

HOSTILE = [
    "/etc/passwd", "relative/path", "~/.claude/agents", ".hidden",
    "a;b|c", "x $(rm -rf /)", "back\\slash", "with space", "tab\there",
    "nul\there\x00", "UPPER", "", "a" * 65, "x"*64 + "y", "-lead",
    "https://evil.example/x", "C:\\Windows",
]

#: Shape attacks any free-text intent token must survive (case and length
#: are name-grammar facts, not token-safety facts — `UPPER` is a harmless
#: keyword and stays out of this list).
TOKEN_HOSTILE = [
    "/etc/passwd", "relative/path", "~/.claude/agents", ".hidden",
    "a;b|c", "x $(rm -rf /)", "back\\slash", "with space", "tab\there",
    "nul\there\x00", "", "a" * 129, "-flag",
    "https://evil.example/x", "C:\\Windows",
]


@pytest.mark.parametrize("hostile", HOSTILE)
def test_native_name_field_refuses_path_or_shell_strings(hostile: str):
    with pytest.raises(errors.DomainError) as excinfo:
        build_mount(make_source(), HANDLE, native_name=hostile, content="content")
    assert excinfo.value.code == errors.DEFINITION_INVALID
    with pytest.raises(errors.DomainError):
        build_remove(make_source(), HANDLE, native_name=hostile)
    with pytest.raises(errors.DomainError):
        build_invoke_action(make_source(), native_name=hostile,
                            action_id="a", schema_version="v1",
                            invokable_evidence=("some-evidence",))
    # capability probe: the SAME builder accepts a valid name (the guard is
    # live, not a blind raise).
    ok = build_mount(make_source(), HANDLE, native_name="agent-a", content="content")
    assert ok.relative_name == "agents/agent-a.md"


@pytest.mark.parametrize("hostile", TOKEN_HOSTILE)
def test_field_paths_refuse_path_or_shell_strings(hostile: str):
    with pytest.raises(errors.DomainError):
        safe_field_path((hostile,))
    with pytest.raises(errors.DomainError):
        safe_field_path(("agents", hostile))
    # the contract's own FieldPath additionally refuses raw separators /
    # traversal even if this layer were removed:
    if hostile in {"", "/", "..", "."} or "/" in hostile or "\\" in hostile:
        with pytest.raises(ContractError):
            FieldPath((hostile,))
    safe_field_path(("agents",))  # capability: valid paths compile


@pytest.mark.parametrize("hostile", TOKEN_HOSTILE)
def test_invoke_evidence_refuses_path_or_shell_strings(hostile: str):
    with pytest.raises(errors.DomainError):
        build_invoke_action(make_source(), native_name="agent-a",
                            action_id="a", schema_version="v1",
                            invokable_evidence=(hostile,))
    # capability: a bare token passes
    action = build_invoke_action(make_source(), native_name="agent-a",
                                 action_id="assets.native-subagents.invoke",
                                 schema_version="v1",
                                 invokable_evidence=("control-entry-obs-1",))
    assert isinstance(action, InvokeAction)


def test_secret_binding_slot_and_ref_refuse_path_or_shell_strings():
    env = TargetHandle("assets.native-subagents.claude.environment", 1)
    for hostile in TOKEN_HOSTILE:
        with pytest.raises(errors.DomainError):
            build_secret_binding(make_source(), env, slot=hostile,
                                 secret_ref="opaque-ref")
        with pytest.raises(errors.DomainError):
            build_secret_binding(make_source(), env, slot="provider_api_key",
                                 secret_ref=hostile)
    # capability: an opaque host-granted binding is a real BindSecret
    binding = build_secret_binding(make_source(), env, slot="provider_api_key",
                                   secret_ref="vault-ref-1")
    assert isinstance(binding, BindSecret)
    # and a secret-bearing NAME can never ride a SetField (the contract's own
    # rule this refactor inherits): plaintext goes to BindSecret only.
    with pytest.raises(ContractError):
        SetField(make_source(), HANDLE, FieldPath(("api_key",)), "x")


# -- rebuild-class options: refused, never spelled as hot apply -----------------


def test_rebuild_option_cannot_be_spelled_at_all():
    # The published vocabulary has no rebuild-class option intent and Q3 must
    # not map `agents` onto SetField (that would claim an in-place apply —
    # disproved at C-6). The refusal is total and named.
    for key in ("agents", "setting_sources", "anything"):
        with pytest.raises(errors.DomainError) as excinfo:
            build_rebuild_class_option(key, True)
        assert "rebuild-class" in excinfo.value.detail
    # capability probe: compile itself is NOT blocked by this refusal —
    # mounts still come out (tested in the happy-path tests below).


def test_emitted_kind_set_is_closed_to_contract_members():
    set_ = compile_all([make_item()], directory_context(), make_source(),
                       render=render, native_names=frozenset())
    kinds = {type(i) for i in set_.intents}
    assert kinds == {MountContent}
    # the real IntentSet re-validates membership: a foreign object cannot be
    # stuffed into a set even by a direct constructor call:
    with pytest.raises(ContractError):
        IntentSet((object(),))
    with pytest.raises(ContractError):
        IntentSet(("not-an-intent",))


# -- digest is bound to content ------------------------------------------------


def test_mount_digest_must_match_content():
    from ordessa_assets_subagents import digest
    content = "name: agent-a\n"
    good = build_mount(make_source(), HANDLE, native_name="agent-a",
                       content=content, content_digest=digest.bytes_digest(content.encode()))
    assert good.immutable_content_ref.sha256 == digest.bytes_digest(content.encode()).removeprefix("sha256:")
    with pytest.raises(errors.DomainError) as excinfo:
        build_mount(make_source(), HANDLE, native_name="agent-a", content=content,
                    content_digest="sha256:" + "0" * 64)
    assert "does not stamp" in excinfo.value.detail
    with pytest.raises(errors.DomainError):
        build_mount(make_source(), HANDLE, native_name="agent-a", content=content,
                    content_digest="md5:abcdef")


def test_contentref_is_the_digest_addressed_external_ref_c0_resolves():
    # SR-1b(a) fact encoded: ContentRef carries reference/sha256/size ONLY —
    # the bytes live in the host content map C0 reads at
    # `private_generation._preflight` (`data = content.get(ref)`).
    staged: dict[str, bytes] = {}
    set_ = compile_all([make_item("code-reviewer")], directory_context(), make_source(),
                       render=render, native_names=frozenset(),
                       stage_content=lambda ref, data: staged.__setitem__(ref, data))
    mount = set_.intents[0]
    ref = mount.immutable_content_ref
    assert ref.reference == ref.sha256 and len(ref.sha256) == 64
    assert staged[ref.reference].decode() == render(make_item("code-reviewer"))
    assert len(staged[ref.reference]) == ref.size


def test_mount_content_rejects_nul_and_stray_control_bytes():
    from ordessa_assets_subagents import digest
    for bad in ("a\x00b", "a\x07b"):
        with pytest.raises(errors.DomainError):
            build_mount(make_source(), HANDLE, native_name="agent-a", content=bad)
    # capability: ordinary text passes
    build_mount(make_source(), HANDLE, native_name="agent-a",
                content="a\tb\nc\r\nok")
    assert digest.is_digest(digest.bytes_digest(b"x"))


# -- invoke needs an invokable fact --------------------------------------------


def test_invoke_intent_without_evidence_is_unconstructible():
    with pytest.raises(errors.DomainError) as excinfo:
        build_invoke_action(make_source(), native_name="agent-a",
                            action_id="a", schema_version="v1",
                            invokable_evidence=())
    assert excinfo.value.code == errors.NATIVE_ENTRY_UNAVAILABLE
    with pytest.raises(errors.DomainError):  # a bare string is not evidence
        build_invoke_action(make_source(), native_name="agent-a",
                            action_id="a", schema_version="v1",
                            invokable_evidence="file-sighting")
    ok = build_invoke_action(make_source(), native_name="agent-a",
                             action_id="assets.native-subagents.invoke",
                             schema_version="v1",
                             invokable_evidence=("claude-control-tool-observed-at-pin",))
    assert isinstance(ok, InvokeAction)
    assert "claude-control-tool-observed-at-pin" in ok.expected_observation


# -- ownership: the host grants it, the builder only echoes it ------------------


def test_compile_all_requires_a_host_injected_source_and_never_invents_one():
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([make_item()], directory_context(), None, render=render)
    assert excinfo.value.code == errors.TARGET_CONFLICT
    assert "host" in excinfo.value.detail
    with pytest.raises(errors.DomainError):  # a bare string is not a source
        compile_all([make_item()], directory_context(), "assets.native-subagents",
                    render=render)


def test_source_cannot_claim_a_foreign_facet():
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([make_item()], directory_context(),
                    make_source(facet="assets.skills"), render=render)
    assert excinfo.value.code == errors.TARGET_CONFLICT
    assert "own facet" in excinfo.value.detail


def test_owner_is_structurally_unforgeable():
    # The contract's IntentSource has NO owner field — ownership is stamped by
    # the carrier outside the intent (C0: AuthorizedIntents(view.owner, …),
    # and intent_merge refuses any source ≠ the authorized submission).
    names = {f.name for f in dataclasses.fields(IntentSource)}
    assert names == {"facet_id", "item_id", "contribution_version"}
    set_ = compile_all([make_item()], directory_context(), make_source(),
                       render=render, native_names=frozenset())
    for intent in set_.intents:
        # the exact injected object is echoed, unchanged:
        assert intent.source.facet_id == FACET_ID
        assert intent.source.item_id == "def-1"
        for attr in dir(intent):
            assert "owner" not in attr.lower(), attr


# -- compile_all: complete collection, refusals before intents ------------------


def test_compile_all_produces_complete_sorted_real_set():
    items = [make_item("zed-agent", definition_id="d2"), make_item("alpha-agent")]
    set_ = compile_all(items, directory_context(), make_source(), render=render)
    assert [m.relative_name for m in set_.intents] == [
        "agents/alpha-agent.md", "agents/zed-agent.md",
    ]
    assert all(type(m) is MountContent for m in set_.intents)
    for mount in set_.intents:
        assert mount.target == HANDLE  # the host-issued handle, copied
        assert mount.mode == "read-only"
    # native_names not given -> the Unknown diagnostic is recorded OUTSIDE the
    # set (the real IntentSet has no diagnostics channel — SR gap list):
    assert discovery_diagnostics(None) and "unknown" in discovery_diagnostics(None)[0]
    assert discovery_diagnostics(frozenset()) == ()


def test_compile_all_refuses_a_path_shaped_host_handle():
    poisoned = directory_context(TargetHandle("assets/../etc", 1))
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([make_item()], poisoned, make_source(), render=render)
    assert excinfo.value.code == errors.TARGET_CONFLICT
    # capability: the same call with the clean handle compiles
    assert compile_all([make_item()], directory_context(), make_source(),
                       render=render, native_names=frozenset()).intents


def test_compile_all_requires_the_real_context_shape():
    for fake in ("~/.claude/agents", None, 3, [HANDLE]):
        with pytest.raises(errors.DomainError) as excinfo:
            compile_all([make_item()], fake, make_source(), render=render)
        assert excinfo.value.code == errors.TARGET_CONFLICT
    # a real AdapterContext without a content target also refuses:
    empty = AdapterContext((), Installation("claude", None, (0, 81, 2), "f"),
                           "acp", "instance", "fixture:cap")
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([make_item()], empty, make_source(), render=render)
    assert excinfo.value.code == errors.TARGET_CONFLICT


def test_compile_all_native_collision_diagnosed_before_intents():
    items = [make_item("code-reviewer")]
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all(items, directory_context(), make_source(), render=render,
                    native_names=frozenset({"code-reviewer", "other"}))
    assert excinfo.value.code == errors.NATIVE_NAME_CONFLICT
    assert excinfo.value.item_id == "code-reviewer"


def test_compile_all_duplicate_managed_names_refused():
    items = [make_item("same-name", definition_id="d1"),
             make_item("same-name", definition_id="d2")]
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all(items, directory_context(), make_source(), render=render)
    assert excinfo.value.code == errors.NATIVE_NAME_CONFLICT


def test_compile_all_refuses_retained_native_fields_never_drops():
    item = make_item(retained={"hooks": [{"cmd": "curl evil"}]})
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([item], directory_context(), make_source(), render=render)
    assert excinfo.value.code == errors.DEFINITION_INVALID
    assert "retained" in excinfo.value.detail
    assert "hooks" in excinfo.value.detail


def test_compile_all_refuses_credential_named_fields_never_carries():
    # FR05/G09: a definition declaring a credential stays REFUSED (not
    # silently converted into a BindSecret — a declaration is not a grant)…
    item = make_item(retained={"api_key": "sk-whatever"})
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([item], directory_context(), make_source(), render=render)
    assert excinfo.value.code == errors.DEFINITION_INVALID
    assert "credential" in excinfo.value.detail
    # …while a HOST-granted binding does route through the real BindSecret.
    ctx = AdapterContext(
        (TargetDescriptor(HANDLE, "directory", "content", "instance", (("agents",),)),
         TargetDescriptor(TargetHandle("assets.native-subagents.claude.environment", 3),
                          "environment", "environment", "instance",
                          (("provider_api_key",),))),
        Installation("claude", None, (0, 81, 2), "fixture:install"),
        "acp", "instance", "fixture:capability")
    set_ = compile_all([make_item()], ctx, make_source(), render=render,
                       native_names=frozenset(),
                       secret_bindings=(("provider_api_key", "vault-ref-9"),))
    kinds = {type(i) for i in set_.intents}
    assert kinds == {MountContent, BindSecret}
    binding = next(i for i in set_.intents if isinstance(i, BindSecret))
    assert binding.secret_ref == "vault-ref-9"  # opaque reference only
    # capability negative half: a binding with NO environment target refuses
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([make_item()], directory_context(), make_source(), render=render,
                    native_names=frozenset(),
                    secret_bindings=(("provider_api_key", "vault-ref-9"),))
    assert excinfo.value.code == errors.TARGET_CONFLICT


def test_compile_all_refuses_revision_without_source():
    item = make_item(with_source=False)
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([item], directory_context(), make_source(), render=render)
    assert "source approval" in excinfo.value.detail


def test_compile_all_enables_collection_cap():
    items = [make_item(f"agent-{i}", definition_id=f"d{i}") for i in range(65)]
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all(items, directory_context(), make_source(), render=render)
    assert "MAX_ENABLED_DEFINITIONS" in excinfo.value.detail


@pytest.mark.parametrize("bad_slug", ["Bad_Name", "-lead", ".dot", "a/b", "x" * 65, ""])
def test_compile_all_refuses_bad_agent_names(bad_slug: str):
    with pytest.raises(errors.DomainError) as excinfo:
        compile_all([make_item(bad_slug)], directory_context(), make_source(),
                    render=render)
    assert excinfo.value.code == errors.DEFINITION_INVALID


def test_compile_all_refuses_before_any_intent_on_second_item_failure():
    items = [make_item("good-one"), make_item(retained={"mcpServers": []})]
    with pytest.raises(errors.DomainError):
        compile_all(items, directory_context(), make_source(), render=render)
    # (the refusal is an exception: nothing was returned to apply)


def test_compile_all_requires_render_to_return_str():
    with pytest.raises(errors.DomainError):
        compile_all([make_item()], directory_context(), make_source(),
                    render=lambda item: 42)


def test_managed_item_typechecks():
    with pytest.raises(TypeError):
        ManagedItem("not-a-definition", "not-a-revision")
