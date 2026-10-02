"""Real Pi reverse-switch diagnosis: startup admission -> live-register B ->
re-register A, zero inference, synthetic credentials, private HOME.

Usage: python probe-reverse-switch.py /absolute/pi-profile-runtime
Mirrors the production Profile reverse switch (Profile A at creation, single
model B, then Profile A again) against the real installed adapter. The
whitelisted condition code is printed when the reverse registration cannot be
proven, so the first mismatched condition is named, never guessed.
This is a developer-artifact check, NOT proof of root-managed installation.
"""
import json
import hashlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

SYNTHETIC = 'synthetic-private-key-not-for-inference'


def probe(artifact: Path, drift: str = None) -> dict:
    entry = artifact / "node_modules/@automatalabs/pi-acp/dist/ordessa-profile.mjs"
    with tempfile.TemporaryDirectory(prefix="ordessa-pi-reverse-probe-") as temporary:
        home = Path(temporary)
        instance = home / "instance"
        instance.mkdir(mode=0o700)
        # Neutral boot defaults; the Profile provider itself arrives via the
        # creation RPC, never models.json, so the startup admission matches
        # production semantics.
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
        environment = {"PATH": os.defpath, "HOME": str(home), "PI_OFFLINE": "1",
                       "ORDESSA_PI_INSTANCE_DIR": str(instance),
                       "ANTHROPIC_API_KEY": "ordessa-nomodel-fixture-not-a-real-credential"}
        replies = queue.Queue()
        with tempfile.TemporaryFile(mode="w+") as stderr:
            process = subprocess.Popen(["/usr/bin/node", str(entry)], cwd=project,
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=stderr, text=True)
            from ordessa_harness.server_acp.registry import _Channel, _ObservedTransport
            channel = _Channel(connection_id='probe-channel', harness_id='pi',
                workspace_id='probe-project', profile_id='probe-profile', cwd=str(project),
                session_scope_id='probe-scope')
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
                channel.transport.send_line(frame)
                while True:
                    frame = replies.get(timeout=25)
                    assert "invalid_stdout" not in frame, "non-JSON protocol stdout"
                    if frame.get("id") == serial:
                        assert ("error" in frame) == fails, (method, frame.get("error"))
                        return frame.get("result", frame.get("error"))

            def model_selection(native):
                _, observed = channel._configuration_rpc(native, '_ordessa/session/configuration',
                    {'sessionId': native})
                options = observed['configOptions'] if isinstance(observed, dict) else observed.config_options
                model = next(item for item in options if item['id'] == 'model')
                return model['currentValue']

            report = {}
            try:
                initialized = request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                    "clientInfo": {"name": "ordessa-reverse-probe", "version": "1"}})
                assert initialized["_meta"]["ordessaConfiguration"]["supported"] is True
                from ordessa_harness_api import ApplicationTarget, DesiredFragment, Installation, IntentSource
                from ordessa_harness.server_acp.registry import AcpChannelRegistry
                from ordessa_harness.server_acp.profile_owner import ProfileSessionOwner
                from ordessa_harness.configuration.model.backend import preparation_params
                from ordessa_harness.configuration.model.provider_registration import PiProviderRegistrationService
                from ordessa_harness.configuration.model.plugin import ModelProviderAdaptersPlugin
                from ordessa_harness.pi.configuration.runtime import PiLiveModelRuntime
                from ordessa_harness.application.configuration_service import ConfigurationApplicationService
                from ordessa_harness.application.operation_journal import OperationJournal
                from ordessa_harness.application.action_execution import ActionGrant
                from ordessa_server.bootstrap import build_runtime

                registry = AcpChannelRegistry(session_records=None, profile_records=None,
                    launch=lambda **kwargs: (_ for _ in ()).throw(AssertionError('probe cannot launch twice')))
                registry._by_id[channel.connection_id] = channel
                registry._by_pair[channel.pair] = channel
                owners = ProfileSessionOwner(registry, server_id='probe-server-incarnation')

                # Step 1: startup admission via the production creation path.
                payload_a = {'provider': 'ordessa-start', 'model': 'first', 'protocol': 'openai-chat',
                    'endpoint': 'http://127.0.0.1:9/start', 'credentialRef': 'fixture:start'}
                params = preparation_params('pi', payload_a, 'create:probe-scope',
                    credential=SYNTHETIC, models=['first', 'second'])
                prepared = registry.prepare_native_creation(channel.connection_id, params)
                assert prepared['state'] == 'prepared', prepared
                created = request("session/new", {"cwd": str(project), "mcpServers": []})
                native = created["sessionId"]
                bound = owners.bind(canonical_session_id='probe-canonical', harness_id='pi',
                    workspace_id='probe-project', connection_id=channel.connection_id,
                    native_session_id=native)
                assert model_selection(native) == 'ordessa-start/first', model_selection(native)
                report['startupAdmissionSelected'] = 'ordessa-start/first'

                # Step 2: forward live-registration of provider B, then select it.
                registration = PiProviderRegistrationService(registry, owners,
                    verify=lambda _: 'DEVELOPMENT-pinned-reverse-probe')
                payload_b = {'provider': 'ordessa-next', 'model': 'third', 'protocol': 'openai-chat',
                    'endpoint': 'http://127.0.0.1:9/next', 'credentialRef': 'fixture:next'}
                plan_b = registration.prepare(bound.target, payload_b, operation_key='forward-b',
                    credential=SYNTHETIC)
                assert plan_b.mode == 'live-update'
                result_b = registration.execute(plan_b, payload_b, credential=SYNTHETIC)
                assert result_b.state == 'observed', (result_b.state, result_b.reason)
                carrier_runtime = build_runtime(home / "controlled-carrier")
                try:
                    carrier_runtime.plugin_host.activate(ModelProviderAdaptersPlugin())
                    view = next(view for view in carrier_runtime.plugin_host.contributions(
                        'harness.configuration-adapters')
                        if view.payload.descriptor.adapter_id == 'assets.model-provider.pi')
                    native_runtime = PiLiveModelRuntime(registry, owners, target=bound.target,
                        installation=Installation('pi', (0, 5, 0), (1, 0, 0),
                            'development-pinned-pi:0.5.0'),
                        private_root=home / 'never-materialized',
                        publication_revision=view.publication_token)
                    grant = ActionGrant(bound.target, view.owner, view.publication_token,
                        'assets.model-provider', 'choice', '1', 'acp.session.set-config-option', '1')
                    service = ConfigurationApplicationService(principal='probe', target=bound.target,
                        carrier=carrier_runtime.plugin_host, runtime=native_runtime, permits=None,
                        owner_application=True, journal=OperationJournal(home / 'c4.sqlite'),
                        action_executor=native_runtime, action_grants=(grant,))
                    native_runtime.credential_binding = lambda snapshot, desired: registration.credential_binding(
                        snapshot, desired, credential=SYNTHETIC)
                    def c4_select(payload, key):
                        desired = DesiredFragment('assets.model-provider', 'choice', '1',
                            'fixture:' + key, 'fixture:' + key + '-revision', 'set', dict(payload))
                        plan = service.plan(bound.target, (desired,),
                            native_runtime.capture(bound.target).before_revision)
                        assert plan.kind == 'plan', (key, plan)
                        confirmed = service.apply_prepared(plan.plan_id, key)
                        assert confirmed.kind == 'confirmed', (key, confirmed)
                        return confirmed
                    c4_select(payload_b, 'forward-b-select')
                    assert model_selection(native) == 'ordessa-next/third', model_selection(native)
                    report['forwardSwitchConfirmed'] = 'ordessa-next/third'

                    # Step 3: the reverse switch — re-register the startup
                    # provider A and select it again, exactly the production
                    # Profile reverse application order.
                    reverse_payload = dict(payload_a)
                    reverse_credential = SYNTHETIC
                    if drift == 'endpoint':
                        # The provider resource row was re-versioned after the
                        # session was created; the resolver now yields a
                        # different endpoint for the same providerConfigId.
                        reverse_payload['endpoint'] = 'http://127.0.0.1:9/changed'
                    elif drift == 'credential':
                        # The keyring now resolves different bytes for the same
                        # credentialRef (rotated key).
                        reverse_credential = 'rotated-synthetic-key-not-for-inference'
                    plan_a = registration.prepare(bound.target, reverse_payload, operation_key='reverse-a',
                        credential=reverse_credential)
                    result_a = registration.execute(plan_a, reverse_payload, credential=reverse_credential)
                    report['reverseRegistrationState'] = result_a.state
                    report['reverseRegistrationReason'] = result_a.reason
                    if result_a.state == 'refused':
                        # A proven pre-effect refusal is terminal and must not
                        # wedge the session: a fresh preparation under a new
                        # operation key succeeds, and no effect was re-sent.
                        fresh = registration.prepare(bound.target, reverse_payload,
                            operation_key='reverse-a-retry', credential=SYNTHETIC)
                        report['retryAfterRefusalPrepared'] = fresh.operation_id != plan_a.operation_id
                    elif result_a.state == 'observed':
                        c4_select(payload_a, 'reverse-a-select')
                        assert model_selection(native) == 'ordessa-start/first', model_selection(native)
                        report['reverseSwitchConfirmed'] = 'ordessa-start/first'
                    # else: unknown keeps the whitelisted condition code in the
                    # report; no effect is replayed either way.
                    report['modelPrompts'] = 0
                finally:
                    carrier_runtime.stop()
                assert not (instance / "models.json").exists(), 'models.json must stay untouched'
                assert sentinel.read_bytes() == before
                process.stdin.close()
                process.wait(timeout=15)
                assert process.returncode == 0
                report['processExit'] = process.returncode
                return report
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
    arguments = sys.argv[2:]
    drift = 'endpoint' if '--drift-endpoint' in arguments else (
        'credential' if '--drift-credential' in arguments else None)
    print(json.dumps(probe(Path(sys.argv[1]).resolve(), drift=drift), indent=2, sort_keys=True))
