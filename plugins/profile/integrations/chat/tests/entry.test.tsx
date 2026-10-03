// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { ProfileServiceToken, type ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { ChatContributionsToken, createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken } from '@extensions/ordessa.contracts/contract.js'
import { createUiComponentsService } from '../../../../../packages/desktop-platform/ui-components/src/index'
import createPlugin from '../src/entry'
import { ProfilePickerKey } from '../src/glue'
import { ProfilePicker } from '../src/picker'
import type { ProfilePickerProps } from '../src/picker-model'
import { ProfileCatalog } from '../src/catalog'
import { AgentSessionsToken } from '@extensions/ordessa.agent-contracts/contract.js'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: (() => void | Promise<void>)[] = []
afterEach(async () => { for (const dispose of cleanups.splice(0).reverse()) await dispose() })
const A = { profileId: 'a', harnessId: 'pi', displayName: '预设 A', archived: false }
const B = { ...A, profileId: 'b', displayName: '预设 B' }
const groups = [{ harnessId: 'pi', harnessTitle: 'Pi', profiles: [A] }]
const snapshot: ChatSubmissionSnapshot = { submissionId: 'send1', draftId: 'd1', draftRevision: 1,
  target: { kind: 'draft', draftId: 'd1', contextRevision: 1 }, text: '保留草稿', attachmentIds: [] }

function setup(profileCatalog = vi.fn(async (_realm: string) => groups)) {
  const resources = new OwnedResources()
  cleanups.push(() => resources.dispose())
  const chat = createChatContributions()
  const service = createUiComponentsService([{ componentId: ProfilePickerKey.id, major: 1, providerId: 'ordessa.profile-chat' }])
  cleanups.push(() => service.dispose())
  const ui = service.uiComponents
  const beginTurnApplication = vi.fn(), selectForSession = vi.fn()
  const profiles = { profileCatalog, beginTurnApplication, selectForSession } as unknown as ProfileServiceClient
  const plugin = createPlugin()
  const glue = plugin.activate({ resources, root: { mount() { throw Error('Profile Chat must not mount a root') } } }, profiles, chat, ui)
  const props = () => {
    const view = chat.contributionsBySlot('composer.toolbar').getSnapshot()[0]!
    const projection = view.project!({ slot: 'composer.toolbar', location: snapshot.target, connection: { status: 'connected' } })
    if (projection.hidden) throw Error('picker unexpectedly hidden')
    return projection.props as ProfilePickerProps
  }
  return { resources, chat, ui, plugin, glue, profileCatalog, beginTurnApplication, selectForSession, props }
}

it('activates the default factory with shared tokens and the original key; scope revokes provider and guard', async () => {
  const state = setup()
  expect(state.plugin.requires).toEqual([ProfileServiceToken, ChatContributionsToken, UiComponentsToken, AgentSessionsToken])
  expect(state.plugin.id).toBe('ordessa.profile-chat')
  const consumer = new OwnedResources()
  cleanups.push(() => consumer.dispose())
  const binding = state.ui.forScope(consumer).bind(ProfilePickerKey, { required: false })
  expect(binding.getSnapshot()).toMatchObject({ status: 'ready', providerId: 'ordessa.profile-chat' })
  expect(state.chat.contributionsBySlot('composer.toolbar').getSnapshot()[0]?.key).toBe(ProfilePickerKey)
  await vi.waitFor(() => expect(state.props().getLiveProps!().groups).toEqual(groups))
  expect(state.profileCatalog).toHaveBeenCalledWith('local')
  const gateway = { submit: vi.fn(async () => ({ status: 'accepted' as const })) }
  expect(await state.chat.submit(snapshot, gateway)).toEqual({ status: 'accepted' })
  state.glue.store.select('draft:d1', A)
  expect(await state.chat.submit(snapshot, gateway)).toMatchObject({ status: 'refused', reason: expect.stringContaining('尚未接入') })
  expect(gateway.submit).toHaveBeenCalledTimes(1)
  expect(state.beginTurnApplication).not.toHaveBeenCalled()
  expect(state.selectForSession).not.toHaveBeenCalled()
  expect(state.glue.store.peek('draft:d1')).toEqual(A)
  expect(snapshot.text).toBe('保留草稿')
  state.resources.dispose()
  expect(state.chat.contributionsBySlot('composer.toolbar').getSnapshot()).toEqual([])
  expect(binding.getSnapshot()).toMatchObject({ status: 'missing' })
  expect(await state.chat.submit(snapshot, gateway)).toEqual({ status: 'accepted' })
})

it('renders directory failure, explicitly refreshes new profiles, and immediately shows a pure selection', async () => {
  const profileCatalog = vi.fn(async (_realm: string) => groups)
  profileCatalog.mockRejectedValueOnce(Error('目录断开'))
  const state = setup(profileCatalog)
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanups.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(<ProfilePicker {...state.props()} />))
  expect(container.textContent).toContain('目录断开')
  profileCatalog.mockResolvedValue([{ ...groups[0]!, profiles: [A, B] }])
  await act(async () => { container.querySelector<HTMLButtonElement>('[data-profile-refresh]')!.click() })
  const openPicker = async () => {
    await act(async () => {
      container.querySelector('[data-profile-trigger]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    })
  }
  await openPicker()
  expect(document.querySelectorAll('[data-profile-value]')).toHaveLength(2)
  await act(async () => {
    document.querySelector<HTMLElement>('[data-profile-value="pi::b"]')!.click()
  })
  expect(container.textContent).toContain('预设 B')
  expect(state.selectForSession).not.toHaveBeenCalled()
  expect(state.beginTurnApplication).not.toHaveBeenCalled()
  const gateway = { submit: vi.fn(async () => ({ status: 'accepted' as const })) }
  expect(await state.chat.submit(snapshot, gateway)).toMatchObject({ status: 'refused' })
  expect(gateway.submit).not.toHaveBeenCalled()
  expect(state.glue.store.peek('draft:d1')).toEqual({ profileId: B.profileId, harnessId: B.harnessId, displayName: B.displayName })
  await openPicker()
  await act(async () => { Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]')).find(item => item.textContent === '清除预设选择')!.click() })
  expect(state.glue.store.peek('draft:d1')).toBeNull()
  expect(container.querySelector('[data-profile-trigger]')?.textContent).toContain('选择预设')
  expect(await state.chat.submit(snapshot, gateway)).toEqual({ status: 'accepted' })
  expect(gateway.submit).toHaveBeenCalledTimes(1)
  expect(state.selectForSession).not.toHaveBeenCalled()
  expect(state.beginTurnApplication).not.toHaveBeenCalled()
  const priorRefreshes = profileCatalog.mock.calls.length
  await openPicker()
  expect(profileCatalog).toHaveBeenCalledTimes(priorRefreshes + 1)
})

it('a synchronously throwing directory client can be explicitly refreshed again', async () => {
  let attempts = 0
  const catalog = new ProfileCatalog({ profileCatalog() {
    if (++attempts === 1) throw Error('sync failure')
    return Promise.resolve(groups)
  } })
  await catalog.refresh()
  expect(catalog.message).toContain('sync failure')
  await catalog.refresh()
  expect(catalog.groups).toEqual(groups)
  expect(attempts).toBe(2)
  catalog.dispose()
})
