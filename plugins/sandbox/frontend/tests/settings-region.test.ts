// FR-05/FR-06/FR-08/FR-09 behaviour of the Sandbox Settings region, driven
// through the real Workbench composition API
// (packages/workbench/src/model.ts -> composition.forScope().addSettingsSection)
// so the section's presence/absence is proven against the actual contribution
// point rather than a stand-in registry.
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../../packages/workbench/src/model'
import {
  SANDBOX_SETTINGS_SECTION_ID,
  SANDBOX_SETTINGS_SECTION_TITLE,
  createInMemoryDraftStore,
  createSandboxSettingsRegion,
  resolveSandboxRegionState,
} from '../src/settings-region'
import {
  REQUEST, claudeDescribe, codexDescribe, describeResult, fakeTransport,
  noProvider, ok, option, providerError, unknownPinDescribe,
} from './fixtures'

function host() {
  const lifetime = new OwnedResources()
  const scope = new OwnedResources()
  const model = createWorkbench(lifetime)
  return { scope, sections: () => model.sections.getSnapshot().map(s => s.id), host: model.composition.forScope(scope) }
}

const lockedCodex = () => describeResult({
  lockedByAdministrator: true,
  options: [
    option({ lockedByAdministrator: true }),
    option({ optionId: 'sandbox_mode=workspace-write' }),
    option({ optionId: 'sandbox_mode=danger-full-access', status: 'unsupported', coverage: [] }),
  ],
})

describe('the region appears only when the backend contributes it (FR-08)', () => {
  it('no sandbox provider installed => the Settings section is never registered', async () => {
    const { sections, host: h } = host()
    const region = await createSandboxSettingsRegion({
      host: h, transport: fakeTransport(noProvider()).transport, request: REQUEST,
      drafts: createInMemoryDraftStore(),
    })
    expect(region.registered).toBe(false)
    expect(sections()).toEqual([])
  })

  it('an uninstalled facet (backend visible=false) leaves no broken placeholder', async () => {
    const { sections, host: h } = host()
    const region = await createSandboxSettingsRegion({
      host: h, request: REQUEST, drafts: createInMemoryDraftStore(),
      transport: fakeTransport(ok(describeResult({ visible: false, status: 'uninstalled', options: [] }))).transport,
    })
    expect(region.registered).toBe(false)
    expect(sections()).toEqual([])
  })

  it('a present-but-failing provider registers a local error state, not an absence', async () => {
    const { sections, host: h } = host()
    const region = await createSandboxSettingsRegion({
      host: h, transport: fakeTransport(providerError('adapter blew up')).transport,
      request: REQUEST, drafts: createInMemoryDraftStore(),
    })
    expect(region.registered).toBe(true)
    expect(sections()).toEqual([SANDBOX_SETTINGS_SECTION_ID])
    expect(region.getSnapshot().state.kind).toBe('provider-error')
    await region.select('sandbox_mode=read-only')
    expect(region.drafts.read(REQUEST.harnessId)).toBeUndefined()
  })

  it('the section carries the domain title the UX names', async () => {
    const { sections, host: h } = host()
    await createSandboxSettingsRegion({
      host: h, transport: fakeTransport(ok(codexDescribe())).transport, request: REQUEST,
      drafts: createInMemoryDraftStore(),
    })
    expect(sections()).toEqual([SANDBOX_SETTINGS_SECTION_ID])
    expect(SANDBOX_SETTINGS_SECTION_TITLE).toBe('Harness 原生隔离')
  })

  it('describe for an unknown pin contributes no menu at all', async () => {
    const state = await resolveSandboxRegionState(
      fakeTransport(ok(unknownPinDescribe())).transport, REQUEST)
    expect(state.kind).toBe('unknown-pin')
    if (state.kind !== 'unknown-pin') throw Error('unreachable')
    expect(state.menu).toEqual([])
  })
})

describe('selection refuses rather than guessing (FR-06/FR-09)', () => {
  const ready = async (result = codexDescribe()) => {
    const { host: h } = host()
    const drafts = createInMemoryDraftStore()
    const region = await createSandboxSettingsRegion({
      host: h, transport: fakeTransport(ok(result)).transport, request: REQUEST, drafts,
    })
    return { region, drafts }
  }

  it('a supported option applies and persists the draft', async () => {
    const { region, drafts } = await ready()
    expect(await region.select('sandbox_mode=workspace-write')).toEqual({
      status: 'applied', optionId: 'sandbox_mode=workspace-write',
    })
    expect(drafts.read('codex')).toEqual({ optionId: 'sandbox_mode=workspace-write' })
  })

  it('an unsupported option cannot be selected', async () => {
    const { region, drafts } = await ready()
    const outcome = await region.select('sandbox_mode=danger-full-access')
    expect(outcome).toMatchObject({ status: 'refused', code: 'SANDBOX_NATIVE_UNSUPPORTED' })
    expect(drafts.read('codex')).toBeUndefined()
  })

  it('an unproven (unknown) option refuses with the unknown code, never merged with unsupported', async () => {
    const { region } = await ready(claudeDescribe())
    expect(region.getSnapshot().state.kind).toBe('ready')
    expect(await region.select('bash_sandbox=enabled'))
      .toMatchObject({ status: 'refused', code: 'SANDBOX_EFFECT_UNKNOWN' })
  })

  it('an option absent from describe is refused instead of being invented', async () => {
    const { region } = await ready(unknownPinDescribe())
    expect(await region.select('sandbox_mode=read-only'))
      .toMatchObject({ status: 'refused', code: 'SANDBOX_NATIVE_UNSUPPORTED' })
  })

  it('an administrator-locked option is read-only and widening it is refused with a stable code', async () => {
    const { region, drafts } = await ready(lockedCodex())
    expect(region.getSnapshot().state.kind).toBe('ready')
    const widening = await region.select('sandbox_mode=workspace-write')
    expect(widening).toMatchObject({ status: 'refused', code: 'SANDBOX_CONFIG_CONFLICT' })
    // the refusal is surfaced, never silently downgraded to the locked value
    expect(drafts.read('codex')).toBeUndefined()
    expect(await region.select('sandbox_mode=read-only')).toEqual({
      status: 'applied', optionId: 'sandbox_mode=read-only',
    })
  })

  it('a late click against a superseded describe generation does not land', async () => {
    const { host: h } = host()
    const drafts = createInMemoryDraftStore()
    const transport = fakeTransport(ok(codexDescribe()), ok(describeResult({ nativeVersion: '0.148.0' })))
    const region = await createSandboxSettingsRegion({ host: h, transport: transport.transport, request: REQUEST, drafts })
    const stale = region.getSnapshot().generation
    await region.refresh()
    expect(await region.select('sandbox_mode=workspace-write', stale))
      .toMatchObject({ status: 'refused', code: 'PROVIDER_BUSY' })
    expect(drafts.read('codex')).toBeUndefined()
  })
})
