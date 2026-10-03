"""Compile-input & published-intent boundaries: no absolute host paths,
one-shot sets only, ONE vocabulary.

contracts.md §Harness 配置贡献: the payload references managed content
coordinates + the frozen generation bounds, and "由 Harness 从自身私有内容
装载目标操作,不信适配器给任意绝对路径". Since the harness-api checkpoint
these tests run against the PUBLISHED `ordessa_harness_api` intent types:
the interim Skills-side vocabulary this file used to pin is deleted, and
what remains provable is (a) the adapter-side sweep refuses host-path
smuggling BEFORE a DTO exists, (b) the published DTOs' own checks refuse
the shapes they check, and (c) compile emits one complete set of real
`MountContent` intents (no per-skill incremental edit verbs).
"""
from __future__ import annotations

import json

import pytest

from ordessa_harness_api import (
    ContentRef, ContractError, IntentSet, MountContent, RemoveOwnedContent,
)
from ordessa_skills.harness_adapters import pi
from ordessa_skills.harness_adapters.base import (
    AdapterTarget, SKILLS_FACET_ID, content_ref_for, mount_content_for,
    preview_target_handle,
)
from ordessa_skills.harness_adapters.intent import (
    GenerationBounds, ManagedContentRef, SkillIntentError,
    looks_like_absolute_host_path, sweep_host_path_free,
)

DIGEST = "sha256:" + "a" * 64
BOUNDS = GenerationBounds("gen-7", "proj-ordessa", 3, 11)


def _ref(asset_id: str = "demo-skill", revision: int = 1,
         name: str = "demo-skill", size: int | None = 128) -> ManagedContentRef:
    return ManagedContentRef(asset_id=asset_id, revision=revision,
                             tree_digest=DIGEST, native_name=name,
                             size_bytes=size)


def _target() -> AdapterTarget:
    return AdapterTarget("pi", "0.84.2", "0.5.0", "acp")


def _handle():
    return preview_target_handle("pi", BOUNDS)


# -- absolute host paths are refused at our sweep, before any DTO --------------

@pytest.mark.parametrize("slot", [
    "/runtime/home/skills",              # POSIX absolute
    "/home/user/.claude/skills",         # the very path the design forbids
    "~/skills",                          # home-relative
    "C:\\Users\\me\\skills",             # Windows drive
    "C:/Users/me/skills",                # Windows drive, forward slashes —
    #                                        NOT caught by the published
    #                                        `_relative_name`; the sweep must
    "\\\\host\\share\\skills",           # UNC
    "file:///etc/skills",                # URL with an absolute target
])
def test_a_mount_target_that_looks_like_an_absolute_host_path_is_refused(slot):
    with pytest.raises(SkillIntentError) as exc:
        mount_content_for(_ref(), _handle(), slot=slot)
    assert exc.value.code == "SKILL_INTENT_HOST_PATH"


def test_bounds_carry_bounded_tokens_not_paths():
    for bad in ("/home/maoqh", "~/.config", "file:///srv/gen"):
        with pytest.raises(SkillIntentError) as exc:
            GenerationBounds(bad, "proj-ordessa", 3, 11)
        assert exc.value.code == "SKILL_INTENT_HOST_PATH"
        with pytest.raises(SkillIntentError):
            GenerationBounds("gen-7", bad, 3, 11)


def test_content_coordinates_refuse_smuggled_paths():
    with pytest.raises(SkillIntentError):
        ManagedContentRef("/etc/skills", 1, DIGEST, "demo-skill")
    with pytest.raises(SkillIntentError):
        ManagedContentRef("demo-skill", 1, DIGEST, "../escape")


def test_the_published_dto_checks_reject_the_shapes_they_check():
    # The published types are the vocabulary now; their own guards apply:
    # MountContent/RemoveOwnedContent relative names must be clean-relative,
    # and ContentRef digests must be bare lowercase sha256 hex.
    with pytest.raises(ContractError):
        mount = mount_content_for(_ref(), _handle(), slot="skills")
        # tamper is impossible on a frozen DTO — construct the bad shape:
        from ordessa_harness_api import IntentSource, TargetHandle
        MountContent(source=IntentSource(SKILLS_FACET_ID, "x", "r1"),
                     target=TargetHandle("h", 0), relative_name="../escape",
                     immutable_content_ref=mount.immutable_content_ref,
                     mode="read-only")
    with pytest.raises(ContractError):
        ContentRef(reference="x", sha256="not-a-digest", size=1)


def test_traversal_and_empty_slots_never_yield_a_mount():
    # The published DTO rejects traversal/leading-slash shapes; the sweep
    # catches the absolute-looking ones first. Either way NO mount object
    # is ever constructed for these slot labels.
    from ordessa_harness_api import IntentSource, TargetHandle
    for bad in ("skills/../../etc", "", "//", "skills//x"):
        with pytest.raises((SkillIntentError, ContractError)):
            intent = mount_content_for(_ref(), _handle(), slot=bad)
            # empty slot produces "/demo" (absolute-shaped) → sweep;
            # traversal reaches the published `_relative_name` check.
            assert isinstance(intent, MountContent)
        with pytest.raises(ContractError):
            MountContent(source=IntentSource(SKILLS_FACET_ID, "x", "r1"),
                         target=TargetHandle("h", 0), relative_name=bad,
                         immutable_content_ref=content_ref_for(_ref()),
                         mode="read-only") if bad else _skip()


def _skip():
    # placeholder to keep the parametrised shape honest: an empty relative
    # name is refused by the published `_id` check.
    from ordessa_harness_api import IntentSource, TargetHandle
    MountContent(source=IntentSource(SKILLS_FACET_ID, "x", "r1"),
                 target=TargetHandle("h", 0), relative_name="",
                 immutable_content_ref=content_ref_for(_ref()),
                 mode="read-only")


def test_the_detector_itself_is_precise():
    assert looks_like_absolute_host_path("/a")
    assert not looks_like_absolute_host_path(".claude/skills")
    assert not looks_like_absolute_host_path("skills")
    assert not looks_like_absolute_host_path(DIGEST)


def test_a_content_ref_never_fabricates_a_size():
    with pytest.raises(SkillIntentError) as exc:
        content_ref_for(_ref(size=None))
    assert exc.value.code == "SKILL_INTENT_CONTENT_SIZE_UNKNOWN"


# -- compiled sets are complete, path-free, and published ----------------------

def _compile(refs):
    return pi.compile(refs, _target(), bounds=BOUNDS)


def test_compile_is_one_shot_for_the_whole_resolved_collection():
    refs = [_ref("alpha", 1, "alpha"), _ref("beta", 2, "beta"),
            _ref("gamma", 3, "gamma")]
    compiled = _compile(refs)
    assert isinstance(compiled.intents, IntentSet)
    mounts = [i for i in compiled.intents.intents if isinstance(i, MountContent)]
    assert len(mounts) == 3
    # One complete declaration: every intent is a whole-set mount; there is
    # no per-skill incremental edit verb in the vocabulary at all.
    assert {type(item).__name__ for item in compiled.intents.intents} == \
        {"MountContent"}
    assert {item.source.item_id for item in mounts} == {"alpha", "beta", "gamma"}


def test_serialized_intent_set_contains_no_absolute_host_path_anywhere():
    compiled = _compile([_ref()])
    payload = compiled.public_dict()
    blob = json.dumps(payload)
    assert "/runtime/home" not in blob
    assert "/home/" not in blob

    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from strings(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                yield from strings(item)

    assert not [s for s in strings(payload) if looks_like_absolute_host_path(s)]


def test_intents_reference_only_the_coordinates_plus_bounds():
    compiled = _compile([_ref()])
    mount = compiled.intents.intents[0]
    assert isinstance(mount, MountContent)
    # ContentRef carries the content coordinates: assetId@revision reference,
    # the tree digest as bare hex, and the real byte size.
    assert mount.immutable_content_ref.reference == "demo-skill@1"
    assert mount.immutable_content_ref.sha256 == "a" * 64
    assert mount.immutable_content_ref.size == 128
    # provenance names the facet + item + contribution revision:
    assert mount.source.facet_id == SKILLS_FACET_ID == "assets.skills"
    assert mount.source.item_id == "demo-skill"
    assert mount.source.contribution_version == "r1"
    # the generation face rides with the projection (published-side: the
    # ApplicationTarget + plan revision fences):
    bound_fields = {"runtime_generation", "project_id",
                    "profile_revision", "assignment_revision"}
    assert {f for f in vars(compiled.bounds)} == bound_fields
    # and the preview handle binds exactly that frozen face:
    assert mount.target.handle_id == (
        "skills-preview:pi:gen-7:proj-ordessa:pr3:ar11")


def test_bounded_identifiers_reject_oversized_values():
    with pytest.raises(SkillIntentError):
        GenerationBounds("gen-" + "x" * 200, "proj", 1, 1)


def test_digest_shape_is_pinned():
    with pytest.raises(SkillIntentError):
        ManagedContentRef("demo-skill", 1, "not-a-digest", "demo-skill")


def test_removals_are_published_remove_owned_content():
    compiled = pi.compile([], _target(), bounds=BOUNDS,
                          removals=[_ref("gone-skill", 2, "gone-skill")])
    (intent,) = compiled.intents.intents
    assert isinstance(intent, RemoveOwnedContent)
    assert intent.relative_name == "skills/gone-skill"
