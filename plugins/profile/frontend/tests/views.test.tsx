// @vitest-environment jsdom
/** View render gates (PV-08/09, ux.md §1/§2): real provider rows only,
 * non-empty buckets, offline banner, conflict banner, unsaved bar. */
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import type { ProfileIdentityDto, ProfileServiceClient } from '@ordessa/plugin-profile-api'
import { MechanismPolicyStore, ProfileDraftStore } from '../src/stores'
import { ProfileManagementView } from '../src/management-view'
import { ProfileSettingsView } from '../src/settings-view'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

const POLICY = {
  realm: 'local', revision: 2,
  facetEnabled: { model_selection: false },
  allowUserOverrideWritesGlobal: true,
  allowUserOverrideWrites: {},
}

function fakePolicyClient() {
  return {
    async getMechanismPolicy() { return { ...POLICY, facetEnabled: { ...POLICY.facetEnabled } } },
    async updateMechanismPolicy() { throw new Error('not used here') },
    async previewMechanismPolicy() { return { policy: POLICY, impact: { disabling: {} }, preview: true } },
  } as unknown as ProfileServiceClient
}

it('settings view lists only real providers and never a fake autoswitch switch', async () => {
  const store = new MechanismPolicyStore(fakePolicyClient())
  await store.load('local')
  const container = await mount(
    <ProfileSettingsView
      realms={['local']}
      realm="local"
      onRealmChange={() => {}}
      store={store}
      facetLabels={{ model_selection: '模型配置' }}
      onReload={() => {}}
      sections={[]}
    />,
  )
  const text = container.textContent ?? ''
  expect(text).toContain('模型配置')
  expect(container.querySelectorAll('[data-facet-row]')).toHaveLength(1)
  // no phantom provider entries and no fake agent-autoswitch control
  expect(text).not.toContain('Agent 自动切换')
  expect(container.querySelector('[data-profile-section]')).toBeNull() // no sections → no empty card
  const disabledRow = container.querySelector('[data-facet-row="model_selection"] input')
  expect((disabledRow as HTMLInputElement | null)?.checked).toBe(false)
})

it('management view groups by harness, filters archives, and shows the unsaved bar', async () => {
  const profiles = [
    { profileId: 'p1', displayName: '开发助手', harnessId: 'pi', archivedAt: null },
    { profileId: 'p2', displayName: '旧配置', harnessId: 'pi', archivedAt: '2026-01-01' },
    { profileId: 'p3', displayName: '默认', harnessId: 'codex', archivedAt: null },
  ]
  const client = {} as ProfileServiceClient
  const draft = new ProfileDraftStore(client, {
    profileId: 'p1', version: 1, displayName: '开发助手', harnessId: 'pi',
    currentRevision: 1, archivedAt: null, createdAt: 't', updatedAt: 't', realm: 'local',
  } satisfies ProfileIdentityDto)
  draft.edit({ facetId: 'model', itemId: 'model', op: 'set', value: 'm2' })
  const container = await mount(
    <ProfileManagementView
      profiles={profiles}
      selectedId="p1"
      onSelect={() => {}}
      search=""
      onSearch={() => {}}
      showArchived={false}
      onShowArchived={() => {}}
      onCreate={() => {}}
      draft={draft}
      onSave={() => {}}
      onDiscard={() => {}}
      categoryContent={{ 模型: <p>模型字段</p>, 能力: null }}
      offline
    />,
  )
  const text = container.textContent ?? ''
  const groups = container.querySelectorAll('[data-harness-group]')
  expect(groups.length).toBe(2) // pi (active only) + codex
  expect(text).toContain('默认')
  expect(text).not.toContain('旧配置')
  expect(container.querySelector('[data-unsaved-bar]')).not.toBeNull()
  expect(text).toContain('模型字段')
  expect(container.querySelector('[data-category="能力"]')).toBeNull() // empty bucket hidden
  expect(container.querySelector('[data-profile-manager]')?.textContent).toContain('离线')
})
