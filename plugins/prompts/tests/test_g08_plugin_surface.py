"""T06 / G08 — the Server plugin surface: real contract types, the full
`prompts.*` family, and bare business management without Profile/Harness.

contracts.md §1 publishes the service as port `prompts.service` with the
`prompts.*` wire prefix; this release registers no HTTP or stream surface,
never imports host internals, and must keep working (public library CRUD)
with zero composed ports. Profile-scoped work refuses with a typed error
while the public library is untouched.

Gates: G08 (plus the wire halves of G01/G05/G06). Requirements: FR07, FR08.
"""
from __future__ import annotations

import base64
import sqlite3

import pytest

from ordessa_prompts.api import PROMPT_ERROR_CODES, PromptError
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore
from ordessa_prompts.plugin import DATA_DIR_NAME, PLUGIN_ID, PromptsServerPlugin

from server_plugin_api import (
    PLUGIN_METHOD_ID,
    SERVER_PLUGIN_API_VERSION,
    ServerMethodDescriptor,
    ServerPlugin,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

#: the operations contracts.md §1 lists for prompts.service
CONTRACT_OPERATIONS = (
    "prompts.list", "prompts.get", "prompts.getRevision", "prompts.create",
    "prompts.update", "prompts.clone", "prompts.archive", "prompts.restore",
    "prompts.importText", "prompts.exportText", "prompts.resolveSnapshot",
    "prompts.preview",
)

#: the error names contracts.md §1 requires the family to carry
CONTRACT_ERROR_NAMES = (
    "NOT_FOUND", "REVISION_CONFLICT", "INVALID_CONTENT", "LIMIT_EXCEEDED",
    "REF_KIND_MISMATCH", "SCOPE_REFUSED", "ARCHIVED_SELECTION",
    "DEPENDENCY_UNAVAILABLE", "NATIVE_SEMANTICS_UNSUPPORTED",
)

REQUEST = {"requestId": "req-00000001"}


def _b64(text: bytes) -> str:
    return base64.b64encode(text).decode("ascii")


def _create_request(**overrides) -> dict:
    params = dict(REQUEST, kind="instruction", scope={"kind": "library"},
                  title="wire title", body=_b64(b"wire body"),
                  operationKey="k-wire-create")
    params.update(overrides)
    return params


# -- the registration really uses the published contract vocabulary -------------

def test_the_plugin_is_a_server_plugin_and_declares_the_descriptor(
        plugin_registration):
    plugin, registration, _handlers = plugin_registration
    assert isinstance(plugin, ServerPlugin), (
        "the plugin does not satisfy the published ServerPlugin protocol")
    descriptor = plugin.descriptor()
    assert isinstance(descriptor, ServerPluginDescriptor)
    assert descriptor.id == PLUGIN_ID == "ordessa.assets.prompts"
    assert descriptor.api_version == SERVER_PLUGIN_API_VERSION
    assert descriptor.requires == (), (
        "Prompts must not hard-require Profile or Harness (SC01)")
    assert descriptor.display_name and descriptor.version
    assert isinstance(registration, ServerPluginRegistration)
    assert isinstance(registration.methods, tuple)
    assert all(isinstance(item, ServerMethodDescriptor)
               for item in registration.methods)


def test_the_service_port_is_provided_and_is_the_same_object_the_wire_uses(
        plugin_registration):
    _plugin, registration, handlers = plugin_registration
    provided = registration.provided_ports
    assert set(provided) == {"prompts.service"}, sorted(provided)
    service = provided["prompts.service"]
    assert isinstance(service, PromptsService)
    # the wire family and the port are one composition, not two stacks
    created = handlers["prompts.create"](_create_request())
    assert service.get(created["id"])["id"] == created["id"]
    assert created["scope"] == {"kind": "library"}
    # the snapshot's serverScope comes from the same service context
    snapshot = handlers["prompts.resolveSnapshot"]({
        **REQUEST, "selection": {"instructions": [{"promptId": created["id"]}]}})
    assert snapshot["serverScope"] == service.server_scope


def test_the_published_wire_family_is_exactly_the_contracted_operations(
        plugin_registration):
    _plugin, registration, _handlers = plugin_registration
    published = tuple(descriptor.method_id for descriptor in registration.methods)
    assert set(published) == set(CONTRACT_OPERATIONS), (
        f"{sorted(set(published) ^ set(CONTRACT_OPERATIONS))} differ from "
        "contracts.md §1")
    assert len(published) == len(set(published)) == len(CONTRACT_OPERATIONS)
    for descriptor in registration.methods:
        assert PLUGIN_METHOD_ID.fullmatch(descriptor.method_id), descriptor.method_id
        assert descriptor.owner == PLUGIN_ID
        assert "requestId" in descriptor.required_params
        assert not (descriptor.required_params & descriptor.optional_params)
    # first release exposes no deletion and no HTTP/stream surface
    assert not [name for name in published if "delete" in name or "remove" in name]
    assert registration.http_routes == ()
    assert registration.stream_routes == ()


def test_this_release_registers_no_http_or_stream_surface(plugin_registration):
    _plugin, registration, _handlers = plugin_registration
    assert registration.http_routes == () and registration.stream_routes == (), (
        "prompts must not open a second transport in this release")


# -- bare management over the public library, zero composed ports (G08) ---------

def test_full_library_management_works_without_profile_or_harness(
        plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    created = handlers["prompts.create"](_create_request())
    prompt_id = created["id"]
    assert created["metadataVersion"] == 1 and created["latestRevision"] == 1
    assert created["replayed"] is False

    fetched = handlers["prompts.get"]({**REQUEST, "id": prompt_id})
    assert base64.b64decode(fetched["bodyBase64"]) == b"wire body"
    assert fetched["sha256"].startswith("sha256:")

    revision = handlers["prompts.getRevision"]({**REQUEST, "id": prompt_id,
                                                "revision": 1})
    assert revision["revision"] == 1 and revision["byteSize"] == len(b"wire body")

    updated = handlers["prompts.update"]({
        **REQUEST, "id": prompt_id, "expectedVersion": 1, "expectedRevision": 1,
        "patch": {"title": "renamed", "bodyBase64": _b64(b"second wire body")},
        "operationKey": "k-wire-update"})
    assert updated["latestRevision"] == 2 and updated["metadataVersion"] == 2
    assert updated["sha256"].startswith("sha256:")

    cloned = handlers["prompts.clone"]({
        **REQUEST, "sourceId": prompt_id, "targetScope": {"kind": "library"},
        "title": "cloned on the wire", "operationKey": "k-wire-clone"})
    assert cloned["id"] != prompt_id
    assert base64.b64decode(
        handlers["prompts.get"]({**REQUEST, "id": cloned["id"]})["bodyBase64"]
    ) == b"second wire body"

    archived = handlers["prompts.archive"]({**REQUEST, "id": cloned["id"],
                                            "expectedVersion": 1,
                                            "operationKey": "k-wire-archive"})
    assert archived["archived"] is True
    listed = handlers["prompts.list"]({**REQUEST})
    assert cloned["id"] not in [item["id"] for item in listed["items"]]
    restored = handlers["prompts.restore"]({**REQUEST, "id": cloned["id"],
                                            "expectedVersion": 2,
                                            "operationKey": "k-wire-restore"})
    assert restored["archived"] is False

    imported = handlers["prompts.importText"]({
        **REQUEST, "contentBase64": _b64("导入的正文\n".encode("utf-8")),
        "filenameHint": "/somewhere/notes.md", "operationKey": "k-wire-import"})
    assert imported["title"] == "notes" and imported["bomStripped"] is False

    exported = handlers["prompts.exportText"]({**REQUEST, "id": imported["id"]})
    assert base64.b64decode(exported["bodyBase64"]) == "导入的正文\n".encode("utf-8")
    assert exported["suggestedFilename"] == "notes.prompt1.md"

    snapshot = handlers["prompts.resolveSnapshot"]({
        **REQUEST, "selection": {"instructions": [{"promptId": prompt_id}]}})
    assert snapshot["instructions"] == [prompt_id]
    assert snapshot["resolved"][0]["revision"] == 2

    preview = handlers["prompts.preview"]({
        **REQUEST, "selection": {"instructions": [{"promptId": prompt_id}]}})
    assert preview["revisions"] == {prompt_id: 2}
    assert preview["claim"].startswith("This is the Ordessa-configured content")


def test_profile_scoped_wire_work_refuses_typed_and_the_library_is_unaffected(
        plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    before = handlers["prompts.list"]({**REQUEST})
    with pytest.raises(PromptError) as exc:
        handlers["prompts.create"](_create_request(
            scope={"kind": "profile", "profileId": "alpha"},
            operationKey="k-wire-profile"))
    assert exc.value.code == "DEPENDENCY_UNAVAILABLE", exc.value
    after = handlers["prompts.list"]({**REQUEST})
    assert after == before, "a refused profile create changed the library"
    # and the public library still works end to end
    assert handlers["prompts.create"](_create_request(
        title="public stands", operationKey="k-wire-public"))["scope"] == {
        "kind": "library"}


# -- paging and the no-body rule -------------------------------------------------

def test_list_pages_default_50_and_refuse_over_100(plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    listed = handlers["prompts.list"]({**REQUEST})
    assert listed["limit"] == 50 and listed["offset"] == 0
    assert listed["nextOffset"] is None

    big = handlers["prompts.create"](_create_request(
        title="big page", operationKey="k-big-page"))["id"]
    assert big
    assert handlers["prompts.list"]({**REQUEST, "limit": 100})["limit"] == 100
    # above the published maximum is a capacity refusal with the numbers in it
    for limit in (101, 500):
        with pytest.raises(PromptError) as exc:
            handlers["prompts.list"]({**REQUEST, "limit": limit})
        assert exc.value.code == "LIMIT_EXCEEDED", exc.value
        assert exc.value.details["requested"] == limit
    # a limit that is not a positive page size at all is a shape refusal
    for limit in (0, -5, "50", True):
        with pytest.raises(PromptError) as exc:
            handlers["prompts.list"]({**REQUEST, "limit": limit})
        assert exc.value.code == "INVALID_REQUEST", exc.value
    # offset 0 is the first page; negatives and non-integers are shape errors
    assert handlers["prompts.list"]({**REQUEST, "offset": 0})["offset"] == 0
    assert handlers["prompts.list"]({**REQUEST, "offset": 999})["items"] == []
    for offset in (-1, "0", True):
        with pytest.raises(PromptError) as exc:
            handlers["prompts.list"]({**REQUEST, "offset": offset})
        assert exc.value.code == "INVALID_REQUEST", exc.value


def test_pagination_walks_every_record_exactly_once(plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    for index in range(5):
        handlers["prompts.create"](_create_request(
            title=f"paged {index}", body=_b64(f"body {index}".encode()),
            operationKey=f"k-page-{index}"))
    # one big page is the published order; walking must reproduce it exactly
    single = handlers["prompts.list"]({**REQUEST, "limit": 100})
    expected = [item["id"] for item in single["items"]]
    assert len(expected) == 5, expected

    seen: list[str] = []
    offsets: list[int] = []
    offset = 0
    for _ in range(10):
        page = handlers["prompts.list"]({**REQUEST, "limit": 2, "offset": offset})
        assert len(page["items"]) <= 2
        seen.extend(item["id"] for item in page["items"])
        offsets.append(page["offset"])
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert seen == expected, f"paging lost, duplicated or reordered: {seen}"
    assert offsets == [0, 2, 4], offsets


def test_list_items_never_carry_a_body(plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    handlers["prompts.create"](_create_request(
        title="no body in lists", body=_b64(b"keep this hidden from lists"),
        operationKey="k-nobody"))
    for params in ({**REQUEST}, {**REQUEST, "includeArchived": True},
                   {**REQUEST, "kind": "instruction"},
                   {**REQUEST, "query": "no body"}):
        listed = handlers["prompts.list"](params)
        assert listed["items"], f"the query found nothing: {params}"
        for item in listed["items"]:
            assert "bodyBase64" not in item and "body" not in item, item
            assert {"id", "kind", "scope", "title", "metadataVersion",
                    "latestRevision", "archived"} <= set(item)


# -- request shape and error mapping --------------------------------------------

def test_missing_or_malformed_params_refuse_invalid_request(plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    with pytest.raises(PromptError) as missing:
        handlers["prompts.get"]({**REQUEST})
    assert missing.value.code == "INVALID_REQUEST"
    assert "id" in missing.value.message

    # a body that is not base64 at all is a shape error; a well-formed but
    # empty payload is a content error
    for bad_body in ("not! base64", 42, b"raw bytes", "YWJj=="):
        with pytest.raises(PromptError) as exc:
            handlers["prompts.create"](_create_request(body=bad_body,
                                                       operationKey="k-bad-body"))
        assert exc.value.code == "INVALID_REQUEST", exc.value
    with pytest.raises(PromptError) as empty_body:
        handlers["prompts.create"](_create_request(body="",
                                                  operationKey="k-empty-body"))
    assert empty_body.value.code == "INVALID_CONTENT", empty_body.value

    for bad_version in (0, "1", True, None):
        with pytest.raises(PromptError) as exc:
            handlers["prompts.update"]({
                **REQUEST, "id": "prompt_whatever-1", "expectedVersion": bad_version,
                "expectedRevision": 1, "patch": {"title": "x"},
                "operationKey": "k-bad-version"})
        assert exc.value.code == "INVALID_REQUEST", exc.value


def test_unknown_params_are_not_part_of_the_published_shape(plugin_registration):
    """The host rejects a request carrying an unknown parameter; the plugin
    must therefore declare the shape exactly (no smuggled fields)."""
    _plugin, registration, handlers = plugin_registration
    by_id = {descriptor.method_id: descriptor for descriptor in registration.methods}
    create = by_id["prompts.create"]
    allowed = set(create.required_params) | set(create.optional_params)
    assert allowed == {"requestId", "kind", "scope", "title", "body",
                       "operationKey", "description"}, sorted(allowed)
    # an undeclared identity field is not in the shape; the handler ignores it
    # and the context subject still decides (G06), so nothing widens here
    assert "owner" not in allowed and "subject" not in allowed
    created = handlers["prompts.create"](_create_request(owner="whoever",
                                                        operationKey="k-smuggle"))
    assert created["scope"] == {"kind": "library"}


def test_every_wire_refusal_uses_a_contracted_error_name(plugin_registration):
    _plugin, _registration, handlers = plugin_registration
    handlers["prompts.create"](_create_request(operationKey="k-map"))
    prompt_id = handlers["prompts.create"](_create_request(
        title="target", operationKey="k-map-target"))["id"]
    persona_id = handlers["prompts.create"](_create_request(
        kind="persona", title="a persona", body=_b64(b"persona body"),
        operationKey="k-map-persona"))["id"]
    triggers = (
        ("prompts.get", {**REQUEST, "id": "prompt_nothing-here"}),
        ("prompts.update", {**REQUEST, "id": prompt_id, "expectedVersion": 9,
                            "expectedRevision": 9, "patch": {"title": "x"},
                            "operationKey": "k-map-conflict"}),
        ("prompts.create", _create_request(kind="nonsense",
                                          operationKey="k-map-kind")),
        ("prompts.list", {**REQUEST, "limit": 500}),
        ("prompts.create", _create_request(scope={"kind": "profile",
                                                 "profileId": "alpha"},
                                          operationKey="k-map-scope")),
        # a persona record does not belong in the instructions slot
        ("prompts.resolveSnapshot", {
            **REQUEST, "selection": {"instructions": [
                {"promptId": persona_id}]}}),
        ("prompts.importText", {**REQUEST, "contentBase64": _b64(b"   "),
                                 "operationKey": "k-map-import"}),
    )
    observed: set[str] = set()
    for method, params in triggers:
        with pytest.raises(PromptError) as exc:
            handlers[method](params)
        assert exc.value.code in PROMPT_ERROR_CODES, exc.value.code
        observed.add(exc.value.code)
    assert {"NOT_FOUND", "REVISION_CONFLICT", "INVALID_CONTENT", "LIMIT_EXCEEDED",
            "DEPENDENCY_UNAVAILABLE", "REF_KIND_MISMATCH"} <= observed, observed
    assert "ARCHIVED_SELECTION" in PROMPT_ERROR_CODES
    # archived refusal, driven through the wire too
    handlers["prompts.archive"]({**REQUEST, "id": prompt_id, "expectedVersion": 1,
                                 "operationKey": "k-map-archive"})
    with pytest.raises(PromptError) as archived_exc:
        handlers["prompts.update"]({**REQUEST, "id": prompt_id,
                                   "expectedVersion": 2, "expectedRevision": 1,
                                   "patch": {"title": "late edit"},
                                   "operationKey": "k-map-archived-edit"})
    assert archived_exc.value.code == "ARCHIVED_SELECTION"


def test_the_frozen_error_family_covers_every_contracts_name():
    missing = set(CONTRACT_ERROR_NAMES) - set(PROMPT_ERROR_CODES)
    assert missing == set(), f"contracts.md §1 names with no error class: {missing}"


# -- data root, disposal, isolation --------------------------------------------

def test_the_plugin_uses_the_context_data_root_as_its_private_directory(tmp_path):
    """No invented path rule: one directory named `prompts` under the product
    data root, nothing else written there."""
    context = ServerPluginContext(plugin_id=PLUGIN_ID, data_root=tmp_path, ports={})
    plugin = PromptsServerPlugin()
    registration = plugin.build(context)
    expected = tmp_path / DATA_DIR_NAME / "prompts.db"
    assert expected.exists(), "the private store did not land in the data root"
    assert sorted(path.name for path in tmp_path.iterdir()) == [DATA_DIR_NAME]
    handlers = {descriptor.method_id: descriptor.handler
                for descriptor in registration.methods}
    created = handlers["prompts.create"](_create_request(operationKey="k-root"))
    # a second assembly over the same data root reads the same domain back
    reopened = PromptsServerPlugin().build(context)
    reopened_handlers = {descriptor.method_id: descriptor.handler
                        for descriptor in reopened.methods}
    assert reopened_handlers["prompts.get"]({**REQUEST, "id": created["id"]})[
        "title"] == "wire title"
    # and a different data root is a different Server data domain
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = PromptsServerPlugin().build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=other_root, ports={}))
    other_handlers = {descriptor.method_id: descriptor.handler
                      for descriptor in other.methods}
    with pytest.raises(PromptError) as exc:
        other_handlers["prompts.get"]({**REQUEST, "id": created["id"]})
    assert exc.value.code == "NOT_FOUND"


def test_build_without_a_data_root_refuses_instead_of_guessing_a_path(tmp_path):
    plugin = PromptsServerPlugin()
    with pytest.raises(PromptError) as exc:
        plugin.build(ServerPluginContext(plugin_id=PLUGIN_ID, data_root=None,
                                        ports={}))
    assert exc.value.code == "INVALID_REQUEST", exc.value
    assert list(tmp_path.iterdir()) == [], "a guessed path was written anyway"


def test_disposal_closes_the_private_store(plugin_registration):
    plugin, registration, _handlers = plugin_registration
    assert callable(registration.disposal)
    store = plugin._store  # noqa: SLF001 - asserting the disposal boundary
    assert isinstance(store, PromptsStore) and not store.closed
    registration.disposal()
    assert store.closed, "disposal left the store open"
    assert plugin._store is None and plugin._service is None  # noqa: SLF001
    with pytest.raises(sqlite3.ProgrammingError):
        store.connection.execute("SELECT 1 FROM prompt_records")
    # disposal is idempotent for the host's teardown path
    registration.disposal()


def test_an_empty_selection_is_an_honest_empty_snapshot(plugin_registration):
    """No content configured is a real answer, not an error and not a claim
    about the native prompt; it also performs no side effect."""
    _plugin, _registration, handlers = plugin_registration
    snapshot = handlers["prompts.resolveSnapshot"]({**REQUEST, "selection": {}})
    assert snapshot["resolved"] == [] and snapshot["instructions"] == []
    assert snapshot["persona"] is None and snapshot["systemReplacement"] is None
    assert snapshot["totalBodyBytes"] == 0
    assert snapshot["serverScope"]
    preview = handlers["prompts.preview"]({**REQUEST, "selection": {}})
    assert preview["compositionOrder"] == [] and preview["revisions"] == {}
    listed = handlers["prompts.list"]({**REQUEST})
    assert listed["items"] == []
