// ordessa.asset-mcp — MCP asset frontend glue (Q4 T08, advanceable part).
//
// Consumes only real platform APIs: the Workbench composition
// (`workbench.composition.forScope(...).addSettingsSection`, owner id
// `ordessa.asset.mcp.settings`) and the chat-api r3 ChatContributions service
// (`chatContribution()` + `addInputSource`). Nothing here re-implements a
// registry or a ServiceLocator.
//
// Service presence is fail-closed and visible:
// * no wire client (product config `wire.baseUrl` absent / session-service
//   owner not wired) → the Settings section is NOT registered (contracts.md §2
//   「后端 provider 缺席时设置区域不显示」) and the chat panel answers with an
//   `unavailable` entry;
// * the Credential service has no platform token yet → `credentials` stays
//   undefined, which makes secretRef fields read-only and blocks 批准并用于选择;
// * Profile facet UI is skipped in T08 (profile-api/foundation composition
//   incompatibility, Z1 r2) — registered in the T08 report, nothing here.

import type { PluginContext } from '@ordessa/extension-api'
import { WirePortToken, WorkbenchToken, type Workbench, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { ChatContributionsToken, type ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import { createWirePortMcpWireClient, type McpWireClient } from './wire'
import { createMcpStatusService } from './status'
import { McpSettingsSection } from './settings'
import { createMcpChatInputSource, mcpStatusChipContribution, McpStatusChip } from './chat'

/** Product configuration slice forwarded verbatim by the host (extension-
 * loader `config`); opaque to the host. The transport itself is the platform's
 * ONE wire port (`ordessa.wirePort.v1`, EA-1/D-021-7) — this slice only names
 * the caller principal the assembly chose, if any. The retired `wire.baseUrl`
 * route is gone: a locator in static config was the seam EA-1 retired. */
export interface McpFrontendConfig {
  readonly principal?: string
}

export const MCP_SETTINGS_SECTION_ID = 'ordessa.asset.mcp.settings'

/** Everything the registrations need, resolved once; split out so tests and
 * the future session-owner seam drive the same code path. */
export function registerMcpFrontend(
  scope: PluginContext['resources'],
  workbench: Workbench,
  chat: ChatContributionsService,
  deps: { readonly wireClient?: McpWireClient; readonly credentials?: undefined } = {},
): void {
  const status = createMcpStatusService(deps.wireClient)
  if (deps.wireClient) {
    const client = deps.wireClient
    // Absent composition = baseline Workbench: reject, do not fall back to
    // legacy view ids (WorkbenchComposition contract note).
    const composition = workbench.composition?.forScope(scope)
    if (composition) composition.addSettingsSection({
      id: MCP_SETTINGS_SECTION_ID, title: 'MCP 服务器', order: 40,
      component: () => <McpSettingsSection client={client} credentials={deps.credentials} />,
    })
  }
  const contributions = chat.forScope(scope)
  contributions.addInputSource(createMcpChatInputSource(deps.wireClient ? status : undefined))
  contributions.addContribution(mcpStatusChipContribution(deps.wireClient ? status : undefined))
}

/** The wire client the product route binds: the C-03 port plus the caller
 * identity. `serverScope` is the port's own read-only scope fact — when the
 * host has none (Server down, bridge absent) the identity is unnameable and
 * the client is honestly absent, which renders as the unavailable panel, not
 * an empty success. */
export function wireClientOf(wire: WirePort | undefined, config?: McpFrontendConfig): McpWireClient | undefined {
  if (wire === undefined || wire.scope === null || wire.scope === '') return undefined
  return createWirePortMcpWireClient(wire, {
    serverScope: wire.scope,
    principal: config?.principal ?? 'desktop-local',
  })
}

export default function createPlugin(_api?: unknown, config?: McpFrontendConfig) {
  return {
    id: 'ordessa.asset-mcp', autoStart: true,
    requires: [WorkbenchToken, ChatContributionsToken, WirePortToken],
    activate: (context: PluginContext, workbench: Workbench, chat: ChatContributionsService, wire?: WirePort) => {
      const wireClient = wireClientOf(wire, config)
      registerMcpFrontend(context.resources, workbench, chat, wireClient ? { wireClient } : {})
    },
  }
}

// Re-export the chip so the product assembly (C0) can map the key id in the
// chat frontend's component resolver table without importing this bundle's
// internals twice.
export { McpStatusChip, mcpStatusChipKey } from './chat'
