# Claude SDK cutover scope

## Current ports and ownership

- `ordessa_harness_claude_code.factory`: explicit pinned SDK provider factory.
- `ClaudeHarnessProvider.validate_profile(ProfileContent) -> None`: pure native
  configuration validation, no registration or authority creation.
- `prepare(ProfileContent, PrepareContext) -> LaunchPlan`: immutable plan only.
- `open_session(process, context)`: explicit native-bootstrap-unavailable refusal.
- Agent/Profile/interaction authority belongs to the original Agent owners;
  environment/Use and process operations remain external. This leaf holds neither.

## Physically retired execution paths

Removed Python modules: `provider`, `sdk`, `assembly`, `configuration_face`,
`native_evidence`, `ownership`, `owner_projection`, `runtime_channel`, `termination`,
`unit_lifecycle`, `stream_json`, `server_plugin`, `profile`, `launch`, `composition`,
`command_declarations`, `installation_declarations`, `registration`,
`registration_declarations`, `acp_model_configuration`, `fake_claude`,
`native_identity`; also `configuration/` and `_registration_declarations/`.
`production` no longer exports capability/deployment emitters or a command main.
Metadata drops Unit/execution-api/infrastructure/server-plugin/official-SDK runtime
dependencies and publishes only the SDK provider entry point. No aliases survive.

## Exact residual consumers outside this write domain

`products/server/src/ordessa_server_product/harness_adapters/configuration/model/live_service.py`
still imports removed `configuration.runtime.ClaudeLiveModelRuntime`.
`products/server/.../configuration/model/common.py` consumes retained pure
`acp_model_facts`; this is data, not a runtime fallback.
The exact authorized staging path
`products/agent-tools/src/ordessa_cli/native_clients/claude.py` does not exist.

Existing leaf tests importing removed modules are deliberately retained, including
provider/SDK/stream-json/assembly/Unit lifecycle/owner projection/configuration
face/server-plugin/native locator/production-template/distribution assertions.
These require explicit assertion migration by the integration owner. Do not skip,
remove assertions, restore aliases or claim whole-leaf acceptance. Historical
Pacthold harness-kit and product native-client tests also import retired APIs.

New `tests/test_sdk_provider.py` supplies offline SDK/provider/import-boundary
assertions. Existing pure native compiler and attachment tests remain unchanged.
No tests, builds, dependency installs or model calls were run for this leaf change;
serial verification belongs to the integrator.

## Preserved sources versus unavailable capabilities

Native `claude-stream-json/1` framing and existing ids are unchanged. Native
bootstrap, control permission routing, interrupt, fresh receipt capture, continuation
and live configuration require explicit original Agent-owned protocol support.
The SDK provider never repurposes the historical ACP adapter as that support.
Packaging resources, license/source pins, attachments and pure compilers are kept
as existing source material; their old observations are not new runtime evidence.
