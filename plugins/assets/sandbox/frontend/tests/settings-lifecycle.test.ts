// FR-08 lifecycle: "卸载后配置项隐藏、值保留". Hiding removes only the UI
// contribution; the stored draft survives, and re-showing asks the backend
// again instead of replaying a cached availability answer.
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../../packages/workbench/src/model'
import {
  SANDBOX_SETTINGS_SECTION_ID,
  createInMemoryDraftStore,
  createSandboxSettingsRegion,
} from '../src/settings-region'
import { REQUEST, codexDescribe, describeResult, fakeTransport, noProvider, ok } from './fixtures'

function host() {
  const scope = new OwnedResources()
  const model = createWorkbench(new OwnedResources())
  return { scope, sections: () => model.sections.getSnapshot().map(s => s.id), host: model.composition.forScope(scope) }
}

describe('hide / re-show keeps the draft and re-reads the backend', () => {
  it('hiding removes the Settings contribution only; the stored draft survives', async () => {
    const { sections, host: h } = host()
    const drafts = createInMemoryDraftStore()
    const region = await createSandboxSettingsRegion({
      host: h, transport: fakeTransport(ok(codexDescribe())).transport, request: REQUEST, drafts,
    })
    await region.select('sandbox_mode=workspace-write')
    expect(sections()).toEqual([SANDBOX_SETTINGS_SECTION_ID])

    region.hide()
    expect(sections()).toEqual([])
    expect(drafts.read('codex')).toEqual({ optionId: 'sandbox_mode=workspace-write' })
  })

  it('re-showing calls describe again and takes the fresh answer, not cached availability', async () => {
    const { sections, host: h } = host()
    const drafts = createInMemoryDraftStore()
    const transport = fakeTransport(
      ok(codexDescribe()),
      noProvider(),                 // provider went away: region must disappear
      ok(describeResult({ nativeVersion: '0.148.0' })), // and come back with new facts
    )
    const region = await createSandboxSettingsRegion({ host: h, transport: transport.transport, request: REQUEST, drafts })
    expect(transport.calls).toHaveLength(1)
    await region.select('sandbox_mode=workspace-write')

    await region.refresh()
    expect(sections()).toEqual([])
    expect(transport.calls).toHaveLength(2)

    await region.show()
    expect(transport.calls).toHaveLength(3)
    expect(sections()).toEqual([SANDBOX_SETTINGS_SECTION_ID])
    expect(region.getSnapshot().state).toMatchObject({ kind: 'ready', nativeVersion: '0.148.0' })
    // the draft survived both the hide and the fresh describe
    expect(drafts.read('codex')).toEqual({ optionId: 'sandbox_mode=workspace-write' })
  })

  it('an uninstall answer (visible=false) hides the region while values stay stored', async () => {
    const { sections, host: h } = host()
    const drafts = createInMemoryDraftStore()
    const transport = fakeTransport(
      ok(codexDescribe()),
      ok(describeResult({ visible: false, status: 'uninstalled', options: [] })),
    )
    const region = await createSandboxSettingsRegion({ host: h, transport: transport.transport, request: REQUEST, drafts })
    await region.select('sandbox_mode=read-only')
    await region.refresh()
    expect(sections()).toEqual([])
    expect(region.registered).toBe(false)
    expect(drafts.read('codex')).toEqual({ optionId: 'sandbox_mode=read-only' })
  })
})
