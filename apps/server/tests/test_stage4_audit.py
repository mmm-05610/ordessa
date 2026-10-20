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

from ordessa_server.composition.runtime import build_runtime
from ordessa_interfaces.http import create_app

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

    import ordessa_server.composition.runtime as runtime_module

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

    import ordessa_server.composition.runtime as runtime_module

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


def test_default_product_publishes_only_the_pacthold_agent_contract(tmp_path):
    """The core method factory owns `/3`; retired product aliases are unknown."""
    from server_plugin_api import WireError

    default = build_runtime(tmp_path / "default")
    try:
        default.start()
        caller = default.wire.identity_authority.authenticate("Bearer " + default.token)
        result = default.wire.dispatch("agents.capabilities", {}, caller=caller)
        assert result["contractVersion"] == "agent-assembly/3"
        assert result["supports"]["profileCatalog"] is False  # no protected production key
        assert "agents.profiles.list" in result["supportedMethods"]
        assert "agents.profiles.create" not in result["supportedMethods"]
        ids = set(default.wire._registry.method_ids())
        assert not any(method.startswith(("profiles.v2.", "agent.")) for method in ids)
        for retired in ("profiles.v2.listProfiles", "agent.session.resolve"):
            try:
                default.wire.dispatch(retired, {}, caller=caller)
            except WireError as refusal:
                assert refusal.family == "INVALID_REQUEST"
            else:
                raise AssertionError(f"retired method remained callable: {retired}")
    finally:
        default.stop()


def test_the_host_source_carries_no_harness_business_knowledge():
    """The host's composition and transport name no family and no brand: the
    only harness facts they touch arrive through the live directory port.

    The transport app factory and the wire dispatch mechanism moved to the
    interfaces distribution (system-access services / HTTP mechanism), so the
    same guarantee is asserted there too — the scan follows the code.
    """
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    host = repo / "apps" / "server" / "src" / "ordessa_server"
    interfaces = repo / "packages" / "interfaces" / "src" / "ordessa_interfaces"
    targets = (
        host / "composition/runtime.py",
        host / "composition/plugin_host/host.py",
        interfaces / "http/runtime.py",
        interfaces / "system_access/services/invocation.py",
    )
    for path in targets:
        relative = path.relative_to(repo).as_posix()
        source = path.read_text(encoding="utf-8")
        for brand in ("codex", "claude", "opencode", "hermes", "qoder", "qwen",
                      "dsh", "kilo", "pi-cli"):
            assert brand not in source.lower(), f"{relative} names {brand}"
        # and no family list is spelled in the host either
        assert "HarnessDescriptor" not in source, relative


def test_the_server_core_package_declares_no_business_dependency():
    """Only reviewed Host public-port distributions supplement neutral contracts.

    Workspace, retired compat and default-product dependencies remain forbidden.
    The independently installed bare Host contract is tested above; selection
    metadata is now the explicit nine-port bundle approved by the coordinator.
    """
    from importlib import metadata
    from pathlib import Path
    import re
    import tomllib

    repo = Path(__file__).resolve().parents[3]
    selected_roots = {module.split(".")[0]
                      for pairs in _APPROVED_HOST_PUBLIC_PORT_IMPORTS.values()
                      for module, _ in pairs}
    approved = {}
    for project in (repo / "plugins/harness").glob("*/pyproject.toml"):
        source_roots = {p.name for p in (project.parent / "src").glob("ordessa_harness_*") if p.is_dir()}
        if selected_roots & source_roots:
            data = tomllib.loads(project.read_text())["project"]
            approved[data["name"]] = data["version"]
    assert len(approved) == 9
    requires = metadata.requires("ordessa-server") or []
    business = ("ordessa-harness", "ordessa-workspace", "ordessa-server-compat",
                "ordessa-server-product")
    selected = [r for r in requires if any(b in r for b in business)]
    assert set(selected) == {f"{name}=={version}" for name, version in approved.items()}
    declared_business = [r for r in selected if r not in
                         {f"{name}=={version}" for name, version in approved.items()}]
    assert declared_business == [], (
        "the Server core's install boundary pulls business packages: "
        f"{declared_business}")


def test_the_host_source_imports_no_harness_package():
    """The harness package is a plugin dependency, not a host dependency: no
    file under apps/server — including the legacy alias shims — may IMPORT
    pacthold.harness_kit. Prose and comments may mention it; only real imports
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
                    assert alias.name != "pacthold.harness_kit"
                    assert not alias.name.startswith("pacthold.harness_kit."), (
                        f"{path.name} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:  # relative import — inside the host package
                    continue
                assert module != "pacthold.harness_kit"
                assert not module.startswith("pacthold.harness_kit."), (
                    f"{path.name} imports {module}")


# Exact reviewed Host selection seams, not an allowance for arbitrary brand imports.
_APPROVED_HOST_PUBLIC_PORT_IMPORTS = {'composition/native_channels/selected_acp_resources.py': (('ordessa_harness_codex.acp_resources', ('acp_resources',)), ('ordessa_harness_pi.acp_resources', ('acp_resources',)), ('ordessa_harness_claude_code.acp_resources', ('acp_resources',)), ('ordessa_harness_opencode.acp_resources', ('acp_resources',)), ('ordessa_harness_hermes.acp_resources', ('acp_resources',)), ('ordessa_harness_dsh.acp_resources', ('acp_resources',)), ('ordessa_harness_kilo.acp_resources', ('acp_resources',)), ('ordessa_harness_qwen.acp_resources', ('acp_resources',)), ('ordessa_harness_grok_build.acp_resources', ('acp_resources',))), 'composition/native_channels/selected_installation_ports.py': (('ordessa_harness_codex.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm')), ('ordessa_harness_claude_code.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm')), ('ordessa_harness_opencode.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm')), ('ordessa_harness_hermes.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm')), ('ordessa_harness_dsh.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm')), ('ordessa_harness_kilo.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm')), ('ordessa_harness_pi.installation_declarations', ('installation_declaration', 'installation_owner_id', 'installation_requires_npm'))), 'composition/selected_command_catalog.py': (('ordessa_harness_claude_code.command_declarations', ('command_candidates',)), ('ordessa_harness_codex.command_declarations', ('command_candidates',)), ('ordessa_harness_dsh.command_declarations', ('command_candidates',)), ('ordessa_harness_hermes.command_declarations', ('command_candidates',)), ('ordessa_harness_kilo.command_declarations', ('command_candidates',)), ('ordessa_harness_opencode.command_declarations', ('command_candidates',)), ('ordessa_harness_pi.command_declarations', ('command_candidates',)), ('ordessa_harness_qwen.command_declarations', ('command_candidates',))), 'composition/selected_harness_catalog.py': (('ordessa_harness_codex.registration_declarations', ('registration_declarations',)), ('ordessa_harness_claude_code.registration_declarations', ('registration_declarations',)), ('ordessa_harness_opencode.registration_declarations', ('registration_declarations',)), ('ordessa_harness_hermes.registration_declarations', ('registration_declarations',)), ('ordessa_harness_dsh.registration_declarations', ('registration_declarations',)), ('ordessa_harness_kilo.registration_declarations', ('registration_declarations',)), ('ordessa_harness_pi.registration_declarations', ('registration_declarations',)), ('ordessa_harness_grok_build.registration_declarations', ('registration_declarations',))), 'composition/selected_model_configuration.py': (('ordessa_harness_pi.configuration.c2', ('descriptor', 'declared_protocols', 'declared_model_control')), ('ordessa_harness_codex.configuration.c2', ('descriptor', 'declared_protocols', 'declared_model_control')), ('ordessa_harness_claude_code.configuration.c2', ('descriptor', 'declared_protocols', 'declared_model_control'))), 'composition/selected_native_configuration.py': (('ordessa_harness_pi.configuration.native_model', ('provider',)), ('ordessa_harness_codex.configuration.native_model', ('provider',)), ('ordessa_harness_claude_code.configuration.native_model', ('provider',)))}


def _audit_host_port_imports(sources):
    import ast
    seen = {}
    for relative, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith(("ordessa_harness", "ordessa_server_product"))
                               for a in node.names), relative
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("ordessa_harness"):
                    pair = (module, tuple(a.name for a in node.names))
                    assert pair in _APPROVED_HOST_PUBLIC_PORT_IMPORTS.get(relative, ()), (relative, pair)
                    seen.setdefault(relative, []).append(pair)
                if module.startswith("ordessa_server_product"):
                    assert (relative, module, tuple(a.name for a in node.names)) == (
                        "composition/configuration/product_selection.py",
                        "ordessa_server_product.composition", ("create_composition",)), relative
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if name in ("__import__", "import_module"):
                    # Selection ports must be statically reviewable, never brand discovery.
                    raise AssertionError((relative, "unreviewed dynamic module loading"))
    assert {k: tuple(v) for k, v in seen.items()} == _APPROVED_HOST_PUBLIC_PORT_IMPORTS


def test_host_brand_imports_are_exact_public_selection_ports():
    from pathlib import Path
    host = Path(__file__).resolve().parents[3] / "apps/server/src/ordessa_server"
    _audit_host_port_imports({p.relative_to(host).as_posix(): p.read_text()
                             for p in host.rglob("*.py")})


def test_host_public_selection_guard_rejects_foreign_and_internal_imports():
    import pytest
    baseline = {k: "\n".join("from " + module + " import " + ", ".join(names)
                             for module, names in pairs)
                for k, pairs in _APPROVED_HOST_PUBLIC_PORT_IMPORTS.items()}
    for relative, injected in (
        ("composition/runtime.py", "from ordessa_harness_pi.configuration.c2 import descriptor"),
        ("composition/selected_model_configuration.py", "from ordessa_harness_pi.configuration._deployment import provider"),
        ("composition/selected_model_configuration.py", "from ordessa_harness_pi.configuration.c2 import *"),
        ("composition/runtime.py", "from ordessa_server_product.harness_adapters.generic.factory import create"),
        ("composition/runtime.py", "import ordessa_harness_unknown"),
        ("composition/runtime.py", "__import__('ordessa_harness_pi.configuration._deployment')"),
    ):
        with pytest.raises(AssertionError):
            _audit_host_port_imports({**baseline, relative: baseline.get(relative, "") + "\n" + injected})
