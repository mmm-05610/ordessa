from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ordessa_harness_api import (
    ActionDescriptor, BindSecret, ContentRef, FieldPath, IntentSet,
    IntentSource, InvokeAction, MountContent, RemoveOwnedContent, ResetField,
    SetField, TargetDescriptor, TargetHandle, ValueSchema,
)
from ordessa_harness.materialization import (
    AuthorizedIntents, IntentMergeError, MergeAuthority, OwnedContent, TargetAuthority,
    merge_intents,
)


def source(facet="model", item="one"):
    return IntentSource(facet, item, "v1")


FILE = TargetHandle("config", 3)
DIR = TargetHandle("content", 3)
ENV = TargetHandle("env", 3)


def authority(*, array=False, owned=()):
    return MergeAuthority((
        TargetAuthority(TargetDescriptor(FILE, "file", "json", "instance",
                                         (("model",), ("theme",), ("items",)),
                                         ("remove-key",)), ("cfg", "settings.json"),
                        (("items",),) if array else ()),
        TargetAuthority(TargetDescriptor(DIR, "directory", "content", "instance"), ("cfg",)),
        TargetAuthority(TargetDescriptor(ENV, "environment", "environment", "instance", (("API_KEY",),)), ("process", "env")),
    ), (ActionDescriptor("reload", "v1", ValueSchema("object"), ValueSchema("object"), "instance", "protocol-ack", True),), owned_content=owned)


def batch(owner, facet, *intents, item="one", version="v1"):
    return AuthorizedIntents(owner, facet, item, version, IntentSet(intents))


def model(value="a", facet="model", field="model"):
    return SetField(source(facet), FILE, FieldPath((field,)), value)


def test_disjoint_facets_one_json_file_and_permutation_have_same_immutable_plan():
    left = batch("owner.model", "model", model())
    right = batch("owner.theme", "theme", model("dark", "theme", "theme"))
    first = merge_intents(authority(), (left, right))
    second = merge_intents(authority(), (right, left))
    assert first == second
    assert [(item.owner, item.facet_id, item.field, item.detail) for item in first.intents] == [
        ("owner.model", "model", ("model",), '"a"'),
        ("owner.theme", "theme", ("theme",), '"dark"'),
    ]
    with pytest.raises(FrozenInstanceError):
        first.intents[0].owner = "forged"


@pytest.mark.parametrize("other", [
    lambda: model("a", "theme"),
    lambda: ResetField(source("theme"), FILE, FieldPath(("model",)), "remove-key"),
])
def test_equal_value_and_set_reset_claims_conflict_even_across_facets(other):
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(authority(), (batch("one", "model", model()), batch("two", "theme", other())))


def test_ancestor_descendant_and_array_subtree_contention():
    root = SetField(source(), FILE, FieldPath(("items",)), [1, 2])
    child = SetField(source("skills"), FILE, FieldPath(("items", "0")), "x")
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(authority(array=True), (batch("one", "model", root), batch("two", "skills", child)))
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(authority(array=True), (
            batch("one", "model", SetField(source(), FILE, FieldPath(("items", "0")), "x")),
            batch("two", "skills", child),
        ))
    accepted = merge_intents(authority(array=True), (batch("one", "model", SetField(source(), FILE, FieldPath(("items", "0")), "x")),))
    assert accepted.intents[0].field == ("items", "0")


def test_array_descendant_cannot_narrow_ancestor_claim():
    nested = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", "json", "instance",
        (("items",), ("items", "children"), ("items", "other")),
    ), ("cfg", "settings.json"), (("items", "children"),)),))
    ancestor = SetField(source(), FILE, FieldPath(("items",)), {"children": [], "other": 1})
    sibling = SetField(source("theme"), FILE, FieldPath(("items", "other")), 2)
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(nested, (batch("one", "model", ancestor), batch("two", "theme", sibling)))


def test_nested_array_declaration_order_cannot_split_outer_array_claim():
    nested = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", "json", "instance",
        (("items",), ("items", "a"), ("items", "b")),
    ), ("cfg", "settings.json"),
        (("items", "a"), ("items", "b"), ("items",))),))
    left = SetField(source(), FILE, FieldPath(("items", "a", "0")), "a")
    right = SetField(source("theme"), FILE, FieldPath(("items", "b", "0")), "b")
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(nested, (batch("one", "model", left), batch("two", "theme", right)))


def test_mount_remove_and_file_directory_overlap():
    ref = ContentRef("sha256:fixture", "0" * 64, 1)
    mount = MountContent(source(), DIR, "settings.json", ref, "read-only")
    remove = RemoveOwnedContent(source("skills"), DIR, "settings.json")
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(authority(owned=(OwnedContent(DIR, ("cfg",), "settings.json", "two"),)),
                      (batch("one", "model", mount), batch("two", "skills", remove)))
    with pytest.raises(IntentMergeError, match="overlapping"):
        merge_intents(authority(), (batch("one", "model", mount), batch("two", "model", model())))
    owned = (OwnedContent(DIR, ("cfg",), "skills/b", "two"),)
    accepted = merge_intents(authority(owned=owned), (
        batch("one", "model", MountContent(source(), DIR, "skills/a", ref, "read-only")),
        batch("two", "skills", RemoveOwnedContent(source("skills"), DIR, "skills/b")),
    ))
    assert {item.kind for item in accepted.intents} == {"mount-content", "remove-owned-content"}


def test_remove_requires_server_ownership_snapshot_with_matching_owner():
    remove = RemoveOwnedContent(source(), DIR, "skills/b")
    with pytest.raises(IntentMergeError, match="owned content"):
        merge_intents(authority(), (batch("two", "model", remove),))
    with pytest.raises(IntentMergeError, match="owned content"):
        merge_intents(authority(owned=(OwnedContent(DIR, ("cfg",), "skills/b", "one"),)),
                      (batch("two", "model", remove),))
    assert merge_intents(authority(owned=(OwnedContent(DIR, ("cfg",), "skills/b", "two"),)),
                         (batch("two", "model", remove),)).intents[0].kind == "remove-owned-content"
    with pytest.raises(IntentMergeError, match="stale"):
        authority(owned=(OwnedContent(TargetHandle("content", 2), ("cfg",), "skills/b", "two"),))
    with pytest.raises(IntentMergeError, match="stale"):
        authority(owned=(OwnedContent(DIR, ("wrong",), "skills/b", "two"),))


def test_secret_and_action_admission_with_no_execution():
    secret = BindSecret(source(), ENV, "API_KEY", "vault:fixture")
    action = InvokeAction(source(), "reload", "v1", {}, "ack")
    plan = merge_intents(authority(), (batch("one", "model", secret, action),))
    assert [item.kind for item in plan.intents] == ["bind-secret", "invoke-action"]
    assert plan.intents[0].detail == "vault:fixture"
    with pytest.raises(IntentMergeError, match="duplicate secret slot"):
        merge_intents(authority(), (batch("one", "model", secret), batch("two", "model", secret)))
    with pytest.raises(IntentMergeError, match="duplicate action"):
        merge_intents(authority(), (batch("one", "model", action), batch("two", "model", action)))


@pytest.mark.parametrize("bad, message", [
    (SetField(source(), TargetHandle("config", 2), FieldPath(("model",)), "x"), "stale"),
    (model("x", field="unknown"), "unauthorized field"),
    (ResetField(source(), FILE, FieldPath(("model",)), "native-default"), "baseline"),
    (BindSecret(source(), ENV, "OTHER", "vault:x"), "secret slot"),
    (InvokeAction(source(), "unlisted", "v1", {}, "ack"), "unauthorized action"),
    (InvokeAction(source(), "reload", "v1", [1], "ack"), "action payload"),
    (SetField(source("wrong"), FILE, FieldPath(("model",)), "x"), "source facet"),
    (SetField(source(item="forged"), FILE, FieldPath(("model",)), "x"), "source item"),
    (SetField(IntentSource("model", "one", "v2"), FILE, FieldPath(("model",)), "x"), "source version"),
])
def test_invalid_admission_refused(bad, message):
    with pytest.raises(IntentMergeError, match=message):
        merge_intents(authority(), (batch("owner", "model", bad),))
