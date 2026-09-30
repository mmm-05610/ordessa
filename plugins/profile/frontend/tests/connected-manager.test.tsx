// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { profileFacetEditorKey, type ProfileFacetEditorProps, type ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { createUiComponentsService } from '../../../../packages/desktop-platform/ui-components/src/index'
import { ModelProfileEditor } from '../../../assets/model-provider/desktop/src/profile-editor'
import { createModelProviderService } from '../../../assets/model-provider/desktop/src/service'
import { ConnectedProfileManager } from '../src/connected-manager'
import { ProfileConfigurationPane } from '../src/configuration-pane'
import { ProfileDraftStore } from '../src/stores'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => Promise<void> | void)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); vi.restoreAllMocks() })

async function rig(options: { saveFails?: boolean; previewFails?: boolean; schemaVersion?: string } = {}) {
  let profile = { profileId: 'p1', harnessId: 'pi', realm: 'local', version: 1, currentRevision: 1,
    displayName: '开发', archivedAt: null, createdAt: 't', updatedAt: 't' }
  let value: unknown = { harnessId: 'pi', providerConfigId: 'provider1', modelId: 'm1' }
  let failPreview = !!options.previewFails
  const save = vi.fn(async (_key: string, input: { patches: { op: string; value?: unknown }[] }) => {
    if (options.saveFails) throw new Error('Profile Unknown: connection-lost')
    value = input.patches[0]?.op === 'unset' ? undefined : input.patches[0]?.value
    profile = { ...profile, version: profile.version + 1, currentRevision: profile.currentRevision + 1 }
    return { profile }
  })
  const client = { listProfiles: async () => [profile], saveProfile: save,
    describeFacets: async () => [{ facetId: 'assets.model-provider', schemaVersion: options.schemaVersion ?? '1', applicability: 'supported',
      itemDescriptors: [{ itemId: 'choice' }] }],
    resolvePreview: async () => {
      if (failPreview) { failPreview = false; throw new Error('catalog offline') }
      return { profileId: 'p1', harnessId: 'pi', revision: profile.currentRevision, conflicts: [],
        items: value === undefined ? [] : [{ facetId: 'assets.model-provider', itemId: 'choice', value }] }
    },
  } as unknown as ProfileServiceClient
  const service = createModelProviderService(async () => ({ items: [
    { id: 'provider1', displayName: 'API', harness: 'pi', archivedAt: null, models: [{ modelId: 'm1' }, { modelId: 'm2' }] },
    { id: 'wrong', displayName: '另一个品牌', harness: 'codex', archivedAt: null, models: [{ modelId: 'm3' }] },
  ], nextCursor: null }))
  const ui = createUiComponentsService([{ componentId: 'ordessa.profile.editor:assets.model-provider', major: 1, providerId: 'model-editor' }])
  const provider = new OwnedResources(), consumer = new OwnedResources()
  ui.uiComponents.forScope(provider).register({ key: profileFacetEditorKey('assets.model-provider'), providerId: 'model-editor',
    component: (props: ProfileFacetEditorProps) => <ModelProfileEditor {...props} service={service} /> })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  cleanup.push(() => { consumer.dispose(); provider.dispose(); ui.dispose() })
  cleanup.push(async () => { await act(async () => root.unmount()); host.remove() })
  await act(async () => root.render(<ConnectedProfileManager client={client} wire={{ ready: true, scope: 'local',
    async call() { return { kind: 'Accepted', requestId: 'x', result: { data: ['pi'] } } } }}
    ui={ui.uiComponents.forScope(consumer)} />))
  await act(async () => host.querySelector<HTMLButtonElement>('[data-profile-item="p1"]')!.click())
  return { host, save, provider, value: () => value }
}

it('edits an atomic provider/model choice and saves only once on explicit action', async () => {
  const { host, save } = await rig()
  const model = host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!
  expect(model.value).toBe('m1')
  expect(host.textContent).not.toContain('另一个品牌')
  await act(async () => { model.value = 'm2'; model.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(save).not.toHaveBeenCalled()
  await act(async () => { const button = host.querySelector<HTMLButtonElement>('[data-save]')!; button.click(); button.click() })
  expect(save).toHaveBeenCalledTimes(1)
  expect(save.mock.calls[0]?.[1]).toEqual({ profileId: 'p1', expectedVersion: 1, patches: [{
    facetId: 'assets.model-provider', itemId: 'choice', op: 'set',
    value: { harnessId: 'pi', providerConfigId: 'provider1', modelId: 'm2' },
  }] })
  expect(host.querySelector('[data-unsaved-bar]')).toBeNull()
})

it('clear is a draft unset and discard restores saved data without writing', async () => {
  const { host, save, value } = await rig()
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === '清除预设模型')!.click())
  expect(host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!.value).toBe('')
  await act(async () => host.querySelector<HTMLButtonElement>('[data-discard]')!.click())
  expect(host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!.value).toBe('m1')
  expect(save).not.toHaveBeenCalled()
  expect(value()).toEqual({ harnessId: 'pi', providerConfigId: 'provider1', modelId: 'm1' })
})

it('uncertain save retains edited input and does not retry automatically', async () => {
  const { host, save } = await rig({ saveFails: true })
  const model = host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!
  await act(async () => { model.value = 'm2'; model.dispatchEvent(new Event('change', { bubbles: true })) })
  await act(async () => host.querySelector<HTMLButtonElement>('[data-save]')!.click())
  expect(save).toHaveBeenCalledTimes(1)
  expect(host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!.value).toBe('m2')
  expect(host.querySelector('[data-unsaved-bar]')).not.toBeNull()
  expect(host.textContent).toContain('connection-lost')
})

it('unloading the editor hides its UI without deleting stored values', async () => {
  const { host, provider, value } = await rig()
  expect(host.querySelector('[aria-label="默认模型配置"]')).not.toBeNull()
  await act(async () => provider.dispose())
  expect(host.querySelector('[aria-label="默认模型配置"]')).toBeNull()
  expect(value()).toEqual({ harnessId: 'pi', providerConfigId: 'provider1', modelId: 'm1' })
})

it('configuration load failure can be retried in place', async () => {
  const { host } = await rig({ previewFails: true })
  expect(host.textContent).toContain('catalog offline')
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === '重试配置加载')!.click())
  expect(host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!.value).toBe('m1')
})

it('unknown model configuration schema is visible but read-only', async () => {
  const { host, save } = await rig({ schemaVersion: 'future' })
  expect(host.textContent).toContain('此版本的模型配置只读')
  expect(host.querySelector<HTMLSelectElement>('[aria-label="预设模型"]')!.disabled).toBe(true)
  expect([...host.querySelectorAll('button')].find(b => b.textContent === '清除预设模型')!.disabled).toBe(true)
  expect(save).not.toHaveBeenCalled()
})

it('a late preview cannot replace the newly selected profile', async () => {
  let release!: (value: unknown) => void
  const old = new Promise(resolve => { release = resolve })
  const client = { describeFacets: async () => [], resolvePreview: (id: string) => id === 'old' ? old :
    Promise.resolve({ profileId: id, harnessId: 'pi', revision: 1, conflicts: [], items: [] }) } as unknown as ProfileServiceClient
  const ui = createUiComponentsService([])
  const scope = new OwnedResources()
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  cleanup.push(() => { scope.dispose(); ui.dispose() })
  cleanup.push(async () => { await act(async () => root.unmount()); host.remove() })
  const render = (id: string) => {
    const profile = { profileId: id, harnessId: 'pi', realm: 'local', version: 1, currentRevision: 1,
      displayName: id, archivedAt: null, createdAt: 't', updatedAt: 't' }
    return <ProfileConfigurationPane client={client} profile={profile} draft={new ProfileDraftStore(client, profile)}
      ui={ui.uiComponents.forScope(scope)} generation={0} changed={() => {}} busy={false} />
  }
  await act(async () => root.render(render('old')))
  expect(host.textContent).toContain('读取预设配置')
  await act(async () => root.render(render('new')))
  expect(host.querySelector('[data-profile-configuration]')).not.toBeNull()
  // A stale, even malformed response must not damage the current selection.
  await act(async () => release({ profileId: 'wrong', harnessId: 'codex', revision: 42 }))
  expect(host.querySelector('[data-profile-configuration]')).not.toBeNull()
  expect(host.querySelector('[role="alert"]')).toBeNull()
})
