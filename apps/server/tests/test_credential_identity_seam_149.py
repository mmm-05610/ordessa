"""Work Order 149 (`R-0078 ①`): an injected credential must BE a bindable identity.

Ops measured the defect on a fresh assembly: the trial launcher puts a secret in
the store under a chosen ``credentialId`` but never registers that name, so the
record layer - which only recognises rows in ``server_credentials``
(``model_configs/repository.py:60``/``:92``) - answers ``CREDENTIAL_NOT_FOUND``
when a provider record binds it, while "only the model id changed" succeeds
(`a-r5-cause-split.json`: ``D2`` fails, ``D2b`` passes). Injection and identity
were two unrelated facts.

The fix is one idempotent identity entry - ``CredentialRecords.register_if_missing``
- that every supported injection path shares, so naming a credential and making it
bindable are a single step that cannot leave the half state.

Every gate drives the bind through the *real* ``providerModels.create``/``update``
wire (G5), never by calling ``credentials.*`` directly. The seam must close the
identity gap **without** widening ``CREDENTIAL_NOT_FOUND``: a credential that was
never injected still refuses typed (G2), which is what the counter-examples pin.
"""
from __future__ import annotations

import copy
import json

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.transport.http import create_app
from pacthold.storage import MemorySecretStore

from test_wire_v1 import Wire

FAKE_SECRET = b"fake-loopback-value-not-a-secret"

MODEL = {"modelId": "model-a", "displayName": "Model A",
         "availability": "unknown", "unavailableReason": None}
PROVENANCE = {
    "baseUrl": "https://api.deepseek.com", "authStyle": "api_key",
    "wireApi": "chat_completions", "fieldsSource": "manual",
}
BASE = {"displayName": "Official API", "harness": "alpha", "provider": "opaque-provider",
        "credentialId": None, "configuration": [], "models": [MODEL]}


def credential_registry():
    """`alpha` declares a credential kind, so binding is allowed and the seam is
    reachable; a credential-incapable harness would refuse every bind here."""
    reg = HarnessRegistry()
    reg.register(HarnessDescriptor(
        "alpha", credential_kind="api-key", capability_claims={"stream": True},
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
    ))
    return reg


class Env:
    def __init__(self, api, runtime, store, tmp_path):
        self.api = api
        self.runtime = runtime
        self.store = store
        self.tmp_path = tmp_path

    @property
    def records(self):
        return self.runtime.plugin_host.provided_port('product.repository').credentials

    def list_records(self):
        return self.api.ok("providerModels.list", {"includeArchived": False})["items"]


@pytest.fixture
def env(tmp_path):
    store = MemorySecretStore(values={})
    runtime = build_runtime(
        tmp_path / "data", secret_store=store,
        server_plugins=create_composition().compatibility_plugins(
            harnesses=credential_registry()),
    )
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        api = Wire(client, {"Authorization": f"Bearer {runtime.token}"})
        yield Env(api, runtime, store, tmp_path)


def body(credential_id, request_id):
    if len(request_id) < 8:  # the wire's requestId shape gate (>= 8 characters)
        request_id = ("o149-seam-" + request_id)[-24:]
    return dict(copy.deepcopy(BASE), requestId=request_id,
                credentialId=credential_id, provenance=PROVENANCE)


def inject(env, credential_id, *, content=FAKE_SECRET):
    """One supported injection path: import the secret, then name the identity via
    the single shared entry. This is what a corrected launcher / 151's wire entry
    does; the return is ``(register_if_missing result, locator)``."""
    source = env.tmp_path / f"key-{credential_id}-{len(content)}-{hash(content) & 0xffff}"
    source.write_bytes(content)
    _store_id, locator = env.store.import_file(source, "api-key")
    result = env.records.register_if_missing(credential_id, "api-key", locator)
    return result, locator


# -- G1 新鲜装配可绑：注入的凭据经真实 wire 绑定成功 ---------------------

def test_fresh_assembly_injected_credential_binds_through_real_wire(env):
    before = len(env.list_records())
    result, _locator = inject(env, "cred-inj")
    assert result["created"] is True

    record = env.api.ok("providerModels.create", body("cred-inj", "o149-g1"))["providerModel"]
    assert record["credentialId"] == "cred-inj"

    after = env.list_records()
    assert len(after) == before + 1
    assert any(item["id"] == record["id"] for item in after)
    # The identity is resolvable kind-aware at the record layer (a real row, not an echo).
    env.records.get("cred-inj", kind="api-key")


# -- G2 反例：不存在的 id 仍然类型化拒绝，记录行不增 ----------------------

def test_binding_a_never_injected_credential_still_refuses_typed(env):
    before = len(env.list_records())
    error = env.api.err("providerModels.create", body("cred-ghost", "o149-g2"))
    assert error["code"] == "NOT_FOUND"
    assert error["details"]["internalCode"] == "CREDENTIAL_NOT_FOUND"
    # The seam must not widen the family into "bind anything": no row was added.
    assert len(env.list_records()) == before


# -- G3 幂等：同一身份声明两次，不抛错、不重复行、不覆盖、不重读密钥 ------

def test_the_identity_entry_is_idempotent_and_never_overwrites(env):
    first, loc1 = inject(env, "cred-twice", content=b"AAAA")
    assert first["created"] is True

    second, loc2 = inject(env, "cred-twice", content=b"BBBB")
    assert loc2 != loc1
    assert second["created"] is False
    # The already-resolved name is kept exactly: original locator, not the new one.
    assert second["secret_locator"] == loc1

    rows = [row for row in env.records.list() if row["credentialId"] == "cred-twice"]
    assert len(rows) == 1


# -- G4 半状态可判：密钥在场而身份未建，绝不静默；命名即闭合 --------------

def test_injected_but_unregistered_is_visible_never_silent(env):
    source = env.tmp_path / "orphan-key"
    source.write_bytes(FAKE_SECRET)
    _store_id, locator = env.store.import_file(source, "api-key")

    # The record layer can JUDGE the gap - a secret is present, the identity is not.
    assert env.records.exists("cred-orphan") is False
    error = env.api.err("providerModels.create", body("cred-orphan", "o149-g4"))
    assert error["code"] == "NOT_FOUND"
    assert error["details"]["internalCode"] == "CREDENTIAL_NOT_FOUND"

    # Naming it through the shared entry closes the gap (the fix the launcher uses),
    # and `created` reported the transition so a caller could fail-fast at startup.
    result = env.records.register_if_missing("cred-orphan", "api-key", locator)
    assert result["created"] is True
    assert env.records.exists("cred-orphan") is True
    record = env.api.ok("providerModels.create", body("cred-orphan", "o149-g4b"))["providerModel"]
    assert record["credentialId"] == "cred-orphan"


# -- G5 真链：改绑也走真实 wire，并由另一个 wire 方法读回（非写入的回声） --

def test_rebind_flows_through_real_wire_update(env):
    inject(env, "cred-a")
    inject(env, "cred-b")
    record = env.api.ok("providerModels.create", body("cred-a", "o149-g5"))["providerModel"]
    assert record["credentialId"] == "cred-a"

    updated = env.api.ok("providerModels.update", {
        "requestId": "o149-g5u", "providerModelId": record["id"],
        "expectedVersion": record["version"], "displayName": record["displayName"],
        "credentialId": "cred-b", "configuration": [], "models": [MODEL],
    })["providerModel"]
    assert updated["credentialId"] == "cred-b"

    listed = {item["id"]: item for item in env.list_records()}
    assert listed[record["id"]]["credentialId"] == "cred-b"


# -- 反例（门要能咬）：把身份建立那一步做成 no-op ⇒ G1 的正例必须红 --------

def test_counterexample_dropping_the_identity_step_breaks_the_bind(env, monkeypatch):
    # Simulate the old launcher: the secret reaches the store, but no identity row
    # is ever established (register_if_missing reduced to a no-op).
    monkeypatch.setattr(
        type(env.records), "register_if_missing",
        lambda self, credential_id, kind, locator: {
            "credential_id": credential_id, "kind": kind, "created": False},
    )
    inject(env, "cred-x")
    error = env.api.err("providerModels.create", body("cred-x", "o149-counter"))
    assert error["code"] == "NOT_FOUND"
    assert error["details"]["internalCode"] == "CREDENTIAL_NOT_FOUND"


# -- G6 无凭据外泄：返回/列举只出 id/kind，密钥形状 grep 必须为空 ----------

def test_no_credential_material_crosses_the_wire(env):
    secret = b"sk-REAL-LOOKING-BUT-fake-loopback-value"
    inject(env, "cred-leak", content=secret)
    created = env.api.ok("providerModels.create", body("cred-leak", "o149-g6"))
    listed = env.api.ok("providerModels.list", {"includeArchived": False})
    blob = json.dumps(created) + json.dumps(listed)

    assert secret.decode() not in blob
    assert "sk-" not in blob
    # The locator says where a secret lives; it is a Server-internal address, never on the wire.
    assert "secret_locator" not in blob and "locator" not in blob


# -- 形制：本单的幂等入口是记录层唯一的那条，`register` 仍是裸 INSERT -------

def test_register_if_missing_is_the_single_idempotent_entry():
    """`register()` stays a bare INSERT (non-idempotent) so the existing callers'
    behaviour is verbatim; the idempotent semantics live in exactly one place -
    `register_if_missing` - which 151's wire entry must reuse rather than define a
    second one. A duplicate INSERT guard must not reappear in this class."""
    import inspect

    from ordessa_server.credentials import CredentialRecords

    source = inspect.getsource(CredentialRecords)
    assert source.count("INSERT INTO server_credentials") == 2  # register + register_if_missing
    # `register` has no existence guard (it is the raw one); `register_if_missing` does.
    register_body = inspect.getsource(CredentialRecords.register)
    assert "SELECT" not in register_body
    seam_body = inspect.getsource(CredentialRecords.register_if_missing)
    assert "SELECT" in seam_body and "created" in seam_body
