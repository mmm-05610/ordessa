// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { ProfileServiceToken, type ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { ChatContributionsToken, createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, WirePortToken, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { createUiComponentsService } from '../../../../../packages/frontend/ui-components/src/index'
import createPlugin from '../src/entry'
import { ProfilePickerKey } from '../src/glue'
import { ProfilePicker } from '../src/picker'
import type { ProfilePickerProps } from '../src/picker-model'
import { ProfileCatalog } from '../src/catalog'
import { AgentSessionsToken, type AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'

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
  const writes: Readonly<Record<string, unknown>>[] = []
  const records = new Map<string, { revision: number; resolved: Record<string, unknown> }>()
  const wire: WirePort = {
    ready: true,
    scope: 'http://127.0.0.1:9|server_profile_test',
    async call(method, params) {
      if (method === 'agent.session.resolve') {
        return { kind: 'Accepted', requestId: 'resolve', result: { target: 'canonical-profile-draft', generation: 9 } }
      }
      const target = String(params.target)
      let record = records.get(target)
      if (!record) { record = { revision: 0, resolved: {} }; records.set(target, record) }
      if (method === 'agent.config.read') {
        return { kind: 'Accepted', requestId: 'read', result: {
          ownerRef: `agent-config:${target}`, revision: record.revision, observedEvidence: 'unset',
          fields: Object.fromEntries(Object.keys(record.resolved).map(key => [key, 'known'])),
          resolved: { ...record.resolved },
        } }
      }
      if (method === 'agent.config.submitOperation') {
        const patch = params.patch as Record<string, unknown>
        writes.push(patch)
        Object.assign(record.resolved, patch)
        record.revision += 1
        return { kind: 'Accepted', requestId: `write-${record.revision}`, result: {
          operationId: `operation-${record.revision}`, patchKinds: Object.keys(patch).map(() => 'present' as const), state: 'pending',
        } }
      }
      return { kind: 'Refused', requestId: 'unexpected', reason: `unexpected method ${method}`, retryable: false }
    },
  }
  const sessions = {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'connection-profile-test', runtimeGeneration: 9 }),
    subscribe: () => () => undefined,
  } as unknown as AgentSessions
  const profiles = {
    profileCatalog,
    resolvePreview: vi.fn(async (profileId: string) => ({
      profileId, harnessId: 'pi', revision: profileId === 'a' ? 3 : 4, digest: `digest:${profileId}`,
      unavailable: [], conflicts: [],
      items: profileId === 'a'
        ? [{ facetId: 'general', itemId: 'prompt', value: 'A prompt', state: 'explicit', source: { kind: 'profile', revision: 3 } }]
        : [{ facetId: 'general', itemId: 'prompt', value: 'B prompt', state: 'explicit', source: { kind: 'profile', revision: 4 } }],
    })),
  } as unknown as ProfileServiceClient
  const plugin = createPlugin()
  const glue = plugin.activate({ resources, root: { mount() { throw Error('Profile Chat must not mount a root') } } }, profiles, chat, ui, wire, sessions)
  const props = () => {
    const view = chat.contributionsBySlot('composer.toolbar').getSnapshot()[0]!
    const projection = view.project!({ slot: 'composer.toolbar', location: snapshot.target, connection: { status: 'connected' } })
    if (projection.hidden) throw Error('picker unexpectedly hidden')
    return projection.props as ProfilePickerProps
  }
  return { resources, chat, ui, plugin, glue, profileCatalog, profiles, props, writes, records, wire }
}

it('activates the default factory with shared tokens and original key; scope revokes provider', async () => {
  const state = setup()
  // WirePort and AgentSessions are required because this production consumer
  // resolves backend-issued canonical targets and fences their generation.
  expect(state.plugin.requires).toEqual([ProfileServiceToken, ChatContributionsToken, UiComponentsToken, WirePortToken, AgentSessionsToken])
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
  state.props().onSelect(A)
  await vi.waitFor(() => expect(state.writes).toHaveLength(1))
  expect(state.writes[0]).toEqual({ 'general.prompt': 'A prompt' })
  expect([...state.records.values()].map(record => record.resolved)).toEqual([{ 'general.prompt': 'A prompt' }])
  expect(state.profiles.resolvePreview).toHaveBeenCalledWith('a', undefined)
  expect(snapshot.text).toBe('保留草稿')
  state.resources.dispose()
  expect(state.chat.contributionsBySlot('composer.toolbar').getSnapshot()).toEqual([])
  expect(binding.getSnapshot()).toMatchObject({ status: 'missing' })
  expect(await state.chat.submit(snapshot, gateway)).toEqual({ status: 'accepted' })
})

it('renders directory failure, explicitly refreshes new profiles, and dispatches only present Profile fields', async () => {
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
  await vi.waitFor(() => expect(state.writes).toHaveLength(1))
  expect(container.textContent).toContain('预设 B')
  expect(state.profiles.resolvePreview).toHaveBeenCalledWith('b', undefined)
  // The second Profile has no model field, so this backend operation preserves
  // every model choice and only carries its explicit prompt field.
  expect(state.writes[0]).toEqual({ 'general.prompt': 'B prompt' })
  expect([...state.records.values()].map(record => record.resolved)).toEqual([{ 'general.prompt': 'B prompt' }])
  expect(snapshot.text).toBe('保留草稿')
  const gateway = { submit: vi.fn(async () => ({ status: 'accepted' as const })) }
  expect(await state.chat.submit(snapshot, gateway)).toEqual({ status: 'accepted' })
  expect(gateway.submit).toHaveBeenCalledTimes(1)
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
