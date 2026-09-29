"""Shared test support for the server-registration slice.

Builds a REAL host (`build_runtime`, explicit composition with the storage
provider the default product injects) with the workspace plugin plus
`SkillsServerPlugin`, starts it, and drives every call through
`runtime.wire.dispatch` — the one dispatch wall the product uses. No
private shortcuts: no direct handler invocation, no registry mutation.

Error reading across the dispatch wall: since the foundation checkpoint the
plugin's domain refusals leave the handlers as the published
`server_plugin_api.ServerError` (converted at the wire boundary by
`error_families.to_server_error`) and the host projects them through this
composition's `wire.error-families` contribution — the api-requests.md §G1
"no plugin-visible typed refusal" gap is closed and consumed. The helpers
below assert BOTH halves of the answer: the wire family the host published
for the code, and the domain refusal preserved on `__cause__`.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from server_plugin_api import WireError

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPAT_BOUNDARY_FILE = (REPO_ROOT / "apps" / "server" / "tests"
                        / "test_server_compat_boundary.py")

# The sibling plugin and host sources: in the package-isolation venv
# (G21) `ordessa_workspace` is a real installed wheel and nothing is
# added here; the repo `src/` path is a fallback only when the module is
# not importable, the same way tests/conftest.py does it (paths only, no
# import reordering). These are TEST-side paths: the src surface stays
# pinned by tests/test_dependency_direction.py.
import importlib.util as _ilu  # noqa: E402

_ws_src = REPO_ROOT / "plugins" / "workspace" / "src"
if (_ilu.find_spec("ordessa_workspace") is None
        and _ws_src.is_dir() and str(_ws_src) not in sys.path):
    sys.path.append(str(_ws_src))

from ordessa_server.bootstrap.runtime import build_runtime  # noqa: E402
from ordessa_workspace.plugin import WorkspaceServerPlugin  # noqa: E402

from ordessa_skills.error_families import SKILLS_ERROR_FAMILIES  # noqa: E402
from ordessa_skills.plugin import SkillsServerPlugin  # noqa: E402
from ordessa_skills.wire import SKILLS_METHOD_IDS  # noqa: E402,F401


def frozen_compat_methods() -> frozenset[str]:
    """`FROZEN_COMPAT_METHODS` from the boundary test file itself — the
    host's frozen compat surface is pinned where it lives, not duplicated.
    (Loaded from source because apps/server/tests is not an importable
    package; this is the same file-load pattern its own conftest uses.)"""
    spec = importlib.util.spec_from_file_location(
        "server_compat_boundary_pin", COMPAT_BOUNDARY_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.FROZEN_COMPAT_METHODS)


@pytest.fixture
def runtime(tmp_path):
    """A bare host composed with exactly the workspace + skills plugins.

    `requires=("ordessa.skills" -> "ordessa.workspace")` — the declared
    dependency must be in the selection, so the composition carries both;
    product assembly of the default set is §G1 (C0).

    Since foundation the storage provider is a product decision: an
    explicit plugin selection without a database factory refuses typed
    (`SERVER_PRODUCT_MISSING`) unless an installed product answers. This
    test composition injects the very class the default product hands the
    host (`products/server` `ServerProductComposition.database_type()` →
    `pacthold_runtime_compat.storage.Database`), so the wire chain runs
    against the real storage assembly without depending on the entry
    point.

    `contribute_harness_adapters=False`: `build_runtime` activates the
    explicit plugin selection INSIDE the call, and an explicit bare
    composition declares no product contribution points — the
    `harness.configuration-adapters` point is bound only through
    `products/server` `server_contribution_points()` (the §G1 assembly).
    A contribution to an unbound point refuses activation fail-closed,
    so this wire fixture opts out explicitly; the adapters' real-registry
    path is proven end-to-end in `test_harness_api_registration.py`
    against the published handler and a live `ServerPluginHost` round.
    """
    from pacthold_runtime_compat.storage import Database

    rt = build_runtime(
        tmp_path / "data-root",
        server_plugins=(WorkspaceServerPlugin(),
                        SkillsServerPlugin(contribute_harness_adapters=False)),
        database_factory=Database)
    rt.start()
    try:
        yield rt
    finally:
        rt.stop()


_counter = 0


def request_id(prefix: str = "req") -> str:
    global _counter
    _counter += 1
    return f"{prefix}-{_counter:08d}"


def dispatch(rt, method: str, **params):
    merged = {"requestId": request_id()}
    merged.update(params)
    return rt.wire.dispatch(method, merged)


def domain_code(exc: BaseException) -> str | None:
    """The typed refusal code behind the host's projection wall.

    After the foundation seam the handler-side `AssetDomainError` is
    converted to `server_plugin_api.ServerError` (carrying the same `code`)
    at the wire edge, and `WireError.from_server_error` chains THAT as
    `__cause__`; the ServerError in turn keeps the domain error one more
    link down. Reading `.code` off the immediate cause therefore returns
    the domain's frozen spelling either way.
    """
    cause = exc.__cause__
    return getattr(cause, "code", None)


def expect_domain_refusal(rt, method: str, code: str, **params):
    info = _raises_wire(rt, method, **params)
    assert domain_code(info.value) == code, (
        f"{method}: expected typed code {code!r}, got "
        f"family={info.value.family!r} cause={info.value.__cause__!r}")
    # The seam is genuinely consumed: the code leaves the wire projected
    # onto the family this domain CONTRIBUTED to the host's
    # `wire.error-families` point (never the generic UNAVAILABLE
    # class-name fall-through a handler exception used to get).
    assert info.value.family == SKILLS_ERROR_FAMILIES[code], (
        f"{method}: code {code!r} must project onto the contributed family "
        f"{SKILLS_ERROR_FAMILIES[code]!r}, got {info.value.family!r}")
    assert info.value.details.get("internalCode") == code, (
        f"{method}: the frozen internal code must survive the projection: "
        f"{info.value.details!r}")
    return info.value


def _raises_wire(rt, method: str, **params):
    with pytest.raises(WireError) as info:
        dispatch(rt, method, **params)
    return info


def expect_shape_refusal(rt, method: str, **params):
    """A declared-shape refusal, answered by the host wall itself."""
    with pytest.raises(WireError) as info:
        dispatch(rt, method, **params)
    assert info.value.family == "INVALID_REQUEST"
    return info.value


def manifest_bytes(name: str, body: str) -> bytes:
    text = (f"---\nname: {name}\ndescription: A demo skill for tests.\n"
            f"---\n\n{body}\n")
    return text.encode("utf-8")


def import_skill(rt, *, asset_id: str, revision: int, approve: bool = True,
                 body: str | None = None) -> dict:
    """The full chunked import protocol through the wire: begin → chunk →
    preview → commit (→ approve). Returns the commit result."""
    payload = manifest_bytes(asset_id, body or f"Body revision {revision}.")
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    begun = dispatch(rt, "skills.importBegin",
                     files=[{"path": "SKILL.md", "bytes": len(payload),
                             "sha256": digest}],
                     totalBytes=len(payload))
    import_id = begun["importId"]
    dispatch(rt, "skills.importChunk", importId=import_id, chunkIndex=0,
             payloadBase64=base64.b64encode(payload).decode(), sha256=digest)
    dispatch(rt, "skills.importPreview", importId=import_id,
             source={"kind": "local"})
    committed = dispatch(rt, "skills.importCommit", importId=import_id,
                         assetId=asset_id, revision=revision)
    if approve:
        preview_digest = committed["asset"]["digest"]
        dispatch(rt, "skills.approveRevision", assetId=asset_id,
                 revision=revision, expectedDigest=preview_digest)
    return committed


def open_workspace(rt, tmp_path, name: str = "proj") -> str:
    """Seed a real workspace row through the workspace plugin's public
    `workspace.records` port (the host-sanctioned cross-plugin surface).

    The full-wire route (`workspaces.open`, local environment) needs the
    deployment's sandbox provider `agent_box_sandbox_bwrap`, which is not
    present in this tree — the same registered artifact gap that keeps the
    apps/server suite from collecting (docs/known-issues.md). Seeding via
    the port keeps this honest: every SKILLS method still runs exclusively
    through real wire dispatch, against a workspace fact the registry
    itself issued.
    """
    records = rt.plugin_host.provided_port("workspace.records")
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    _created, row = records.upsert_by_location(
        env_kind="local", env_host=None, remote_user=None,
        normalized_path=str(path.resolve()), connection_id=None,
    )
    return str(row["id"])


def blob(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)
