from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

from ordessa_harness_api import (
    ContentRef, FieldPath, IntentSet, IntentSource, MountContent,
    RemoveOwnedContent, ResetField, SetField, TargetDescriptor, TargetHandle,
)
from ordessa_harness.materialization import (
    AuthorizedIntents, MaterializationError, MergeAuthority, OwnedContent,
    TargetAuthority, materialize_generation,
)


FILE = TargetHandle("config", 7)
DIR = TargetHandle("content", 7)
SOURCE = IntentSource("model", "item", "v1")


def make_root(path):
    path.mkdir()
    path.chmod(0o700)
    return path


def authority(*, owned=(), codec="json"):
    return MergeAuthority((
        TargetAuthority(TargetDescriptor(FILE, "file", codec, "instance",
                                         (("model",), ("old",)), ("remove-key",)),
                        ("private", "settings.json")),
        TargetAuthority(TargetDescriptor(DIR, "directory", "content", "instance"),
                        ("private", "skills")),
    ), owned_content=owned)


def submit(*intents, owner="owner.a"):
    return (AuthorizedIntents(owner, "model", "item", "v1", IntentSet(intents)),)


def test_complete_private_generation_json_set_reset_mount_remove_and_home_unchanged(tmp_path):
    root = tmp_path / "instance"
    make_root(root)
    home = tmp_path / "home" / "settings.json"
    home.parent.mkdir()
    home.write_bytes(b'{"global":true}\n')
    before = home.read_bytes()
    payload = b"skill bytes"
    digest = hashlib.sha256(payload).hexdigest()
    plan = materialize_generation(
        root, authority(owned=(OwnedContent(DIR, ("private", "skills"), "old.txt", "owner.a"),)),
        submit(SetField(SOURCE, FILE, FieldPath(("model",)), "fixture"),
               ResetField(SOURCE, FILE, FieldPath(("old",)), "remove-key"),
               RemoveOwnedContent(SOURCE, DIR, "old.txt"),
               MountContent(SOURCE, DIR, "new.txt", ContentRef("ref:new", digest, len(payload)), "read-only")),
        snapshot={("private", "settings.json"): b'{"old":1,"keep":true}',
                  ("private", "skills", "old.txt"): b"old"},
        content={"ref:new": payload},
    )
    assert plan.generation_name.startswith("gen-")
    assert json.loads(plan.read_bytes(("private", "settings.json"))) == {"keep": True, "model": "fixture"}
    assert plan.read_bytes(("private", "skills", "new.txt")) == payload
    with pytest.raises(MaterializationError, match="manifest"):
        plan.read_bytes(("private", "skills", "old.txt"))
    assert home.read_bytes() == before
    assert sorted(path.name for path in root.iterdir()) == [plan.generation_name]
    assert stat.S_IMODE(os.fstat(plan.fileno()).st_mode) == 0o700
    assert stat.S_IMODE((root / plan.generation_name / "private" / "settings.json").stat().st_mode) == 0o600
    plan.close()


@pytest.mark.parametrize("bad_content", [b"wrong", b"too long"])
def test_content_preflight_fails_before_any_generation_write(tmp_path, bad_content):
    root = tmp_path / "instance"
    make_root(root)
    good = b"good"
    intent = MountContent(SOURCE, DIR, "new.txt", ContentRef("ref:new", hashlib.sha256(good).hexdigest(), len(good)), "read-only")
    with pytest.raises(MaterializationError, match="digest mismatch"):
        materialize_generation(root, authority(), submit(intent), snapshot={}, content={"ref:new": bad_content})
    assert list(root.iterdir()) == []


def test_unsupported_reset_rule_refuses_before_writes(tmp_path):
    root = tmp_path / "instance"
    make_root(root)
    with pytest.raises(ValueError, match="baseline rule"):
        materialize_generation(root, authority(codec="toml"),
                               submit(ResetField(SOURCE, FILE, FieldPath(("old",)), "native-default")), snapshot={})
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(("codec", "suffix", "before", "expected"), [
    ("toml", "toml", b'old = 1\n[keep]\nflag = true\n',
     {'keep': {'flag': True}, 'model': {'selected': 'fixture'}}),
    ("yaml", "yaml", b'old: 1\nkeep:\n  flag: true\n',
     {'keep': {'flag': True}, 'model': {'selected': 'fixture'}}),
])
def test_structured_set_reset_preserves_unclaimed_nested_values(tmp_path, codec, suffix, before, expected):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    resource = ("private", f"settings.{suffix}")
    target = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", codec, "instance", (("model", "selected"), ("old",)), ("remove-key",)), resource),))
    lease = materialize_generation(root, target, submit(
        SetField(SOURCE, FILE, FieldPath(("model", "selected")), "fixture"),
        ResetField(SOURCE, FILE, FieldPath(("old",)), "remove-key")), snapshot={resource: before})
    try:
        assert module._document(codec, lease.read_bytes(resource)) == expected
        assert sorted(path.name for path in root.iterdir()) == [lease.generation_name]
    finally:
        lease.close()


@pytest.mark.parametrize("literal", ["on", "off", "yes", "no", "012"])
def test_yaml_12_ambiguous_implicit_scalar_remains_unclaimed_string(tmp_path, literal):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    resource = ("private", "settings.yaml")
    target = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", "yaml", "instance", (("model",),)), resource),))
    lease = materialize_generation(root, target,
        submit(SetField(SOURCE, FILE, FieldPath(("model",)), "selected")),
        snapshot={resource: f"keep: {literal}\n".encode()})
    try:
        assert module._document("yaml", lease.read_bytes(resource))["keep"] == literal
    finally:
        lease.close()


def test_yaml_12_core_numeric_scalars_keep_their_types(tmp_path):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    resource = ("private", "settings.yaml")
    target = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", "yaml", "instance", (("model",),)), resource),))
    lease = materialize_generation(root, target,
        submit(SetField(SOURCE, FILE, FieldPath(("model",)), "selected")),
        snapshot={resource: b"count: 0x12\nratio: 1e3\n"})
    try:
        document = module._document("yaml", lease.read_bytes(resource))
        assert document["count"] == 18 and type(document["count"]) is int
        assert document["ratio"] == 1000.0 and type(document["ratio"]) is float
    finally:
        lease.close()


@pytest.mark.parametrize(("codec", "suffix", "snapshot"), [
    ("toml", "toml", b"keep = 2026-09-28\n"),
    ("yaml", "yaml", b"keep: 2026-09-28\n"),
])
def test_native_date_snapshot_refuses_before_writes(tmp_path, codec, suffix, snapshot):
    root = make_root(tmp_path / "instance")
    resource = ("private", f"settings.{suffix}")
    target = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", codec, "instance", (("model",),)), resource),))
    with pytest.raises(MaterializationError, match="unsupported value"):
        materialize_generation(root, target,
            submit(SetField(SOURCE, FILE, FieldPath(("model",)), "selected")),
            snapshot={resource: snapshot})
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(("codec", "suffix", "before"), [
    ("toml", "toml", b'model = "scalar"\n'),
    ("yaml", "yaml", b'model: scalar\n'),
])
def test_structured_nested_scalar_conflict_refuses_before_writes(tmp_path, codec, suffix, before):
    root = make_root(tmp_path / "instance")
    resource = ("private", f"settings.{suffix}")
    target = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", codec, "instance", (("model", "selected"),)), resource),))
    with pytest.raises(MaterializationError, match="field parent"):
        materialize_generation(root, target,
                               submit(SetField(SOURCE, FILE, FieldPath(("model", "selected")), "x")),
                               snapshot={resource: before})
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(("codec", "suffix", "before"), [
    ("toml", "toml", b'model = [\n'),
    ("yaml", "yaml", b'model: [\n'),
    ("yaml", "yaml", b'model: first\nmodel: second\n'),
    ("yaml", "yaml", b'first: &item {nested: value}\nmodel: *item\n'),
    ("yaml", "yaml", b'model: !!python/object/apply:os.system ["true"]\n'),
])
def test_invalid_structured_snapshot_refuses_before_writes(tmp_path, codec, suffix, before):
    root = make_root(tmp_path / "instance")
    resource = ("private", f"settings.{suffix}")
    target = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", codec, "instance", (("model",),)), resource),))
    with pytest.raises(MaterializationError):
        materialize_generation(root, target, submit(), snapshot={resource: before})
    assert list(root.iterdir()) == []


def test_toml_unrepresentable_null_refuses_before_writes(tmp_path):
    root = make_root(tmp_path / "instance")
    with pytest.raises(MaterializationError, match="represented as TOML"):
        materialize_generation(root, authority(codec="toml"),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), None)), snapshot={})
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("codec", ["json", "toml", "yaml"])
def test_symlink_root_or_parent_and_traversal_refused(tmp_path, codec):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    intents = submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x"))
    for unsafe in (link, link / "child", tmp_path / "missing" / ".." / "actual"):
        with pytest.raises(MaterializationError):
            materialize_generation(unsafe, authority(codec=codec), intents, snapshot={})
    assert list(actual.iterdir()) == []


def test_group_writable_root_refused(tmp_path):
    root = tmp_path / "instance"
    root.mkdir(mode=0o770)
    root.chmod(0o770)
    with pytest.raises(MaterializationError, match="group/world writable"):
        materialize_generation(root, authority(),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")), snapshot={})
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("codec", ["json", "toml", "yaml"])
def test_root_replacement_before_publish_refuses_and_cleans_candidate(tmp_path, monkeypatch, codec):
    import ordessa_harness.materialization.private_generation as module

    root = tmp_path / "instance"
    make_root(root)
    original = module._write_candidate

    def replace(rootfd, candidate, files):
        result = original(rootfd, candidate, files)
        root.rename(tmp_path / "moved")
        make_root(root)
        return result

    monkeypatch.setattr(module, "_write_candidate", replace)
    with pytest.raises(MaterializationError, match="root replaced"):
        materialize_generation(root, authority(codec=codec),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")), snapshot={})
    assert list(root.iterdir()) == []
    assert list((tmp_path / "moved").iterdir()) == []


def test_remove_other_owner_refuses_before_private_write(tmp_path):
    root = tmp_path / "instance"
    make_root(root)
    with pytest.raises(ValueError, match="owned content"):
        materialize_generation(root,
                               authority(owned=(OwnedContent(DIR, ("private", "skills"), "old.txt", "owner.b"),)),
                               submit(RemoveOwnedContent(SOURCE, DIR, "old.txt")),
                               snapshot={("private", "skills", "old.txt"): b"old"})
    assert list(root.iterdir()) == []


def test_second_file_write_failure_cannot_publish_half_generation(tmp_path, monkeypatch):
    import ordessa_harness.materialization.private_generation as module

    root = tmp_path / "instance"
    make_root(root)
    original = module._write_candidate

    def interrupted(rootfd, candidate, files):
        first = dict(list(sorted(files.items()))[:1])
        original(rootfd, candidate, first)
        raise OSError("injected second-file write failure")

    monkeypatch.setattr(module, "_write_candidate", interrupted)
    with pytest.raises(OSError, match="second-file"):
        materialize_generation(root, authority(),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")),
                               snapshot={("private", "skills", "old.txt"): b"old"})
    assert list(root.iterdir()) == []


def test_invalid_untouched_json_snapshot_refuses_before_writes(tmp_path):
    root = tmp_path / "instance"
    make_root(root)
    with pytest.raises(MaterializationError, match="invalid JSON"):
        materialize_generation(root, authority(), submit(),
                               snapshot={("private", "settings.json"): b"{"})
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("owned", [(), (OwnedContent(DIR, ("private", "skills"), "new.txt", "owner.b"),)])
def test_mount_cannot_replace_unowned_or_other_owner_content(tmp_path, owned):
    root = make_root(tmp_path / "instance")
    payload = b"replacement"
    intent = MountContent(SOURCE, DIR, "new.txt",
                          ContentRef("ref:new", hashlib.sha256(payload).hexdigest(), len(payload)), "read-only")
    with pytest.raises(MaterializationError, match="replace.*ownership"):
        materialize_generation(root, authority(owned=owned), submit(intent),
                               snapshot={("private", "skills", "new.txt"): b"original"},
                               content={"ref:new": payload})
    assert list(root.iterdir()) == []


def test_mount_may_replace_content_with_same_owner_snapshot(tmp_path):
    root = make_root(tmp_path / "instance")
    payload = b"replacement"
    intent = MountContent(SOURCE, DIR, "new.txt",
                          ContentRef("ref:new", hashlib.sha256(payload).hexdigest(), len(payload)), "read-only")
    published = materialize_generation(
        root, authority(owned=(OwnedContent(DIR, ("private", "skills"), "new.txt", "owner.a"),)),
        submit(intent), snapshot={("private", "skills", "new.txt"): b"original"},
        content={"ref:new": payload})
    assert published.read_bytes(("private", "skills", "new.txt")) == payload
    published.close()


def test_null_ancestor_is_not_silently_replaced_by_object(tmp_path):
    root = make_root(tmp_path / "instance")
    nested = MergeAuthority((TargetAuthority(TargetDescriptor(
        FILE, "file", "json", "instance", (("model", "selected"),),
    ), ("private", "settings.json")),))
    intent = SetField(SOURCE, FILE, FieldPath(("model", "selected")), "x")
    with pytest.raises(MaterializationError, match="field parent"):
        materialize_generation(root, nested, submit(intent),
                               snapshot={("private", "settings.json"): b'{"model":null}'})
    assert list(root.iterdir()) == []


def test_candidate_symlink_swap_before_rename_cannot_publish_attacker_tree(tmp_path, monkeypatch):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "marker").write_bytes(b"attacker")
    original = module._write_candidate

    def swap(rootfd, candidate, files):
        result = original(rootfd, candidate, files)
        os.rename(candidate, "stolen-candidate", src_dir_fd=rootfd, dst_dir_fd=rootfd)
        os.symlink(attacker, candidate, dir_fd=rootfd)
        return result

    monkeypatch.setattr(module, "_write_candidate", swap)
    with pytest.raises(MaterializationError, match="candidate"):
        materialize_generation(root, authority(),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")), snapshot={})
    assert not any(path.name.startswith("gen-") for path in root.iterdir())
    assert (attacker / "marker").read_bytes() == b"attacker"


def test_candidate_directory_swap_is_quarantined_without_deleting_foreign_bytes(tmp_path, monkeypatch):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    foreign = root / "foreign"
    foreign.mkdir()
    (foreign / "marker").write_bytes(b"foreign")
    original = module._write_candidate

    def swap(rootfd, candidate, files):
        result = original(rootfd, candidate, files)
        os.rename(candidate, "stolen-candidate", src_dir_fd=rootfd, dst_dir_fd=rootfd)
        os.rename("foreign", candidate, src_dir_fd=rootfd, dst_dir_fd=rootfd)
        return result

    monkeypatch.setattr(module, "_write_candidate", swap)
    with pytest.raises(MaterializationError, match="candidate"):
        materialize_generation(root, authority(),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")), snapshot={})
    assert not any(path.name.startswith("gen-") for path in root.iterdir())
    rejected = [path for path in root.iterdir() if path.name.startswith(".rejected-")]
    assert len(rejected) == 1 and (rejected[0] / "marker").read_bytes() == b"foreign"


def test_post_rename_byte_mutation_is_detected_and_generation_removed(tmp_path, monkeypatch):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    original = module.os.rename

    def corrupt(source, destination, *, src_dir_fd=None, dst_dir_fd=None):
        original(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if destination.startswith("gen-"):
            (root / destination / "private" / "settings.json").write_bytes(b'{"model":"corrupt"}')

    monkeypatch.setattr(module.os, "rename", corrupt)
    with pytest.raises(MaterializationError, match="candidate bytes"):
        materialize_generation(root, authority(),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")), snapshot={})
    assert list(root.iterdir()) == []


def test_post_scan_name_swap_is_refused_without_returning_swapped_path(tmp_path, monkeypatch):
    import ordessa_harness.materialization.private_generation as module

    root = make_root(tmp_path / "instance")
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "marker").write_bytes(b"attacker")
    original = module._verify_files

    def swap_after_scan(candidatefd, files):
        original(candidatefd, files)
        name, = (entry.name for entry in root.iterdir() if entry.name.startswith("gen-"))
        (root / name).rename(root / "stolen")
        (root / name).symlink_to(attacker, target_is_directory=True)

    monkeypatch.setattr(module, "_verify_files", swap_after_scan)
    with pytest.raises(MaterializationError, match="candidate"):
        materialize_generation(root, authority(),
                               submit(SetField(SOURCE, FILE, FieldPath(("model",)), "x")), snapshot={})
    assert not any(entry.name.startswith("gen-") for entry in root.iterdir())
    assert (attacker / "marker").read_bytes() == b"attacker"


def test_returned_lease_stays_bound_after_generation_name_is_replaced(tmp_path):
    root = make_root(tmp_path / "instance")
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "private").mkdir()
    (attacker / "private" / "settings.json").write_bytes(b'{"model":"attacker"}')
    lease = materialize_generation(root, authority(),
                                   submit(SetField(SOURCE, FILE, FieldPath(("model",)), "real")), snapshot={})
    try:
        (root / lease.generation_name).rename(root / "stolen")
        (root / lease.generation_name).symlink_to(attacker, target_is_directory=True)
        assert json.loads(lease.read_bytes(("private", "settings.json"))) == {"model": "real"}
        assert not hasattr(lease, "root")
    finally:
        lease.close()


def test_returned_lease_refuses_mutated_file_bytes(tmp_path):
    root = make_root(tmp_path / "instance")
    lease = materialize_generation(root, authority(),
                                   submit(SetField(SOURCE, FILE, FieldPath(("model",)), "real")), snapshot={})
    try:
        (root / lease.generation_name / "private" / "settings.json").write_bytes(b'{"model":"tampered"}')
        with pytest.raises(MaterializationError, match="bytes changed"):
            lease.read_bytes(("private", "settings.json"))
    finally:
        lease.close()
