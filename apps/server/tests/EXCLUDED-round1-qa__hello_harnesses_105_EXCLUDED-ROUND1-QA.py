"""Order 105: `server.hello` publishes the family directory the registry holds.

The list has to come from the registry and nowhere else. Records are user data:
a fresh deployment has none, and deriving a directory from them is what left a
client with "custom harness" as the only option. So the gates here are set
equality against the registry (including *shrinking* it), the absence of
anything the family did not declare, and the locked wire artifact - checked by
digest, then used to validate a live response. The artifact had to be widened
for this key to be legal at all (`ed6592b7`); a later drift in either tree
shows up here as a red gate rather than a quiet "clients will cope".
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_server.execution import HarnessDescriptor, HarnessRegistry

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

#: Registered deliberately out of alphabetical order: an insertion-ordered list
#: and a sorted one are only distinguishable if they differ.
def registry() -> HarnessRegistry:
    reg = HarnessRegistry()
    reg.register(HarnessDescriptor(
        "zeta", capability_claims={"stream": True}, control_options={},
    ))
    reg.register(HarnessDescriptor(
        "alpha", capability_claims={"stream": True}, control_options={},
        credential_kind="api_key", model_control_id="model",
    ))
    reg.register(HarnessDescriptor(
        "mido", capability_claims={}, control_options={}, credential_kind="oauth",
    ))
    return reg


def build(tmp_path, *, harnesses):
    runtime = build_runtime(tmp_path / "data", harnesses=harnesses)
    return runtime, create_app(runtime)


@pytest.fixture
def hello(tmp_path):
    runtime, app = build(tmp_path, harnesses=registry())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        api = Client(client, runtime.token)
        yield runtime, api, api.hello()


class Client:
    def __init__(self, client, token):
        self.client = client
        self.token = token
        self.n = 0

    def hello(self):
        self.n += 1
        response = self.client.post("/wire/v1/server.hello", headers=self.headers,
                                    json={"jsonrpc": "2.0", "id": f"h{self.n}",
                                          "method": "server.hello", "params": HELLO})
        assert response.status_code == 200, response.text
        body = response.json()
        assert "result" in body, body
        return body["result"]

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def call(self, method, params):
        self.n += 1
        return self.client.post(f"/wire/v1/{method}", headers=self.headers,
                                json={"jsonrpc": "2.0", "id": f"c{self.n}",
                                      "method": method, "params": params}).json()


# -- G1: the list *is* the registry ----------------------------------------

def test_hello_lists_exactly_the_registered_families(hello):
    runtime, _api, result = hello
    assert [entry["id"] for entry in result["harnesses"]] == list(runtime.plugin_host.provided_port('harness.directory').registered())
    assert [entry["id"] for entry in result["harnesses"]] == ["alpha", "mido", "zeta"]


def test_the_order_is_the_registries_own_and_reproducible(hello):
    """Two calls, same list - and *not* the order they were registered in.

    Insertion order was zeta, alpha, mido; both the registry and hello answer
    alpha, mido, zeta. If a later change sorted in the handler as well, the two
    sorts can drift; this says which one is authoritative.
    """
    _runtime, api, first = hello
    assert [entry["id"] for entry in first["harnesses"]] == ["alpha", "mido", "zeta"]
    second = api.hello()
    assert json.dumps(first["harnesses"]) == json.dumps(second["harnesses"])


def test_removing_a_family_from_the_registry_removes_it_from_hello(hello):
    """The counter-example the order asks for, run against the live registry.

    Also the proof that the list is not derived from records: a Profile row for
    `alpha` is created first, so a record-backed list would still say `alpha`
    after the registry forgot it.
    """
    runtime, api, _before = hello
    api.call("profiles.create", {"requestId": "harn-profile-1", "displayName": "R",
                                 "harness": "alpha"})
    del runtime.plugin_host.provided_port('harness.directory')._descriptors["mido"]  # noqa: SLF001 - the registry's own state is the subject
    after = api.hello()
    assert [entry["id"] for entry in after["harnesses"]] == ["alpha", "zeta"]


def test_a_family_declaring_nothing_shares_only_its_id(hello):
    """`credentialKind` / `modelControlId` are declarations, not columns: an
    undeclared one is absent, never a null the client has to distrust."""
    _runtime, _api, result = hello
    by_id = {entry["id"]: entry for entry in result["harnesses"]}
    assert by_id["alpha"] == {"id": "alpha", "credentialKind": "api_key", "modelControlId": "model"}
    assert by_id["mido"] == {"id": "mido", "credentialKind": "oauth"}
    assert by_id["zeta"] == {"id": "zeta"}
    assert all("credentialKind" not in entry or entry["credentialKind"] is not None
               for entry in result["harnesses"])


# -- G3: the empty deployment ---------------------------------------------

def test_a_deployment_with_no_families_answers_an_empty_list_not_an_error(tmp_path):
    """`build_runtime()` without a registry registers nothing, so this is the
    shape every in-process composition of this tree already has."""
    runtime, app = build(tmp_path, harnesses=HarnessRegistry())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        result = Client(client, runtime.token).hello()
    assert result["harnesses"] == []
    assert len(result["capabilities"]) == 67


# -- G2: declarations only, no implementation ------------------------------

def test_the_family_list_publishes_declarations_and_nothing_else(hello):
    _runtime, _api, result = hello
    allowed = {"id", "credentialKind", "modelControlId"}
    for entry in result["harnesses"]:
        assert set(entry) <= allowed, entry
    text = json.dumps(result["harnesses"]).lower()
    for tell in ("credentialenvironment", "adapter", "controloptions", "capabilityclaims",
                 "securitylockedcontrols", "sha256", "digest", "c:\\", "/home/", "/mnt/",
                 ".agentbox", "token", "secret"):
        assert tell not in text, tell
    assert all(entry["id"] in runtime_names(result) for entry in result["harnesses"])


def runtime_names(result):
    return {entry["id"] for entry in result["harnesses"]}


def test_harness_ids_do_not_leak_into_the_capability_table(hello):
    """§明确不做: the family list is not a method list. A client that confuses
    them would gate a method on a harness name; keep the vocabularies apart."""
    _runtime, _api, result = hello
    capability_ids = {item["id"] for item in result["capabilities"]}
    assert capability_ids & {entry["id"] for entry in result["harnesses"]} == set()


# -- the field 092 added: landed on the descriptor, still not published here --

def test_wire_protocols_reached_the_descriptor_and_is_still_not_published(hello):
    """The replacement this pin asked for. The previous version asserted
    `wire_protocols` was absent from `HarnessDescriptor` *because 092 had not
    landed yet*, and said so: "when 092 adds the field it goes red and the
    replacement - publish the key set - is a deliberate edit."

    092 has landed in the LNX-002 integration base (the runtime line carries
    `execution/__init__.py:_validate_wire_protocols` and
    `bootstrap/runtime.py` wires the seat map in), so the field is asserted
    present by name here rather than assumed away.

    What did **not** change: `server.hello` still publishes only what a family
    declares, and the family directory stays `{id, credentialKind?,
    modelControlId?}`. Protocol facts ride the `providerModels` read face (092
    stage 2), which is a different surface — and the registered artifact encodes
    exactly that, so `test_the_relocked_artifact_accepts_what_the_server_emits`
    above would refuse an `wireProtocols` key appearing here unannounced.
    """
    fields = {f.name for f in dataclasses.fields(HarnessDescriptor)}
    assert "wire_protocols" in fields
    _runtime, _api, result = hello
    assert all("wireProtocols" not in entry for entry in result["harnesses"])


# -- the relock: registered, and still falsifiable -------------------------

#: Order 113 moved this copy out of `generated/` and into `contract/`, named for
#: the digest it must hash to. The old path advertised "the artifact" while being
#: a copy; a file whose name is its own hash cannot quietly stop being current.
ARTIFACT = (pathlib.Path(__file__).resolve().parents[3]
            / "docs/server-round1/fullstack/contract"
            / "wire-v1.schema.registered-b1eb4762.json")

#: The pair this tree registers. The relock landed in the settings line at
#: `ed6592b7`, encoding the shape this Server actually emits; the digest below
#: is that artifact, copied into this tree so the gate is reproducible here.
#:
#: LNX-002 (2026-09-21) re-registered this pair: the artifact now also declares
#: the profile read-face facts the Server already emitted (`recoveryPending`,
#: `sendability`) and the two `provenance` params the Server already accepted, so
#: `server.hello#result` is unchanged but the file it lives in is new. `harnesses`
#: — the face this order pins — is byte-for-byte the same shape.
ARTIFACT_SHA256 = "b1eb4762b2a8e13e873967b770854e5e73a948488d4d066da07bc584e693dcd1"


def _hello_schema():
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["server.hello#result"]


def test_the_relocked_artifact_accepts_what_the_server_emits(hello):
    """G4. Before `ed6592b7` this assertion was the *refusal* of the new key;
    flipping it to acceptance is what "the relock is done" means in code, and
    the digest check keeps the two trees honest about which artifact that is."""
    import hashlib

    import jsonschema

    assert hashlib.sha256(ARTIFACT.read_bytes()).hexdigest() == ARTIFACT_SHA256
    _runtime, _api, result = hello
    jsonschema.validate(result, _hello_schema())


@pytest.mark.parametrize("tamper", [
    pytest.param(lambda entry: entry.update({"credentialEnvironment": "/home/x/.agentbox"}),
                 id="undeclared-key"),
    pytest.param(lambda entry: entry.update({"credentialKind": None}),
                 id="null-instead-of-absent"),
    pytest.param(lambda entry: entry.pop("id"), id="id-less-entry"),
])
def test_the_locked_shape_still_refuses_what_must_not_be_sent(hello, tamper):
    """The falsification for the gate above: `additionalProperties: false`,
    `required: [id]` and "string, not null" are precisely the three ways a later
    change could leak an implementation detail or invent a declaration."""
    import jsonschema

    _runtime, _api, result = hello
    assert result["harnesses"], "the tamper cases need a populated directory"
    entry = dict(result["harnesses"][0])
    tamper(entry)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**result, "harnesses": [entry]}, _hello_schema())


def test_the_four_old_fields_are_exactly_unchanged(hello):
    """§必须保持不变: `capabilities` keeps 097's shape, and the new key is the
    only addition to the envelope."""
    runtime, _api, result = hello
    assert set(result) == {"serverId", "protocolVersion", "capabilities", "auth", "harnesses"}
    assert result["protocolVersion"] == "wire/1"
    assert result["auth"] == {"required": True, "schemes": ["session_token"]}
    rows = result["capabilities"]
    assert len(rows) == len(runtime.wire._handlers)  # noqa: SLF001 - 097's invariant
    for row in rows:
        assert set(row) == ({"id", "supported", "reason"} if not row["supported"]
                            else {"id", "supported"})
