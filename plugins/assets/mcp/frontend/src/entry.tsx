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
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { ChatContributionsToken, type ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import { createFetchMcpWireClient, type McpWireClient } from './wire'
import { createMcpStatusService } from './status'
import { McpSettingsSection } from './settings'
import { createMcpChatInputSource, mcpStatusChipContribution, McpStatusChip } from './chat'

/** Product configuration slice forwarded verbatim by the host (extension-
 * loader `config`); opaque to the host, and the only thing the assembly may
*  hand this extension today. The wire CLIENT itself is meant to be provided
 * by the session-service owner; until that seam exists `wire.baseUrl` lets a
 * product point this glue at the server's `/wire/v1` surface. */
export interface McpFrontendConfig {
  readonly wire?: { readonly baseUrl?: string }
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

export default function createPlugin(_api?: unknown, config?: McpFrontendConfig) {
  return {
    id: 'ordessa.asset-mcp', autoStart: true,
    requires: [WorkbenchToken, ChatContributionsToken],
    activate: (context: PluginContext, workbench: Workbench, chat: ChatContributionsService) => {
      const baseUrl = config?.wire?.baseUrl
      const wireClient = baseUrl ? createFetchMcpWireClient({ baseUrl }) : undefined
      registerMcpFrontend(context.resources, workbench, chat, { ...(wireClient ? { wireClient } : {}) })
    },
  }
}

// Re-export the chip so the product assembly (C0) can map the key id in the
// chat frontend's component resolver table without importing this bundle's
// internals twice.
export { McpStatusChip, mcpStatusChipKey } from './chat'
