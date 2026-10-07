// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions } from '@extensions/ordessa.chat-api/contract.js'
import type { ChatLocation } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, WirePortToken, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { AgentSessionsToken, type AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'
import type { ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { createUiComponentsService } from '../../../../../packages/frontend/ui-components/src/index'
import createPlugin from '../src/entry'
import type { ProfilePickerProps } from '../src/picker-model'

const resourcesToDispose: OwnedResources[] = []
afterEach(() => { for (const resources of resourcesToDispose.splice(0)) resources.dispose() })

const location: ChatLocation = {
  kind: 'draft', draftId: 'draft-1', connectionId: 'connection-1', serverInstanceId: 'server-1',
  projectId: 'project-1', harnessId: 'harness-1', contextRevision: 4, runtimeGeneration: 9,
}
const profilesById = {
  A: {
    profileId: 'profile-A', harnessId: 'harness-1', displayName: 'Profile A', archived: false,
  },
  B: {
    profileId: 'profile-B', harnessId: 'harness-1', displayName: 'Profile B', archived: false,
  },
}
const groups = [{ harnessId: 'harness-1', harnessTitle: 'Harness 1', profiles: Object.values(profilesById) }]

function setup() {
  const resources = new OwnedResources()
  resourcesToDispose.push(resources)
  const chat = createChatContributions()
  const uiService = createUiComponentsService([
    { componentId: 'ordessa.profile.picker', major: 1, providerId: 'ordessa.profile-chat' },
  ])
  resourcesToDispose.push(uiService)
  const writes: Readonly<Record<string, unknown>>[] = []
  const records = new Map<string, { revision: number; resolved: Record<string, unknown> }>()
  const wire: WirePort = {
    ready: true,
    scope: 'origin:server-1',
    async call(method, params) {
      if (method === 'agent.session.resolve') {
        return { kind: 'Accepted', requestId: 'resolve', result: { target: 'canonical-draft-1', generation: 9 } }
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
          operationId: `operation-${record.revision}`, patchKinds: Object.keys(patch).map(() => 'present'), state: 'pending',
        } }
      }
      return { kind: 'Refused', requestId: 'unexpected', reason: `unexpected method ${method}`, retryable: false }
    },
  }
  const prepareSubmission = vi.fn(async () => {
    throw new Error('Profile selection must not prepare or create a native session')
  })
  const sessions = {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'connection-1', runtimeGeneration: 9 }),
    subscribe: () => () => undefined,
    selectConnection: async () => undefined,
    reconnect: async () => undefined,
    refreshSessions: async () => undefined,
    newSession: async () => undefined,
    openSession: async () => undefined,
    send: async () => ({ status: 'accepted' }),
    prepareSubmission,
    stop: async () => undefined,
    respond: async () => undefined,
    setOption: async () => undefined,
    commandCatalog: () => ({ kind: 'absent' }),
  } as unknown as AgentSessions
  const profiles = {
    profileCatalog: vi.fn(async () => groups),
    resolvePreview: vi.fn(async (profileId: string) => ({
      profileId,
      harnessId: 'harness-1',
      revision: profileId === 'profile-A' ? 3 : 4,
      digest: `digest:${profileId}`,
      unavailable: [], conflicts: [],
      items: profileId === 'profile-A'
        ? [
          { facetId: 'general', itemId: 'prompt', value: 'A prompt', state: 'explicit', source: { kind: 'profile', revision: 3 } },
          { facetId: 'assets.model-provider', itemId: 'choice', value: {
            harnessId: 'harness-1', providerConfigId: 'provider-1', modelId: 'model-1', configVersion: 7,
          }, state: 'explicit', source: { kind: 'profile', revision: 3 } },
        ]
        : [
          { facetId: 'general', itemId: 'prompt', value: 'B prompt', state: 'explicit', source: { kind: 'profile', revision: 4 } },
        ],
    })),
  } as unknown as ProfileServiceClient
  const plugin = createPlugin()
  const activate = plugin.activate as (...args: unknown[]) => { dispose?: () => void }
  activate({ resources, root: { mount: () => { throw new Error('not used') } } },
    profiles, chat, uiService.uiComponents, wire, sessions)
  const props = (): ProfilePickerProps => {
    const view = chat.contributionsBySlot('composer.toolbar').getSnapshot()[0]!
    const projection = view.project!({ slot: 'composer.toolbar', location, connection: { status: 'connected' } })
    if (projection.hidden) throw new Error('canonical Profile picker unexpectedly hidden')
    return projection.props as ProfilePickerProps
  }
  return { plugin, profiles, props, prepareSubmission, writes, records, wire }
}

it('the production Profile entry resolves only preview fields into the Agent canonical target', async () => {
  const state = setup()
  expect(state.plugin.requires).toContain(WirePortToken)
  expect(state.plugin.requires).toContain(AgentSessionsToken)
  expect(state.plugin.requires).toContain(UiComponentsToken)

  await state.props().onSelect(profilesById.A)
  await vi.waitFor(() => expect(state.writes).toHaveLength(1))
  await state.props().onSelect(profilesById.B)
  await vi.waitFor(() => expect(state.writes).toHaveLength(2))

  expect(state.profiles.resolvePreview).toHaveBeenNthCalledWith(1, 'profile-A', undefined)
  expect(state.profiles.resolvePreview).toHaveBeenNthCalledWith(2, 'profile-B', undefined)
  expect(state.writes[0]).toMatchObject({
    'general.prompt': 'A prompt',
    model: { harnessId: 'harness-1', providerConfigId: 'provider-1', modelId: 'model-1', configVersion: 7 },
  })
  expect(state.writes[1]).toEqual({ 'general.prompt': 'B prompt' })
  expect(state.prepareSubmission).not.toHaveBeenCalled()
  expect([...state.records.values()].map(record => record.resolved.model)).toEqual([
    { harnessId: 'harness-1', providerConfigId: 'provider-1', modelId: 'model-1', configVersion: 7 },
  ])
})
