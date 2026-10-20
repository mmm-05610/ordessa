# ordessa-sandbox-backend

This independent Server plugin lives at `plugins/agents/resources/sandbox/backend`
(distribution `ordessa-sandbox-backend`). It owns the native Sandbox backend
service, intent/evidence repository, verifier and the read-only
`sandbox.describe` method. Its public DTOs are in the sibling Sandbox API
package at `plugins/agents/resources/sandbox/api`; it registers through the
Server plugin API. The public neutral `SandboxV1` resource DTO is defined by the execution SDK
at `packages/interfaces/execution/c1-api/src/ordessa_execution_api/environment/runtime_composition.py`; Kernel consumes that contract. This Sandbox backend does not own or redefine it.

## Pin and catalogue boundary

`SandboxOptionCatalogue` returns no options for an absent or unknown pin; it
never guesses from a brand. The production Server captures selected Harness
registration declarations in `apps/server/src/ordessa_server/composition/selected_harness_catalog.py`
and binds that registry to the Server product through
`apps/server/src/ordessa_server/composition/runtime.py`. The product passes
measured family/version pins from that captured registry to
`SandboxAdaptersServerPlugin` (`apps/server/deployment/default-product/src/ordessa_server_product/composition.py`).
That adapter pin flow does not populate this backend plugin's catalogue: the
current `build_sandbox_plugin()` call supplies no catalogue, so its backend
service starts with an empty catalogue and describes options as unknown unless
a catalogue is explicitly injected. Do not describe the backend as reading a
repository TOML or as receiving those adapter pins.

`SandboxOptionCatalogue.from_repo()` is a separate explicit file-loading
helper. Tests that use it first capture the host-selected declaration bytes
through `capture_selected_harness_catalog()` and write those bytes to a
temporary file (`tests/_sandbox_backend_helpers.py`); it is not the production
Server startup path.

## Native effect boundary

The backend registers `sandbox.native-configuration@1` and
`sandbox.describe@1`, plus the read-only `sandbox.describe` wire method. Its
`ConfigurationTarget` and `EffectProbe` protocols remain unbound. The current
plugin can report only evidence supplied through its ports; it does not apply
configuration to a real Harness. Do not treat `verified` fixtures or the
existence of brand adapters as live native-effect acceptance.

The plugin has no Permissions dependency. Its dependency-direction suite
checks that package imports do not load Permissions, Server internals, or
Pacthold internals.

## Focused checks

```sh
.venv-nightly/bin/python -m pytest -q plugins/agents/resources/sandbox/backend
```

The historical T04b evidence under
`docs/implementation/specifications/011-q5-safety/evidence/` records its own
source revision and does not establish current product wiring or live native
application.
