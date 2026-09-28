"""Core-cleanup stage 4: the host-boundary audit gates.

The acceptance questions this batch must answer with counterexamples:

- a bare host starts and exposes exactly the host capabilities;
- a missing product selection or a missing dependency plugin is a typed
  startup refusal (fail closed), never a silently bare server;
- adding a controlled Harness configuration requires no change to
  `apps/server` or `server-plugin-api` — the seat is registered through the
  compatibility core's registry and hello advertises it;
- the host's own source carries no Harness-brand or business knowledge.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

REPO_ROOT = None  # set lazily; tests resolve from __file__


def _hello(runtime):
    result = runtime.wire.hello(HELLO)
    return result


def test_bare_host_exposes_exactly_the_host_capabilities(tmp_path):
    runtime = build_runtime(tmp_path / "bare", server_plugins=[])
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            assert client.get("/live").status_code == 200
            result = _hello(runtime)
            ids = [item["id"] for item in result["capabilities"]]
            assert ids == ["server.hello"], ids
            assert result["harnesses"] == []
            # business routes are not mounted at all on a bare host
            for route in ("/api/v1/readiness", "/api/v1/profiles", "/api/v1/workspaces"):
                answer = client.get(route, headers={
                    "Authorization": f"Bearer {runtime.token}"})
                assert answer.status_code == 404, route
    finally:
        runtime.stop()


def test_a_missing_product_selection_refuses_startup(monkeypatch, tmp_path):
    """Zero product candidates = typed refusal. A bare host is a deliberate
    `server_plugins=()` choice, never the accident of a missing package."""
    from importlib import metadata

    import ordessa_server.bootstrap.runtime as runtime_module

    class _Empty:
        def select(self, group):
            return []

        def get(self, group):
            return ()

    monkeypatch.setattr(metadata, "entry_points", lambda: _Empty())
    try:
        build_runtime(tmp_path / "data")
    except RuntimeError as refusal:
        assert "SERVER_PRODUCT_MISSING" in str(refusal), refusal
    else:
        raise AssertionError("composition without a product selection must refuse")


def test_a_ambiguous_product_selection_refuses_startup(monkeypatch, tmp_path):
    from importlib import metadata

    import ordessa_server.bootstrap.runtime as runtime_module

    class _FakeEP:
        def __init__(self, name):
            self.name = name

        def load(self):
            raise AssertionError("two candidates must refuse before any load")

    class _Two:
        def select(self, group):
            return [_FakeEP("a"), _FakeEP("b")]

        def get(self, group):
            return self.select(group)

    monkeypatch.setattr(metadata, "entry_points", lambda: _Two())
    try:
        build_runtime(tmp_path / "data")
    except RuntimeError as refusal:
        assert "SERVER_PRODUCT_AMBIGUOUS" in str(refusal), refusal
    else:
        raise AssertionError("two product candidates must refuse")


def test_a_missing_dependency_plugin_refuses_startup(tmp_path):
    """A selection whose declared dependency is absent refuses at activation
    (fail closed), not at first request."""
    from server_plugin_api import (
        ServerPluginDescriptor, ServerPlugin, ServerPluginContext,
        ServerPluginRegistration, DependencyError,
    )

    class _Lonely:
        def descriptor(self):
            return ServerPluginDescriptor(id="fake.lonely", display_name="l",
                                          version="1", requires=("ordessa.workspace",))

        def build(self, context: ServerPluginContext):
            return ServerPluginRegistration()

    try:
        build_runtime(tmp_path / "data", server_plugins=[_Lonely()])
    except DependencyError as refusal:
        assert "ordessa.workspace" in str(refusal)
    else:
        raise AssertionError("a missing dependency must refuse startup")


def test_a_controlled_harness_config_needs_no_host_change(tmp_path):
    """Registering one more Harness seat is a registry operation in the
    compatibility core's domain — the host learns the family through the
    live directory port and hello advertises it. No apps/server or
    server-plugin-api change is involved."""
    from ordessa_server_compat.execution import HarnessDescriptor

    runtime = build_runtime(tmp_path / "data")
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            headers = {"Authorization": f"Bearer {runtime.token}"}
            before = client.post("/wire/v1/server.hello", headers=headers, json={
                "jsonrpc": "2.0", "id": "1", "method": "server.hello", "params": HELLO,
            }).json()["result"]["harnesses"]
            assert all(entry["id"] != "audit-alpha" for entry in before)

            runtime.plugin_host.provided_port('harness.directory').register(HarnessDescriptor(
                "audit-alpha", credential_kind="audit-key",
                capability_claims={"stream": True},
            ))
            after = client.post("/wire/v1/server.hello", headers=headers, json={
                "jsonrpc": "2.0", "id": "1", "method": "server.hello", "params": HELLO,
            }).json()["result"]["harnesses"]
            seats = {entry["id"]: entry for entry in after}
            assert seats["audit-alpha"]["credentialKind"] == "audit-key"
    finally:
        runtime.stop()


def test_the_host_source_carries_no_harness_business_knowledge():
    """The host's composition and transport name no family and no brand: the
    only harness facts they touch arrive through the live directory port."""
    import ast
    from pathlib import Path

    host = Path(__file__).resolve().parents[3] / "apps" / "server" / "src" / "ordessa_server"
    for relative in ("bootstrap/runtime.py", "transport/http/app.py",
                     "plugin_host/host.py", "wire/handlers.py"):
        source = (host / relative).read_text(encoding="utf-8")
        for brand in ("codex", "claude", "opencode", "hermes", "qoder", "qwen",
                      "dsh", "kilo", "pi-cli"):
            assert brand not in source.lower(), f"{relative} names {brand}"
        # and no family list is spelled in the host either
        assert "HarnessDescriptor" not in source, relative


def test_the_server_core_package_declares_no_business_dependency():
    """The install boundary: `ordessa-server` must start a bare host with no
    business package installed. Its declared requirements may therefore name
    only the kernel's own surface — not ordessa-harness, not the domain
    plugins, not the product selection."""
    from importlib import metadata

    requires = metadata.requires("ordessa-server") or []
    business = ("ordessa-harness", "ordessa-workspace", "ordessa-server-compat",
                "ordessa-server-product")
    declared_business = [r for r in requires
                         if any(b in r for b in business)]
    assert declared_business == [], (
        "the Server core's install boundary pulls business packages: "
        f"{declared_business}")


def test_the_host_source_imports_no_harness_package():
    """The harness package is a plugin dependency, not a host dependency: no
    file under apps/server — including the legacy alias shims — may IMPORT
    ordessa_harness. Prose and comments may mention it; only real imports
    count, so this parses the AST instead of scanning strings. (The
    acp_channel alias's ownership moves with the domain; a bare-host install
    without the harness package must import cleanly.)

    Note for the packaging half of this boundary: after any pyproject.toml
    dependency change the distribution metadata must be refreshed (reinstall
    in the environment) before the metadata-based gate can see it."""
    import ast
    from pathlib import Path

    host = Path(__file__).resolve().parents[3] / "apps" / "server" / "src" / "ordessa_server"
    for path in host.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "ordessa_harness"
                    assert not alias.name.startswith("ordessa_harness."), (
                        f"{path.name} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:  # relative import — inside the host package
                    continue
                assert module != "ordessa_harness"
                assert not module.startswith("ordessa_harness."), (
                    f"{path.name} imports {module}")
