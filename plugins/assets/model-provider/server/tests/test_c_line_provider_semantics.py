"""C-line acceptance counterexamples for ModelProvider (C14-C18, C21).

Driven through the **real wire surface** (``providerModels.*`` on an activated
``ServerPluginHost``), not by calling service internals, so what is proven is
the boundary the product actually exposes.

Controlled fixtures only: no endpoint is contacted, no system keyring is
touched, no model call is made. C16 additionally requires an L3/L4 observation
of the real system keyring across processes; the L1 half lives in
``test_credential_import.py`` and is not repeated here.
"""
from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest
from ordessa_server.errors import ServerError
from ordessa_server.plugin_host.host import ServerPluginHost

from ordessa_model_provider import probe as probe_module
from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.plugin import ModelProviderPlugin
from ordessa_model_provider.records import ProviderModelRecords
from ordessa_model_provider.probe import ProbeError, probe_connection
from ordessa_model_provider.testing import (
    FakeHarnesses, harness_descriptor, seed_credential_row, wire_body,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_model_provider"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]

#: A reserved, never-globally-routable range. Saving it must work (no DNS);
#: probing it must not.
FAKE_IP = "198.18.0.7"


class _NoReferences:
    """The reference port answering "nothing references this". Its presence is
    what makes ``archive`` decidable at all -- see the fail-closed test."""

    def references_of(self, provider_config_id: str) -> list[str]:
        return []


@pytest.fixture()
def wired(stack, credentials):
    """An activated host with the real plugin registered, plus its handlers.

    The harnesses here accept an ``api-key`` credential so the C18 split
    between a bound key and an official-login record is reachable.
    """
    seed_credential_row(stack["database"])
    harnesses = FakeHarnesses(
        descriptors={"pi": harness_descriptor(credential_kind="api_key")},
        protocols={"pi": {"openai-chat": ""}},
    )
    host = ServerPluginHost(host_ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })
    host.activate_all([ModelProviderPlugin(harnesses=harnesses)])
    handlers = {mid: host.methods.lookup(mid).handler for mid in (
        "providerModels.create", "providerModels.update",
        "providerModels.archive", "providerModels.list",
        "providerModels.probeConnection", "providerModels.probeModels",
    )}
    catalog = ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"], harnesses=harnesses, credentials=credentials,
        reference_port=_NoReferences(),
    )
    return host, handlers, catalog


def _create(handlers, request_id, **over):
    return handlers["providerModels.create"]({
        "requestId": request_id, **wire_body(**over)})["providerModel"]


# --------------------------------------------------------------------------
# C14 -- saving/editing needs no DNS; probing still enforces SSRF
# --------------------------------------------------------------------------
def _no_dns(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("configuration storage performed a DNS lookup")
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(probe_module.socket, "getaddrinfo", explode)


def test_c14_saving_a_provider_config_performs_no_dns_lookup(wired, monkeypatch):
    """C14: storing configuration is not a network probe. Every
    ``getaddrinfo`` is a hard failure here, so a save that needed DNS could not
    pass -- and a Fake-IP address, which resolves nowhere, saves fine."""
    _host, handlers, _catalog = wired
    _no_dns(monkeypatch)
    created = _create(handlers, "c14-save-0001", credentialId="cred-1",
                      protocols=["openai-chat"],
                      endpoints={"openai-chat": f"https://{FAKE_IP}/v1"},
                      provenance={"baseUrl": f"https://{FAKE_IP}/v1",
                                  "wireApi": "chat_completions",
                                  "fieldsSource": "manual"})
    assert created["id"]

    edited = handlers["providerModels.update"]({
        "requestId": "c14-edit-0001", "providerModelId": created["id"],
        "expectedVersion": created["version"],
        **wire_body(credentialId="cred-1",
                    protocols=["openai-chat"],
                    endpoints={"openai-chat": f"https://{FAKE_IP}/v2"},
                    provenance={"baseUrl": f"https://{FAKE_IP}/v2",
                                "wireApi": "chat_completions",
                                "fieldsSource": "manual"}),
    })["providerModel"]
    assert edited["version"] == created["version"] + 1
    # The address the user typed reads back verbatim: no resolution, no
    # substitution, no silent drop.
    assert edited["endpoints"]["openai-chat"] == f"https://{FAKE_IP}/v2"


def test_c14_probing_that_same_saved_address_is_refused(wired, monkeypatch):
    """C14 counterexample: making the save succeed must not have loosened the
    probe. The very address that just saved is refused at probe time -- with a
    typed code the UI can show, not an untyped crash."""
    _host, handlers, _catalog = wired
    monkeypatch.setattr(probe_module.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM,
                                          6, "", (FAKE_IP, 443))])
    answer = handlers["providerModels.probeConnection"](
        {"requestId": "c14-probe-0001", "baseUrl": f"https://{FAKE_IP}/v1"})
    assert answer == {"status": "failed", "code": "PROBE_ENDPOINT_BLOCKED"}


@pytest.mark.parametrize("host", ["10.0.0.5", "192.168.1.10", "172.16.4.4",
                                  "169.254.169.254", "198.18.0.7"])
def test_c14_probe_refuses_the_whole_private_surface_not_one_range(host, monkeypatch):
    """The counterexample to 'loosen every private range so a Fake-IP saves':
    each private class is still refused at probe time."""
    monkeypatch.setattr(probe_module.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM,
                                          6, "", (host, 443))])
    with pytest.raises(ProbeError) as excinfo:
        probe_connection(f"https://{host}/v1", None)
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_c14_loopback_is_the_one_narrow_documented_exception(monkeypatch):
    """C14: the split is syntax-vs-resolution, not a general loosening. Explicit
    loopback is the one address the probe admits, so a locally running provider
    can still be probed -- and the plain-http exception stays closed to every
    other host."""
    monkeypatch.setattr(probe_module.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM,
                                          6, "", ("127.0.0.1", 443))])
    assert probe_module._validate_endpoint("https://127.0.0.1:9443/v1") == (
        "https://127.0.0.1:9443/v1", "127.0.0.1")
    with pytest.raises(ProbeError) as excinfo:
        probe_module._normalize_endpoint_url("http://10.0.0.5/v1")
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_c14_a_name_offering_both_public_and_private_is_refused(monkeypatch):
    """One public answer must not launder a private sibling."""
    monkeypatch.setattr(probe_module.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443)),
    ])
    with pytest.raises(ProbeError) as excinfo:
        probe_connection("https://mixed.example.test/v1", None)
    assert excinfo.value.code == "PROBE_ENDPOINT_BLOCKED"


def test_c14_plain_http_off_loopback_still_refuses_at_save_time(wired, monkeypatch):
    """The syntax-level rule applies at save without any lookup, so save is
    not a loophole around the https requirement."""
    _host, handlers, _catalog = wired
    _no_dns(monkeypatch)
    with pytest.raises(ServerError) as excinfo:
        _create(handlers, "c14-http-0001",
                protocols=["openai-chat"],
                endpoints={"openai-chat": "http://api.acme.test/v1"})
    assert excinfo.value.code == "PROFILE_CONFIGURATION_INVALID"


# --------------------------------------------------------------------------
# C15 -- the catalogue is served by the backend, honestly
# --------------------------------------------------------------------------
def test_c15_catalogue_is_served_from_the_backend_records(wired):
    """C15: the list is whatever the backend stored -- created and archived
    rows, projected by the backend, never a frontend constant."""
    _host, handlers, _catalog = wired
    _create(handlers, "c15-a-000001", displayName="Acme A")
    _create(handlers, "c15-b-000001", displayName="Acme B")
    live = handlers["providerModels.list"]({"includeArchived": False})["items"]
    assert {row["displayName"] for row in live} == {"Acme A", "Acme B"}

    second = next(row for row in live if row["displayName"] == "Acme B")
    _catalog.archive(second["id"], second["version"], "c15-arch-0001")
    assert {row["displayName"] for row in
            handlers["providerModels.list"](
                {"includeArchived": False})["items"]} == {"Acme A"}
    assert {row["displayName"] for row in
            handlers["providerModels.list"](
                {"includeArchived": True})["items"]} == {"Acme A", "Acme B"}


def test_c15_archive_refuses_fail_closed_when_references_are_unprovable(stack,
                                                                        credentials):
    """C15 counterexample: an archive whose reference state cannot be proven is
    refused. "Cannot prove there are none" is never read as "there are none"."""
    seed_credential_row(stack["database"])
    harnesses = FakeHarnesses(
        descriptors={"pi": harness_descriptor(credential_kind="api_key")},
        protocols={"pi": {"openai-chat": ""}},
    )
    portless = ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"], harnesses=harnesses, credentials=credentials,
    )
    body = wire_body(credentialId=None)
    created = portless.create("c15-fc-0001", body)
    with pytest.raises(ServerError) as excinfo:
        portless.archive(created["id"],
                         created["version"], "c15-fc-arch")
    assert excinfo.value.code == "REFERENCE_STATE_UNKNOWN"


def test_c15_unavailable_model_is_disabled_with_an_explicit_reason(wired):
    """C15: an unavailable entry is carried honestly with its reason, never
    projected as a silently selectable option."""
    _host, handlers, _catalog = wired
    with pytest.raises(ServerError) as excinfo:
        _create(handlers, "c15-bad-00001", models=[{
            "modelId": "m1", "displayName": "M1", "availability": "unavailable",
            "unavailableReason": None}])
    assert excinfo.value.code == "PROFILE_CONFIGURATION_INVALID"

    created = _create(handlers, "c15-ok-000001", models=[{
        "modelId": "m1", "displayName": "M1", "availability": "unavailable",
        "unavailableReason": "the provider retired it"}])
    entry = created["models"][0]
    assert entry["availability"] == "unavailable"
    assert entry["unavailableReason"] == "the provider retired it"


def test_c15_empty_or_duplicated_model_list_is_refused(wired):
    _host, handlers, _catalog = wired
    with pytest.raises(ServerError):
        _create(handlers, "c15-empty-0001", models=[])
    with pytest.raises(ServerError):
        _create(handlers, "c15-dup-000001", models=[
            {"modelId": "m1", "displayName": "A", "availability": "available",
             "unavailableReason": None},
            {"modelId": "m1", "displayName": "B", "availability": "available",
             "unavailableReason": None},
        ])


def test_c15_a_dangling_model_reference_is_refused_when_it_is_actually_resolved(wired):
    """C15 counterexample: a control naming a model the backend does not serve
    is refused at the point the reference is resolved -- not offered, not
    silently defaulted. (Save stores the declaration; the freeze that resolves
    it is where the answer must be honest.)"""
    _host, handlers, catalog = wired
    _create(handlers, "c15-dangling-1", configuration=[
        {"controlId": "model", "value": {"providerId": "no-such-record",
                                         "modelId": "m9"}}])
    with pytest.raises(ServerError) as excinfo:
        catalog.freeze_execution_configuration(
            "pi", {"model": {"providerId": "no-such-record", "modelId": "m9"}})
    assert excinfo.value.code == "PROVIDER_MODEL_NOT_FOUND"

    # A real record, but a model it does not carry, is refused the same way.
    real = _create(handlers, "c15-dangling-2")
    with pytest.raises(ServerError) as excinfo:
        catalog.freeze_execution_configuration(
            "pi", {"model": {"providerId": real["id"], "modelId": "m-does-not-exist"}})
    assert excinfo.value.code == "PROFILE_CONFIGURATION_INVALID"


# --------------------------------------------------------------------------
# C18 -- the official account and API configurations stay separate
# --------------------------------------------------------------------------
def test_c18_official_login_and_api_key_are_distinct_records(wired):
    """C18: a record bound to an API-key credential and one bound to the
    official account are different records; choosing a model never implies
    either, and never moves the other."""
    _host, handlers, _catalog = wired
    api = _create(handlers, "c18-api-0001", displayName="Acme API",
                  credentialId="cred-1")
    official = _create(handlers, "c18-official-1", displayName="Acme official",
                       credentialId=None)
    assert api["id"] != official["id"]
    assert api["credentialId"] == "cred-1"
    assert official["credentialId"] is None

    # Creating and choosing a third record leaves both alone.
    other = _create(handlers, "c18-other-001", displayName="Other API",
                    credentialId="cred-1")
    rows = {row["id"]: row for row in
            handlers["providerModels.list"]({"includeArchived": False})["items"]}
    assert rows[api["id"]]["credentialId"] == "cred-1"
    assert rows[official["id"]]["credentialId"] is None
    assert rows[other["id"]]["credentialId"] == "cred-1"


def test_c18_a_harness_that_accepts_no_credentials_refuses_one(stack, credentials):
    """C18 counterexample: an official-login harness cannot be handed an API
    key, so switching a model can never quietly substitute one for it."""
    official_only = FakeHarnesses(
        descriptors={"pi": harness_descriptor(credential_kind=None)},
        protocols={"pi": {"openai-chat": ""}},
    )
    seed_credential_row(stack["database"])
    host = ServerPluginHost(host_ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })
    host.activate_all([ModelProviderPlugin(harnesses=official_only)])
    create = host.methods.lookup("providerModels.create").handler
    with pytest.raises(ServerError) as excinfo:
        create({"requestId": "c18-refuse-001", **wire_body(credentialId="cred-1")})
    assert excinfo.value.code == "PROFILE_CONFIGURATION_INVALID"

    # The credential-free shape is the one that works for that harness.
    ok = create({"requestId": "c18-ok-000001", **wire_body(credentialId=None)})
    assert ok["providerModel"]["credentialId"] is None


# --------------------------------------------------------------------------
# C21 -- no second provider adapter; not a process/session coordinator
# --------------------------------------------------------------------------
def _imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def _defined_names(path: Path) -> set[str]:
    return {node.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def test_c21_no_second_provider_adapter_implementation_exists():
    """C21: the only brand-adapter implementation is Harness's. ModelProvider
    carries no per-brand adaptation source of its own."""
    adapter_sources = sorted(
        p for p in (PLUGIN_ROOT / "adapters" / "src").rglob("*.py"))
    assert adapter_sources == [], (
        "a second provider adapter implementation appeared: "
        + ", ".join(str(p) for p in adapter_sources))


def test_c21_the_plugin_never_branches_on_a_brand_to_shape_configuration():
    """C21 counterexample-proof in one test: the analyser below sees a brand
    conditional, and the real tree contains none."""
    brands = {"codex", "claude", "claude-code", "gemini", "cursor"}
    offending = ('def shape(harness_id):\n'
                 '    if harness_id == "codex":\n'
                 '        return {"wire_api": "responses"}\n'
                 '    return {}\n')

    def brand_conditionals(source: str) -> list[str]:
        hits = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Compare):
                for operand in [node.left, *node.comparators]:
                    if isinstance(operand, ast.Constant) and isinstance(
                            operand.value, str) and operand.value.lower() in brands:
                        hits.append(operand.value)
        return hits

    assert brand_conditionals(offending) == ["codex"], "analyser is blind"
    for path in sorted(SRC.glob("*.py")):
        assert brand_conditionals(path.read_text(encoding="utf-8")) == [], path.name


def test_c21_brand_tests_never_drive_a_process_or_a_session():
    """C21: the brand matrix exercises the Harness contract, never a process or
    a session coordinator owned by ModelProvider."""
    for path in sorted((Path(__file__).resolve().parent).glob("test_brand_*.py")):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("subprocess", "Popen", "os.fork", "pty.spawn",
                          "session_new", "threading.Thread"):
            assert forbidden not in text, f"{path.name} drives {forbidden}"


def test_c21_configuration_application_goes_only_through_the_harness_capability():
    """C21: the one route to native configuration is the published Harness
    application contract. A private Harness module would be a second,
    uncoordinated route."""
    importers = {}
    for path in sorted(SRC.glob("*.py")):
        modules = {m for m in _imports_of(path) if m.startswith("ordessa_harness")}
        if modules:
            importers[path.name] = modules
    assert importers, "the binding must consume the Harness capability"
    for name, modules in importers.items():
        private = {m for m in modules
                   if not (m == "ordessa_harness_api"
                           or m.startswith("ordessa_harness_api."))}
        assert private == set(), f"{name} reaches a private Harness module: {private}"


def test_c21_the_import_analyser_discriminates_a_private_harness_import(tmp_path):
    """Counterexample proof: the rule above can see a violation."""
    offender = tmp_path / "bad.py"
    offender.write_text(
        "from ordessa_harness.configuration.model.backend import X\n",
        encoding="utf-8")
    modules = _imports_of(offender)
    assert modules == {"ordessa_harness.configuration.model.backend"}
    assert any(m.startswith("ordessa_harness.")
               and not m.startswith("ordessa_harness_api.") for m in modules)


def test_c21_model_provider_owns_no_process_or_session_coordination_surface():
    """C21: the plugin's surface is provider/model/credentialRef data plus UI
    business. It starts no process, owns no session and never writes a global
    Harness configuration."""
    banned = {"spawn", "start_process", "launch", "Popen", "create_session",
              "session_new", "new_session", "write_global_config",
              "set_global_config", "restart_agent", "kill_process"}
    found = {path.name: sorted(_defined_names(path) & banned)
             for path in sorted(SRC.glob("*.py"))}
    found = {name: hits for name, hits in found.items() if hits}
    assert found == {}

    # And the rule is not vacuous: a synthesised definition is caught.
    assert _defined_names.__call__ is not None
    offender = Path(__file__).resolve().parent / "_synthetic_offender.py"
    try:
        offender.write_text("def spawn(cmd):\n    return cmd\n", encoding="utf-8")
        assert _defined_names(offender) & banned == {"spawn"}
    finally:
        offender.unlink(missing_ok=True)

# --------------------------------------------------------------------------
# C17 -- key removal/replacement governs future preparation only
# --------------------------------------------------------------------------
def test_c17_a_deleted_key_fails_future_preparation_and_never_fakes_anonymous(tmp_path):
    """C17 counterexample: once the key is gone, a declared-credential
    configuration can no longer be prepared -- it refuses typed rather than
    quietly running unauthenticated. The secret itself never crosses the error.
    """
    from ordessa_model_provider.catalog import ModelCatalogService
    from ordessa_model_provider.records import ProviderModelRecords
    from ordessa_model_provider.testing import (
        RecordingSecretStore, harness_descriptor,
    )
    from pacthold.storage import ObjectStore
    from pacthold_runtime_compat.storage import Database
    from ordessa_server.idempotency import IdempotentRecords

    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    objects = ObjectStore(root)
    store = RecordingSecretStore()
    store.deleted = False
    harnesses = FakeHarnesses(
        descriptors={"pi": harness_descriptor(credential_kind="api_key")},
        protocols={"pi": {"openai-chat": ""}},
    )
    catalog = ModelCatalogService(
        ProviderModelRecords(database, IdempotentRecords(database)),
        objects, harnesses=harnesses, credentials=FakeCredentialsLike(),
        secret_store=store,
    )
    ref = "ref://cred-1"
    assert catalog.application_credential(ref, harness_id="pi") == \
        RecordingSecretStore.SENTINEL

    # The key disappears from the store: preparation must refuse, not degrade.
    def refuse_read(locator):
        if locator == "loc://cred-1":
            raise RuntimeError("the keyring entry is gone")
        return RecordingSecretStore.SENTINEL.encode("utf-8")
    store.read = refuse_read
    with pytest.raises(ServerError) as excinfo:
        catalog.application_credential(ref, harness_id="pi")
    assert excinfo.value.code == "CREDENTIAL_UNRESOLVED"
    assert RecordingSecretStore.SENTINEL not in str(excinfo.value)

    # And the declared credential cannot be replaced by an anonymous run:
    # dropping the reference does not change what a *declared* credential means,
    # it only makes a different declaration.
    assert catalog.application_credential(None, harness_id="pi") is None


class FakeCredentialsLike:
    """The minimal credentials port: one stored locator for ``cred-1``."""

    def get(self, credential_id, kind=None):
        if credential_id != "cred-1":
            from ordessa_server.errors import ServerError
            raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found",
                              status=404)
        return {"id": "cred-1", "kind": kind or "api_key",
                "secret_locator": "loc://cred-1"}
