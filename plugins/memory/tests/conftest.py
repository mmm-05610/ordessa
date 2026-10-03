"""Shared fixtures: recorded fakes for the runner/catalog/REST edges, and a
plugin built against a temp data root. No test here touches a real Docker
daemon or a real model endpoint (E2 discipline: fake OpenAI-compatible
endpoints only)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_memory import provisioning
from ordessa_memory.plugin import MemoryPlugin
from ordessa_memory.store import MemoryStore


class FakeRunner:
    """Records every command; per-prefix scripted results."""

    def __init__(self, script: dict[str, "tuple[int, str, str]"] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.script = script or {}

    def __call__(self, argv: tuple[str, ...], timeout: float) -> provisioning.CommandResult:
        self.calls.append(tuple(argv))
        joined = " ".join(argv)
        for prefix, (code, out, err) in self.script.items():
            if prefix in joined:
                return provisioning.CommandResult(tuple(argv), code, out, err)
        return provisioning.CommandResult(tuple(argv), 0, "", "")


@pytest.fixture
def fake_runner():
    return FakeRunner()


@pytest.fixture
def data_root(tmp_path) -> Path:
    root = tmp_path / "data-root" / "memory"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def store(data_root):
    s = MemoryStore(data_root / "memory.db")
    yield s
    s.close()


@pytest.fixture
def port_plan():
    return provisioning.PortPlan(server_port=18080, postgres_port=18432)


class FakeCatalog:
    """Duck-typed ``model_provider.catalog``: list() over provider rows."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list(self, include_archived: bool = False):
        return [dict(r) for r in self._rows
                if include_archived or r.get("archivedAt") is None]


def provider_row(provider="openai", credential_id="ref://cred-1", base_url=None,
                 models=("m-1",), state="active", archived_at=None):
    return {
        "id": f"pm-{provider}", "version": 1, "displayName": provider.title(),
        "harness": None, "provider": provider, "credentialId": credential_id,
        "models": [{"modelId": m, "displayName": m} for m in models],
        "archivedAt": archived_at, "managedBy": "ordessa", "state": state,
        "provenance": {"baseUrl": base_url} if base_url else None,
        "createdAt": "2026-09-28T00:00:00Z", "updatedAt": "2026-09-28T00:00:00Z",
    }


@pytest.fixture
def catalog_openai():
    return FakeCatalog([provider_row("openai", "ref://openai-cred",
                                     "https://api.acme.test/v1", ("gpt-x",))])


def build_plugin(data_root: Path, catalog=None, port_plan=None, runner=None,
                 server_scope=None) -> MemoryPlugin:
    plugin = MemoryPlugin(
        data_root=data_root.parent, port_plan=port_plan, runner=runner)
    ports = {"server.id": server_scope}
    if catalog is not None:
        ports["model_provider.catalog"] = catalog
    context = SimpleNamespace(plugin_id="test", data_root=data_root.parent, ports=ports)
    plugin.build(context)
    return plugin


@pytest.fixture
def plugin(data_root, catalog_openai, port_plan, fake_runner):
    p = build_plugin(data_root, catalog=catalog_openai, port_plan=port_plan,
                     runner=fake_runner, server_scope="srv-1")
    yield p
    if p.store is not None:
        p.store.close()


# -- a fake mem0 REST server (in-process, records requests) -----------------------

class _FakeMem0Handler(BaseHTTPRequestHandler):
    server_version = "FakeMem0/1"

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 - http.server vocabulary
        self.server.requests.append(("GET", self.path, dict(self.headers), None))
        if self.path.startswith("/docs"):
            self._respond(200, {"ok": True})
        else:
            self._respond(200, {"results": []})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append(("POST", self.path, dict(self.headers), body))
        if self.path == "/search":
            self._respond(200, {"results": [
                {"id": "m1", "memory": "用户在深色模式下工作", "score": 0.9}]}
            )
        else:
            self._respond(200, {"results": []})

    def log_message(self, *args):  # silence the console
        pass


@pytest.fixture
def fake_mem0():
    """An in-process fake of the mem0 REST surface; records every request."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeMem0Handler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


class FakeClientFactory:
    """Hands out one real client pointed at the fake server, recording the
    key getter's answers (the reference the env file carries)."""

    def __init__(self, base_url: str, api_key: str = "test-admin-key"):
        from ordessa_memory.mem0_client import Mem0Client
        self.key = api_key
        self.client = Mem0Client(base_url, lambda: self.key)


@pytest.fixture
def client_factory(fake_mem0):
    return FakeClientFactory(f"http://127.0.0.1:{fake_mem0.server_address[1]}")
