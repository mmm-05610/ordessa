"""Actual loopback uvicorn + independent CLI processes, isolated data only.

Unknown injection uses a marked stored-request fixture; it is not evidence of
an actual response-loss crash. No native process or model is selected; the optional discovery scenario
selects independent providers with their default unsupported effect methods.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


SERVER_SCRIPT = r'''
import json, socket, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from deployment import AgentServiceConfiguration, AgentToolsDeployment, build_agent_runtime, create_agent_app
from ordessa_persistence_sqlite import ProtectedFingerprintHmac
import uvicorn
root, ready = Path(sys.argv[2]), Path(sys.argv[3])
port = ProtectedFingerprintHmac({"fixture": b"isolated-http-fixture"}, active_key_id="fixture")
if len(sys.argv) > 5 and sys.argv[5] == "providers":
    import importlib, subprocess
    repo = Path(sys.argv[1]).parents[1]
    for source in ("plugins/harness/codex/src", "plugins/harness/pi/src", "plugins/harness/claude-code/src",
                   "packages/backend/harness-transport/src"):
        sys.path.insert(0, str(repo / source))
    def native_forbidden(*args, **kwargs):
        raise AssertionError("discovery must not spawn native process")
    subprocess.Popen = native_forbidden
    plugins = []
    for folder, package, prefix in (("codex", "ordessa_harness_codex", "Codex"),
            ("pi", "ordessa_harness_pi", "Pi"), ("claude-code", "ordessa_harness_claude_code", "ClaudeCode")):
        provider_class = getattr(importlib.import_module(package), prefix + "RuntimeProvider")
        wrapper = getattr(importlib.import_module(package + ".server_plugin"), prefix + "ServerPlugin")
        def factory(environment, cls=provider_class, definition=folder):
            return cls(definition_ref={"environmentNamespace": environment.value, "definitionId": definition,
                "revision": "1"}, implementation_digest="sha256:" + "b" * 64)
        plugins.append(wrapper(factory))
    runtime = AgentToolsDeployment(fingerprint_port=port, agent_contract_version=sys.argv[4],
        provider_plugins=tuple(plugins)).build_runtime(AgentServiceConfiguration(root, agent_contract_version=sys.argv[4]))
else:
    runtime = build_agent_runtime(AgentServiceConfiguration(root, agent_contract_version=sys.argv[4]), fingerprint_port=port)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen(128)
def on_bound():
    ready.write_text(json.dumps({"port": sock.getsockname()[1], "environment": runtime.core_binding.environment.environment_id}))
from ordessa_server.transport.http.app import create_app
app = create_app(runtime, on_bound=on_bound)
server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
def await_stop():
    if sys.stdin.readline().strip() == "stop":
        server.should_exit = True
threading.Thread(target=await_stop, daemon=True).start()
server.run(sockets=[sock])
'''


class IsolatedService:
    def __init__(self, tmp_path, *, version="agent-assembly/1", providers=False, cli_executable=None):
        self.version = version
        self.providers = providers
        self.cli_executable = cli_executable
        self.product = Path(__file__).resolve().parents[2]
        self.root = tmp_path / "server-root"
        self.ready = tmp_path / "ready.json"
        self.config = tmp_path / "service.json"
        self.log = tmp_path / "service.log"
        self.process = None

    def start(self):
        self.ready.unlink(missing_ok=True)
        self.log_stream = self.log.open("ab")
        self.process = subprocess.Popen([sys.executable, "-c", SERVER_SCRIPT, str(self.product),
                                         str(self.root), str(self.ready), self.version, "providers" if self.providers else "empty"],
                                        stdin=subprocess.PIPE, stdout=self.log_stream, stderr=self.log_stream)
        deadline = time.monotonic() + 15
        while not self.ready.exists():
            if self.process.poll() is not None:
                raise AssertionError("isolated server failed: " + self.log.read_text())
            if time.monotonic() > deadline:
                raise AssertionError("isolated server readiness deadline exceeded")
            time.sleep(0.05)
        ready = json.loads(self.ready.read_text())
        self.identity = ready["environment"]
        self.config.write_text(json.dumps({"services": {"fixture": {
            "endpoint": "http://127.0.0.1:" + str(ready["port"]), "tokenEnv": "AGENT_TOOLS_TEST_TOKEN"}}}))
        self.config.chmod(0o600)
        self.token = (self.root / "secrets" / "http-token").read_text().strip()

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.stdin.write(b"stop\n")
                self.process.stdin.flush()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.log_stream.close()
            assert self.process.returncode == 0, self.log.read_text()
            self.process = None

    def cli(self, args, expected=0, token=None):
        env = os.environ.copy()
        if self.cli_executable:
            env = {key: value for key, value in env.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
        env["AGENT_TOOLS_TEST_TOKEN"] = self.token if token is None else token
        command = ([str(self.cli_executable)] if self.cli_executable else [sys.executable, "-m", "ordessa_agent_tools"]) + [*args,
                   "--config", str(self.config), "--service", "fixture", "--json"]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
        assert self.token not in result.stdout + result.stderr
        assert result.stderr == ""
        response = json.loads(result.stdout)
        assert response["apiVersion"] == "agent-tools/1"
        return response


def test_real_http_cli_catalog_lifecycle_conflicts_auth_and_restart(tmp_path):
    service = IsolatedService(tmp_path)
    try:
        service.start()
        identity = service.identity
        service.cli(["doctor"])
        denied = service.cli(["profiles", "list"], expected=3, token="invalid-test-token")
        assert denied["error"]["code"] == "AUTHORIZATION_REFUSED"
        source = {"harnessDefinitionRef": {"environmentNamespace": identity,
                  "definitionId": "missing-harness", "revision": "1"},
                  "schemaVersion": "1", "declarations": []}
        file = tmp_path / "manifest.json"
        file.write_text(json.dumps(source))
        create = ["profiles", "create", "--profile-id", "one", "--name", "One",
                  "--file", str(file), "--request-id", "http-create"]
        service.cli(create, expected=3, token="invalid-test-token")
        assert service.cli(["profiles", "list"])["data"]["entries"] == []
        first = service.cli(create)["data"]
        assert service.cli(create)["data"] == first
        ref = json.dumps(first["currentManifestRef"])
        assert service.cli(["profiles", "show", ref])["data"]["content"] == source
        preview = service.cli(["profiles", "preview", ref], expected=4)
        assert preview["data"]["ready"] is False
        assert preview["error"]["code"] == "PROVIDER_UNAVAILABLE"
        service.cli(["profiles", "rename", "one", "--name", "Forbidden replay",
                    "--expected-catalog-revision", "1", "--request-id", "http-create"], expected=5)
        source["metadata"] = {"updated": True}
        file.write_text(json.dumps(source))
        service.cli(create, expected=5)
        edit = ["profiles", "edit", "one", "--file", str(file), "--expected-catalog-revision", "1",
                "--base-manifest", ref, "--request-id", "http-edit"]
        second = service.cli(edit)["data"]
        assert second["catalogRevision"] == 2
        assert second["currentManifestRef"]["manifestRevision"] == 2
        stale = edit.copy()
        stale[stale.index("http-edit")] = "http-stale"
        service.cli(stale, expected=5)
        renamed = service.cli(["profiles", "rename", "one", "--name", "Renamed",
                    "--expected-catalog-revision", "2", "--request-id", "http-rename"])["data"]
        assert renamed["currentManifestRef"] == second["currentManifestRef"]
        service.cli(["profiles", "clone", ref, "--profile-id", "clone", "--name", "Clone",
                     "--request-id", "http-clone"])
        service.cli(["profiles", "archive", "one", "--expected-catalog-revision", "3",
                     "--request-id", "http-archive"])
        assert [x["profileId"] for x in service.cli(["profiles", "list"])["data"]["entries"]] == ["clone"]
        service.cli(["profiles", "restore", "one", "--expected-catalog-revision", "4",
                     "--request-id", "http-restore"])
        service.stop()
        service.cli(["doctor"], expected=4)
        # Explicit stored-request fixture, injected only while this test's
        # service is stopped. This does not simulate a real HTTP lost receipt.
        import hashlib
        from ordessa_environment_api import RequestKey
        from ordessa_persistence_sqlite import SqliteStorePort, ProtectedFingerprintHmac
        uncertain_key = RequestKey(identity, "local", "http-unknown")
        comparison = {"profileId": "one", "expectedCatalogRevision": 5, "displayName": "Uncertain"}
        canonical = json.dumps(comparison, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        port = ProtectedFingerprintHmac({"fixture": b"isolated-http-fixture"}, active_key_id="fixture")
        digest = port.fingerprint(uncertain_key, "pacthold.agents.profiles.rename",
                                  "sha256:" + hashlib.sha256(canonical.encode()).hexdigest())
        fixture_store = SqliteStorePort(service.root / "state" / "core.sqlite")
        try:
            assert fixture_store.claim_dispatch(uncertain_key, digest)
        finally:
            fixture_store.close()
        service.start()
        assert service.identity == identity
        uncertain = ["profiles", "rename", "one", "--name", "Uncertain",
                     "--expected-catalog-revision", "5", "--request-id", "http-unknown"]
        response = service.cli(uncertain, expected=6)
        assert response["status"] == "unknown" and response["error"]["retryable"] is False
        service.cli(uncertain, expected=6)
        assert service.cli(["profiles", "entry", "one"])["data"]["displayName"] == "Renamed"
        assert service.cli(["profiles", "entry", "one"])["data"]["catalogRevision"] == 5
        assert service.cli(edit)["data"] == second  # exact persisted old result, not current entry
        assert service.cli(["profiles", "show", ref])["data"]["content"]["declarations"] == []
    finally:
        service.stop()


def test_real_committed_create_receipt_lost_on_tcp_never_resubmits(tmp_path):
    """The proxy discards a real upstream committed reply, not a fake result."""
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request, build_opener, ProxyHandler

    service = IsolatedService(tmp_path)
    proxy = None
    proxy_thread = None
    evidence = {"createRequests": 0, "committedReplies": [], "errors": []}
    try:
        service.start()
        direct_config = json.loads(service.config.read_text())
        upstream = direct_config["services"]["fixture"]["endpoint"]
        opener = build_opener(ProxyHandler({}))

        class DropCommittedCreate(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                is_create = self.path == "/wire/v1/agents.profiles.create"
                if is_create:
                    evidence["createRequests"] += 1
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = self.rfile.read(size)
                    request = Request(upstream + self.path, data=payload, method="POST", headers={
                        "Content-Type": "application/json",
                        "Authorization": self.headers.get("Authorization", ""),
                    })
                    with opener.open(request, timeout=5) as response:
                        reply = response.read()
                        status = response.status
                    if is_create:
                        parsed = json.loads(reply)
                        if status != 200 or "error" in parsed or "result" not in parsed:
                            raise AssertionError("upstream did not confirm a committed create")
                        evidence["committedReplies"].append(parsed)
                        # The Server response is already completely read. The
                        # client receives no status line, headers or body.
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(reply)))
                    self.end_headers()
                    self.wfile.write(reply)
                except BaseException as exc:
                    evidence["errors"].append(type(exc).__name__)
                    self.close_connection = True
                    self.connection.close()

        proxy = ThreadingHTTPServer(("127.0.0.1", 0), DropCommittedCreate)
        proxy_thread = Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()
        through_proxy = json.loads(json.dumps(direct_config))
        through_proxy["services"]["fixture"]["endpoint"] = "http://127.0.0.1:" + str(proxy.server_port)
        service.config.write_text(json.dumps(through_proxy))
        source = {"harnessDefinitionRef": {"environmentNamespace": service.identity,
                   "definitionId": "absent", "revision": "1"},
                  "schemaVersion": "1", "declarations": []}
        file = tmp_path / "lost-receipt-manifest.json"
        file.write_text(json.dumps(source))
        lost = service.cli(["profiles", "create", "--profile-id", "lost-receipt",
                   "--name", "Lost receipt", "--file", str(file),
                   "--request-id", "lost-receipt-create"], expected=6)
        assert lost["status"] == "unknown"
        assert lost["error"]["code"] == "OUTCOME_UNKNOWN"
        assert lost["error"]["retryable"] is False
        assert evidence["createRequests"] == 1
        assert len(evidence["committedReplies"]) == 1
        assert evidence["errors"] == []
        # Recovery uses readEntry/read/list directly against the real Server.
        # No second create is issued, even with the original request identity.
        service.config.write_text(json.dumps(direct_config))
        entry = service.cli(["profiles", "entry", "lost-receipt"])["data"]
        assert entry == evidence["committedReplies"][0]["result"]
        ref = json.dumps(entry["currentManifestRef"])
        recovered = service.cli(["profiles", "show", ref])["data"]
        assert recovered["content"] == source
        assert recovered["ref"]["manifestRevision"] == 1
        entries = service.cli(["profiles", "list"])["data"]["entries"]
        assert entries == [entry]
        assert evidence["createRequests"] == 1
        assert len(evidence["committedReplies"]) == 1
    finally:
        if proxy is not None:
            proxy.shutdown()
            proxy.server_close()
        if proxy_thread is not None:
            proxy_thread.join(timeout=5)
            assert not proxy_thread.is_alive()
        service.stop()


def test_real_http_v2_provider_discovery_has_no_native_readiness_or_execution(tmp_path):
    service = IsolatedService(tmp_path, version="agent-assembly/2")
    try:
        service.start()
        capabilities = service.cli(["capabilities"])["data"]["coreAgent"]
        assert capabilities["contractVersion"] == "agent-assembly/2"
        assert capabilities["supports"] == {"profileCatalog": True, "nodes": False, "managedInput": False,
                                            "configurationManagement": False, "nodePreparation": False}
        listed = service.cli(["providers", "list"])
        assert listed["data"] == {"providers": []}
        assert listed["evidence"] == {"level": "providerRegistryObserved", "runtimeVerified": False}
        denied = service.cli(["providers", "list"], expected=3, token="invalid-test-token")
        assert denied["error"]["code"] == "AUTHORIZATION_REFUSED"
        absent = service.cli(["providers", "describe", json.dumps({"environmentNamespace": service.identity,
                    "definitionId": "absent", "revision": "1"})], expected=3)
        assert absent["error"]["code"] == "AUTHORIZATION_REFUSED"
    finally:
        service.stop()


def test_real_http_v2_node_observation_requires_explicit_read_authority(tmp_path):
    service = IsolatedService(tmp_path, version='agent-assembly/2')
    try:
        service.start()
        core = service.cli(['capabilities'])['data']['coreAgent']
        assert {'agents.nodes.list', 'agents.nodes.read'} <= set(core['supportedMethods'])
        assert core['supports']['nodePreparation'] is False
        # This deployment only grants Profile/registry reads. Publishing a
        # method and possession of Bearer never become Node read authority.
        for args in (['nodes', 'list'], ['nodes', 'inspect', json.dumps({
                'environmentNamespace': service.identity, 'instanceId': 'absent', 'generation': 1})]):
            denied = service.cli(args, expected=3)
            assert denied['error']['code'] == 'AUTHORIZATION_REFUSED'
            assert denied['error']['retryable'] is False
            assert denied['status'] == 'refused'
            assert denied['evidence']['level'] == 'coreCapabilitiesObserved'
    finally:
        service.stop()


def test_real_http_v2_catalog_deployment_refuses_prepare_without_authorities(tmp_path):
    service = IsolatedService(tmp_path, version='agent-assembly/2')
    try:
        service.start()
        manifest = tmp_path / 'recipe.json'
        manifest.write_text(json.dumps({'harnessDefinitionRef': {'environmentNamespace': service.identity,
            'definitionId': 'absent', 'revision': '1'}, 'schemaVersion': '1', 'declarations': []}))
        entry = service.cli(['profiles', 'create', '--file', str(manifest), '--profile-id', 'recipe',
            '--name', 'Recipe', '--request-id', 'create-recipe'])['data']
        request = tmp_path / 'preparation.json'
        request.write_text(json.dumps({'requestId': 'prepare-recipe', 'profileRef': entry['currentManifestRef'],
            'context': {}, 'options': {}}))
        refused = service.cli(['nodes', 'prepare', '--file', str(request)], expected=4)
        assert refused['error']['code'] == 'NODE_PREPARATION_UNAVAILABLE'
        assert refused['error']['retryable'] is False and refused['operationRef'] is None
        assert refused['status'] == 'refused' and refused['requestId'] == 'prepare-recipe'
        assert refused['data']['coreAgent']['supports']['nodePreparation'] is False
        assert 'agents.nodes.prepare' not in refused['data']['coreAgent']['supportedMethods']
        assert service.cli(['profiles', 'entry', 'recipe'])['data'] == entry
    finally:
        service.stop()
