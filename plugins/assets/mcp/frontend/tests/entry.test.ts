// Plugin entry proof: real Workbench/Chat contribution tokens are required,
// registration goes through the real chat-api service and a faithful fake of
// the Workbench composition, and the fail-closed branches are asserted:
// no wire client ⇒ NO Settings section + unavailable chat panel.

import { describe, expect, it } from 'vitest'
import { OwnedResources, Token, type PluginContext, type ResourceScope } from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench, type WorkbenchSettingsSection } from '@extensions/ordessa.contracts/contract.js'
import { ChatContributionsToken, createChatContributions } from '@extensions/ordessa.chat-api/contract.js'
import createPlugin, { MCP_SETTINGS_SECTION_ID, registerMcpFrontend } from '../src/entry'

function fakeWorkbench() {
  const sections: WorkbenchSettingsSection[] = []
  const workbench: Workbench = {
    forScope: () => ({ addView: () => { throw new Error('unused') }, addUI: () => { throw new Error('unused') } }),
    open: () => {}, close: () => {},
    composition: {
      forScope: () => ({
        addModule: () => { throw new Error('unused') },
        addOverlay: () => { throw new Error('unused') },
        addSettingsSection: section => {
          sections.push(section)
          return { isDisposed: false, dispose() { const i = sections.indexOf(section); if (i >= 0) sections.splice(i, 1) } }
        },
      }),
      activateModule: () => {}, openOverlay: () => { throw new Error('unused') }, openSettings: () => {},
    },
  }
  return { workbench, sections }
}

const context = (): { ctx: PluginContext; scope: OwnedResources } => {
  const scope = new OwnedResources()
  const ctx: PluginContext = {
    root: { mount: () => { throw new Error('unused') } },
    resources: scope as ResourceScope,
  }
  return { ctx, scope }
}

describe('ordessa.asset-mcp plugin shape', () => {
  it('requires the real platform tokens and carries the extension identity', () => {
    const plugin = createPlugin(undefined, undefined)
    expect(plugin.id).toBe('ordessa.asset-mcp')
    expect(plugin.autoStart).toBe(true)
    // The exact shared token objects — not lookalikes: same construction sites.
    expect(plugin.requires).toContain(WorkbenchToken)
    expect(plugin.requires).toContain(ChatContributionsToken)
    expect(Token).toBeDefined()
  })

  it('without a wire client: no Settings section is registered, the chat source still answers unavailable', async () => {
    const plugin = createPlugin(undefined, undefined)
    const { ctx, scope } = context()
    const { workbench, sections } = fakeWorkbench()
    const chat = createChatContributions()
    await plugin.activate(ctx, workbench, chat)
    expect(sections).toHaveLength(0)
    const view = chat.queryInputSources({ location: { kind: 'session', connectionId: 'c', sessionId: 's', contextRevision: 1 }, query: '', surface: 'plus', signal: new AbortController().signal })
    for (let i = 0; i < 50 && view.getSnapshot().some(source => source.state.status === 'loading'); i++) await new Promise(r => setTimeout(r, 0))
    expect(view.getSnapshot().find(source => source.source.id === 'ordessa.asset.mcp.chat-status')?.entries[0]?.title).toBe('MCP 状态服务不可用')
    // Closing the plugin scope revokes exactly this extension's registrations.
    scope.dispose()
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(0)
  })

  it('with a configured wire base the Settings section registers under the owner id', async () => {
    const plugin = createPlugin(undefined, { wire: { baseUrl: 'http://127.0.0.1:41207' } })
    const { ctx } = context()
    const { workbench, sections } = fakeWorkbench()
    await plugin.activate(ctx, workbench, createChatContributions())
    expect(sections.map(section => section.id)).toEqual([MCP_SETTINGS_SECTION_ID])
    expect(sections[0].title).toBe('MCP 服务器')
  })

  it('registerMcpFrontend is the shared seam the session-service owner can drive with its own client', () => {
    const { ctx } = context()
    const { workbench, sections } = fakeWorkbench()
    registerMcpFrontend(ctx.resources, workbench, createChatContributions(), { wireClient: undefined })
    expect(sections).toHaveLength(0)
  })
})
