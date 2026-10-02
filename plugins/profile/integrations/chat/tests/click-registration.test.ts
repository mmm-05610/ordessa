/** Click-time registration (021 appendix §6c F1.1/F1.2, codex review F1).
 *
 * A bound chat session's explicit Profile selection must reach the backend at
 * CLICK time — the click order, not the submit order, is the intent order the
 * session's action_seq stamps. The tests below drive the REAL glue's projected
 * picker props (the same `onSelect` the composer button invokes), so the wire
 * sequence asserted here is the production one.
 *
 * Red before the fix: the old glue only wrote the frontend store on select and
 * deferred `selectForSession` to applyOnSubmit, so a later model click won the
 * action_seq race and silently overrode the user's last click.
 */
import { expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { createProfileChatGlue } from '../src/glue'
import type { ProfilePickerProps } from '../src/picker-model'
import type { ProfileServiceClient, ProfileSelection, AppliedReceiptDto, NativeCreationPreparationDto, SessionRef } from '@ordessa/plugin-profile-api'

const selection = { profileId: 'profile', displayName: 'P', harnessId: 'pi', archived: false }
const next = { profileId: 'next', displayName: 'N', harnessId: 'pi', archived: false }
const ref: SessionRef = { realm: 'local', harnessId: 'pi', nativeSessionKey: 'native', sessionUid: 'canonical' }
const receipt: AppliedReceiptDto = { operationId: 'op', sessionRef: ref, runtimeGeneration: '1',
  configDigest: 'digest', profileId: 'profile', profileRevision: 1, overlayRevision: null, policyRevision: 1,
  providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' }
const draftSnapshot: ChatSubmissionSnapshot = { submissionId: 'send', draftId: 'draft', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 },
  text: 'keep text', attachmentIds: [] }
const sessionLocation = { kind: 'session' as const, connectionId: 'client',
  serverInstanceId: 'server', sessionId: 'native', harnessId: 'pi', contextRevision: 1 }

function setup() {
  const scope = new OwnedResources(), chat = createChatContributions(), order: string[] = []
  const registrations: string[] = []
  let registerFail: string | null = null
  let nativePrepared = false
  let currentProfileId = 'profile'
  const currentReceipt = () => ({ ...receipt, profileId: currentProfileId })
  const profiles = {
    async registerNativeSession() { order.push('register'); return { sessionRef: ref } },
    async selectForSession(_operation: string, input: { profileId: string }) {
      order.push(`select:${input.profileId}`)
      registrations.push(input.profileId)
      if (registerFail) throw new Error(registerFail)
      currentProfileId = input.profileId
      return {}
    },
    async inspectSessionConfig() { return { sessionRef: ref, switchState: 'settled', current: { profileId: currentProfileId, revision: 1 }, pending: null,
      evidence: { receipt: currentReceipt(), evidenceKind: receipt.evidenceKind, journal: { operationId: 'op', state: 'confirmed' } } } },
    async beginTurnApplication() {
      order.push(`apply:${currentProfileId}`)
      return { turnId: 'turn', appliedSwitch: false, receipt: currentReceipt() }
    },
    async prepareNativeCreation(input: { connectionId: string; profileId: string; operationId: string }) {
      order.push('prepare-provider')
      return { state: 'not-required', operationId: input.operationId, connectionId: input.connectionId,
        profileId: input.profileId, harnessId: 'pi', profileRevision: 1 } as NativeCreationPreparationDto
    },
  } as unknown as ProfileServiceClient
  const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'client', draft: { active: true, canSend: true } }),
    subscribe: () => () => undefined,
    async prepareSubmission(preparation) {
      order.push('prepare')
      // beforeCreate belongs to session CREATION only: an existing session's
      // submission reuses its identity and never re-prepares the provider
      if (preparation && !nativePrepared) {
        await preparation.beforeCreate(Object.freeze({ attemptId: 'attempt', serverInstanceId: 'server',
          connectionId: 'channel', harnessId: 'pi', workspaceId: 'project' }))
        nativePrepared = true
      }
      return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel', nativeSessionId: 'native', harnessId: 'pi', workspaceId: 'project' }
    },
  } })
  const gateway = { async submit() { order.push('prompt'); return { status: 'accepted' as const } } }
  const pickerProps = (location: unknown = sessionLocation): ProfilePickerProps => {
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
      .filter(item => item.id === 'ordessa.profile-chat.picker')
    const projected = view?.project?.({ slot: 'composer.toolbar' as const, location: location as never,
      connection: { status: 'connected' as const } })
    if (!projected || projected.hidden) throw new Error('picker unexpectedly hidden')
    return projected.props as ProfilePickerProps
  }
  return { scope, chat, glue, order, registrations,
    failRegister: (reason: string | null) => { registerFail = reason },
    pickerProps, gateway }
}

/** One ordinary draft submit, so the chat session owns a registered binding. */
async function bindSession(f: ReturnType<typeof setup>, picked: ProfileSelection = selection) {
  f.glue.store.select('draft:draft', picked)
  expect(await f.chat.submit(draftSnapshot, f.gateway)).toEqual({ status: 'accepted' })
  f.order.length = 0
  f.registrations.length = 0
}

it('registers a bound-session selection at click time, before any submit, with zero native effects', async () => {
  const f = setup()
  try {
    await bindSession(f)
    f.pickerProps().onSelect(next)
    await vi.waitFor(() => expect(f.order).toContain('select:next'))
    // the click itself never applies, prepares or restarts anything (FR-04)
    expect(f.order).toEqual(['select:next'])
    expect(f.registrations).toEqual(['next'])
  } finally { f.scope.dispose() }
})

it('serializes consecutive clicks in click order with a fresh registration each', async () => {
  const f = setup()
  try {
    await bindSession(f)
    f.pickerProps().onSelect(selection)
    f.pickerProps().onSelect(next)
    await vi.waitFor(() => expect(f.registrations).toEqual(['profile', 'next']))
    expect(f.order).toEqual(['select:profile', 'select:next'])
  } finally { f.scope.dispose() }
})

it('surfaces a failed click registration in the picker props and keeps the selection for retry', async () => {
  const f = setup()
  try {
    await bindSession(f)
    f.failRegister('wire lost')
    f.pickerProps().onSelect(next)
    await vi.waitFor(() => expect(f.order).toContain('select:next'))
    await vi.waitFor(() => expect(f.pickerProps().registrationError).toContain('wire lost'))
    // the pick is kept, unregistered — a later submit retries the registration
    expect(f.glue.store.peek('session:native')).toEqual(next)
    f.failRegister(null)
    f.order.length = 0
    expect(await f.chat.submit({ ...draftSnapshot, submissionId: 'send2',
      target: sessionLocation }, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prepare', 'select:next', 'apply:next', 'prompt'])
  } finally { f.scope.dispose() }
})

it('a draft click registers nothing: registration stays at submit after the native session exists', async () => {
  const f = setup()
  try {
    f.pickerProps({ kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 })
      .onSelect(selection)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(f.order).toEqual([])
    expect(f.glue.store.peek('draft:draft')).toEqual(selection)
    // the submit registers the pick and applies it, as before
    expect(await f.chat.submit(draftSnapshot, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prepare', 'prepare-provider', 'register', 'select:profile', 'apply:profile', 'prompt'])
  } finally { f.scope.dispose() }
})

it('a bound submit after a click-registered pick applies once without reselecting', async () => {
  const f = setup()
  try {
    await bindSession(f)
    f.pickerProps().onSelect(next)
    await vi.waitFor(() => expect(f.order).toContain('select:next'))
    f.order.length = 0
    expect(await f.chat.submit({ ...draftSnapshot, submissionId: 'send2',
      target: sessionLocation }, f.gateway)).toEqual({ status: 'accepted' })
    // no second registration at submit: the click already owns the action_seq
    expect(f.order).toEqual(['prepare', 'apply:next', 'prompt'])
  } finally { f.scope.dispose() }
})

it('projects the click-order seam: registration tasks run one after another, in submission order', async () => {
  const f = setup()
  try {
    await bindSession(f)
    const seam = f.pickerProps().serializeRegistration
    expect(typeof seam).toBe('function')
    const events: string[] = []
    let release!: () => void
    const first = new Promise<void>(resolve => { release = resolve })
    const second = seam!(() => first.then(() => { events.push('first') }))
    const third = seam!(async () => { events.push('second') })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(events).toEqual([]) // the second task waits for the first to finish
    release()
    await Promise.all([second, third])
    expect(events).toEqual(['first', 'second'])
  } finally { f.scope.dispose() }
})

it('an unregistered pick is registered by the submit guard before it is applied', async () => {
  const f = setup()
  try {
    await bindSession(f)
    f.glue.store.select('session:native', next) // store-level pick: not registered
    f.order.length = 0
    expect(await f.chat.submit({ ...draftSnapshot, submissionId: 'send2',
      target: sessionLocation }, f.gateway)).toEqual({ status: 'accepted' })
    // the guard registered it, then applied exactly once
    expect(f.order).toEqual(['prepare', 'select:next', 'apply:next', 'prompt'])
  } finally { f.scope.dispose() }
})
