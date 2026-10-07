"""CAS + operation-key guard on the binding writes (requirement 2c).

data-model.md §内容与版本: 更新已启用范围时明确挑选目标修订并写 CAS/操作键；
重试不能重复升级. contracts.md assigns/upsert carry `expectedVersion` +
`operationKey`.

The CAS *table* is the assignments slice's (T05); here it is the injected
`library.records.BindingCasPort`, so these tests pin the protocol contract the
T05 implementation has to satisfy — and pin that the **legacy unguarded shape
still works unchanged** (wire-compat.md §4: `assets.bind` without a revision
pins latest-at-bind-time, review-record MINOR accepts the read-then-write
shape) *within its guards*: a replay of a change the row already holds is a
no-op, and no wire method can reach it at all.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pacthold_runtime_compat.storage import Database

from ordessa_skills.api.errors import BindingError
from ordessa_skills.library.records import AssetRecords, BindingCasPort

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "ordessa_skills"


class InMemoryCas:
    """The smallest port that satisfies the documented contract."""

    def __init__(self) -> None:
        self.versions: dict[tuple[str, str], int] = {}
        self.results: dict[str, dict] = {}
        self.replayed: list[str] = []
        self.settled: list[tuple[str, int]] = []

    def current_version(self, profile_id: str, asset_id: str) -> int:
        return self.versions.get((profile_id, asset_id), 0)

    def replay(self, operation_key: str):
        record = self.results.get(operation_key)
        if record is not None:
            self.replayed.append(operation_key)
        return record

    def settle(self, *, operation_key, profile_id, asset_id, version, result) -> None:
        self.versions[(profile_id, asset_id)] = version
        self.results[operation_key] = dict(result)
        self.settled.append((operation_key, version))


@pytest.fixture()
def bound(tmp_path):
    """A database with two published revisions and one binding at revision 1."""
    database = Database(tmp_path / "data")
    database.initialize()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_a',1,'role','pi',1,0,'sha256:x','t','t')")
    records = AssetRecords(database)
    for revision in (1, 2):
        records.publish(kind="skill", name="demo-skill", revision=revision,
                        digest="sha256:" + str(revision) * 64, asset_id="demo-skill")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)
    return records, database


def _row(database):
    with database.read() as conn:
        row = conn.execute(
            "SELECT revision,enabled,created_at,updated_at FROM server_profile_assets "
            "WHERE profile_id='profile_a' AND asset_id='demo-skill'").fetchone()
    return tuple(row)


def test_the_port_is_runtime_checkable_on_its_documented_shape():
    assert isinstance(InMemoryCas(), BindingCasPort)


def test_an_unguarded_write_keeps_the_legacy_read_then_write_shape(bound, tmp_path):
    cas = InMemoryCas()
    records, database = bound
    records.cas = cas
    moved = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                   revision=2)
    assert moved["revision"] == 2  # unchanged legacy behaviour, no CAS asked for
    assert cas.versions == {} and cas.settled == [] and cas.replayed == []


def test_a_matching_expected_version_writes_and_advances_the_version(bound):
    cas = InMemoryCas()
    records, database = bound
    records.cas = cas
    moved = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                   revision=2, expected_version=0,
                                   operation_key="op-1")
    assert moved["revision"] == 2
    assert cas.current_version("profile_a", "demo-skill") == 1
    assert cas.settled == [("op-1", 1)]


def test_a_stale_expected_version_is_refused_and_writes_nothing(bound):
    records, database = bound
    records.cas = InMemoryCas()
    before = _row(database)
    with pytest.raises(BindingError) as refusal:
        records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                               revision=2, expected_version=7)
    assert refusal.value.code == "BINDING_VERSION_CONFLICT"
    assert _row(database) == before


def test_repeating_the_operation_key_upgrades_only_once(bound):
    records, database = bound
    records.cas = InMemoryCas()
    first = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                   revision=2, expected_version=0,
                                   operation_key="op-1")
    after_first = _row(database)
    second = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                    revision=1,  # a resent older intent
                                    expected_version=0, operation_key="op-1")
    assert second == first  # replayed verbatim
    assert _row(database) == after_first  # no second write happened
    assert records.bindings("profile_a")[0]["revision"] == 2


def test_a_retry_after_a_crash_before_settle_does_not_double_upgrade(bound):
    """The write landed but the key was never settled: the row is the truth."""
    records, database = bound
    cas = InMemoryCas()
    records.cas = cas
    records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                           revision=2, expected_version=0, operation_key="op-1")
    cas.settled.clear()
    cas.results.clear()  # the ledger never got the outcome
    with pytest.raises(BindingError) as refusal:
        records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                               revision=2, expected_version=0, operation_key="op-1")
    assert refusal.value.code == "BINDING_VERSION_CONFLICT"
    assert records.bindings("profile_a")[0]["revision"] == 2


def test_guarded_writes_without_a_port_are_a_typed_refusal(bound):
    records, database = bound
    before = _row(database)
    with pytest.raises(BindingError) as refusal:
        records.bind(profile_id="profile_a", asset_id="demo-skill", revision=2,
                     operation_key="op-x")
    assert refusal.value.code == "BINDING_CAS_UNAVAILABLE"
    with pytest.raises(BindingError) as refusal:
        records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                               revision=2, expected_version=0)
    assert refusal.value.code == "BINDING_CAS_UNAVAILABLE"
    assert _row(database) == before


def test_a_first_guarded_bind_settles_one_version(bound):
    records, database = bound
    cas = InMemoryCas()
    records.cas = cas
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_b',1,'role','pi',1,0,'sha256:x','t','t')")
    bound_row = records.bind(profile_id="profile_b", asset_id="demo-skill",
                             revision=2, expected_version=0, operation_key="op-b")
    assert bound_row["revision"] == 2
    assert cas.current_version("profile_b", "demo-skill") == 1
    replayed = records.bind(profile_id="profile_b", asset_id="demo-skill",
                            revision=1, operation_key="op-b")
    assert replayed == bound_row
    assert records.bindings("profile_b")[0]["revision"] == 2


# -- counter-examples for the port-less (legacy) shape ------------------------


def test_a_replayed_legacy_update_is_a_no_op_not_a_second_upgrade(bound):
    """data-model.md 重试不能重复升级 holds on the legacy path too: once the
    row carries the logical change, replaying the same update writes nothing
    (identical row bytes, no second timestamp bump) and returns the view."""
    records, database = bound  # the fixture's AssetRecords has cas=None
    first = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                   revision=2)
    assert first["revision"] == 2
    after_first = _row(database)
    replay = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                     revision=2)
    assert replay == first
    assert _row(database) == after_first  # no re-write, no re-bump
    # a different logical change (the enable flip) still moves through:
    flipped = records.update_binding(profile_id="profile_a", asset_id="demo-skill",
                                     revision=2, enabled=False)
    assert flipped["enabled"] is False
    assert _row(database)[1] == 0


def test_the_unguarded_records_writes_are_unreachable_from_the_wire():
    """The legacy read-then-write shape cannot be hit by accident: the only
    in-repo callers of `AssetRecords.bind/update_binding` are records.py
    itself. The wire's binding writes are `skills.assignmentsUpsert/Remove`,
    which route service.upsert_assignment -> AssignmentStore (its own CAS
    ledger in assignments/store.py), never through this class."""
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        if path.name == "records.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in {"bind",
                                                                 "update_binding"}:
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")
    assert offenders == [], f"call sites outside records.py: {offenders}"
    from ordessa_skills.wire import SKILLS_METHOD_IDS
    assert not [m for m in SKILLS_METHOD_IDS
                if "bind" in m.lower() or "binding" in m.lower()]
    # the two CAS-carrying wire methods are exactly the assignment ones
    assert {"skills.assignmentsUpsert", "skills.assignmentsRemove"} <= set(
        SKILLS_METHOD_IDS)
