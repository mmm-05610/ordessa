"""Controlled-proof doubles and the composition stack for tests/service/.

The host pieces are the real ones: `ordessa_server.plugin_host`
(`ServerPluginHost`/`MethodRegistry`, the `host.py` test precedent) and the
real `WireService.dispatch`/`hello` over the same registry — shape checks,
the requestId wall, error-family resolution and availability advertisement
are exactly what a production composition runs. Nothing here edits a host
file; the only substitutions are the domain's OWN injectable seams (probe
runner, managed client factory, permission/gate ports via `host_ports`),
which is the honest L0/L1 proof boundary of backend/managed
(specs/011-q4-mcp/reports/t04-t05-research.md).

The package-root conftest blocks socket/Popen for the whole suite; this
layer never needs them (the probe transport is injected, the managed client
is the labelled in-memory fake), and the pin standing is itself the point:
a wire call that secretly spawned would die here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost
from ordessa_server.wire.handlers import WireService
from server_plugin_api import WireError

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from backend.managed.session_manager import InMemoryManagedClient  # noqa: E402
from backend.plugin import McpAssetServerPlugin  # noqa: E402


class Stack:
    """One live composition: real host + real WireService + the Q4 plugin."""

    def __init__(self, tmp_path, *, host_ports=None, probe_runner=None,
                 client_factory=None, plugin=None) -> None:
        self.root = tmp_path
        self.registry = MethodRegistry()
        self.host_ports = dict(host_ports or {})
        self.host = ServerPluginHost(
            methods=self.registry, data_root=tmp_path, host_ports=self.host_ports)
        # the same facade the production composition root binds (runtime.py):
        # the plugin resolves MCP codes through ITS composition's aggregate
        self.host_ports.setdefault(
            "wire.error_family_resolver",
            lambda code: self.host.wire_error_families.family_for(code))
        self.plugin = plugin or McpAssetServerPlugin(
            probe_runner=probe_runner or fake_probe_runner,
            client_factory=client_factory)
        self.active = self.host.activate(self.plugin)
        for hook in self.active.registration.start_hooks:
            hook()
        self.wire = WireService(
            server_id_provider=lambda: "proof-server", cursor_secret=b"c" * 16,
            method_registry=self.registry,
            error_family_resolver=lambda code: self.host.wire_error_families.family_for(code))

    def call(self, method, **params):
        return self.wire.dispatch(method, params)

    def expect_refusal(self, method, *, family, internal_code, **params):
        with pytest.raises(WireError) as info:
            self.wire.dispatch(method, params)
        error = info.value
        assert error.family == family, f"{method}: {error.family} != {family} ({error.message})"
        assert error.details.get("internalCode") == internal_code, error.details
        assert error.message.startswith(f"{internal_code}: "), error.message
        return error


def fake_probe_runner(canonical, *, policy=None, cancel=None):
    """The labelled L0/L1 probe double: same facts shape as backend/probe.py,
    zero transport. Composition-injected, never a wire parameter."""
    del canonical, policy, cancel
    return {
        "status": "ok", "transport": "stdio", "evidence": "initialize-handshake",
        "serverInfo": {"name": "fake-probe", "version": "0"},
        "protocolVersion": "2025-11-25",
        "negotiation": {"requested": "2025-11-25", "supported": ["2025-11-25"],
                        "negotiated": "2025-11-25"},
        "credentialScope": "unproven", "credentialsExcluded": ["TOKEN"],
        "proves": ["initialize-handshake"],
        "doesNotProve": ["tool-catalog", "credential-usability", "connection-lease",
                         "tool-invocability"],
    }


def raising_probe_runner(exc):
    def run(canonical, *, policy=None, cancel=None):
        raise exc
    return run


class AllowProbeAuthority:
    def __init__(self):
        self.calls = []

    def authorize_probe(self, *, principal, server_scope, definition_id, revision):
        self.calls.append((principal, server_scope, definition_id, revision))
        return True


class DenyProbeAuthority:
    def authorize_probe(self, *, principal, server_scope, definition_id, revision):
        return False


class FakeSubmissionGate:
    def __init__(self):
        self.planned = []

    def plan_submission(self, *, principal, server_scope, session_ref,
                        runtime_generation, snapshot_digest, credential_references):
        self.planned.append(snapshot_digest)
        return {"status": "planned-by-gate", "snapshotDigest": snapshot_digest,
                "credentialReferences": [dict(r) for r in credential_references]}


class FakeCredentialRecords:
    """The shape of the host's CredentialRecords the adapter reads."""

    def __init__(self, ids=("cred-1",)):
        self.rows = {cid: {"secret_locator": f"loc-{cid}"} for cid in ids}

    def exists(self, credential_id):
        return credential_id in self.rows

    def get(self, credential_id):
        return dict(self.rows[credential_id])


class FakeSecretStore:
    PLAINTEXT = "super-secret-value-42"

    def read(self, locator):
        return self.PLAINTEXT.encode("utf-8")


def stdio_definition(name="demo", **env):
    """env values: a plain str becomes a typed {"literal": str}; pass a dict
    ({"secretRef": id} / {"literal": v}) to state the shape explicitly."""
    values = {key: ({"literal": value} if isinstance(value, str) else value)
              for key, value in env.items()}
    return {"name": name, "transport": {"stdio": {
        "command": "/bin/true", "args": [], "env": values or None}}}


def make_client(lease):
    del lease
    return InMemoryManagedClient(
        tools=[{"name": "read_file", "inputSchema": {"type": "object"}},
               {"name": "write_file", "inputSchema": {"type": "object"}}])


def seed_revision(stack, *, scope="s1", principal="alice", definition_id="demo",
                  revision=1, **env):
    """save + approve one revision in THIS stack's composition."""
    stack.call("mcp.saveRevision", serverScope=scope, principal=principal,
               definitionId=definition_id, definition=stdio_definition(
                   name=definition_id, **env),
               expectedVersion=0, operationKey=f"op-save-{definition_id}")
    stack.call("mcp.approveRevision", serverScope=scope, principal=principal,
               definitionId=definition_id, revision=revision)
    return stack


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


@pytest.fixture
def saved(stack):
    """One saved + approved revision in scope "s1" under principal "alice"."""
    stack.call("mcp.saveRevision", requestId="req-save-1", serverScope="s1",
               principal="alice", definitionId="demo",
               definition=stdio_definition(), expectedVersion=0,
               operationKey="op-save-1")
    stack.call("mcp.approveRevision", serverScope="s1", principal="alice",
               definitionId="demo", revision=1)
    return stack
