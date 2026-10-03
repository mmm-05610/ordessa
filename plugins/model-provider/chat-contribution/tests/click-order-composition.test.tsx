// @vitest-environment jsdom
// Cross-contribution click-order composition (021 appendix §6c F1.2, codex
// review F1): the REAL Profile chat glue and the REAL model-provider chat
// contribution registered in ONE chat registry. The two contributions'
// registration wire calls (profiles.v2.selectForSession and
// modelProvider.chooseForSession) must reach the Server in click order — the
// Profile glue's per-session serializer is the seam, read by the model side
// through the same read-side projection channel as the bound fact.
//
// Red before the fix: the old Profile glue emitted NO wire call on click (the
// registration was deferred to submit), so no ordering existed to observe and
// a later model click won the backend action_seq race.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { ChatModelSelector, PROFILE_BINDING_CONTRIBUTION_ID, profileRegistrationSeamOf, registerModelSelector, type SelectorWiring } from '../src/chat-api-entry'
import type { AgentWorkspaceSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'
// test-only cross-workspace composition: the two contributions must be the
// REAL modules for this acceptance (appendix §6c F1.3); production wiring
// resolves them independently through the extension host.
import { createProfileChatGlue } from '../../../profile/integrations/chat/src/glue'
import type { ProfilePickerProps } from '../../../profile/integrations/chat/src/picker-model'
import type { ProfileServiceClient, AppliedReceiptDto, NativeCreationPreparationDto, SessionRef } from '@ordessa/plugin-profile-api'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount())
  document.body.replaceChildren()
})

const selection = { profileId: 'profile', displayName: 'P', harnessId: 'pi', archived: false }
const next = { profileId: 'next', displayName: 'N', harnessId: 'pi', archived: false }
const ref: SessionRef = { realm: 'local', harnessId: 'pi', nativeSessionKey: 'native', sessionUid: 'canonical' }
const receipt: AppliedReceiptDto = { operationId: 'op', sessionRef: ref, runtimeGeneration: '1',
  configDigest: 'digest', profileId: 'profile', profileRevision: 1, overlayRevision: null, policyRevision: 1,
  providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' }
const draftSnapshot: ChatSubmissionSnapshot = { submissionId: 'send', draftId: 'draft', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 },
  text: 'keep text', attachmentIds: [] }
const pickerLocation = { kind: 'session' as const, connectionId: 'client',
  serverInstanceId: 'server', sessionId: 'native', harnessId: 'pi', contextRevision: 0 }
const modelLocation = { kind: 'session' as const, connectionId: 'client',
  serverInstanceId: 'server', sessionId: 'native', harnessId: 'pi', contextRevision: 0 }
const config = { id: 'p', version: 7, displayName: 'Fixture', harness: 'pi', archivedAt: null,
  models: [{ modelId: 'm', availability: 'available' }] }
const chooseAnswer = { outcome: 'pending-next-turn', sequence: 2, intentRoute: 'independent' }
const emptyObservation = { desired: null, lastConfirmed: null, revision: null, intentRoute: null }

function sessionsFixture() {
  const snapshotState: AgentWorkspaceSnapshot = { available: [], selectedConnectionId: 'client',
    selectionRevision: 1, runtimeGeneration: 1,
    agent: { selectedSessionId: 'native', connection: { status: 'connected' } } }
  return {
    getSnapshot: () => snapshotState,
    subscribe: () => () => undefined,
    async prepareSubmission() {
      return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel',
        nativeSessionId: 'native', harnessId: 'pi', workspaceId: 'project' }
    },
  }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

async function composed(invoke: ReturnType<typeof vi.fn>, timeline: string[], prebind = true) {
  const scope = new OwnedResources(), chat = createChatContributions()
  let holdSelect = false
  let releaseSelect: (() => void) | undefined
  const profiles = {
    async registerNativeSession() { timeline.push('profile-register'); return { sessionRef: ref } },
    async selectForSession(_operation: string, input: { profileId: string }) {
      timeline.push('profile-select')
      if (holdSelect) await new Promise<void>(resolve => { releaseSelect = resolve })
      return { sessionRef: input.sessionRef, pendingProfileId: input.profileId, pendingSeq: 1, switchState: 'pending' as const }
    },
    async inspectSessionConfig() { return { sessionRef: ref, switchState: 'settled', current: { ...selection, revision: 1 }, pending: null,
      evidence: { receipt, evidenceKind: receipt.evidenceKind, journal: { operationId: 'op', state: 'confirmed' } } } },
    async beginTurnApplication() { return { turnId: 'turn', appliedSwitch: false, receipt } },
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
      return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel', nativeSessionId: 'native', harnessId: 'pi', workspaceId: 'project' }
    },
  } })
  // bind the chat session once (draft submit → registered binding)
  if (prebind) {
    glue.store.select('draft:draft', selection)
    expect(await chat.submit(draftSnapshot, { async submit() { return { status: 'accepted' as const } } }))
      .toEqual({ status: 'accepted' })
  }
  timeline.length = 0
  // the REAL model contribution, wired to read the REAL Profile projection
  const wiring: SelectorWiring = {
    service: { list: async () => [config] } as never, invoke,
    sessions: sessionsFixture() as never,
    registrationSeam: location => profileRegistrationSeamOf(chat, location),
  }
  registerModelSelector(chat, scope, wiring)
  const pickerProps = (): ProfilePickerProps => {
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
      .filter(item => item.id === PROFILE_BINDING_CONTRIBUTION_ID)
    const projected = view?.project?.({ slot: 'composer.toolbar' as const, location: pickerLocation,
      connection: { status: 'connected' as const } })
    if (!projected || projected.hidden) throw new Error('picker unexpectedly hidden')
    return projected.props as ProfilePickerProps
  }
  const deferSelect = () => {
    holdSelect = true
    return { release: () => { holdSelect = false; releaseSelect?.() } }
  }
  return { scope, chat, wiring, pickerProps, timeline, deferSelect }
}

it('first Profile click registers an existing session before a later model click, without applying', async () => {
  const timeline: string[] = []
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.chooseForSession') timeline.push('model-choose')
    return chooseAnswer
  })
  const state = await composed(invoke, timeline, false)
  try {
    const hold = state.deferSelect()
    const props = state.pickerProps()
    props.onSelect(selection)
    const seam = profileRegistrationSeamOf(state.chat, pickerLocation)
    expect(seam).not.toBeNull()
    const model = seam!(() => invoke('modelProvider.chooseForSession', {}))
    await flush()
    expect(timeline).toEqual(['profile-register', 'profile-select'])
    hold.release()
    await model
    expect(timeline).toEqual(['profile-register', 'profile-select', 'model-choose'])
  } finally { state.scope.dispose() }
})

async function mountSelector(wiring: SelectorWiring) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={wiring} location={modelLocation as never} />))
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  return container
}

it('P-click then M-click: the Profile registration reaches the wire before the model choice', async () => {
  const timeline: string[] = []
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice')
      return { verdict: 'supported', reason: null, providerConfigId: 'p', configVersion: 7 }
    if (method === 'modelProvider.queryChoice') return emptyObservation
    if (method === 'modelProvider.chooseForSession') timeline.push('model-choose')
    return chooseAnswer
  })
  const state = await composed(invoke, timeline)
  try {
    await mountSelector(state.wiring)
    // P-click first: its registration is in flight...
    const gate = state.deferSelect()
    state.pickerProps().onSelect(next)
    await flush()
    expect(state.timeline).toEqual(['profile-select'])
    // ...so the M-click's chooseForSession waits behind it (click order kept)
    await act(async () => {
      document.querySelector<HTMLElement>('[role="option"]')!.click()
    })
    await flush()
    expect(state.timeline).toEqual(['profile-select'])
    gate.release()
    await flush()
    await flush()
    expect(state.timeline).toEqual(['profile-select', 'model-choose'])
  } finally { await state.scope.dispose() }
})

it('M-click then P-click: the model choice reaches the wire before the Profile registration', async () => {
  const timeline: string[] = []
  let releaseChoose!: () => void
  const chooseGate = new Promise<void>(resolve => { releaseChoose = resolve })
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice')
      return { verdict: 'supported', reason: null, providerConfigId: 'p', configVersion: 7 }
    if (method === 'modelProvider.queryChoice') return emptyObservation
    if (method === 'modelProvider.chooseForSession') {
      timeline.push('model-choose')
      await chooseGate
    }
    return chooseAnswer
  })
  const state = await composed(invoke, timeline)
  try {
    await mountSelector(state.wiring)
    // M-click first: the choose hangs in flight on the seam...
    await act(async () => {
      document.querySelector<HTMLElement>('[role="option"]')!.click()
    })
    await flush()
    expect(state.timeline).toEqual(['model-choose'])
    // ...so the P-click's registration waits behind it (click order kept)
    state.pickerProps().onSelect(next)
    await flush()
    await flush()
    expect(state.timeline).toEqual(['model-choose'])
    releaseChoose()
    await flush()
    await flush()
    expect(state.timeline).toEqual(['model-choose', 'profile-select'])
  } finally { await state.scope.dispose() }
})
