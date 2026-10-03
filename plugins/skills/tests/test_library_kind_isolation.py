"""G01 counter-example 「非 Skill 行被修改」: the Skills library never touches
another kind's rows (requirement 2a; plan.md 原有 Assets-Skill 迁移: 旧表其他
kind 由迁移账指定旧业务所有者，不能由 Skills 清空).

The guard is asserted two ways on purpose:

* the **row-bytes probe** — every non-Skill row of `server_assets` and
  `server_profile_assets` is dumped with its rowid before and after the whole
  Skills write surface runs, and must come back byte-identical;
* the **refusal probe** — each write that *targets* a foreign row is refused
  with a typed error, so the guard is not an accident of the happy path.

Rows are planted straight through SQL (never through this domain), which is
how the mcp/command/plugin kinds actually get there today (legacy-inventory.md
§B.3: server-compat owns them).
"""
from __future__ import annotations

import hashlib

import pytest

from pacthold_runtime_compat.storage import Database

from ordessa_skills.api.errors import AssetDomainError, BindingError
from ordessa_skills.library.catalog import CatalogStore
from ordessa_skills.library.import_transfer import ImportService
from ordessa_skills.library.records import AssetRecords
from ordessa_skills.library.store import SkillRevisionStore

FOREIGN_KINDS = ("mcp", "command", "plugin")


@pytest.fixture()
def seeded(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_a',1,'role','pi',1,0,'sha256:x','t','t')")
        for index, kind in enumerate(FOREIGN_KINDS):
            conn.execute(
                "INSERT INTO server_assets(id,kind,name,description,latest_revision,"
                "digest,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"foreign-{kind}", kind, f"name-{kind}", "not a skill", index + 1,
                 "sha256:" + "f" * 64, "legacy:server-compat", "t0", "t0"))
            # A binding of a foreign asset: exactly the row shape the old
            # Assets surface owns and Skills must leave alone.
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,revision,enabled,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("profile_a", f"foreign-{kind}", index + 1, 1, "t0", "t0"))
    return database, tmp_path


def _foreign_rows(database):
    with database.read() as conn:
        assets = [tuple(row) for row in conn.execute(
            "SELECT rowid,id,kind,name,description,latest_revision,digest,source,"
            "created_at,updated_at FROM server_assets WHERE kind<>'skill' ORDER BY rowid")]
        bindings = [tuple(row) for row in conn.execute(
            "SELECT b.rowid,b.profile_id,b.asset_id,b.revision,b.enabled,b.created_at,"
            "b.updated_at FROM server_profile_assets b "
            "JOIN server_assets a ON a.id=b.asset_id WHERE a.kind<>'skill' ORDER BY b.rowid")]
    return assets, bindings


def _skill_files(body: str = "v1"):
    manifest = f"---\nname: demo-skill\ndescription: A demo.\n---\n\n{body}\n".encode()
    return {"SKILL.md": manifest}


def _import_commit(records, tmp_path, *, revision):
    service = ImportService(root=tmp_path / "assets", records=records)
    files = _skill_files(f"v{revision}")
    opened = service.begin(request_id="r", files=[
        {"path": path, "bytes": len(data),
         "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        for path, data in sorted(files.items())],
        total_bytes=sum(len(data) for data in files.values()))
    for index, path in enumerate(sorted(files)):
        data = files[path]
        service.chunk(opened["importId"], index=index, payload=data,
                      sha256="sha256:" + hashlib.sha256(data).hexdigest())
    service.prepare(opened["importId"], source={"type": "local-transfer", "origin": "d"})
    return service.commit(opened["importId"], asset_id="demo-skill", revision=revision)


def test_the_whole_write_surface_leaves_foreign_rows_byte_identical(seeded):
    database, tmp_path = seeded
    records = AssetRecords(database)
    before = _foreign_rows(database)
    assert len(before[0]) == len(FOREIGN_KINDS), "the fixture planted foreign rows"

    # every write this domain owns, run against a Skill asset
    _import_commit(records, tmp_path, revision=1)
    store = SkillRevisionStore(tmp_path / "assets")
    _import_commit(records, tmp_path, revision=2)
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)
    records.update_binding(profile_id="profile_a", asset_id="demo-skill", revision=2)
    records.publish(kind="skill", name="demo-skill", revision=3,
                    digest="sha256:" + "3" * 64, asset_id="demo-skill")
    records.unbind(profile_id="profile_a", asset_id="demo-skill")
    records.bindings("profile_a")
    catalog = CatalogStore(tmp_path / "assets" / "catalogs")
    assert catalog.snapshot("nothing") is None

    assert _foreign_rows(database) == before


@pytest.mark.parametrize("kind", FOREIGN_KINDS)
def test_publishing_a_foreign_kind_is_refused(seeded, kind):
    database, _tmp_path = seeded
    records = AssetRecords(database)
    before = _foreign_rows(database)
    with pytest.raises(AssetDomainError) as refusal:
        records.publish(kind=kind, name=f"name-{kind}", revision=1,
                        digest="sha256:" + "a" * 64)
    assert refusal.value.code == "ASSET_KIND_NOT_SKILL"
    assert _foreign_rows(database) == before


@pytest.mark.parametrize("kind", FOREIGN_KINDS)
def test_publishing_onto_a_foreign_asset_id_is_refused(seeded, kind):
    database, _tmp_path = seeded
    records = AssetRecords(database)
    before = _foreign_rows(database)
    with pytest.raises(AssetDomainError) as refusal:
        records.publish(kind="skill", name="hijack", revision=4,
                        digest="sha256:" + "b" * 64, asset_id=f"foreign-{kind}")
    assert refusal.value.code == "ASSET_KIND_NOT_SKILL"
    assert _foreign_rows(database) == before


def test_binding_a_foreign_asset_is_refused_and_creates_no_row(seeded):
    database, _tmp_path = seeded
    records = AssetRecords(database)
    before = _foreign_rows(database)
    with pytest.raises(BindingError) as refusal:
        records.bind(profile_id="profile_a", asset_id="foreign-mcp", revision=1)
    assert refusal.value.code == "ASSET_NOT_FOUND"
    assert _foreign_rows(database) == before


def test_a_foreign_binding_is_never_listed_as_a_skill(seeded):
    database, _tmp_path = seeded
    records = AssetRecords(database)
    rows = records.bindings("profile_a")
    assert rows == []  # the three foreign pins stay invisible to Skills


@pytest.mark.parametrize("operation", ["unbind", "update_binding"])
def test_mutating_a_foreign_binding_is_refused(seeded, operation):
    database, _tmp_path = seeded
    records = AssetRecords(database)
    before = _foreign_rows(database)
    with pytest.raises(BindingError) as refusal:
        if operation == "unbind":
            records.unbind(profile_id="profile_a", asset_id="foreign-mcp")
        else:
            records.update_binding(profile_id="profile_a", asset_id="foreign-mcp",
                                   revision=1)
    assert refusal.value.code in {"BINDING_NOT_FOUND", "ASSET_KIND_NOT_SKILL",
                                 "ASSET_NOT_FOUND"}
    assert _foreign_rows(database) == before


def test_every_binding_mutation_carries_the_guard_in_sql_itself(seeded):
    """The guard is not only a Python pre-check: the issued statements say it.

    Recorded by wrapping the database handles the records layer uses, so what
    is asserted is the SQL that actually reaches SQLite (a future call site
    cannot bypass the rule by skipping a Python check).
    """
    from contextlib import contextmanager

    recorded: list[tuple[str, tuple]] = []

    class Recorder:
        """Forwarding proxy: keeps the real connection, logs every execute."""

        def __init__(self, conn) -> None:
            self._conn = conn

        def execute(self, sql, parameters=()):
            recorded.append((" ".join(sql.split()), tuple(parameters)))
            return self._conn.execute(sql, parameters)

        def __getattr__(self, item):
            return getattr(self._conn, item)

    class RecordingDatabase:
        def __init__(self, inner) -> None:
            self._inner = inner

        @contextmanager
        def read(self):
            with self._inner.read() as conn:
                yield Recorder(conn)

        @contextmanager
        def transaction(self):
            with self._inner.transaction() as conn:
                yield Recorder(conn)

    database, _tmp_path = seeded
    records = AssetRecords(RecordingDatabase(database))
    records.publish(kind="skill", name="demo-skill", revision=1,
                    digest="sha256:" + "1" * 64, asset_id="demo-skill")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)
    records.update_binding(profile_id="profile_a", asset_id="demo-skill", revision=1)
    records.unbind(profile_id="profile_a", asset_id="demo-skill")
    with pytest.raises(BindingError) as refusal:
        records.bind(profile_id="profile_a", asset_id="foreign-mcp", revision=1)
    assert refusal.value.code == "ASSET_NOT_FOUND"

    mutations = [(sql, params) for sql, params in recorded
                 if sql.upper().lstrip().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert mutations, "no write statements were recorded — the probe checks nothing"
    for sql, params in mutations:
        if "server_profile_assets" in sql:
            assert "kind=?" in sql, f"binding write without a kind guard: {sql}"
        if "UPDATE server_assets" in sql:
            assert "AND kind=?" in sql, sql
        if "INSERT INTO server_assets" in sql:
            # the kind column is the second value and is pinned to 'skill'
            assert params[1] == "skill", sql
    # the foreign bind never reached a write: it was refused before one
    assert not [sql for sql, params in mutations
                if "foreign-mcp" in " ".join(str(item) for item in params)]

