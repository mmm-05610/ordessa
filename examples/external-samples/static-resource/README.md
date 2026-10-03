# ordessa-sample-static-resource — external sample #2 (static resource package)

External sample #2 of spec 026 (`lifecycle-evidence.md` §SDK真实穿透与样例):
a **static resource package** that installs **without Server, Harness or
Profile** and is composed through the public contract only. It is an
independent build input under `examples/` — it is not a workspace member, not
a host import and not an application dependency, and nothing in the product
source tree references it.

## What it is

- dist name `ordessa-sample-static-resource`, import name
  `ordessa_sample_static_resource`.
- Ships one frozen JSON document
  (`src/ordessa_sample_static_resource/data/resources.json`) whose sha256 is
  pinned in `plugin.py` (`FROZEN_RESOURCES_SHA256`). The plugin verifies the
  digest at build time and refuses to activate over a mismatch — content is
  immutable and self-verifying.
- Runtime dependency: `ordessa-server-plugin-api` only. No Agent, Profile,
  Harness or Environment import anywhere in the package
  (`tests/test_access.py::test_plugin_imports_only_public_plugin_api_and_stdlib`
  pins this structurally).

## All owner (所有者)

- Plugin id / method owner: `ordessa.sample-static-resource`.
- The plugin owns exactly two read-only wire methods and nothing else:
  - `sample.resources.list` — returns the frozen document's resources in file
    order plus `contentSha256`;
  - `sample.resources.get` (`id`) — returns one resource plus
    `contentSha256`; unknown ids answer typed `NOT_FOUND`.
- `provided_ports` is empty and `requires` is empty: the sample consumes no
  host facade, provides nothing to other plugins, and writes nothing under
  the data root.

## Public capabilities (公开能力)

Compose it exactly as an outside deployment would, via the public seam:

```python
from ordessa_server.bootstrap import build_runtime
from ordessa_sample_static_resource import SampleStaticResourcePlugin

runtime = build_runtime(data_root, server_plugins=(SampleStaticResourcePlugin(),))
runtime.start()
runtime.wire.dispatch("sample.resources.list", {})
runtime.wire.dispatch("sample.resources.get", {"id": "sample-wire-notes"})
runtime.stop()
```

Installing the distribution never enables it (no entry points are declared):
composition happens only through an explicit `server_plugins` selection.
`server.hello` advertises exactly `sample.resources.list`,
`sample.resources.get` and `server.hello` itself — no session, model,
profile, harness, chat, agent or environment capability exists in this
composition.

## Absent behavior (缺席行为)

- Not composed: the two methods do not exist — they are absent from
  `server.hello` and dispatch answers the unknown-method refusal. Nothing
  keeps them alive on a second table.
- Built but not started: the registry carries the rows, the round gate
  refuses every business method typed (`INVALID_REQUEST` with
  `internalCode: ROUND_NOT_STARTED`); `server.hello` stays answerable so
  discovery never lies about the Server's existence.
- Frozen content corrupted (digest mismatch): typed startup failure
  (`SAMPLE_STATIC_RESOURCE_CONTENT_MISMATCH`) — unverified bytes are never
  served.
- Stopped round: both methods are retired with the round and dispatch
  refuses typed; `server.hello` remains answerable and honestly drops them.

## Lifecycle (生命周期)

- **Install**: `.venv/bin/python -m pip install -e examples/external-samples/static-resource`
  (a plain `pip install` from a built wheel works the same; build with
  `python -m build` if needed). Nothing else is installed and no product
  package is pulled in beyond the plugin-API contract.
- **Compose / start**: explicit `server_plugins=(SampleStaticResourcePlugin(),)`
  at `build_runtime`, then `runtime.start()`. Methods are available from the
  started round on; no start hooks, no storage, no data-root footprint.
- **Stop / exit**: `runtime.stop()` retires both methods with the round and
  releases the data root; the plugin holds no resource of its own. The only
  trace left behind is the generic Server data root the composition created.
- **Uninstall**: `pip uninstall ordessa-sample-static-resource` — the
  distribution leaves no entry point, no manifest registration and no on-disk
  state of its own.

## Test dependencies

`examples/` has no Python-package precedent (existing samples are npm
packages), so this sample's `pyproject.toml` declares only
`ordessa-server-plugin-api` (runtime) and `pytest` (dev). The access test
imports `ordessa_server` from the venv's existing editable install
(`apps/server`) and `server_plugin_api` from the venv's editable install
(`packages/backend/server-plugin-api`); installing the full product stack as
a dependency of a sample would contradict the sample's own premise (it must
install without Server/Harness/Profile). Run:

```bash
.venv/bin/python -m pip install -e examples/external-samples/static-resource -q
.venv/bin/python -m pytest examples/external-samples/static-resource -q
```
