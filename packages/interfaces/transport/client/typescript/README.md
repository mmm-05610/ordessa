# @ordessa/system-access-client

Host-independent TypeScript client. Uses the existing `@ordessa/interface-contracts` WirePort/result contract; no Electron, app or business imports.

`HttpWirePort` is extracted from the Desktop ServerBridge implementation. Inject origin, wire path prefix, scope, token reader and optionally fetch/timeout. It retains Accepted/Refused/Unknown results and never automatically retries commands. Desktop provides the existing shared-layout path and main-process token reader; the renderer never receives credentials.

`QueryClient` is explicitly for a selected read query. It coalesces refresh calls, publishes state through subscribe/getSnapshot, retains the last accepted data and timestamp through failure, and marks stale until a successful refresh. It does not discover business methods or create a second business object model. Server event subscriptions require an actual published event protocol; local state subscriptions do not claim to provide one.

HTTP regression coverage remains under `apps/desktop/electron/server-bridge/tests`; refresh lifecycle coverage is in `workbench/status-board/src/tests/store.test.ts`.
