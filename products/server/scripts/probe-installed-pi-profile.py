"""Explicit installed-product probe; synthetic key, two sessions, zero prompts.

This validates launch/isolation/readback, not Profile application authorization.
Run with this checkout's installed Python packages or explicit source PYTHONPATH.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import argparse

from ordessa_server_product.composition import create_composition
from ordessa_harness_api import ApplicationTarget


def probe(artifact_root="/opt/ordessa/harnesses/artifacts", *, apply_profile=False):
    root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="ordessa-installed-profile-") as temporary:
        private = Path(temporary)
        for name in ("home", "project"):
            (private / name).mkdir(mode=0o700)
        # This probe's own process must not pass real credentials to adapters.
        os.environ.clear()
        os.environ.update(PATH=os.defpath, HOME=str(private / "home"), PI_OFFLINE="1",
            ANTHROPIC_API_KEY="ordessa-nomodel-fixture-not-a-real-credential")
        module = (root / "plugins/harness/packaging/native-server-plan.mjs").as_uri()
        selected = {"harnessId": "pi", "pluginRoot": str(root / "plugins/harness"),
                    "artifactRoot": artifact_root, "piProfileBridge": True}
        plan = json.loads(subprocess.check_output(["/usr/bin/node", "--input-type=module", "-e",
            f"import {{nativeServerPlan}} from {json.dumps(module)}; "
            f"console.log(JSON.stringify(nativeServerPlan({json.dumps(selected)}).args))"], text=True))
        def value(flag):
            return plan[plan.index(flag) + 1]
        runtime = create_composition().native_runtime(private / "data", plugin_root=root / "plugins/harness",
            harness_id=value("--native-harness"), adapter_command=value("--native-adapter-command"),
            adapter_args=tuple(item.split("=", 1)[1] for item in plan if item.startswith("--native-adapter-arg=")),
            installed_artifact_root=value("--native-installed-artifact-root"), pi_profile_bridge=True)
        opened = []
        observations = []
        requests = []
        class ImmediateLoop:
            def call_soon_threadsafe(self, callback, argument):
                callback(argument)
        try:
            runtime.start()
            workspace = runtime.wire.dispatch("workspaces.open", {"requestId": "installed-profile-project",
                "environment": {"kind": "local", "host": None, "user": None},
                "path": str(private / "project")})["workspace"]["id"]
            registry = runtime.plugin_host.provided_port("acp.channels")
            profile_core = runtime.plugin_host.provided_port("profile.core")
            profile = profile_core.profiles.create("probe-profile", harness_id="pi", display_name="Probe")
            if apply_profile:
                catalog = runtime.plugin_host.provided_port("model_provider.catalog")
                config = catalog.create("probe-provider", {"displayName": "Synthetic fixture", "harness": "pi",
                    "provider": "ordessa-fixture", "credentialId": None, "configuration": [],
                    "protocols": ["openai-chat"], "endpoints": {"openai-chat": "http://127.0.0.1:9/v1"},
                    "models": [{"modelId": name, "displayName": name, "availability": "available",
                                "unavailableReason": None} for name in ("first", "second")]})
                profile = profile_core.profiles.set_facet_values("probe-model-choice",
                    profile_id=profile["profile_id"], expected_version=profile["version"], values=[{
                        "facet_id": "assets.model-provider", "item_id": "choice", "value": {
                            "harnessId": "pi", "providerConfigId": config["id"], "modelId": "second"}}])
            canonical_sessions = runtime.plugin_host.provided_port("profile.native-sessions")
            assert canonical_sessions is not None
            refs = []
            seeded = set()
            for scope in ("installed-session-a", "installed-session-b"):
                binding = runtime.wire.dispatch("acp.channel.open", {
                    "harnessId": "pi", "projectId": workspace, "sessionScopeId": scope})
                opened.append(binding)
                if apply_profile:
                    instances = set((private / "data/harness-instances").iterdir()) - seeded
                    assert len(instances) == 1
                    instance = instances.pop()
                    seeded.add(instance)
                    (instance / "models.json").write_text(json.dumps({"providers": {"ordessa-fixture": {
                        "api": "openai-completions", "baseUrl": "http://127.0.0.1:9/v1",
                        "apiKey": "ordessa-nomodel-fixture-not-a-real-credential",
                        "models": [{"id": name, "name": name, "reasoning": True, "input": ["text"],
                                    "contextWindow": 8192, "maxTokens": 1024,
                                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}
                                   for name in ("first", "second")]}}}))
                    (instance / "settings.json").write_text(json.dumps({"defaultProvider": "ordessa-fixture",
                        "defaultModel": "first", "defaultThinkingLevel": "off"}))
                channel = registry.get(binding["connectionId"])
                inbox = queue.Queue()
                channel.attach(ImmediateLoop(), inbox.put)
                def request(method, params, channel=channel, inbox=inbox):
                    channel.transport.send_line(json.dumps({"jsonrpc": "2.0", "id": method,
                        "method": method, "params": params}))
                    while True:
                        line = inbox.get(timeout=40)
                        assert line is not None, "channel ended before response"
                        frame = json.loads(line)
                        if frame.get("id") == method:
                            assert "error" not in frame, frame.get("error")
                            return frame["result"]
                initialized = request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                    "clientInfo": {"name": "ordessa-installed-profile-probe", "version": "1"}})
                assert initialized["_meta"]["ordessaConfiguration"]["supported"] is True
                native = request("session/new", {"cwd": str(private / "project"), "mcpServers": []})["sessionId"]
                observed = registry.query_native_configuration(binding["connectionId"], native)
                assert observed.owner.execution_id == binding["executionId"]
                assert observed.busy is False and observed.config_options
                observations.append(observed)
                requests.append(request)
                registered = runtime.wire.dispatch("profiles.v2.registerNativeSession", {
                    "connectionId": binding["connectionId"], "nativeSessionId": native,
                    "profileId": profile["profile_id"]})["data"]
                ref, target = registered["sessionRef"], registered["target"]
                snapshot = canonical_sessions.owners.readback(ApplicationTarget(
                    target["serverId"], target["sessionId"], target["channelId"],
                    target["runtimeGeneration"]))
                assert snapshot.owner is observed.owner
                assert snapshot.target.session_id == ref["sessionUid"]
                from ordessa_profile.contracts import SessionRef
                inspection = profile_core.config_port.inspect(SessionRef(ref["realm"], ref["harnessId"],
                    ref["nativeSessionKey"], ref["sessionUid"]))
                assert inspection.target.session_ref.session_uid == ref["sessionUid"]
                if apply_profile:
                    selected = runtime.wire.dispatch("profiles.v2.selectForSession", {
                        "operationKey": "probe-select:" + ref["sessionUid"], "sessionRef": ref,
                        "profileId": profile["profile_id"]})["data"]
                    assert selected["switchState"] == "pending"
                    ticket = runtime.wire.dispatch("profiles.v2.beginTurnApplication", {
                        "operationKey": "probe-turn:" + ref["sessionUid"], "sessionRef": ref})["data"]
                    assert ticket["receipt"]["sessionRef"] == ref
                    assert ticket["turnId"] and ticket["appliedSwitch"] is False
                    session_config = runtime.wire.dispatch("profiles.v2.inspectSessionConfig", {"sessionRef": ref})["data"]
                    assert session_config["evidence"]["receipt"]["sessionRef"] == ref
                    assert session_config["evidence"]["journal"]["state"] == "confirmed"
                    current = registry.query_native_configuration(binding["connectionId"], native)
                    assert next(item for item in current.config_options if item["id"] == "model")["currentValue"] == "ordessa-fixture/second"
                    observations[-1] = current
                refs.append(ref)
            assert len({row["connectionId"] for row in opened}) == 2
            assert len({row["executionId"] for row in opened}) == 2
            assert len({ref["sessionUid"] for ref in refs}) == 2
            with profile_core.db.read() as conn:
                assert conn.execute("SELECT COUNT(*) FROM profile_sessions").fetchone()[0] == 2
                assert conn.execute("SELECT COUNT(*) FROM profile_applied_receipts").fetchone()[0] == (2 if apply_profile else 0)
            instances = list((private / "data/harness-instances").iterdir())
            assert len(instances) == 2 and all(item.stat().st_mode & 0o077 == 0 for item in instances)
            thinking = next(option for option in observations[0].config_options if option["id"] == "thinkingLevel")
            changed = next(option["value"] for option in thinking["options"]
                           if option["value"] != thinking["currentValue"])
            requests[0]("session/set_config_option", {"sessionId": observations[0].owner.native_session_id,
                "configId": "thinkingLevel", "value": changed})
            after_a = registry.query_native_configuration(opened[0]["connectionId"], observations[0].owner.native_session_id)
            after_b = registry.query_native_configuration(opened[1]["connectionId"], observations[1].owner.native_session_id)
            assert next(option for option in after_a.config_options if option["id"] == "thinkingLevel")["currentValue"] == changed
            assert after_b.config_options == observations[1].config_options, "sibling configuration changed"
            runtime.wire.dispatch("acp.channel.release", {"connectionId": opened[0]["connectionId"]})
            assert registry.get(opened[0]["connectionId"]) is None
            survivor = observations[1].owner
            assert registry.query_native_configuration(survivor.connection_id, survivor.native_session_id).busy is False
            return {"trustedInstalledProductRoute": True, "independentInstances": 2,
                    "actualLedgerOwners": 2, "sessionNew": 2, "prompt": 0,
                    "canonicalRegistrationComponent": True, "productionProfileWire": True,
                    "productionConfigPortInspected": True,
                    "siblingConfigurationUnchanged": True, "siblingSurvivesRelease": True,
                    "profileApplicationConfirmed": apply_profile}
        finally:
            try:
                registry = runtime.plugin_host.provided_port("acp.channels")
                for row in opened:
                    if registry is not None and registry.get(row["connectionId"]) is not None:
                        assert runtime.wire.dispatch("acp.channel.release", {
                            "connectionId": row["connectionId"]})["released"]
            finally:
                runtime.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", default="/opt/ordessa/harnesses/artifacts")
    parser.add_argument("--apply-profile", action="store_true")
    args = parser.parse_args()
    print(json.dumps(probe(args.artifact_root, apply_profile=args.apply_profile)))
