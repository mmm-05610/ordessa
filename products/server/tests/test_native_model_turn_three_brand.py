"""M13: Pi, Codex and Claude each prove the model application really travels
the registered Harness port of that brand (021 zcode closeout §5 M13).

What "really" means here, and what it does not:

- REAL: the product composition (``native_runtime``), the neutral authority
  (``native.configuration``), the C4 ``ConfigurationApplicationService`` with
  its shared journal and fences, the brand's own registered C2 adapter
  (``BridgeConfigurationAdapter`` for that brand, published through
  ``harness.configuration-adapters``), the brand's own live runtime class
  (``PiLiveModelRuntime`` / ``CodexLiveModelRuntime`` /
  ``ClaudeLiveModelRuntime``), the brand dialect compiler
  (``compile_live_model`` for pi, ``compile_native_model`` for codex and
  claude-code), the brand's ``NativeSessionActionExecutor`` and the
  installation trust verification - which runs the real Node policy against
  the real root-owned installed assets and returns the real
  ``installed-<brand>:sha256:...`` evidence reference.
- CONTROLLED: only the deep native ACP agent process (the channel that would
  host the brand's ACP adapter). It is a per-brand double that speaks that
  brand's native configuration dialect - Pi's ``provider/model`` option value
  encoding, Codex's ``custom-gateway``/``responses`` route facts,
  Claude's ``main``/``anthropic`` route facts - and it records what the brand
  port received. No model, no network, no prompt, no native process is spawned.

The two counter-examples M13 names are pinned here:

1. production "fake supported" - an answer that does not cite the brand's
   registered adapter, runtime and executor. Every ``ready`` below must carry
   a brand-prefixed native operation evidence ref, a brand-prefixed C4
   read-back evidence ref, an adapter id equal to the brand's registered one,
   and a real installation evidence ref.
2. cached request read-back - a ``ready`` whose read-back is the requested
   value. The drift case makes the brand port report an observed value that
   differs from the requested one; the outcome must then be ``unknown`` with
   zero prompt, and the independent read-back port must report the OBSERVED
   value, never the request.

Evidence grade of this module, and where the real-process evidence lives
(F3 review gap, 2026-10-02):

- This module stays at CONTROLLED level for the deep native ACP agent process
  and is NOT upgraded by anything below. The doubles above are deliberate and
  stay: reaching the drift and re-read counter-examples without a model is
  exactly what they are for.
- The real-adapter-process evidence that closes the F3 gap is kept out of tree,
  beside the probe that produced it:
  ``.cleanup-evidence/zcode-profile-model/f3-real-process-<brand>.json`` for
  ``pi`` / ``codex`` / ``claude-code``, rolled up in
  ``.cleanup-evidence/zcode-profile-model/f3-summary.json``; probe
  ``f3-real-process-probe.mjs``, roll-up ``f3-summarise.mjs``. It spawns each
  brand's own installed, root-owned adapter entry, resolved through the
  production launch authority and the real trust gate, then drives
  ``initialize -> session/new -> <manifest configurationQuery> -> session/close``
  with every turn-starting method on a hard denylist (prompt count is 0 by
  construction) and a local refusal endpoint that counts inference attempts
  (measured 0 for all three brands).
- Recorded result: ``pi`` and ``claude-code`` complete the sequence with no
  precondition at all; ``codex``'s bare ``session/new`` is refused with -32000
  ``Authentication required`` and only proceeds after the product's own
  no-model provider-registration route (``_ordessa/channel/configuration/prepare``)
  is satisfied with a synthetic non-credential endpoint. That precondition is
  recorded, not hidden. T05 evidence level is the Lead's call; this module's
  own grade is unchanged either way.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from shutil import which
from types import SimpleNamespace

import pytest

from ordessa_harness.configuration.model.bridge import ADAPTER_IDS
from ordessa_harness.server_acp.native_action_executor import configuration_digest
from ordessa_harness.server_acp.registry import (
    NativeConfigurationObservation, NativeSessionObservation,
)
from ordessa_harness_api import Installation

from ordessa_server_product.composition import create_composition

ROOT = Path(__file__).resolve().parents[3]
ENDPOINT = "http://127.0.0.1:8765/v1"

#: The three installed, root-owned asset roots the product plan selects by
#: default (products/desktop/native-product-plan.mjs). Read-only: the same
#: roots the launch plan verifies; nothing here installs or writes.
BRAND_ASSET_ROOTS = {
    "pi": "/opt/ordessa/harnesses/profile-pi-registration-owner-bound/artifacts",
    "codex": "/opt/ordessa/harnesses/profile-codex-catalog-fast-off-v6/artifacts",
    "claude-code": "/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts",
}

#: Each brand's native configuration dialect, as its own installed adapter
#: publishes it. These are NOT one template: pi encodes the option value as
#: ``provider/model`` and allows a partial choice, while codex and claude-code
#: expose the bare model id and demand an exact observed native route
#: (plugins/harness/src/ordessa_harness/configuration/model/live_model.py).
BRANDS = {
    "pi": {
        "protocol": "openai-chat",
        "protocols": ["openai-chat"],
        "native_value": lambda model: f"acme/{model}",
        "route": {"provider": "acme", "api": "openai-completions"},
        "runtime_class": "PiLiveModelRuntime",
        # the brand runtime refuses any installation whose verified native
        # version is not its own pin
        "native_version": (0, 5, 0),
    },
    "codex": {
        "protocol": "openai-responses",
        "protocols": ["openai-responses"],
        "native_value": lambda model: model,
        "route": {"provider": "custom-gateway", "api": "responses"},
        "runtime_class": "CodexLiveModelRuntime",
        "native_version": (1, 1, 14),
    },
    "claude-code": {
        "protocol": "anthropic-messages",
        "protocols": ["anthropic-messages"],
        "native_value": lambda model: model,
        "route": {"provider": "main", "api": "anthropic"},
        "runtime_class": "ClaudeLiveModelRuntime",
        "native_version": (0, 81, 2),
    },
}


def target_of(brand):
    return {"serverInstanceId": "srv-1", "harnessId": brand, "acpSessionId": "s-1"}


class BrandChannel:
    """The controlled native agent boundary for one brand.

    It serves that brand's native selector dialect and answers the brand's
    ``_ordessa/session/configuration/apply`` with the operation-bound record the
    executor verifies. ``drift_to`` programs the case where the native port
    reports an observed value DIFFERENT from the requested one.
    """

    ended = False
    workspace_id = "workspace"
    transport = None
    execution_id = "controlled-execution"
    session_id = "ledger-session"

    def __init__(self, brand, state):
        self.harness_id = brand
        self._state = state
        self.operations: list[dict] = []

    @property
    def pair(self):
        return (self.harness_id, self.workspace_id)

    def finish(self):
        pass

    def native_session_observation(self, native_id):
        """The channel-level fact the real registry method delegates to."""
        return self._state["owner"] if native_id == "s-1" else None

    def _configuration_rpc(self, native_id, method, params, *, timeout=10):
        assert method == "_ordessa/session/configuration/apply"
        requested = params["value"]
        observed = self._state["drift_to"] or requested
        options = deepcopy(self._state["options"])
        for option in options:
            if option.get("id") == params["configId"]:
                option["currentValue"] = observed
        self._state["options"] = options
        digest = configuration_digest(options)
        record = {
            "operationId": params["operationId"], "state": "observed",
            "generation": self._state["generation"],
            "target": asdict(self._state["target"]),
            "manifestDigest": sha256(json.dumps(
                params["actionManifest"], sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest(),
            "beforeConfigDigest": params["expectedConfigDigest"],
            "configId": params["configId"], "requestedValue": requested,
            "observedValue": observed,
            "after": {"generation": self._state["generation"], "sessionId": native_id,
                      "busy": False, "configOptions": options},
            "afterConfigDigest": digest,
            # The executor demands the brand's own operation evidence prefix.
            "evidenceRef": f"{self.harness_id}-native-operation:controlled",
        }
        self.operations.append(record)
        return self._state["owner"], record


def options_of(brand, models, current="legacy/m0"):
    """The brand's own native model selector, with its own route metadata.

    Codex and Claude expose the bare model id as the option value and publish
    the native route under ``_meta.ordessaModel``; Pi publishes the
    ``provider/model`` encoding. A brand's compiler reads exactly this.
    """
    dialect = BRANDS[brand]
    initial = dialect["native_value"](current)
    entries = [{"value": initial, "name": "initial"}]
    for model in models:
        entries.append({"value": dialect["native_value"](model), "name": model,
                        "_meta": {"ordessaModel": dict(
                            dialect["route"], model=model, baseUrl=ENDPOINT)}})
    return [{"id": "model", "type": "select", "currentValue": initial,
             "options": entries}]


def runtime_at(tmp_path, brand, *, include_profile=False):
    return create_composition().native_runtime(
        tmp_path / f"data-{brand}", plugin_root=ROOT / "plugins/harness",
        harness_id=brand, adapter_command=which("node"),
        installed_artifact_root=BRAND_ASSET_ROOTS[brand],
        include_profile=include_profile)


def controlled_native(monkeypatch, runtime, brand, *, models=("m1", "m2")):
    """Point the real composition at the controlled native agent boundary.

    The installation route is NOT stubbed: ``verify`` stays the real trust
    verification over the real installed asset root, so the evidence this
    test cites is produced by the shipped policy, not by a fixture.
    """
    state = {"owner": NativeSessionObservation("connection", "execution",
                                               "ledger-session", "s-1"),
             "generation": "native-generation-1",
             "options": options_of(brand, models), "target": None,
             "drift_to": None}
    channel = BrandChannel(brand, state)
    registry = runtime.plugin_host.provided_port("acp.channels")
    registry._by_id["connection"] = channel
    monkeypatch.setattr(registry, "query_native_configuration",
                        lambda connection_id, native_id, timeout=10:
                        NativeConfigurationObservation(state["owner"], state["generation"],
                                                       False, json.dumps(state["options"])))
    authority = runtime.plugin_host.provided_port("native.configuration")
    # the controlled channel carries no real run record; the release path has
    # nothing honest to settle for it
    import ordessa_harness.server_acp.registry as acp_registry
    monkeypatch.setattr(acp_registry, "end_run_released", lambda *args, **kwargs: None)
    return SimpleNamespace(state=state, channel=channel, registry=registry,
                           authority=authority)


def bind_native(controlled, brand):
    binding = controlled.authority.ensure_native(harness_id=brand,
                                                 native_session_id="s-1")
    assert binding is not None
    controlled.state["target"] = binding.snapshot.target
    return binding


def seed_provider(runtime, brand, model_ids=("m1", "m2")):
    from ordessa_model_provider.testing import wire_body

    dialect = BRANDS[brand]
    return runtime.wire.dispatch("providerModels.create", {
        "requestId": f"m13-seed-{brand}", **wire_body(harness=brand, provider="acme",
        models=[
            {"modelId": model, "displayName": model, "availability": "available",
             "unavailableReason": None} for model in model_ids]),
        "configuration": [], "protocols": dialect["protocols"],
        "endpoints": {dialect["protocol"]: ENDPOINT},
    })["providerModel"]


def model_plugin(runtime):
    return next(plugin for plugin in runtime.plugin_selection
                if plugin.descriptor().id == "ordessa.model-provider")


def queue_model(runtime, brand, record, model, key):
    pending = runtime.wire.dispatch("modelProvider.chooseForSession", {
        "target": target_of(brand),
        "choice": {"harnessId": brand, "providerConfigId": record["id"], "modelId": model},
        "operationKey": f"{key}-queue-op"})
    assert pending["outcome"] == "pending-next-turn"
    return pending


def submit(runtime, brand, pending, key):
    return runtime.wire.dispatch("modelProvider.beginTurnApplication", {
        "target": target_of(brand), "operationKey": f"{key}-submit-op",
        "expectedSequence": pending["sequence"]})


def apply_model(runtime, brand, record, model, key):
    return submit(runtime, brand, queue_model(runtime, brand, record, model, key), key)


# -- M13: each brand applies through its own registered port ------------------------


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_brand_model_application_travels_its_registered_harness_port(
        tmp_path, monkeypatch, brand):
    runtime = runtime_at(tmp_path, brand)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime, brand)
        # The installation route the composition will use is the real one:
        # root-owned asset, manifest and tree digest verified by the shipped
        # policy. A missing/foreign/tampered asset would raise here.
        installation = controlled.authority.services.verify(brand)
        assert installation.harness_id == brand
        assert installation.evidence_ref.startswith(f"installed-{brand}:sha256:")

        # exactly one published C2 adapter for THIS brand, and it is the
        # registered per-brand adapter id (never a generic stand-in)
        views = [view for view in controlled.authority.services.carrier.contributions(
            "harness.configuration-adapters")
            if view.payload.descriptor.adapter_id == ADAPTER_IDS[brand]]
        assert len(views) == 1
        assert views[0].payload.brand == brand

        plugin = model_plugin(runtime)
        assert type(plugin._harness_config_port).__name__ == "NativeModelEligibilityPort"
        # the legacy pseudo read-back entry is never the application path
        with pytest.raises(Exception):
            plugin._harness_config_port.apply(target_of(brand), {"modelId": "m1"})

        bind_native(controlled, brand)
        record = seed_provider(runtime, brand)
        answer = apply_model(runtime, brand, record, "m1", "m13")
        assert answer["outcome"] == "ready", answer
        application = answer["application"]
        assert application["operationId"]
        assert application["nativeTarget"]["canonicalUid"].startswith("profile-session-")
        assert application["nativeTarget"]["owner"] == "connection:s-1"
        assert application["appliedRevision"]

        # 1. the brand port is the one that was called, in the brand's dialect
        assert len(controlled.channel.operations) == 1
        operation = controlled.channel.operations[0]
        assert operation["configId"] == "model"
        assert operation["requestedValue"] == BRANDS[brand]["native_value"]("m1")
        assert operation["evidenceRef"].startswith(f"{brand}-native-operation:")
        # the executor, not the double, decides the verdict; here it accepted
        assert operation["observedValue"] == operation["requestedValue"]

        # 2. the C4 read-back is this brand's own independent query
        assert application["evidenceRef"].startswith(f"{brand}-independent-query:")
        assert application["evidenceRef"] != operation["evidenceRef"]

        # 3. the live runtime really is the brand's runtime class
        binding = controlled.authority.observed_native(harness_id=brand,
                                                       native_session_id="s-1")
        _, native_runtime = controlled.authority.create_service(binding.snapshot.target)
        assert type(native_runtime).__name__ == BRANDS[brand]["runtime_class"]
        assert native_runtime.harness_id == brand
        assert native_runtime.installation.evidence_ref == installation.evidence_ref
        # the runtime only accepts the verified installation whose native
        # version is its own pin, so this is the version the trust check read
        assert native_runtime.installation.native_version == BRANDS[brand]["native_version"]
        assert native_runtime.installation.native_version == native_runtime.native_version

        # 4. the independent read-back port reports the NATIVE observation
        observed = plugin._harness_config_port.read_back(target_of(brand))
        assert observed["model"] == "m1"
        assert observed["nativeValue"] == BRANDS[brand]["native_value"]("m1")
    finally:
        runtime.stop()


# -- M13 counter-example 2: a read-back that is not the native observation ----------


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_readback_diverging_from_the_native_observation_is_never_ready(
        tmp_path, monkeypatch, brand):
    """The native port reports a value the request never asked for.

    That is the shape of a cached-request read-back and of a native agent that
    did not actually apply the selection. Either way the answer must be
    ``unknown`` - zero prompt, no application evidence - and the independent
    read-back must surface the OBSERVED value, not the requested one.
    """
    runtime = runtime_at(tmp_path, brand)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime, brand)
        bind_native(controlled, brand)
        record = seed_provider(runtime, brand)
        controlled.state["drift_to"] = BRANDS[brand]["native_value"]("m2")
        answer = apply_model(runtime, brand, record, "m1", "m13-drift")
        assert answer["outcome"] == "unknown"
        assert answer["application"] is None
        # the effect really was attempted and the record really disagrees
        assert len(controlled.channel.operations) == 1
        operation = controlled.channel.operations[0]
        assert operation["requestedValue"] == BRANDS[brand]["native_value"]("m1")
        assert operation["observedValue"] == BRANDS[brand]["native_value"]("m2")
        assert operation["observedValue"] != operation["requestedValue"]
        # the read-back port is a live observation of the native owner, and it
        # reports what the native port said, not what the request asked for
        observed = model_plugin(runtime)._harness_config_port.read_back(target_of(brand))
        assert observed["model"] == "m2"
        assert observed["nativeValue"] == BRANDS[brand]["native_value"]("m2")
    finally:
        runtime.stop()


# -- C03, brand dimension: absent brand port / unsupported resource ---------------


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_absent_brand_native_port_refuses_typed_with_zero_prompt(
        tmp_path, monkeypatch, brand):
    """The brand's native port is gone: the queue itself refuses typed, and no
    native operation is ever attempted. An "unknown but queued anyway" intent
    here would be the fake M13 forbids."""
    runtime = runtime_at(tmp_path, brand)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime, brand)
        bind_native(controlled, brand)
        record = seed_provider(runtime, brand)
        # the brand's own native owner disappears from the registry
        del controlled.registry._by_id["connection"]
        from server_plugin_api import WireError
        with pytest.raises(WireError) as refused:
            queue_model(runtime, brand, record, "m1", "m13-absent")
        assert refused.value.details["internalCode"] == "SELECTION_UNSUPPORTED"
        assert controlled.channel.operations == []
    finally:
        runtime.stop()


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_brand_port_lost_between_queue_and_submit_refuses_typed(
        tmp_path, monkeypatch, brand):
    """The port was live when the intent was queued and is gone at submit.

    The submit gate must answer a typed refusal with zero prompt and no
    application evidence, and it must keep the frozen intent (FR-06: a refusal
    never silently drops the user's choice).
    """
    runtime = runtime_at(tmp_path, brand)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime, brand)
        bind_native(controlled, brand)
        record = seed_provider(runtime, brand)
        pending = queue_model(runtime, brand, record, "m1", "m13-lost")
        del controlled.registry._by_id["connection"]
        answer = submit(runtime, brand, pending, "m13-lost")
        assert answer["outcome"] == "refused"
        assert answer["application"] is None
        assert "TARGET_STALE" in answer["reason"]
        assert answer["sequence"] == pending["sequence"]
        assert controlled.channel.operations == []
    finally:
        runtime.stop()


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_model_absent_from_the_brand_native_catalog_refuses_typed(
        tmp_path, monkeypatch, brand):
    """The brand port is present but does not expose the requested model.

    The brand's own compiler refuses; nothing is applied and nothing prompts.
    A "supported" answer here would be exactly the fake M13 forbids.
    """
    runtime = runtime_at(tmp_path, brand)
    try:
        runtime.start()
        controlled = controlled_native(monkeypatch, runtime, brand,
                                       models=("m9-not-this-one",))
        bind_native(controlled, brand)
        record = seed_provider(runtime, brand, model_ids=("m1",))
        answer = apply_model(runtime, brand, record, "m1", "m13-unsupported")
        assert answer["outcome"] == "refused"
        assert answer["application"] is None
        # the refusal is the brand compiler's own code, quoted through C4
        assert answer["reason"].startswith("capability-unsupported")
        assert controlled.channel.operations == []
    finally:
        runtime.stop()
