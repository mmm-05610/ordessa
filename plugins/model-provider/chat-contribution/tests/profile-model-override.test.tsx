// @vitest-environment jsdom
// N2.1 — "the later operation overrides the earlier one" (逐项后操作覆盖前操作)
// across the TWO composer routes that can configure one native session:
//   Profile→模型, 模型→Profile, and a Profile that changes no model at all.
//
// Both REAL contributions are registered in ONE real chat registry: the Profile
// chat glue (plugins/profile/integrations/chat) and this package's selector.
// Every assertion is about what THIS frontend emits and orders — never a
// fabricated backend verdict.
//
// Honest scope (deliberately not overclaimed):
// - provable here: which registration wire call carries the LATER click (the
//   backend stamps its action_seq from that arrival order), that ONE explicit
//   send performs exactly ONE configuration application and ONE prompt, and
//   which pick the send gate consumes;
// - NOT provable here: which of two pending backend intents the Server ledger
//   finally resolves (backend / N1 surface). These tests pin the ORDER the
//   backend consumes and this frontend's own bookkeeping — not the backend's
//   ledger outcome.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { ChatModelSelector, PROFILE_BINDING_CONTRIBUTION_ID, clientRegistryOf, profileRegistrationSeamOf,
         registerModelSelector, type SelectorWiring } from '../src/chat-api-entry'
// test-only cross-workspace composition (same seam as click-order-composition):
// production wiring resolves the two contributions independently.
import { createProfileChatGlue } from '../../../../profile/integrations/chat/src/glue'
import type { ProfilePickerProps } from '../../../../profile/integrations/chat/src/picker-model'
import type { ProfileServiceClient, AppliedReceiptDto, NativeCreationPreparationDto, SessionRef } from '@ordessa/plugin-profile-api'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount())
  document.body.replaceChildren()
})

const profile = { profileId: 'profile', displayName: 'P', harnessId: 'pi', archived: false }
const otherProfile = { profileId: 'other', displayName: 'O', harnessId: 'pi', archived: false }
const ref: SessionRef = { realm: 'local', harnessId: 'pi', nativeSessionKey: 'native', sessionUid: 'canonical' }
const receipt = (profileId: string): AppliedReceiptDto => ({ operationId: `op-${profileId}`, sessionRef: ref,
  runtimeGeneration: '1', configDigest: 'digest', profileId, profileRevision: 1, overlayRevision: null,
  policyRevision: 1, providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' })
const sessionLocation = { kind: 'session' as const, connectionId: 'client', serverInstanceId: 'server',
  sessionId: 'native', harnessId: 'pi', contextRevision: 0 }
const config = { id: 'p', version: 7, displayName: 'Fixture', harness: 'pi', archivedAt: null,
  models: [{ modelId: 'm', availability: 'available' }, { modelId: 'n', availability: 'available' }] }
const emptyObservation = { desired: null, lastConfirmed: null, revision: null, intentRoute: null }
const draftSnapshot: ChatSubmissionSnapshot = { submissionId: 'send-0', draftId: 'draft', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 },
  text: 'keep text', attachmentIds: [] }
const sendSnapshot: ChatSubmissionSnapshot = { ...draftSnapshot, submissionId: 'send-1',
  target: { kind: 'session', sessionId: 'native', connectionId: 'client', harnessId: 'pi',
    serverInstanceId: 'server', contextRevision: 2 } }
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))

/** The two contributions in ONE registry, with the native session already bound
 * to a Profile — the state a real composer is in after its first send. */
async function composed(timeline: string[]) {
  const scope = new OwnedResources(), chat = createChatContributions()
  let currentProfileId = 'profile'
  // a click registers a PENDING intent; the explicit send is what commits it
  let pendingProfileId: string | null = null
  const profiles = {
    async registerNativeSession() { timeline.push('profile-register'); return { sessionRef: ref } },
    async selectForSession(_operation: string, input: { profileId: string }) {
      timeline.push(`profile-select:${input.profileId}`); pendingProfileId = input.profileId; return {}
    },
    async inspectSessionConfig() { return { sessionRef: ref, switchState: 'settled',
      current: { profileId: currentProfileId, revision: 1 }, pending: null,
      evidence: { receipt: receipt(currentProfileId), evidenceKind: 'controlled-fixture',
        journal: { operationId: receipt(currentProfileId).operationId, state: 'confirmed' } } } },
    async beginTurnApplication() {
      timeline.push('profile-apply')
      if (pendingProfileId !== null) { currentProfileId = pendingProfileId; pendingProfileId = null }
      return { turnId: 'turn', appliedSwitch: false, receipt: receipt(currentProfileId) }
    },
    async prepareNativeCreation(input: { connectionId: string; profileId: string; operationId: string }) {
      return { state: 'not-required', operationId: input.operationId, connectionId: input.connectionId,
        profileId: input.profileId, harnessId: 'pi', profileRevision: 1 } as NativeCreationPreparationDto
    },
  } as unknown as ProfileServiceClient
  const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'client', draft: { active: true, canSend: true } }),
    subscribe: () => () => undefined,
    async prepareSubmission(preparation) {
      await preparation?.beforeCreate(Object.freeze({ attemptId: 'attempt', serverInstanceId: 'server',
        connectionId: 'channel', harnessId: 'pi', workspaceId: 'project' }))
      return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel',
        nativeSessionId: 'native', harnessId: 'pi', workspaceId: 'project' }
    },
  } })
  glue.store.select('draft:draft', profile)
  currentProfileId = 'profile'
  expect(await chat.submit(draftSnapshot, { async submit() { return { status: 'accepted' as const } } }))
    .toEqual({ status: 'accepted' })
  timeline.length = 0

  const invoke = vi.fn(async (method: string, params?: { choice?: { modelId: string } }) => {
    if (method === 'modelProvider.inspectChoice')
      return { verdict: 'supported', reason: null, providerConfigId: 'p', configVersion: 7 }
    if (method === 'modelProvider.queryChoice') return emptyObservation
    if (method === 'modelProvider.chooseForSession') {
      timeline.push(`model-choose:${params?.choice?.modelId}`)
      return { outcome: 'pending-next-turn', sequence: 2, intentRoute: 'profile-overlay' }
    }
    timeline.push(`model-${method}`)
    return { outcome: 'no-intent' }
  })
  // cached by identity: useSyncExternalStore requires a stable snapshot object
  const sessionSnapshot = { available: [], selectedConnectionId: 'client', selectionRevision: 1,
    runtimeGeneration: 1, agent: { selectedSessionId: 'native', connection: { status: 'connected' as const } } }
  const wiring: SelectorWiring = {
    service: { list: async () => [config] } as never, invoke,
    sessions: {
      getSnapshot: () => sessionSnapshot,
      subscribe: () => () => undefined,
      async prepareSubmission() { return { sessionId: 'native', serverInstanceId: 'server',
        connectionId: 'channel', nativeSessionId: 'native', harnessId: 'pi', workspaceId: 'project' } },
    } as never,
    registrationSeam: location => profileRegistrationSeamOf(chat, location),
  }
  registerModelSelector(chat, scope, wiring)
  const pickerProps = (): ProfilePickerProps => {
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
      .filter(item => item.id === PROFILE_BINDING_CONTRIBUTION_ID)
    const projected = view?.project?.({ slot: 'composer.toolbar' as const, location: sessionLocation,
      connection: { status: 'connected' as const } })
    if (!projected || projected.hidden) throw new Error('picker unexpectedly hidden')
    return projected.props as ProfilePickerProps
  }
  const clickProfile = async (pick: typeof profile) => {
    await act(async () => { pickerProps().onSelect(pick) })
    await flush()
  }
  const pickModel = async (modelId: string) => {
    await act(async () => { document.body.querySelector<HTMLElement>(`[data-testid="model-option-p-${modelId}"]`)!.click() })
    await flush()
  }
  const trigger = () => document.body.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!
  return { scope, chat, glue, wiring, invoke, pickerProps, clickProfile, pickModel, trigger }
}

/** The one queue bookkeeping the composer UI and this package's submission
 * guard share for the bound native session — the frontend's OWN record of
 * which pick is newest. */
const pendingOf = (wiring: SelectorWiring) =>
  clientRegistryOf(wiring).get(JSON.stringify({
    serverInstanceId: 'server', harnessId: 'pi', acpSessionId: 'native' }))?.client.pending ?? null

async function mountSelector(wiring: SelectorWiring) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={wiring} location={sessionLocation as never} />))
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  return container
}

const send = async (state: Awaited<ReturnType<typeof composed>>) => {
  const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
  const result = await state.chat.submit(sendSnapshot, gateway, () => true)
  return { result, gateway }
}

it('N2.1a Profile→模型: the model choice reaches the wire after the Profile registration, survives the send, and one application runs', async () => {
  const timeline: string[] = []
  const state = await composed(timeline)
  try {
    const container = await mountSelector(state.wiring)
    await state.clickProfile(otherProfile)
    expect(timeline).toEqual(['profile-select:other'])
    await state.pickModel('m')
    // the LATER user operation is the model choice — that is the order the
    // backend stamps its action_seq from
    expect(timeline).toEqual(['profile-select:other', 'model-choose:m'])
    // and it is what the composer shows as the next-turn intent
    const label = container.querySelector('[data-testid="model-selector-trigger"]')!.textContent!
    expect(label).toContain('Fixture › m')
    expect(label).toContain('下轮使用')

    timeline.length = 0
    const { result, gateway } = await send(state)
    expect(result).toEqual({ status: 'accepted' })
    expect(timeline.filter(item => item === 'profile-apply')).toHaveLength(1) // ONE application
    expect(state.invoke.mock.calls.some(([method]) => method === 'modelProvider.beginTurnApplication'))
      .toBe(false) // the bound model route never applies a second time (M06)
    expect(gateway.submit).toHaveBeenCalledTimes(1) // ONE prompt
  } finally { state.scope.dispose() }
})

it('N2.1b 模型→Profile: the Profile registration is the later one and its pick is the newest registered intent for that session', async () => {
  const timeline: string[] = []
  const state = await composed(timeline)
  try {
    await mountSelector(state.wiring)
    await state.pickModel('m')
    expect(timeline).toEqual(['model-choose:m'])
    await state.clickProfile(otherProfile)
    // the Profile click is the LAST wire registration
    expect(timeline).toEqual(['model-choose:m', 'profile-select:other'])
    // …and it owns the session key as the newest REGISTERED pick
    expect(state.glue.store.peek('session:native')).toBe(otherProfile)
    expect(state.glue.store.isRegistered('session:native', otherProfile)).toBe(true)

    timeline.length = 0
    const { result, gateway } = await send(state)
    expect(result).toEqual({ status: 'accepted' })
    expect(timeline).toEqual(['profile-apply']) // the later Profile pick is what applies
    // the earlier model pick is never applied on top of it
    expect(state.invoke.mock.calls.some(([method]) => method === 'modelProvider.beginTurnApplication'))
      .toBe(false)
    expect(gateway.submit).toHaveBeenCalledTimes(1)
    // the applied configuration is the Profile's, not the earlier model pick's
    expect(state.glue.store.currentLabel('session:native')).toBe(otherProfile.displayName)
  } finally { state.scope.dispose() }
})

it('N2.1c a Profile pick that declares no model issues zero model-provider calls and leaves the shown model untouched', async () => {
  const timeline: string[] = []
  const state = await composed(timeline)
  try {
    await mountSelector(state.wiring)
    await flush()
    const before = state.invoke.mock.calls.length
    const shownBefore = state.trigger().textContent

    await state.clickProfile(otherProfile)

    // the Profile click touched ONLY the Profile service
    expect(timeline).toEqual(['profile-select:other'])
    expect(state.invoke.mock.calls).toHaveLength(before)
    expect(state.invoke.mock.calls.some(([method]) => method === 'modelProvider.chooseForSession')).toBe(false)
    expect(state.trigger().textContent).toBe(shownBefore)
    expect(state.trigger().textContent).not.toContain('下轮使用')

    timeline.length = 0
    const { result, gateway } = await send(state)
    expect(result).toEqual({ status: 'accepted' })
    expect(timeline.filter(item => item === 'profile-apply')).toHaveLength(1)
    expect(state.invoke.mock.calls.some(([method]) => method === 'modelProvider.beginTurnApplication')).toBe(false)
    expect(gateway.submit).toHaveBeenCalledTimes(1)
  } finally { state.scope.dispose() }
})

it('N2.1d a second model pick supersedes the first: only the newest stays pending and one send applies once', async () => {
  const timeline: string[] = []
  const state = await composed(timeline)
  try {
    const container = await mountSelector(state.wiring)
    await state.pickModel('m')
    expect(pendingOf(state.wiring)?.modelId).toBe('m')
    await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
    await state.pickModel('n')
    expect(timeline).toEqual(['model-choose:m', 'model-choose:n'])
    // the SECOND pick is what stays pending — the earlier one is superseded in
    // this frontend's own bookkeeping, not just visually on the trigger
    expect(pendingOf(state.wiring)?.modelId).toBe('n')
    const label = container.querySelector('[data-testid="model-selector-trigger"]')!.textContent!
    expect(label).toContain('Fixture › n')
    expect(label).not.toContain('Fixture › m')
    expect(container.querySelector('[data-testid="model-queue-error"]')).toBeNull()

    const { result, gateway } = await send(state)
    expect(result).toEqual({ status: 'accepted' })
    expect(timeline.filter(item => item === 'profile-apply')).toHaveLength(1)
    expect(gateway.submit).toHaveBeenCalledTimes(1)
  } finally { state.scope.dispose() }
})
