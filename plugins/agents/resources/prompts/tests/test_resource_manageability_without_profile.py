"""T007-11/T007-12 — resource manageability without a Profile.

The prompts domain (`ordessa.assets.prompts`) is a top-level resource plugin.
This suite pins its assembly entry and verifies library work without Profile,
session, or Agent state, typed refusal when Profile-scoped writes are absent,
and refusal of forged DataArea namespaces before filesystem effects.

Cross-domain imports are the published packages only (`pacthold`,
`server_plugin_api`).
"""
from __future__ import annotations

import base64
import sqlite3

import pytest

from pacthold.adapters.filesystem.data_area import DataAreaError, FileDataAreaAdapter
from ordessa_prompts.api import PromptError, body_digest
from ordessa_prompts.plugin import DATA_DIR_NAME, PLUGIN_ID, PromptsServerPlugin

from server_plugin_api import ServerPluginContext

REQUEST = {"requestId": "req-t007-11-1"}

#: the wire family contracts.md §1 freezes for the domain
WIRE_FAMILY = {
    "prompts.list", "prompts.get", "prompts.getRevision", "prompts.create",
    "prompts.update", "prompts.clone", "prompts.archive", "prompts.restore",
    "prompts.importText", "prompts.exportText", "prompts.resolveSnapshot",
    "prompts.preview",
}

#: the port names THIS domain is documented to consume; anything else (an
#: agent/harness/acp/session facade) read at build time would be drift
DOCUMENTED_PORTS = {"server.id", "prompts.subject_provider",
                    "profile.prompts_authorization"}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class _PoisonProfilePort:
    """A Profile authorisation port that fails on any call: bare library work
    must never consult it (zero Profile interaction)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def is_authorized(self, caller_subject: str, profile_id: str) -> bool:
        self.calls.append((caller_subject, profile_id))
        raise AssertionError(
            "library work consulted profile.prompts_authorization")


class _RecordingPorts(dict):
    """Records every documented port name the plugin reads during build, so
    the test can prove no Agent/Harness port was touched."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reads: list[str] = []

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)


def _assemble(tmp_path, ports):
    """The production assembly entry: PromptsServerPlugin over a tmp data
    root, no forced store path, no Profile/Harness composed by the test."""
    plugin = PromptsServerPlugin()
    context = ServerPluginContext(plugin_id=PLUGIN_ID, data_root=tmp_path,
                                  ports=ports)
    registration = plugin.build(context)
    handlers = {descriptor.method_id: descriptor.handler
                for descriptor in registration.methods}
    return plugin, registration, handlers


def _private_tables(db_path) -> "set[str]":
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _count(db_path, sql: str, params: "tuple" = ()) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    finally:
        conn.close()


# -- positive: the whole domain chain without Profile/session/Agent ------------


def test_domain_chain_is_manageable_without_profile_session_or_agent(tmp_path):
    poison = _PoisonProfilePort()
    ports = _RecordingPorts({
        "profile.prompts_authorization": poison,
        "prompts.subject_provider": lambda: "operator-without-profile",
    })
    _plugin, registration, handlers = _assemble(tmp_path, ports)
    try:
        # the domain assembles on the published vocabulary alone
        assert set(registration.provided_ports) == {"prompts.service"}
        assert set(handlers) == WIRE_FAMILY
        assert registration.http_routes == () and registration.stream_routes == ()

        listed = handlers["prompts.list"](dict(REQUEST))
        assert listed["items"] == [] and listed["nextOffset"] is None

        created = handlers["prompts.create"]({
            **REQUEST, "kind": "instruction", "scope": {"kind": "library"},
            "title": "no-profile instruction", "body": _b64(b"first body"),
            "operationKey": "k-t007-create"})
        prompt_id = created["id"]
        assert created["scope"] == {"kind": "library"}
        assert created["latestRevision"] == 1 and created["metadataVersion"] == 1

        updated = handlers["prompts.update"]({
            **REQUEST, "id": prompt_id, "expectedVersion": 1,
            "expectedRevision": 1,
            "patch": {"title": "renamed", "bodyBase64": _b64(b"second body")},
            "operationKey": "k-t007-update"})
        assert updated["latestRevision"] == 2 and updated["metadataVersion"] == 2

        revision = handlers["prompts.getRevision"]({
            **REQUEST, "id": prompt_id, "revision": 2})
        assert base64.b64decode(revision["bodyBase64"]) == b"second body"
        assert revision["sha256"] == body_digest(b"second body")

        preview = handlers["prompts.preview"]({
            **REQUEST,
            "selection": {"instructions": [{"promptId": prompt_id}]}})
        assert preview["revisions"] == {prompt_id: 2}
        assert preview["compositionOrder"] == [f"instruction:{prompt_id}"]
        assert preview["contentDigest"].startswith("sha256:")
        assert "NOT_NATIVE_FULL_SYSTEM_PROMPT" in preview["diagnostics"]

        listed = handlers["prompts.list"]({**REQUEST, "kind": "instruction"})
        assert [item["id"] for item in listed["items"]] == [prompt_id]

        # zero Profile/Agent interaction: the poison port was never touched and
        # only the documented ports were read (no agent/harness/acp/session)
        assert poison.calls == []
        assert set(ports.reads) <= DOCUMENTED_PORTS, sorted(set(ports.reads))
        assert not [name for name in ports.reads
                    if any(word in name for word in ("agent", "harness", "acp",
                                                     "session"))]

        # zero profiles/session persistence: the private store holds only the
        # domain's own tables and no profile-scoped row
        db_path = tmp_path / DATA_DIR_NAME / "prompts.db"
        assert _private_tables(db_path) == {
            "prompt_meta", "prompt_records", "prompt_revisions",
            "prompt_idempotency"}
        assert not [table for table in _private_tables(db_path)
                    if "profile" in table or "session" in table]
        assert _count(db_path, "SELECT COUNT(*) FROM prompt_records") == 1
        assert _count(db_path,
                      "SELECT COUNT(*) FROM prompt_records WHERE scope_kind='profile'") == 0
        assert [path.name for path in tmp_path.iterdir()] == [DATA_DIR_NAME]
    finally:
        registration.disposal()


def test_profile_scoped_write_is_typed_absent_and_fabricates_no_profile(tmp_path):
    """Missing condition: with no Profile port composed, profile-scoped work
    refuses typed while the public library stays untouched and no profile row
    or directory is invented."""
    _plugin, registration, handlers = _assemble(tmp_path, _RecordingPorts())
    try:
        before = handlers["prompts.list"](dict(REQUEST))
        with pytest.raises(PromptError) as exc:
            handlers["prompts.create"]({
                **REQUEST, "kind": "instruction",
                "scope": {"kind": "profile", "profileId": "profile-alpha"},
                "title": "needs a profile", "body": _b64(b"profile body"),
                "operationKey": "k-t007-profile"})
        assert exc.value.code == "DEPENDENCY_UNAVAILABLE", exc.value
        assert handlers["prompts.list"](dict(REQUEST)) == before

        db_path = tmp_path / DATA_DIR_NAME / "prompts.db"
        assert _count(db_path, "SELECT COUNT(*) FROM prompt_records") == 0
        assert _count(db_path,
                      "SELECT COUNT(*) FROM prompt_records WHERE scope_kind='profile'") == 0
        assert [path.name for path in tmp_path.iterdir()] == [DATA_DIR_NAME]
    finally:
        registration.disposal()


# -- counter-example: a DataArea namespace is an identity, not a window/path ----


def test_data_area_claim_rejects_forged_window_ids_and_paths(tmp_path):
    root = tmp_path / "areas"
    adapter = FileDataAreaAdapter(root)
    forged = ("Window-1", "../escape", "/etc/passwd", "ordessa/../outside",
              ".hidden", "")
    for namespace in forged:
        with pytest.raises(DataAreaError):
            adapter.claim(namespace, "write", "1-1")
    # nothing was created for any refusal: no traversal target, no marker
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / "passwd").exists()
    assert not root.exists() or list(root.rglob("*")) == []

    # positive control: a grammar-valid stable identity still claims and opens
    descriptor = adapter.claim("ordessa.prompts.store", "write", "1-1")
    assert descriptor.area_id == "area.ordessa.prompts.store"
    assert descriptor.namespace == "ordessa.prompts.store"
    opened = adapter.open(descriptor.area_id)
    assert root.resolve() in opened.resolve().parents
