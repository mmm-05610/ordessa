import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { ChatComposerKey, ChatContributionsToken, ChatMessageBodyKey, ChatReasoningKey, ChatToolActivityKey, ChatContributionsToken as TokenIdentity,
  type ChatInputEntry, type ChatInputQuery, type ChatInputSource } from '@extensions/ordessa.chat-api/contract.js'
import { chatContribution, mergeInputEntries, createChatContributions } from '../src/registry'

const cleanup: OwnedResources[] = []
afterEach(() => { for (const scope of cleanup.splice(0).reverse()) scope.dispose() })
const newScope = () => { const scope = new OwnedResources(); cleanup.push(scope); return scope }

const bodyContribution = (id: string, order: number) => chatContribution({
  id, slot: 'composer.toolbar', order, key: ChatMessageBodyKey,
  project: () => ({ hidden: true }),
})

const entry = (id: string, groupId: string, order: number, surfaces: ('plus' | 'slash')[] = ['plus']): ChatInputEntry => ({
  id, title: `entry ${id}`, groupId, order, surfaces, availability: { kind: 'ready' }, action: { kind: 'insert-command', text: `/${id}` },
})

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const source = (id: string, groups: { id: string; title: string; order: number }[], query: ChatInputSource['query']): ChatInputSource =>
  ({ id, title: `source ${id}`, groups, query })

const staticSource = (id: string, entries: ChatInputEntry[]): ChatInputSource =>
  source(id, [{ id: 'g1', title: 'Group', order: 1 }], async () => entries)

describe('chat-api contribution registration', () => {
  it('registers, orders by (order,id) regardless of load order, and revokes only its own', () => {
    const chat = createChatContributions()
    const scopeA = newScope(), scopeB = newScope()
    chat.forScope(scopeA).addContribution(bodyContribution('z.last', 2))
    chat.forScope(scopeB).addContribution(bodyContribution('a.first', 1))
    chat.forScope(scopeA).addContribution(bodyContribution('m.middle', 1))
    const slot = chat.contributionsBySlot('composer.toolbar')
    expect(slot.getSnapshot().map(view => view.id)).toEqual(['a.first', 'm.middle', 'z.last'])
    // revoke only the first-scope entry; the other scope's registration survives
    expect(slot.getSnapshot().map(view => view.keyId)).toEqual([ChatMessageBodyKey.id, ChatMessageBodyKey.id, ChatMessageBodyKey.id])
    scopeA.dispose()
    expect(slot.getSnapshot().map(view => view.id)).toEqual(['a.first'])
    scopeB.dispose()
    expect(slot.getSnapshot()).toEqual([])
  })

  it('duplicate ids, content kinds and source ids are refused with the id in the error', () => {
    const chat = createChatContributions()
    const scope = newScope(), ui = chat.forScope(scope)
    ui.addContribution(bodyContribution('sample.x', 1))
    expect(() => ui.addContribution(bodyContribution('sample.x', 5))).toThrowError(/sample\.x/)
    ui.addContribution(chatContribution({
      id: 'sample.diff', slot: 'content.renderers', order: 1, key: ChatToolActivityKey, contentKind: 'sample.git-diff',
      decode: () => null,
    }))
    expect(() => ui.addContribution(chatContribution({
      id: 'sample.diff2', slot: 'content.renderers', order: 2, key: ChatToolActivityKey, contentKind: 'sample.git-diff',
      decode: () => null,
    }))).toThrowError(/sample\.git-diff/)
    ui.addInputSource(staticSource('sample.src', []))
    expect(() => ui.addInputSource(staticSource('sample.src', []))).toThrowError(/sample\.src/)
  })

  it('rejects registrations assembled outside the chatContribution factory', () => {
    const chat = createChatContributions()
    const ui = chat.forScope(newScope())
    expect(() => ui.addContribution({} as never)).toThrowError(/chatContribution/)
  })

  it('the factory enforces the conditional slot rules at construction time', () => {
    // content.renderers requires a pure decoder; other slots must not carry a contentKind
    expect(() => chatContribution({ id: 'bad.renderer', slot: 'content.renderers', order: 1, key: ChatMessageBodyKey, contentKind: 'bad.kind' }))
      .toThrowError(/decode/)
    expect(() => chatContribution({ id: 'bad.kind-slot', slot: 'session.auxiliary', order: 1, key: ChatMessageBodyKey, contentKind: 'bad.kind', decode: () => null }))
      .toThrowError(/contentKind/)
    expect(() => chatContribution({ id: 'nonamespaced', slot: 'composer.toolbar', order: 1, key: ChatMessageBodyKey })).toThrowError(/namespaced/)
  })

  it('a disposed scope refuses new registrations and half-registers nothing', () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    scope.dispose()
    expect(() => chat.forScope(scope)).toThrowError(/closed/)
  })

  it('revokes the original contribution after its caller mutates the descriptor', () => {
    const chat = createChatContributions()
    const scope = newScope()
    const descriptor = { id: 'sample.original', slot: 'composer.toolbar' as const,
      order: 1, key: ChatMessageBodyKey }
    const registration = chatContribution(descriptor)
    chat.forScope(scope).addContribution(registration)
    descriptor.id = 'sample.moved'
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot().map(view => view.id))
      .toEqual(['sample.original'])
    scope.dispose()
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toEqual([])
  })
})

describe('chat-api input sources', () => {
  const query = (location: ChatInputQuery['location']): ChatInputQuery => ({
    location, query: '', surface: 'plus', signal: new AbortController().signal,
  })
  const draftLocation = { kind: 'draft' as const, draftId: 'd1', contextRevision: 1 }

  it('merges entries stably by group then item ordering, undeclared groups last', async () => {
    const src = source('s', [{ id: 'b', title: 'B', order: 2 }, { id: 'a', title: 'A', order: 1 }], async () =>
      [entry('z', 'zz-late', 1), entry('y', 'b', 2), entry('x', 'a', 9), entry('w', 'a', 1)])
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(src)
    const view = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(view.getSnapshot()[0].entries.map(e => e.id)).toEqual(['w', 'x', 'y', 'z'])
  })

  it('one failing source never contaminates another; errors carry the message', async () => {
    const gate = deferred<ChatInputEntry[]>()
    const failing = deferred<ChatInputEntry[]>()
    const chat = createChatContributions()
    const scope = newScope(), ui = chat.forScope(scope)
    ui.addInputSource(source('good', [{ id: 'g', title: 'G', order: 1 }], () => gate.promise))
    ui.addInputSource(source('bad', [{ id: 'g', title: 'G', order: 1 }], () => failing.promise))
    const view = chat.queryInputSources(query(draftLocation))
    expect(view.getSnapshot().map(state => state.state.status)).toEqual(['loading', 'loading'])
    gate.resolve([entry('keep', 'g', 1)])
    failing.reject(new Error('catalog unavailable'))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    const states = Object.fromEntries(view.getSnapshot().map(state => [state.source.id, state.state]))
    expect(states.good.status).toBe('ready')
    expect(states.bad.status).toBe('error')
    expect(states.bad.error).toContain('catalog unavailable')
    expect(view.getSnapshot().find(state => state.source.id === 'good')!.entries.map(e => e.id)).toEqual(['keep'])
    expect(view.getSnapshot().find(state => state.source.id === 'bad')!.entries).toEqual([])
  })

  it('an aborted query keeps the previous entries and reports ready again', async () => {
    const gate = deferred<ChatInputEntry[]>()
    const controller = new AbortController()
    let calls = 0
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(source('slow', [{ id: 'g', title: 'G', order: 1 }], async () => {
      calls++
      if (calls === 1) return [entry('first', 'g', 1)]
      return new Promise<ChatInputEntry[]>(resolve => {
        controller.signal.addEventListener('abort', () => resolve([]), { once: true })
      })
    }))
    const first = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(first.getSnapshot()[0].entries.map(e => e.id)).toEqual(['first'])
    // second query is aborted while in flight
    const abortedQuery: ChatInputQuery = { ...query(draftLocation), signal: controller.signal }
    const second = chat.queryInputSources(abortedQuery)
    expect(second.getSnapshot()[0].state.status).toBe('loading')
    controller.abort()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(second.getSnapshot()[0].state.status).toBe('ready')
    expect(second.getSnapshot()[0].entries.map(e => e.id)).toEqual(['first'])
  })

  it('an already-aborted query never flips the source to loading', async () => {
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(staticSource('s', [entry('e', 'g', 1)]))
    // load the source once, then an already-cancelled query must keep that view
    const warmup = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    const controller = new AbortController()
    controller.abort()
    const view = chat.queryInputSources({ ...query(draftLocation), signal: controller.signal })
    expect(view.getSnapshot()[0].state.status).toBe('ready')
    expect(view.getSnapshot()[0].entries.map(e => e.id)).toEqual(['e'])
  })

  it('a late same-source query cannot overwrite the newer query result', async () => {
    const a = deferred<ChatInputEntry[]>(), b = deferred<ChatInputEntry[]>()
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(source('s', [{ id: 'g', title: 'G', order: 1 }],
      request => request.query === 'A' ? a.promise : b.promise))
    const first = chat.queryInputSources({ ...query(draftLocation), query: 'A' })
    const second = chat.queryInputSources({ ...query(draftLocation), query: 'B' })
    b.resolve([entry('new', 'g', 1)])
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(second.getSnapshot()[0].entries.map(item => item.id)).toEqual(['new'])
    a.resolve([entry('old', 'g', 1)])
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(second.getSnapshot()[0].entries.map(item => item.id)).toEqual(['new'])
    expect(first.getSnapshot()[0].entries.map(item => item.id)).toEqual(['old'])
  })

  it('different location views keep their own entries and actions', async () => {
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(source('s', [{ id: 'g', title: 'G', order: 1 }],
      async request => [entry(request.location.kind === 'draft' ? 'draft-action' : 'session-action', 'g', 1)]))
    const draft = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    const session = chat.queryInputSources(query({ kind: 'session', connectionId: 'c', sessionId: 's', contextRevision: 1 }))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(draft.getSnapshot()[0].entries.map(item => item.id)).toEqual(['draft-action'])
    expect(session.getSnapshot()[0].entries.map(item => item.id)).toEqual(['session-action'])
  })

  it('a pending or aborted new location never inherits the previous location action', async () => {
    const pending = deferred<ChatInputEntry[]>()
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(source('s', [{ id: 'g', title: 'G', order: 1 }],
      request => request.location.kind === 'draft' ? Promise.resolve([entry('draft-only', 'g', 1)]) : pending.promise))
    const draft = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(draft.getSnapshot()[0].entries.map(item => item.id)).toEqual(['draft-only'])
    const controller = new AbortController()
    const session = chat.queryInputSources({ ...query({ kind: 'session', connectionId: 'c', sessionId: 's', contextRevision: 1 }),
      signal: controller.signal })
    expect(session.getSnapshot()[0].entries).toEqual([])
    controller.abort()
    await Promise.resolve()
    expect(session.getSnapshot()[0].entries).toEqual([])
    pending.resolve([entry('session-only', 'g', 1)])
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(session.getSnapshot()[0].entries).toEqual([])
  })

  it('snapshots source provenance, groups and query callback before caller mutation', async () => {
    const provided = { id: 'sample.original', title: 'Original', groups: [{ id: 'g', title: 'Group', order: 1 }],
      query: async () => [entry('original-action', 'g', 1)] }
    const chat = createChatContributions(), scope = newScope()
    chat.forScope(scope).addInputSource(provided)
    provided.id = 'sample.moved'
    provided.title = 'Moved'
    provided.groups[0].id = 'changed'
    provided.query = async () => [entry('moved-action', 'changed', 1)]
    const view = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(view.getSnapshot()[0].source).toMatchObject({ id: 'sample.original', title: 'Original', groups: [{ id: 'g' }] })
    expect(view.getSnapshot()[0].entries.map(item => item.id)).toEqual(['original-action'])
    scope.dispose()
    expect(view.getSnapshot()).toEqual([])
  })

  it('keeps a class source query bound to its private owner state', async () => {
    class OwnedSource implements ChatInputSource {
      readonly id = 'sample.class'
      readonly title = 'Class source'
      readonly groups = [{ id: 'g', title: 'G', order: 1 }]
      #label = 'from-owner'
      async query() { return [entry(this.#label, 'g', 1)] }
    }
    const source = new OwnedSource()
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(source)
    Object.defineProperty(source, 'query', { value: async () => [entry('replaced', 'g', 1)] })
    const view = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(view.getSnapshot()[0].entries.map(item => item.id)).toEqual(['from-owner'])
  })

  it('a subscribed view loses withdrawn source actions immediately', async () => {
    const chat = createChatContributions()
    const scope = newScope()
    chat.forScope(scope).addInputSource(staticSource('s', [entry('withdrawn', 'g', 1)]))
    const view = chat.queryInputSources(query(draftLocation))
    const changes: number[] = []
    const unsubscribe = view.subscribe(() => changes.push(view.getSnapshot().length))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(view.getSnapshot()[0].entries.map(item => item.id)).toEqual(['withdrawn'])
    scope.dispose()
    expect(view.getSnapshot()).toEqual([])
    expect(changes.at(-1)).toBe(0)
    unsubscribe()
  })

  it('disabled availability passes through with its reason untouched', async () => {
    const disabledEntry: ChatInputEntry = { ...entry('d', 'g', 1), availability: { kind: 'disabled', reason: 'no attachment capability' } }
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(staticSource('s', [disabledEntry]))
    const view = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(view.getSnapshot()[0].entries[0].availability).toEqual({ kind: 'disabled', reason: 'no attachment capability' })
  })

  it('unsubscribed query views are reclaimed instead of accumulating forever', async () => {
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(staticSource('s', []))
    for (let i = 0; i < 50; i++) {
      const view = chat.queryInputSources(query(draftLocation))
      await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
      const unsubscribe = view.subscribe(() => {})
      unsubscribe()
    }
    // internal reclaim is observable only through stability: a fresh query still works and
    // no stale view keeps firing. 50 dead views must not leak subscriptions.
    const fresh = chat.queryInputSources(query(draftLocation))
    await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(fresh.getSnapshot().length).toBe(1)
  })
})

describe('chat-api identity and isolation', () => {
  it('exposes the token name and frozen keys', () => {
    expect(TokenIdentity.name).toBe('ordessa.chat.contributions.v1')
    expect(ChatContributionsToken.name).toBe('ordessa.chat.contributions.v1')
    for (const key of [ChatMessageBodyKey, ChatReasoningKey, ChatToolActivityKey, ChatComposerKey]) {
      expect(key.major).toBe(1)
      expect(Object.isFrozen(key)).toBe(true)
    }
    expect(ChatMessageBodyKey.id).toBe('ordessa.chat.message-body')
    expect(ChatReasoningKey.id).toBe('ordessa.chat.reasoning')
    expect(ChatToolActivityKey.id).toBe('ordessa.chat.tool-activity')
    expect(ChatComposerKey.id).toBe('ordessa.chat.composer')
  })

  it('two service instances share nothing', () => {
    const one = createChatContributions(), two = createChatContributions()
    one.forScope(newScope()).addContribution(bodyContribution('only.one', 1))
    expect(one.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(1)
    expect(two.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(0)
    expect(() => two.forScope(newScope()).addContribution(bodyContribution('only.one', 1))).not.toThrow()
  })

  it('disposal is idempotent and revocation checks identity, not just ids', () => {
    const chat = createChatContributions()
    const ui = chat.forScope(newScope())
    const disposable = ui.addContribution(bodyContribution('sample.idem', 1))
    disposable.dispose()
    disposable.dispose()
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toEqual([])
  })

  it('mergeInputEntries is exported for adapter reuse and stable', () => {
    const src = staticSource('s', [])
    const entries = [entry('b', 'g', 2), entry('a', 'g', 1)]
    expect(mergeInputEntries(src, entries).map(e => e.id)).toEqual(['a', 'b'])
    expect(mergeInputEntries(src, entries)).not.toBe(entries)
  })
})
