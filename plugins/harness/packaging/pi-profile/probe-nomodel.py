"""Real enhanced Pi, private HOME, no credentials, no prompt/model requests.

Usage: python probe-nomodel.py /absolute/pi-profile-runtime
This is a developer-artifact check, NOT proof of root-managed installation.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading


def probe(artifact: Path, *, owner_rpc=False) -> dict:
    entry = artifact / "node_modules/@automatalabs/pi-acp/dist/ordessa-profile.mjs"
    with tempfile.TemporaryDirectory(prefix="ordessa-pi-profile-probe-") as temporary:
        home = Path(temporary)
        instance = home / "instance"
        instance.mkdir(mode=0o700)
        # Synthetic, non-secret test credentials only. They make a reasoning
        # model selectable locally; no prompt or outbound request is sent.
        (instance / "settings.json").write_text(json.dumps({
            "defaultProvider": "anthropic", "defaultModel": "claude-opus-4-6",
            "defaultThinkingLevel": "off"}))
        project = home / "project"
        project.mkdir(mode=0o700)
        global_dir = home / ".pi/agent"
        global_dir.mkdir(parents=True)
        sentinel = global_dir / "settings.json"
        sentinel.write_text('{"sentinel":"do not modify"}\n')
        before = sentinel.read_bytes()
        # Do not inherit credentials, HOME configuration or provider variables.
        environment = {"PATH": os.defpath, "HOME": str(home), "PI_OFFLINE": "1",
                       "ORDESSA_PI_INSTANCE_DIR": str(instance),
                       "ANTHROPIC_API_KEY": "ordessa-nomodel-fixture-not-a-real-credential"}
        replies = queue.Queue()
        with tempfile.TemporaryFile(mode="w+") as stderr:
            process = subprocess.Popen(["/usr/bin/node", str(entry)], cwd=project,
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=stderr, text=True)
            channel = None
            if owner_rpc:
                from ordessa_harness.server_acp.registry import _Channel, _ObservedTransport
                channel = _Channel(connection_id='probe-channel', harness_id='pi',
                    workspace_id='probe-project', profile_id='probe-profile', cwd=str(project))
                # Ledger fixture only: this probe is NOT a full Server composition.
                channel.session_id = 'probe-ledger-session'
                channel.execution_id = 'probe-execution'
                class PipeTransport:
                    def send_line(self, line):
                        process.stdin.write(line + '\n')
                        process.stdin.flush()
                class ImmediateLoop:
                    def call_soon_threadsafe(self, callback, item):
                        callback(item)
                channel.transport = _ObservedTransport(channel, PipeTransport())
                channel.attach(ImmediateLoop(), lambda line: replies.put(json.loads(line)))
            def collect():
                for line in process.stdout:
                    try:
                        if channel is None:
                            replies.put(json.loads(line))
                        else:
                            channel.deliver(line)
                    except ValueError:
                        replies.put({"invalid_stdout": True})
            reader = threading.Thread(target=collect, daemon=True)
            reader.start()
            serial = 0
            def request(method, params, *, fails=False):
                nonlocal serial
                serial += 1
                frame = json.dumps({"jsonrpc": "2.0", "id": serial, "method": method, "params": params})
                if channel is None:
                    process.stdin.write(frame + "\n")
                    process.stdin.flush()
                else:
                    channel.transport.send_line(frame)
                while True:
                    frame = replies.get(timeout=25)
                    assert "invalid_stdout" not in frame, "non-JSON protocol stdout"
                    if frame.get("id") == serial:
                        assert ("error" in frame) == fails, (method, frame.get("error"))
                        return frame.get("result", frame.get("error"))
            def configuration(native):
                if channel is None:
                    return request('_ordessa/session/configuration', {'sessionId': native})
                observed = channel.query_native_configuration(native)
                assert observed.owner.ledger_session_id == 'probe-ledger-session'
                assert observed.owner.native_session_id == native
                assert replies.empty(), 'owner configuration reply leaked to client relay'
                return {'sessionId': native, 'generation': observed.native_generation,
                    'busy': observed.busy, 'configOptions': observed.config_options}
            try:
                initialized = request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                    "clientInfo": {"name": "ordessa-profile-nomodel", "version": "1"}})
                assert initialized["_meta"]["ordessaConfiguration"]["supported"] is True
                request("_ordessa/session/configuration", {"sessionId": "missing"}, fails=True)
                created = request("session/new", {"cwd": str(project), "mcpServers": []})
                native = created["sessionId"]
                initial = configuration(native)
                thinking = next(o for o in initial["configOptions"] if o["id"] == "thinkingLevel")
                different = next(o["value"] for o in thinking["options"] if o["value"] != thinking["currentValue"])
                request("session/set_config_option", {"sessionId": native,
                    "configId": "thinkingLevel", "value": different})
                actual = configuration(native)
                assert actual["generation"] == initial["generation"]
                assert actual["sessionId"] == native and actual["busy"] is False
                assert next(o for o in actual["configOptions"] if o["id"] == "thinkingLevel")["currentValue"] == different
                assert sentinel.read_bytes() == before
                assert json.loads((instance / "settings.json").read_text())["defaultThinkingLevel"] == different
                request("_ordessa/session/configuration", {"sessionId": native, "desired": different}, fails=True)
                request("session/close", {"sessionId": native})
                request("_ordessa/session/configuration", {"sessionId": native}, fails=True)
                if channel is not None:
                    from ordessa_harness.server_acp.registry import NativeConfigurationUnavailable
                    try:
                        channel.query_native_configuration(native)
                    except NativeConfigurationUnavailable:
                        pass
                    else:
                        raise AssertionError('closed native session gave owner evidence')
                process.stdin.close()
                process.wait(timeout=15)
                assert process.returncode == 0
                return {"realPiConfigurationReadback": True, "sameInstanceGeneration": True,
                    "isolatedSettingsWrite": True, "globalSentinelUnchanged": True,
                    "closedSessionRefused": True, "processExit": process.returncode,
                    "sessionNew": 1, "modelPrompts": 0, "credentialAccess": "synthetic fixture only",
                    "productionOwnerRpc": owner_rpc, 'serverLedger': 'fixture only'}
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                reader.join(timeout=2)


if __name__ == "__main__":
    print(json.dumps(probe(Path(sys.argv[1]).resolve(), owner_rpc='--owner-rpc' in sys.argv[2:])))
