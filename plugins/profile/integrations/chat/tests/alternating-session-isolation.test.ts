// N2.3 / N2.4 on the Profile side: two sessions alternating their picks, a
// registration answer that arrives late, and an unknown application outcome.
//
// Counterexample under test: a click, a registration failure or an application
// that belongs to ONE native session must never change another session's pick,
// its label or its binding — and must never send or clear a queue.
import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { createProfileChatGlue } from '../src/glue'
import type { ProfilePickerProps } from '../src/picker-model'
import type { ProfileServiceClient, AppliedReceiptDto, ProfileSelection, SessionRef } from '@ordessa/plugin-profile-api'

const ALPHA = 'alpha', BETA = 'beta'
// identity-comparable: the store matches a pick by reference, so each pick
// is ONE object reused across assertions, never a fresh equal-looking one
const ALPHA_ONE = { profileId: 'alpha-one', displayName: 'ALPHA-ONE', harnessId: 'pi', archived: false }
const BETA_TWO = { profileId: 'beta-two', displayName: 'BETA-TWO', harnessId: 'pi', archived: false }
const ALPHA_TWO = { profileId: 'alpha-two', displayName: 'ALPHA-TWO', harnessId: 'pi', archived: false }
const refs: Record<string, SessionRef> = {
  [ALPHA]: { realm: 'local', harnessId: 'pi', nativeSessionKey: 'nat-alpha', sessionUid: 'uid-alpha' },
  [BETA]: { realm: 'local', harnessId: 'pi', nativeSessionKey: 'nat-beta', sessionUid: 'uid-beta' },
}
const ownerOf = (id: string) => ({ sessionId: id, serverInstanceId: 'server', connectionId: `channel-${id}`,
  nativeSessionId: refs[id].nativeSessionKey, harnessId: 'pi', workspaceId: 'project' })
const locationOf = (id: string) => ({ kind: 'session' as const, sessionId: id, connectionId: `channel-${id}`,
  serverInstanceId: 'server', harnessId: 'pi', contextRevision: 0 })
const snapshotFor = (id: string, submissionId: string): ChatSubmissionSnapshot => ({
  submissionId, draftId: `draft-${id}`, draftRevision: 1, text: `text of ${id}`, attachmentIds: [],
  target: locationOf(id),
})
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))
const receipt = (id: string, profileId: string): AppliedReceiptDto => ({ operationId: `op-${id}-${profileId}`,
  sessionRef: refs[id], runtimeGeneration: '1', configDigest: 'digest', profileId, profileRevision: 1,
  overlayRevision: null, policyRevision: 1, providerGenerations: {}, evidenceKind: 'controlled-fixture',
  confirmedAt: 'now' })

/** Two genuinely different native sessions behind one chat registry. */
function twoSessions(order: string[]) {
  const scope = new OwnedResources(), chat = createChatContributions()
  let selected = ALPHA
  const current: Record<string, string> = { [ALPHA]: 'seed', [BETA]: 'seed' }
  const pending: Record<string, string | null> = { [ALPHA]: null, [BETA]: null }
  const hold = new Map<string, Promise<void>>()
  let release: (() => void) | undefined
  const unknownFor = new Set<string>()
  const failFor = new Set<string>()
  const failRegistrationFor = new Set<string>()
  const needsRecovery = new Set<string>()
  const idOf = (ref: SessionRef) => (ref.nativeSessionKey === refs[BETA].nativeSessionKey ? BETA : ALPHA)
  const profiles = {
    async registerNativeSession(input: { nativeSessionId: string }) {
      const id = input.nativeSessionId === refs[BETA].nativeSessionKey ? BETA : ALPHA
      order.push(`register:${id}`); return { sessionRef: refs[id] }
    },
    async selectForSession(_operation: string, input: { sessionRef: SessionRef; profileId: string }) {
      const id = idOf(input.sessionRef)
      order.push(`select:${id}:${input.profileId}`)
      const gate = hold.get(id); if (gate) await gate
      if (failRegistrationFor.has(id)) throw new Error('登记失败：此 Harness 未确认会话身份')
      pending[id] = input.profileId
      return {}
    },
    async inspectSessionConfig(sessionRef: SessionRef) {
      const id = idOf(sessionRef)
      return { sessionRef, switchState: needsRecovery.has(id) ? 'needs_recovery' : 'settled',
        current: { profileId: current[id], revision: 1 }, pending: null,
        evidence: { receipt: receipt(id, current[id]), evidenceKind: 'controlled-fixture',
          journal: { operationId: receipt(id, current[id]).operationId, state: 'confirmed' } } }
    },
    async beginTurnApplication(_operation: string, sessionRef: SessionRef) {
      const id = idOf(sessionRef)
      order.push(`apply:${id}`)
      if (unknownFor.has(id)) { needsRecovery.add(id); throw Object.assign(new Error('配置切换结果未知'), { kind: 'Unknown' }) }
      if (failFor.has(id)) throw new Error('此 Harness 不支持该预设')
      if (pending[id] !== null) { current[id] = pending[id]!; pending[id] = null }
      return { turnId: `turn-${id}`, appliedSwitch: false, receipt: receipt(id, current[id]) }
    },
  } as unknown as ProfileServiceClient
  const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
    getSnapshot: () => ({ available: [], selectedConnectionId: `channel-${selected}`,
      agent: { connection: { harnessId: 'pi' } }, draft: { active: false, canSend: true } }),
    subscribe: () => () => undefined,
    async prepareSubmission() { return ownerOf(selected) },
  } })
  const pickerProps = (id: string): ProfilePickerProps => {
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
      .filter(item => item.id === 'ordessa.profile-chat.picker')
    const projected = view?.project?.({ slot: 'composer.toolbar' as const, location: locationOf(id),
      connection: { status: 'connected' as const } })
    if (!projected || projected.hidden) throw new Error('picker unexpectedly hidden')
    return projected.props as ProfilePickerProps
  }
  const gateway = { async submit() { order.push('prompt'); return { status: 'accepted' as const } } }
  return { scope, chat, glue, gateway, pickerProps, current,
    select: async (id: string) => { selected = id; await flush() },
    // the picker only acts for the pane the user is actually in
    pick: async (id: string, chosen: ProfileSelection) => {
      selected = id; await flush(); pickerProps(id).onSelect(chosen); await flush()
    },
    deferRegistration(id: string) { hold.set(id, new Promise<void>(resolve => { release = resolve })) },
    async releaseRegistration() { hold.clear(); release?.(); await flush(); await flush(); await flush() },
    // a send happens in the pane it belongs to; the native owner follows it
    send: async (id: string, submissionId: string) => {
      selected = id
      return chat.submit(snapshotFor(id, submissionId), gateway)
    },
    unknownFor, failFor, failRegistrationFor }
}

it('N2.3e alternating Profile picks register and apply only their own session', async () => {
  const order: string[] = []
  const f = twoSessions(order)
  try {
    await f.pick(ALPHA, ALPHA_ONE)
    await f.pick(BETA, BETA_TWO)
    expect(order).toEqual(['register:alpha', 'select:alpha:alpha-one',
      'register:beta', 'select:beta:beta-two'])
    expect(f.glue.store.peek(`session:${ALPHA}`)).toEqual(ALPHA_ONE)
    expect(f.glue.store.peek(`session:${BETA}`)).toEqual(BETA_TWO)

    order.length = 0
    expect(await f.send(ALPHA, 'send-a')).toEqual({ status: 'accepted' })
    expect(order).toEqual(['apply:alpha', 'prompt'])
    expect(f.current[ALPHA]).toBe('alpha-one')
    expect(f.current[BETA]).toBe('seed') // B's configuration is untouched

    expect(await f.send(BETA, 'send-b')).toEqual({ status: 'accepted' })
    expect(order).toEqual(['apply:alpha', 'prompt', 'apply:beta', 'prompt'])
    expect(f.current[BETA]).toBe('beta-two')
  } finally { f.scope.dispose() }
})

it('N2.3f a click registration that arrives after the pane switch only settles its own session', async () => {
  const order: string[] = []
  const f = twoSessions(order)
  try {
    await f.pick(ALPHA, ALPHA_ONE)
    f.deferRegistration(BETA)
    await f.select(BETA)
    f.pickerProps(BETA).onSelect(BETA_TWO)
    await flush()
    // the pane moved on before B's registration was acknowledged
    await f.select(ALPHA)
    await f.releaseRegistration()

    // A's own pick and label are exactly as the user left them
    expect(f.glue.store.peek(`session:${ALPHA}`)).toEqual(ALPHA_ONE)
    expect(f.pickerProps(ALPHA).label).toBe('ALPHA-ONE')
    expect(f.pickerProps(ALPHA).registrationError).toBeNull()
    // B's registration settled on B
    expect(f.glue.store.peek(`session:${BETA}`)).toEqual(BETA_TWO)
    expect(f.glue.store.isRegistered(`session:${BETA}`, BETA_TWO)).toBe(true)

    order.length = 0
    expect(await f.send(ALPHA, 'send-a')).toEqual({ status: 'accepted' })
    expect(order).toEqual(['apply:alpha', 'prompt'])
  } finally { f.scope.dispose() }
})

it('N2.4e an unknown application keeps the pick, blocks the send and never auto-reconciles', async () => {
  const order: string[] = []
  const f = twoSessions(order)
  try {
    await f.pick(ALPHA, ALPHA_ONE)
    await f.pick(BETA, BETA_TWO)
    f.unknownFor.add(ALPHA)
    order.length = 0
    // zero prompt: the user must verify before anything is sent
    expect(await f.send(ALPHA, 'send-a')).toEqual({ status: 'unknown' })
    expect(order).toEqual(['apply:alpha'])
    expect(order).not.toContain('prompt')
    expect(f.glue.store.peek(`session:${ALPHA}`)).toEqual(ALPHA_ONE)
    // the other session's pick is untouched by A's failure
    expect(f.glue.store.peek(`session:${BETA}`)).toEqual(BETA_TWO)

    f.unknownFor.delete(ALPHA)
    order.length = 0
    expect(await f.send(BETA, 'send-b')).toEqual({ status: 'accepted' })
    expect(order).toEqual(['apply:beta', 'prompt'])
    expect(f.current[BETA]).toBe('beta-two')
    // A was never reconciled or re-applied behind the user's back
    expect(order.filter(item => item.startsWith('apply:alpha'))).toEqual([])
    expect(f.glue.store.peek(`session:${ALPHA}`)).toEqual(ALPHA_ONE)
  } finally { f.scope.dispose() }
})

it('N2.4f a refused application keeps that session\'s choice and leaves the other session sendable', async () => {
  const order: string[] = []
  const f = twoSessions(order)
  try {
    await f.pick(ALPHA, ALPHA_ONE)
    await f.pick(BETA, BETA_TWO)
    f.failFor.add(BETA)
    order.length = 0
    expect(await f.send(BETA, 'send-b')).toMatchObject({ status: 'refused' })
    expect(order).toEqual(['apply:beta']) // zero prompt, and no second registration
    expect(f.glue.store.peek(`session:${BETA}`)).toEqual(BETA_TWO)
    expect(snapshotFor(BETA, 'send-b').text).toBe('text of beta')

    f.failFor.delete(BETA)
    order.length = 0
    expect(await f.send(ALPHA, 'send-a')).toEqual({ status: 'accepted' })
    expect(order).toEqual(['apply:alpha', 'prompt'])
    expect(f.current[ALPHA]).toBe('alpha-one')
  } finally { f.scope.dispose() }
})

it('N2.4g a failed click registration is surfaced for its own session only and survives re-projection', async () => {
  const order: string[] = []
  const f = twoSessions(order)
  try {
    await f.pick(ALPHA, ALPHA_ONE)
    f.failRegistrationFor.add(BETA)
    await f.pick(BETA, BETA_TWO)

    // B keeps its pick and shows its own failure…
    expect(f.glue.store.peek(`session:${BETA}`)).toEqual(BETA_TWO)
    expect(f.glue.store.isRegistered(`session:${BETA}`, BETA_TWO)).toBe(false)
    expect(f.pickerProps(BETA).registrationError).toContain('登记失败')
    // …and nothing about A changed
    expect(f.pickerProps(ALPHA).registrationError).toBeNull()
    expect(f.pickerProps(ALPHA).label).toBe('ALPHA-ONE')
    expect(f.glue.store.isRegistered(`session:${ALPHA}`, ALPHA_ONE)).toBe(true)

    // ordinary re-projection keeps that state stable (no flicker, no drop)
    for (let revision = 1; revision <= 4; revision += 1) {
      expect(f.pickerProps(BETA).registrationError).toContain('登记失败')
      expect(f.pickerProps(ALPHA).registrationError).toBeNull()
      expect(f.pickerProps(ALPHA).label).toBe('ALPHA-ONE')
    }

    // the unregistered pick is fail-closed for B, while A still sends normally
    order.length = 0
    expect(await f.send(BETA, 'send-b')).toMatchObject({ status: 'refused' })
    expect(order).not.toContain('prompt')
    order.length = 0
    expect(await f.send(ALPHA, 'send-a')).toEqual({ status: 'accepted' })
    expect(order).toEqual(['apply:alpha', 'prompt'])
    expect(f.pickerProps(BETA).registrationError).toContain('登记失败')
  } finally { f.scope.dispose() }
})

it('N2.3k a late acknowledgement of an earlier pick never upgrades the newer pick', async () => {
  const order: string[] = []
  const f = twoSessions(order)
  try {
    const key = `session:${ALPHA}`
    // two clicks in ONE session: the second is the user's current intent
    f.glue.store.select(key, ALPHA_ONE)
    f.glue.store.select(key, ALPHA_TWO)
    // the FIRST click's registration settles afterwards (a slow wire answer)
    f.glue.store.markRegistered(key, ALPHA_ONE)
    expect(f.glue.store.peek(key)).toBe(ALPHA_TWO)
    expect(f.glue.store.isRegistered(key, ALPHA_ONE)).toBe(false)
    // the stale answer must NOT have registered the newer pick either: until
    // ITS OWN click settles, the newest pick stays unregistered (fail-closed)
    expect(f.glue.store.isRegistered(key, ALPHA_TWO)).toBe(false)
    expect(f.glue.store.registrationError(key)).toBeNull() // no error invented either

    // when the newer pick's own registration lands, it — and only it — is applied
    f.glue.store.markRegistered(key, ALPHA_TWO)
    expect(f.glue.store.registeredPending(key)).toBe(ALPHA_TWO)
  } finally { f.scope.dispose() }
})
