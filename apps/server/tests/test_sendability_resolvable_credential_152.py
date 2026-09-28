"""Work Order 152 (`R-0080`, ACC-R5-4): `sendability: ready` must count "can this
host actually open the credential", not just "does the identity row exist".

A's first-hand reading on the `18790` box: 21 of 22 profiles reported `ready`, 20 of
them behind a Windows DPAPI credential id whose locator cannot be read on Linux -
while the one profile whose credential *was* readable reported `blocked`. The
projection asked only "record present? kind correct?" (`handlers.py:786`) and so
promised a send that would die inside the turn as `EXECUTION_FAILED`. That is the
honesty loop (⑤) meeting the sendability loops (③④): the picker must not lie.

Order 152 adds the one missing step to 117's re-walk: after the identity resolves,
ask the *secret store* whether this host can open the locator (try-read and discard;
the value never leaves the probe). Unopenable -> `blocked` (typed reason + actions);
no locator to ask about -> `unknown`; resolvable -> still `ready`. A Server composed
without any store keeps 117's freeze-equivalent behaviour (out of this order's scope,
which is a store that exists and cannot open *this* host's locator).

Every gate drives the real `profiles.list` wire (G6). 117's own suite is the drift
guard for the earlier steps and stays green untouched.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.transport.http import create_app
from pacthold.storage import MemorySecretStore

from test_wire_v1 import Wire

MODELS = [{"modelId": "model-a", "displayName": "Model A",
           "availability": "unknown", "unavailableReason": None}]
FAKE_SECRET = b"fake-loopback-value-not-a-secret"


def _registry() -> HarnessRegistry:
    reg = HarnessRegistry()
    reg.register(HarnessDescriptor(
        "alpha", capability_claims={"stream": True}, model_control_id="model",
        control_options={"model": ()}, credential_kind="api_key",
        configuration_validator=lambda value: (
            None if isinstance(value, dict) else ValueError()),
    ))
    return reg


class Env:
    def __init__(self, api, runtime, store, tmp_path, headers):
        self.api = api
        self.runtime = runtime
        self.store = store
        self.tmp_path = tmp_path
        self.headers = headers

    def item(self, profile_id):
        items = self.api.ok("profiles.list", {"includeArchived": True})["items"]
        return next(i for i in items if i["id"] == profile_id)

    def sendability(self, profile_id):
        return self.item(profile_id)["sendability"]

    def verdict(self, profile_id):
        sendability = self.sendability(profile_id)
        return sendability["state"], sendability.get("reason")


def _client_and_api(runtime):
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1",
                        raise_server_exceptions=False)
    headers = {"Authorization": f"Bearer {runtime.token}"}
    return client, Wire(client, headers), headers


def _bind(env, *, credential_id, locator):
    """Name a credential (149's single entry), create a provider bound to it, then a
    profile selecting that model. The provider/profile writes all succeed - only the
    sendability projection is meant to catch the unopenable credential."""
    env.runtime.plugin_host.provided_port('product.repository').credentials.register_if_missing(credential_id, "api_key", locator)
    provider = env.api.ok("providerModels.create", {
        "requestId": f"o152-prov-{credential_id}", "displayName": "152 P",
        "harness": "alpha", "provider": "opaque-provider",
        "credentialId": credential_id, "configuration": [], "models": MODELS,
    })["providerModel"]
    created = env.api_ok_profile(credential_id)
    version = env.item(created)["version"]
    env.api.ok("profiles.updateConfig", {
        "requestId": f"o152-cfg-{credential_id}", "profileId": created,
        "expectedVersion": version,
        "values": [{"controlId": "model",
                    "value": {"providerId": provider["id"], "modelId": "model-a"}}],
    })
    return created


def _make_env(tmp_path, *, store):
    runtime = build_runtime(tmp_path / "data", secret_store=store,
                            server_plugins=create_composition().compatibility_plugins(harnesses=_registry()))
    client, api, headers = _client_and_api(runtime)
    env = Env(api, runtime, store, tmp_path, headers)

    def api_ok_profile(tag):
        response = client.post("/api/v1/profiles", headers={**headers, "Idempotency-Key": f"o152-{tag}"},
                               json={"name": "role", "harness_type": "alpha",
                                     "configuration": {}, "credential_id": None})
        assert response.status_code == 201, response.text
        return response.json()["profile_id"]

    env.api_ok_profile = api_ok_profile  # type: ignore[attr-defined]
    return client, env


@pytest.fixture
def env(tmp_path):
    store = MemorySecretStore(values={})
    client, built = _make_env(tmp_path, store=store)
    with client:
        yield built


def _resolvable_locator(env, tag):
    source = env.tmp_path / f"key-{tag}"
    source.write_bytes(FAKE_SECRET)
    _store_id, locator = env.store.import_file(source, "api_key")
    return locator


# -- G1 记录在、本机解析不了 => blocked，整体不 ready（本单主目标）----------

def test_unresolvable_credential_is_blocked_not_ready(env):
    profile = _bind(env, credential_id="cred-dne", locator="credential_absent_in_this_store")
    state, reason = env.verdict(profile)
    assert state == "blocked", env.sendability(profile)
    assert reason == "CREDENTIAL_NOT_RESOLVABLE", env.sendability(profile)
    sendability = env.sendability(profile)
    assert sendability["actions"], sendability
    assert "provision_the_credential_on_this_host" in sendability["actions"]


# -- G2 能解析 => 仍 ready（不许把正常情形打成 blocked）---------------------

def test_resolvable_credential_stays_ready(env):
    locator = _resolvable_locator(env, "good")
    profile = _bind(env, credential_id="cred-good", locator=locator)
    assert env.verdict(profile) == ("ready", None), env.sendability(profile)


# -- G3 问不出来（无 locator 可试）=> unknown，不是 ready --------------------

def test_no_locator_to_probe_is_unknown_not_ready(env):
    profile = _bind(env, credential_id="cred-noloc", locator="")
    state, reason = env.verdict(profile)
    assert state != "ready", env.sendability(profile)
    assert state == "unknown", env.sendability(profile)
    assert reason == "CREDENTIAL_RESOLVABILITY_UNKNOWN", env.sendability(profile)


# -- 反例（门要能咬）：身份存在性相同，只有可解析性翻转 => 判定翻转 ----------

def test_counterexample_resolvability_is_what_moves_the_verdict(env, monkeypatch):
    profile = _bind(env, credential_id="cred-flip", locator="credential_absent_here")
    assert env.verdict(profile)[0] == "blocked"   # record present, secret not openable
    # Give the host the ability to open it; the *same* row must go ready. If the
    # verdict were driven by mere presence (the pre-152 lie), this would not flip.
    monkeypatch.setattr(type(env.store), "read", lambda self, locator: b"ok")
    assert env.verdict(profile)[0] == "ready"


# -- 边界：本机没有组合 secret store => 保持 117 的冻结等价语义（不越界降级）--

def test_server_without_a_store_keeps_prior_ready_semantics(tmp_path):
    client, env = _make_env(tmp_path, store=None)
    with client:
        profile = _bind(env, credential_id="cred-ns", locator="memory:some-locator")
        assert env.verdict(profile) == ("ready", None), env.sendability(profile)


# -- G6 真链 + 不过线：走 profiles.list，密钥形状 grep 必须为空 ---------------

def test_sendability_never_leaks_credential_material(env):
    secret = b"sk-REAL-LOOKING-BUT-fake-loopback-value"
    source = env.tmp_path / "key-leak"
    source.write_bytes(secret)
    _store_id, locator = env.store.import_file(source, "api_key")
    profile = _bind(env, credential_id="cred-leak", locator=locator)
    blob = json.dumps(env.item(profile))
    assert secret.decode() not in blob
    assert "sk-" not in blob
    assert "secret_locator" not in blob
    # The credential is referenced only by id.
    assert "cred-leak" in blob
