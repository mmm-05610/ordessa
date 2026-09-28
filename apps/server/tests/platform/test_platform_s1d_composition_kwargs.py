"""T014-S1d: `build_runtime` carries no copy of the product's compat funnel.

The seven composition facts `harnesses`, `execution`, `execution_factory`,
`home_concurrency`, `shared_store_guards`, `subscription_files_for` and
`declared_credentials` existed on the host's composition root only so a
caller could hand them to the host, which forwarded them to the product
composition, which funnelled them into `ServerCompatPlugin` — a duplicate
of the funnel `products/server` already owns (`_COMPAT_KWARGS`). S1d
deleted the duplicate:

1. the signature names none of them (the FR-006 absence, checked at the
   symbol level, not by prose);
2. the one funnel remains the product's: passing a fact through
   `default_plugins` reaches the compatibility plugin that declares it —
   proven by injecting a sentinel `execution` through the product seam and
   reading it back off the composed plugin host;
3. the host source no longer forwards them anywhere.

If the parameters come back, gate 1 goes red; if the product funnel is
broken so a kwarg no longer reaches its plugin, gate 2 goes red; if a
caller is added to the host's forward list again, gate 3 goes red.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from ordessa_server.bootstrap import build_runtime
from ordessa_server.bootstrap import runtime as runtime_module

BUSINESS_KWARGS = (
    "harnesses", "execution", "execution_factory", "home_concurrency",
    "shared_store_guards", "subscription_files_for", "declared_credentials",
)


def test_build_runtime_signs_none_of_the_compat_business_kwargs():
    params = inspect.signature(runtime_module.build_runtime).parameters
    leaked = sorted(name for name in BUSINESS_KWARGS if name in params)
    assert leaked == []
    # The seams the host genuinely owns stay: storage primitives, the
    # credential store, the local provider (a location, not a domain) and
    # the plugin selection itself.
    assert set(params) == {
        "data_root", "secret_store", "local_workspace_provider", "server_plugins",
        "database_factory",
    }


def test_the_host_no_forwards_business_composition_facts():
    source = (Path(__file__).resolve().parents[4] / "apps" / "server" / "src"
              / "ordessa_server" / "bootstrap" / "runtime.py").read_text(encoding="utf-8")
    # The docstring may NAME the removed parameters (this slice's record);
    # the call graph may not: no `composition.default_plugins(<kwarg>)`
    # forwarding survives.
    assert "default_plugins(\n" not in source
    assert "default_plugins(harnesses" not in source
    assert "execution_factory=execution_factory" not in source
    assert "declared_credentials=tuple(declared_credentials)" not in source


def test_the_product_funnel_is_the_single_route_for_a_business_fact(tmp_path):
    """The deletion moved the route, not the reach: a sentinel injected
    through the product's `default_plugins` still lands on the plugin that
    owns the execution domain, and nowhere on the host."""
    from ordessa_server_product.composition import create_composition

    class _Port:
        def stop(self, timeout=None):
            return True

    port = _Port()
    runtime = build_runtime(
        tmp_path / "data",
        server_plugins=create_composition().compatibility_plugins(execution=port),
    )
    try:
        assert runtime.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp")
        compat = runtime.plugin_host.active("ordessa.server-compat")
        assert compat.registration.provided_ports["execution.port"] is port
        # The host itself keeps no reference to the injected object: the
        # runtime gained no execution attribute on the way.
        assert not hasattr(runtime, "execution")
        host_fields = {f for f in dir(runtime) if not f.startswith("_")}
        assert "execution" not in host_fields
    finally:
        runtime.stop()
