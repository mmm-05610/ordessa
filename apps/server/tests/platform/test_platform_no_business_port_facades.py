"""T014-S1b guard: the composition root carries no business port facades.

FR-006 forbids the host from being a bag of domain objects
(`specs/010-platform-core/spec.md`: 「宿主不承载业务门面」). Slice S1b deleted
`_RUNTIME_PORT_FACADES` and `_bind_runtime_facades()` from
`ordessa_server.bootstrap.runtime`, so what the active plugins provide is now
read only through the host wall — `plugin_host.provided_port("<port-name>")`.

A deletion alone is not a guard: nothing failed when this file was written to
check whether a future edit reintroduces a port-name→attribute bag on
`ServerRuntime`. Each guard below is paired with a counterexample in
`test_reintroducing_a_facade_is_caught...`: the detectors are shown to be able
to go red, so a pass here means the invariant holds, not that the check is
vacuous (constitution: 证据不假绿, 守卫必须有反例).
"""
from __future__ import annotations

from collections.abc import Mapping
import re

import pytest

from ordessa_server.bootstrap import build_runtime

#: The 21 fields the deleted `_RUNTIME_PORT_FACADES` table bound on
#: `ServerRuntime` (recovered verbatim from
#: `git show HEAD:apps/server/src/ordessa_server/bootstrap/runtime.py`).
#: Their absence is the removal; the ports they fronted stay reachable, but
#: only through the host wall.
FORMER_FACADE_ATTRIBUTES: tuple[str, ...] = (
    "service", "repository", "harnesses", "execution", "approvals", "queue",
    "model_configs", "account_records", "account_assets", "asset_records",
    "skill_assets", "mcp_assets", "asset_catalogs", "plugin_assets",
    "hook_records", "hook_triggers", "delegation_service", "delegation_tokens",
    "acp_channels", "events_stream_source", "compat_handlers",
)

#: Port names as the platform declares them: `"<ns>.<name>"`, lower-case ns.
PORT_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_.]*$")


def _bound_facades(runtime) -> tuple[str, ...]:
    """The former facade names currently present on this runtime instance."""
    return tuple(name for name in FORMER_FACADE_ATTRIBUTES if hasattr(runtime, name))


def _facade_tables(module) -> list[str]:
    """Module-level Mappings that look like a re-grown facade table.

    Deliberately simple, not clever: a non-empty Mapping whose values are all
    dotted port-name strings is exactly the shape `_RUNTIME_PORT_FACADES`
    had; the setattr loop that consumed it was table-shaped too, so a table
    back is what this catches. A binding smuggled in without a table is
    caught by the instance checks, not here.
    """
    flagged = []
    for attr_name, attr in vars(module).items():
        if attr_name.startswith("__") or not isinstance(attr, Mapping):
            continue
        values = list(attr.values())
        if values and all(isinstance(v, str) and PORT_NAME_RE.match(v) for v in values):
            flagged.append(attr_name)
    return flagged


# -- the composed runtime carries no business attributes ----------------------


def test_the_composed_runtime_binds_none_of_the_former_facade_attributes(tmp_path):
    """The 21 facade fields are gone, at the instance the composition returns.

    A built (not necessarily started) `ServerRuntime` must carry none of
    them: business ports are reachable only through the host wall,
    `plugin_host.provided_port("<port-name>")`, which resolves against the
    live round and answers None once the round is stopped — a snapshot
    attribute cannot promise either of those.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        assert _bound_facades(runtime) == ()
        assert hasattr(runtime, "plugin_host") and runtime.plugin_host is not None
    finally:
        runtime.stop()


def test_the_bootstrap_module_grew_no_replacement_binding_table():
    """`_RUNTIME_PORT_FACADES` may not come back under a new name.

    No module-level Mapping in `ordessa_server.bootstrap.runtime` may have
    values that are all dotted port names — the shape of the deleted table
    that fed the `setattr(runtime, field, provided_port(name))` loop.
    """
    import ordessa_server.bootstrap.runtime as runtime_module

    assert _facade_tables(runtime_module) == []


# -- the wall answers; the attribute does not ---------------------------------


def test_a_started_default_runtime_answers_facade_reads_with_attributeerror_while_the_wall_provides_the_same_port(tmp_path):
    """The pair, per real port: the old read fails, the sanctioned read works.

    `runtime.service` is no longer a thing the host carries; the very same
    object is one `provided_port("product.service")` call away. Same for
    `compat_handlers`/`compat.handlers` (the order-098/101/147 injection
    point). This is the live behaviour the deletion was for, not just the
    source shape.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        with pytest.raises(AttributeError):
            _ = runtime.service
        service = runtime.plugin_host.provided_port("product.service")
        assert service is not None
        assert hasattr(service, "list_credentials"), (
            "the wall must answer the real port object, not a stand-in")
        assert runtime.plugin_host.provided_port("product.service") is service, (
            "the wall must answer the same live port object twice")

        with pytest.raises(AttributeError):
            _ = runtime.compat_handlers
        handlers = runtime.plugin_host.provided_port("compat.handlers")
        assert handlers is not None
        assert runtime.plugin_host.provided_port("compat.handlers") is handlers
    finally:
        runtime.stop()


# -- counterexamples: the detectors must be able to fail -----------------------


def test_reintroducing_a_facade_is_caught_by_the_instance_guard_and_clears_once_removed(tmp_path):
    """Self-check for `_bound_facades`: fake the old binding, see it flagged.

    `setattr(runtime, "service", <port object>)` is exactly what
    `_bind_runtime_facades()` used to do; the guard must name it. After the
    attribute is removed the guard returns to clean, so the pass in the
    first test is the invariant holding, not the detector being blind.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        assert _bound_facades(runtime) == ()
        runtime.service = runtime.plugin_host.provided_port("product.service")
        assert runtime.service is not None  # the facade is genuinely bound
        assert _bound_facades(runtime) == ("service",)
        del runtime.service
        assert _bound_facades(runtime) == ()
    finally:
        runtime.stop()


def test_reintroducing_a_facade_table_is_caught_by_the_module_guard_and_clears_once_removed():
    """Self-check for `_facade_tables`: put a table-shaped Mapping back.

    An exact copy of the deleted table's signature — attribute names as keys,
    dotted port names as values — must be flagged on the live module, and the
    flag must disappear when the attribute is removed.
    """
    import ordessa_server.bootstrap.runtime as runtime_module

    assert _facade_tables(runtime_module) == []
    runtime_module._REGENERATED_FACADES = {
        "service": "product.service", "compat_handlers": "compat.handlers"}
    try:
        assert _facade_tables(runtime_module) == ["_REGENERATED_FACADES"]
    finally:
        del runtime_module._REGENERATED_FACADES
    assert _facade_tables(runtime_module) == []
