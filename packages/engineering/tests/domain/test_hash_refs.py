from dataclasses import FrozenInstanceError

import pytest

from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.changes.baselines import (RepositorySnapshotRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.mechanisms.hashing import (record_digest)


def revision(identifier="D3", digest="a" * 64, realm="realm", project="project"):
    return ArtifactRevisionRef(realm, project, "design", identifier, Digest("sha256", digest))


def test_batch_target_order_is_canonical_but_roles_are_distinct():
    base, proposed = Target("base", revision()), Target("proposed", revision("D4", "b" * 64))
    left, right = TargetSet((base, proposed)), TargetSet((proposed, base))
    assert left == right and left.digest == right.digest
    assert left.digest != TargetSet((Target("primary", revision()),)).digest
    with pytest.raises(FrozenInstanceError):
        left.targets = ()


def test_two_versions_of_same_logical_role_cannot_hide_in_batch():
    with pytest.raises(ReferenceError, match="DUPLICATE_TARGET"):
        TargetSet((Target("base", revision()), Target("base", revision("D4", "b" * 64))))


@pytest.mark.parametrize("realm,project", [("foreign", "project"), ("realm", "foreign")])
def test_cross_scope_target_is_rejected(realm, project):
    with pytest.raises(ReferenceError, match="REALM_MISMATCH"):
        TargetSet((Target("base", revision()), Target("proposed", revision("D4", realm=realm, project=project))))


def test_method_release_and_schema_version_are_separate_and_strict():
    ref = MethodRef("incremental", "1.2.0", 1, Digest("sha256", "a" * 64))
    assert ref.release_version == "1.2.0" and ref.schema_version == 1
    for value in [0, True, "1"]:
        with pytest.raises(ReferenceError):
            MethodRef("incremental", "1.2.0", value, ref.snapshot_digest)


def test_repository_commit_and_dirty_content_are_independent_identity():
    digest = Digest("sha256", "a" * 64)
    clean = RepositorySnapshotRef("realm", "project", "repo", "git", "b" * 40, digest, None)
    dirty = RepositorySnapshotRef("realm", "project", "repo", "git", "b" * 40, digest, Digest("sha256", "c" * 64))
    assert TargetSet((Target("base", clean),)).digest != TargetSet((Target("base", dirty),)).digest
    with pytest.raises(ReferenceError):
        RepositorySnapshotRef("realm", "project", "repo", "none", "b" * 40, digest, None)


def test_domain_hash_prefix_is_owner_specific_and_preserves_bytes():
    value = {"body": "设计\r\n", "version": 1}
    assert record_digest("artifact-revision", value) != record_digest("proposal", value)
    assert record_digest("proposal", value) != record_digest("proposal", {**value, "body": "设计\n"})
