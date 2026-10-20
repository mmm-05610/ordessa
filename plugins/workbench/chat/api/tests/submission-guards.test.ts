import { expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions } from '../src/registry'
import type { ChatSubmissionSnapshot } from '../src/contract'

const snapshot: ChatSubmissionSnapshot = { submissionId: 'submit-1', draftId: 'draft-1', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft-1', contextRevision: 1 }, text: 'keep this', attachmentIds: [] }

it('no guards preserves the existing gateway and forwards an immutable captured snapshot', async () => {
  const chat = createChatContributions()
  const submit = vi.fn(async (value: ChatSubmissionSnapshot) => {
    expect(Object.isFrozen(value)).toBe(true)
    expect(Object.isFrozen(value.target)).toBe(true)
    expect(value).toEqual(snapshot)
    return { status: 'accepted' as const }
  })
  expect(await chat.submit(snapshot, { submit })).toEqual({ status: 'accepted' })
  expect(submit).toHaveBeenCalledTimes(1)
})

it('prepares in deterministic order before sending, captures callbacks and revokes with scope', async () => {
  const chat = createChatContributions(), scope = new OwnedResources(), calls: string[] = []
  const guard = { id: 'profile.prepare', order: 10, prepare: async () => { calls.push('profile'); return { status: 'ready' as const } } }
  chat.forScope(scope).addSubmissionGuard(guard)
  guard.prepare = async () => { throw new Error('mutated after registration') }
  chat.forScope(scope).addSubmissionGuard({ id: 'other.prepare', order: 5,
    prepare: async () => { calls.push('other'); return { status: 'ready' } } })
  const gateway = { submit: async () => { calls.push('send'); return { status: 'accepted' as const } } }
  await chat.submit(snapshot, gateway)
  expect(calls).toEqual(['other', 'profile', 'send'])
  scope.dispose()
  await chat.submit(snapshot, gateway)
  expect(calls).toEqual(['other', 'profile', 'send', 'send'])
})

it.each(['refused', 'unknown', 'throws'] as const)('%s preparation never sends or edits the caller draft', async status => {
  const chat = createChatContributions(), scope = new OwnedResources()
  chat.forScope(scope).addSubmissionGuard({ id: 'profile.prepare', order: 1, prepare: async () => {
    if (status === 'throws') throw new Error('failed')
    return status === 'refused' ? { status, reason: 'not applied' } : { status }
  } })
  const submit = vi.fn()
  expect((await chat.submit(snapshot, { submit })).status).toBe(status === 'throws' ? 'unknown' : status)
  expect(submit).not.toHaveBeenCalled()
  expect(snapshot.text).toBe('keep this')
  scope.dispose()
})

it('a lost gateway acknowledgement is unknown and is never automatically resent', async () => {
  const chat = createChatContributions()
  const submit = vi.fn(async () => { throw new Error('reply lost after send') })
  expect(await chat.submit(snapshot, { submit })).toEqual({ status: 'unknown' })
  expect(submit).toHaveBeenCalledTimes(1)
  expect(snapshot.text).toBe('keep this')
})

it('scope unload or a new guard while preparing prevents a stale send', async () => {
  for (const unload of [true, false]) {
    const chat = createChatContributions(), scope = new OwnedResources()
    let finish!: () => void
    const wait = new Promise<void>(resolve => { finish = resolve })
    chat.forScope(scope).addSubmissionGuard({ id: 'profile.prepare', order: 1,
      prepare: async () => { await wait; return { status: 'ready' } } })
    const submit = vi.fn()
    const pending = chat.submit(snapshot, { submit })
    if (unload) scope.dispose()
    else chat.forScope(scope).addSubmissionGuard({ id: 'late.prepare', order: 2, prepare: async () => ({ status: 'ready' }) })
    finish()
    expect((await pending).status).toBe('refused')
    expect(submit).not.toHaveBeenCalled()
    scope.dispose()
  }
})

it('changed consumer target refuses before gateway; duplicate ids and closed scopes refuse', async () => {
  const chat = createChatContributions(), scope = new OwnedResources()
  const guard = { id: 'profile.prepare', order: 1, prepare: async () => ({ status: 'ready' as const }) }
  const scoped = chat.forScope(scope)
  scoped.addSubmissionGuard(guard)
  expect(() => scoped.addSubmissionGuard(guard)).toThrow('Duplicate')
  const submit = vi.fn()
  expect((await chat.submit(snapshot, { submit }, () => false)).status).toBe('refused')
  expect(submit).not.toHaveBeenCalled()
  scope.dispose()
  expect(() => scoped.addSubmissionGuard(guard)).toThrow('closed')
})
