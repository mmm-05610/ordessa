// @vitest-environment jsdom
// Intent fate (021 appendix §6c F2.2/F2.3, codex review F2): a bound fact
// alone is no longer a sufficient send permit. The newest model intent's
// handover fate — profile-overlay | independent | handover-failed, plus the
// undecided latch for an unreadable queue answer — gates the send.
//
// Red before the fix: the guard passed every bound session unconditionally and
// the client never learned a queue answer's intentRoute, so a handover failure
// folded into "independent" and the send went out on the old model.
import { describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  chatContribution,
  createChatContributions,
  type ChatContributionsService,
  type ChatLocation,
  type ChatSubmissionSnapshot,
} from '@extensions/ordessa.chat-api/contract.js'
import {
  MODEL_SELECTOR_ID,
  PROFILE_BINDING_CONTRIBUTION_ID,
  ModelSelectorKey,
  clientRegistryOf,
  registerModelSelector,
} from '../src/chat-api-entry'
import { CHOOSE_METHOD, SUBMIT_METHOD, createNextTurnClient } from '../src/next-turn-client'
import type { ModelProviderService } from '../contracts/index'

const LOCATION: ChatLocation = {
  kind: 'session', connectionId: 'conn-1', serverInstanceId: 'srv-1',
  sessionId: 's-9', harnessId: 'pi', contextRevision: 0,
}
const TARGET = { serverInstanceId: 'srv-1', harnessId: 'pi', acpSessionId: 's-9' }

function snapshot(target: ChatLocation = LOCATION): ChatSubmissionSnapshot {
  return {
    submissionId: 'sub-1', target, draftId: 'd-1', draftRevision: 1,
    text: 'hello', attachmentIds: [],
  }
}

function evidence() {
  return {
    operationId: 'op-native-1',
    nativeTarget: { owner: 'connection:s-9', canonicalUid: 'profile-session-1', generation: 3 },
    appliedRevision: 'applied-1',
    evidenceRef: 'pi-independent-query:1',
  }
}

function makeService(): ModelProviderService {
  return {} as ModelProviderService
}

function bindProfileFact(chat: ChatContributionsService, bound: {
  serverInstanceId: string; sessionId: string
} | null) {
  const registration = chatContribution({
    id: PROFILE_BINDING_CONTRIBUTION_ID,
    slot: 'composer.toolbar',
    order: 10,
    key: ModelSelectorKey,
    project: () => ({
      hidden: false as const,
      props: { label: null, groups: [], onSelect: () => undefined, boundNativeSession: bound },
    }),
  })
  chat.forScope(new OwnedResources()).addContribution(registration)
}

describe('intent fate bookkeeping (appendix §6c F2.2)', () => {
  it.each([
    ['profile-overlay', { kind: 'routed' }],
    ['independent', { kind: 'independent' }],
  ] as const)('a %s queue answer records that fate', async (route, fate) => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4, intentRoute: route })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(client.intentFate()).toEqual(fate)
  })

  it('a handover-failed queue answer carries the server mark and its reason', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4,
      intentRoute: 'handover-failed', intentReason: 'OVERLAY_WRITE_LOST' })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(client.intentFate()).toEqual({ kind: 'handover-failed', code: 'OVERLAY_WRITE_LOST' })
  })

  it('a queue answer without a valid intentRoute is undecided', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4 })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    const outcome = await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(outcome).toEqual({ state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' })
    expect(client.intentFate()).toEqual({ kind: 'undecided', code: 'OPERATION_UNKNOWN' })
  })

  it('an observed query resyncs the fate', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 4,
        intentRoute: 'handover-failed', intentReason: 'OVERLAY_WRITE_LOST' })
      .mockResolvedValueOnce({ desired: { providerConfigId: 'p-1', modelId: 'm1' },
        lastConfirmed: null, revision: 4, intentRoute: 'profile-overlay' })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(client.intentFate()).toEqual({ kind: 'handover-failed', code: 'OVERLAY_WRITE_LOST' })
    expect(await client.query()).toMatchObject({ state: 'observed' })
    expect(client.intentFate()).toEqual({ kind: 'routed' })
  })

  it('an evidenced ready consumes the intent and clears the fate', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
      .mockResolvedValueOnce({ outcome: 'ready', sequence: 4, application: evidence() })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(await client.submitTurn()).toMatchObject({ state: 'ready' })
    expect(client.intentFate()).toEqual({ kind: 'none' })
  })
})

describe('bound-branch send adjudication (appendix §6c F2.3)', () => {
  async function runWith(invoke: ReturnType<typeof vi.fn>, bound: {
    serverInstanceId: string; sessionId: string
  } | null, queued: boolean) {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    const wiring = { service: makeService(), invoke }
    registerModelSelector(chat, scope, wiring)
    if (queued) {
      const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
      await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
      clientRegistryOf(wiring).set(JSON.stringify(TARGET), { client, isCurrent: () => true })
    }
    bindProfileFact(chat, bound)
    const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
    const result = await chat.submit(snapshot(), gateway, () => true)
    return { result, gateway, invoke }
  }

  it('a handover-failed intent blocks the send with zero prompt and zero model submit', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4,
      intentRoute: 'handover-failed', intentReason: 'OVERLAY_WRITE_LOST' })
    const { result, gateway } = await runWith(invoke, { serverInstanceId: 'srv-1', sessionId: 's-9' }, true)
    expect(result).toMatchObject({ status: 'refused' })
    expect(gateway.submit).not.toHaveBeenCalled()
    expect(invoke.mock.calls.some(([method]) => method === SUBMIT_METHOD)).toBe(false)
  })

  it('a routed intent passes on a bound send without a model-side apply (single apply, M06)', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'profile-overlay' })
    const { result, gateway } = await runWith(invoke, { serverInstanceId: 'srv-1', sessionId: 's-9' }, true)
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalled()
    expect(invoke.mock.calls.some(([method]) => method === SUBMIT_METHOD)).toBe(false)
  })

  it('a routed intent whose binding vanished refuses instead of passing without evidence', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'profile-overlay' })
    const { result, gateway } = await runWith(invoke, null, true)
    expect(result).toMatchObject({ status: 'refused' })
    expect(gateway.submit).not.toHaveBeenCalled()
    expect(invoke.mock.calls.some(([method]) => method === SUBMIT_METHOD)).toBe(false)
  })

  it('an independent intent on an unbound session still submits through the gate', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
      .mockResolvedValueOnce({ outcome: 'ready', sequence: 4, application: evidence() })
    const { result, gateway } = await runWith(invoke, null, true)
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalled()
    expect(invoke).toHaveBeenCalledWith(SUBMIT_METHOD, expect.objectContaining({ target: TARGET }))
  })

  it('a newly bound independent intent blocks until backend handover is observed', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
      .mockResolvedValue({ desired: { providerConfigId: 'p-1', modelId: 'm1' },
        lastConfirmed: null, revision: 4, intentRoute: 'independent' })
    const { result, gateway } = await runWith(invoke, { serverInstanceId: 'srv-1', sessionId: 's-9' }, true)
    expect(result).toMatchObject({ status: 'refused' })
    expect(gateway.submit).not.toHaveBeenCalled()
    expect(invoke.mock.calls.some(([method]) => method === SUBMIT_METHOD)).toBe(false)
  })

  it('observes first-binding handover without performing a second apply', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
      .mockResolvedValue({ desired: { providerConfigId: 'p-1', modelId: 'm1' },
        lastConfirmed: null, revision: 4, intentRoute: 'profile-overlay' })
    const { result, gateway } = await runWith(invoke, { serverInstanceId: 'srv-1', sessionId: 's-9' }, true)
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalledTimes(1)
    expect(invoke.mock.calls.some(([method]) => method === SUBMIT_METHOD)).toBe(false)
  })

  it('a remounted bound selector checks failed handover instead of trusting absent cache', async () => {
    const invoke = vi.fn().mockResolvedValue({ desired: { providerConfigId: 'p-1', modelId: 'm1' },
      lastConfirmed: null, revision: 4, intentRoute: 'handover-failed' })
    const { result, gateway } = await runWith(invoke, { serverInstanceId: 'srv-1', sessionId: 's-9' }, false)
    expect(result).toMatchObject({ status: 'refused' })
    expect(gateway.submit).not.toHaveBeenCalled()
  })

  it('an undecided queue answer blocks the send until an observation settles it', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 4 }) // no intentRoute: undecided
      .mockResolvedValueOnce({ desired: null, lastConfirmed: null, revision: null, intentRoute: null })
      .mockResolvedValueOnce({ outcome: 'no-intent' }) // the settled gate check
    const chat = createChatContributions()
    const scope = new OwnedResources()
    const wiring = { service: makeService(), invoke }
    registerModelSelector(chat, scope, wiring)
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    clientRegistryOf(wiring).set(JSON.stringify(TARGET), { client, isCurrent: () => true })
    bindProfileFact(chat, null)
    const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
    expect(await chat.submit(snapshot(), gateway, () => true)).toMatchObject({ status: 'refused' })
    expect(gateway.submit).not.toHaveBeenCalled()
    // an observation that settles the queue (nothing queued) clears the latch
    await client.query()
    expect(await chat.submit({ ...snapshot(), submissionId: 'sub-2' }, gateway, () => true))
      .toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalled()
  })

  it('a queue refusal leaves no intent: the send passes (nothing to apply)', async () => {
    // the choose was refused (nothing queued); the gate's server check then
    // answers no-intent and the send passes
    const invoke = vi.fn(async (method: string) => {
      if (method === 'modelProvider.chooseForSession')
        throw { outcome: 'Refused', details: { internalCode: 'SELECTION_UNSUPPORTED' } }
      return { outcome: 'no-intent' }
    })
    const { result, gateway } = await runWith(invoke, null, true)
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalled()
  })

  it('the choose call itself is untouched by the fate adjudication', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(invoke).toHaveBeenCalledWith(CHOOSE_METHOD, expect.objectContaining({
      target: TARGET, choice: { providerConfigId: 'p-1', modelId: 'm1' },
    }))
    void MODEL_SELECTOR_ID
  })
})
